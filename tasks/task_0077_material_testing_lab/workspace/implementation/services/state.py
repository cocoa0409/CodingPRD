"""State-machine helpers — cascade side effects, assignment selector, sample
maturity checks. Kept here so route modules stay slim.

All mutations bump version + updated_at on touched rows (except the version-
less InstrumentBooking row, which is mutated in place but never re-versioned).
"""

from db import DB
from services.time_util import now_iso, parse_iso, today_utc
from services.calculations import (
    METHOD_TO_CATEGORY,
    BASE_FEE_CENTS,
    compute_qualification_posture,
    tester_has_category_in_effect,
    booking_duration_minutes_ceil,
)
from services.audit import emit_audit


# ---------------------------------------------------------------------------
# Bump helpers
# ---------------------------------------------------------------------------

def touch(row):
    """Refresh updated_at and bump version on a versioned row."""
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = now_iso()


# ---------------------------------------------------------------------------
# Sample maturity — derives the sample's status after a child task changes
# ---------------------------------------------------------------------------

def recompute_sample_after_completion(sample_id):
    """If every task under this sample is COMPLETED, move the sample to TESTED.

    This is fired from the task-complete cascade. Does NOT bump sample if it
    is already DISPOSED/TESTED/etc.
    """
    sample = DB["samples"].get(sample_id)
    if sample is None:
        return
    tasks = [t for t in DB["tasks"].values() if t.get("sample_id") == sample_id]
    if not tasks:
        return
    # All tasks must be COMPLETED (CANCELLED tasks don't gate; but spec says
    # "all of its tasks finish and the resulting reports have been issued or
    # archived" before disposal, and for IN_TESTING->TESTED the precondition
    # is "Count of TestTasks with sample_id == this.id AND status != COMPLETED
    # equals 0"). We therefore count anything not COMPLETED. We treat
    # CANCELLED as not blocking — but the precondition reads strictly. To be
    # safe: only move when every task in {ASSIGNED, IN_PROGRESS, ... } is gone.
    not_complete = [t for t in tasks if t.get("status") != "COMPLETED"]
    if not_complete:
        return
    if sample.get("status") in ("IN_TESTING", "RETESTING"):
        sample["status"] = "TESTED"
        touch(sample)


# ---------------------------------------------------------------------------
# Tester assignment selector (SCAFFOLD calculations.tester_assignment_selection)
# ---------------------------------------------------------------------------

def find_assignment_candidate(task):
    """Return the chosen Tester row or None. Raises nothing.

    Eligibility: posture in {QUALIFIED, EXPIRING_SOON}, at least one qual
    entry in-effect for the task's material_category, active_task_count
    strictly less than max_concurrent_tasks.
    """
    sample = DB["samples"].get(task["sample_id"])
    if sample is None:
        return None, "no_sample"
    category = sample["material_category"]

    qualified_at_all = []  # any tester with a matching in-effect qualification (regardless of workload/posture)
    eligible = []          # qualified AND posture {QUALIFIED, EXPIRING_SOON} AND workload OK

    for t in DB["testers"].values():
        if not tester_has_category_in_effect(t, category):
            continue
        qualified_at_all.append(t)
        if t.get("qualification_posture") == "LAPSED":
            continue
        if t.get("active_task_count", 0) >= t.get("max_concurrent_tasks", 5):
            continue
        eligible.append(t)

    if not qualified_at_all:
        return None, "no_qualified_tester"
    if not eligible:
        # qualified testers exist but all at workload cap (or LAPSED posture)
        # The spec separates these reasons. If every qualified+posture-ok tester
        # is at the cap -> WORKLOAD_EXCEEDED. If every qualified tester is
        # LAPSED -> NO_QUALIFIED_TESTER.
        non_lapsed_qualified = [t for t in qualified_at_all
                                if t.get("qualification_posture") != "LAPSED"]
        if not non_lapsed_qualified:
            return None, "no_qualified_tester"
        return None, "workload_exceeded"

    eligible.sort(key=lambda t: (
        t.get("active_task_count", 0),
        t.get("created_at", ""),
        t.get("id", ""),
    ))
    return eligible[0], "ok"


def assign_task_to_tester(task, tester):
    """Mutate task and tester for the ASSIGNED transition. Bumps version on both."""
    task["assigned_tester_id"] = tester["id"]
    task["status"] = "ASSIGNED"
    touch(task)
    tester["active_task_count"] = tester.get("active_task_count", 0) + 1
    touch(tester)


def release_task_assignment(task, *, cancel_booking=True):
    """Cascade for reassign/qualification-lapse/instrument-failure.

    Decrements prior tester's active_task_count, clears assigned_tester_id,
    cancels the linked InstrumentBooking if any. Caller is responsible for
    setting task.status to PENDING_ASSIGNMENT afterwards.
    """
    prev_tester_id = task.get("assigned_tester_id")
    if prev_tester_id:
        prev = DB["testers"].get(prev_tester_id)
        if prev is not None:
            prev["active_task_count"] = max(0, prev.get("active_task_count", 0) - 1)
            touch(prev)
    task["assigned_tester_id"] = None
    if cancel_booking:
        bid = task.get("instrument_booking_id")
        if bid:
            b = DB["bookings"].get(bid)
            if b is not None and b.get("status") == "RESERVED":
                b["status"] = "CANCELLED"
        task["instrument_booking_id"] = None


# ---------------------------------------------------------------------------
# Reconcile posture for one tester (mutation-trigger variant) or all testers
# (clock-advance variant with cascade).
# ---------------------------------------------------------------------------

def reconcile_tester_posture(tester, *, with_cascade=False, lapsed_at_iso=None):
    """Recompute qualification_posture; if cascade is requested and posture
    flips to LAPSED from a prior non-LAPSED value, cascade-revert ASSIGNED
    tasks to PENDING_ASSIGNMENT.
    """
    prev = tester.get("qualification_posture")
    new_posture = compute_qualification_posture(tester.get("qualifications", []))
    if new_posture == prev:
        return new_posture, False
    tester["qualification_posture"] = new_posture
    touch(tester)
    if with_cascade and new_posture == "LAPSED" and prev != "LAPSED":
        for t in list(DB["tasks"].values()):
            if t.get("assigned_tester_id") == tester["id"] and t.get("status") == "ASSIGNED":
                release_task_assignment(t, cancel_booking=False)
                t["status"] = "PENDING_ASSIGNMENT"
                touch(t)
        emit_audit(
            "QUALIFICATION_LAPSED", "Tester", tester["id"],
            "system", "system",
            {"lapsed_at": lapsed_at_iso or now_iso()},
        )
    return new_posture, True


# ---------------------------------------------------------------------------
# Instrument calibration-lapse cascade (clock-advance sweep)
# ---------------------------------------------------------------------------

def cascade_instrument_calibration_lapse(instrument, *, lapsed_at_iso=None):
    """When an instrument crosses calibration_valid_to, transition it to
    CALIBRATION_DUE and cancel future-dated RESERVED bookings; affected
    tasks revert to PENDING_ASSIGNMENT.
    """
    instrument["status"] = "CALIBRATION_DUE"
    touch(instrument)
    cal_to = parse_iso(instrument["calibration_valid_to"]) if isinstance(instrument["calibration_valid_to"], str) else instrument["calibration_valid_to"]
    for b in list(DB["bookings"].values()):
        if b.get("instrument_id") != instrument["id"]:
            continue
        if b.get("status") != "RESERVED":
            continue
        slot_start = parse_iso(b["slot_start"]) if isinstance(b["slot_start"], str) else b["slot_start"]
        if slot_start > cal_to:
            b["status"] = "CANCELLED"
            t = DB["tasks"].get(b["task_id"])
            if t is not None and t.get("status") in ("ASSIGNED", "IN_PROGRESS"):
                release_task_assignment(t, cancel_booking=False)
                t["instrument_booking_id"] = None
                t["status"] = "PENDING_ASSIGNMENT"
                touch(t)
    emit_audit(
        "INSTRUMENT_CALIBRATION_LAPSED",
        "Instrument", instrument["id"],
        "system", "system",
        {"lapsed_at": lapsed_at_iso or now_iso()},
    )


def cascade_instrument_out_of_service(instrument, *, now_dt):
    """report-failure cascade: cancel RESERVED bookings whose slot_end > now,
    and revert affected tasks (ASSIGNED or IN_PROGRESS) to PENDING_ASSIGNMENT.
    """
    instrument["status"] = "OUT_OF_SERVICE"
    touch(instrument)
    for b in list(DB["bookings"].values()):
        if b.get("instrument_id") != instrument["id"]:
            continue
        if b.get("status") != "RESERVED":
            continue
        slot_end = parse_iso(b["slot_end"]) if isinstance(b["slot_end"], str) else b["slot_end"]
        if slot_end > now_dt:
            b["status"] = "CANCELLED"
            t = DB["tasks"].get(b["task_id"])
            if t is not None and t.get("status") in ("ASSIGNED", "IN_PROGRESS"):
                release_task_assignment(t, cancel_booking=False)
                t["instrument_booking_id"] = None
                t["status"] = "PENDING_ASSIGNMENT"
                touch(t)
