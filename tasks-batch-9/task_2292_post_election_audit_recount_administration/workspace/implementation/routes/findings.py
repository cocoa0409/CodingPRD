"""Discrepancy and CorrectiveAction endpoints."""

from flask import Blueprint, g

from db import clock_now, db, insert, iso, now_iso, touch
from errors import fail
from middleware import (
    ROLE_AUDIT_MANAGER,
    ROLE_CANDIDATE_REPRESENTATIVE,
    ROLE_CANVASSING_BOARD_MEMBER,
    ROLE_ELECTIONS_DIRECTOR,
    SIX_ROLES,
    guard,
)
from routes.common import list_endpoint, lookup, paged, single
from services.domain import (
    TERMINAL_AUDIT_STATES,
    actions_of_discrepancy,
    audit_chain,
    create_round,
    discrepancy_chain,
    eligible_pool,
    latest_live_round,
    project_audit_timeline,
    recompute_audit_ledger,
    recompute_election,
)
from validate import (
    body,
    filter_value,
    pagination,
    req_dt,
    req_enum,
    req_str,
)

bp = Blueprint("findings", __name__)

DISCREPANCY_STATUSES = ("OPEN", "DOCUMENTED", "ESCALATED", "RESOLVED", "VOIDED")
DISCREPANCY_TYPES = ("OVERSTATEMENT", "UNDERSTATEMENT", "BALLOT_COUNT_MISMATCH")
ACTION_CATEGORIES = ("EQUIPMENT", "PROCESS", "TRAINING")
ACTION_STATUSES = ("OPEN", "IN_PROGRESS", "COMPLETED", "VERIFIED", "CANCELLED")
ACTION_ROLES = (
    ROLE_ELECTIONS_DIRECTOR,
    ROLE_AUDIT_MANAGER,
    ROLE_CANVASSING_BOARD_MEMBER,
    ROLE_CANDIDATE_REPRESENTATIVE,
)
ALLOWED_ACTION_TRANSITIONS = {
    "OPEN": ("IN_PROGRESS", "CANCELLED"),
    "IN_PROGRESS": ("COMPLETED", "CANCELLED"),
    "COMPLETED": ("VERIFIED",),
    "VERIFIED": (),
    "CANCELLED": (),
}


# ---------------------------------------------------------------------------
# discrepancies
# ---------------------------------------------------------------------------


@bp.get("/discrepancies")
@guard(SIX_ROLES)
def list_discrepancies():
    return list_endpoint(
        "discrepancies",
        {
            "manual_tally_id": ("manual_tally_id", None),
            "status": ("status", DISCREPANCY_STATUSES),
            "discrepancy_type": ("discrepancy_type", DISCREPANCY_TYPES),
        },
    )


@bp.get("/discrepancies/<discrepancy_id>")
@guard(SIX_ROLES)
def get_discrepancy(discrepancy_id):
    return single(lookup("discrepancies", discrepancy_id))


@bp.post("/discrepancies/<discrepancy_id>/document")
@guard([ROLE_CANVASSING_BOARD_MEMBER])
def document_discrepancy(discrepancy_id):
    data = body()
    note = req_str(data, "documentation_note", 1, None)

    row = lookup("discrepancies", discrepancy_id)
    if row["status"] != "OPEN":
        fail("ERR_INVALID_DISCREPANCY_STATE")
    tally, audit_batch, rnd, audit, contest, election = discrepancy_chain(row)
    if audit["status"] in TERMINAL_AUDIT_STATES:
        fail("ERR_INVALID_AUDIT_STATE")

    row["status"] = "DOCUMENTED"
    row["documentation_note"] = note
    touch(row)
    return single(row)


@bp.post("/discrepancies/<discrepancy_id>/escalate")
@guard([ROLE_CANVASSING_BOARD_MEMBER])
def escalate_discrepancy(discrepancy_id):
    data = body()
    reason = req_str(data, "escalation_reason", 1, None)

    row = lookup("discrepancies", discrepancy_id)
    if row["status"] != "DOCUMENTED":
        fail("ERR_INVALID_DISCREPANCY_STATE")
    tally, audit_batch, rnd, audit, contest, election = discrepancy_chain(row)
    if audit["status"] not in ("TALLYING", "DISCREPANCY_REVIEW"):
        fail("ERR_INVALID_AUDIT_STATE")

    pool = eligible_pool(audit, contest)
    if not pool:
        fail("ERR_NO_UNSAMPLED_BATCHES")

    row["status"] = "ESCALATED"
    row["escalation_reason"] = reason
    touch(row)

    previous_round = latest_live_round(audit)
    create_round(audit, contest, pool, len(pool), True, previous_round)
    audit["status"] = "ESCALATED_FULL_HAND_COUNT"
    audit["escalation_level"] = audit["escalation_level"] + 1
    touch(audit)
    recompute_audit_ledger(audit)
    project_audit_timeline(audit)
    recompute_election(election)
    return single(row)


@bp.post("/discrepancies/<discrepancy_id>/resolve")
@guard([ROLE_CANVASSING_BOARD_MEMBER])
def resolve_discrepancy(discrepancy_id):
    data = body()
    note = req_str(data, "resolution_note", 1, None)

    row = lookup("discrepancies", discrepancy_id)
    if row["status"] not in ("DOCUMENTED", "ESCALATED"):
        fail("ERR_INVALID_DISCREPANCY_STATE")

    for action in actions_of_discrepancy(row):
        if action["category"] == "EQUIPMENT" and action["status"] not in (
            "VERIFIED",
            "CANCELLED",
        ):
            fail("ERR_EQUIPMENT_ACTION_UNVERIFIED")

    row["status"] = "RESOLVED"
    row["resolution_note"] = note
    row["resolved_at"] = now_iso()
    touch(row)
    return single(row)


@bp.get("/discrepancies/<discrepancy_id>/corrective-actions")
@guard(ACTION_ROLES)
def list_discrepancy_actions(discrepancy_id):
    limit, offset = pagination()
    status = filter_value("status", ACTION_STATUSES)
    category = filter_value("category", ACTION_CATEGORIES)
    row = lookup("discrepancies", discrepancy_id)
    rows = actions_of_discrepancy(row)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    return paged(rows, limit, offset)


# ---------------------------------------------------------------------------
# corrective actions
# ---------------------------------------------------------------------------


@bp.post("/corrective-actions")
@guard([ROLE_CANVASSING_BOARD_MEMBER])
def create_corrective_action():
    data = body()
    discrepancy_id = req_str(data, "discrepancy_id", 1, None)
    category = req_enum(data, "category", ACTION_CATEGORIES)
    description = req_str(data, "description", 1, 500)
    due_at = req_dt(data, "due_at")

    lookup("discrepancies", discrepancy_id)

    if due_at <= clock_now():
        fail("ERR_INVALID_TIME_WINDOW")

    row = insert(
        "corrective_actions",
        {
            "discrepancy_id": discrepancy_id,
            "category": category,
            "description": description,
            "due_at": iso(due_at),
            "status": "OPEN",
            "completed_by_user_id": None,
            "verified_by_user_id": None,
            "completed_at": None,
            "verified_at": None,
        },
    )
    return single(row, 201)


@bp.get("/corrective-actions")
@guard(ACTION_ROLES)
def list_corrective_actions():
    return list_endpoint(
        "corrective_actions",
        {
            "discrepancy_id": ("discrepancy_id", None),
            "category": ("category", ACTION_CATEGORIES),
            "status": ("status", ACTION_STATUSES),
        },
    )


@bp.get("/corrective-actions/<action_id>")
@guard(ACTION_ROLES)
def get_corrective_action(action_id):
    return single(lookup("corrective_actions", action_id))


@bp.post("/corrective-actions/<action_id>/transition")
@guard([ROLE_CANVASSING_BOARD_MEMBER])
def transition_corrective_action(action_id):
    data = body()
    to_status = req_enum(data, "to_status", ACTION_STATUSES)
    note = data.get("note")
    if note is not None and not isinstance(note, str):
        fail("ERR_VALIDATION", "Field 'note' must be a string.")

    action = lookup("corrective_actions", action_id)
    if to_status not in ALLOWED_ACTION_TRANSITIONS.get(action["status"], ()):
        fail("ERR_INVALID_CORRECTIVE_ACTION_STATE")

    if to_status == "VERIFIED":
        if g.user_id is not None and g.user_id == action["completed_by_user_id"]:
            fail("ERR_SEGREGATION_OF_DUTIES")
        if g.user_id is None and action["completed_by_user_id"] is None:
            fail("ERR_SEGREGATION_OF_DUTIES")

    action["status"] = to_status
    if to_status == "COMPLETED":
        action["completed_by_user_id"] = g.user_id
        action["completed_at"] = now_iso()
    elif to_status == "VERIFIED":
        action["verified_by_user_id"] = g.user_id
        action["verified_at"] = now_iso()
    touch(action)
    return single(action)
