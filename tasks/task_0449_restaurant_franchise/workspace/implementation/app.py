"""Restaurant Franchise Management & Royalty API — Flask entry point.

Implements the endpoint surface of PRD §4 / SCAFFOLD §1.5. Storage is in-memory
(db.py); the store is empty on every boot, so a fresh process carries no state.
Every behavior traces to a PRD sentence (citations inline).
"""
import os

from flask import Flask, request

import calculations as calc
import db
import errors
import helpers as h
from errors import ApiError
from middleware import get_identity, require_role, serialize
from response import object_response, array_response, error_response

app = Flask(__name__)

# Validation ordering (PRD §2.9): auth -> forbidden -> not_found ->
# not_resource_owner -> invalid_state -> business rules -> field-level.


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 400)


def auth(allowed_roles):
    """Resolve identity (401), enforce role (403); return (user_id, role)."""
    user_id, role = get_identity()
    require_role(role, allowed_roles)
    return user_id, role


def ok(record, status=200):
    return object_response(serialize(record), status=status)


READ_ROLES = ["Franchisor", "ComplianceAuditor", "Franchisee", "FinanceClerk"]


def _filter(records, field, value):
    """Filter a list by exact match on a field when the query value is given.

    period_index filters are integer-typed; others compare as the stored type.
    """
    if value is None:
        return records
    if field == "period_index":
        try:
            ival = int(value)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "period_index must be an integer")
        return [r for r in records if r.get(field) == ival]
    return [r for r in records if r.get(field) == value]


def _list(records):
    page, pagination = h.paginate(records)
    return array_response([serialize(r) for r in page], pagination)


# ===========================================================================
# Brand & clock
# ===========================================================================
@app.route("/franchise/brands", methods=["POST"])
def create_brand():
    """PRD §3.1 — create a Brand (Franchisor only)."""
    auth(["Franchisor"])
    body = h.get_body()
    h.require_fields(body, ["name"])
    with db.LOCK:
        brand = {
            "name": body["name"],
            "royalty_tier_1_rate": _rate(body, "royalty_tier_1_rate", 0.06),
            "royalty_tier_2_rate": _rate(body, "royalty_tier_2_rate", 0.05),
            "royalty_tier_3_rate": _rate(body, "royalty_tier_3_rate", 0.04),
            "ad_fund_rate": _rate(body, "ad_fund_rate", 0.02),
            "late_fee_monthly_rate": _rate(body, "late_fee_monthly_rate", 0.015),
            "current_period_index": 0,
            "current_utc": "2026-01-01T00:00:00Z",
        }
        db.init_common(brand)
        db.brands[brand["id"]] = brand
    return ok(brand, 201)


def _rate(body, name, default):
    if name not in body or body.get(name) is None:
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be a number" % name)
    if val < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be >= 0" % name)
    return val


@app.route("/franchise/brands/<brand_id>", methods=["GET"])
def get_brand(brand_id):
    auth(READ_ROLES)
    brand = h.get_or_404(db.brands, brand_id)
    return ok(brand)


@app.route("/franchise/brands/<brand_id>/close-period", methods=["POST"])
def close_period(brand_id):
    """PRD §3.11 — advance the brand clock and run period-close cascades."""
    auth(["Franchisor", "FinanceClerk"])
    with db.LOCK:
        brand = h.get_or_404(db.brands, brand_id)
        brand["current_period_index"] += 1
        cpi = brand["current_period_index"]

        # ISSUED statements now past due and not fully paid -> OVERDUE with
        # SIMPLE provisional late fee (PRD §3.11 / §3.9).
        for stmt in db.royalty_statements.values():
            if stmt["brand_id"] != brand_id:
                continue
            if (stmt["status"] == "ISSUED"
                    and cpi > stmt["due_period_index"]
                    and stmt["amount_paid_cents"] < stmt["total_due_cents"]):
                _apply_late_fee(brand, stmt, compound=False)
                stmt["status"] = "OVERDUE"
                db.touch(stmt)

        # Development schedules past deadline with opened_units < required ->
        # BEHIND (only from ON_TRACK) (PRD §3.4 / §3.11).
        for sched in db.development_schedules.values():
            if sched["brand_id"] != brand_id:
                continue
            if (sched["status"] == "ON_TRACK"
                    and cpi >= sched["deadline_period_index"]
                    and sched["opened_units"] < sched["required_units"]):
                sched["status"] = "BEHIND"
                db.touch(sched)

        # close-period increments Brand.version (PRD §3.11). db.touch bumps it.
        db.touch(brand)
    return ok(brand)


def _apply_late_fee(brand, stmt, compound):
    principal = stmt["royalty_cents"] + stmt["ad_fund_cents"]
    months_late = brand["current_period_index"] - stmt["due_period_index"]
    if months_late < 1:
        months_late = 1
    rate = brand["late_fee_monthly_rate"]
    if compound:
        stmt["late_fee_cents"] = calc.late_fee_compound(principal, rate, months_late)
    else:
        stmt["late_fee_cents"] = calc.late_fee_simple(principal, rate, months_late)
    stmt["total_due_cents"] = (stmt["royalty_cents"] + stmt["ad_fund_cents"]
                               + stmt["late_fee_cents"])


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    """PRD §2.5 — administrative clock capability; Franchisor only."""
    auth(["Franchisor"])
    body = h.get_body()
    h.require_fields(body, ["brand_id", "to_iso8601"])
    with db.LOCK:
        brand = h.require_fk(db.brands, body["brand_id"])
        brand["current_utc"] = body["to_iso8601"]
        db.touch(brand)
    return ok(brand)


# ===========================================================================
# Territory
# ===========================================================================
@app.route("/franchise/territories", methods=["POST"])
def create_territory():
    """PRD §3.1 — create a Territory; code unique per brand."""
    auth(["Franchisor"])
    body = h.get_body()
    h.require_fields(body, ["brand_id", "code", "name"])
    with db.LOCK:
        brand = h.require_fk(db.brands, body["brand_id"])
        code = str(body["code"]).upper()  # code uppercased (entity field desc)
        protected = body.get("protected", True)
        # code unique within brand -> ERR_TERRITORY_CONFLICT (PRD §3.1)
        for t in db.territories.values():
            if t["brand_id"] == brand["id"] and t["code"] == code:
                raise errors.err(errors.ERR_TERRITORY_CONFLICT,
                                 "Territory code already used in this brand")
        terr = {
            "brand_id": brand["id"],
            "code": code,
            "name": body["name"],
            "protected": bool(protected),
            "assigned_franchisee_id": None,
            "status": "AVAILABLE",
        }
        db.init_common(terr)
        db.territories[terr["id"]] = terr
    return ok(terr, 201)


@app.route("/franchise/territories/<territory_id>", methods=["GET"])
def get_territory(territory_id):
    auth(READ_ROLES)
    terr = h.get_or_404(db.territories, territory_id)
    return ok(terr)


@app.route("/franchise/territories", methods=["GET"])
def list_territories():
    auth(READ_ROLES)
    recs = list(db.territories.values())
    recs = _filter(recs, "brand_id", request.args.get("brand_id"))
    recs = _filter(recs, "assigned_franchisee_id", request.args.get("assigned_franchisee_id"))
    recs = _filter(recs, "status", request.args.get("status"))
    return _list(recs)


@app.route("/franchise/territories/<territory_id>/assign", methods=["POST"])
def assign_territory(territory_id):
    """PRD §3.1 — assign a Territory to a franchisee (grants exclusivity)."""
    auth(["Franchisor"])
    body = h.get_body()
    h.require_fields(body, ["franchisee_id"])
    with db.LOCK:
        terr = h.get_or_404(db.territories, territory_id)
        fr = h.require_fk(db.franchisees, body["franchisee_id"])
        # already ASSIGNED to another franchisee -> ERR_TERRITORY_CONFLICT (PRD §3.1)
        if terr["status"] == "ASSIGNED" and terr["assigned_franchisee_id"] != fr["id"]:
            raise errors.err(errors.ERR_TERRITORY_CONFLICT,
                             "Territory already assigned to another franchisee")
        terr["status"] = "ASSIGNED"
        terr["assigned_franchisee_id"] = fr["id"]
        db.touch(terr)
    return ok(terr)


# ===========================================================================
# Franchisee
# ===========================================================================
@app.route("/franchise/franchisees", methods=["POST"])
def create_franchisee():
    """PRD §3.2 — create a Franchisee (applicant)."""
    auth(["Franchisor"])
    body = h.get_body()
    h.require_fields(body, ["brand_id", "legal_name", "owner_user_id"])
    with db.LOCK:
        brand = h.require_fk(db.brands, body["brand_id"])
        fr = {
            "brand_id": brand["id"],
            "legal_name": body["legal_name"],
            "owner_user_id": body["owner_user_id"],
            "is_existing_operator": bool(body.get("is_existing_operator", False)),
            "status": "APPLICANT",
            "open_compliance_strikes": 0,
        }
        db.init_common(fr)
        db.franchisees[fr["id"]] = fr
    return ok(fr, 201)


@app.route("/franchise/franchisees/<franchisee_id>", methods=["GET"])
def get_franchisee(franchisee_id):
    auth(READ_ROLES)
    fr = h.get_or_404(db.franchisees, franchisee_id)
    return ok(fr)


@app.route("/franchise/franchisees", methods=["GET"])
def list_franchisees():
    auth(["Franchisor", "ComplianceAuditor", "FinanceClerk"])
    recs = list(db.franchisees.values())
    recs = _filter(recs, "brand_id", request.args.get("brand_id"))
    recs = _filter(recs, "status", request.args.get("status"))
    return _list(recs)


@app.route("/franchise/franchisees/<franchisee_id>/approve", methods=["POST"])
def approve_franchisee(franchisee_id):
    """PRD §3.2 — approve an applicant franchisee (APPLICANT -> APPROVED)."""
    auth(["Franchisor"])
    with db.LOCK:
        fr = h.get_or_404(db.franchisees, franchisee_id)
        if fr["status"] != "APPLICANT":
            raise errors.err(errors.ERR_INVALID_STATE, "Franchisee is not APPLICANT")
        fr["status"] = "APPROVED"
        db.touch(fr)
    return ok(fr)


@app.route("/franchise/franchisees/<franchisee_id>/terminate", methods=["POST"])
def terminate_franchisee(franchisee_id):
    """PRD §3.2 — terminate a franchisee from ACTIVE or DEFAULTED."""
    auth(["Franchisor"])
    with db.LOCK:
        fr = h.get_or_404(db.franchisees, franchisee_id)
        if fr["status"] not in ("ACTIVE", "DEFAULTED"):
            raise errors.err(errors.ERR_INVALID_STATE,
                             "Franchisee cannot be terminated from its current state")
        # blocked if any unit still OPEN -> ERR_FRANCHISEE_HAS_OPEN_UNITS (PRD §3.2)
        for u in h.franchisee_units(fr["id"]):
            if u["operational_status"] == "OPEN":
                raise errors.err(errors.ERR_FRANCHISEE_HAS_OPEN_UNITS,
                                 "Franchisee has units still OPEN")
        # blocked if any royalty statement of franchisee's units is OVERDUE
        # -> ERR_OUTSTANDING_OBLIGATIONS (PRD §3.2)
        if _franchisee_has_overdue(fr["id"]):
            raise errors.err(errors.ERR_OUTSTANDING_OBLIGATIONS,
                             "Franchisee has outstanding overdue obligations")
        fr["status"] = "TERMINATED"
        db.touch(fr)
        # cascade: release held territories (PRD §3.2)
        for t in db.territories.values():
            if t["assigned_franchisee_id"] == fr["id"]:
                t["assigned_franchisee_id"] = None
                t["status"] = "AVAILABLE"
                db.touch(t)
        # cascade: terminate EXECUTED/RENEWAL_PENDING agreements (PRD §3.2)
        for ag in db.agreements.values():
            if ag["franchisee_id"] == fr["id"] and ag["status"] in ("EXECUTED", "RENEWAL_PENDING"):
                ag["status"] = "TERMINATED"
                db.touch(ag)
    return ok(fr)


def _franchisee_has_overdue(franchisee_id):
    unit_ids = {u["id"] for u in h.franchisee_units(franchisee_id)}
    for stmt in db.royalty_statements.values():
        if stmt["unit_id"] in unit_ids and stmt["status"] == "OVERDUE":
            return True
    return False


def _check_default_threshold(fr):
    """If strikes reach 2 and franchisee ACTIVE -> DEFAULTED (PRD §3.5)."""
    if fr["open_compliance_strikes"] >= 2 and fr["status"] == "ACTIVE":
        fr["status"] = "DEFAULTED"
        db.touch(fr)


def _check_recover_threshold(fr):
    """If strikes drop below 2 and franchisee DEFAULTED -> ACTIVE (PRD §3.6)."""
    if fr["open_compliance_strikes"] < 2 and fr["status"] == "DEFAULTED":
        fr["status"] = "ACTIVE"
        db.touch(fr)


# ===========================================================================
# Franchise Agreement (FDD / renewal / transfer)
# ===========================================================================
@app.route("/franchise/agreements", methods=["POST"])
def create_agreement():
    """PRD §3.3 — create a draft FranchiseAgreement; brand_id derived from franchisee."""
    auth(["Franchisor"])
    body = h.get_body()
    h.require_fields(body, ["franchisee_id", "fdd_version", "term_end_period_index"])
    with db.LOCK:
        fr = h.require_fk(db.franchisees, body["franchisee_id"])
        term_end = _require_int(body, "term_end_period_index")
        ag = {
            "brand_id": fr["brand_id"],
            "franchisee_id": fr["id"],
            "fdd_version": body["fdd_version"],
            "term_end_period_index": term_end,
            "transfer_fee_rate": _rate(body, "transfer_fee_rate", 0.02),
            "successor_agreement_id": None,
            "status": "DRAFT",
        }
        db.init_common(ag)
        db.agreements[ag["id"]] = ag
    return ok(ag, 201)


def _require_int(body, name):
    val = body.get(name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be an integer" % name)
    return val


@app.route("/franchise/agreements/<agreement_id>", methods=["GET"])
def get_agreement(agreement_id):
    auth(READ_ROLES)
    ag = h.get_or_404(db.agreements, agreement_id)
    return ok(ag)


@app.route("/franchise/agreements", methods=["GET"])
def list_agreements():
    auth(READ_ROLES)
    recs = list(db.agreements.values())
    recs = _filter(recs, "brand_id", request.args.get("brand_id"))
    recs = _filter(recs, "franchisee_id", request.args.get("franchisee_id"))
    recs = _filter(recs, "successor_agreement_id", request.args.get("successor_agreement_id"))
    recs = _filter(recs, "status", request.args.get("status"))
    return _list(recs)


@app.route("/franchise/agreements/<agreement_id>/execute", methods=["POST"])
def execute_agreement(agreement_id):
    """PRD §3.3 — DRAFT -> EXECUTED; franchisee must be APPROVED or ACTIVE."""
    auth(["Franchisor"])
    with db.LOCK:
        ag = h.get_or_404(db.agreements, agreement_id)
        if ag["status"] != "DRAFT":
            raise errors.err(errors.ERR_INVALID_STATE, "Agreement is not DRAFT")
        fr = db.franchisees[ag["franchisee_id"]]
        if fr["status"] not in ("APPROVED", "ACTIVE"):
            raise errors.err(errors.ERR_FRANCHISEE_NOT_APPROVED,
                             "Owning franchisee is not APPROVED or ACTIVE")
        ag["status"] = "EXECUTED"
        db.touch(ag)
    return ok(ag)


@app.route("/franchise/agreements/<agreement_id>/begin-renewal", methods=["POST"])
def begin_renewal(agreement_id):
    """PRD §3.3 — EXECUTED -> RENEWAL_PENDING; renewal window must be open."""
    auth(["Franchisor"])
    with db.LOCK:
        ag = h.get_or_404(db.agreements, agreement_id)
        if ag["status"] != "EXECUTED":
            raise errors.err(errors.ERR_INVALID_STATE, "Agreement is not EXECUTED")
        brand = db.brands[ag["brand_id"]]
        # window open when current_period_index >= term_end_period_index - 1 (PRD §3.3)
        if brand["current_period_index"] < ag["term_end_period_index"] - 1:
            raise errors.err(errors.ERR_RENEWAL_WINDOW_CLOSED,
                             "Renewal window has not opened")
        ag["status"] = "RENEWAL_PENDING"
        db.touch(ag)
    return ok(ag)


@app.route("/franchise/agreements/<agreement_id>/renew", methods=["POST"])
def renew_agreement(agreement_id):
    """PRD §3.3 — RENEWAL_PENDING -> RENEWED; creates EXECUTED successor."""
    auth(["Franchisor"])
    body = h.get_body()
    with db.LOCK:
        ag = h.get_or_404(db.agreements, agreement_id)
        if ag["status"] != "RENEWAL_PENDING":
            raise errors.err(errors.ERR_INVALID_STATE, "Agreement is not RENEWAL_PENDING")
        fr = db.franchisees[ag["franchisee_id"]]
        # blocked while any of the franchisee's units is SUSPENDED -> ERR_COMPLIANCE_BLOCK
        for u in h.franchisee_units(fr["id"]):
            if u["compliance_status"] == "SUSPENDED":
                raise errors.err(errors.ERR_COMPLIANCE_BLOCK,
                                 "A unit of the franchisee is SUSPENDED")
        # new_fdd_version and new_term_end_period_index required (PRD §3.3)
        if body.get("new_fdd_version") is None or body.get("new_term_end_period_index") is None:
            raise errors.err(errors.ERR_INVALID_REQUEST,
                             "new_fdd_version and new_term_end_period_index required")
        new_term = body["new_term_end_period_index"]
        if isinstance(new_term, bool) or not isinstance(new_term, int):
            raise errors.err(errors.ERR_INVALID_REQUEST,
                             "new_term_end_period_index must be an integer")
        successor = {
            "brand_id": ag["brand_id"],
            "franchisee_id": fr["id"],
            "fdd_version": body["new_fdd_version"],
            "term_end_period_index": new_term,
            "transfer_fee_rate": ag["transfer_fee_rate"],
            "successor_agreement_id": None,
            "status": "EXECUTED",
        }
        db.init_common(successor)
        db.agreements[successor["id"]] = successor
        ag["status"] = "RENEWED"
        ag["successor_agreement_id"] = successor["id"]
        db.touch(ag)
    return ok(ag)


@app.route("/franchise/agreements/<agreement_id>/transfer", methods=["POST"])
def transfer_agreement(agreement_id):
    """PRD §3.3 / §3.9 — RENEWAL_PENDING -> TRANSFERRED; compute transfer fee,
    create successor under buyer, reassign units & territories."""
    auth(["Franchisor"])
    body = h.get_body()
    h.require_fields(body, ["buyer_franchisee_id"])
    with db.LOCK:
        ag = h.get_or_404(db.agreements, agreement_id)
        if ag["status"] != "RENEWAL_PENDING":
            raise errors.err(errors.ERR_INVALID_STATE, "Agreement is not RENEWAL_PENDING")
        seller = db.franchisees[ag["franchisee_id"]]
        buyer = h.require_fk(db.franchisees, body["buyer_franchisee_id"])
        if buyer["status"] not in ("APPROVED", "ACTIVE"):
            raise errors.err(errors.ERR_FRANCHISEE_NOT_APPROVED,
                             "Buyer franchisee is not APPROVED or ACTIVE")
        # no seller unit royalty statement OVERDUE -> ERR_OUTSTANDING_OBLIGATIONS
        if _franchisee_has_overdue(seller["id"]):
            raise errors.err(errors.ERR_OUTSTANDING_OBLIGATIONS,
                             "Seller has outstanding overdue obligations")
        brand = db.brands[ag["brand_id"]]
        transfer_fee = _compute_transfer_fee(brand, seller, ag, buyer)
        successor = {
            "brand_id": ag["brand_id"],
            "franchisee_id": buyer["id"],
            "fdd_version": ag["fdd_version"],
            "term_end_period_index": ag["term_end_period_index"],
            "transfer_fee_rate": ag["transfer_fee_rate"],
            "successor_agreement_id": None,
            "status": "EXECUTED",
        }
        db.init_common(successor)
        db.agreements[successor["id"]] = successor
        ag["status"] = "TRANSFERRED"
        ag["successor_agreement_id"] = successor["id"]
        db.touch(ag)
        # reassign each seller unit to buyer (PRD §3.3)
        for u in h.franchisee_units(seller["id"]):
            u["franchisee_id"] = buyer["id"]
            db.touch(u)
        # reassign each seller-held territory to buyer (PRD §3.3)
        for t in db.territories.values():
            if t["assigned_franchisee_id"] == seller["id"]:
                t["assigned_franchisee_id"] = buyer["id"]
                db.touch(t)
        # strikes are per-unit counts; recompute both franchisees after move
        h.recompute_open_compliance_strikes(seller)
        h.recompute_open_compliance_strikes(buyer)
        # transfer fee returned in response, not persisted on the agreement entity
        out = serialize(ag)
        out["transfer_fee_cents"] = transfer_fee
    return object_response(out, status=200)


def _compute_transfer_fee(brand, seller, ag, buyer):
    cpi = brand["current_period_index"]
    lo = cpi - 12
    hi = cpi - 1
    seller_unit_ids = {u["id"] for u in h.franchisee_units(seller["id"])}
    trailing = 0
    for stmt in db.royalty_statements.values():
        if stmt["unit_id"] in seller_unit_ids \
                and lo <= stmt["period_index"] <= hi \
                and stmt["status"] in ("ISSUED", "OVERDUE", "PAID", "WRITTEN_OFF"):
            trailing += stmt["net_sales_basis_cents"]
    return calc.transfer_fee_cents(trailing, ag["transfer_fee_rate"],
                                   buyer["is_existing_operator"])


@app.route("/franchise/agreements/<agreement_id>/decline-renewal", methods=["POST"])
def decline_renewal(agreement_id):
    """PRD §3.3 — RENEWAL_PENDING -> TERMINATED; release held territories."""
    auth(["Franchisor"])
    with db.LOCK:
        ag = h.get_or_404(db.agreements, agreement_id)
        if ag["status"] != "RENEWAL_PENDING":
            raise errors.err(errors.ERR_INVALID_STATE, "Agreement is not RENEWAL_PENDING")
        ag["status"] = "TERMINATED"
        db.touch(ag)
        for t in db.territories.values():
            if t["assigned_franchisee_id"] == ag["franchisee_id"]:
                t["assigned_franchisee_id"] = None
                t["status"] = "AVAILABLE"
                db.touch(t)
    return ok(ag)


# ===========================================================================
# Development Schedule
# ===========================================================================
@app.route("/franchise/development-schedules", methods=["POST"])
def create_dev_schedule():
    """PRD §3.4 — create a development schedule; required_units >= 1."""
    auth(["Franchisor"])
    body = h.get_body()
    h.require_fields(body, ["franchisee_id", "required_units", "deadline_period_index"])
    with db.LOCK:
        fr = h.require_fk(db.franchisees, body["franchisee_id"])
        required = body["required_units"]
        if isinstance(required, bool) or not isinstance(required, int) or required < 1:
            raise errors.err(errors.ERR_INVALID_REQUEST, "required_units must be >= 1")
        deadline = _require_int(body, "deadline_period_index")
        sched = {
            "brand_id": fr["brand_id"],
            "franchisee_id": fr["id"],
            "required_units": required,
            "deadline_period_index": deadline,
            "opened_units": 0,
            "status": "ON_TRACK",
        }
        db.init_common(sched)
        db.development_schedules[sched["id"]] = sched
    return ok(sched, 201)


@app.route("/franchise/development-schedules/<schedule_id>", methods=["GET"])
def get_dev_schedule(schedule_id):
    auth(READ_ROLES)
    sched = h.get_or_404(db.development_schedules, schedule_id)
    return ok(sched)


@app.route("/franchise/development-schedules", methods=["GET"])
def list_dev_schedules():
    auth(READ_ROLES)
    recs = list(db.development_schedules.values())
    recs = _filter(recs, "brand_id", request.args.get("brand_id"))
    recs = _filter(recs, "franchisee_id", request.args.get("franchisee_id"))
    recs = _filter(recs, "status", request.args.get("status"))
    return _list(recs)


@app.route("/franchise/development-schedules/<schedule_id>/declare-breach", methods=["POST"])
def declare_breach(schedule_id):
    """PRD §3.4 — BEHIND -> BREACHED after deadline strictly passed; may default."""
    auth(["Franchisor"])
    with db.LOCK:
        sched = h.get_or_404(db.development_schedules, schedule_id)
        if sched["status"] != "BEHIND":
            raise errors.err(errors.ERR_INVALID_STATE, "Schedule is not BEHIND")
        brand = db.brands[sched["brand_id"]]
        # current_period_index strictly > deadline (PRD §3.4)
        if brand["current_period_index"] <= sched["deadline_period_index"]:
            raise errors.err(errors.ERR_DEADLINE_NOT_PASSED, "Deadline has not passed")
        sched["status"] = "BREACHED"
        db.touch(sched)
        fr = db.franchisees[sched["franchisee_id"]]
        if fr["status"] == "ACTIVE":
            fr["status"] = "DEFAULTED"
            db.touch(fr)
    return ok(sched)


# ===========================================================================
# Unit
# ===========================================================================
@app.route("/franchise/units", methods=["POST"])
def create_unit():
    """PRD §3.5 — create a planned Unit (Franchisor or owning Franchisee)."""
    user_id, role = auth(["Franchisor", "Franchisee"])
    body = h.get_body()
    h.require_fields(body, ["franchisee_id", "territory_id", "address"])
    with db.LOCK:
        fr = h.require_fk(db.franchisees, body["franchisee_id"])
        terr = h.require_fk(db.territories, body["territory_id"])
        _ownership_check(role, user_id, fr)
        unit = {
            "brand_id": fr["brand_id"],
            "franchisee_id": fr["id"],
            "territory_id": terr["id"],
            "address": body["address"],
            "operational_status": "PLANNED",
            "compliance_status": "GOOD_STANDING",
            "latest_audit_score": None,
            "lifetime_net_sales_cents": 0,
        }
        db.init_common(unit)
        db.units[unit["id"]] = unit
    return ok(unit, 201)


def _ownership_check(role, user_id, franchisee):
    """Franchisee may only mutate resources of a franchisee whose owner_user_id
    == X-User-ID (PRD §2.1 / validations priority 4)."""
    if role == "Franchisee" and franchisee["owner_user_id"] != user_id:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER,
                         "Caller does not own this franchisee's resources")


@app.route("/franchise/units/<unit_id>", methods=["GET"])
def get_unit(unit_id):
    auth(READ_ROLES)
    unit = h.get_or_404(db.units, unit_id)
    return ok(unit)


@app.route("/franchise/units", methods=["GET"])
def list_units():
    auth(READ_ROLES)
    recs = list(db.units.values())
    recs = _filter(recs, "brand_id", request.args.get("brand_id"))
    recs = _filter(recs, "franchisee_id", request.args.get("franchisee_id"))
    recs = _filter(recs, "territory_id", request.args.get("territory_id"))
    recs = _filter(recs, "operational_status", request.args.get("operational_status"))
    recs = _filter(recs, "compliance_status", request.args.get("compliance_status"))
    return _list(recs)


@app.route("/franchise/units/<unit_id>/open", methods=["POST"])
def open_unit(unit_id):
    """PRD §3.5 — PLANNED -> OPEN; franchisee promotion + dev-schedule recompute."""
    user_id, role = auth(["Franchisee", "Franchisor"])
    with db.LOCK:
        unit = h.get_or_404(db.units, unit_id)
        fr = db.franchisees[unit["franchisee_id"]]
        _ownership_check(role, user_id, fr)
        # state validity first (PRD §2.9 ordering)
        if unit["operational_status"] != "PLANNED":
            raise errors.err(errors.ERR_INVALID_STATE, "Unit is not PLANNED")
        # franchisee APPROVED or ACTIVE (PRD §3.5)
        if fr["status"] not in ("APPROVED", "ACTIVE"):
            raise errors.err(errors.ERR_FRANCHISEE_NOT_APPROVED,
                             "Owning franchisee is not APPROVED or ACTIVE")
        # territory ASSIGNED to this unit's franchisee (PRD §3.5)
        terr = db.territories.get(unit["territory_id"])
        if terr is None or terr["status"] != "ASSIGNED" \
                or terr["assigned_franchisee_id"] != fr["id"]:
            raise errors.err(errors.ERR_TERRITORY_NOT_HELD,
                             "Unit's territory is not ASSIGNED to its franchisee")
        unit["operational_status"] = "OPEN"
        db.touch(unit)
        # side effect: promote APPROVED -> ACTIVE (PRD §3.5)
        if fr["status"] == "APPROVED":
            fr["status"] = "ACTIVE"
            db.touch(fr)
        # side effect: recompute dev schedule (PRD §3.5)
        h.recompute_development_schedule(fr["id"])
    return ok(unit)


@app.route("/franchise/units/<unit_id>/close", methods=["POST"])
def close_unit(unit_id):
    """PRD §3.5 — OPEN -> CLOSED; blocked by OVERDUE statement; dev-schedule recompute."""
    user_id, role = auth(["Franchisee", "Franchisor"])
    with db.LOCK:
        unit = h.get_or_404(db.units, unit_id)
        fr = db.franchisees[unit["franchisee_id"]]
        _ownership_check(role, user_id, fr)
        if unit["operational_status"] != "OPEN":
            raise errors.err(errors.ERR_INVALID_STATE, "Unit is not OPEN")
        # no royalty statement of this unit OVERDUE (PRD §3.5)
        for stmt in db.royalty_statements.values():
            if stmt["unit_id"] == unit["id"] and stmt["status"] == "OVERDUE":
                raise errors.err(errors.ERR_OUTSTANDING_OBLIGATIONS,
                                 "Unit has an overdue royalty statement")
        unit["operational_status"] = "CLOSED"
        db.touch(unit)
        h.recompute_development_schedule(fr["id"])
    return ok(unit)


@app.route("/franchise/units/<unit_id>/reinstate", methods=["POST"])
def reinstate_unit(unit_id):
    """PRD §3.6 — SUSPENDED -> PROBATION after a qualifying post-suspension audit."""
    auth(["Franchisor"])
    with db.LOCK:
        unit = h.get_or_404(db.units, unit_id)
        if unit["compliance_status"] != "SUSPENDED":
            raise errors.err(errors.ERR_INVALID_STATE, "Unit is not SUSPENDED")
        # require a FINALIZED audit, grade != FAIL, created after the suspending
        # audit -> else ERR_REMEDIATION_INCOMPLETE / ERR_COMPLIANCE_BLOCK (PRD §3.6).
        if not _has_post_suspension_remediation(unit):
            raise errors.err(errors.ERR_REMEDIATION_INCOMPLETE,
                             "No qualifying post-suspension remediation audit")
        unit["compliance_status"] = "PROBATION"
        db.touch(unit)
        # reverse the strike (PRD §3.6)
        fr = db.franchisees[unit["franchisee_id"]]
        if fr["open_compliance_strikes"] > 0:
            fr["open_compliance_strikes"] -= 1
            db.touch(fr)
        _check_recover_threshold(fr)
    return ok(unit)


def _has_post_suspension_remediation(unit):
    """A FINALIZED audit (grade != FAIL) created after the audit that caused
    the most recent suspension (PRD §3.6)."""
    unit_audits = [a for a in db.audits.values() if a["unit_id"] == unit["id"]]
    unit_audits.sort(key=lambda a: a["_seq"])
    # the suspending audit is the latest FINALIZED audit with grade FAIL
    suspend_seq = None
    for a in unit_audits:
        if a["status"] in ("FINALIZED", "REMEDIATION", "CLOSED") and a["grade"] == "FAIL":
            suspend_seq = a["_seq"]
    if suspend_seq is None:
        return False
    for a in unit_audits:
        if a["_seq"] > suspend_seq \
                and a["status"] in ("FINALIZED", "REMEDIATION", "CLOSED") \
                and a["grade"] is not None and a["grade"] != "FAIL":
            return True
    return False


# ===========================================================================
# Sales Reports (POS polling)
# ===========================================================================
@app.route("/franchise/sales-reports", methods=["POST"])
def create_sales_report():
    """PRD §3.8 — ingest a POS sales report for a unit's current period."""
    user_id, role = auth(["Franchisee", "Franchisor", "System"])
    body = h.get_body()
    h.require_fields(body, ["unit_id", "period_index", "gross_sales_cents"])
    with db.LOCK:
        unit = h.require_fk(db.units, body["unit_id"])
        fr = db.franchisees[unit["franchisee_id"]]
        _ownership_check(role, user_id, fr)
        period_index = _require_int(body, "period_index")
        gross = h.require_non_negative_int(body, "gross_sales_cents")
        discounts = h.require_non_negative_int(body, "discounts_cents",
                                               required=False, default=0)
        # discounts <= gross (PRD §3.8 / validation priority 17)
        if discounts > gross:
            raise errors.err(errors.ERR_INVALID_REQUEST,
                             "discounts_cents may not exceed gross_sales_cents")
        source = body.get("source", "POS_POLL")
        if source not in ("POS_POLL", "MANUAL"):
            raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid source")
        # period_index must equal brand.current_period_index (PRD §3.8)
        brand = db.brands[unit["brand_id"]]
        if period_index != brand["current_period_index"]:
            raise errors.err(errors.ERR_PERIOD_CLOSED,
                             "period_index does not match the brand's current period")
        sr = {
            "brand_id": unit["brand_id"],
            "unit_id": unit["id"],
            "period_index": period_index,
            "gross_sales_cents": gross,
            "discounts_cents": discounts,
            "net_sales_cents": calc.net_sales(gross, discounts),
            "source": source,
            "status": "POLLED",
        }
        db.init_common(sr)
        db.sales_reports[sr["id"]] = sr
    return ok(sr, 201)


@app.route("/franchise/sales-reports/<report_id>/accept", methods=["POST"])
def accept_sales_report(report_id):
    """PRD §3.8 — POLLED -> ACCEPTED; recompute unit lifetime_net_sales_cents."""
    auth(["Franchisor", "FinanceClerk"])
    with db.LOCK:
        sr = h.get_or_404(db.sales_reports, report_id)
        if sr["status"] != "POLLED":
            raise errors.err(errors.ERR_INVALID_STATE, "Sales report is not POLLED")
        sr["status"] = "ACCEPTED"
        db.touch(sr)
        unit = db.units[sr["unit_id"]]
        h.recompute_lifetime_net_sales(unit)
        db.touch(unit)
    return ok(sr)


@app.route("/franchise/sales-reports/<report_id>", methods=["GET"])
def get_sales_report(report_id):
    auth(READ_ROLES)
    sr = h.get_or_404(db.sales_reports, report_id)
    return ok(sr)


@app.route("/franchise/sales-reports", methods=["GET"])
def list_sales_reports():
    auth(READ_ROLES)
    recs = list(db.sales_reports.values())
    recs = _filter(recs, "brand_id", request.args.get("brand_id"))
    recs = _filter(recs, "unit_id", request.args.get("unit_id"))
    recs = _filter(recs, "period_index", request.args.get("period_index"))
    recs = _filter(recs, "status", request.args.get("status"))
    return _list(recs)


# ===========================================================================
# Royalty Statements
# ===========================================================================
@app.route("/franchise/royalty-statements", methods=["POST"])
def create_royalty_statement():
    """PRD §3.8 — create a draft statement; due_period_index = period_index + 1."""
    auth(["FinanceClerk", "Franchisor"])
    body = h.get_body()
    h.require_fields(body, ["unit_id", "period_index"])
    with db.LOCK:
        unit = h.require_fk(db.units, body["unit_id"])
        period_index = _require_int(body, "period_index")
        stmt = {
            "brand_id": unit["brand_id"],
            "unit_id": unit["id"],
            "period_index": period_index,
            "net_sales_basis_cents": 0,
            "royalty_cents": 0,
            "ad_fund_cents": 0,
            "late_fee_cents": 0,
            "total_due_cents": 0,
            "amount_paid_cents": 0,
            "due_period_index": period_index + 1,
            "status": "DRAFT",
        }
        db.init_common(stmt)
        db.royalty_statements[stmt["id"]] = stmt
    return ok(stmt, 201)


@app.route("/franchise/royalty-statements/<statement_id>", methods=["GET"])
def get_royalty_statement(statement_id):
    auth(READ_ROLES)
    stmt = h.get_or_404(db.royalty_statements, statement_id)
    return ok(stmt)


@app.route("/franchise/royalty-statements", methods=["GET"])
def list_royalty_statements():
    auth(READ_ROLES)
    recs = list(db.royalty_statements.values())
    recs = _filter(recs, "brand_id", request.args.get("brand_id"))
    recs = _filter(recs, "unit_id", request.args.get("unit_id"))
    recs = _filter(recs, "period_index", request.args.get("period_index"))
    recs = _filter(recs, "status", request.args.get("status"))
    return _list(recs)


@app.route("/franchise/royalty-statements/<statement_id>/issue", methods=["POST"])
def issue_statement(statement_id):
    """PRD §3.8 / §3.9 — DRAFT -> ISSUED; recompute basis, royalty, ad-fund, total."""
    auth(["FinanceClerk"])
    with db.LOCK:
        stmt = h.get_or_404(db.royalty_statements, statement_id)
        if stmt["status"] != "DRAFT":
            raise errors.err(errors.ERR_INVALID_STATE, "Statement is not DRAFT")
        # at least one ACCEPTED sales report for unit+period (PRD §3.8)
        accepted = [sr for sr in db.sales_reports.values()
                    if sr["unit_id"] == stmt["unit_id"]
                    and sr["period_index"] == stmt["period_index"]
                    and sr["status"] == "ACCEPTED"]
        if not accepted:
            raise errors.err(errors.ERR_NO_SALES_BASIS,
                             "No ACCEPTED sales report for this unit+period")
        basis = sum(sr["net_sales_cents"] for sr in accepted)
        brand = db.brands[stmt["brand_id"]]
        stmt["net_sales_basis_cents"] = basis
        stmt["royalty_cents"] = calc.royalty_cents(
            basis, brand["royalty_tier_1_rate"], brand["royalty_tier_2_rate"],
            brand["royalty_tier_3_rate"])
        stmt["ad_fund_cents"] = calc.ad_fund_cents(basis, brand["ad_fund_rate"])
        stmt["total_due_cents"] = (stmt["royalty_cents"] + stmt["ad_fund_cents"]
                                   + stmt["late_fee_cents"])
        stmt["status"] = "ISSUED"
        db.touch(stmt)
    return ok(stmt)


@app.route("/franchise/royalty-statements/<statement_id>/payments", methods=["POST"])
def record_payment(statement_id):
    """PRD §3.8 — payment permitted while ISSUED or OVERDUE; -> PAID when covered."""
    auth(["FinanceClerk"])
    body = h.get_body()
    with db.LOCK:
        stmt = h.get_or_404(db.royalty_statements, statement_id)
        if stmt["status"] not in ("ISSUED", "OVERDUE"):
            raise errors.err(errors.ERR_INVALID_STATE,
                             "Statement is not ISSUED or OVERDUE")
        amount = h.require_non_negative_int(body, "amount_cents")
        stmt["amount_paid_cents"] += amount
        if stmt["amount_paid_cents"] >= stmt["total_due_cents"]:
            stmt["status"] = "PAID"
        # else stays in prior status with partial payment recorded (PRD §3.8)
        db.touch(stmt)
    return ok(stmt)


@app.route("/franchise/royalty-statements/<statement_id>/write-off", methods=["POST"])
def write_off_statement(statement_id):
    """PRD §3.8 / §2.8 — OVERDUE -> WRITTEN_OFF; OCC on brand version; final
    compound late fee."""
    auth(["FinanceClerk"])
    body = h.get_body()
    with db.LOCK:
        stmt = h.get_or_404(db.royalty_statements, statement_id)
        if stmt["status"] != "OVERDUE":
            raise errors.err(errors.ERR_INVALID_STATE, "Statement is not OVERDUE")
        brand = db.brands[stmt["brand_id"]]
        _check_brand_occ(brand, body)
        # final compound late fee replaces the provisional value (PRD §3.9)
        _apply_late_fee(brand, stmt, compound=True)
        stmt["status"] = "WRITTEN_OFF"
        db.touch(stmt)
        # write-off increments Brand.version (SCAFFOLD §1.2 RoyaltyStatement)
        db.touch(brand)
    return ok(stmt)


def _check_brand_occ(brand, body):
    """expected_brand_version must equal brand.version (PRD §2.8). Mismatch ->
    ERR_STALE_VERSION (412). When omitted, the field is required for these
    OCC-guarded writes."""
    if "expected_brand_version" not in body or body.get("expected_brand_version") is None:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "expected_brand_version is required")
    if body["expected_brand_version"] != brand["version"]:
        raise errors.err(errors.ERR_STALE_VERSION,
                         "expected_brand_version is stale")


# ===========================================================================
# Vendors & approved-vendor compliance
# ===========================================================================
VENDOR_CATEGORIES = ("FOOD", "PACKAGING", "EQUIPMENT", "SERVICES")


@app.route("/franchise/vendors", methods=["POST"])
def create_vendor():
    """PRD §3.10 — create a vendor (Franchisor or ComplianceAuditor)."""
    auth(["Franchisor", "ComplianceAuditor"])
    body = h.get_body()
    h.require_fields(body, ["brand_id", "name", "category"])
    with db.LOCK:
        brand = h.require_fk(db.brands, body["brand_id"])
        category = body["category"]
        if category not in VENDOR_CATEGORIES:
            raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid vendor category")
        vendor = {
            "brand_id": brand["id"],
            "name": body["name"],
            "category": category,
            "approval_status": "PENDING",
        }
        db.init_common(vendor)
        db.vendors[vendor["id"]] = vendor
    return ok(vendor, 201)


@app.route("/franchise/vendors/<vendor_id>", methods=["GET"])
def get_vendor(vendor_id):
    auth(READ_ROLES)
    vendor = h.get_or_404(db.vendors, vendor_id)
    return ok(vendor)


@app.route("/franchise/vendors", methods=["GET"])
def list_vendors():
    auth(READ_ROLES)
    recs = list(db.vendors.values())
    recs = _filter(recs, "brand_id", request.args.get("brand_id"))
    recs = _filter(recs, "category", request.args.get("category"))
    recs = _filter(recs, "approval_status", request.args.get("approval_status"))
    return _list(recs)


@app.route("/franchise/vendors/<vendor_id>/approve", methods=["POST"])
def approve_vendor(vendor_id):
    """PRD §3.10 — PENDING -> APPROVED (ComplianceAuditor)."""
    auth(["ComplianceAuditor"])
    with db.LOCK:
        vendor = h.get_or_404(db.vendors, vendor_id)
        if vendor["approval_status"] != "PENDING":
            raise errors.err(errors.ERR_INVALID_STATE, "Vendor is not PENDING")
        vendor["approval_status"] = "APPROVED"
        db.touch(vendor)
    return ok(vendor)


@app.route("/franchise/vendors/<vendor_id>/revoke", methods=["POST"])
def revoke_vendor(vendor_id):
    """PRD §3.10 — approval -> REVOKED; cascade ACTIVE authorizations -> DISABLED."""
    auth(["ComplianceAuditor"])
    with db.LOCK:
        vendor = h.get_or_404(db.vendors, vendor_id)
        vendor["approval_status"] = "REVOKED"
        db.touch(vendor)
        for va in db.vendor_authorizations.values():
            if va["vendor_id"] == vendor["id"] and va["status"] == "ACTIVE":
                va["status"] = "DISABLED"
                db.touch(va)
    return ok(vendor)


@app.route("/franchise/vendor-authorizations", methods=["POST"])
def create_vendor_authorization():
    """PRD §3.10 — authorize a unit to source from an APPROVED vendor."""
    user_id, role = auth(["Franchisee", "Franchisor"])
    body = h.get_body()
    h.require_fields(body, ["unit_id", "vendor_id"])
    with db.LOCK:
        unit = h.require_fk(db.units, body["unit_id"])
        vendor = h.require_fk(db.vendors, body["vendor_id"])
        fr = db.franchisees[unit["franchisee_id"]]
        _ownership_check(role, user_id, fr)
        qp = h.require_non_negative_int(body, "qualifying_purchase_cents",
                                        required=False, default=0)
        # vendor must be APPROVED (PRD §3.10)
        if vendor["approval_status"] != "APPROVED":
            raise errors.err(errors.ERR_VENDOR_NOT_APPROVED, "Vendor is not APPROVED")
        va = {
            "brand_id": unit["brand_id"],
            "unit_id": unit["id"],
            "vendor_id": vendor["id"],
            "qualifying_purchase_cents": qp,
            "status": "ACTIVE",
        }
        db.init_common(va)
        db.vendor_authorizations[va["id"]] = va
    return ok(va, 201)


@app.route("/franchise/vendor-authorizations/<auth_id>", methods=["GET"])
def get_vendor_authorization(auth_id):
    auth(READ_ROLES)
    va = h.get_or_404(db.vendor_authorizations, auth_id)
    return ok(va)


@app.route("/franchise/vendor-authorizations", methods=["GET"])
def list_vendor_authorizations():
    auth(READ_ROLES)
    recs = list(db.vendor_authorizations.values())
    recs = _filter(recs, "brand_id", request.args.get("brand_id"))
    recs = _filter(recs, "unit_id", request.args.get("unit_id"))
    recs = _filter(recs, "vendor_id", request.args.get("vendor_id"))
    recs = _filter(recs, "status", request.args.get("status"))
    return _list(recs)


# ===========================================================================
# Brand Audits
# ===========================================================================
@app.route("/franchise/audits", methods=["POST"])
def create_audit():
    """PRD §3.7 — schedule a brand-standard audit; one active audit per unit."""
    auth(["ComplianceAuditor"])
    body = h.get_body()
    h.require_fields(body, ["unit_id"])
    with db.LOCK:
        unit = h.require_fk(db.units, body["unit_id"])
        # at most one active audit (SCHEDULED|IN_PROGRESS) per unit (PRD §3.7)
        for a in db.audits.values():
            if a["unit_id"] == unit["id"] and a["status"] in ("SCHEDULED", "IN_PROGRESS"):
                raise errors.err(errors.ERR_AUDIT_IN_PROGRESS,
                                 "Unit already has an active audit")
        audit = {
            "brand_id": unit["brand_id"],
            "unit_id": unit["id"],
            "food_safety_score": None,
            "cleanliness_score": None,
            "service_score": None,
            "brand_compliance_score": None,
            "weighted_score": None,
            "overall_score": None,
            "grade": None,
            "status": "SCHEDULED",
        }
        db.init_common(audit)
        db.audits[audit["id"]] = audit
    return ok(audit, 201)


@app.route("/franchise/audits/<audit_id>", methods=["GET"])
def get_audit(audit_id):
    auth(READ_ROLES)
    audit = h.get_or_404(db.audits, audit_id)
    return ok(audit)


@app.route("/franchise/audits", methods=["GET"])
def list_audits():
    auth(READ_ROLES)
    recs = list(db.audits.values())
    recs = _filter(recs, "brand_id", request.args.get("brand_id"))
    recs = _filter(recs, "unit_id", request.args.get("unit_id"))
    recs = _filter(recs, "status", request.args.get("status"))
    recs = _filter(recs, "grade", request.args.get("grade"))
    return _list(recs)


@app.route("/franchise/audits/<audit_id>/start", methods=["POST"])
def start_audit(audit_id):
    """PRD §3.7 — SCHEDULED -> IN_PROGRESS; target unit must be OPEN."""
    auth(["ComplianceAuditor"])
    with db.LOCK:
        audit = h.get_or_404(db.audits, audit_id)
        if audit["status"] != "SCHEDULED":
            raise errors.err(errors.ERR_INVALID_STATE, "Audit is not SCHEDULED")
        unit = db.units[audit["unit_id"]]
        if unit["operational_status"] != "OPEN":
            raise errors.err(errors.ERR_UNIT_NOT_OPEN, "Target unit is not OPEN")
        audit["status"] = "IN_PROGRESS"
        db.touch(audit)
    return ok(audit)


@app.route("/franchise/audits/<audit_id>/finalize", methods=["POST"])
def finalize_audit(audit_id):
    """PRD §3.7 — IN_PROGRESS -> FINALIZED; compute scores/grade; cascade compliance."""
    auth(["ComplianceAuditor"])
    body = h.get_body()
    with db.LOCK:
        audit = h.get_or_404(db.audits, audit_id)
        if audit["status"] != "IN_PROGRESS":
            raise errors.err(errors.ERR_INVALID_STATE, "Audit is not IN_PROGRESS")
        scores = {}
        for name in ("food_safety_score", "cleanliness_score",
                     "service_score", "brand_compliance_score"):
            val = body.get(name)
            if val is None or isinstance(val, bool) or not isinstance(val, int) \
                    or val < 0 or val > 100:
                raise errors.err(errors.ERR_INVALID_REQUEST,
                                 "%s must be an integer in 0..100" % name)
            scores[name] = val
        weighted, overall, grade = calc.audit_scores(
            scores["food_safety_score"], scores["cleanliness_score"],
            scores["service_score"], scores["brand_compliance_score"])
        audit.update(scores)
        # weighted_score / overall_score are 1-dp quantities; emit as floats
        audit["weighted_score"] = float(weighted)
        audit["overall_score"] = float(overall)
        audit["grade"] = grade
        audit["status"] = "FINALIZED"
        db.touch(audit)
        # write latest_audit_score and cascade compliance (PRD §3.7 / §3.5)
        unit = db.units[audit["unit_id"]]
        unit["latest_audit_score"] = float(overall)
        _cascade_audit_compliance(unit, grade)
        db.touch(unit)
    return ok(audit)


def _cascade_audit_compliance(unit, grade):
    """PRD §3.5 / §3.7 — compliance transitions on finalize."""
    fr = db.franchisees[unit["franchisee_id"]]
    if grade == "CONDITIONAL" and unit["compliance_status"] == "GOOD_STANDING":
        unit["compliance_status"] = "PROBATION"
    elif grade == "FAIL" and unit["compliance_status"] in ("GOOD_STANDING", "PROBATION"):
        unit["compliance_status"] = "SUSPENDED"
        fr["open_compliance_strikes"] += 1
        db.touch(fr)
        _check_default_threshold(fr)
    elif grade == "PASS" and unit["compliance_status"] == "PROBATION":
        unit["compliance_status"] = "GOOD_STANDING"


@app.route("/franchise/audits/<audit_id>/open-remediation", methods=["POST"])
def open_remediation(audit_id):
    """PRD §3.7 — FINALIZED -> REMEDIATION; grade must be CONDITIONAL or FAIL."""
    auth(["ComplianceAuditor"])
    with db.LOCK:
        audit = h.get_or_404(db.audits, audit_id)
        if audit["status"] != "FINALIZED":
            raise errors.err(errors.ERR_INVALID_STATE, "Audit is not FINALIZED")
        if audit["grade"] not in ("CONDITIONAL", "FAIL"):
            raise errors.err(errors.ERR_NO_REMEDIATION_NEEDED,
                             "A passing audit needs no remediation")
        audit["status"] = "REMEDIATION"
        db.touch(audit)
    return ok(audit)


@app.route("/franchise/audits/<audit_id>/close", methods=["POST"])
def close_audit(audit_id):
    """PRD §3.7 — FINALIZED(PASS) -> CLOSED directly, or REMEDIATION -> CLOSED
    once a later non-FAIL finalized audit exists for the unit."""
    auth(["ComplianceAuditor"])
    with db.LOCK:
        audit = h.get_or_404(db.audits, audit_id)
        if audit["status"] == "FINALIZED":
            # only PASS may close directly (PRD §3.7)
            if audit["grade"] != "PASS":
                raise errors.err(errors.ERR_INVALID_STATE,
                                 "Only PASS audits close directly")
            audit["status"] = "CLOSED"
            db.touch(audit)
        elif audit["status"] == "REMEDIATION":
            if not _has_later_non_fail_audit(audit):
                raise errors.err(errors.ERR_REMEDIATION_INCOMPLETE,
                                 "No later non-FAIL finalized audit for the unit")
            audit["status"] = "CLOSED"
            db.touch(audit)
        else:
            raise errors.err(errors.ERR_INVALID_STATE,
                             "Audit cannot be closed from its current state")
    return ok(audit)


def _has_later_non_fail_audit(audit):
    """A later FINALIZED audit for the same unit with grade != FAIL (PRD §3.7)."""
    for a in db.audits.values():
        if a["unit_id"] == audit["unit_id"] and a["_seq"] > audit["_seq"] \
                and a["status"] in ("FINALIZED", "REMEDIATION", "CLOSED") \
                and a["grade"] is not None and a["grade"] != "FAIL":
            return True
    return False


# ===========================================================================
# National Accounts / Rebates
# ===========================================================================
@app.route("/franchise/national-accounts", methods=["POST"])
def create_national_account():
    """PRD §3.9 — create a national-account rebate program."""
    auth(["Franchisor", "FinanceClerk"])
    body = h.get_body()
    h.require_fields(body, ["brand_id", "vendor_id", "name", "rebate_pool_cents"])
    with db.LOCK:
        brand = h.require_fk(db.brands, body["brand_id"])
        vendor = h.require_fk(db.vendors, body["vendor_id"])
        pool = h.require_non_negative_int(body, "rebate_pool_cents")
        min_q = h.require_non_negative_int(body, "min_qualifying_cents",
                                           required=False, default=1000000)
        na = {
            "brand_id": brand["id"],
            "vendor_id": vendor["id"],
            "name": body["name"],
            "rebate_pool_cents": pool,
            "min_qualifying_cents": min_q,
            "status": "OPEN",
        }
        db.init_common(na)
        db.national_accounts[na["id"]] = na
    return ok(na, 201)


@app.route("/franchise/national-accounts/<account_id>", methods=["GET"])
def get_national_account(account_id):
    auth(READ_ROLES)
    na = h.get_or_404(db.national_accounts, account_id)
    return ok(na)


@app.route("/franchise/national-accounts", methods=["GET"])
def list_national_accounts():
    auth(["Franchisor", "ComplianceAuditor", "FinanceClerk"])
    recs = list(db.national_accounts.values())
    recs = _filter(recs, "brand_id", request.args.get("brand_id"))
    recs = _filter(recs, "vendor_id", request.args.get("vendor_id"))
    recs = _filter(recs, "status", request.args.get("status"))
    return _list(recs)


@app.route("/franchise/national-accounts/<account_id>/distribute", methods=["POST"])
def distribute_rebate(account_id):
    """PRD §3.9 / §2.8 — OPEN -> DISTRIBUTED; OCC on brand version; waterfall
    allocation across qualifying ACTIVE vendor authorizations."""
    auth(["FinanceClerk"])
    body = h.get_body()
    with db.LOCK:
        na = h.get_or_404(db.national_accounts, account_id)
        if na["status"] != "OPEN":
            raise errors.err(errors.ERR_INVALID_STATE, "National account is not OPEN")
        brand = db.brands[na["brand_id"]]
        _check_brand_occ(brand, body)
        # eligible: this account's vendor, ACTIVE, qp >= min_qualifying (PRD §3.9)
        eligible = [va for va in db.vendor_authorizations.values()
                    if va["vendor_id"] == na["vendor_id"]
                    and va["status"] == "ACTIVE"
                    and va["qualifying_purchase_cents"] >= na["min_qualifying_cents"]]
        shares = calc.rebate_distribution(na["rebate_pool_cents"], eligible)
        na["status"] = "DISTRIBUTED"
        db.touch(na)
        # distribute increments Brand.version (SCAFFOLD §1.2.1)
        db.touch(brand)
        out = serialize(na)
        out["distribution"] = [
            {"vendor_authorization_id": vid, "share_cents": shares[vid]}
            for vid in shares
        ]
    return object_response(out, status=200)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
