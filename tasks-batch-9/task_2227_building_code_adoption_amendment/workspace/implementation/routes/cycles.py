"""Code cycles (PRD 3.1) and their sub-collections."""
from flask import Blueprint

import config
import db
import middleware
import response
import validate
from errors import ApiError
from routes.common import apply_filters, as_int, as_str, paged
from services import derive, lookup, serialize

bp = Blueprint("cycles", __name__)

_OPERATOR_TRANSITIONS = {
    ("DRAFT", "INTAKE_OPEN"),
    ("INTAKE_OPEN", "INTAKE_CLOSED"),
    ("INTAKE_CLOSED", "DELIBERATION"),
    ("DELIBERATION", "RULEMAKING"),
    ("DRAFT", "ABANDONED"),
    ("INTAKE_OPEN", "ABANDONED"),
}

RESOLVED_REVIEW_STATUSES = ("APPROVED", "REJECTED", "WITHDRAWN")


@bp.post("/code-cycles")
def create_code_cycle():
    middleware.require((config.ROLE_COUNCIL_ADMIN,))
    body = validate.body()
    cycle_year = validate.req_int(body, "cycle_year",
                                 config.CYCLE_YEAR_MIN, config.CYCLE_YEAR_MAX)
    model_code_edition = validate.req_string(body, "model_code_edition")
    intake_opens_at = validate.req_dt(body, "intake_opens_at")
    intake_closes_at = validate.req_dt(body, "intake_closes_at")

    for existing in db.code_cycles.values():
        if (existing["cycle_year"] == cycle_year
                and existing["model_code_edition"] == model_code_edition):
            raise ApiError("ERR_DUPLICATE_CODE_CYCLE")

    record = db.new_record({
        "cycle_year": cycle_year,
        "model_code_edition": model_code_edition,
        "intake_opens_at": intake_opens_at,
        "intake_closes_at": intake_closes_at,
        "status": "DRAFT",
    })
    db.code_cycles[record["id"]] = record
    return response.object_response(serialize.code_cycle(record), 201)


@bp.get("/code-cycles")
def list_code_cycles():
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    rows = apply_filters(list(db.code_cycles.values()), {
        "status": ("status", as_str),
        "cycle_year": ("cycle_year", as_int),
    })
    return paged(rows, serialize.code_cycle, limit, offset)


@bp.get("/code-cycles/<cycle_id>")
def get_code_cycle(cycle_id):
    middleware.require(config.ALL_ROLES)
    record = lookup.code_cycle(cycle_id)
    return response.object_response(serialize.code_cycle(record))


@bp.post("/code-cycles/<cycle_id>/status")
def set_code_cycle_status(cycle_id):
    middleware.require((config.ROLE_COUNCIL_ADMIN,))
    body = validate.body()
    to_status = validate.req_enum(body, "to_status", config.CYCLE_STATUSES)
    cycle = lookup.code_cycle(cycle_id)

    if (cycle["status"], to_status) not in _OPERATOR_TRANSITIONS:
        raise ApiError("ERR_CYCLE_STATE_INVALID")

    if to_status == "INTAKE_OPEN":
        if derive.seated_committee_count(cycle["id"]) < 1:
            raise ApiError("ERR_COMMITTEE_NOT_SEATED")

    proposals = derive.proposals_of_cycle(cycle["id"])
    if to_status == "RULEMAKING":
        unresolved = [p for p in proposals
                      if p["review_status"] not in RESOLVED_REVIEW_STATUSES]
        if unresolved:
            raise ApiError("ERR_PROPOSALS_UNRESOLVED")
    if to_status == "ABANDONED":
        if proposals:
            raise ApiError("ERR_PROPOSALS_UNRESOLVED")

    cycle["status"] = to_status
    db.touch(cycle)

    if to_status == "ABANDONED":
        for committee in db.ordered(derive.children(db.discipline_committees,
                                                    "code_cycle_id", cycle["id"])):
            if committee["status"] != "DISSOLVED":
                committee["status"] = "DISSOLVED"
                db.touch(committee)

    return response.object_response(serialize.code_cycle(cycle))


@bp.post("/code-cycles/<cycle_id>/discipline-committees")
def create_committee(cycle_id):
    middleware.require((config.ROLE_COUNCIL_ADMIN,))
    body = validate.body()
    discipline = validate.req_enum(body, "discipline", config.DISCIPLINES)
    voting_seat_count = validate.req_int(body, "voting_seat_count",
                                        config.VOTING_SEAT_COUNT_MIN,
                                        config.VOTING_SEAT_COUNT_MAX)
    cycle = lookup.code_cycle(cycle_id)

    for existing in derive.children(db.discipline_committees, "code_cycle_id", cycle["id"]):
        if existing["discipline"] == discipline and existing["status"] != "DISSOLVED":
            raise ApiError("ERR_DUPLICATE_COMMITTEE_DISCIPLINE")

    record = db.new_record({
        "code_cycle_id": cycle["id"],
        "discipline": discipline,
        "voting_seat_count": voting_seat_count,
        "status": "FORMING",
    })
    db.discipline_committees[record["id"]] = record
    return response.object_response(serialize.discipline_committee(record), 201)


@bp.get("/code-cycles/<cycle_id>/discipline-committees")
def list_cycle_committees(cycle_id):
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    cycle = lookup.code_cycle(cycle_id)
    rows = derive.children(db.discipline_committees, "code_cycle_id", cycle["id"])
    return paged(rows, serialize.discipline_committee, limit, offset)


@bp.get("/code-cycles/<cycle_id>/amendment-proposals")
def list_cycle_proposals(cycle_id):
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    cycle = lookup.code_cycle(cycle_id)
    rows = derive.proposals_of_cycle(cycle["id"])
    return paged(rows, serialize.amendment_proposal, limit, offset)


@bp.get("/code-cycles/<cycle_id>/adoption-rules")
def list_cycle_adoption_rules(cycle_id):
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    cycle = lookup.code_cycle(cycle_id)
    rows = derive.children(db.adoption_rules, "code_cycle_id", cycle["id"])
    return paged(rows, serialize.adoption_rule, limit, offset)
