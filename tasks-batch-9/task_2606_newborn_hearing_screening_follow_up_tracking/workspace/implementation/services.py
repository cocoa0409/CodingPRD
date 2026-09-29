"""Shared state transitions and cascades."""
import calc
import db
from db import store
from errors import ApiError


# --- risk ------------------------------------------------------------------
def recompute_risk(infant):
    score, band = calc.ltf_risk(infant)
    if infant["ltf_risk_score"] != score or infant["priority_band"] != band:
        infant["ltf_risk_score"] = score
        infant["priority_band"] = band
        db.touch(infant)
    return band


# --- episodes ---------------------------------------------------------------
def create_episode(infant, episode_type, supersedes_episode_id=None):
    benchmark = calc.DIAGNOSTIC_BENCHMARK_DAYS if episode_type == "DIAGNOSTIC" \
        else calc.SCREENING_BENCHMARK_DAYS
    row = db.base_row()
    row.update({
        "infant_id": infant["id"],
        "supersedes_episode_id": supersedes_episode_id,
        "episode_type": episode_type,
        "status": "PENDING_SCHEDULING",
        "owner_scope": "FACILITY",
        "escalation_flag": False,
        "benchmark_days": benchmark,
        "due_date": db.add_days(infant["birth_datetime"], benchmark),
        "timeliness_status": "PENDING",
        "closure_reason": None,
        "closed_at": None,
    })
    store.episodes[row["id"]] = row
    return row


def write_episode_timeliness(episode, infant, instant):
    age = calc.effective_age(infant, instant)
    episode["timeliness_status"] = calc.timeliness(
        age, episode["benchmark_days"], True)


def cancel_linked_interpreter_task(appointment):
    task_id = appointment.get("linked_navigation_task_id")
    if not task_id:
        return
    task = store.tasks.get(task_id)
    if task is not None and task["status"] in ("UNASSIGNED", "OPEN"):
        task["status"] = "CANCELLED"
        db.touch(task)


def cancel_appointment(appointment, reason=None):
    appointment["status"] = "CANCELLED"
    if reason is not None:
        appointment["disposition_reason"] = reason
    db.touch(appointment)
    cancel_linked_interpreter_task(appointment)


def cancel_booked_appointments(episode):
    for appointment in db.sort_rows(calc.episode_appointments(episode["id"])):
        if appointment["status"] == "BOOKED":
            cancel_appointment(appointment)


def close_episode(episode, status, closure_reason, infant=None, instant=None,
                  write_timeliness=False):
    episode["status"] = status
    episode["closure_reason"] = closure_reason
    episode["closed_at"] = db.now()
    if write_timeliness and infant is not None:
        write_episode_timeliness(episode, infant, instant or db.now())
    db.touch(episode)
    cancel_booked_appointments(episode)


# --- navigation tasks -------------------------------------------------------
def travel_buffer_conflict(provider_id, starts_at, ends_at, ignore_task_id=None):
    if starts_at is None or ends_at is None:
        return False
    for task in store.tasks.values():
        if task["id"] == ignore_task_id:
            continue
        if task["task_type"] != "HOME_VISIT":
            continue
        if task["assigned_provider_id"] != provider_id:
            continue
        if task["status"] not in ("UNASSIGNED", "OPEN"):
            continue
        other_start = task["visit_starts_at"]
        other_end = task["visit_ends_at"]
        if other_start is None or other_end is None:
            continue
        gap_ok = (starts_at >= db.add_seconds(other_end, calc.TRAVEL_BUFFER_SECONDS)
                  or other_start >= db.add_seconds(ends_at, calc.TRAVEL_BUFFER_SECONDS))
        if not gap_ok:
            return True
    return False


def _new_task_row(infant, task_type, episode_id, visit_starts_at, visit_ends_at,
                  units, shortfall):
    row = db.base_row()
    row.update({
        "infant_id": infant["id"],
        "episode_id": episode_id,
        "funding_facility_id": infant["birth_facility_id"],
        "assigned_provider_id": None,
        "task_type": task_type,
        "visit_starts_at": visit_starts_at,
        "visit_ends_at": visit_ends_at,
        "units_reserved": units,
        "budget_shortfall_flag": shortfall,
        "status": "UNASSIGNED",
        "outcome": None,
        "contacted_language": None,
        "closure_note": None,
    })
    store.tasks[row["id"]] = row
    return row


def assign_task(task, provider):
    task["assigned_provider_id"] = provider["id"]
    task["status"] = "OPEN"
    db.touch(task)


def mint_cascade_task(infant, task_type, episode_id=None):
    """Cascade-minted task: never rejected, unfunded when the budget is short,
    left UNASSIGNED when the navigator pool is empty."""
    facility = store.facilities.get(infant["birth_facility_id"])
    required = calc.navigation_units_required(infant, task_type)
    remaining = calc.budget_remaining(facility) if facility else 0
    if remaining >= required:
        units, shortfall = required, False
    else:
        units, shortfall = 0, True
    task = _new_task_row(infant, task_type, episode_id, None, None, units, shortfall)
    pool = calc.navigator_candidates(infant)
    if pool:
        assign_task(task, pool[0])
    return task


def reserve_units_or_reject(infant, task_type):
    facility = store.facilities.get(infant["birth_facility_id"])
    required = calc.navigation_units_required(infant, task_type)
    remaining = calc.budget_remaining(facility) if facility else 0
    if remaining < required:
        raise ApiError("ERR_NAVIGATION_BUDGET_EXHAUSTED")
    return required


def mint_interpreter_task(infant, episode_id):
    """Booking-attached interpreter task: operator-initiated funding rules."""
    units = reserve_units_or_reject(infant, "INTERPRETER_SESSION")
    task = _new_task_row(infant, "INTERPRETER_SESSION", episode_id, None, None,
                         units, False)
    pool = calc.navigator_candidates(infant)
    if pool:
        assign_task(task, pool[0])
    return task


# --- early intervention -----------------------------------------------------
def mint_referral(infant, evaluation_id, excluded=()):
    pool = calc.ei_program_candidates(infant, excluded)
    row = db.base_row()
    row.update({
        "infant_id": infant["id"],
        "diagnostic_evaluation_id": evaluation_id,
        "ei_program_facility_id": pool[0]["id"] if pool else None,
        "status": "PENDING",
        "referred_at": db.now(),
        "accepted_at": None,
        "ifsp_date": None,
        "enrollment_age_days": None,
        "ei_timeliness_status": "PENDING",
        "resolution_reason": None,
    })
    store.referrals[row["id"]] = row
    return row


# --- risk registry ----------------------------------------------------------
def create_risk_entry(infant, code, identified_at, source):
    row = db.base_row()
    row.update({
        "infant_id": infant["id"],
        "risk_factor_code": code,
        "identified_at": identified_at,
        "source": source,
        "surveillance_due_date": calc.surveillance_due_date(infant, code),
        "status": "ACTIVE",
        "surveillance_result": None,
        "surveillance_recorded_at": None,
    })
    store.risk_entries[row["id"]] = row
    return row


# --- re-engagement cascade (PRD 3.4) ---------------------------------------
def reengagement_cascade(infant):
    lost = [e for e in calc.infant_episodes(infant["id"])
            if e["status"] == "LOST_TO_FOLLOW_UP"]
    episode = db.latest(lost)
    if episode is not None:
        episode["status"] = "PENDING_SCHEDULING"
        episode["closure_reason"] = None
        episode["closed_at"] = None
        db.touch(episode)
    if infant["screening_status"] == "LOST_TO_FOLLOW_UP":
        infant["screening_status"] = "REFERRED"
        infant["reengagement_count"] += 1
        db.touch(infant)
    recompute_risk(infant)
