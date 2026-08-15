"""Volunteer registration and reads (PRD 3.7)."""
from flask import Blueprint

import services as svc
from db import stamp_new, store
from errors import not_found
from middleware import require_roles
from response import ok, ok_list
from util import (
    get_body, opt_enum_filter, page_params, paginate, v_bool, v_str,
)

bp = Blueprint("volunteers", __name__)

SIGNUP_STATUSES = {"SIGNED_UP", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED"}


def get_volunteer_or_404(volunteer_id):
    v = store.volunteers.get(volunteer_id)
    if v is None:
        raise not_found("Volunteer not found")
    return v


@bp.post("/closet/volunteers")
@require_roles("ProgramAdmin", "VolunteerLead")
def create_volunteer():
    data = get_body()
    full_name = v_str(data, "full_name")
    is_lead = v_bool(data, "is_lead", required=False, default=False)
    v = stamp_new({
        "full_name": full_name,
        "is_lead": is_lead,
        "status": "ACTIVE",
    })
    store.volunteers[v["id"]] = v
    return ok(svc.serialize_volunteer(v), 201)


@bp.get("/closet/volunteers/<vid>")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def get_volunteer(vid):
    return ok(svc.serialize_volunteer(get_volunteer_or_404(vid)))


@bp.get("/closet/volunteers/<vid>/signups")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def list_volunteer_signups(vid):
    get_volunteer_or_404(vid)
    status = opt_enum_filter("status", SIGNUP_STATUSES)
    limit, offset = page_params()
    rows = [s for s in store.signups.values() if s["volunteer_id"] == vid]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([svc.serialize_signup(s) for s in page], total, limit, offset)
