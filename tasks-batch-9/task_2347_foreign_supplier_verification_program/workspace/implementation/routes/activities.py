"""VerificationActivity: proposal, revision and second-QI review."""
from flask import Blueprint, g

import core
import serialize
from core import write_txn
from db import store
from errors import fail
from middleware import CO, FDA, QI, endpoint
from response import object_response
from routes._common import acting_qi, find, paged, require_qi_current
from shapes import (
    body,
    opt_dt,
    opt_int,
    opt_str,
    pagination,
    query_enum,
    query_str,
    req_dt,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("activities", __name__)

REVIEW_DECISIONS = ("APPROVE", "REQUEST_CHANGES", "WITHDRAW")


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap: adjacency never counts."""
    return a_start < b_end and b_start < a_end


def _check_capacity(assigned_qi, window_start, window_end, exclude_id=None):
    """Ladder rung 40 — ERR_QI_WINDOW_CAPACITY_EXCEEDED."""
    count = 0
    for existing in store.activities.values():
        if existing["id"] == exclude_id:
            continue
        if existing["assigned_qi_id"] != assigned_qi["id"]:
            continue
        if existing["status"] not in core.LIVE_ACTIVITY_STATUSES:
            continue
        if _overlaps(
            window_start, window_end, existing["window_start"], existing["window_end"]
        ):
            count += 1
    if count >= assigned_qi["concurrent_activity_capacity"]:
        fail(
            "ERR_QI_WINDOW_CAPACITY_EXCEEDED",
            "the assigned qualified individual has no capacity for this window",
        )


@bp.post("/fsvp/verification-activities")
@endpoint([QI])
def create_activity():
    b = body()
    pair_id = req_str(b, "pair_id")
    activity_type = req_enum(b, "activity_type", core.ACTIVITY_TYPES)
    frequency_per_year = req_int(b, "frequency_per_year", lo=0, hi=12)
    justification_text = req_str(b, "justification_text")
    window_start = req_dt(b, "window_start")
    window_end = req_dt(b, "window_end")
    assigned_qi_id = req_str(b, "assigned_qi_id")

    # rung 5
    assigned_qi = find("qi", assigned_qi_id, "ERR_QI_NOT_FOUND")
    # rung 8
    pair = find("pair", pair_id, "ERR_PAIR_NOT_FOUND")

    # rung 14
    proposer = acting_qi()
    if assigned_qi["importer_id"] != pair["importer_id"] or (
        proposer is not None and proposer["importer_id"] != pair["importer_id"]
    ):
        fail("ERR_IMPORTER_SCOPE_MISMATCH", "every referenced entity must share one importer")

    # rung 26
    require_qi_current(proposer)

    # rung 31
    if not pair["active_hazard_analysis_id"]:
        fail("ERR_HAZARD_ANALYSIS_REQUIRED", "the pair has no active hazard analysis")

    # rung 36
    if not window_start < window_end:
        fail("ERR_INVALID_WINDOW", "window_start must be strictly before window_end")

    # rung 40
    _check_capacity(assigned_qi, window_start, window_end)

    # rung 42
    if len(justification_text) < 20:
        fail("ERR_JUSTIFICATION_INSUFFICIENT", "justification_text must be at least 20 characters")

    with write_txn():
        row = store.new_row("activity")
        row.update(
            {
                "pair_id": pair_id,
                "proposed_by_qi_id": g.user_id,
                "assigned_qi_id": assigned_qi_id,
                "reviewed_by_qi_id": None,
                "activity_type": activity_type,
                "frequency_per_year": frequency_per_year,
                "justification_text": justification_text,
                "window_start": window_start,
                "window_end": window_end,
                "status": "PROPOSED",
                "revision_count": 0,
            }
        )
        store.insert(row)
    return object_response(serialize.activity_out(row), 201)


@bp.get("/fsvp/verification-activities/<activity_id>")
@endpoint([CO, QI, FDA])
def read_activity(activity_id):
    row = find("activity", activity_id, "ERR_ACTIVITY_NOT_FOUND")
    return object_response(serialize.activity_out(row))


@bp.get("/fsvp/verification-activities")
@endpoint([CO, QI, FDA])
def list_activities():
    pair_id = query_str("pair_id")
    proposed_by = query_str("proposed_by_qi_id")
    assigned_to = query_str("assigned_qi_id")
    reviewed_by = query_str("reviewed_by_qi_id")
    status = query_enum("status", core.ACTIVITY_STATUSES)
    activity_type = query_enum("activity_type", core.ACTIVITY_TYPES)
    limit, offset = pagination()

    rows = list(store.activities.values())
    if pair_id is not None:
        rows = [r for r in rows if r["pair_id"] == pair_id]
    if proposed_by is not None:
        rows = [r for r in rows if r["proposed_by_qi_id"] == proposed_by]
    if assigned_to is not None:
        rows = [r for r in rows if r["assigned_qi_id"] == assigned_to]
    if reviewed_by is not None:
        rows = [r for r in rows if r["reviewed_by_qi_id"] == reviewed_by]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if activity_type is not None:
        rows = [r for r in rows if r["activity_type"] == activity_type]
    return paged(rows, serialize.activity_out, limit, offset)


@bp.patch("/fsvp/verification-activities/<activity_id>")
@endpoint([QI])
def patch_activity(activity_id):
    b = body()
    frequency_per_year = opt_int(b, "frequency_per_year", lo=0, hi=12)
    justification_text = opt_str(b, "justification_text")
    window_start = opt_dt(b, "window_start")
    window_end = opt_dt(b, "window_end")
    assigned_qi_id = opt_str(b, "assigned_qi_id")

    # rung 5
    new_assigned_qi = None
    if assigned_qi_id is not None:
        new_assigned_qi = find("qi", assigned_qi_id, "ERR_QI_NOT_FOUND")

    # rung 10
    activity = find("activity", activity_id, "ERR_ACTIVITY_NOT_FOUND")
    pair = store.pairs.get(activity["pair_id"])

    effective_assigned_id = assigned_qi_id or activity["assigned_qi_id"]
    assigned_qi = new_assigned_qi or store.qis.get(effective_assigned_id)

    # rung 14
    reviser = acting_qi()
    if pair is not None:
        if (assigned_qi is not None and assigned_qi["importer_id"] != pair["importer_id"]) or (
            reviser is not None and reviser["importer_id"] != pair["importer_id"]
        ):
            fail("ERR_IMPORTER_SCOPE_MISMATCH", "every referenced entity must share one importer")

    # rung 23
    if activity["status"] not in ("PROPOSED", "CHANGES_REQUESTED"):
        fail("ERR_ACTIVITY_NOT_REVISABLE", "a %s activity is frozen" % activity["status"])

    # rung 26
    require_qi_current(reviser)

    effective_start = window_start or activity["window_start"]
    effective_end = window_end or activity["window_end"]
    effective_justification = (
        justification_text if justification_text is not None else activity["justification_text"]
    )

    # rung 36
    if not effective_start < effective_end:
        fail("ERR_INVALID_WINDOW", "window_start must be strictly before window_end")

    # rung 40
    window_changed = (
        effective_start != activity["window_start"] or effective_end != activity["window_end"]
    )
    assignee_changed = effective_assigned_id != activity["assigned_qi_id"]
    if (window_changed or assignee_changed) and assigned_qi is not None:
        _check_capacity(assigned_qi, effective_start, effective_end, exclude_id=activity["id"])

    # rung 42
    if len(effective_justification) < 20:
        fail("ERR_JUSTIFICATION_INSUFFICIENT", "justification_text must be at least 20 characters")

    # rung 43
    if g.user_id != activity["proposed_by_qi_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "only the proposing qualified individual may revise")

    with write_txn():
        if frequency_per_year is not None:
            activity["frequency_per_year"] = frequency_per_year
        if justification_text is not None:
            activity["justification_text"] = justification_text
        if window_start is not None:
            activity["window_start"] = window_start
        if window_end is not None:
            activity["window_end"] = window_end
        if assigned_qi_id is not None:
            activity["assigned_qi_id"] = assigned_qi_id
        if activity["status"] == "CHANGES_REQUESTED":
            activity["status"] = "PROPOSED"
            activity["revision_count"] = activity["revision_count"] + 1
        store.touch(activity)
    return object_response(serialize.activity_out(activity))


@bp.post("/fsvp/verification-activities/<activity_id>/review")
@endpoint([QI])
def review_activity(activity_id):
    b = body()
    decision = req_enum(b, "decision", REVIEW_DECISIONS)
    req_str(b, "reviewer_note", minlen=1)

    activity = find("activity", activity_id, "ERR_ACTIVITY_NOT_FOUND")
    pair = store.pairs.get(activity["pair_id"])

    # rung 19
    allowed = {
        "APPROVE": ("PROPOSED",),
        "REQUEST_CHANGES": ("PROPOSED",),
        "WITHDRAW": ("PROPOSED", "CHANGES_REQUESTED"),
    }
    if activity["status"] not in allowed[decision]:
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "cannot %s a %s activity" % (decision, activity["status"]),
        )
    if decision == "APPROVE" and pair is not None and pair["verification_status"] == "RETIRED":
        fail("ERR_INVALID_STATE_TRANSITION", "the parent pair is retired")

    # rung 26 — only the approval decision requires current training
    if decision == "APPROVE":
        require_qi_current()

    # rung 43
    if g.user_id == activity["proposed_by_qi_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the proposer may not review their own activity")

    with write_txn():
        if decision == "APPROVE":
            activity["status"] = "APPROVED"
        elif decision == "REQUEST_CHANGES":
            activity["status"] = "CHANGES_REQUESTED"
        else:
            activity["status"] = "WITHDRAWN"
        activity["reviewed_by_qi_id"] = g.user_id
        store.touch(activity)
    return object_response(serialize.activity_out(activity))
