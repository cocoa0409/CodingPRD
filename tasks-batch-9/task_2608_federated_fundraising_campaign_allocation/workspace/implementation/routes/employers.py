"""Workplace partnerships and the coordinator roster (PRD 3.1)."""

from flask import Blueprint

import auth
from auth import ALL_ROLES, authenticate, get_employer
from envelope import created, filter_str, filter_int, ok, paginate
from errors import ApiError
from store import base_entity, db, sort_created_asc, sort_created_desc, touch
from validators import bad, body, get_bool, get_enum, get_int, get_str

from services import aggregates

bp = Blueprint("employers", __name__)

COORDINATOR_ROLES = ("LEAD", "DEPARTMENT")


@bp.get("/employers/<employer_id>")
def read_employer(employer_id):
    authenticate(ALL_ROLES)
    return ok(get_employer(employer_id))


@bp.get("/employers/<employer_id>/coordinators")
def list_coordinators(employer_id):
    authenticate(ALL_ROLES)
    get_employer(employer_id)
    status = filter_str("status")
    rows = [c for c in db.coordinators.values() if c["employer_id"] == employer_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    return paginate(sort_created_asc(rows))


@bp.get("/employers/<employer_id>/campaigns")
def list_employer_campaigns(employer_id):
    authenticate(ALL_ROLES)
    get_employer(employer_id)
    posture = filter_str("posture")
    campaign_year = filter_int("campaign_year")
    rows = [c for c in db.campaigns.values() if c["employer_id"] == employer_id]
    if posture is not None:
        rows = [c for c in rows if c["posture"] == posture]
    if campaign_year is not None:
        rows = [c for c in rows if c["campaign_year"] == campaign_year]
    # PRD 2.3: the campaigns of one employer are returned newest first.
    return paginate(sort_created_desc(rows))


@bp.post("/employers")
def create_employer():
    authenticate(("UnitedFundAdmin",))
    data = body()
    legal_name = get_str(data, "legal_name", min_len=1, max_len=200)
    employee_count = get_int(data, "employee_count", minimum=1)
    payroll_periods = get_int(
        data, "payroll_periods_per_year", minimum=0, maximum=52, required=False, default=26
    )
    shrinkage_bps = get_int(
        data, "historical_shrinkage_rate_bps", minimum=0, maximum=10000,
        required=False, default=800,
    )
    partnership_signed = get_bool(data, "partnership_signed", required=False, default=False)

    row = base_entity()
    row.update({
        "legal_name": legal_name,
        "employee_count": employee_count,
        "payroll_periods_per_year": payroll_periods,
        "historical_shrinkage_rate_bps": shrinkage_bps,
        "partnership_signed": partnership_signed,
        "status": "ACTIVE" if partnership_signed else "PROSPECT",
        "suspended_reason": None,
        "active_campaign_count": 0,
    })
    db.employers[row["id"]] = row
    return created(row)


@bp.post("/employers/<employer_id>/activate")
def activate_employer(employer_id):
    authenticate(("UnitedFundAdmin",))
    body()
    employer = get_employer(employer_id)
    if employer["status"] != "PROSPECT":
        raise ApiError("ERR_EMPLOYER_INVALID_STATE")
    employer["status"] = "ACTIVE"
    employer["partnership_signed"] = True
    touch("employer", employer)
    return ok(employer)


@bp.post("/employers/<employer_id>/coordinators")
def seat_coordinator(employer_id):
    authenticate(("UnitedFundAdmin",))
    data = body()
    full_name = get_str(data, "full_name", min_len=1, max_len=120)
    email = get_str(data, "email", min_len=1)
    if "@" not in email:
        bad("Field 'email' must contain '@'.")
    coordinator_role = get_enum(
        data, "coordinator_role", COORDINATOR_ROLES, required=False, default="DEPARTMENT"
    )
    for existing in db.coordinators.values():
        if existing["email"] == email:
            bad("Field 'email' must be unique across all campaign coordinators.")
    get_employer(employer_id)

    row = base_entity()
    row.update({
        "employer_id": employer_id,
        "full_name": full_name,
        "email": email,
        "coordinator_role": coordinator_role,
        "status": "ACTIVE",
        "recorded_pledge_count": 0,
    })
    db.coordinators[row["id"]] = row
    return created(row)
