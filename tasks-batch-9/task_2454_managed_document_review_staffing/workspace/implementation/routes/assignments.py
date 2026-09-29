"""Assignments: creation, auto-selection, coding, submission and voiding."""

from decimal import Decimal

from flask import Blueprint, request

from db import base_row, by_creation, db, touch
from errors import ApiError
from middleware import (
    ROLE_CLIENT_COUNSEL,
    ROLE_ENGAGEMENT_MANAGER,
    ROLE_QC_LEAD,
    ROLE_REVIEWER,
    ROLE_STAFFING_COORDINATOR,
    body,
    require_roles,
    user_id,
)
from response import created_response, object_response, paginated
from routes.batches import require_approved_protocol
from routes.matters import require_not_suspended
from services import cascade, compute
from services.compute import dec, round_half_up
from validation import opt_int, present, req_enum, req_id, req_int, req_str

bp = Blueprint("assignments", __name__)

PASS_TYPES = ("FIRST_PASS", "SECOND_LEVEL")
LIVE_STATUSES = ("ASSIGNED", "IN_PROGRESS", "REOPENED")
NON_TERMINAL_STATUSES = ("ASSIGNED", "IN_PROGRESS", "REOPENED", "SUBMITTED")


# ---------------------------------------------------------------------------
# Shared create path
# ---------------------------------------------------------------------------
def _active_same_pass(batch_id, pass_type):
    for assignment in compute.assignments_of_batch(batch_id):
        if assignment["pass_type"] == pass_type and assignment["status"] in LIVE_STATUSES:
            return assignment
    return None


def _check_batch_state(batch, pass_type):
    """Rank 12 for both create paths; returns the row being superseded."""
    superseded = _active_same_pass(batch["id"], pass_type)
    if pass_type == "FIRST_PASS":
        if superseded is not None:
            if batch["status"] not in ("ASSIGNED", "IN_PROGRESS"):
                raise ApiError("ERR_INVALID_STATE",
                               "The batch does not accept a first-pass reassignment now.")
            return superseded
        if batch["status"] != "CREATED":
            raise ApiError("ERR_INVALID_STATE",
                           "A first-pass assignment is created on a CREATED batch.")
        return None
    if batch["status"] != "SECOND_LEVEL":
        raise ApiError("ERR_INVALID_STATE",
                       "A second-level assignment requires a batch in SECOND_LEVEL.")
    return superseded


def _check_second_level_separation(batch, reviewer_id, pass_type):
    """Rank 20 - the two passes of a batch never share a reviewer."""
    other = "FIRST_PASS" if pass_type == "SECOND_LEVEL" else "SECOND_LEVEL"
    for assignment in compute.assignments_of_batch(batch["id"]):
        if assignment["pass_type"] != other:
            continue
        if assignment["status"] == "VOIDED":
            continue
        if assignment["reviewer_id"] == reviewer_id:
            raise ApiError("ERR_SECOND_LEVEL_SAME_REVIEWER",
                           "The two review passes of a batch may not share a reviewer.")


def _finish_create(batch, matter, reviewer, pass_type, protocol, superseded):
    effective_rate = compute.effective_per_document_cents(matter, reviewer, pass_type)
    committed = compute.committed_amount_cents(matter, batch, protocol, effective_rate)

    # Rank 43 - the budget ceiling is the very last check, and nothing is written
    # until it passes.
    if compute.committed_spend_cents(matter) + committed > matter["budget_cap_cents"]:
        raise ApiError("ERR_BUDGET_WOULD_EXCEED",
                       "The commitment would carry the matter past its budget cap.")

    if superseded is not None:
        cascade.void_assignment(superseded, "SUPERSEDED_BY_REASSIGNMENT",
                                reset_batch=False)

    row = base_row()
    row.update({
        "batch_id": batch["id"],
        "reviewer_id": reviewer["id"],
        "reassigned_from_assignment_id": None if superseded is None else superseded["id"],
        "pass_type": pass_type,
        "status": "ASSIGNED",
        "documents_coded": 0,
        "minutes_logged": 0,
        "privilege_hits_logged": 0,
        "billable_minutes": 0,
        "effective_per_document_cents": effective_rate,
        "committed_amount_cents": committed,
        "billable_amount_cents": 0,
        "started_at": None,
        "submitted_at": None,
        "voided_at": None,
        "void_reason": None,
    })
    db.assignments[row["id"]] = row
    cascade.append_ledger(matter["id"], row["id"], "COMMITMENT", committed,
                          batch["batch_number"])

    if pass_type == "FIRST_PASS":
        batch["status"] = "ASSIGNED"
    touch(batch)
    cascade.engage_reviewer(reviewer)
    return row


@bp.route("/batches/<batch_id>/assignments", methods=["POST"])
def create_assignment(batch_id):
    require_roles(ROLE_STAFFING_COORDINATOR)
    batch = compute.get_batch(batch_id)
    matter = compute.matter_of_batch(batch)
    payload = body()

    # Rank 5 - the named reviewer must exist.
    reviewer = None
    if present(payload, "reviewer_id") and isinstance(payload["reviewer_id"], str):
        reviewer = compute.get_reviewer(payload["reviewer_id"])

    expected_batch_version = req_int(payload, "expected_batch_version")
    req_id(payload, "reviewer_id")
    if reviewer is None:
        reviewer = compute.get_reviewer(payload["reviewer_id"])
    pass_type = req_enum(payload, "pass_type", PASS_TYPES)

    # Rank 11.
    if expected_batch_version != batch["version"]:
        raise ApiError("ERR_STALE_BATCH_VERSION",
                       "The batch has moved on since it was last read.")

    superseded = _check_batch_state(batch, pass_type)
    require_not_suspended(matter)
    if reviewer["engagement_status"] == "REMOVED":
        raise ApiError("ERR_REVIEWER_REMOVED", "The reviewer has been removed.")
    protocol = require_approved_protocol(matter)
    if matter["status"] != "IN_REVIEW":
        raise ApiError("ERR_MIN_STAFFING_UNMET",
                       "The matter has not reached its minimum staffing.")
    if not compute.has_cleared_screening(reviewer["id"], matter["id"]):
        raise ApiError("ERR_CONFLICTS_NOT_CLEARED",
                       "No CLEARED conflicts screening exists for this pair.")
    cascade.apply_lazy_expiry_many(compute.agreements_of_pair(reviewer["id"], matter["id"]))
    if compute.live_agreement(reviewer["id"], matter["id"]) is None:
        raise ApiError("ERR_CONFIDENTIALITY_NOT_EXECUTED",
                       "No executed confidentiality agreement covers the logical clock.")
    if reviewer["credential_status"] != "VERIFIED":
        raise ApiError("ERR_CREDENTIAL_NOT_VERIFIED",
                       "The reviewer's credential standing is not VERIFIED.")
    _check_second_level_separation(batch, reviewer["id"], pass_type)

    # Rank 28.
    if not db.now() < matter["_deadline_dt"]:
        raise ApiError("ERR_MATTER_DEADLINE_PASSED",
                       "The matter's deadline has already passed.")
    for state in matter["required_bar_states"]:
        if state not in reviewer["bar_admissions"]:
            raise ApiError("ERR_BAR_ADMISSION_MISSING",
                           "The reviewer lacks a required bar admission.")
    if not compute.active_assignment_count(reviewer["id"]) < reviewer["max_concurrent_batches"]:
        raise ApiError("ERR_REVIEWER_CAPACITY_EXCEEDED",
                       "The reviewer already holds their maximum concurrent batches.")
    for language in matter["required_languages"]:
        if language not in reviewer["languages"]:
            raise ApiError("ERR_LANGUAGE_REQUIREMENT_UNMET",
                           "The reviewer lacks a required language.")
    if reviewer["tier"] != pass_type:
        raise ApiError("ERR_TIER_MISMATCH",
                       "The reviewer's tier does not match the requested pass type.")

    row = _finish_create(batch, matter, reviewer, pass_type, protocol, superseded)
    return created_response(compute.assignment_out(row))


# ---------------------------------------------------------------------------
# Auto-assignment
# ---------------------------------------------------------------------------
def _eligible(reviewer, batch, matter, pass_type):
    if reviewer["engagement_status"] not in ("CLEARED", "ENGAGED"):
        return False
    if reviewer["credential_status"] != "VERIFIED":
        return False
    if not compute.has_cleared_screening(reviewer["id"], matter["id"]):
        return False
    if compute.live_agreement(reviewer["id"], matter["id"]) is None:
        return False
    if reviewer["tier"] != pass_type:
        return False
    for state in matter["required_bar_states"]:
        if state not in reviewer["bar_admissions"]:
            return False
    for language in matter["required_languages"]:
        if language not in reviewer["languages"]:
            return False
    if not compute.active_assignment_count(reviewer["id"]) < reviewer["max_concurrent_batches"]:
        return False
    other = "FIRST_PASS" if pass_type == "SECOND_LEVEL" else "SECOND_LEVEL"
    for assignment in compute.assignments_of_batch(batch["id"]):
        if assignment["reviewer_id"] != reviewer["id"]:
            continue
        if assignment["pass_type"] != other:
            continue
        if assignment["status"] in NON_TERMINAL_STATUSES:
            return False
    return True


def _score(reviewer, matter, protocol):
    accuracy = compute.accuracy_score(reviewer["id"], "SAMPLE_WEIGHTED")
    pace = compute.reviewer_pace_dph(reviewer["id"])
    normalised_pace = pace / dec(protocol["min_pace_dph"])
    if normalised_pace > compute.PACE_NORMALISATION_CAP:
        normalised_pace = compute.PACE_NORMALISATION_CAP
    normalised_pace = normalised_pace / compute.PACE_NORMALISATION_CAP

    required_languages = matter["required_languages"]
    if required_languages:
        shared = len(set(reviewer["languages"]) & set(required_languages))
        language_ratio = dec(shared) / dec(len(required_languages))
    else:
        language_ratio = Decimal(0)
    matter_tags = matter["subject_matter_tags"]
    if matter_tags:
        shared_tags = len(set(reviewer["subject_matter_tags"]) & set(matter_tags))
        subject_ratio = dec(shared_tags) / dec(len(matter_tags))
    else:
        subject_ratio = Decimal(0)
    strikes = min(compute.scorecard_strikes(reviewer["id"]), compute.STRIKE_PENALTY_CAP)
    penalty = compute.STRIKE_PENALTY_WEIGHT * dec(strikes)

    raw = (compute.ACCURACY_WEIGHT * accuracy
           + compute.PACE_WEIGHT * normalised_pace
           + compute.LANGUAGE_WEIGHT * language_ratio
           + compute.SUBJECT_WEIGHT * subject_ratio
           - penalty)
    return round_half_up(raw, 4)


@bp.route("/batches/<batch_id>/auto-assign", methods=["POST"])
def auto_assign(batch_id):
    require_roles(ROLE_STAFFING_COORDINATOR)
    batch = compute.get_batch(batch_id)
    matter = compute.matter_of_batch(batch)
    payload = body()
    expected_batch_version = req_int(payload, "expected_batch_version")
    pass_type = req_enum(payload, "pass_type", PASS_TYPES)

    if expected_batch_version != batch["version"]:
        raise ApiError("ERR_STALE_BATCH_VERSION",
                       "The batch has moved on since it was last read.")

    superseded = _check_batch_state(batch, pass_type)
    require_not_suspended(matter)
    protocol = require_approved_protocol(matter)
    if matter["status"] != "IN_REVIEW":
        raise ApiError("ERR_MIN_STAFFING_UNMET",
                       "The matter has not reached its minimum staffing.")
    if not db.now() < matter["_deadline_dt"]:
        raise ApiError("ERR_MATTER_DEADLINE_PASSED",
                       "The matter's deadline has already passed.")

    cascade.apply_lazy_expiry_many(compute.agreements_of_matter(matter["id"]))
    pool = [r for r in by_creation(list(db.reviewers.values()))
            if _eligible(r, batch, matter, pass_type)]
    if not pool:
        raise ApiError("ERR_NO_ELIGIBLE_REVIEWER",
                       "No reviewer is eligible for this batch and pass type.")

    ranked = []
    for reviewer in pool:
        headroom = reviewer["max_concurrent_batches"] \
            - compute.active_assignment_count(reviewer["id"])
        ranked.append((reviewer, _score(reviewer, matter, protocol), headroom))
    ranked.sort(key=lambda item: (-item[1], -item[2],
                                  item[0]["hourly_cost_cents"],
                                  item[0]["created_at"], item[0]["_seq"]))
    winner = ranked[0][0]

    _check_second_level_separation(batch, winner["id"], pass_type)
    row = _finish_create(batch, matter, winner, pass_type, protocol, superseded)
    return created_response(compute.assignment_out(row))


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.route("/assignments/<assignment_id>", methods=["GET"])
def read_assignment(assignment_id):
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR,
                  ROLE_QC_LEAD, ROLE_REVIEWER)
    assignment = compute.get_assignment(assignment_id)
    return object_response(compute.assignment_out(assignment))


@bp.route("/assignments", methods=["GET"])
def list_assignments():
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR,
                  ROLE_QC_LEAD, ROLE_REVIEWER)
    rows = by_creation(list(db.assignments.values()))
    batch_id = request.args.get("batch_id")
    reviewer_id = request.args.get("reviewer_id")
    reassigned_from = request.args.get("reassigned_from_assignment_id")
    status = request.args.get("status")
    pass_type = request.args.get("pass_type")
    if batch_id:
        rows = [r for r in rows if r["batch_id"] == batch_id]
    if reviewer_id:
        rows = [r for r in rows if r["reviewer_id"] == reviewer_id]
    if reassigned_from:
        rows = [r for r in rows if r["reassigned_from_assignment_id"] == reassigned_from]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if pass_type:
        rows = [r for r in rows if r["pass_type"] == pass_type]
    return paginated(rows, compute.assignment_out)


@bp.route("/assignments/<assignment_id>/budget-ledger", methods=["GET"])
def list_assignment_ledger(assignment_id):
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR, ROLE_CLIENT_COUNSEL)
    assignment = compute.get_assignment(assignment_id)
    rows = compute.ledger_of_assignment(assignment["id"])
    entry_type = request.args.get("entry_type")
    if entry_type:
        rows = [r for r in rows if r["entry_type"] == entry_type]
    return paginated(rows, compute.ledger_entry_out)


# ---------------------------------------------------------------------------
# Coding lifecycle
# ---------------------------------------------------------------------------
def _require_owner(assignment):
    if user_id() != assignment["reviewer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the assigned reviewer may act on this assignment.")


def _require_live_coverage(reviewer_id, matter):
    cascade.apply_lazy_expiry_many(compute.agreements_of_pair(reviewer_id, matter["id"]))
    if compute.live_agreement(reviewer_id, matter["id"]) is None:
        raise ApiError("ERR_CONFIDENTIALITY_NOT_EXECUTED",
                       "No executed confidentiality agreement covers the logical clock.")


def _require_active_session(reviewer_id, matter):
    if compute.active_session(reviewer_id, matter["id"]) is None:
        raise ApiError("ERR_NO_ACTIVE_SESSION",
                       "The reviewer holds no ACTIVE session containing the clock.")


@bp.route("/assignments/<assignment_id>/start", methods=["POST"])
def start_assignment(assignment_id):
    require_roles(ROLE_REVIEWER)
    assignment = compute.get_assignment(assignment_id)
    batch = compute.batch_of_assignment(assignment)
    matter = compute.matter_of_batch(batch)
    reviewer = compute.get_reviewer(assignment["reviewer_id"])
    _require_owner(assignment)

    if assignment["status"] not in ("ASSIGNED", "REOPENED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Work starts from ASSIGNED or REOPENED only.")
    require_not_suspended(matter)
    _require_live_coverage(reviewer["id"], matter)
    if reviewer["credential_status"] != "VERIFIED":
        raise ApiError("ERR_CREDENTIAL_NOT_VERIFIED",
                       "The reviewer's credential standing is not VERIFIED.")

    assignment["status"] = "IN_PROGRESS"
    if assignment["started_at"] is None:
        assignment["started_at"] = db.now_iso()
    touch(assignment)
    if batch["status"] in ("ASSIGNED", "QC_FAILED"):
        batch["status"] = "IN_PROGRESS"
        touch(batch)
    return object_response(compute.assignment_out(assignment))


@bp.route("/assignments/<assignment_id>/progress", methods=["POST"])
def record_progress(assignment_id):
    require_roles(ROLE_REVIEWER)
    assignment = compute.get_assignment(assignment_id)
    batch = compute.batch_of_assignment(assignment)
    matter = compute.matter_of_batch(batch)
    _require_owner(assignment)
    payload = body()
    documents_coded = req_int(payload, "documents_coded", 0)
    minutes_logged = req_int(payload, "minutes_logged", 0)
    privilege_hits_logged = opt_int(payload, "privilege_hits_logged", 0, None,
                                   assignment["privilege_hits_logged"])

    if assignment["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE",
                       "Progress is recorded against an IN_PROGRESS assignment only.")
    require_not_suspended(matter)
    _require_live_coverage(assignment["reviewer_id"], matter)
    _require_active_session(assignment["reviewer_id"], matter)

    # Rank 39 - four monotonicity conditions, one identifier.
    if documents_coded < assignment["documents_coded"]:
        raise ApiError("ERR_DOCUMENT_COUNT_EXCEEDED",
                       "'documents_coded' may not decrease.")
    if documents_coded > batch["document_count"]:
        raise ApiError("ERR_DOCUMENT_COUNT_EXCEEDED",
                       "'documents_coded' may not exceed the batch's document count.")
    if minutes_logged < assignment["minutes_logged"]:
        raise ApiError("ERR_DOCUMENT_COUNT_EXCEEDED",
                       "'minutes_logged' may not decrease.")
    if privilege_hits_logged < assignment["privilege_hits_logged"]:
        raise ApiError("ERR_DOCUMENT_COUNT_EXCEEDED",
                       "'privilege_hits_logged' may not decrease.")

    assignment["documents_coded"] = documents_coded
    assignment["minutes_logged"] = minutes_logged
    assignment["privilege_hits_logged"] = privilege_hits_logged
    touch(assignment)
    return object_response(compute.assignment_out(assignment))


@bp.route("/assignments/<assignment_id>/submit", methods=["POST"])
def submit_assignment(assignment_id):
    require_roles(ROLE_REVIEWER)
    assignment = compute.get_assignment(assignment_id)
    batch = compute.batch_of_assignment(assignment)
    matter = compute.matter_of_batch(batch)
    reviewer = compute.get_reviewer(assignment["reviewer_id"])
    _require_owner(assignment)

    if assignment["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "A pass is submitted from IN_PROGRESS only.")
    require_not_suspended(matter)
    _require_live_coverage(reviewer["id"], matter)
    _require_active_session(reviewer["id"], matter)

    # Rank 25 - the two completeness conditions.
    if assignment["documents_coded"] != batch["document_count"]:
        raise ApiError("ERR_ASSIGNMENT_INCOMPLETE",
                       "Every document of the batch must be coded before submission.")
    authored = len([e for e in compute.entries_of_batch(batch["id"])
                    if e["authored_by_reviewer_id"] == reviewer["id"]])
    if assignment["privilege_hits_logged"] != authored:
        raise ApiError("ERR_ASSIGNMENT_INCOMPLETE",
                       "Declared privilege hits do not reconcile with the logged entries.")

    first_submit = assignment["billable_amount_cents"] == 0
    assignment["status"] = "SUBMITTED"
    assignment["submitted_at"] = db.now_iso()

    if first_submit:
        if matter["pricing_model"] == "PER_DOCUMENT":
            billable = assignment["effective_per_document_cents"] \
                * assignment["documents_coded"]
            entry_type = "ACTUAL_PER_DOCUMENT"
        else:
            assignment["billable_minutes"] = compute.billable_minutes_for(
                assignment["minutes_logged"])
            billable = compute.hourly_billable_cents(matter, assignment["billable_minutes"])
            entry_type = "ACTUAL_HOURLY"
        assignment["billable_amount_cents"] = billable
    touch(assignment)

    if first_submit:
        cascade.append_ledger(matter["id"], assignment["id"], entry_type,
                              assignment["billable_amount_cents"], batch["batch_number"])
        cascade.append_ledger(matter["id"], assignment["id"], "REVERSAL",
                              -assignment["committed_amount_cents"], batch["batch_number"])

    protocol = compute.effective_protocol(matter["id"])
    min_pace = protocol["min_pace_dph"] if protocol else 0
    if compute.assignment_pace_dph(assignment) < dec(min_pace):
        cascade.append_scorecard_event(
            reviewer["id"], "PACE_SHORTFALL",
            "Pace below the protocol minimum on batch %s." % batch["batch_number"],
            batch["batch_number"])
        cascade.evaluate_removal(reviewer)

    # The batch fork.
    if not first_submit:
        batch["status"] = "QC_SAMPLING"
    elif assignment["pass_type"] == "FIRST_PASS":
        if protocol is not None and protocol["second_level_required"]:
            batch["status"] = "SECOND_LEVEL"
        else:
            batch["status"] = "QC_SAMPLING"
    else:
        batch["status"] = "QC_SAMPLING"
    touch(batch)
    return object_response(compute.assignment_out(assignment))


@bp.route("/assignments/<assignment_id>/void", methods=["POST"])
def void_assignment_route(assignment_id):
    require_roles(ROLE_STAFFING_COORDINATOR)
    assignment = compute.get_assignment(assignment_id)
    reviewer = compute.get_reviewer(assignment["reviewer_id"])
    payload = body()
    void_reason = req_str(payload, "void_reason", 1, 200)

    if assignment["status"] not in LIVE_STATUSES:
        raise ApiError("ERR_INVALID_STATE",
                       "Only a non-terminal assignment may be voided.")

    matter = cascade.void_assignment(assignment, void_reason)
    cascade.recompute_engagement(reviewer)
    cascade.sync_matter_staffing(matter)
    return object_response(compute.assignment_out(assignment))
