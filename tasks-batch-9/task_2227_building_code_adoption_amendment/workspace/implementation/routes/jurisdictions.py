"""Jurisdictions (PRD 3.8) and their read sub-collections."""
from flask import Blueprint, request

import config
import db
import middleware
import response
import validate
from errors import ApiError
from routes.common import apply_filters, as_str, paged
from services import derive, lookup, serialize

bp = Blueprint("jurisdictions", __name__)


@bp.post("/jurisdictions")
def create_jurisdiction():
    middleware.require((config.ROLE_COUNCIL_ADMIN,))
    body = validate.body()
    name = validate.req_string(body, "name")
    population = validate.req_int(body, "population", 0)
    local_authority_level = validate.req_enum(body, "local_authority_level",
                                             config.LOCAL_AUTHORITY_LEVELS)
    host_seat_capacity = validate.req_int(body, "host_seat_capacity", 0)
    official_headcount = validate.req_int(body, "official_headcount", 1)

    for existing in db.jurisdictions.values():
        if existing["name"] == name:
            raise ApiError("ERR_DUPLICATE_JURISDICTION")

    record = db.new_record({
        "name": name,
        "population": population,
        "local_authority_level": local_authority_level,
        "host_seat_capacity": host_seat_capacity,
        "official_headcount": official_headcount,
    })
    db.jurisdictions[record["id"]] = record
    return response.object_response(serialize.jurisdiction(record), 201)


@bp.get("/jurisdictions")
def list_jurisdictions():
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    rows = list(db.jurisdictions.values())
    rows = apply_filters(rows, {"local_authority_level": ("local_authority_level", as_str)})
    readiness = request.args.get("enforcement_readiness")
    if readiness:
        rows = [row for row in rows
                if derive.jurisdiction_compliance(row)[2] == readiness]
    return paged(rows, serialize.jurisdiction, limit, offset)


@bp.get("/jurisdictions/<jurisdiction_id>")
def get_jurisdiction(jurisdiction_id):
    middleware.require(config.ALL_ROLES)
    record = lookup.jurisdiction(jurisdiction_id)
    return response.object_response(serialize.jurisdiction(record))


@bp.get("/jurisdictions/<jurisdiction_id>/local-amendments")
def list_jurisdiction_local_amendments(jurisdiction_id):
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    jurisdiction = lookup.jurisdiction(jurisdiction_id)
    rows = derive.children(db.local_amendments, "jurisdiction_id", jurisdiction["id"])
    return paged(rows, serialize.local_amendment, limit, offset)


@bp.get("/jurisdictions/<jurisdiction_id>/interpretation-requests")
def list_jurisdiction_interpretations(jurisdiction_id):
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    jurisdiction = lookup.jurisdiction(jurisdiction_id)
    rows = derive.children(db.interpretation_requests, "jurisdiction_id", jurisdiction["id"])
    return paged(rows, serialize.interpretation_request, limit, offset)


@bp.get("/jurisdictions/<jurisdiction_id>/hosted-training-sessions")
def list_jurisdiction_hosted_sessions(jurisdiction_id):
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    jurisdiction = lookup.jurisdiction(jurisdiction_id)
    rows = derive.children(db.training_sessions, "host_jurisdiction_id", jurisdiction["id"])
    return paged(rows, serialize.training_session, limit, offset)


@bp.get("/jurisdictions/<jurisdiction_id>/training-enrollments")
def list_jurisdiction_enrollments(jurisdiction_id):
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    jurisdiction = lookup.jurisdiction(jurisdiction_id)
    rows = derive.children(db.training_enrollments, "jurisdiction_id", jurisdiction["id"])
    return paged(rows, serialize.training_enrollment, limit, offset)
