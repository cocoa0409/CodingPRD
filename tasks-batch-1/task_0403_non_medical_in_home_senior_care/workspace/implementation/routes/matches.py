"""CaregiverMatch endpoints + lifecycle (PRD §3.4)."""
from flask import Blueprint, request

import db
import errors
from errors import ApiError
from middleware import get_auth, require_roles
from response import success, list_success
from services import requtil
from services.calc import recompute_continuity_score
from services.lookup import get_caregiver, get_client, get_match

bp = Blueprint("matches", __name__)

READ_ROLES = {"AgencyAdmin", "Scheduler", "BillingClerk", "Caregiver"}
TIERS = {"TIER_1", "TIER_2", "TIER_3"}


@bp.post("/matches")
def create_match():
    _, role = get_auth()
    require_roles(role, {"Scheduler", "AgencyAdmin"})
    body = requtil.get_body()
    caregiver_id = requtil.require_str(body, "caregiver_id")
    client_id = requtil.require_str(body, "client_id")
    # Existence left-to-right: caregiver, then client.
    get_caregiver(caregiver_id)
    get_client(client_id)
    is_primary = requtil.optional_bool(body, "is_primary", False)

    match = {
        "caregiver_id": caregiver_id,
        "client_id": client_id,
        "is_primary": is_primary,
        "match_status": "PROPOSED",
        "continuity_status": "STANDARD",
    }
    db.stamp_new(match)
    db.matches[match["id"]] = match
    return success(db.public(match), status=201)


@bp.get("/matches")
def list_matches():
    _, role = get_auth()
    require_roles(role, {"AgencyAdmin", "Scheduler", "BillingClerk"})
    limit, offset = requtil.pagination()
    caregiver_id = request.args.get("caregiver_id")
    client_id = request.args.get("client_id")
    items = list(db.matches.values())
    if caregiver_id is not None:
        items = [m for m in items if m["caregiver_id"] == caregiver_id]
    if client_id is not None:
        items = [m for m in items if m["client_id"] == client_id]
    page, total = requtil.paginate(items, limit, offset)
    return list_success([db.public(m) for m in page], limit, offset, total)


@bp.get("/matches/<mid>")
def get_match_route(mid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    match = get_match(mid)
    return success(db.public(match))


@bp.post("/matches/<mid>/transition")
def transition_match(mid):
    _, role = get_auth()
    require_roles(role, {"Scheduler", "AgencyAdmin"})
    match = get_match(mid)
    body = requtil.get_body()
    action = requtil.require_enum(body, "action", {"ACTIVATE", "END"})

    if action == "ACTIVATE":
        # Tier-5 state check first (PRD §2.6): valid from PROPOSED.
        if match["match_status"] != "PROPOSED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "ACTIVATE requires PROPOSED match")
        caregiver = db.caregivers.get(match["caregiver_id"])
        client = db.clients.get(match["client_id"])
        # Business-referential preconditions in PRD §3.4 order.
        if caregiver is None or caregiver["employment_status"] != "ACTIVE":
            raise ApiError(errors.ERR_CAREGIVER_NOT_ACTIVE, 409, "caregiver not ACTIVE")
        if caregiver["background_tier"] not in TIERS:
            raise ApiError(errors.ERR_BACKGROUND_NOT_CLEARED, 409, "background not cleared")
        if client is None or client["status"] not in ("INTAKE", "ACTIVE"):
            raise ApiError(errors.ERR_CLIENT_NOT_SCHEDULABLE, 409, "client not schedulable")
        for other in db.matches.values():
            if other["id"] == match["id"]:
                continue
            if (other["caregiver_id"] == match["caregiver_id"]
                    and other["client_id"] == match["client_id"]
                    and other["match_status"] == "ACTIVE"):
                raise ApiError(errors.ERR_DUPLICATE_ACTIVE_MATCH, 409,
                               "duplicate ACTIVE match for this pair")

        match["match_status"] = "ACTIVE"
        if match.get("is_primary"):
            # Demote any other PREFERRED match for the same client.
            for other in db.matches.values():
                if (other["id"] != match["id"]
                        and other["client_id"] == match["client_id"]
                        and other["continuity_status"] == "PREFERRED"):
                    other["continuity_status"] = "STANDARD"
                    db.touch(other)
            match["continuity_status"] = "PREFERRED"
        db.touch(match)

    elif action == "END":
        if match["match_status"] == "ENDED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "match already ENDED")
        match["match_status"] = "ENDED"
        broke = False
        if match.get("is_primary") and match["continuity_status"] == "PREFERRED":
            match["continuity_status"] = "BROKEN"
            broke = True
        db.touch(match)
        if broke:
            client = db.clients.get(match["client_id"])
            if client is not None:
                recompute_continuity_score(client)

    return success(db.public(match))
