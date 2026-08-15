"""Volunteer registration, orientation, waiver, standing (PRD section 3.1)."""
from flask import Blueprint, request

import db
import services
from app_util import body
from errors import err, err_invalid_request, err_not_found, err_ownership, err_state
from middleware import ALL_ROLES, SELF_SERVICE_ROLES, require_auth, require_role
from response import ok
from util import opt_str, pagination_args, req_enum, req_str, parse_date

bp = Blueprint("volunteers", __name__)

STANDING_TARGETS = {"GOOD", "PROBATION", "SUSPENDED"}
# allowed standing transitions: from_state -> set of valid to_states
STANDING_TRANSITIONS = {
    "GOOD": {"PROBATION", "SUSPENDED"},
    "PROBATION": {"SUSPENDED", "GOOD"},
    "SUSPENDED": {"GOOD"},
}


@bp.post("/api/volunteers")
def create_volunteer():
    ctx = require_auth()
    require_role(ctx, ["GardenAdmin", "Coordinator"])
    data = body()
    # shape (tier 5)
    full_name = req_str(data, "full_name")
    email = req_str(data, "email")
    dob_raw = req_str(data, "date_of_birth")
    dob = parse_date(dob_raw, "date_of_birth")
    phone = opt_str(data, "phone", None)
    # uniqueness (tier 11)
    if any(v["email"] == email for v in db.volunteers.values()):
        raise err("ERR_EMAIL_TAKEN", "email already registered")
    rec = services.create_record({
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "date_of_birth": dob.isoformat(),
        "_dob": dob,
        "orientation_status": "PENDING",
        "waiver_status": "UNSIGNED",
        "waiver_signed_at": None,
        "standing": "GOOD",
    })
    db.volunteers[rec["id"]] = rec
    return ok(services.volunteer_view(rec), status=201)


@bp.get("/api/volunteers")
def list_volunteers():
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    limit, offset = pagination_args(request.args)
    items = services.list_view(
        db.volunteers.values(),
        {"standing": "standing", "waiver_status": "waiver_status",
         "orientation_status": "orientation_status"},
        request.args, services.volunteer_view,
    )
    total = len(items)
    page = items[offset:offset + limit]
    return ok([services.volunteer_view(v) for v in page],
              pagination=(limit, offset, total))


def _get_volunteer(volunteer_id):
    vol = db.volunteers.get(volunteer_id)
    if vol is None:
        raise err_not_found("volunteer")
    return vol


@bp.get("/api/volunteers/<volunteerId>")
def get_volunteer(volunteerId):
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    return ok(services.volunteer_view(_get_volunteer(volunteerId)))


@bp.post("/api/volunteers/<volunteerId>/orientation/complete")
def complete_orientation(volunteerId):
    ctx = require_auth()
    require_role(ctx, ["GardenAdmin", "Coordinator"])
    vol = _get_volunteer(volunteerId)
    if vol["orientation_status"] != "PENDING":
        raise err_state("VOLUNTEER")
    vol["orientation_status"] = "ORIENTED"
    services.bump(vol)
    return ok(services.volunteer_view(vol))


@bp.post("/api/volunteers/<volunteerId>/waiver/sign")
def sign_waiver(volunteerId):
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    vol = _get_volunteer(volunteerId)
    # ownership (tier 4): self-service roles may sign only their own record
    if ctx.role in SELF_SERVICE_ROLES and ctx.user_id != vol["id"]:
        raise err_ownership()
    if vol["waiver_status"] not in {"UNSIGNED", "EXPIRED"}:
        raise err_state("VOLUNTEER")
    import clock
    vol["waiver_status"] = "SIGNED"
    vol["waiver_signed_at"] = clock.now()
    services.bump(vol)
    return ok(services.volunteer_view(vol))


@bp.post("/api/volunteers/<volunteerId>/standing")
def set_standing(volunteerId):
    ctx = require_auth()
    require_role(ctx, ["GardenAdmin"])
    vol = _get_volunteer(volunteerId)
    data = body()
    to_state = req_enum(data, "to_state", STANDING_TARGETS)
    if to_state not in STANDING_TRANSITIONS.get(vol["standing"], set()):
        raise err_state("VOLUNTEER")
    if to_state == "SUSPENDED":
        vol["standing"] = "SUSPENDED"
        services.bump(vol)
        services.suspend_volunteer_cascade(vol)
    else:
        vol["standing"] = to_state
        services.bump(vol)
    return ok(services.volunteer_view(vol))
