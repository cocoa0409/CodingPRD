"""EmployeeVolunteer endpoints."""
from flask import Blueprint, request

from db import db
from errors import raise_err, ERR_VOLUNTEER_NOT_FOUND, ERR_DUPLICATE_EMAIL, ERR_VALIDATION
from middleware import authenticate, body
from response import success_object, success_list
from services import calc
from services.core import mint, ser_volunteer, sort_entities
from timeutil import parse_date
from validate import req_string, opt_str_list, opt_bool

bp = Blueprint("volunteers", __name__)


@bp.post("/employee-volunteers")
def create_volunteer():
    authenticate(["CommunityEngagementManager"])
    data = body()
    full_name = req_string(data, "full_name")
    email = req_string(data, "email")
    department = req_string(data, "department")
    dob_raw = req_string(data, "date_of_birth")
    dob = parse_date(dob_raw, "date_of_birth")
    skills = opt_str_list(data, "skills")
    dietary = opt_str_list(data, "dietary_tags")
    is_lead = opt_bool(data, "is_staff_lead", False)
    for tag in dietary:
        if tag not in calc.DIETARY_TAGS:
            raise_err(ERR_VALIDATION, f"dietary_tags entries must be one of {sorted(calc.DIETARY_TAGS)}")
    if any(v["email"] == email for v in db.volunteers.values()):
        raise_err(ERR_DUPLICATE_EMAIL, "an employee volunteer with this email already exists")
    v = mint()
    v.update(
        {
            "full_name": full_name,
            "email": email,
            "department": department,
            "date_of_birth": dob_raw,
            "_dob": dob,
            "skills": skills,
            "dietary_tags": dietary,
            "is_staff_lead": is_lead,
        }
    )
    db.volunteers[v["id"]] = v
    return success_object(ser_volunteer(v), 201)


@bp.get("/employee-volunteers")
def list_volunteers():
    authenticate(["Any"])
    items = list(db.volunteers.values())
    raw = request.args.get("is_staff_lead")
    if raw is not None:
        if raw not in ("true", "false"):
            raise_err(ERR_VALIDATION, "is_staff_lead filter must be 'true' or 'false'")
        flag = raw == "true"
        items = [v for v in items if v["is_staff_lead"] == flag]
    return success_list([ser_volunteer(v) for v in sort_entities(items)])


@bp.get("/employee-volunteers/<volunteerId>")
def get_volunteer(volunteerId):
    authenticate(["Any"])
    v = db.volunteers.get(volunteerId)
    if v is None:
        raise_err(ERR_VOLUNTEER_NOT_FOUND, "employee volunteer not found")
    return success_object(ser_volunteer(v))
