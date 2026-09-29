"""Hearings: scheduling, agenda, convening, ballots, adjournment (PRD 3.5)."""
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

bp = Blueprint("hearings", __name__)


def _require_chair(user_id, role, hearing):
    """Priority 9: the acting identity must chair this hearing's committee."""
    member = db.committee_members.get(user_id)
    if (member is None
            or not member["is_chair"]
            or member["status"] != "ACTIVE"
            or member["committee_id"] != hearing["committee_id"]):
        raise ApiError("ERR_NOT_COMMITTEE_CHAIR")
    return member


@bp.post("/hearings")
def create_hearing():
    middleware.require((config.ROLE_COUNCIL_ADMIN,))
    body = validate.body()
    committee_id = validate.req_string(body, "committee_id")
    scheduled_start = validate.req_dt(body, "scheduled_start")
    scheduled_end = validate.req_dt(body, "scheduled_end")
    if scheduled_end <= scheduled_start:
        raise validate.bad_request("scheduled_end must be later than scheduled_start.")

    committee = lookup.committee(committee_id)
    if committee["status"] != "SEATED":
        raise ApiError("ERR_COMMITTEE_NOT_SEATED")

    if scheduled_start < clock.now() + timedelta(days=config.HEARING_NOTICE_DAYS):
        raise ApiError("ERR_HEARING_NOTICE_TOO_SHORT")

    buffer = timedelta(minutes=config.HEARING_BUFFER_MINUTES)
    padded_start = scheduled_start - buffer
    padded_end = scheduled_end + buffer
    for other in derive.children(db.hearings, "committee_id", committee["id"]):
        if other["status"] not in ("SCHEDULED", "CONVENED"):
            continue
        if padded_start < other["scheduled_end"] and other["scheduled_start"] < padded_end:
            raise ApiError("ERR_HEARING_TIME_CONFLICT")

    record = db.new_record({
        "committee_id": committee["id"],
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
        "agenda_proposal_ids": [],
        "present_member_ids": None,
        "present_voting_count": None,
        "quorum_required_at_convene": None,
        "convened_at": None,
        "adjourned_at": None,
    })
    db.hearings[record["id"]] = record
    return response.object_response(serialize.hearing(record), 201)


@bp.get("/hearings")
def list_hearings():
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    rows = apply_filters(list(db.hearings.values()), {
        "status": ("status", as_str),
        "committee_id": ("committee_id", as_str),
    })
    return paged(rows, serialize.hearing, limit, offset)


@bp.get("/hearings/<hearing_id>")
def get_hearing(hearing_id):
    middleware.require(config.ALL_ROLES)
    record = lookup.hearing(hearing_id)
    return response.object_response(serialize.hearing(record))


@bp.post("/hearings/<hearing_id>/agenda")
def fill_agenda(hearing_id):
    middleware.require((config.ROLE_COUNCIL_ADMIN,))
    body = validate.body()
    validate.req_enum(body, "mode", ("AUTO_FILL",))
    hearing = lookup.hearing(hearing_id)

    if hearing["status"] != "SCHEDULED":
        raise ApiError("ERR_HEARING_STATE_INVALID")

    committee = db.discipline_committees.get(hearing["committee_id"])
    committed = set()
    for other in db.hearings.values():
        if other["id"] == hearing["id"]:
            continue
        if other["status"] in ("SCHEDULED", "CONVENED"):
            committed.update(other["agenda_proposal_ids"])

    pool = []
    for proposal in db.amendment_proposals.values():
        if proposal["committee_id"] != hearing["committee_id"]:
            continue
        if committee is not None and proposal["code_cycle_id"] != committee["code_cycle_id"]:
            continue
        if proposal["review_status"] != "COMMENT_CLOSED":
            continue
        if proposal["analysis_status"] != "COMPLETE":
            continue
        if proposal["id"] in committed:
            continue
        pool.append(proposal)

    if not pool:
        raise ApiError("ERR_NO_ELIGIBLE_PROPOSALS")

    pool.sort(key=lambda p: (-calc.dec(p["base_docket_score"] or 0),
                             p["created_at"], p["_seq"]))
    selected = pool[:config.AGENDA_MAX_ITEMS]

    hearing["agenda_proposal_ids"] = [p["id"] for p in selected]
    db.touch(hearing)

    for index, proposal in enumerate(selected, start=1):
        proposal["docket_queue_rank"] = index
        proposal["docket_priority_score"] = calc.docket_priority_score(
            proposal["base_docket_score"] or 0, index)
        db.touch(proposal)

    return response.object_response(serialize.hearing(hearing))


@bp.post("/hearings/<hearing_id>/convene")
def convene_hearing(hearing_id):
    user_id, role = middleware.require((config.ROLE_COUNCIL_CHAIR,))
    middleware.resolve_identity(user_id, role)
    body = validate.body()
    present_member_ids = validate.req_id_list(body, "present_member_ids")
    hearing = lookup.hearing(hearing_id)
    _require_chair(user_id, role, hearing)

    if hearing["status"] != "SCHEDULED":
        raise ApiError("ERR_HEARING_STATE_INVALID")

    committee = db.discipline_committees.get(hearing["committee_id"])
    if committee is None or committee["status"] != "SEATED":
        raise ApiError("ERR_COMMITTEE_NOT_SEATED")

    present_voting_count = 0
    seen = set()
    for member_id in present_member_ids:
        if member_id in seen:
            continue
        seen.add(member_id)
        member = db.committee_members.get(member_id)
        if (member is not None and member["committee_id"] == committee["id"]
                and member["status"] == "ACTIVE" and member["voting_seat"]):
            present_voting_count += 1

    quorum_required = derive.committee_quorum_required(committee["id"])
    if present_voting_count < quorum_required:
        raise ApiError("ERR_QUORUM_NOT_MET")

    if clock.now() < hearing["scheduled_start"]:
        raise ApiError("ERR_HEARING_NOT_STARTED")

    if not hearing["agenda_proposal_ids"]:
        raise ApiError("ERR_AGENDA_EMPTY")

    hearing["status"] = "CONVENED"
    hearing["present_member_ids"] = list(present_member_ids)
    hearing["present_voting_count"] = present_voting_count
    hearing["quorum_required_at_convene"] = quorum_required
    hearing["convened_at"] = clock.now()
    db.touch(hearing)
    return response.object_response(serialize.hearing(hearing))


@bp.post("/hearings/<hearing_id>/adjourn")
def adjourn_hearing(hearing_id):
    user_id, role = middleware.require((config.ROLE_COUNCIL_CHAIR,))
    middleware.resolve_identity(user_id, role)
    validate.body()
    hearing = lookup.hearing(hearing_id)
    _require_chair(user_id, role, hearing)

    if hearing["status"] != "CONVENED":
        raise ApiError("ERR_HEARING_STATE_INVALID")

    hearing["status"] = "ADJOURNED"
    hearing["adjourned_at"] = clock.now()
    db.touch(hearing)
    return response.object_response(serialize.hearing(hearing))


@bp.post("/hearings/<hearing_id>/votes")
def record_vote(hearing_id):
    user_id, role = middleware.require((config.ROLE_COUNCIL_CHAIR,))
    middleware.resolve_identity(user_id, role)
    body = validate.body()
    proposal_id = validate.req_string(body, "proposal_id")
    raw_ballots = validate.req_list(body, "ballots")
    ballots = []
    for entry in raw_ballots:
        if not isinstance(entry, dict):
            raise validate.bad_request("each ballots entry must be an object.")
        member_id = validate.req_string(entry, "member_id")
        value = validate.req_enum(entry, "ballot", config.BALLOT_VALUES)
        ballots.append({"member_id": member_id, "ballot": value})

    hearing = lookup.hearing(hearing_id)
    proposal = lookup.proposal(proposal_id)
    _require_chair(user_id, role, hearing)

    if hearing["status"] != "CONVENED":
        raise ApiError("ERR_HEARING_STATE_INVALID")

    if proposal["analysis_status"] != "COMPLETE":
        raise ApiError("ERR_ANALYSIS_INCOMPLETE")

    # priority 14 — business safety
    if (proposal["stringency_direction"] == "LESS_STRINGENT"
            and str(proposal["code_section"]).startswith(config.LIFE_SAFETY_SECTION_PREFIXES)):
        raise ApiError("ERR_STRINGENCY_FLOOR_VIOLATION")

    committee = db.discipline_committees.get(hearing["committee_id"])
    voting_seats_at_call = (derive.active_voting_member_count(committee["id"])
                           if committee is not None else 0)
    quorum_required = calc.quorum_required(voting_seats_at_call)

    member_lookup = {m["id"]: m for m in
                     (derive.committee_members_of(committee["id"]) if committee else [])}
    tally = calc.tally_ballots(ballots, member_lookup, voting_seats_at_call,
                               proposal["stringency_direction"])

    if tally["cast_total"] < quorum_required:
        raise ApiError("ERR_QUORUM_NOT_MET")

    # priority 15 — graph placement
    if proposal["id"] not in hearing["agenda_proposal_ids"]:
        raise ApiError("ERR_PROPOSAL_NOT_ON_AGENDA")

    for ballot in ballots:
        member = member_lookup.get(ballot["member_id"])
        if member is None or member["status"] != "ACTIVE" or not member["voting_seat"]:
            raise ApiError("ERR_BALLOT_MEMBER_NOT_ON_COMMITTEE")

    # priority 17 — business constraints
    seen = set()
    for ballot in ballots:
        if ballot["member_id"] in seen:
            raise ApiError("ERR_DUPLICATE_BALLOT")
        seen.add(ballot["member_id"])

    for existing in db.vote_records.values():
        if existing["hearing_id"] == hearing["id"] and existing["proposal_id"] == proposal["id"]:
            raise ApiError("ERR_DUPLICATE_VOTE_RECORD")

    # priority 18 — the benefit-cost floor, recomputed from scratch
    cost = proposal["statewide_incremental_cost_cents"]
    final_ratio = None
    if cost not in (None, 0):
        cost_benefit = derive.accepted_analysis(proposal["id"], "COST_BENEFIT")
        savings = cost_benefit["annual_cost_savings_cents"] if cost_benefit else None
        life = cost_benefit["measure_life_years"] if cost_benefit else None
        final_ratio = calc.final_bcr(savings, life, cost)
        if final_ratio is not None and final_ratio < config.BCR_FLOOR:
            raise ApiError("ERR_BENEFIT_COST_BELOW_FLOOR")

    proposal["final_benefit_cost_ratio"] = final_ratio

    record = db.new_record({
        "hearing_id": hearing["id"],
        "proposal_id": proposal["id"],
        "ballots": ballots,
        "voting_seats_at_call": voting_seats_at_call,
        "quorum_required": quorum_required,
        "yes_count": tally["yes_count"],
        "no_count": tally["no_count"],
        "abstain_count": tally["abstain_count"],
        "absent_count": tally["absent_count"],
        "outcome": tally["outcome"],
        "outcome_reason": tally["outcome_reason"],
        "final_benefit_cost_ratio_at_vote": final_ratio,
        "recorded_by_user_id": user_id,
    }, versioned=False)
    db.vote_records[record["id"]] = record

    cycle = db.code_cycles.get(proposal["code_cycle_id"])
    cascades.apply_vote_outcome(proposal, cycle, tally["outcome"])

    return response.object_response(serialize.vote_record(record), 201)


@bp.get("/hearings/<hearing_id>/votes")
def list_hearing_votes(hearing_id):
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    hearing = lookup.hearing(hearing_id)
    rows = derive.children(db.vote_records, "hearing_id", hearing["id"])
    return paged(rows, serialize.vote_record, limit, offset)


@bp.get("/vote-records")
def list_vote_records():
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    rows = apply_filters(list(db.vote_records.values()), {
        "hearing_id": ("hearing_id", as_str),
        "proposal_id": ("proposal_id", as_str),
        "outcome": ("outcome", as_str),
    })
    return paged(rows, serialize.vote_record, limit, offset)


@bp.get("/vote-records/<vote_record_id>")
def get_vote_record(vote_record_id):
    middleware.require(config.ALL_ROLES)
    record = lookup.vote_record(vote_record_id)
    return response.object_response(serialize.vote_record(record))
