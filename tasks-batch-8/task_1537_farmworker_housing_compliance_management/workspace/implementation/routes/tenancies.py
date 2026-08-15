"""Tenancies: create (OCC on unit), list, get, lifecycle, payments, statement."""

from flask import Blueprint

import clock
import db
from errors import err
from middleware import require_roles, get_auth
from response import success_object, success_list
from services import core
from services import calculations
from validate import (
    get_body, require_string, require_enum, require_int,
    parse_date_strict, parse_pagination, get_filter, sort_and_paginate,
)

bp = Blueprint("tenancies", __name__)

TENANCY_TARGETS = {"ACTIVE", "NOTICE", "TERMINATED", "CANCELLED"}


def _view(t):
    return {
        "id": t["id"],
        "household_id": t["household_id"],
        "unit_id": t["unit_id"],
        "move_in_date": t["move_in_date"],
        "move_out_date": t["move_out_date"],
        "status": t["status"],
        "notice_reason": t["notice_reason"],
        "balance_cents": t["balance_cents"],
        "rent_bucket_balance_cents": t["rent_bucket_balance_cents"],
        "utility_bucket_balance_cents": t["utility_bucket_balance_cents"],
        "damage_bucket_balance_cents": t["damage_bucket_balance_cents"],
        "is_delinquent": t["is_delinquent"],
        "oldest_unpaid_charge_date": t["oldest_unpaid_charge_date"],
        "subsidy_tier_percent": t["subsidy_tier_percent"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


@bp.route("/tenancies", methods=["POST"])
def create_tenancy():
    require_roles("IntakeCoordinator")
    body = get_body()
    household_id = require_string(body, "household_id")
    unit_id = require_string(body, "unit_id")
    move_in = parse_date_strict(body.get("move_in_date"), "move_in_date")
    if "expected_unit_version" not in body or body["expected_unit_version"] is None:
        raise err("ERR_INVALID_REQUEST", "expected_unit_version is required")
    expected_unit_version = body["expected_unit_version"]
    if isinstance(expected_unit_version, bool) or not isinstance(expected_unit_version, int):
        raise err("ERR_INVALID_REQUEST", "expected_unit_version must be an integer")

    # Existence, body FK left to right: household_id then unit_id.
    h = db.households.get(household_id)
    if h is None:
        raise err("ERR_HOUSEHOLD_NOT_FOUND")
    unit = db.units.get(unit_id)
    if unit is None:
        raise err("ERR_UNIT_NOT_FOUND")

    # OCC after existence, before business rules.
    if expected_unit_version != unit["version"]:
        raise err("ERR_STALE_VERSION")

    # Household must be ELIGIBLE.
    if h["eligibility_status"] != "ELIGIBLE":
        raise err("ERR_HOUSEHOLD_NOT_ELIGIBLE")

    now = db.now_ts()
    t = {
        "id": db.new_id(),
        "household_id": household_id,
        "unit_id": unit_id,
        "move_in_date": move_in.isoformat(),
        "move_out_date": None,
        "status": "PENDING_MOVE_IN",
        "notice_reason": None,
        "balance_cents": 0,
        "rent_bucket_balance_cents": 0,
        "utility_bucket_balance_cents": 0,
        "damage_bucket_balance_cents": 0,
        "is_delinquent": False,
        "oldest_unpaid_charge_date": None,
        "subsidy_tier_percent": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.tenancies[t["id"]] = t
    unit["version"] += 1
    unit["updated_at"] = now
    return success_object(_view(t), status=201)


@bp.route("/tenancies", methods=["GET"])
def list_tenancies():
    get_auth()
    limit, offset = parse_pagination()
    items = list(db.tenancies.values())
    hh_f = get_filter("household_id")
    unit_f = get_filter("unit_id")
    status_f = get_filter("status")
    if hh_f is not None:
        items = [t for t in items if t["household_id"] == hh_f]
    if unit_f is not None:
        items = [t for t in items if t["unit_id"] == unit_f]
    if status_f is not None:
        items = [t for t in items if t["status"] == status_f]
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([_view(t) for t in page], total, limit, offset)


@bp.route("/tenancies/<tid>", methods=["GET"])
def get_tenancy(tid):
    get_auth()
    t = db.tenancies.get(tid)
    if t is None:
        raise err("ERR_TENANCY_NOT_FOUND")
    # Keep clock-dependent computed fields fresh on read.
    t.update(core.compute_ledger(tid))
    return success_object(_view(t))


@bp.route("/tenancies/<tid>/statement", methods=["GET"])
def statement(tid):
    get_auth()
    t = db.tenancies.get(tid)
    if t is None:
        raise err("ERR_TENANCY_NOT_FOUND")
    # Statement is a computed read: derive buckets/delinquency live against the
    # current clock so aging reflects the present moment, and keep the stored
    # tenancy fields in sync.
    computed = core.compute_ledger(tid)
    t.update(computed)
    data = {
        "balance_cents": computed["balance_cents"],
        "rent_bucket_balance_cents": computed["rent_bucket_balance_cents"],
        "utility_bucket_balance_cents": computed["utility_bucket_balance_cents"],
        "damage_bucket_balance_cents": computed["damage_bucket_balance_cents"],
        "is_delinquent": computed["is_delinquent"],
        "oldest_unpaid_charge_date": computed["oldest_unpaid_charge_date"],
        "subsidy_tier_percent": t["subsidy_tier_percent"],
    }
    return success_object(data)


def _household_members_in_other_active_tenancy(household_id, exclude_tenancy_id):
    """True if any member's household has a different tenancy in ACTIVE/NOTICE.

    Per PRD: no member of the household may belong to another tenancy in
    ACTIVE or NOTICE. Since members belong to exactly one household, this
    reduces to: the household itself has another ACTIVE/NOTICE tenancy.
    """
    for t in db.tenancies.values():
        if t["id"] == exclude_tenancy_id:
            continue
        if t["household_id"] == household_id and t["status"] in ("ACTIVE", "NOTICE"):
            return True
    return False


@bp.route("/tenancies/<tid>", methods=["PUT"])
def drive_tenancy(tid):
    user_id, role = require_roles("IntakeCoordinator", "Resident")
    body = get_body()
    target = require_enum(body, "status", TENANCY_TARGETS)
    t = db.tenancies.get(tid)
    if t is None:
        raise err("ERR_TENANCY_NOT_FOUND")
    current = t["status"]
    now = db.now_ts()

    # Role/ownership gate (priority 2).
    if role == "Resident":
        # Resident may only give NOTICE on own tenancy.
        if not (current == "ACTIVE" and target == "NOTICE"):
            raise err("ERR_INSUFFICIENT_PERMISSIONS")
        if t["household_id"] != user_id:
            raise err("ERR_INSUFFICIENT_PERMISSIONS")

    # State machine from-state validity (priority 7).
    allowed = {
        "PENDING_MOVE_IN": {"ACTIVE", "CANCELLED"},
        "ACTIVE": {"NOTICE", "TERMINATED"},
        "NOTICE": {"ACTIVE", "TERMINATED"},
        "TERMINATED": set(),
        "CANCELLED": set(),
    }
    if target not in allowed.get(current, set()):
        raise err("ERR_INVALID_STATE", f"Cannot move tenancy from {current} to {target}")

    unit = db.units.get(t["unit_id"])
    household = db.households.get(t["household_id"])

    if target == "ACTIVE":
        # Activation or rescission. Both share site/posture/unit gates.
        site = db.sites.get(unit["site_id"]) if unit else None
        if site is None or site["status"] != "OPEN":
            raise err("ERR_SITE_NOT_OPEN")
        # Unit status gate (priority 9).
        if unit["status"] == "CONDEMNED":
            raise err("ERR_UNIT_CONDEMNED")
        if unit["status"] not in ("CERTIFIED", "OCCUPIED"):
            raise err("ERR_INVALID_STATE", f"Unit status {unit['status']} does not allow activation")
        # Posture gate (priority 10).
        if site["compliance_posture"] == "RESTRICTED":
            raise err("ERR_SITE_RESTRICTED")

        if current == "PENDING_MOVE_IN":
            move_in = clock.parse_date(t["move_in_date"])
            # Pest exclusion (priority 11).
            if core.unit_pest_exclusion_blocks_move_in(unit["id"], move_in):
                raise err("ERR_UNIT_UNDER_PEST_EXCLUSION")
            # Certification validity (priority 12) with lazy expiry side effect.
            if not core.unit_has_valid_certification(unit["id"]):
                raise err("ERR_NO_VALID_CERTIFICATION")
            # Household eligibility (priority 16).
            if household["eligibility_status"] != "ELIGIBLE":
                raise err("ERR_HOUSEHOLD_NOT_ELIGIBLE")
            # Member already housed (priority 16).
            if _household_members_in_other_active_tenancy(t["household_id"], t["id"]):
                raise err("ERR_MEMBER_ALREADY_HOUSED")
            # Occupancy (priority 13).
            core.recompute_unit_occupancy(unit["id"])
            projected = unit["current_occupancy"] + household["member_count"]
            if projected > unit["max_occupancy"]:
                raise err("ERR_OCCUPANCY_LIMIT_EXCEEDED")

            # ---- Activation side effects ----
            t["status"] = "ACTIVE"
            t["updated_at"] = now
            unit["current_occupancy"] = unit["current_occupancy"] + household["member_count"]
            if unit["status"] == "CERTIFIED":
                unit["status"] = "OCCUPIED"
            unit["updated_at"] = now

            # Post prorated RENT.
            rent_charge = calculations.prorated_rent_charge(unit, move_in)
            _post_entry(t["id"], "RENT", rent_charge, description="Prorated move-in rent")
            # Subsidy.
            tier, credit = calculations.subsidy_tier_and_credit(unit, household, rent_charge)
            t["subsidy_tier_percent"] = float(tier)
            if tier > 0:
                _post_entry(t["id"], "SUBSIDY_CREDIT", credit, description="Subsidy credit")
            core.recompute_tenancy_ledger(t["id"])
            core.recompute_site_posture(unit["site_id"])
            t["version"] += 1
            return success_object(_view(t))
        else:
            # Rescission NOTICE -> ACTIVE.
            if t["notice_reason"] == "CONDEMNATION":
                raise err("ERR_UNIT_CONDEMNED", "A condemnation notice cannot be rescinded")
            t["status"] = "ACTIVE"
            t["notice_reason"] = None
            t["updated_at"] = now
            t["version"] += 1
            return success_object(_view(t))

    if target == "NOTICE":
        # ACTIVE -> NOTICE (operator or resident).
        t["status"] = "NOTICE"
        t["notice_reason"] = "RESIDENT" if role == "Resident" else "OPERATOR"
        t["updated_at"] = now
        t["version"] += 1
        return success_object(_view(t))

    if target == "TERMINATED":
        move_out = body.get("move_out_date")
        if move_out is None:
            raise err("ERR_INVALID_REQUEST", "move_out_date is required on TERMINATED")
        move_out_d = parse_date_strict(move_out, "move_out_date")
        move_in_d = clock.parse_date(t["move_in_date"])
        if move_out_d < move_in_d:
            raise err("ERR_INVALID_REQUEST", "move_out_date must be >= move_in_date")
        t["status"] = "TERMINATED"
        t["move_out_date"] = move_out_d.isoformat()
        t["updated_at"] = now
        # Occupancy release.
        core.recompute_unit_occupancy(unit["id"])
        if unit["status"] == "OCCUPIED" and unit["current_occupancy"] == 0:
            unit["status"] = "CERTIFIED"
        unit["updated_at"] = now
        core.recompute_site_posture(unit["site_id"])
        t["version"] += 1
        return success_object(_view(t))

    if target == "CANCELLED":
        t["status"] = "CANCELLED"
        t["updated_at"] = now
        t["version"] += 1
        return success_object(_view(t))

    raise err("ERR_INVALID_STATE")


def _post_entry(tenancy_id, entry_type, amount_cents, description=None,
                usage_lines=None, source_work_order_id=None, payment_purpose=None):
    now = db.now_ts()
    e = {
        "id": db.new_id(),
        "tenancy_id": tenancy_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "usage_lines": usage_lines,
        "source_work_order_id": source_work_order_id,
        "description": description,
        "charge_date": clock.today_iso(),
        "status": "POSTED",
        "void_reason": None,
        "payment_purpose": payment_purpose,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.ledger_entries[e["id"]] = e
    return e


@bp.route("/tenancies/<tid>/payments", methods=["POST"])
def record_payment(tid):
    require_roles("IntakeCoordinator")
    body = get_body()
    gross = require_int(body, "gross_wages_cents", min_value=0)
    parse_date_strict(body.get("pay_period_start"), "pay_period_start")
    parse_date_strict(body.get("pay_period_end"), "pay_period_end")
    t = db.tenancies.get(tid)
    if t is None:
        raise err("ERR_TENANCY_NOT_FOUND")

    # Tenancy must be ACTIVE or NOTICE (priority 7.5).
    if t["status"] not in ("ACTIVE", "NOTICE"):
        raise err("ERR_INVALID_STATE", "Payments require tenancy in ACTIVE or NOTICE")

    household = db.households.get(t["household_id"])
    # Active authorization (priority 17).
    auth = None
    for a in db.deduction_authorizations.values():
        if a["household_id"] == t["household_id"] and a["status"] == "ACTIVE":
            auth = a
            break
    if auth is None:
        raise err("ERR_NO_ACTIVE_DEDUCTION_AUTHORIZATION")

    # Recompute buckets to current.
    core.recompute_tenancy_ledger(tid)
    covered = t["rent_bucket_balance_cents"]
    if auth["purpose"] == "RENT_AND_UTILITIES":
        covered += t["utility_bucket_balance_cents"]

    allowed = calculations.payroll_deduction_cap(gross, auth["cap_percent"], covered)
    if allowed <= 0:
        raise err("ERR_NOTHING_TO_COLLECT")

    entry = _post_entry(
        tid, "PAYMENT", allowed,
        description="Payroll deduction payment",
        payment_purpose=auth["purpose"],
    )
    core.recompute_tenancy_ledger(tid)
    t["version"] += 1
    t["updated_at"] = db.now_ts()
    return success_object(_view_entry(entry), status=201)


def _view_entry(e):
    return {
        "id": e["id"],
        "tenancy_id": e["tenancy_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "usage_lines": e["usage_lines"],
        "source_work_order_id": e["source_work_order_id"],
        "description": e["description"],
        "charge_date": e["charge_date"],
        "status": e["status"],
        "void_reason": e["void_reason"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }
