"""Instructor and Venue endpoints."""

from flask import Blueprint

import db
from db import stamp_new, store, touch
from errors import fail
from middleware import require_roles
from response import ok, serialize
from services import lookups
from util import body_json, req_enum, req_int, req_list, req_str

bp = Blueprint("instructors_venues", __name__)

READ_ROLES = (
    "CollegeAdmin",
    "WorkforceCoordinator",
    "CredentialOfficer",
    "GrantOfficer",
    "EmployerContact",
    "BillingClerk",
    "Instructor",
)

VENUE_KINDS = ("CAMPUS_LAB", "EMPLOYER_SITE")


# ---------------------------------------------------------------------------
# Instructors
# ---------------------------------------------------------------------------

@bp.route("/ct/instructors", methods=["POST"])
def create_instructor():
    require_roles("CollegeAdmin")
    body = body_json()
    full_name = req_str(body, "full_name")
    credentials = req_list(body, "credentials")
    for cred in credentials:
        if not isinstance(cred, dict) or not isinstance(cred.get("code"), str) or not cred.get("code"):
            fail("ERR_INVALID_REQUEST", "Each credential requires a 'code' string")
        if not isinstance(cred.get("expires_on"), str):
            fail("ERR_INVALID_REQUEST", "Each credential requires an 'expires_on' date string")
    rate = req_int(body, "hourly_rate_cents", min_value=0)
    rec = stamp_new(
        {
            "id": db.new_id(),
            "full_name": full_name,
            "credentials": credentials,
            "hourly_rate_cents": rate,
            "committed_hours": 0,
            "status": "ACTIVE",
        }
    )
    store["instructors"][rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/ct/instructors/<iid>", methods=["GET"])
def get_instructor(iid):
    require_roles(*READ_ROLES)
    return ok(serialize(lookups.get_or_404("instructors", iid, "Instructor")))


@bp.route("/ct/instructors/<iid>/deactivate", methods=["POST"])
def deactivate_instructor(iid):
    require_roles("CollegeAdmin")
    instructor = lookups.get_or_404("instructors", iid, "Instructor")
    if instructor["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", f"Cannot deactivate an instructor in {instructor['status']}")
    for assignment in store["assignments"].values():
        if assignment["instructor_id"] != iid or assignment["status"] != "CONFIRMED":
            continue
        session = store["sessions"].get(assignment["session_id"])
        if session is not None and session["status"] == "PLANNED":
            fail(
                "ERR_INVALID_STATE",
                "Instructor holds CONFIRMED assignments on PLANNED sessions; release them first",
            )
    instructor["status"] = "INACTIVE"
    touch(instructor)
    return ok(serialize(instructor))


@bp.route("/ct/instructors/<iid>/reactivate", methods=["POST"])
def reactivate_instructor(iid):
    require_roles("CollegeAdmin")
    instructor = lookups.get_or_404("instructors", iid, "Instructor")
    if instructor["status"] != "INACTIVE":
        fail("ERR_INVALID_STATE", f"Cannot reactivate an instructor in {instructor['status']}")
    instructor["status"] = "ACTIVE"
    touch(instructor)
    return ok(serialize(instructor))


# ---------------------------------------------------------------------------
# Venues
# ---------------------------------------------------------------------------

@bp.route("/ct/venues", methods=["POST"])
def create_venue():
    require_roles("CollegeAdmin")
    body = body_json()
    rec = stamp_new(
        {
            "id": db.new_id(),
            "name": req_str(body, "name"),
            "kind": req_enum(body, "kind", VENUE_KINDS),
            "capacity": req_int(body, "capacity", min_value=1),
            "hourly_cost_cents": req_int(body, "hourly_cost_cents", min_value=0),
            "turnover_buffer_minutes": 30,
        }
    )
    store["venues"][rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/ct/venues/<vid>", methods=["GET"])
def get_venue(vid):
    require_roles(*READ_ROLES)
    return ok(serialize(lookups.get_or_404("venues", vid, "Venue")))
