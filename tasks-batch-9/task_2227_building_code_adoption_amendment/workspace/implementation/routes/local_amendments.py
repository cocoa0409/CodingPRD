"""Local amendments (PRD 3.8)."""
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
from services import lookup, serialize

bp = Blueprint("local_amendments", __name__)

_LIVE_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "RETURNED", "FILED_EFFECTIVE")


def _within_window(rule, moment):
    published_at = rule["published_at"]
    if published_at is None:
        return False
    return moment <= published_at + timedelta(days=config.LOCAL_FILING_WINDOW_DAYS)


@bp.post("/local-amendments")
def create_local_amendment():
    user_id, role = middleware.require((config.ROLE_JURISDICTION_OFFICIAL,))
    middleware.resolve_identity(user_id, role)
    body = validate.body()
    expected_jurisdiction_version = validate.req_int(body, "expected_jurisdiction_version")
    jurisdiction_id = validate.req_string(body, "jurisdiction_id")
    adoption_rule_id = validate.req_string(body, "adoption_rule_id")
    code_section = validate.req_string(body, "code_section")
    local_text = validate.req_string(body, "local_text")
    stringency_direction = validate.req_enum(body, "stringency_direction",
                                            config.LOCAL_STRINGENCY_DIRECTIONS)
    justification = validate.req_string(body, "justification")

    jurisdiction = lookup.jurisdiction(jurisdiction_id)
    rule = lookup.adoption_rule(adoption_rule_id)

    if jurisdiction["id"] != user_id:
        raise ApiError("ERR_JURISDICTION_MISMATCH")

    if expected_jurisdiction_version != jurisdiction["version"]:
        raise ApiError("ERR_STALE_JURISDICTION_VERSION")

    if jurisdiction["local_authority_level"] == "NONE":
        raise ApiError("ERR_LOCAL_AUTHORITY_ABSENT")

    for existing in db.local_amendments.values():
        if (existing["jurisdiction_id"] == jurisdiction["id"]
                and existing["adoption_rule_id"] == rule["id"]
                and existing["code_section"] == code_section
                and existing["status"] not in ("REJECTED", "VOIDED")):
            raise ApiError("ERR_DUPLICATE_LOCAL_AMENDMENT")

    record = db.new_record({
        "jurisdiction_id": jurisdiction["id"],
        "adoption_rule_id": rule["id"],
        "code_section": code_section,
        "local_text": local_text,
        "stringency_direction": stringency_direction,
        "justification": justification,
        "filed_within_window": False,
        "revision_round": 0,
        "reviewed_by_user_id": None,
        "status": "SUBMITTED",
    })
    record["filed_within_window"] = _within_window(rule, record["created_at"])
    db.local_amendments[record["id"]] = record
    db.touch(jurisdiction)
    return response.object_response(serialize.local_amendment(record), 201)


@bp.get("/local-amendments")
def list_local_amendments():
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    rows = apply_filters(list(db.local_amendments.values()), {
        "jurisdiction_id": ("jurisdiction_id", as_str),
        "adoption_rule_id": ("adoption_rule_id", as_str),
        "status": ("status", as_str),
    })
    return paged(rows, serialize.local_amendment, limit, offset)


@bp.get("/local-amendments/<local_amendment_id>")
def get_local_amendment(local_amendment_id):
    middleware.require(config.ALL_ROLES)
    record = lookup.local_amendment(local_amendment_id)
    return response.object_response(serialize.local_amendment(record))


@bp.post("/local-amendments/<local_amendment_id>/review")
def review_local_amendment(local_amendment_id):
    user_id, _ = middleware.require((config.ROLE_COUNCIL_ADMIN,))
    body = validate.body()
    decision = validate.req_enum(body, "decision",
                                 ("START_REVIEW", "ACCEPT", "RETURN", "REJECT"))
    amendment = lookup.local_amendment(local_amendment_id)

    required = "SUBMITTED" if decision == "START_REVIEW" else "UNDER_REVIEW"
    if amendment["status"] != required:
        raise ApiError("ERR_LOCAL_AMENDMENT_STATE_INVALID")

    rule = db.adoption_rules.get(amendment["adoption_rule_id"])
    jurisdiction = db.jurisdictions.get(amendment["jurisdiction_id"])

    if decision == "START_REVIEW":
        if rule is None or rule["status"] not in ("PUBLISHED", "EFFECTIVE"):
            raise ApiError("ERR_ADOPTION_RULE_NOT_IN_FORCE")
        amendment["status"] = "UNDER_REVIEW"
        amendment["reviewed_by_user_id"] = user_id
        db.touch(amendment)
        return response.object_response(serialize.local_amendment(amendment))

    if decision == "ACCEPT":
        if amendment["stringency_direction"] == "LESS_STRINGENT":
            raise ApiError("ERR_LOCAL_LESS_STRINGENT_FORBIDDEN")
        if jurisdiction is None or jurisdiction["local_authority_level"] not in ("FULL", "LIMITED"):
            raise ApiError("ERR_LOCAL_AUTHORITY_ABSENT")
        if not amendment["filed_within_window"]:
            raise ApiError("ERR_LOCAL_FILING_DEADLINE_PASSED")
        amendment["status"] = "FILED_EFFECTIVE"
        db.touch(amendment)
        db.touch(jurisdiction)
    elif decision == "RETURN":
        amendment["status"] = "RETURNED"
        db.touch(amendment)
    else:
        amendment["status"] = "REJECTED"
        db.touch(amendment)

    return response.object_response(serialize.local_amendment(amendment))


@bp.post("/local-amendments/<local_amendment_id>/resubmit")
def resubmit_local_amendment(local_amendment_id):
    user_id, role = middleware.require((config.ROLE_JURISDICTION_OFFICIAL,))
    middleware.resolve_identity(user_id, role)
    body = validate.body()
    local_text = validate.req_string(body, "local_text")
    stringency_direction = validate.req_enum(body, "stringency_direction",
                                            config.LOCAL_STRINGENCY_DIRECTIONS)
    justification = validate.req_string(body, "justification")
    amendment = lookup.local_amendment(local_amendment_id)

    if amendment["jurisdiction_id"] != user_id:
        raise ApiError("ERR_JURISDICTION_MISMATCH")

    if amendment["status"] != "RETURNED":
        raise ApiError("ERR_LOCAL_AMENDMENT_STATE_INVALID")

    if amendment["revision_round"] >= config.LOCAL_REVISION_ROUNDS_MAX:
        raise ApiError("ERR_LOCAL_REVISION_ROUNDS_EXHAUSTED")

    rule = db.adoption_rules.get(amendment["adoption_rule_id"])
    amendment["status"] = "SUBMITTED"
    amendment["revision_round"] = amendment["revision_round"] + 1
    amendment["local_text"] = local_text
    amendment["stringency_direction"] = stringency_direction
    amendment["justification"] = justification
    amendment["filed_within_window"] = (_within_window(rule, clock.now())
                                        if rule is not None else False)
    db.touch(amendment)
    return response.object_response(serialize.local_amendment(amendment))
