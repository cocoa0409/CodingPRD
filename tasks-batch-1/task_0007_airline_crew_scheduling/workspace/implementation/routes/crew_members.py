"""CrewMember routes (PRD §3.2)."""
from flask import Blueprint

import db
from errors import not_found, invalid_request
from middleware import require_roles, ROLE_PLANNER, ROLE_OPS, ROLE_CREW
from response import success, paginated
from routes.common import get_json_body, parse_pagination, sort_by_created_at, slice_page
from services.constants import RANKS, LINE_TYPES, CREW_STATUSES
from services import validate
from services.entity import stamp_new


bp = Blueprint("crew_members", __name__)


CREW_REQUIRED = (
    "employee_code", "full_name", "rank", "base_airport",
    "seniority_number", "line_type",
)
CREW_ALLOWED = set(CREW_REQUIRED)


@bp.route("/crew-members", methods=["POST"])
def create_crew_member():
    require_roles({ROLE_PLANNER})
    body = validate.ensure_dict(get_json_body())
    validate.require_fields(body, CREW_REQUIRED)
    validate.reject_extra(body, CREW_ALLOWED)
    employee_code = validate.check_string(
        body, "employee_code", pattern=r"^[A-Z]{2}[0-9]{4}$"
    )
    full_name = validate.check_string(body, "full_name")
    rank = validate.check_enum(body, "rank", RANKS)
    base_airport = validate.check_string(
        body, "base_airport", pattern=r"^[A-Z]{3}$"
    )
    seniority_number = validate.check_int(body, "seniority_number", min_val=1)
    line_type = validate.check_enum(body, "line_type", LINE_TYPES)

    # Uniqueness: employee_code globally unique; seniority_number unique within (rank, base).
    for cm in db.crew_members.values():
        if cm["employee_code"] == employee_code:
            raise invalid_request("employee_code already exists")
        if (
            cm["rank"] == rank
            and cm["base_airport"] == base_airport
            and cm["seniority_number"] == seniority_number
        ):
            raise invalid_request(
                "seniority_number must be unique within (rank, base_airport)"
            )

    record = {
        "employee_code": employee_code,
        "full_name": full_name,
        "rank": rank,
        "base_airport": base_airport,
        "seniority_number": seniority_number,
        "line_type": line_type,
        "status": "AVAILABLE",
        "total_flight_minutes_7d": 0,
        "total_duty_minutes_7d": 0,
        "last_off_duty_utc": None,
    }
    stamp_new(record)
    db.crew_members[record["id"]] = record
    return success(record, status=201)


@bp.route("/crew-members", methods=["GET"])
def list_crew_members():
    require_roles({ROLE_PLANNER, ROLE_OPS})
    limit, offset = parse_pagination()
    rows = list(db.crew_members.values())

    from flask import request
    rank = request.args.get("rank")
    base_airport = request.args.get("base_airport")
    line_type = request.args.get("line_type")
    status = request.args.get("status")
    if rank:
        rows = [r for r in rows if r["rank"] == rank]
    if base_airport:
        rows = [r for r in rows if r["base_airport"] == base_airport]
    if line_type:
        rows = [r for r in rows if r["line_type"] == line_type]
    if status:
        rows = [r for r in rows if r["status"] == status]

    rows = sort_by_created_at(rows)
    page, total = slice_page(rows, limit, offset)
    return paginated(page, limit, offset, total)


@bp.route("/crew-members/<crew_id>", methods=["GET"])
def get_crew_member(crew_id):
    require_roles({ROLE_PLANNER, ROLE_OPS, ROLE_CREW})
    cm = db.crew_members.get(crew_id)
    if cm is None:
        raise not_found("CrewMember not found")
    return success(cm, status=200)
