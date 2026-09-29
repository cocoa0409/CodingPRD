"""The logical clock and the nightly compliance sweep (PRD 2.9)."""

from flask import Blueprint

import calc
import constants as C
import sync
from db import store
from middleware import authenticate
from response import object_response
from validation import body, dt_field

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(("ProgramAdmin",))
    data = body()
    current_utc, parsed = dt_field(data, "current_utc", True)
    store.set_clock(current_utc, parsed)
    return object_response({"current_utc": current_utc})


@bp.post("/_ops/daily-run")
def daily_run():
    authenticate(("ProgramAdmin",))
    clock = store.clock

    counters = {
        "training_expired_count": 0,
        "drills_missed_count": 0,
        "protective_activated_count": 0,
        "protective_expired_count": 0,
        "actions_overdue_count": 0,
        "log_retention_expired_count": 0,
        "plans_review_due_count": 0,
        "plans_rescored_count": 0,
    }

    # -- step 1: training assignments lapse -------------------------------
    touched_employees = []
    for assignment in list(store.training_assignments.values()):
        expired = False
        if assignment["status"] == "ASSIGNED":
            due = calc.dt_of(assignment, "due_at")
            expired = due is not None and due < clock
        elif assignment["status"] == "COMPLETED":
            expires = calc.dt_of(assignment, "expires_at")
            expired = expires is not None and expires <= clock
        if not expired:
            continue
        sync.assign(assignment, {"status": "EXPIRED"})
        counters["training_expired_count"] += 1
        employee = store.employees.get(assignment["employee_id"])
        if employee is not None and employee not in touched_employees:
            touched_employees.append(employee)
    for employee in touched_employees:
        sync.sync_employee_training(employee)

    # -- step 2: drills lapse ---------------------------------------------
    for drill in list(store.drills.values()):
        if drill["status"] != "SCHEDULED":
            continue
        scheduled = calc.dt_of(drill, "scheduled_at")
        if scheduled is not None and scheduled < clock:
            sync.assign(drill, {"status": "MISSED"})
            counters["drills_missed_count"] += 1

    # -- step 3: protective measures advance ------------------------------
    for action in list(store.case_actions.values()):
        if action["action_class"] != "PROTECTIVE":
            continue
        if action["status"] != "SCHEDULED":
            continue
        starts = calc.dt_of(action, "starts_at")
        ends = calc.dt_of(action, "ends_at")
        if starts is None or ends is None:
            continue
        if starts <= clock and ends > clock:
            sync.assign(action, {"status": "ACTIVE"})
            counters["protective_activated_count"] += 1

    for action in list(store.case_actions.values()):
        if action["action_class"] != "PROTECTIVE":
            continue
        if action["status"] not in C.COVERED_STATUSES:
            continue
        ends = calc.dt_of(action, "ends_at")
        if ends is not None and ends <= clock:
            sync.release_protective(action, "EXPIRED")
            counters["protective_expired_count"] += 1

    # -- step 4: post-incident actions fall behind ------------------------
    for action in list(store.case_actions.values()):
        if action["action_class"] != "POST_INCIDENT":
            continue
        if action["status"] != "PENDING":
            continue
        due = calc.dt_of(action, "due_at")
        if due is not None and due < clock:
            sync.assign(action, {"status": "OVERDUE"})
            counters["actions_overdue_count"] += 1

    # -- step 5: coverage is re-measured ----------------------------------
    for case in list(store.threat_cases.values()):
        if case["status"] == "CLOSED":
            continue
        sync.sync_case_actions_count(case)
        sync.sync_case_coverage(case, allow_auto_action=False)

    # -- step 6: retention expires ----------------------------------------
    for entry in list(store.log_entries.values()):
        if entry["retention_status"] != "ACTIVE":
            continue
        expiry = calc.dt_of(entry, "retention_expiry_date")
        if expiry is not None and expiry <= clock:
            entry["retention_status"] = "RETENTION_EXPIRED"
            counters["log_retention_expired_count"] += 1

    # -- step 7: plan review falls due ------------------------------------
    for plan in list(store.prevention_plans.values()):
        if plan["status"] != "ACTIVE":
            continue
        review_due = calc.dt_of(plan, "review_due_date")
        if review_due is not None and review_due <= clock:
            sync.assign(plan, {"status": "REVIEW_DUE"})
            counters["plans_review_due_count"] += 1

    # -- step 8: everything is rescored -----------------------------------
    counters["plans_rescored_count"] = sync.sync_all_plans()

    return object_response(counters)
