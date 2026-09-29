"""AdoptionCycle endpoints, including the phase-advance sweep (PRD 3.1)."""

import domain
import serializers as S
import validation as V
from db import apply_changes, base_record, db, now
from errors import fail
from middleware import authorize, check_state_scope
from response import respond, respond_list

from flask import Blueprint

bp = Blueprint("cycles", __name__)

READ_ROLES = (
    "PlatformAdmin",
    "StateAdoptionOfficer",
    "PublisherEditor",
    "EditorialDirector",
    "PricingManager",
    "ReviewCommitteeMember",
    "SalesRep",
)

PANEL_LIST_ROLES = (
    "PlatformAdmin",
    "StateAdoptionOfficer",
    "PublisherEditor",
    "ReviewCommitteeMember",
)


@bp.post("/adoption-cycles")
def create_cycle():
    user_id, role = authorize(("StateAdoptionOfficer",))
    payload = V.body()

    state_id = V.get_str(payload, "state_id")
    subject = V.get_enum(payload, "subject", V.SUBJECTS)
    cycle_year = V.get_int(payload, "cycle_year", minimum=2020, maximum=2100)
    submission_open_at = V.get_datetime(payload, "submission_open_at")
    submission_deadline_at = V.get_datetime(payload, "submission_deadline_at")
    committee_review_at = V.get_datetime(payload, "committee_review_at")
    public_comment_start_at = V.get_datetime(payload, "public_comment_start_at")
    public_comment_end_at = V.get_datetime(payload, "public_comment_end_at")
    adoption_decision_at = V.get_datetime(payload, "adoption_decision_at")
    contract_term_years = V.get_int(
        payload, "contract_term_years", minimum=1, maximum=10
    )

    if submission_deadline_at <= submission_open_at:
        fail(
            "ERR_INVALID_REQUEST",
            "submission_deadline_at must be strictly after submission_open_at.",
        )
    if committee_review_at < submission_deadline_at:
        fail(
            "ERR_INVALID_REQUEST",
            "committee_review_at must be at or after submission_deadline_at.",
        )
    if public_comment_start_at < committee_review_at:
        fail(
            "ERR_INVALID_REQUEST",
            "public_comment_start_at must be at or after committee_review_at.",
        )
    if public_comment_end_at <= public_comment_start_at:
        fail(
            "ERR_INVALID_REQUEST",
            "public_comment_end_at must be strictly after public_comment_start_at.",
        )
    if adoption_decision_at < public_comment_end_at:
        fail(
            "ERR_INVALID_REQUEST",
            "adoption_decision_at must be at or after public_comment_end_at.",
        )

    domain.find_state(state_id, "ERR_REFERENCED_RESOURCE_NOT_FOUND")
    check_state_scope(role, user_id, state_id)

    for existing in db.adoption_cycles.values():
        if existing["state_id"] != state_id or existing["subject"] != subject:
            continue
        # Half-open [open, deadline) intersection test.
        if (
            submission_open_at < existing["submission_deadline_at"]
            and existing["submission_open_at"] < submission_deadline_at
        ):
            fail(
                "ERR_CYCLE_WINDOW_OVERLAP",
                "Submission window intersects an existing cycle of this "
                "state and subject.",
            )

    record = base_record()
    record.update(
        {
            "state_id": state_id,
            "subject": subject,
            "cycle_year": cycle_year,
            "submission_open_at": submission_open_at,
            "submission_deadline_at": submission_deadline_at,
            "committee_review_at": committee_review_at,
            "public_comment_start_at": public_comment_start_at,
            "public_comment_end_at": public_comment_end_at,
            "adoption_decision_at": adoption_decision_at,
            "contract_term_years": contract_term_years,
            "status": "SCHEDULED",
            "phase_epoch": 0,
            "submission_count": 0,
            "scheduled_submission_count": 0,
            "adopted_count": 0,
        }
    )
    db.adoption_cycles[record["id"]] = record
    return respond(S.serialize(record, S.ADOPTION_CYCLE_FIELDS), 201)


@bp.get("/adoption-cycles/<cycle_id>")
def get_cycle(cycle_id):
    authorize(READ_ROLES)
    record = domain.find_cycle(cycle_id)
    return respond(S.serialize(record, S.ADOPTION_CYCLE_FIELDS))


@bp.get("/adoption-cycles")
def list_cycles():
    authorize(READ_ROLES)
    limit, offset = V.pagination()
    state_id = V.query_str("state_id")
    subject = V.query_enum("subject", V.SUBJECTS)
    cycle_year = V.query_int("cycle_year")
    status = V.query_enum("status", V.CYCLE_STATUSES)

    items = domain.ordered(list(db.adoption_cycles.values()))
    if state_id is not None:
        items = [i for i in items if i["state_id"] == state_id]
    if subject is not None:
        items = [i for i in items if i["subject"] == subject]
    if cycle_year is not None:
        items = [i for i in items if i["cycle_year"] == cycle_year]
    if status is not None:
        items = [i for i in items if i["status"] == status]

    total = len(items)
    page = items[offset:offset + limit]
    return respond_list(
        S.serialize_many(page, S.ADOPTION_CYCLE_FIELDS), total, limit, offset
    )


@bp.post("/adoption-cycles/<cycle_id>/phase-advance")
def phase_advance(cycle_id):
    user_id, role = authorize(("StateAdoptionOfficer",))
    V.body()

    cycle = domain.find_cycle(cycle_id)
    check_state_scope(role, user_id, cycle["state_id"])

    current = cycle["status"]
    if current == "ARCHIVED":
        fail(
            "ERR_ADOPTION_CYCLE_STATE_INVALID",
            "An ARCHIVED cycle is read-only.",
        )
    target = domain.PHASE_ORDER[domain.PHASE_ORDER.index(current) + 1]

    if current == "IN_REVIEW" and target == "PUBLIC_COMMENT":
        for panel in db.committee_panels.values():
            if panel["cycle_id"] == cycle["id"] and panel["status"] == "IN_SESSION":
                fail(
                    "ERR_COMMITTEE_PANEL_STATE_INVALID",
                    "A panel of this cycle is still IN_SESSION.",
                )

    if target == "ARCHIVED":
        due_at = domain.archive_due_at(cycle)
    else:
        due_at = cycle[domain.PHASE_GATE[target]]
    if now() < due_at:
        fail(
            "ERR_PHASE_NOT_DUE",
            "The logical clock has not reached the %s timestamp." % target,
        )

    apply_changes(
        cycle, {"status": target, "phase_epoch": cycle["phase_epoch"] + 1}
    )

    domain.epoch_sweep(cycle)

    if current == "OPEN" and target == "CLOSED_FOR_SUBMISSION":
        for submission in domain.submissions_of_cycle(cycle["id"]):
            if submission["review_status"] == "DRAFT":
                apply_changes(submission, {"review_status": "WITHDRAWN"})
        domain.recount_cycle(cycle)

    if current == "PUBLIC_COMMENT" and target == "DECIDED":
        for submission in domain.submissions_of_cycle(cycle["id"]):
            if submission["review_status"] not in domain.LIVE_REVIEW_STATUSES:
                continue
            apply_changes(submission, {"review_status": "NOT_ADOPTED"})
            for slot in domain.slots_of_submission(submission["id"]):
                if slot["status"] == "RESERVED":
                    domain.cancel_slot(slot)
        domain.recount_cycle(cycle)

    return respond(S.serialize(cycle, S.ADOPTION_CYCLE_FIELDS))


@bp.get("/adoption-cycles/<cycle_id>/panels")
def list_cycle_panels(cycle_id):
    authorize(PANEL_LIST_ROLES)
    limit, offset = V.pagination()
    status = V.query_enum("status", V.PANEL_STATUSES)

    domain.find_cycle(cycle_id)

    items = domain.ordered(
        [p for p in db.committee_panels.values() if p["cycle_id"] == cycle_id]
    )
    if status is not None:
        items = [i for i in items if i["status"] == status]

    total = len(items)
    page = items[offset:offset + limit]
    return respond_list(
        S.serialize_many(page, S.COMMITTEE_PANEL_FIELDS), total, limit, offset
    )
