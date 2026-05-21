"""CrewMember endpoints."""
from flask import Blueprint, request, g

import store
import validators
import serializers
import responses
from auth import require_roles
from errors import raise_error


bp = Blueprint("crew_members", __name__)


@bp.post("/crew-members")
@require_roles("CrewScheduler")
def create_crew_member():
    body = request.get_json(silent=True)
    validators.require_dict(body)
    validators.require_fields(body, "employee_no", "rank", "base_airport",
                              "union_seniority_number", "union_local_id")

    employee_no = validators.require_employee_no(body["employee_no"])
    rank = validators.require_rank(body["rank"])
    base_airport = validators.require_iata(body["base_airport"], "base_airport")
    union_seniority = validators.require_int(body, "union_seniority_number", min_value=1)
    union_local_id = validators.require_string(body, "union_local_id")

    # Uniqueness: employee_no globally unique
    for cm in store.crew_members.values():
        if cm["employee_no"] == employee_no:
            raise_error("ERR_VALIDATION_FAILED",
                        "employee_no must be unique.")
        if cm["rank"] == rank and cm["union_seniority_number"] == union_seniority:
            raise_error("ERR_VALIDATION_FAILED",
                        "union_seniority_number must be unique within rank.")

    row = {
        "employee_no": employee_no,
        "rank": rank,
        "base_airport": base_airport,
        "union_seniority_number": union_seniority,
        "union_local_id": union_local_id,
        "status": "ACTIVE",
        "cumulative_duty_minutes_7d": 0,
        "cumulative_block_minutes_30d": 0,
        "last_duty_end_at": None,
    }
    store.init_common(row)
    store.crew_members[row["id"]] = row
    return responses.success(serializers.crew_member(row), http_status=201)


@bp.get("/crew-members/<cm_id>")
def get_crew_member(cm_id):
    row = store.crew_members.get(cm_id)
    if row is None:
        raise_error("ERR_RESOURCE_NOT_FOUND", "Crew member not found.")
    role = g.role
    if role in ("Pilot", "FlightAttendant"):
        if cm_id != g.user_id:
            raise_error("ERR_FORBIDDEN", "Cannot view another crew member.")
    elif role in ("CrewScheduler", "UnionSteward"):
        pass
    else:
        raise_error("ERR_FORBIDDEN")
    return responses.success(serializers.crew_member(row))


@bp.get("/crew-members")
@require_roles("CrewScheduler")
def list_crew_members():
    limit, offset = validators.parse_pagination(request.args)
    rank = request.args.get("rank")
    base = request.args.get("base_airport")
    status = request.args.get("status")

    rows = list(store.crew_members.values())
    if rank:
        rows = [r for r in rows if r["rank"] == rank]
    if base:
        rows = [r for r in rows if r["base_airport"] == base]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["created_at"])
    page, pag = validators.paginate(rows, limit, offset)
    return responses.success([serializers.crew_member(r) for r in page],
                             response_type="array", pagination=pag)
