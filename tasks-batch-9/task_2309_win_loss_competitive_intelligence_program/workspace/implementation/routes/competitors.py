"""The competitive registry."""
from flask import Blueprint

from db import db, new_row, touch
from errors import fail
from middleware import ANY_ROLE, endpoint
from response import list_response, object_response
from validate import (COMPETITOR_STATUS, COMPETITOR_TIER, body, fk_from_body,
                      fk_from_query, paginate, pagination, query_enum, req_enum,
                      req_str, resolve)

from services import serialize
from services.listing import by_created_at

bp = Blueprint("competitors", __name__)


@bp.post("/competitors")
@endpoint(("ProgramAdmin",))
def register_competitor():
    payload = body()
    program = fk_from_body(payload, "program_id", db.programs, "ERR_PROGRAM_NOT_FOUND")
    program_id = req_str(payload, "program_id")
    name = req_str(payload, "name")
    tier = req_enum(payload, "tier", COMPETITOR_TIER)
    if program is None:
        fail("ERR_PROGRAM_NOT_FOUND")
    for existing in db.competitors.values():
        if existing["program_id"] == program_id and \
                existing["name"].lower() == name.lower():
            fail("ERR_DUPLICATE_RESOURCE_KEY",
                 "A competitor with that name already exists in the program.")
    competitor = new_row({
        "program_id": program_id,
        "name": name,
        "tier": tier,
        "status": "ACTIVE",
    })
    db.competitors[competitor["id"]] = competitor
    return object_response(serialize.competitor(competitor), 201)


@bp.get("/competitors/<competitor_id>")
@endpoint(ANY_ROLE)
def read_competitor(competitor_id):
    competitor = resolve(db.competitors, competitor_id, "ERR_COMPETITOR_NOT_FOUND")
    return object_response(serialize.competitor(competitor))


@bp.post("/competitors/<competitor_id>/archive")
@endpoint(("ProgramAdmin",))
def archive_competitor(competitor_id):
    competitor = resolve(db.competitors, competitor_id, "ERR_COMPETITOR_NOT_FOUND")
    competitor["status"] = "ARCHIVED"
    touch(competitor)
    return object_response(serialize.competitor(competitor))


@bp.get("/competitors")
@endpoint(ANY_ROLE)
def list_competitors():
    program_id = fk_from_query("program_id", db.programs, "ERR_PROGRAM_NOT_FOUND")
    tier = query_enum("tier", COMPETITOR_TIER)
    status = query_enum("status", COMPETITOR_STATUS)
    limit, offset = pagination()
    rows = list(db.competitors.values())
    if program_id:
        rows = [c for c in rows if c["program_id"] == program_id]
    if tier:
        rows = [c for c in rows if c["tier"] == tier]
    if status:
        rows = [c for c in rows if c["status"] == status]
    rows = sorted(by_created_at(rows), key=lambda c: c["name"])
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.competitor(r) for r in page],
                         limit, offset, total)
