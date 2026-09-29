"""Information requests: dispatch, response, chasing and adjudication (PRD 3.8)."""

from flask import Blueprint

import calc
import cascade
import clock
import store
from common import (ALL, arg, eq, list_scope, need, need_respondent, paged,
                    scoped_child, start, PREFIX)
from errors import fail
from response import ok, ok_list
from validate import body, fbool, fenum, fstr, validate

bp = Blueprint("rfis", __name__)

TOPICS = ("OWNERSHIP_EVIDENCE", "LICENSING_EVIDENCE", "NESTED_DISCLOSURE",
          "ACTIVITY_EXPLANATION", "CONTROL_REMEDIATION")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


@bp.post(PREFIX + "/respondents/<respondent_id>/information-requests")
def create_request(respondent_id):
    start(("ComplianceAnalyst", "SanctionsOfficer"))
    resp = need_respondent(respondent_id)
    data = body()
    validate(data, [
        fenum("request_topic", TOPICS, True),
        fenum("severity", SEVERITIES, True),
        fstr("monitoring_alert_id", False, 1, None),
    ])
    cascade.guard_not_closed(resp, allow_exiting=True)
    alert_id = data.get("monitoring_alert_id")
    if alert_id is not None:
        alert = store.get("alerts", alert_id)
        if alert is None:
            fail("ERR_MONITORING_ALERT_NOT_FOUND",
                 "monitoring_alert_id does not resolve.")
        if alert["respondent_bank_id"] != resp["id"]:
            fail("ERR_CROSS_RESPONDENT_REFERENCE",
                 "That alert belongs to another respondent.")
        if alert["severity"] != data["severity"]:
            fail("ERR_INVALID_REQUEST_BODY",
                 "The request severity must equal the linked alert's severity.")
    row = cascade.new_request(resp, data["request_topic"], data["severity"], alert_id)
    return ok(row, 201)


@bp.get(PREFIX + "/information-requests")
def list_requests():
    ctx = start(ALL)
    scope_id = list_scope(ctx)
    rows = store.by_seq(store.all_rows("rfis"))
    rows = eq(rows, "respondent_bank_id", scope_id)
    rows = eq(rows, "monitoring_alert_id", arg("monitoring_alert_id"))
    rows = eq(rows, "state", arg("state"))
    rows = eq(rows, "request_topic", arg("request_topic"))
    page, limit, offset, total = paged(rows)
    return ok_list(page, limit, offset, total)


@bp.get(PREFIX + "/information-requests/<request_id>")
def read_request(request_id):
    ctx = start(ALL)
    return ok(scoped_child("rfis", request_id, ctx))


@bp.post(PREFIX + "/information-requests/<request_id>/dispatch")
def dispatch(request_id):
    start(("ComplianceAnalyst", "SanctionsOfficer"))
    row = need("rfis", request_id)
    resp = store.get("respondents", row["respondent_bank_id"])
    if resp["dd_state"] in ("PROSPECT", "DECLINED", "TERMINATED"):
        fail("ERR_INVALID_RESPONDENT_STATE",
             "This respondent state permits no dispatch.")
    cascade.guard_not_closed(resp, allow_exiting=True)
    if row["state"] not in ("DRAFT", "ESCALATED"):
        fail("ERR_INVALID_RFI_STATE",
             "Only a draft or escalated request may be dispatched.")
    if row["state"] == "ESCALATED" and int(row["reminder_count"]) > 2:
        fail("ERR_INVALID_RFI_STATE",
             "This request has already been reminded too many times to re-issue.")
    alert_id = row.get("monitoring_alert_id")
    if alert_id:
        alert = store.get("alerts", alert_id)
        if alert is None or alert["state"] not in ("ESCALATED", "UNDER_INVESTIGATION"):
            fail("ERR_INVALID_ALERT_STATE",
                 "The linked alert is not open for a dispatch.")
    cascade.dispatch_request(row, resp)
    if row["severity"] == "CRITICAL":
        cascade.narrow_to_screen_only(resp)
    return ok(row)


@bp.post(PREFIX + "/information-requests/<request_id>/response")
def respond(request_id):
    ctx = start(("RespondentContact",))
    row = scoped_child("rfis", request_id, ctx)
    data = body()
    validate(data, [fstr("response_note", True, 1, 1000)])
    resp = store.get("respondents", row["respondent_bank_id"])
    if resp["dd_state"] == "TERMINATED":
        fail("ERR_INVALID_RESPONDENT_STATE",
             "A terminated relationship accepts no response.")
    if row["state"] not in ("SENT", "OVERDUE", "ESCALATED"):
        fail("ERR_INVALID_RFI_STATE",
             "Only a dispatched request may be answered.")
    row["state"] = "RESPONDED"
    row["response_note"] = data["response_note"]
    store.set_dt(row, "responded_at", clock.now())
    store.touch(row)
    return ok(row)


@bp.post(PREFIX + "/information-requests/<request_id>/overdue-marking")
def overdue_marking(request_id):
    start(("ComplianceAnalyst", "PlatformAdmin"))
    row = need("rfis", request_id)
    data = body()
    validate(data, [fenum("action", ("REMIND", "MARK_OVERDUE", "ESCALATE"), True)])
    resp = store.get("respondents", row["respondent_bank_id"])
    cascade.guard_not_closed(resp, allow_exiting=True)
    action = data["action"]
    allowed = {"REMIND": ("SENT", "OVERDUE"), "MARK_OVERDUE": ("SENT",),
               "ESCALATE": ("OVERDUE",)}
    if row["state"] not in allowed[action]:
        fail("ERR_INVALID_RFI_STATE",
             "Action %s is not declared from state %s." % (action, row["state"]))
    now = clock.now()
    due = store.dt(row, "due_at")
    if action == "REMIND":
        row["reminder_count"] = int(row["reminder_count"]) + 1
        store.touch(row)
    elif action == "MARK_OVERDUE":
        if due is None or now < due:
            fail("ERR_RFI_NOT_YET_OVERDUE",
                 "The logical clock has not reached due_at.")
        row["state"] = "OVERDUE"
        row["reminder_count"] = int(row["reminder_count"]) + 1
        row["escalation_level"] = min(3, int(row["escalation_level"]) + 1)
        store.touch(row)
        cascade.recompute_escalation_units(resp)
        cascade.add_strike(resp)
    else:
        if due is None or now < clock.add_hours(due, 72):
            fail("ERR_RFI_NOT_YET_OVERDUE",
                 "The next 72-hour escalation window has not elapsed.")
        row["escalation_level"] = min(3, int(row["escalation_level"]) + 1)
        row["state"] = "ESCALATED"
        store.touch(row)
        cascade.recompute_escalation_units(resp)
    return ok(row)


@bp.post(PREFIX + "/information-requests/<request_id>/adjudication")
def adjudication(request_id):
    ctx = start(("ComplianceAnalyst", "SanctionsOfficer"))
    row = need("rfis", request_id)
    data = body()
    validate(data, [
        fenum("action", ("ACCEPT", "INSUFFICIENT", "ABANDON"), True),
        fbool("retro_credit", False),
    ])
    resp = store.get("respondents", row["respondent_bank_id"])
    cascade.guard_not_closed(resp, allow_exiting=True)
    action = data["action"]
    if action in ("ACCEPT", "INSUFFICIENT"):
        if row["state"] != "RESPONDED":
            fail("ERR_INVALID_RFI_STATE",
                 "Only a responded request may be adjudicated that way.")
    else:
        if row["state"] == "ESCALATED":
            if int(row["escalation_level"]) != 3:
                fail("ERR_INVALID_RFI_STATE",
                     "An escalated request is abandoned only at escalation level 3.")
        elif row["state"] != "OVERDUE":
            fail("ERR_INVALID_RFI_STATE",
                 "Only an overdue or fully escalated request may be abandoned.")
    if action == "ACCEPT":
        if ctx.user_id == resp["id"]:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The respondent may not adjudicate its own request.")
        row["state"] = "ACCEPTED"
        row["adjudicated_by_user_id"] = ctx.user_id
        row["escalation_level"] = 0
        credit = bool(data.get("retro_credit")) and int(row["reminder_count"]) > 0
        if credit:
            row["retro_credited"] = True
        store.touch(row)
        cascade.recompute_escalation_units(resp)
        if credit:
            cascade.credit_strikes(resp, int(row["reminder_count"]))
        cascade.close_alert_from_rfi(row, "RESPONDENT_EXPLAINED")
    elif action == "INSUFFICIENT":
        if int(row["insufficiency_rounds"]) > 1:
            fail("ERR_ROUNDS_EXHAUSTED", "The insufficiency budget is exhausted.")
        row["insufficiency_rounds"] = int(row["insufficiency_rounds"]) + 1
        row["escalation_level"] = min(3, int(row["escalation_level"]) + 1)
        row["state"] = "SENT"
        now = clock.now()
        hours = calc.rfi_sla_hours(resp, row["severity"])
        store.set_dt(row, "dispatched_at", now)
        row["sla_hours"] = hours
        store.set_dt(row, "due_at", clock.add_hours(now, hours))
        store.touch(row)
        cascade.recompute_escalation_units(resp)
    else:
        row["state"] = "ABANDONED"
        row["adjudicated_by_user_id"] = ctx.user_id
        row["escalation_level"] = 0
        store.touch(row)
        cascade.recompute_escalation_units(resp)
        cascade.add_strike(resp)
        cascade.close_alert_from_rfi(row, "UNRESOLVED_RISK")
    return ok(row)
