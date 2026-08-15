"""SchoolSite endpoints (PRD 3.1)."""
from flask import Blueprint

from errors import raise_error, ERR_VALIDATION
from middleware import authorized, ALL_ROLES, ROLE_COORDINATOR
from response import success_object
from services.core import new_record, public
from util import parse_date
from validate import get_body, reject_unknown, req_date, req_int, req_str
from routes.helpers import get_path

bp = Blueprint("sites", __name__)


@bp.post("/sites")
def create_site():
    authorized([ROLE_COORDINATOR])
    body = get_body()
    reject_unknown(body, ["name", "enrollment_count", "academic_year_start", "academic_year_end"])
    name = req_str(body, "name")
    enrollment = req_int(body, "enrollment_count", minimum=0)
    ay_start = req_date(body, "academic_year_start")
    ay_end = req_date(body, "academic_year_end")
    if parse_date(ay_end) < parse_date(ay_start):
        raise_error(ERR_VALIDATION, "academic_year_end must not precede academic_year_start")
    rec = new_record("sites", {
        "name": name,
        "enrollment_count": enrollment,
        "academic_year_start": ay_start,
        "academic_year_end": ay_end,
        "compliance_posture": "ON_TRACK",
        "drills_scheduled_count": 0,
        "drills_completed_count": 0,
        "drills_missed_count": 0,
        "drills_cancelled_count": 0,
    })
    return success_object(public(rec), 201)


@bp.get("/sites/<rid>")
def get_site(rid):
    authorized(ALL_ROLES)
    site = get_path("sites", rid)
    return success_object(public(site))
