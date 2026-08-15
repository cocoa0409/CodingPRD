"""Retirement cases with segregation of duties (PRD 3.14, 2.8)."""
from flask import Blueprint, g, request

import domain
from envelope import ok, ok_list
from errors import ApiError, invalid_state, not_found
from http_util import RETIRE_REASONS, get_body, parse_pagination, require_roles, v_enum, v_int, v_str
from store import db, new_entity, now_iso, touch

bp_retirements = Blueprint("retirements", __name__)

ROLES = ("SystemAdmin", "LeaseAdmin", "FleetPlanner", "ComplianceOfficer")


def _load_case(case_id):
    r = db.retirements.get(case_id)
    if r is None:
        raise not_found("ERR_RETIREMENT_NOT_FOUND", f"Retirement case {case_id} not found")
    return r


@bp_retirements.route("/retirement-cases", methods=["POST"])
@require_roles("FleetPlanner")
def create_case():
    body = get_body()
    railcar_id = v_str(body, "railcar_id")
    reason = v_enum(body, "reason", RETIRE_REASONS)
    if railcar_id not in db.railcars:
        raise not_found("ERR_RAILCAR_NOT_FOUND", f"Railcar {railcar_id} not found")
    case = new_entity(
        {
            "railcar_id": railcar_id,
            "reason": reason,
            "proposer_user_id": g.user_id,
            "salvage_value_cents": None,
            "book_value_cents": None,
            "impairment_loss_cents": None,
            "reinvestment_credit_cents": None,
            "status": "PROPOSED",
        }
    )
    db.retirements[case["id"]] = case
    return ok(domain.serialize_retirement(case), status=201)


@bp_retirements.route("/retirement-cases", methods=["GET"])
@require_roles(*ROLES)
def list_cases():
    limit, offset = parse_pagination()
    items = sorted(db.retirements.values(), key=lambda r: (r["created_at"], r["_created_seq"]))
    railcar_id = request.args.get("railcar_id")
    status = request.args.get("status")
    if railcar_id is not None:
        items = [r for r in items if r["railcar_id"] == railcar_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([domain.serialize_retirement(r) for r in page], limit, offset, total)


@bp_retirements.route("/retirement-cases/<case_id>", methods=["GET"])
@require_roles(*ROLES)
def get_case(case_id):
    return ok(domain.serialize_retirement(_load_case(case_id)))


@bp_retirements.route("/retirement-cases/<case_id>/appraise", methods=["POST"])
@require_roles("FleetPlanner")
def appraise_case(case_id):
    case = _load_case(case_id)
    body = get_body()
    salvage = v_int(body, "salvage_value_cents", min=0)
    book = v_int(body, "book_value_cents", min=0)
    if case["status"] != "PROPOSED":
        raise invalid_state(f"Retirement case in status {case['status']} cannot be appraised")
    case["salvage_value_cents"] = salvage
    case["book_value_cents"] = book
    case["impairment_loss_cents"] = max(0, book - salvage)
    case["reinvestment_credit_cents"] = salvage
    case["status"] = "APPRAISED"
    touch(case)
    return ok(domain.serialize_retirement(case))


@bp_retirements.route("/retirement-cases/<case_id>/approve", methods=["POST"])
@require_roles("ComplianceOfficer")
def approve_case(case_id):
    case = _load_case(case_id)
    # priority 3: segregation of duties — approver must differ from proposer
    if g.user_id == case["proposer_user_id"]:
        raise ApiError(
            "ERR_SOD_VIOLATION", 403,
            "Retirement approver must differ from the case proposer",
        )
    if case["status"] != "APPRAISED":
        raise invalid_state(f"Retirement case in status {case['status']} cannot be approved")
    car = db.railcars.get(case["railcar_id"])
    if car is None or car["status"] != "AVAILABLE":
        raise ApiError(
            "ERR_RETIREMENT_BLOCKED", 409,
            "Retirement approval requires the railcar to be AVAILABLE",
        )
    case["status"] = "APPROVED"
    touch(case)
    car["status"] = "RETIREMENT_PENDING"
    touch(car)
    return ok(domain.serialize_retirement(case))


@bp_retirements.route("/retirement-cases/<case_id>/execute", methods=["POST"])
@require_roles("FleetPlanner")
def execute_case(case_id):
    case = _load_case(case_id)
    if case["status"] != "APPROVED":
        raise invalid_state(f"Retirement case in status {case['status']} cannot be executed")
    year = db.clock_dt.year
    pool = next((p for p in db.pools.values() if p["fiscal_year"] == year), None)
    if pool is None:
        raise not_found(
            "ERR_POOL_NOT_FOUND",
            f"No capital pool exists for fiscal year {year}",
        )
    car = db.railcars.get(case["railcar_id"])
    if car is not None:
        car["status"] = "RETIRED"
        car["retired_at"] = now_iso()
        touch(car)
    pool["replenishment_cents"] += case["reinvestment_credit_cents"] or 0
    domain.recompute_pool(pool)
    touch(pool)
    case["status"] = "EXECUTED"
    touch(case)
    return ok(domain.serialize_retirement(case))


@bp_retirements.route("/retirement-cases/<case_id>/cancel", methods=["POST"])
@require_roles("FleetPlanner")
def cancel_case(case_id):
    case = _load_case(case_id)
    if case["status"] not in ("PROPOSED", "APPRAISED", "APPROVED"):
        raise invalid_state(f"Retirement case in status {case['status']} cannot be cancelled")
    if case["status"] == "APPROVED":
        # compensation: release the car from RETIREMENT_PENDING
        car = db.railcars.get(case["railcar_id"])
        if car is not None and car["status"] == "RETIREMENT_PENDING":
            car["status"] = "AVAILABLE"
            touch(car)
    case["status"] = "CANCELLED"
    touch(case)
    return ok(domain.serialize_retirement(case))
