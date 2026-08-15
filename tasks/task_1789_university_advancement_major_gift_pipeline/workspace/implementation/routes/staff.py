"""Clock, fundraisers, and portfolio assignments."""

from flask import Blueprint, request

from core import (
    authenticate, authorize, body_json, check_unknown_fields, req_str, req_money,
    req_int, req_enum, opt_str, parse_dt, now, iso, new_entity, touch,
    success_object, success_list, paginate, ALL_ROLES,
)
from db import store, clock
from errors import (
    ApiError, fail, ERR_INVALID_REQUEST, ERR_FUNDRAISER_NOT_FOUND,
    ERR_PROSPECT_NOT_FOUND, ERR_RESOURCE_NOT_FOUND, ERR_STALE_VERSION,
    ERR_FUNDRAISER_INACTIVE, ERR_FUNDRAISER_HAS_ACTIVE_ASSIGNMENTS,
    ERR_PROSPECT_ALREADY_ASSIGNED, ERR_PORTFOLIO_CAPACITY_EXCEEDED,
    ERR_OPEN_ASK_LOAD_EXCEEDED, ERR_INVALID_MOVES_TRANSITION,
)
from services import (
    run_sweeps, ser_fundraiser, ser_assignment,
    active_assignment_of_prospect, fundraiser_current_prospect_count,
    fundraiser_current_open_ask_cents,
)

bp = Blueprint("staff", __name__)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/advancement/_clock/set_current_utc")
def set_clock():
    user_id, role = authenticate()
    authorize(role, ["AdvancementDirector", "VPAdvancement"])
    body = body_json()
    check_unknown_fields(body, {"to_iso8601"})
    target = parse_dt(body.get("to_iso8601"), "to_iso8601")
    if target <= clock["now"]:
        fail(ERR_INVALID_REQUEST, "to_iso8601 must be strictly later than the current logical time")
    clock["now"] = target
    run_sweeps(target)
    return success_object({"current_utc": iso(target)})


# ---------------------------------------------------------------------------
# Fundraisers
# ---------------------------------------------------------------------------

@bp.post("/advancement/fundraisers")
def create_fundraiser():
    user_id, role = authenticate()
    authorize(role, ["VPAdvancement"])
    body = body_json()
    check_unknown_fields(body, {"display_name", "email", "max_prospect_count", "max_open_ask_cents"})
    display_name = req_str(body, "display_name")
    email = req_str(body, "email")
    max_prospect_count = req_money(body, "max_prospect_count")
    max_open_ask_cents = req_money(body, "max_open_ask_cents")
    entity = new_entity()
    entity.update({
        "display_name": display_name,
        "email": email,
        "max_prospect_count": max_prospect_count,
        "max_open_ask_cents": max_open_ask_cents,
        "status": "ACTIVE",
    })
    store["fundraisers"][entity["id"]] = entity
    return success_object(ser_fundraiser(entity), 201)


def _get_fundraiser(fid):
    fundraiser = store["fundraisers"].get(fid)
    if fundraiser is None:
        fail(ERR_FUNDRAISER_NOT_FOUND, "Fundraiser not found")
    return fundraiser


@bp.get("/advancement/fundraisers/<fid>")
def get_fundraiser(fid):
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    return success_object(ser_fundraiser(_get_fundraiser(fid)))


@bp.post("/advancement/fundraisers/<fid>/deactivate")
def deactivate_fundraiser(fid):
    user_id, role = authenticate()
    authorize(role, ["VPAdvancement"])
    fundraiser = _get_fundraiser(fid)
    if fundraiser["status"] != "ACTIVE":
        fail(ERR_INVALID_MOVES_TRANSITION, "Fundraiser is not ACTIVE")
    if fundraiser_current_prospect_count(fid) != 0:
        fail(ERR_FUNDRAISER_HAS_ACTIVE_ASSIGNMENTS, "Fundraiser still holds ACTIVE assignments")
    fundraiser["status"] = "INACTIVE"
    touch(fundraiser)
    return success_object(ser_fundraiser(fundraiser))


@bp.post("/advancement/fundraisers/<fid>/assignments")
def create_assignment(fid):
    user_id, role = authenticate()
    authorize(role, ["AdvancementDirector"])
    body = body_json()
    check_unknown_fields(body, {"prospect_id", "expected_fundraiser_version"})
    prospect_id = req_str(body, "prospect_id")
    expected_version = req_int(body, "expected_fundraiser_version")
    # existence: fundraiser path segment first, then prospect body reference
    fundraiser = _get_fundraiser(fid)
    prospect = store["prospects"].get(prospect_id)
    if prospect is None:
        fail(ERR_PROSPECT_NOT_FOUND, "Prospect not found")
    # OCC on the fundraiser version (priority 7)
    if expected_version != fundraiser["version"]:
        fail(ERR_STALE_VERSION, "expected_fundraiser_version does not match the fundraiser's current version")
    # state (priority 8)
    if fundraiser["status"] != "ACTIVE":
        fail(ERR_FUNDRAISER_INACTIVE, "Fundraiser is INACTIVE")
    # capacity / uniqueness (priority 11)
    if active_assignment_of_prospect(prospect_id) is not None:
        fail(ERR_PROSPECT_ALREADY_ASSIGNED, "Prospect already has an ACTIVE assignment")
    if fundraiser_current_prospect_count(fid) >= fundraiser["max_prospect_count"]:
        fail(ERR_PORTFOLIO_CAPACITY_EXCEEDED, "Fundraiser portfolio count capacity reached")
    prospect_open_ask = sum(
        p["ask_amount_cents"] for p in store["proposals"].values()
        if p["prospect_id"] == prospect_id and p["status"] in ("UNDER_REVIEW", "NEGOTIATING", "APPROVED")
    )
    if fundraiser_current_open_ask_cents(fid) + prospect_open_ask > fundraiser["max_open_ask_cents"]:
        fail(ERR_OPEN_ASK_LOAD_EXCEEDED, "Assignment would exceed the fundraiser's open-ask ceiling")
    entity = new_entity()
    entity.update({
        "fundraiser_id": fid,
        "prospect_id": prospect_id,
        "status": "ACTIVE",
        "released_reason": None,
    })
    store["assignments"][entity["id"]] = entity
    touch(fundraiser)
    return success_object(ser_assignment(entity), 201)


@bp.get("/advancement/fundraisers/<fid>/assignments")
def list_fundraiser_assignments(fid):
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    _get_fundraiser(fid)
    items = [a for a in store["assignments"].values() if a["fundraiser_id"] == fid]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [a for a in items if a["status"] == status_filter]
    page, limit, offset, total = paginate(items)
    return success_list([ser_assignment(a) for a in page], limit, offset, total)


@bp.post("/advancement/assignments/<aid>/release")
def release_assignment(aid):
    user_id, role = authenticate()
    authorize(role, ["AdvancementDirector"])
    body = body_json()
    check_unknown_fields(body, {"released_reason"})
    released_reason = req_enum(body, "released_reason", {"GRADUATED", "REBALANCING", "DISQUALIFIED"})
    assignment = store["assignments"].get(aid)
    if assignment is None:
        fail(ERR_RESOURCE_NOT_FOUND, "Assignment not found")
    if assignment["status"] != "ACTIVE":
        fail(ERR_INVALID_MOVES_TRANSITION, "Assignment is not ACTIVE")
    assignment["status"] = "RELEASED"
    assignment["released_reason"] = released_reason
    touch(assignment)
    fundraiser = store["fundraisers"].get(assignment["fundraiser_id"])
    if fundraiser is not None:
        touch(fundraiser)
    return success_object(ser_assignment(assignment))
