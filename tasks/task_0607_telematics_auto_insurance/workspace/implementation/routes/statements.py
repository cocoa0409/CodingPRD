"""Premium statement endpoints (PRD §3.6)."""
from flask import Blueprint, request

import calculations as calc
import db
from common import (
    find_or_404,
    get_body,
    new_record,
    pagination,
    paginate,
    require_int,
    require_str,
    serialize,
    touch,
)
from errors import ApiError
from middleware import auth_context, require_role
from response import array_response, object_response
from services import ledger

bp = Blueprint("statements", __name__)


@bp.post("/statements")
def create_statement():
    _, role = auth_context()
    require_role(role, ["UnderwritingOps"])
    body = get_body()
    policy_id = require_str(body, "policy_id")
    expected_version = require_int(body, "expected_policy_version")

    pol = find_or_404(db.policies, policy_id)

    # OCC runs before business logic (PRD §2.9, §3.12).
    if expected_version != pol["version"]:
        raise ApiError("ERR_STALE_VERSION")

    if pol["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE")
    if pol["billing_status"] != "PERIOD_OPEN":
        raise ApiError("ERR_PERIOD_NOT_OPEN")

    # No OPEN trips remain in the current period window (PRD §3.6).
    for t in db.trips.values():
        if t.get("policy_id") == pol["id"] and t["status"] == "OPEN":
            raise ApiError("ERR_OPEN_TRIPS_IN_PERIOD")

    plan = db.rate_plans[pol["rate_plan_id"]]
    period_trips = [
        t
        for t in db.trips.values()
        if t.get("policy_id") == pol["id"]
        and t["status"] == "ACCEPTED"
        and t["billed_period_index"] == pol["period_index"]
    ]
    billed_miles, overage_miles, base_charge, mileage_charge = calc.mileage_statement_charges(
        period_trips, pol, plan
    )

    rec = new_record(
        {
            "policy_id": pol["id"],
            "period_index": pol["period_index"],
            "billed_miles": billed_miles,
            "overage_miles": overage_miles,
            "base_charge_cents": base_charge,
            "mileage_charge_cents": mileage_charge,
            "applied_discount_cents": 0,
            "total_due_cents": base_charge + mileage_charge,
            "status": "DRAFT",
        }
    )
    db.statements[rec["id"]] = rec

    # PERIOD_OPEN -> PERIOD_CLOSING; policy version increments (PRD §3.6).
    pol["billing_status"] = "PERIOD_CLOSING"
    touch(pol)

    return object_response(serialize(rec), 201)


@bp.get("/statements")
def list_statements():
    _, role = auth_context()
    require_role(role, ["DriverUser", "UnderwritingOps"])
    limit, offset = pagination()
    items = list(db.statements.values())
    policy_id = request.args.get("policy_id")
    if policy_id is not None:
        items = [s for s in items if s["policy_id"] == policy_id]
    period_index = request.args.get("period_index")
    if period_index is not None:
        try:
            pi = int(period_index)
            items = [s for s in items if s["period_index"] == pi]
        except ValueError:
            items = []
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    data, total = paginate(items, limit, offset)
    return array_response(data, limit, offset, total)


@bp.get("/statements/<rid>")
def get_statement(rid):
    _, role = auth_context()
    require_role(role, ["DriverUser", "UnderwritingOps"])
    rec = find_or_404(db.statements, rid)
    return object_response(serialize(rec), 200)


@bp.post("/statements/<rid>/issue")
def issue_statement(rid):
    _, role = auth_context()
    require_role(role, ["UnderwritingOps"])
    stmt = find_or_404(db.statements, rid)
    if stmt["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    stmt["status"] = "ISSUED"
    touch(stmt)
    return object_response(serialize(stmt), 200)


@bp.post("/statements/<rid>/settle")
def settle_statement(rid):
    _, role = auth_context()
    require_role(role, ["UnderwritingOps"])
    stmt = find_or_404(db.statements, rid)
    pol = db.policies[stmt["policy_id"]]

    if pol["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE")
    if pol["billing_status"] != "PERIOD_CLOSING":
        raise ApiError("ERR_PERIOD_NOT_CLOSING")
    if stmt["status"] != "ISSUED":
        raise ApiError("ERR_STATEMENT_NOT_ISSUED")

    pre_discount_total = stmt["base_charge_cents"] + stmt["mileage_charge_cents"]
    bank = ledger.bank_for_driver(pol["driver_id"])
    applied, total_due = calc.discount_redemption(
        bank["available_cents"], pre_discount_total
    )

    # Guard: a draw must not exceed either bound (PRD §3.6).
    if applied > bank["available_cents"] or applied > pre_discount_total:
        raise ApiError("ERR_DISCOUNT_OVERDRAW")

    stmt["applied_discount_cents"] = applied
    stmt["total_due_cents"] = total_due
    stmt["status"] = "SETTLED"
    touch(stmt)

    if applied > 0:
        ledger.redeem(bank, applied, "STATEMENT_REDEEM")

    # PERIOD_CLOSING -> PERIOD_SETTLED (PRD §3.6).
    pol["billing_status"] = "PERIOD_SETTLED"
    touch(pol)

    return object_response(serialize(stmt), 200)
