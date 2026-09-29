"""StaffMember and WellnessCheck endpoints."""

from flask import Blueprint

from db import clock_now, public
from errors import ApiError
from middleware import (ROLE_AGENCY_ADMIN, ROLE_HOTLINE_ADVOCATE, ROLE_HOUSING_SPECIALIST,
                        ROLE_LEGAL_ADVOCATE, ROLE_PRIVACY_OFFICER, ROLE_SHELTER_MANAGER,
                        auth)
from response import created, ok
from routes.common import by_created, filtered, get_staff, insert, list_page
from services import calc, derive
from validation import (dt_out, get_body, opt_bool, opt_int, req_datetime, req_enum,
                        req_int, req_num, req_str)

bp = Blueprint("staff", __name__)

ROLE_TYPES = ("HOTLINE_ADVOCATE", "SHELTER_MANAGER", "LEGAL_ADVOCATE",
              "HOUSING_SPECIALIST", "PRIVACY_OFFICER")

READ_ALL = (ROLE_AGENCY_ADMIN, ROLE_HOTLINE_ADVOCATE, ROLE_SHELTER_MANAGER,
            ROLE_LEGAL_ADVOCATE, ROLE_HOUSING_SPECIALIST, ROLE_PRIVACY_OFFICER)


@bp.post("/staff-members")
def create_staff():
    auth((ROLE_AGENCY_ADMIN,))
    body = get_body()
    full_name = req_str(body, "full_name", 1, 120)
    role_type = req_enum(body, "role_type", ROLE_TYPES)
    max_caseload = opt_int(body, "max_caseload", 8, 1, 50)
    staff = insert("staff_members", {
        "full_name": full_name,
        "role_type": role_type,
        "max_caseload": max_caseload,
        "active_caseload_count": 0,
        "secondary_trauma_index": 0.0,
        "wellness_posture": "OPEN",
        "last_wellness_check_at": None,
    })
    return created(public(staff))


@bp.get("/staff-members/<staff_id>")
def read_staff(staff_id):
    auth(READ_ALL)
    return ok(public(get_staff(staff_id)))


@bp.post("/staff-members/<staff_id>/wellness-checks")
def create_wellness_check(staff_id):
    auth((ROLE_AGENCY_ADMIN, ROLE_SHELTER_MANAGER))
    body = get_body()
    checked_on = req_datetime(body, "checked_on_utc")
    exposure_hours = req_num(body, "exposure_hours", 0, 200)
    distress_scale = req_int(body, "distress_scale", 0, 10)
    debrief_completed = opt_bool(body, "debrief_completed", False)
    staff = get_staff(staff_id)

    if checked_on > clock_now():
        raise ApiError("ERR_INVALID_DATE_WINDOW",
                       "checked_on_utc may not be later than the logical clock")

    check = insert("wellness_checks", {
        "staff_member_id": staff["id"],
        "checked_on_utc": dt_out(checked_on),
        "exposure_hours": exposure_hours,
        "distress_scale": distress_scale,
        "debrief_completed": debrief_completed,
        "contribution_points": calc.contribution_points(
            distress_scale, exposure_hours, debrief_completed),
    }, audited=False)
    derive.recompute_staff(staff, force=True)
    return created(public(check))


@bp.get("/staff-members/<staff_id>/wellness-checks")
def list_wellness_checks(staff_id):
    auth((ROLE_AGENCY_ADMIN, ROLE_SHELTER_MANAGER))
    staff = get_staff(staff_id)
    rows = by_created(filtered("wellness_checks", {"staff_member_id": staff["id"]}))
    rows = sorted(rows, key=lambda r: r["checked_on_utc"], reverse=True)
    return list_page(rows)
