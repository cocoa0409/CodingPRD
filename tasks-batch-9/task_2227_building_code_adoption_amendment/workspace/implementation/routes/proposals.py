"""Amendment proposals: intake, screening, comment window, reopen (PRD 3.2-3.4, 3.6)."""
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
from services import calc, cascades, derive, lookup, serialize

bp = Blueprint("proposals", __name__)

_SCREENING_REVIEW_SOURCES = {
    "ACCEPT_FOR_ANALYSIS": ("SUBMITTED", "RETURNED_FOR_REVISION"),
    "REJECT": ("SUBMITTED",),
    "WITHDRAW": ("SUBMITTED",),
}

_SCREENING_CYCLE_STATES = {
    ("ACCEPT_FOR_ANALYSIS", "SUBMITTED"): ("INTAKE_OPEN", "INTAKE_CLOSED"),
    ("ACCEPT_FOR_ANALYSIS", "RETURNED_FOR_REVISION"): ("INTAKE_OPEN", "INTAKE_CLOSED", "DELIBERATION"),
    ("REJECT", "SUBMITTED"): ("INTAKE_OPEN", "INTAKE_CLOSED"),
    ("WITHDRAW", "SUBMITTED"): ("INTAKE_OPEN", "INTAKE_CLOSED", "DELIBERATION"),
}


@bp.post("/amendment-proposals")
def create_proposal():
    user_id, _ = middleware.require((config.ROLE_COUNCIL_ADMIN, config.ROLE_TECHNICAL_STAFF,
                                     config.ROLE_JURISDICTION_OFFICIAL, config.ROLE_PETITIONER))
    body = validate.body()
    code_cycle_id = validate.req_string(body, "code_cycle_id")
    code_section = validate.req_string(body, "code_section")
    discipline = validate.req_enum(body, "discipline", config.DISCIPLINES)
    title = validate.req_string(body, "title")
    proposed_text = validate.req_string(body, "proposed_text")
    stringency_direction = validate.req_enum(body, "stringency_direction",
                                            config.STRINGENCY_DIRECTIONS)
    proposer_sector = validate.req_enum(body, "proposer_sector", config.SECTORS)

    cycle = lookup.code_cycle(code_cycle_id)
    if cycle["status"] != "INTAKE_OPEN":
        raise ApiError("ERR_CYCLE_STATE_INVALID")

    candidates = [c for c in derive.children(db.discipline_committees,
                                             "code_cycle_id", cycle["id"])
                  if c["discipline"] == discipline and c["status"] != "DISSOLVED"]
    if not candidates:
        raise ApiError("ERR_NO_COMMITTEE_FOR_DISCIPLINE")
    committee = db.ordered(candidates)[0]

    record = db.new_record({
        "code_cycle_id": cycle["id"],
        "committee_id": committee["id"],
        "code_section": code_section,
        "discipline": discipline,
        "title": title,
        "proposed_text": proposed_text,
        "stringency_direction": stringency_direction,
        "proposer_sector": proposer_sector,
        "submitted_by_user_id": user_id,
        "review_status": "SUBMITTED",
        "analysis_status": "NOT_STARTED",
        "affected_permit_count": None,
        "statewide_incremental_cost_cents": None,
        "preliminary_benefit_cost_ratio": None,
        "final_benefit_cost_ratio": None,
        "comment_window_status": "NONE",
        "comment_opens_at": None,
        "comment_closes_at": None,
        "comment_extension_count": 0,
        "comment_round": 0,
        "revision_round": 0,
        "base_docket_score": None,
        "docket_queue_rank": None,
        "docket_priority_score": None,
    })
    db.amendment_proposals[record["id"]] = record
    return response.object_response(serialize.amendment_proposal(record), 201)


@bp.get("/amendment-proposals")
def list_proposals():
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    rows = apply_filters(list(db.amendment_proposals.values()), {
        "review_status": ("review_status", as_str),
        "analysis_status": ("analysis_status", as_str),
        "discipline": ("discipline", as_str),
        "code_cycle_id": ("code_cycle_id", as_str),
        "committee_id": ("committee_id", as_str),
    })
    return paged(rows, serialize.amendment_proposal, limit, offset)


@bp.get("/amendment-proposals/<proposal_id>")
def get_proposal(proposal_id):
    middleware.require(config.ALL_ROLES)
    record = lookup.proposal(proposal_id)
    return response.object_response(serialize.amendment_proposal(record))


@bp.post("/amendment-proposals/<proposal_id>/screening")
def screen_proposal(proposal_id):
    middleware.require((config.ROLE_TECHNICAL_STAFF,))
    body = validate.body()
    decision = validate.req_enum(body, "decision",
                                 ("ACCEPT_FOR_ANALYSIS", "REJECT", "WITHDRAW"))
    proposal = lookup.proposal(proposal_id)

    review_status = proposal["review_status"]
    if review_status not in _SCREENING_REVIEW_SOURCES[decision]:
        raise ApiError("ERR_PROPOSAL_STATE_INVALID")

    cycle = db.code_cycles.get(proposal["code_cycle_id"])
    allowed_cycle_states = _SCREENING_CYCLE_STATES[(decision, review_status)]
    if cycle is None or cycle["status"] not in allowed_cycle_states:
        raise ApiError("ERR_CYCLE_STATE_INVALID")

    if decision == "ACCEPT_FOR_ANALYSIS":
        proposal["review_status"] = "SCREENED"
        if proposal["analysis_status"] in ("NOT_STARTED", "STALE"):
            proposal["analysis_status"] = "PENDING"
    elif decision == "REJECT":
        proposal["review_status"] = "REJECTED"
    else:
        proposal["review_status"] = "WITHDRAWN"
    db.touch(proposal)
    return response.object_response(serialize.amendment_proposal(proposal))


@bp.post("/amendment-proposals/<proposal_id>/comment-window")
def comment_window(proposal_id):
    middleware.require((config.ROLE_COUNCIL_ADMIN,))
    body = validate.body()
    action = validate.req_enum(body, "action", ("OPEN", "EXTEND", "CLOSE"))
    opens_at = closes_at = None
    if action == "OPEN":
        opens_at = validate.req_dt(body, "opens_at")
        closes_at = validate.req_dt(body, "closes_at")
        if closes_at <= opens_at:
            raise validate.bad_request("closes_at must be later than opens_at.")

    proposal = lookup.proposal(proposal_id)

    required_state = "SCREENED" if action == "OPEN" else "COMMENT_OPEN"
    if proposal["review_status"] != required_state:
        raise ApiError("ERR_PROPOSAL_STATE_INVALID")

    if action == "OPEN":
        if proposal["analysis_status"] != "COMPLETE":
            raise ApiError("ERR_ANALYSIS_INCOMPLETE")
        cycle = db.code_cycles.get(proposal["code_cycle_id"])
        if cycle is None or cycle["status"] not in ("INTAKE_CLOSED", "DELIBERATION"):
            raise ApiError("ERR_CYCLE_STATE_INVALID")
        if closes_at - opens_at < timedelta(days=config.COMMENT_MIN_DAYS):
            raise ApiError("ERR_COMMENT_PERIOD_TOO_SHORT")
        proposal["review_status"] = "COMMENT_OPEN"
        proposal["comment_window_status"] = "OPEN"
        proposal["comment_opens_at"] = opens_at
        proposal["comment_closes_at"] = closes_at
        proposal["comment_round"] = proposal["comment_round"] + 1
        proposal["comment_extension_count"] = 0
    elif action == "EXTEND":
        if proposal["comment_extension_count"] >= config.COMMENT_EXTENSIONS_MAX:
            raise ApiError("ERR_COMMENT_EXTENSIONS_EXHAUSTED")
        proposal["comment_closes_at"] = (proposal["comment_closes_at"]
                                        + timedelta(days=config.COMMENT_EXTENSION_DAYS))
        proposal["comment_extension_count"] = proposal["comment_extension_count"] + 1
    else:
        if proposal["comment_closes_at"] is None or clock.now() < proposal["comment_closes_at"]:
            raise ApiError("ERR_COMMENT_WINDOW_STILL_OPEN")
        proposal["review_status"] = "COMMENT_CLOSED"
        proposal["comment_window_status"] = "CLOSED"
        support, oppose, _ = derive.comment_tallies(proposal)
        proposal["base_docket_score"] = calc.base_docket_score(
            support, oppose, proposal["stringency_direction"],
            proposal["statewide_incremental_cost_cents"])

    db.touch(proposal)
    return response.object_response(serialize.amendment_proposal(proposal))


@bp.post("/amendment-proposals/<proposal_id>/reopen")
def reopen_proposal(proposal_id):
    middleware.require((config.ROLE_COUNCIL_ADMIN,))
    body = validate.body()
    validate.req_string(body, "reason")
    proposal = lookup.proposal(proposal_id)

    if proposal["review_status"] not in ("COMMENT_CLOSED", "APPROVED"):
        raise ApiError("ERR_PROPOSAL_STATE_INVALID")

    cycle = db.code_cycles.get(proposal["code_cycle_id"])
    if cycle is None or cycle["status"] not in ("DELIBERATION", "RULEMAKING"):
        raise ApiError("ERR_CYCLE_STATE_INVALID")

    if proposal["review_status"] == "APPROVED":
        for rule in derive.children(db.adoption_rules, "code_cycle_id", cycle["id"]):
            if rule["status"] in ("FILED", "PUBLISHED", "EFFECTIVE"):
                raise ApiError("ERR_ADOPTION_RULE_STATE_INVALID")

    cascades.reopen_proposal(proposal, cycle)
    return response.object_response(serialize.amendment_proposal(proposal))


@bp.get("/amendment-proposals/<proposal_id>/vote-records")
def list_proposal_vote_records(proposal_id):
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    proposal = lookup.proposal(proposal_id)
    rows = derive.children(db.vote_records, "proposal_id", proposal["id"])
    return paged(rows, serialize.vote_record, limit, offset)
