"""Periodic refresh cycles and the operator sweep (PRD 3.8)."""

from flask import Blueprint

import calc
import cascade
import clock
import store
from common import (ALL, arg, eq, list_scope, need, need_respondent, paged,
                    scoped_child, start, PREFIX)
from errors import fail
from response import ok, ok_list
from validate import body, fbool, fdate, fenum, validate

bp = Blueprint("refresh", __name__)

TRIGGERS = ("CADENCE", "ADVERSE_MEDIA", "ALERT_ESCALATION", "NESTED_DISCOVERY",
            "REGULATOR_ACTION")
ACCELERATING = ("ADVERSE_MEDIA", "ALERT_ESCALATION", "NESTED_DISCOVERY")
CANCEL_REASONS = ("SUPERSEDED_BY_ACCELERATION", "RELATIONSHIP_EXITING")
LIVE_STATES = ("SCHEDULED", "IN_PROGRESS")


def _narrow(resp):
    """OPEN -> SCREEN_ONLY, leaving any narrower posture untouched."""
    if resp["payment_posture"] != "OPEN":
        return False
    resp["payment_posture"] = "SCREEN_ONLY"
    store.touch(resp)
    cascade.hold_cleared_payments(resp)
    return True


@bp.post(PREFIX + "/respondents/<respondent_id>/periodic-refreshes")
def schedule(respondent_id):
    start(("ComplianceAnalyst", "PlatformAdmin"))
    resp = need_respondent(respondent_id)
    data = body()
    parsed = validate(data, [
        fenum("trigger_reason", TRIGGERS, True),
        fdate("window_start", True),
        fdate("scheduled_due_date", True),
    ])
    cascade.guard_not_closed(resp)
    win_start = parsed["window_start"]
    win_end = parsed["scheduled_due_date"]
    for cycle in store.refreshes_of(resp["id"]):
        if cycle["state"] not in LIVE_STATES:
            continue
        other_start = store.dt(cycle, "window_start")
        other_end = store.dt(cycle, "scheduled_due_date")
        if other_start is None or other_end is None:
            continue
        if win_start < other_end and other_start < win_end:
            fail("ERR_REFRESH_WINDOW_OVERLAP",
                 "The half-open window overlaps a live refresh cycle.")
    for cycle in store.refreshes_of(resp["id"]):
        if cycle["state"] != "COMPLETED":
            continue
        other_end = store.dt(cycle, "scheduled_due_date")
        if other_end is None:
            continue
        if other_end <= win_start < clock.add_days(other_end, 30):
            fail("ERR_REFRESH_BUFFER_VIOLATION",
                 "window_start falls inside the 30-day buffer after a completed cycle.")
    row = cascade.schedule_cycle(resp, data["trigger_reason"], win_start, win_end)
    if data["trigger_reason"] in ACCELERATING:
        for cycle in store.by_seq(store.refreshes_of(resp["id"])):
            if cycle["id"] == row["id"] or cycle["state"] != "SCHEDULED":
                continue
            cycle["state"] = "CANCELLED"
            cycle["cancelled_reason"] = "SUPERSEDED_BY_ACCELERATION"
            store.touch(cycle)
    if resp["dd_state"] == "APPROVED":
        resp["dd_state"] = "REFRESH_DUE"
    store.touch(resp)
    return ok(row, 201)


@bp.get(PREFIX + "/periodic-refreshes")
def list_refreshes():
    ctx = start(ALL)
    scope_id = list_scope(ctx)
    rows = store.all_rows("refreshes")
    rows = eq(rows, "respondent_bank_id", scope_id)
    rows = eq(rows, "state", arg("state"))
    rows = eq(rows, "trigger_reason", arg("trigger_reason"))
    rows.sort(key=lambda r: (store.dt(r, "window_start") or clock.DEFAULT_CLOCK,
                            r["_seq"]))
    page, limit, offset, total = paged(rows)
    return ok_list(page, limit, offset, total)


@bp.get(PREFIX + "/periodic-refreshes/<refresh_id>")
def read_refresh(refresh_id):
    ctx = start(ALL)
    return ok(scoped_child("refreshes", refresh_id, ctx))


ACTIONS = ("START", "COMPLETE", "LAPSE", "CANCEL")
FROM_STATES = {
    "START": ("SCHEDULED",),
    "COMPLETE": ("IN_PROGRESS",),
    "LAPSE": ("SCHEDULED", "IN_PROGRESS"),
    "CANCEL": ("SCHEDULED",),
}


@bp.post(PREFIX + "/periodic-refreshes/<refresh_id>/progression")
def progression(refresh_id):
    start(("ComplianceAnalyst", "PlatformAdmin"))
    row = need("refreshes", refresh_id)
    data = body()
    validate(data, [
        fenum("action", ACTIONS, True),
        fenum("cancelled_reason", CANCEL_REASONS, False),
    ])
    resp = store.get("respondents", row["respondent_bank_id"])
    action = data["action"]
    if action in ("START", "COMPLETE"):
        cascade.guard_not_closed(resp)
    else:
        cascade.guard_not_closed(resp, allow_exiting=True)
    if row["state"] not in FROM_STATES[action]:
        fail("ERR_INVALID_REFRESH_STATE",
             "Action %s is not declared from state %s." % (action, row["state"]))
    if action == "START":
        _start_cycle(row, resp)
    elif action == "COMPLETE":
        _complete_cycle(row, resp)
    elif action == "LAPSE":
        _lapse_cycle(row, resp)
    else:
        if data.get("cancelled_reason") is None:
            fail("ERR_INVALID_REQUEST_BODY",
                 "cancelled_reason is required to cancel a refresh cycle.")
        row["state"] = "CANCELLED"
        row["cancelled_reason"] = data["cancelled_reason"]
        store.touch(row)
    return ok(row)


def _start_cycle(row, resp):
    now = clock.now()
    win_start = store.dt(row, "window_start")
    if win_start is not None and now < win_start:
        fail("ERR_INVALID_REFRESH_STATE",
             "The logical clock has not reached window_start.")
    if resp["dd_state"] not in ("APPROVED", "REFRESH_DUE", "REFRESH_OVERDUE"):
        fail("ERR_INVALID_RESPONDENT_STATE",
             "This respondent state permits no refresh start.")
    for other in store.refreshes_of(resp["id"]):
        if other["id"] != row["id"] and other["state"] == "IN_PROGRESS":
            fail("ERR_INVALID_REFRESH_STATE",
                 "Another refresh cycle of this respondent is already in progress.")
    row["state"] = "IN_PROGRESS"
    store.set_dt(row, "started_at", now)
    store.touch(row)
    resp["dd_state"] = "UNDER_REFRESH"
    store.touch(resp)


def _complete_cycle(row, resp):
    started = store.dt(row, "started_at")
    reassessed = False
    for q in store.questionnaires_of(resp["id"]):
        assessed_at = store.dt(q, "assessed_at")
        if q["state"] == "ASSESSED" and assessed_at is not None and started is not None \
                and assessed_at >= started:
            reassessed = True
            break
    if not reassessed:
        fail("ERR_INVALID_QUESTIONNAIRE_STATE",
             "No questionnaire has been assessed since this cycle started.")
    live_assessed = store.dt(resp, "last_risk_assessed_at")
    if resp["risk_assessment_variant"] != "REFRESH_FINAL" or live_assessed is None \
            or started is None or live_assessed < started:
        fail("ERR_REFRESH_NOT_REASSESSED",
             "A REFRESH_FINAL risk assessment since the cycle start is required.")
    if not resp["ownership_verified"]:
        fail("ERR_OWNERSHIP_CHAIN_INCOMPLETE",
             "Ownership must be verified before a refresh completes.")
    if resp["risk_rating"] == "PROHIBITED":
        fail("ERR_INVALID_RESPONDENT_STATE",
             "A prohibited rating cannot complete a refresh.")
    now = clock.now()
    store.set_dt(row, "completed_at", now)
    row["completed_control_score"] = resp["control_score"]
    row["completion_risk_rating"] = resp["risk_rating"]
    row["state"] = "COMPLETED"
    store.touch(row)
    resp["dd_state"] = "APPROVED"
    resp["approved_risk_rating"] = resp["risk_rating"]
    store.set_dt(resp, "last_approved_at", now)
    store.touch(resp)
    cascade.write_refresh_due_date(resp)
    cascade.require_recalibration(resp, "REFRESH_COMPLETION")


def _lapse_cycle(row, resp):
    now = clock.now()
    due = store.dt(row, "scheduled_due_date")
    from_scheduled = row["state"] == "SCHEDULED"
    if from_scheduled:
        if due is not None and now < due:
            fail("ERR_INVALID_REFRESH_STATE",
                 "The logical clock has not reached scheduled_due_date.")
    else:
        if due is not None and now < clock.add_days(due, 90):
            fail("ERR_INVALID_REFRESH_STATE",
                 "An in-progress cycle lapses only 90 days past scheduled_due_date.")
    row["state"] = "LAPSED"
    store.set_dt(row, "lapsed_at", now)
    store.touch(row)
    resp["dd_state"] = "REFRESH_OVERDUE"
    store.touch(resp)
    if from_scheduled:
        _narrow(resp)
    _restriction_grace(resp)


def _restriction_grace(resp):
    """REFRESH_OVERDUE -> RESTRICTED once the 30-day grace has elapsed."""
    if resp["dd_state"] != "REFRESH_OVERDUE":
        return
    lapsed = [c for c in store.refreshes_of(resp["id"]) if c["state"] == "LAPSED"]
    if not lapsed:
        return
    lapsed.sort(key=lambda c: c["_seq"], reverse=True)
    lapsed.sort(key=lambda c: store.dt(c, "scheduled_due_date") or clock.DEFAULT_CLOCK,
                reverse=True)
    due = store.dt(lapsed[0], "scheduled_due_date")
    if due is None:
        return
    if clock.now() >= clock.add_days(due, 30):
        cascade.restrict(resp, "REFRESH_LAPSED", "BLOCKED")


# ------------------------------------------------------------- the sweep -----

def _sweep_order():
    rows = store.all_rows("respondents")
    rows.sort(key=lambda r: r["_seq"])
    rows.sort(key=lambda r: (0, store.dt(r, "refresh_due_date"))
              if store.dt(r, "refresh_due_date") is not None
              else (1, clock.DEFAULT_CLOCK))
    return rows


def _cadence_due(resp, now):
    if resp["dd_state"] != "APPROVED":
        return False
    if store.dt(resp, "last_approved_at") is None:
        return False
    due = store.dt(resp, "refresh_due_date")
    if due is None or now < due:
        return False
    for cycle in store.refreshes_of(resp["id"]):
        if cycle["state"] in LIVE_STATES:
            return False
    return True


def _lapse_ready(cycle, now):
    due = store.dt(cycle, "scheduled_due_date")
    if due is None:
        return False
    if cycle["state"] == "SCHEDULED":
        return now >= due
    if cycle["state"] == "IN_PROGRESS":
        return now >= clock.add_days(due, 90)
    return False


def _sweep_plan(resp, now):
    """The transitions the sweep would apply to one respondent."""
    lapse = [c for c in store.by_seq(store.refreshes_of(resp["id"]))
             if _lapse_ready(c, now)]
    overdue = []
    escalate = []
    for rfi in store.by_seq(store.rfis_of(resp["id"])):
        due = store.dt(rfi, "due_at")
        if due is None:
            continue
        if rfi["state"] == "SENT" and now >= due:
            overdue.append(rfi)
            if now >= clock.add_hours(due, 72):
                escalate.append(rfi)
        elif rfi["state"] == "OVERDUE" and now >= clock.add_hours(due, 72):
            escalate.append(rfi)
    return _cadence_due(resp, now), lapse, overdue, escalate


@bp.post(PREFIX + "/refresh-sweeps")
def refresh_sweep():
    start(("PlatformAdmin",))
    data = body()
    validate(data, [fbool("dry_run", False)])
    dry_run = bool(data.get("dry_run"))
    now = clock.now()
    affected = []
    for resp in _sweep_order():
        cadence, lapse, overdue, escalate = _sweep_plan(resp, now)
        if not (cadence or lapse or overdue or escalate):
            continue
        affected.append(resp)
        if dry_run:
            continue
        if cadence:
            due = store.dt(resp, "refresh_due_date")
            cascade.schedule_cycle(resp, "CADENCE", due, clock.add_days(due, 90),
                                   rating_at_schedule=resp["risk_rating"],
                                   cadence_rating=resp["approved_risk_rating"])
            resp["dd_state"] = "REFRESH_DUE"
            store.touch(resp)
        for cycle in lapse:
            _lapse_cycle(cycle, resp)
        for rfi in overdue:
            rfi["state"] = "OVERDUE"
            rfi["reminder_count"] = int(rfi["reminder_count"]) + 1
            rfi["escalation_level"] = min(3, int(rfi["escalation_level"]) + 1)
            store.touch(rfi)
            cascade.recompute_escalation_units(resp)
            cascade.add_strike(resp)
        for rfi in escalate:
            rfi["escalation_level"] = 3
            rfi["state"] = "ESCALATED"
            store.touch(rfi)
            cascade.recompute_escalation_units(resp)
            _narrow(resp)
    return ok_list(affected, len(affected), 0, len(affected))
