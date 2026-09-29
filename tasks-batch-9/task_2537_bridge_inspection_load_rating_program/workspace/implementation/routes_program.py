"""ProgramCycle, ProjectCandidate and FederalSubmission endpoints."""

from flask import Blueprint

import calc
import db
import params
import response
import serializers
import services
from calc import D, dec
from db import db as store
from errors import ApiError
from middleware import (
    DISTRICT_ENGINEER,
    FHWA_REVIEWER,
    PROGRAM_ADMIN,
    authenticate,
    authenticate_read,
)

bp = Blueprint("program", __name__)

RANKING_POLICIES = ("CONDITION_BASED", "RISK_BASED")
CYCLE_STATUSES = ("PLANNING", "LOCKED", "SUBMITTED", "CLOSED")
CANDIDATE_STATUSES = ("IDENTIFIED", "PROGRAMMED", "DEFERRED", "WITHDRAWN")
WORK_TYPES = ("PRESERVATION", "REPAIR", "REHABILITATION", "REPLACEMENT")
ORIGINS = ("AUTO_FROM_INSPECTION", "MANUAL")
SUBMISSION_TYPES = ("NBI_ANNUAL", "ELEMENT_DATA", "SCOUR_POA")
SUBMISSION_STATUSES = ("BUILDING", "SUBMITTED", "ACCEPTED", "REJECTED")


# --------------------------------------------------------------------------- #
# program cycles
# --------------------------------------------------------------------------- #
@bp.post("/program-cycles")
def create_program_cycle():
    authenticate(PROGRAM_ADMIN)
    body = params.json_body()
    fiscal_year = params.get_int(body, "fiscal_year", required=True, minimum=2020, maximum=2040)
    budget = params.get_int(body, "authorized_budget_cents", required=True, exclusive_minimum=0)
    ranking_policy = params.get_enum(
        body, "ranking_policy", RANKING_POLICIES, default="CONDITION_BASED"
    )
    reserve_pct = params.get_number(
        body,
        "reserve_pct",
        default=calc.DEFAULT_RESERVE_PCT,
        minimum=D("0.00"),
        maximum=D("0.50"),
    )
    reserve = calc.reserve_cents(reserve_pct, budget)
    record = db.new_record(
        {
            "fiscal_year": fiscal_year,
            "authorized_budget_cents": int(budget),
            "reserve_pct": reserve_pct,
            "ranking_policy": ranking_policy,
            "reserve_cents": int(reserve),
            "available_cents": int(budget) - int(reserve),
            "committed_cents": 0,
            "remaining_cents": int(budget) - int(reserve),
            "status": "PLANNING",
            "identified_count": 0,
            "programmed_count": 0,
            "deferred_count": 0,
            "unprogrammed_cost_cents": 0,
            "locked_at": None,
            "submitted_at": None,
            "closed_at": None,
        }
    )
    store.program_cycles[record["id"]] = record
    return response.object_response(serializers.program_cycle(record), 201)


@bp.get("/program-cycles/<cycle_id>")
def read_program_cycle(cycle_id):
    authenticate_read()
    record = services.get_program_cycle(cycle_id)
    return response.object_response(serializers.program_cycle(record))


@bp.get("/program-cycles")
def list_program_cycles():
    authenticate_read()
    limit, offset = params.query_pagination()
    status = params.query_enum("status", CYCLE_STATUSES)
    fiscal_year = params.query_int("fiscal_year")
    ranking_policy = params.query_enum("ranking_policy", RANKING_POLICIES)
    items = []
    for record in services.rows("program_cycles"):
        if status is not None and record["status"] != status:
            continue
        if fiscal_year is not None and int(record["fiscal_year"]) != fiscal_year:
            continue
        if ranking_policy is not None and record["ranking_policy"] != ranking_policy:
            continue
        items.append(serializers.program_cycle(record))
    page, total = response.paginate(items, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.get("/program-cycles/<cycle_id>/allocation-summary")
def allocation_summary(cycle_id):
    authenticate_read()
    record = services.get_program_cycle(cycle_id)
    authorized = int(record["authorized_budget_cents"])
    reserve = int(record["reserve_cents"])
    committed = int(record["committed_cents"])
    remaining = int(record["remaining_cents"])
    data = {
        "program_cycle_id": record["id"],
        "authorized_budget_cents": authorized,
        "reserve_cents": reserve,
        "available_cents": int(record["available_cents"]),
        "committed_cents": committed,
        "remaining_cents": remaining,
        "identified_count": int(record["identified_count"]),
        "programmed_count": int(record["programmed_count"]),
        "deferred_count": int(record["deferred_count"]),
        "unprogrammed_cost_cents": int(record["unprogrammed_cost_cents"]),
        "identity_holds": authorized == reserve + committed + remaining,
    }
    return response.object_response(data)


@bp.post("/program-cycles/<cycle_id>/lock")
def lock_program_cycle(cycle_id):
    authenticate(PROGRAM_ADMIN)
    record = services.get_program_cycle(cycle_id)
    if record["status"] != "PLANNING":
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    record["status"] = "LOCKED"
    record["locked_at"] = db.now()
    services.settle_cycle_and_touch(record)
    return response.object_response(serializers.program_cycle(record))


@bp.post("/program-cycles/<cycle_id>/reopen")
def reopen_program_cycle(cycle_id):
    authenticate(PROGRAM_ADMIN)
    record = services.get_program_cycle(cycle_id)
    if record["status"] != "LOCKED":
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    record["status"] = "PLANNING"
    services.settle_cycle_and_touch(record)
    return response.object_response(serializers.program_cycle(record))


# --------------------------------------------------------------------------- #
# project candidates
# --------------------------------------------------------------------------- #
@bp.post("/program-cycles/<cycle_id>/candidates")
def create_candidate(cycle_id):
    authenticate(DISTRICT_ENGINEER)
    body = params.json_body()
    expected_version = params.get_int(
        body, "expected_program_cycle_version", required=True, minimum=0
    )
    bridge_id = params.get_string(body, "bridge_id", required=True)
    source_inspection_id = params.get_string(body, "source_inspection_id")
    justification = params.get_string(body, "justification")

    cycle = services.get_program_cycle(cycle_id)
    bridge = services.get_bridge(bridge_id)
    source = None
    if source_inspection_id is not None:
        source = services.get_inspection(source_inspection_id)
    if int(expected_version) != int(cycle["version"]):
        raise ApiError("ERR_STALE_CYCLE_VERSION")
    if cycle["status"] != "PLANNING":
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if source is None:
        source = services.latest_accepted_inspection(bridge_id)
        if source is None:
            raise ApiError("ERR_BRIDGE_NOT_INSPECTED")
    elif source["bridge_id"] != bridge_id or source["status"] != "ACCEPTED":
        raise ApiError("ERR_BRIDGE_NOT_INSPECTED")

    record = services.create_candidate(cycle, bridge, source, "MANUAL", justification)
    return response.object_response(serializers.project_candidate(record), 201)


@bp.get("/project-candidates/<candidate_id>")
def read_candidate(candidate_id):
    authenticate_read()
    record = services.get_project_candidate(candidate_id)
    return response.object_response(serializers.project_candidate(record))


@bp.get("/project-candidates")
def list_candidates():
    authenticate_read()
    limit, offset = params.query_pagination()
    bridge_id = params.query_string("bridge_id")
    cycle_id = params.query_string("program_cycle_id")
    source_inspection_id = params.query_string("source_inspection_id")
    status = params.query_enum("status", CANDIDATE_STATUSES)
    work_type = params.query_enum("work_type", WORK_TYPES)
    origin = params.query_enum("origin", ORIGINS)
    items = []
    for record in services.rows("project_candidates"):
        if bridge_id is not None and record["bridge_id"] != bridge_id:
            continue
        if cycle_id is not None and record["program_cycle_id"] != cycle_id:
            continue
        if source_inspection_id is not None and record["source_inspection_id"] != source_inspection_id:
            continue
        if status is not None and record["status"] != status:
            continue
        if work_type is not None and record["work_type"] != work_type:
            continue
        if origin is not None and record["origin"] != origin:
            continue
        items.append(serializers.project_candidate(record))
    page, total = response.paginate(items, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.post("/project-candidates/<candidate_id>/program")
def program_candidate(candidate_id):
    authenticate(DISTRICT_ENGINEER)
    record = services.get_project_candidate(candidate_id)
    cycle = services.get_program_cycle(record["program_cycle_id"])
    if record["status"] != "IDENTIFIED" or cycle["status"] != "PLANNING":
        raise ApiError("ERR_PROGRAM_STATE_INVALID")

    remaining = int(cycle["remaining_cents"])
    cost = int(record["estimated_cost_cents"])
    for other in services.candidates_of(cycle["id"]):
        if other["id"] == record["id"] or other["status"] != "IDENTIFIED":
            continue
        if calc.outranks(other, record) and int(other["estimated_cost_cents"]) <= remaining:
            raise ApiError("ERR_HIGHER_PRIORITY_CANDIDATE_PENDING")
    if cost > remaining:
        raise ApiError("ERR_BUDGET_EXCEEDED")

    record["status"] = "PROGRAMMED"
    record["programmed_at"] = db.now()
    db.touch(record)
    services.settle_cycle_and_touch(cycle)
    return response.object_response(serializers.project_candidate(record))


@bp.post("/project-candidates/<candidate_id>/withdraw")
def withdraw_candidate(candidate_id):
    authenticate(DISTRICT_ENGINEER)
    record = services.get_project_candidate(candidate_id)
    cycle = services.get_program_cycle(record["program_cycle_id"])
    if record["status"] != "PROGRAMMED" or cycle["status"] != "PLANNING":
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    record["status"] = "WITHDRAWN"
    record["withdrawn_at"] = db.now()
    db.touch(record)
    services.settle_cycle_and_touch(cycle)
    return response.object_response(serializers.project_candidate(record))


@bp.post("/project-candidates/<candidate_id>/defer")
def defer_candidate(candidate_id):
    authenticate(DISTRICT_ENGINEER)
    body = params.json_body()
    justification = params.get_string(body, "justification")
    record = services.get_project_candidate(candidate_id)
    cycle = services.get_program_cycle(record["program_cycle_id"])
    if record["status"] != "IDENTIFIED" or cycle["status"] != "PLANNING":
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    record["status"] = "DEFERRED"
    record["deferred_at"] = db.now()
    if justification is not None:
        record["justification"] = justification
    db.touch(record)
    services.settle_cycle_and_touch(cycle)
    return response.object_response(serializers.project_candidate(record))


# --------------------------------------------------------------------------- #
# federal submissions
# --------------------------------------------------------------------------- #
@bp.post("/program-cycles/<cycle_id>/federal-submissions")
def create_federal_submission(cycle_id):
    authenticate(PROGRAM_ADMIN)
    body = params.json_body()
    submission_type = params.get_enum(
        body, "submission_type", SUBMISSION_TYPES, required=True
    )
    cycle = services.get_program_cycle(cycle_id)
    record = db.new_record(
        {
            "program_cycle_id": cycle["id"],
            "submission_type": submission_type,
            "status": "BUILDING",
            "total_bridge_count": 0,
            "overdue_inspection_count": 0,
            "inspection_compliance_pct": D("0.00"),
            "poa_noncompliant_count": 0,
            "open_immediate_finding_count": 0,
            "error_count": 0,
            "submitted_by_user_id": None,
            "reviewer_user_id": None,
            "rejection_reason_code": "NONE",
            "submitted_at": None,
            "reviewed_at": None,
        }
    )
    store.federal_submissions[record["id"]] = record
    return response.object_response(serializers.federal_submission(record), 201)


@bp.get("/federal-submissions/<submission_id>")
def read_federal_submission(submission_id):
    authenticate_read()
    record = services.get_federal_submission(submission_id)
    return response.object_response(serializers.federal_submission(record))


@bp.get("/federal-submissions")
def list_federal_submissions():
    authenticate_read()
    limit, offset = params.query_pagination()
    cycle_id = params.query_string("program_cycle_id")
    status = params.query_enum("status", SUBMISSION_STATUSES)
    submission_type = params.query_enum("submission_type", SUBMISSION_TYPES)
    items = []
    for record in services.rows("federal_submissions"):
        if cycle_id is not None and record["program_cycle_id"] != cycle_id:
            continue
        if status is not None and record["status"] != status:
            continue
        if submission_type is not None and record["submission_type"] != submission_type:
            continue
        items.append(serializers.federal_submission(record))
    page, total = response.paginate(items, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.post("/federal-submissions/<submission_id>/submit")
def submit_federal_submission(submission_id):
    actor = authenticate(PROGRAM_ADMIN)
    record = services.get_federal_submission(submission_id)
    cycle = services.get_program_cycle(record["program_cycle_id"])
    if record["status"] not in ("BUILDING", "REJECTED"):
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if cycle["status"] != "LOCKED":
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    snapshot = services.compliance_snapshot()
    if int(snapshot["poa_noncompliant_count"]) > 0:
        raise ApiError("ERR_SCOUR_CRITICAL_POA_MISSING")

    record.update(snapshot)
    record["status"] = "SUBMITTED"
    record["submitted_at"] = db.now()
    record["submitted_by_user_id"] = actor.user_id
    record["rejection_reason_code"] = "NONE"
    db.touch(record)
    cycle["status"] = "SUBMITTED"
    cycle["submitted_at"] = db.now()
    services.settle_cycle_and_touch(cycle)
    return response.object_response(serializers.federal_submission(record))


@bp.post("/federal-submissions/<submission_id>/review")
def review_federal_submission(submission_id):
    actor = authenticate(FHWA_REVIEWER)
    body = params.json_body()
    decision = params.get_enum(body, "decision", ("ACCEPT", "REJECT"), required=True)
    record = services.get_federal_submission(submission_id)
    cycle = services.get_program_cycle(record["program_cycle_id"])
    if record["status"] != "SUBMITTED":
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if actor.user_id == record["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    compliance = dec(record["inspection_compliance_pct"])
    if decision == "ACCEPT" and compliance < calc.ACCEPTANCE_COMPLIANCE_THRESHOLD_PCT:
        raise ApiError("ERR_COMPLIANCE_BELOW_THRESHOLD")

    if decision == "ACCEPT":
        record["status"] = "ACCEPTED"
        record["reviewed_at"] = db.now()
        record["reviewer_user_id"] = actor.user_id
        db.touch(record)
        cycle["status"] = "CLOSED"
        cycle["closed_at"] = db.now()
    else:
        record["status"] = "REJECTED"
        record["reviewed_at"] = db.now()
        record["reviewer_user_id"] = actor.user_id
        record["rejection_reason_code"] = (
            "COMPLIANCE_BELOW_THRESHOLD"
            if compliance < calc.ACCEPTANCE_COMPLIANCE_THRESHOLD_PCT
            else "DATA_GAPS"
        )
        db.touch(record)
        cycle["status"] = "LOCKED"
        cycle["submitted_at"] = None
    services.settle_cycle_and_touch(cycle)
    return response.object_response(serializers.federal_submission(record))
