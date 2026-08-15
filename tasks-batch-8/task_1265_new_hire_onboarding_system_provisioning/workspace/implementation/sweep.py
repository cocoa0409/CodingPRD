"""State-machine engine: gates, cascades, and the time-based sweep.

All case-gate re-evaluations, automatic transitions, and teardown cascades
live here so route handlers stay thin. Version discipline follows the
SCAFFOLD §1.2 side_effects literally: every transition/mutation listed there
bumps the owning case version by exactly 1; a health-label flip is itself a
case mutation (PRD §2.9) and bumps the version once more.
"""

from datetime import datetime, time as dtime, timedelta, timezone

import calc
from db import store, clock
from helpers import (new_record, touch, children, find_one,
                     session_booked_count)
from util import fmt_dt

TERMINAL_PHASES = ("COMPLETED", "WITHDRAWN", "REVOKED", "SEPARATED")


# ---------------------------------------------------------------- health ----

def refresh_health(case):
    """Recompute health_score; flip the label when the threshold is crossed.
    A flip on a live case is a case mutation (version += 1). Terminal cases
    are locked: their stored label/score update silently (no version bump)."""
    score = calc.case_health_score(case)
    case["health_score"] = score
    label = calc.health_label(score)
    if label != case["health"]:
        case["health"] = label
        if case["phase"] not in TERMINAL_PHASES:
            touch(case)
        else:
            case["updated_at"] = case["updated_at"]  # frozen: no version bump


# ----------------------------------------------------------------- gates ----

def order_of(case_id):
    return find_one("orders", case_id)


def reeval_day_one_gate(case):
    """PROVISIONING <-> DAY_ONE_READY: order FULFILLED and rsvp BOOKED."""
    if case["phase"] == "PROVISIONING":
        order = order_of(case["id"])
        if order is not None and order["status"] == "FULFILLED" \
                and case["orientation_rsvp"] == "BOOKED":
            case["phase"] = "DAY_ONE_READY"
            touch(case)
    elif case["phase"] == "DAY_ONE_READY":
        if case["orientation_rsvp"] != "BOOKED":
            case["phase"] = "PROVISIONING"
            touch(case)


def reeval_probation_gate(case):
    """IN_PROGRESS -> PROBATION once every training is COMPLETED and at least
    one MANAGER check-in is COMPLETED."""
    if case["phase"] != "IN_PROGRESS":
        return
    trainings = children("trainings", case["id"])
    if not all(t["status"] == "COMPLETED" for t in trainings):
        return
    managers = [c for c in children("checkins", case["id"])
                if c["kind"] == "MANAGER"]
    if not any(c["status"] == "COMPLETED" for c in managers):
        return
    case["phase"] = "PROBATION"
    touch(case)


# --------------------------------------------------------- phase cascades ----

def create_provisioning_order(case):
    """CLEARANCE_IN_PROGRESS -> PROVISIONING cascade: order + items from the
    pinned profile template; equipment first, then access grants."""
    prof = case["_profile"]
    order = new_record("orders", {
        "case_id": case["id"],
        "status": "DRAFT",
        "pinned_profile_version": case["pinned_profile_version"],
        "sla_hours": prof["provisioning_sla_hours"],
        "submitted_at": None,
        "fulfilled_at": None,
        "_submitted_dt": None,
        "_fulfilled_dt": None,
    })
    idx = 0
    for eq in prof["equipment_items"]:
        new_record("items", {
            "order_id": order["id"], "item_kind": "EQUIPMENT",
            "item_name": eq["item_name"], "quantity": eq["quantity"],
            "status": "PENDING", "blocked_reason": None, "sort_index": idx,
        })
        idx += 1
    for ag in prof["access_grants"]:
        new_record("items", {
            "order_id": order["id"], "item_kind": "ACCESS",
            "item_name": ag["system_name"], "quantity": 1,
            "status": "PENDING", "blocked_reason": None, "sort_index": idx,
        })
        idx += 1
    case["phase"] = "PROVISIONING"
    touch(case)
    return order


def _cancel(records, statuses):
    for r in records:
        if r["status"] in statuses:
            r["status"] = "CANCELLED"
            touch(r)


def _release_booking(case):
    """Release a held orientation booking (rsvp BOOKED): free the seat and
    return a FULL session to SCHEDULED."""
    if case.get("orientation_rsvp") == "BOOKED":
        sess = store["sessions"].get(case.get("orientation_session_id"))
        case["orientation_rsvp"] = "NONE"
        case["orientation_session_id"] = None
        if sess is not None:
            if sess["status"] == "FULL" and \
                    session_booked_count(sess) < sess["capacity"]:
                sess["status"] = "SCHEDULED"
            touch(sess)


def revoke_case(case):
    """CLEARANCE_IN_PROGRESS -> REVOKED teardown (clearance rejected)."""
    cid = case["id"]
    _cancel(children("tasks", cid), ("PENDING", "SUBMITTED", "REJECTED"))
    _cancel(children("trainings", cid), ("ASSIGNED", "OVERDUE"))
    _cancel(children("checkins", cid), ("SCHEDULED", "MISSED"))
    _cancel(children("cycles", cid), ("ACTIVE", "EVALUATION_DUE"))
    _cancel(children("surveys", cid), ("SENT",))
    nh = store["new_hires"].get(case["new_hire_id"])
    if nh is not None:
        nh["status"] = "RESCINDED"
        touch(nh)
    case["phase"] = "REVOKED"
    touch(case)
    refresh_health(case)


def withdraw_case(case):
    """PRE_BOARDING/CLEARANCE_IN_PROGRESS/PROVISIONING/DAY_ONE_READY ->
    WITHDRAWN: the broadest cascade in the system."""
    cid = case["id"]
    _cancel(children("tasks", cid), ("PENDING", "SUBMITTED", "REJECTED"))
    _cancel(children("clearances", cid), ("IN_PROGRESS", "ESCALATED"))
    order = order_of(cid)
    if order is not None and order["status"] in (
            "DRAFT", "SUBMITTED", "IN_PROGRESS", "ATTENTION_REQUIRED"):
        order["status"] = "CANCELLED"
        touch(order)
        _cancel(children("items", order["id"], key="order_id"),
                ("PENDING", "IN_FULFILLMENT", "BLOCKED"))
    _cancel(children("trainings", cid), ("ASSIGNED", "OVERDUE"))
    _cancel(children("checkins", cid), ("SCHEDULED", "MISSED"))
    _cancel(children("cycles", cid), ("ACTIVE", "EVALUATION_DUE"))
    _release_booking(case)
    _cancel(children("surveys", cid), ("SENT",))
    nh = store["new_hires"].get(case["new_hire_id"])
    if nh is not None:
        nh["status"] = "RESCINDED"
        touch(nh)
    case["phase"] = "WITHDRAWN"
    touch(case)
    refresh_health(case)


def separate_case(case):
    """PROBATION -> SEPARATED teardown (probation FAIL)."""
    cid = case["id"]
    _cancel(children("trainings", cid), ("ASSIGNED", "OVERDUE"))
    _cancel(children("checkins", cid), ("SCHEDULED", "MISSED"))
    _cancel(children("cycles", cid), ("ACTIVE", "EVALUATION_DUE"))
    _cancel(children("surveys", cid), ("SENT",))
    for h in children("handoffs", cid):
        if h["status"] in ("DRAFT", "TRANSMITTED"):
            h["status"] = "WITHDRAWN"
            touch(h)
    nh = store["new_hires"].get(case["new_hire_id"])
    if nh is not None:
        nh["status"] = "SEPARATED"
        touch(nh)
    case["phase"] = "SEPARATED"
    touch(case)
    refresh_health(case)


def advance_day_one(case):
    """DAY_ONE_READY -> IN_PROGRESS: hire becomes EMPLOYED, survey created."""
    case["phase"] = "IN_PROGRESS"
    touch(case)
    nh = store["new_hires"].get(case["new_hire_id"])
    if nh is not None and nh["status"] == "REGISTERED":
        nh["status"] = "EMPLOYED"
        touch(nh)
    now = clock.current
    new_record("surveys", {
        "case_id": case["id"], "status": "SENT",
        "sent_at": fmt_dt(now), "expires_at": fmt_dt(now + timedelta(days=14)),
        "onboarding_experience_rating": None, "manager_support_rating": None,
        "resources_rating": None, "overall_score": None,
        "_sent_dt": now, "_expires_dt": now + timedelta(days=14),
    })


# ------------------------------------------------------- order compound ----

def rederive_order_status(order):
    """Compound status from items. Returns True when the status changed."""
    items = children("items", order["id"], key="order_id")
    if not items:
        return False
    old = order["status"]
    if all(i["status"] == "DONE" for i in items):
        if old != "FULFILLED":
            order["status"] = "FULFILLED"
            now = clock.current
            order["_fulfilled_dt"] = now
            order["fulfilled_at"] = fmt_dt(now)
            touch(order)
            case = store["cases"].get(order["case_id"])
            if case is not None:
                refresh_health(case)
                reeval_day_one_gate(case)
            return True
        return False
    if any(i["status"] == "BLOCKED" for i in items):
        new = "ATTENTION_REQUIRED"
    elif any(i["status"] != "PENDING" for i in items):
        new = "IN_PROGRESS"
    else:
        new = "SUBMITTED"
    if new != old and old != "FULFILLED":
        order["status"] = new
        touch(order)
        if new == "ATTENTION_REQUIRED" or old == "ATTENTION_REQUIRED":
            case = store["cases"].get(order["case_id"])
            if case is not None:
                refresh_health(case)
        return True
    return False


# ----------------------------------------------------------------- sweep ----

def sweep():
    """Evaluate every pending time-based transition as one atomic sweep
    (PRD §2.5). The session-conducted/no-show step runs before the day-one
    advancement so that a case still waiting for day one is no-show-swept
    while pre-day-one; a case that already reached IN_PROGRESS is employed
    and out of scope for the orientation no-show sweep."""
    now = clock.current

    # 1. OrientationSession SCHEDULED/FULL -> CONDUCTED (now >= ends_at),
    #    with the no-show sweep of still-BOOKED pre-day-one cases.
    for s in list(store["sessions"].values()):
        if s["status"] in ("SCHEDULED", "FULL") and now >= s["_ends_dt"]:
            s["status"] = "CONDUCTED"
            touch(s)
            for case in list(store["cases"].values()):
                if case.get("orientation_session_id") == s["id"] and \
                        case.get("orientation_rsvp") == "BOOKED" and \
                        case["phase"] in ("PROVISIONING", "DAY_ONE_READY"):
                    case["orientation_rsvp"] = "NO_SHOW"
                    touch(case)
                    reeval_day_one_gate(case)

    # 2. Day-one phase advancement: DAY_ONE_READY -> IN_PROGRESS
    for case in list(store["cases"].values()):
        if case["phase"] == "DAY_ONE_READY":
            start_dt = datetime.combine(case["_start_d"], dtime(0, 0, 0),
                                        tzinfo=timezone.utc)
            if now >= start_dt:
                advance_day_one(case)

    # 3. TrainingAssignment ASSIGNED -> OVERDUE (now > due_at)
    for t in list(store["trainings"].values()):
        if t["status"] == "ASSIGNED" and now > t["_due_dt"]:
            t["status"] = "OVERDUE"
            touch(t)

    # 4. CheckIn SCHEDULED -> MISSED (now > scheduled_at + 24h)
    for c in list(store["checkins"].values()):
        if c["status"] == "SCHEDULED" and \
                now > c["_sched_dt"] + timedelta(hours=24):
            c["status"] = "MISSED"
            touch(c)

    # 5. Survey SENT -> EXPIRED (now > expires_at)
    for s in list(store["surveys"].values()):
        if s["status"] == "SENT" and now > s["_expires_dt"]:
            s["status"] = "EXPIRED"
            touch(s)

    # 6. ProbationCycle ACTIVE -> EVALUATION_DUE (now >= evaluation_due_at)
    for cy in list(store["cycles"].values()):
        if cy["status"] == "ACTIVE" and now >= cy["_eval_due_dt"]:
            cy["status"] = "EVALUATION_DUE"
            touch(cy)

    # 7. Health pass over every case (flips on live cases bump the version).
    for case in list(store["cases"].values()):
        refresh_health(case)
