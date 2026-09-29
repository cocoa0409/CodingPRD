"""Research analysts."""
from flask import Blueprint

from db import db, new_row, touch
from errors import fail
from middleware import ANY_ROLE, endpoint
from response import list_response, object_response
from validate import (ANALYST_STATUS, EMPLOYMENT_TYPE, body, fk_from_body,
                      fk_from_query, opt_bool, paginate, pagination, query_enum,
                      req_dt, req_enum, req_str, resolve)

from services import serialize
from services.listing import by_created_at

bp = Blueprint("analysts", __name__)


@bp.post("/analysts")
@endpoint(("ProgramAdmin",))
def register_analyst():
    payload = body()
    program = fk_from_body(payload, "program_id", db.programs, "ERR_PROGRAM_NOT_FOUND")
    program_id = req_str(payload, "program_id")
    full_name = req_str(payload, "full_name")
    linked_user_ref = req_str(payload, "linked_user_ref")
    employment_type = req_enum(payload, "employment_type", EMPLOYMENT_TYPE)
    certified_until = req_dt(payload, "certified_until")
    sales_org_member = opt_bool(payload, "sales_org_member", False)
    if program is None:
        fail("ERR_PROGRAM_NOT_FOUND")

    analyst = new_row({
        "program_id": program_id,
        "full_name": full_name,
        "linked_user_ref": linked_user_ref,
        "employment_type": employment_type,
        "sales_org_member": bool(sales_org_member),
        "certified_until": certified_until,
        "status": "ACTIVE",
    })
    db.analysts[analyst["id"]] = analyst
    return object_response(serialize.analyst(analyst), 201)


@bp.get("/analysts/<analyst_id>")
@endpoint(ANY_ROLE)
def read_analyst(analyst_id):
    analyst = resolve(db.analysts, analyst_id, "ERR_ANALYST_NOT_FOUND")
    return object_response(serialize.analyst(analyst))


@bp.post("/analysts/<analyst_id>/deactivate")
@endpoint(("ProgramAdmin",))
def deactivate_analyst(analyst_id):
    analyst = resolve(db.analysts, analyst_id, "ERR_ANALYST_NOT_FOUND")
    analyst["status"] = "INACTIVE"
    touch(analyst)
    return object_response(serialize.analyst(analyst))


@bp.get("/analysts")
@endpoint(ANY_ROLE)
def list_analysts():
    program_id = fk_from_query("program_id", db.programs, "ERR_PROGRAM_NOT_FOUND")
    status = query_enum("status", ANALYST_STATUS)
    employment_type = query_enum("employment_type", EMPLOYMENT_TYPE)
    limit, offset = pagination()
    rows = list(db.analysts.values())
    if program_id:
        rows = [a for a in rows if a["program_id"] == program_id]
    if status:
        rows = [a for a in rows if a["status"] == status]
    if employment_type:
        rows = [a for a in rows if a["employment_type"] == employment_type]
    rows = sorted(by_created_at(rows), key=lambda a: a["full_name"])
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.analyst(r) for r in page], limit, offset, total)
