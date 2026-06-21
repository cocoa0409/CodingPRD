"""Caregiver endpoints + lifecycle (PRD §3.2)."""
from flask import Blueprint

import db
import errors
from errors import ApiError
from middleware import get_auth, require_roles
from response import success, list_success
from services import requtil
from services.calc import recompute_continuity_score
from services.lookup import get_agency, get_caregiver

bp = Blueprint("caregivers", __name__)

READ_ROLES = {"AgencyAdmin", "Scheduler", "BillingClerk", "Caregiver"}
TIERS = {"TIER_1", "TIER_2", "TIER_3"}


@bp.post("/caregivers")
def create_caregiver():
    _, role = get_auth()
    require_roles(role, {"AgencyAdmin"})
    body = requtil.get_body()

    agency_id = requtil.require_str(body, "agency_id")
    full_name = requtil.require_str(body, "full_name")
    hire_state_code = requtil.require_str(body, "hire_state_code")
    # existence (tier 3) before well-formedness of optional numeric (tier 4)
    get_agency(agency_id)
    max_weekly_hours = requtil.optional_number(body, "max_weekly_hours", 50)
    if max_weekly_hours <= 0:
        raise requtil.invalid("max_weekly_hours must be > 0")

    caregiver = {
        "agency_id": agency_id,
        "full_name": full_name,
        "hire_state_code": hire_state_code,
        "background_tier": "PENDING",
        "employment_status": "APPLICANT",
        "max_weekly_hours": max_weekly_hours,
    }
    db.stamp_new(caregiver)
    db.caregivers[caregiver["id"]] = caregiver
    return success(db.public(caregiver), status=201)


@bp.get("/caregivers")
def list_caregivers():
    _, role = get_auth()
    require_roles(role, {"AgencyAdmin", "Scheduler", "BillingClerk"})
    limit, offset = requtil.pagination()
    from flask import request
    agency_id = request.args.get("agency_id")
    items = list(db.caregivers.values())
    if agency_id is not None:
        items = [c for c in items if c["agency_id"] == agency_id]
    page, total = requtil.paginate(items, limit, offset)
    return list_success([db.public(c) for c in page], limit, offset, total)


@bp.get("/caregivers/<cid>")
def get_caregiver_route(cid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    caregiver = get_caregiver(cid)
    return success(db.public(caregiver))


@bp.post("/caregivers/<cid>/transition")
def transition_caregiver(cid):
    _, role = get_auth()
    require_roles(role, {"AgencyAdmin"})
    caregiver = get_caregiver(cid)
    body = requtil.get_body()
    action = requtil.require_enum(
        body, "action", {"CLEAR_BACKGROUND", "ACTIVATE", "SUSPEND", "REVOKE"}
    )

    if action == "CLEAR_BACKGROUND":
        target_tier = body.get("target_tier")
        if target_tier not in TIERS:
            raise requtil.invalid("target_tier must be one of TIER_1, TIER_2, TIER_3")
        if caregiver["background_tier"] != "PENDING":
            raise ApiError(errors.ERR_BACKGROUND_NOT_PENDING, 409,
                           "background_tier must be PENDING to clear")
        caregiver["background_tier"] = target_tier
        db.touch(caregiver)

    elif action == "ACTIVATE":
        if caregiver["background_tier"] not in TIERS:
            raise ApiError(errors.ERR_BACKGROUND_NOT_CLEARED, 409,
                           "background must be cleared before activation")
        if caregiver["employment_status"] not in ("APPLICANT", "SUSPENDED"):
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "cannot activate from current employment status")
        caregiver["employment_status"] = "ACTIVE"
        db.touch(caregiver)

    elif action == "SUSPEND":
        if caregiver["employment_status"] != "ACTIVE":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "employment_status must be ACTIVE to suspend")
        caregiver["employment_status"] = "SUSPENDED"
        db.touch(caregiver)
        _cascade_end_matches(caregiver, statuses={"ACTIVE"})

    elif action == "REVOKE":
        if caregiver["background_tier"] == "REVOKED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "background already REVOKED")
        caregiver["background_tier"] = "REVOKED"
        caregiver["employment_status"] = "TERMINATED"
        db.touch(caregiver)
        _cascade_end_matches(caregiver, statuses={"PROPOSED", "ACTIVE"})

    return success(db.public(caregiver))


def _cascade_end_matches(caregiver, statuses):
    """End the caregiver's matches in the given statuses; break preferred continuity."""
    affected_clients = set()
    for m in db.matches.values():
        if m["caregiver_id"] != caregiver["id"]:
            continue
        if m["match_status"] not in statuses:
            continue
        m["match_status"] = "ENDED"
        broke = False
        if m.get("is_primary") and m["continuity_status"] == "PREFERRED":
            m["continuity_status"] = "BROKEN"
            broke = True
        db.touch(m)
        if broke:
            affected_clients.add(m["client_id"])
    for client_id in affected_clients:
        client = db.clients.get(client_id)
        if client is not None:
            recompute_continuity_score(client)
