"""FundingRequest endpoints: submission, sponsor endorsement/counter, revise,
DEI approval with matching top-up, disbursement, reconciliation."""
from flask import Blueprint, request

from db import STORE
from errors import (
    ApiError, ERR_ALLOCATION_NOT_LOCKED, ERR_GROUP_NOT_ACTIVE,
    ERR_INSUFFICIENT_GROUP_BUDGET, ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION, ERR_LEADERSHIP_GAP, ERR_NOT_FOUND,
    ERR_NOT_GROUP_LEADER, ERR_PROGRAM_NOT_OPEN, ERR_SPONSOR_NOT_ACTIVE,
    ERR_SPONSOR_NOT_ASSIGNED, ERR_SPONSOR_SELF_ENDORSEMENT,
)
from middleware import (
    authenticate, body, opt_int, req_enum, req_int, req_str, sort_and_page,
)
from services import (
    active_term_of, available_cents, funding_json, matching_topup_award,
    new_entity, touch,
)
from util import ok_list, ok_object

bp = Blueprint("funding", __name__)

ALL_ROLES = ("DeiAdmin", "ExecutiveSponsor", "GroupLeader", "Employee")
FUNDING_CATEGORIES = ("EVENT", "TRAINING", "COMMUNITY_OUTREACH", "RECRUITING", "OTHER")


def get_funding(funding_id):
    f = STORE["funding_requests"].get(funding_id)
    if f is None:
        raise ApiError(ERR_NOT_FOUND, 404, "funding request not found")
    return f


@bp.post("/v1/funding-requests")
def create_funding():
    user_id, _ = authenticate(("GroupLeader",))
    data = body()
    group_id = req_str(data, "group_id")
    category = req_enum(data, "category", FUNDING_CATEGORIES)
    purpose = req_str(data, "purpose")
    requested_cents = req_int(data, "requested_cents", min_v=1)
    external_matching_cents = opt_int(data, "external_matching_cents", min_v=0, default=0)
    # 4 existence
    group = STORE["groups"].get(group_id)
    if group is None:
        raise ApiError(ERR_NOT_FOUND, 404, "group not found")
    # 5 state gates
    if group["status"] != "ACTIVE":
        raise ApiError(ERR_GROUP_NOT_ACTIVE, 409, "group is not ACTIVE")
    program = STORE["programs"].get(group["program_id"])
    if program is None or program["status"] not in ("OPEN", "ALLOCATION_LOCKED"):
        raise ApiError(ERR_PROGRAM_NOT_OPEN, 409, "program is not open")
    term = active_term_of(group_id)
    if term is None:
        raise ApiError(ERR_LEADERSHIP_GAP, 409, "group has no active leader")
    # ownership: caller must be the ACTIVE-term leader
    if term["leader_employee_id"] != user_id:
        raise ApiError(ERR_NOT_GROUP_LEADER, 403, "caller is not the group's leader")
    f = new_entity("funding_requests", {
        "group_id": group_id,
        "created_by_employee_id": user_id,
        "category": category,
        "purpose": purpose,
        "requested_cents": requested_cents,
        "external_matching_cents": external_matching_cents,
        "counter_amount_cents": None,
        "approved_cents": None,
        "disbursed_cents": None,
        "actual_spend_cents": None,
        "status": "SUBMITTED",
    })
    return ok_object(funding_json(f), 201)


@bp.get("/v1/funding-requests/<funding_id>")
def read_funding(funding_id):
    authenticate(ALL_ROLES)
    return ok_object(funding_json(get_funding(funding_id)))


@bp.get("/v1/funding-requests")
def list_funding():
    authenticate(ALL_ROLES)
    items = list(STORE["funding_requests"].values())
    for param, field in (("group_id", "group_id"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [f for f in items if f.get(field) == v]
    page, limit, offset, total = sort_and_page(items, funding_json)
    return ok_list(page, limit, offset, total)


@bp.post("/v1/funding-requests/<funding_id>/sponsor-decision")
def funding_sponsor_decision(funding_id):
    user_id, _ = authenticate(("ExecutiveSponsor",))
    data = body()
    decision = req_enum(data, "decision", ("ENDORSE", "COUNTER"))
    counter = opt_int(data, "counter_amount_cents")
    if decision == "COUNTER" and (counter is None or counter <= 0):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "counter_amount_cents is required and must be > 0 on COUNTER")
    f = get_funding(funding_id)
    if f["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "sponsor decision requires a SUBMITTED request")
    group = STORE["groups"].get(f["group_id"])
    sponsor = STORE["sponsors"].get(user_id)
    if sponsor is not None and sponsor["status"] != "ACTIVE":
        raise ApiError(ERR_SPONSOR_NOT_ACTIVE, 409, "sponsor is not ACTIVE")
    if group is None or group["sponsor_id"] != user_id:
        raise ApiError(ERR_SPONSOR_NOT_ASSIGNED, 409,
                       "caller is not the group's assigned sponsor")
    # segregation of duties (403)
    if sponsor["employee_id"] == f["created_by_employee_id"]:
        raise ApiError(ERR_SPONSOR_SELF_ENDORSEMENT, 403,
                       "sponsor may not act on their own submission")
    if decision == "ENDORSE":
        f["status"] = "ENDORSED"
    else:
        f["counter_amount_cents"] = counter
        f["status"] = "COUNTERED"
    touch(f)
    return ok_object(funding_json(f))


@bp.post("/v1/funding-requests/<funding_id>/revise")
def revise_funding(funding_id):
    user_id, _ = authenticate(("GroupLeader",))
    data = body()
    requested_cents = req_int(data, "requested_cents", min_v=1)
    f = get_funding(funding_id)
    if f["status"] != "COUNTERED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "only a COUNTERED request can be revised")
    if f["created_by_employee_id"] != user_id:
        raise ApiError(ERR_NOT_GROUP_LEADER, 403, "caller did not submit this request")
    f["requested_cents"] = requested_cents
    f["status"] = "SUBMITTED"
    touch(f)
    return ok_object(funding_json(f))


@bp.post("/v1/funding-requests/<funding_id>/dei-decision")
def funding_dei_decision(funding_id):
    authenticate(("DeiAdmin",))
    data = body()
    decision = req_enum(data, "decision", ("APPROVE", "DECLINE"))
    f = get_funding(funding_id)
    if decision == "APPROVE":
        if f["status"] != "ENDORSED":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           "approval requires an ENDORSED request")
        group = STORE["groups"][f["group_id"]]
        program = STORE["programs"][group["program_id"]]
        if program["status"] != "ALLOCATION_LOCKED":
            raise ApiError(ERR_ALLOCATION_NOT_LOCKED, 409,
                           "program allocation is not locked")
        award = matching_topup_award(f["requested_cents"], f["external_matching_cents"])
        if award > available_cents(group):
            raise ApiError(ERR_INSUFFICIENT_GROUP_BUDGET, 402,
                           "award exceeds the group's available budget")
        f["approved_cents"] = award
        f["status"] = "APPROVED"
        group["reserved_cents"] += award
        touch(group)
        touch(f)
    else:
        if f["status"] not in ("SUBMITTED", "ENDORSED"):
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           "decline requires a SUBMITTED or ENDORSED request")
        f["status"] = "DECLINED"
        touch(f)
    return ok_object(funding_json(f))


@bp.post("/v1/funding-requests/<funding_id>/disburse")
def disburse_funding(funding_id):
    authenticate(("DeiAdmin",))
    f = get_funding(funding_id)
    if f["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "disbursement requires an APPROVED request")
    group = STORE["groups"][f["group_id"]]
    f["disbursed_cents"] = f["approved_cents"]
    f["status"] = "DISBURSED"
    group["reserved_cents"] -= f["approved_cents"]
    group["spent_cents"] += f["approved_cents"]
    touch(group)
    touch(f)
    return ok_object(funding_json(f))


@bp.post("/v1/funding-requests/<funding_id>/reconcile")
def reconcile_funding(funding_id):
    user_id, _ = authenticate(("GroupLeader",))
    data = body()
    actual_spend_cents = req_int(data, "actual_spend_cents", min_v=0)
    f = get_funding(funding_id)
    if f["status"] != "DISBURSED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "reconciliation requires a DISBURSED request")
    if f["created_by_employee_id"] != user_id:
        raise ApiError(ERR_NOT_GROUP_LEADER, 403, "caller did not submit this request")
    if actual_spend_cents > f["disbursed_cents"]:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "actual_spend_cents exceeds disbursed_cents")
    refund = f["disbursed_cents"] - actual_spend_cents
    group = STORE["groups"][f["group_id"]]
    group["spent_cents"] -= refund
    group["allocated_cents"] -= refund
    # program.unallocated_pool_cents is derived (pool - sum allocated), so the
    # refund flows back to the pool automatically.
    f["actual_spend_cents"] = actual_spend_cents
    f["status"] = "RECONCILED"
    touch(group)
    touch(f)
    return ok_object(funding_json(f))
