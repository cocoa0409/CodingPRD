"""Formal interpretation requests and their opinions (PRD 3.8)."""
from datetime import timedelta

from flask import Blueprint

import clock
import config
import db
import middleware
import response
import validate
from errors import ApiError
from routes.common import apply_filters, as_str, paged
from services import derive, lookup, serialize

bp = Blueprint("interpretations", __name__)

_ACTION_ROLES = {
    "ASSIGN": (config.ROLE_COUNCIL_ADMIN,),
    "ISSUE_OPINION": (config.ROLE_TECHNICAL_STAFF,),
    "PUBLISH": (config.ROLE_COUNCIL_ADMIN,),
    "APPEAL": (config.ROLE_JURISDICTION_OFFICIAL,),
    "DECLINE": (config.ROLE_COUNCIL_ADMIN,),
}

_ACTION_STATES = {
    "ASSIGN": ("SUBMITTED",),
    "ISSUE_OPINION": ("ASSIGNED",),
    "PUBLISH": ("OPINION_DRAFTED",),
    "APPEAL": ("PUBLISHED",),
    "DECLINE": ("SUBMITTED", "ASSIGNED"),
}


@bp.post("/interpretation-requests")
def create_interpretation_request():
    user_id, role = middleware.require((config.ROLE_COUNCIL_ADMIN,
                                        config.ROLE_JURISDICTION_OFFICIAL,
                                        config.ROLE_PETITIONER))
    middleware.resolve_identity(user_id, role)
    body = validate.body()
    adoption_rule_id = validate.req_string(body, "adoption_rule_id")
    code_section = validate.req_string(body, "code_section")
    question = validate.req_string(body, "question")
    jurisdiction_id = validate.opt_string(body, "jurisdiction_id")
    supersedes_request_id = validate.opt_string(body, "supersedes_request_id")

    rule = lookup.adoption_rule(adoption_rule_id)
    jurisdiction = lookup.jurisdiction(jurisdiction_id) if jurisdiction_id is not None else None
    predecessor = (lookup.interpretation_request(supersedes_request_id)
                   if supersedes_request_id is not None else None)

    if role == config.ROLE_JURISDICTION_OFFICIAL:
        if jurisdiction is None or jurisdiction["id"] != user_id:
            raise ApiError("ERR_JURISDICTION_MISMATCH")

    record = db.new_record({
        "adoption_rule_id": rule["id"],
        "jurisdiction_id": jurisdiction["id"] if jurisdiction is not None else None,
        "supersedes_request_id": predecessor["id"] if predecessor is not None else None,
        "assigned_committee_id": None,
        "code_section": code_section,
        "question": question,
        "requested_by_user_id": user_id,
        "opinion_text": None,
        "binding_scope": None,
        "opinion_number": None,
        "drafted_by_user_id": None,
        "published_by_user_id": None,
        "published_at": None,
        "appeal_round": 0,
        "decline_reason": None,
        "status": "SUBMITTED",
    })
    db.interpretation_requests[record["id"]] = record
    return response.object_response(serialize.interpretation_request(record), 201)


@bp.get("/interpretation-requests")
def list_interpretation_requests():
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    rows = apply_filters(list(db.interpretation_requests.values()), {
        "status": ("status", as_str),
        "code_section": ("code_section", as_str),
        "adoption_rule_id": ("adoption_rule_id", as_str),
        "jurisdiction_id": ("jurisdiction_id", as_str),
        "assigned_committee_id": ("assigned_committee_id", as_str),
        "supersedes_request_id": ("supersedes_request_id", as_str),
    })
    return paged(rows, serialize.interpretation_request, limit, offset)


@bp.get("/interpretation-requests/<request_id>")
def get_interpretation_request(request_id):
    middleware.require(config.ALL_ROLES)
    record = lookup.interpretation_request(request_id)
    return response.object_response(serialize.interpretation_request(record))


@bp.get("/interpretation-requests/<request_id>/superseding-requests")
def list_superseding_requests(request_id):
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    record = lookup.interpretation_request(request_id)
    rows = derive.children(db.interpretation_requests, "supersedes_request_id", record["id"])
    return paged(rows, serialize.interpretation_request, limit, offset)


@bp.post("/interpretation-requests/<request_id>/actions")
def act_on_interpretation_request(request_id):
    user_id, role = middleware.require((config.ROLE_COUNCIL_ADMIN,
                                        config.ROLE_TECHNICAL_STAFF,
                                        config.ROLE_JURISDICTION_OFFICIAL))
    body = validate.body()
    action = validate.req_enum(body, "action", tuple(_ACTION_ROLES))

    # priority 2 — the action itself carries its own role gate
    middleware.authorize(role, _ACTION_ROLES[action])
    middleware.resolve_identity(user_id, role)

    if action == "ASSIGN":
        return _assign(request_id, body)
    if action == "ISSUE_OPINION":
        return _issue_opinion(request_id, body, user_id)
    if action == "PUBLISH":
        return _publish(request_id, user_id)
    if action == "APPEAL":
        return _appeal(request_id, body, user_id)
    return _decline(request_id, body)


def _state_check(record, action):
    if record["status"] not in _ACTION_STATES[action]:
        raise ApiError("ERR_INTERPRETATION_STATE_INVALID")


def _assign(request_id, body):
    committee_id = validate.req_string(body, "assigned_committee_id")
    record = lookup.interpretation_request(request_id)
    committee = lookup.committee(committee_id)
    _state_check(record, "ASSIGN")

    rule = db.adoption_rules.get(record["adoption_rule_id"])
    if rule is None or rule["status"] not in ("PUBLISHED", "EFFECTIVE"):
        raise ApiError("ERR_ADOPTION_RULE_NOT_IN_FORCE")

    if rule["code_cycle_id"] != committee["code_cycle_id"]:
        raise ApiError("ERR_COMMITTEE_CYCLE_MISMATCH")

    record["assigned_committee_id"] = committee["id"]
    record["status"] = "ASSIGNED"
    db.touch(record)
    return response.object_response(serialize.interpretation_request(record))


def _issue_opinion(request_id, body, user_id):
    opinion_text = validate.req_string(body, "opinion_text")
    binding_scope = validate.req_enum(body, "binding_scope", config.BINDING_SCOPES)
    record = lookup.interpretation_request(request_id)
    _state_check(record, "ISSUE_OPINION")

    record["opinion_text"] = opinion_text
    record["binding_scope"] = binding_scope
    record["drafted_by_user_id"] = user_id
    record["status"] = "OPINION_DRAFTED"
    db.touch(record)
    return response.object_response(serialize.interpretation_request(record))


def _publish(request_id, user_id):
    record = lookup.interpretation_request(request_id)
    _state_check(record, "PUBLISH")

    if user_id == record["drafted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    rule = db.adoption_rules.get(record["adoption_rule_id"])
    if rule is not None:
        rule["_opinion_seq"] = int(rule.get("_opinion_seq") or 0) + 1
        opinion_number = rule["_opinion_seq"]
    else:
        opinion_number = 1

    record["status"] = "PUBLISHED"
    record["opinion_number"] = opinion_number
    record["published_by_user_id"] = user_id
    record["published_at"] = clock.now()
    db.touch(record)

    predecessor_id = record["supersedes_request_id"]
    if predecessor_id is not None:
        predecessor = db.interpretation_requests.get(predecessor_id)
        if predecessor is not None and predecessor["status"] == "PUBLISHED":
            predecessor["status"] = "SUPERSEDED"
            db.touch(predecessor)

    return response.object_response(serialize.interpretation_request(record))


def _appeal(request_id, body, user_id):
    validate.opt_string(body, "appeal_reason")
    record = lookup.interpretation_request(request_id)

    if record["jurisdiction_id"] is None or record["jurisdiction_id"] != user_id:
        raise ApiError("ERR_JURISDICTION_MISMATCH")

    _state_check(record, "APPEAL")

    published_at = record["published_at"]
    if (published_at is None
            or clock.now() > published_at + timedelta(days=config.APPEAL_WINDOW_DAYS)):
        raise ApiError("ERR_APPEAL_WINDOW_EXPIRED")

    if record["appeal_round"] >= config.APPEAL_ROUNDS_MAX:
        raise ApiError("ERR_APPEAL_ROUNDS_EXHAUSTED")

    record["appeal_round"] = record["appeal_round"] + 1
    record["opinion_text"] = None
    record["binding_scope"] = None
    record["drafted_by_user_id"] = None
    record["published_by_user_id"] = None
    record["published_at"] = None
    record["opinion_number"] = None
    record["status"] = "ASSIGNED"
    db.touch(record)
    return response.object_response(serialize.interpretation_request(record))


def _decline(request_id, body):
    decline_reason = validate.req_string(body, "decline_reason")
    record = lookup.interpretation_request(request_id)
    _state_check(record, "DECLINE")

    record["decline_reason"] = decline_reason
    record["status"] = "DECLINED"
    db.touch(record)
    return response.object_response(serialize.interpretation_request(record))
