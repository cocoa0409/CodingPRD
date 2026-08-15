from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
import errors
import middleware as mw
from response import success
from services import covenants, posture
from services.common import parse_dt, stamp_new, touch
from services.pagination import get_pagination, paginate
from services.serialize import policy as ser_policy
from services.validate import body_json, require_fields, req_enum, req_int

bp = Blueprint("insurance", __name__)

COVERAGE_TYPES = ("PROPERTY", "LIABILITY", "FLOOD")
FORCE_PLACED_PREMIUM_PCT = Decimal("0.02")
FORCE_PLACED_TERM_DAYS = 365


def _active_non_fp_covers(prop_id, coverage_type, moment):
    for p in db.insurance_policies.values():
        if (
            p["property_id"] == prop_id
            and p["coverage_type"] == coverage_type
            and p["status"] == "ACTIVE"
            and not p["force_placed"]
            and p["start_date_dt"] <= moment <= p["end_date_dt"]
        ):
            return True
    return False


@bp.post("/properties/<pid>/insurance-policies")
def create_policy(pid):
    actor = mw.authenticate()
    mw.authorize(actor, ["Borrower"])
    prop = db.properties.get(pid)
    if prop is None:
        raise errors.not_found("Property not found")
    mw.require_borrower_ownership(actor, "property", prop)
    loan = db.loans.get(prop["loan_id"])
    data = body_json()
    require_fields(data, ["coverage_type", "coverage_amount_cents", "start_date", "end_date"])
    ctype = req_enum(data, "coverage_type", COVERAGE_TYPES)
    amount = req_int(data, "coverage_amount_cents", gt=0)
    start = parse_dt(data.get("start_date"), "start_date")
    end = parse_dt(data.get("end_date"), "end_date")
    if end < start:
        raise errors.invalid_request("end_date must not precede start_date")
    # Overlap check (priority 20) before coverage-minimum fiscal check (priority 35).
    for p in db.insurance_policies.values():
        if (
            p["property_id"] == pid
            and p["coverage_type"] == ctype
            and p["status"] == "ACTIVE"
            and not p["force_placed"]
            and start <= p["end_date_dt"]
            and p["start_date_dt"] <= end
        ):
            raise errors.ApiError(
                errors.ERR_COVERAGE_WINDOW_OVERLAP,
                "Coverage window overlaps an ACTIVE policy of the same type", 409)
    if ctype == "PROPERTY" and amount < loan["current_balance_cents"]:
        raise errors.ApiError(
            errors.ERR_COVERAGE_BELOW_MINIMUM,
            "PROPERTY coverage must be at least the loan's current balance", 422)
    pol = {
        "id": db.new_id(),
        "property_id": pid,
        "coverage_type": ctype,
        "coverage_amount_cents": amount,
        "start_date": db.fmt_ts(start),
        "start_date_dt": start,
        "end_date": db.fmt_ts(end),
        "end_date_dt": end,
        "force_placed": False,
        "premium_advance_cents": 0,
        "status": "ACTIVE",
    }
    stamp_new(pol)
    db.insurance_policies[pol["id"]] = pol
    return success(ser_policy(pol), status=201)


@bp.get("/properties/<pid>/insurance-policies")
def list_policies(pid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer", "Borrower"])
    prop = db.properties.get(pid)
    if not mw.read_scope_allows(actor, "property", prop):
        raise errors.not_found("Property not found")
    limit, offset = get_pagination()
    items = [p for p in db.insurance_policies.values() if p["property_id"] == pid]
    ctype = request.args.get("coverage_type")
    status = request.args.get("status")
    if ctype is not None:
        items = [p for p in items if p["coverage_type"] == ctype]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    page, pg = paginate([ser_policy(p) for p in items], limit, offset)
    return success(page, pagination=pg, is_array=True)


@bp.post("/insurance-policies/<pid>/cancel")
def cancel_policy(pid):
    actor = mw.authenticate()
    mw.authorize(actor, ["Borrower", "SpecialServicer"])
    pol = db.insurance_policies.get(pid)
    if pol is None:
        raise errors.not_found("InsurancePolicy not found")
    if actor["role"] == "Borrower":
        mw.require_borrower_ownership(actor, "policy", pol)
    if pol["status"] != "ACTIVE":
        raise errors.invalid_state("Only an ACTIVE policy can be cancelled")
    if pol["force_placed"]:
        # Replacement must start on/before the force-placed policy's own start_date.
        replacement = False
        for p in db.insurance_policies.values():
            if (
                p["id"] != pol["id"]
                and p["property_id"] == pol["property_id"]
                and p["coverage_type"] == pol["coverage_type"]
                and p["status"] == "ACTIVE"
                and not p["force_placed"]
                and p["start_date_dt"] <= pol["start_date_dt"]
            ):
                replacement = True
                break
        if not replacement:
            raise errors.ApiError(
                errors.ERR_FORCE_PLACED_CANCEL_BLOCKED,
                "Force-placed policy cannot be cancelled without replacement coverage", 409)
    prop = db.properties.get(pol["property_id"])
    loan = db.loans.get(prop["loan_id"]) if prop else None
    was_force = pol["force_placed"]
    pol["status"] = "CANCELLED"
    touch(pol)
    if was_force and pol["premium_advance_cents"] > 0 and loan is not None:
        loan["current_balance_cents"] -= pol["premium_advance_cents"]
        loan["capitalized_advances_cents"] -= pol["premium_advance_cents"]
        touch(loan)
    if loan is not None:
        covenants.run_ltv_assessment(loan)
        clock = db.get_clock()
        if not was_force:
            covered = any(
                p["id"] != pol["id"]
                and p["property_id"] == pol["property_id"]
                and p["coverage_type"] == pol["coverage_type"]
                and p["status"] == "ACTIVE"
                and p["start_date_dt"] <= clock <= p["end_date_dt"]
                for p in db.insurance_policies.values()
            )
            if not covered:
                existing = any(
                    e["loan_id"] == loan["id"]
                    and e["criterion"] == "INSURANCE_LAPSE"
                    and e["status"] == "ACTIVE"
                    for e in db.watchlist_entries.values()
                )
                if not existing:
                    posture.create_watchlist_entry(
                        loan, "INSURANCE_LAPSE",
                        source_ref=f"insurance policy {pol['id']}")
        posture.reevaluate_servicing(loan)
    return success(ser_policy(pol))


@bp.post("/properties/<pid>/force-place-insurance")
def force_place(pid):
    actor = mw.authenticate()
    mw.authorize(actor, ["SpecialServicer"])
    prop = db.properties.get(pid)
    if prop is None:
        raise errors.not_found("Property not found")
    loan = db.loans.get(prop["loan_id"])
    data = body_json()
    require_fields(data, ["coverage_type"])
    ctype = req_enum(data, "coverage_type", COVERAGE_TYPES)
    clock = db.get_clock()
    if _active_non_fp_covers(pid, ctype, clock):
        raise errors.ApiError(
            errors.ERR_FORCE_PLACEMENT_NOT_NEEDED,
            "Active non-force-placed coverage of this type already exists", 409)
    # Pinned single-pass evaluation order (calculations.protective_advance_capitalization).
    balance_pre = loan["current_balance_cents"]
    premium = int(
        (Decimal(balance_pre) * FORCE_PLACED_PREMIUM_PCT).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP)
    )
    loan["current_balance_cents"] = balance_pre + premium
    loan["capitalized_advances_cents"] += premium
    touch(loan)
    pol = {
        "id": db.new_id(),
        "property_id": pid,
        "coverage_type": ctype,
        "coverage_amount_cents": balance_pre,
        "start_date": db.fmt_ts(clock),
        "start_date_dt": clock,
        "end_date": db.fmt_ts(clock + timedelta(days=FORCE_PLACED_TERM_DAYS)),
        "end_date_dt": clock + timedelta(days=FORCE_PLACED_TERM_DAYS),
        "force_placed": True,
        "premium_advance_cents": premium,
        "status": "ACTIVE",
    }
    stamp_new(pol)
    db.insurance_policies[pol["id"]] = pol
    covenants.run_ltv_assessment(loan)
    return success(ser_policy(pol), status=201)
