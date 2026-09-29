"""Adoption (rulemaking) orders (PRD 3.7)."""
from flask import Blueprint

import clock
import config
import db
import middleware
import response
import validate
from errors import ApiError
from routes.common import apply_filters, as_str, paged
from services import calc, cascades, derive, lookup, serialize

bp = Blueprint("rules", __name__)

_OPERATOR_TRANSITIONS = {
    ("DRAFT", "FILED"),
    ("FILED", "PUBLISHED"),
    ("PUBLISHED", "EFFECTIVE"),
    ("FILED", "WITHDRAWN"),
    ("PUBLISHED", "WITHDRAWN"),
}


@bp.post("/adoption-rules")
def create_adoption_rule():
    middleware.require((config.ROLE_COUNCIL_ADMIN,))
    body = validate.body()
    code_cycle_id = validate.req_string(body, "code_cycle_id")
    title = validate.req_string(body, "title")
    cycle = lookup.code_cycle(code_cycle_id)

    ledger = derive.cycle_ledger(cycle["id"])
    base_date = calc.midnight(clock.now())
    schedule = calc.adoption_schedule(base_date, ledger["approved_permit_backlog_count"])

    fields = {
        "code_cycle_id": cycle["id"],
        "title": title,
        "base_date": base_date,
        "approved_incremental_cost_cents_at_filing": None,
        # Nothing is pinned until the order is filed (PRD 3.7); an unfiled order
        # therefore carries the empty pin map rather than a missing one.
        "pinned_amendment_versions": {},
        "status": "DRAFT",
        "filed_by_user_id": None,
        "published_by_user_id": None,
        "published_at": None,
        "statewide_readiness_pct_at_effective": None,
        "withdrawal_reason": None,
        "_opinion_seq": 0,
    }
    fields.update(schedule)
    record = db.new_record(fields)
    db.adoption_rules[record["id"]] = record
    return response.object_response(serialize.adoption_rule(record), 201)


@bp.get("/adoption-rules")
def list_adoption_rules():
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    rows = apply_filters(list(db.adoption_rules.values()), {
        "status": ("status", as_str),
        "code_cycle_id": ("code_cycle_id", as_str),
    })
    return paged(rows, serialize.adoption_rule, limit, offset)


@bp.get("/adoption-rules/<adoption_rule_id>")
def get_adoption_rule(adoption_rule_id):
    middleware.require(config.ALL_ROLES)
    record = lookup.adoption_rule(adoption_rule_id)
    return response.object_response(serialize.adoption_rule(record))


@bp.post("/adoption-rules/<adoption_rule_id>/status")
def set_adoption_rule_status(adoption_rule_id):
    user_id, _ = middleware.require((config.ROLE_COUNCIL_ADMIN,))
    body = validate.body()
    to_status = validate.req_enum(body, "to_status", config.ADOPTION_RULE_STATUSES)
    withdrawal_reason = validate.opt_string(body, "withdrawal_reason")
    rule = lookup.adoption_rule(adoption_rule_id)

    if (rule["status"], to_status) not in _OPERATOR_TRANSITIONS:
        raise ApiError("ERR_ADOPTION_RULE_STATE_INVALID")

    cycle = db.code_cycles.get(rule["code_cycle_id"])
    ledger = derive.cycle_ledger(rule["code_cycle_id"])

    if to_status == "FILED":
        if cycle is None or cycle["status"] != "RULEMAKING":
            raise ApiError("ERR_CYCLE_STATE_INVALID")

    if to_status == "PUBLISHED":
        if user_id == rule["filed_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if to_status == "EFFECTIVE":
        if rule["effective_date"] is None or clock.now() < rule["effective_date"]:
            raise ApiError("ERR_EFFECTIVE_DATE_NOT_REACHED")

    if to_status == "FILED":
        if ledger["approved_proposal_count"] < 1:
            raise ApiError("ERR_NO_APPROVED_AMENDMENTS")

    readiness = None
    if to_status == "EFFECTIVE":
        readiness = derive.statewide_readiness_pct()
        if readiness < config.READINESS_THRESHOLD_PCT:
            raise ApiError("ERR_TRAINING_READINESS_NOT_MET")

    if to_status == "FILED":
        pinned = {}
        for proposal in db.ordered(derive.approved_proposals_of_cycle(rule["code_cycle_id"])):
            pinned[proposal["id"]] = proposal["version"]
        rule["pinned_amendment_versions"] = pinned
        rule["approved_incremental_cost_cents_at_filing"] = \
            ledger["approved_incremental_cost_cents"]
        rule["filed_by_user_id"] = user_id
        rule["status"] = "FILED"
        db.touch(rule)
    elif to_status == "PUBLISHED":
        rule["status"] = "PUBLISHED"
        rule["published_by_user_id"] = user_id
        rule["published_at"] = clock.now()
        db.touch(rule)
    elif to_status == "EFFECTIVE":
        cascades.make_rule_effective(rule, cycle, readiness)
    else:
        if rule["status"] == "PUBLISHED":
            cascades.withdraw_published_rule(rule, withdrawal_reason)
        else:
            rule["status"] = "WITHDRAWN"
            rule["withdrawal_reason"] = withdrawal_reason
            db.touch(rule)

    return response.object_response(serialize.adoption_rule(rule))


@bp.get("/adoption-rules/<adoption_rule_id>/local-amendments")
def list_rule_local_amendments(adoption_rule_id):
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    rule = lookup.adoption_rule(adoption_rule_id)
    rows = derive.children(db.local_amendments, "adoption_rule_id", rule["id"])
    return paged(rows, serialize.local_amendment, limit, offset)


@bp.get("/adoption-rules/<adoption_rule_id>/interpretation-requests")
def list_rule_interpretations(adoption_rule_id):
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    rule = lookup.adoption_rule(adoption_rule_id)
    rows = derive.children(db.interpretation_requests, "adoption_rule_id", rule["id"])
    return paged(rows, serialize.interpretation_request, limit, offset)


@bp.get("/adoption-rules/<adoption_rule_id>/training-sessions")
def list_rule_training_sessions(adoption_rule_id):
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    rule = lookup.adoption_rule(adoption_rule_id)
    rows = derive.children(db.training_sessions, "adoption_rule_id", rule["id"])
    return paged(rows, serialize.training_session, limit, offset)
