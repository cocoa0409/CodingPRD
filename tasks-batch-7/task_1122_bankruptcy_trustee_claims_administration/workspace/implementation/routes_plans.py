"""Distribution plan endpoints: proposal (reserve/pool snapshot), confirmation
(OCC-guarded, runs the waterfall), vacatur; class allocations and dividends."""
from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_CASE_NOT_IN_DISTRIBUTION,
    ERR_PLAN_ALREADY_ACTIVE, ERR_STALE_CASE_VERSION, ERR_NO_FUNDS_TO_DISTRIBUTE,
    ERR_DIVIDEND_POSTED, ERR_INSUFFICIENT_ESTATE_FUNDS, ERR_INVALID_REQUEST,
)
from middleware import auth_context, require_roles, json_body, ALL_ROLES
from response import ok_object, paginate
from services_calc import (
    objected_reserve_by_class, approved_unpaid_fees,
    run_waterfall, maybe_enter_final_report,
)
from services_common import (
    new_entity, touch, bump_case, get_case, get_or_404, ensure_case_open,
    ensure_trustee_binding, ser_plan, ser_allocation, ser_dividend, sorted_rows,
)

bp = Blueprint("plans", __name__)


def _get_plan_and_case(plan_id):
    plan = get_or_404(db.plans, plan_id, "distribution plan")
    return plan, db.cases[plan["case_id"]]


@bp.route("/trustee/cases/<id>/plans", methods=["POST"])
def propose_plan(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    case = get_case(id)
    ensure_case_open(case)
    if case["status"] != "DISTRIBUTION":
        raise ApiError(ERR_CASE_NOT_IN_DISTRIBUTION, 409,
                       "A plan may be proposed only while the case is in DISTRIBUTION.")
    ensure_trustee_binding(case, uid)

    reserve = objected_reserve_by_class(id)
    total_reserve = sum(reserve.values())
    pool = case["estate_cash_on_hand_cents"] - total_reserve - approved_unpaid_fees(id)
    if pool <= 0:
        raise ApiError(ERR_NO_FUNDS_TO_DISTRIBUTE, 409, "Distributable pool is not positive.")

    from logical_clock import CLOCK
    sequence = sum(1 for p in db.plans.values() if p["case_id"] == id) + 1
    plan = new_entity({
        "case_id": id,
        "plan_sequence": sequence,
        "reserve_for_objected_cents": total_reserve,
        "distributable_cents": pool,
        "status": "PROPOSED",
        "proposed_at": CLOCK.now(),
    })
    db.plans[plan["id"]] = plan
    return ok_object(ser_plan(plan), status=201)


@bp.route("/trustee/cases/<id>/plans", methods=["GET"])
def list_case_plans(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    get_case(id)
    status = request.args.get("status")
    rows = [p for p in db.plans.values() if p["case_id"] == id]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    return paginate([ser_plan(p) for p in sorted_rows(rows)])


@bp.route("/trustee/plans/<id>", methods=["GET"])
def get_plan(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    return ok_object(ser_plan(get_or_404(db.plans, id, "distribution plan")))


@bp.route("/trustee/plans/<id>/confirm", methods=["POST"])
def confirm_plan(id):
    _, role = auth_context()
    require_roles(role, ("Court",))
    plan, case = _get_plan_and_case(id)
    ensure_case_open(case)
    if plan["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, 409, "Plan must be PROPOSED to confirm.")
    if case["status"] != "DISTRIBUTION":
        raise ApiError(ERR_CASE_NOT_IN_DISTRIBUTION, 409,
                       "Case must be in DISTRIBUTION to confirm a plan.")
    if any(p["case_id"] == case["id"] and p["id"] != id
           and p["status"] in ("CONFIRMED", "EXECUTING") for p in db.plans.values()):
        raise ApiError(ERR_PLAN_ALREADY_ACTIVE, 409,
                       "Another plan of this case is CONFIRMED or EXECUTING.")

    body = json_body()
    expected = body.get("expected_case_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "expected_case_version is required and must be an integer.")
    if expected != case["version"]:
        raise ApiError(ERR_STALE_CASE_VERSION, 412,
                       "expected_case_version does not match the case's current version.")

    run_waterfall(case, plan)  # raises ERR_NO_FUNDS_TO_DISTRIBUTE if pool <= 0
    plan["status"] = "CONFIRMED"
    touch(plan)
    bump_case(case)
    return ok_object(ser_plan(plan))


@bp.route("/trustee/plans/<id>/vacate", methods=["POST"])
def vacate_plan(id):
    _, role = auth_context()
    require_roles(role, ("Court",))
    plan, case = _get_plan_and_case(id)
    ensure_case_open(case)
    if plan["status"] != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a CONFIRMED plan may be vacated.")
    if any(d["plan_id"] == id and d["status"] == "POSTED" for d in db.dividends.values()):
        raise ApiError(ERR_DIVIDEND_POSTED, 409,
                       "A POSTED dividend makes vacatur impossible.")
    for div in db.dividends.values():
        if div["plan_id"] == id and div["status"] == "COMPUTED":
            div["status"] = "VOIDED"
            touch(div)
    plan["status"] = "VACATED"
    touch(plan)
    bump_case(case)
    return ok_object(ser_plan(plan))


@bp.route("/trustee/plans/<id>/allocations", methods=["GET"])
def plan_allocations(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    get_or_404(db.plans, id, "distribution plan")
    rows = [a for a in db.allocations.values() if a["plan_id"] == id]
    return paginate([ser_allocation(a) for a in sorted_rows(rows)])


@bp.route("/trustee/cases/<id>/allocations", methods=["GET"])
def case_allocations(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    get_case(id)
    rows = [a for a in db.allocations.values() if a["case_id"] == id]
    return paginate([ser_allocation(a) for a in sorted_rows(rows)])


@bp.route("/trustee/plans/<id>/dividends", methods=["GET"])
def plan_dividends(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    get_or_404(db.plans, id, "distribution plan")
    status = request.args.get("status")
    claim_id = request.args.get("claim_id")
    rows = [d for d in db.dividends.values() if d["plan_id"] == id]
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    if claim_id is not None:
        rows = [d for d in rows if d["claim_id"] == claim_id]
    return paginate([ser_dividend(d) for d in sorted_rows(rows)])


@bp.route("/trustee/dividends/<id>", methods=["GET"])
def get_dividend(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    return ok_object(ser_dividend(get_or_404(db.dividends, id, "dividend")))


def _check_plan_completion(plan, case):
    """EXECUTING -> FULLY_DISTRIBUTED when every dividend is POSTED or VOIDED;
    then, if no plan of the case remains active, the case enters FINAL_REPORT."""
    if plan["status"] != "EXECUTING":
        return
    plan_dividends = [d for d in db.dividends.values() if d["plan_id"] == plan["id"]]
    if plan_dividends and all(d["status"] in ("POSTED", "VOIDED") for d in plan_dividends):
        plan["status"] = "FULLY_DISTRIBUTED"
        touch(plan)
        maybe_enter_final_report(case)


@bp.route("/trustee/dividends/<id>/post", methods=["POST"])
def post_dividend(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    dividend = get_or_404(db.dividends, id, "dividend")
    plan = db.plans[dividend["plan_id"]]
    case = db.cases[plan["case_id"]]
    ensure_case_open(case)
    if dividend["status"] != "COMPUTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a COMPUTED dividend may be posted.")
    ensure_trustee_binding(case, uid)
    if case["estate_cash_on_hand_cents"] < dividend["amount_cents"]:
        raise ApiError(ERR_INSUFFICIENT_ESTATE_FUNDS, 409,
                       "Posting would drive estate cash negative.")

    dividend["status"] = "POSTED"
    case["estate_cash_on_hand_cents"] -= dividend["amount_cents"]
    alloc = db.allocations.get(dividend.get("_allocation_id"))
    if alloc is not None:
        alloc["paid_total_cents"] += dividend["amount_cents"]
        touch(alloc)
    if plan["status"] == "CONFIRMED":
        plan["status"] = "EXECUTING"
        touch(plan)
    touch(dividend)
    _check_plan_completion(plan, case)
    bump_case(case)
    return ok_object(ser_dividend(dividend))


@bp.route("/trustee/dividends/<id>/void", methods=["POST"])
def void_dividend(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    dividend = get_or_404(db.dividends, id, "dividend")
    plan = db.plans[dividend["plan_id"]]
    case = db.cases[plan["case_id"]]
    ensure_case_open(case)
    if dividend["status"] != "COMPUTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a COMPUTED dividend may be voided.")
    ensure_trustee_binding(case, uid)
    dividend["status"] = "VOIDED"  # amount stays in the estate as unclaimed funds
    touch(dividend)
    _check_plan_completion(plan, case)
    bump_case(case)
    return ok_object(ser_dividend(dividend))
