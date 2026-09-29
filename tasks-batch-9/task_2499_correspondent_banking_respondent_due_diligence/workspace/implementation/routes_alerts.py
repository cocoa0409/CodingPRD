"""Monitoring alerts and their disposition (PRD 3.7)."""

from flask import Blueprint

import cascade
import store
from common import OPS, arg, eq, need, need_respondent, paged, start, PREFIX
from errors import fail
from response import ok, ok_list
from validate import body, fenum, fstr, validate

bp = Blueprint("alerts", __name__)

ALERT_TYPES = ("VOLUME_BREACH", "COUNT_BREACH", "CORRIDOR_UNEXPECTED",
               "NESTED_ACTIVITY_UNDISCLOSED")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
DISPOSITIONS = ("DATA_QUALITY", "EXPECTED_SEASONALITY", "RESPONDENT_EXPLAINED",
                "UNRESOLVED_RISK", "PROHIBITED_NESTING")
FALSE_POSITIVE_REASONS = ("DATA_QUALITY", "EXPECTED_SEASONALITY",
                          "RESPONDENT_EXPLAINED")


@bp.post(PREFIX + "/respondents/<respondent_id>/monitoring-alerts")
def raise_alert(respondent_id):
    start(("ComplianceAnalyst", "SanctionsOfficer"))
    resp = need_respondent(respondent_id)
    data = body()
    validate(data, [
        fenum("alert_type", ALERT_TYPES, True),
        fenum("severity", SEVERITIES, True),
        fstr("activity_observation_id", False, 1, None),
    ])
    cascade.guard_not_closed(resp)
    observation_id = data.get("activity_observation_id")
    if observation_id is not None:
        observation = store.get("observations", observation_id)
        if observation is None:
            fail("ERR_ACTIVITY_OBSERVATION_NOT_FOUND",
                 "activity_observation_id does not resolve.")
        profile = store.get("profiles", observation["monitoring_profile_id"])
        if profile is None or profile["respondent_bank_id"] != resp["id"]:
            fail("ERR_CROSS_RESPONDENT_REFERENCE",
                 "That observation belongs to another respondent's profile.")
    row = store.insert("alerts", {
        "respondent_bank_id": resp["id"],
        "activity_observation_id": observation_id,
        "alert_type": data["alert_type"],
        "severity": data["severity"],
        "state": "OPEN",
        "breach_ratio": None,
        "investigated_by_user_id": None,
        "disposition_reason": None,
        "escalated_at": None,
    })
    return ok(row, 201)


@bp.get(PREFIX + "/monitoring-alerts")
def list_alerts():
    start(OPS)
    rows = store.by_seq(store.all_rows("alerts"))
    rows = eq(rows, "respondent_bank_id", arg("respondent_bank_id"))
    rows = eq(rows, "activity_observation_id", arg("activity_observation_id"))
    rows = eq(rows, "state", arg("state"))
    rows = eq(rows, "severity", arg("severity"))
    rows = eq(rows, "alert_type", arg("alert_type"))
    page, limit, offset, total = paged(rows)
    return ok_list(page, limit, offset, total)


@bp.get(PREFIX + "/monitoring-alerts/<alert_id>")
def read_alert(alert_id):
    start(OPS)
    return ok(need("alerts", alert_id))


ACTIONS = ("INVESTIGATE", "ESCALATE", "CLOSE_FALSE_POSITIVE", "CLOSE_CONFIRMED")
FROM_STATES = {
    "INVESTIGATE": ("OPEN",),
    "ESCALATE": ("UNDER_INVESTIGATION",),
    "CLOSE_FALSE_POSITIVE": ("UNDER_INVESTIGATION",),
    "CLOSE_CONFIRMED": ("UNDER_INVESTIGATION", "ESCALATED"),
}


@bp.post(PREFIX + "/monitoring-alerts/<alert_id>/disposition")
def disposition(alert_id):
    ctx = start(("ComplianceAnalyst", "SanctionsOfficer"))
    alert = need("alerts", alert_id)
    data = body()
    validate(data, [
        fenum("action", ACTIONS, True),
        fenum("disposition_reason", DISPOSITIONS, False),
    ])
    resp = store.get("respondents", alert["respondent_bank_id"])
    action = data["action"]
    reason = data.get("disposition_reason")
    if action in ("INVESTIGATE", "ESCALATE"):
        if resp["dd_state"] in ("DECLINED", "TERMINATED"):
            fail("ERR_INVALID_RESPONDENT_STATE",
                 "This respondent state permits no alert disposition.")
        if action == "ESCALATE" and resp["dd_state"] == "EXITING":
            fail("ERR_INVALID_RESPONDENT_STATE",
                 "An exiting relationship accepts no escalation.")
    cascade.guard_not_closed(resp)
    if alert["state"] not in FROM_STATES[action]:
        fail("ERR_INVALID_ALERT_STATE",
             "Action %s is not declared from state %s." % (action, alert["state"]))
    if action == "CLOSE_FALSE_POSITIVE":
        if alert["alert_type"] == "NESTED_ACTIVITY_UNDISCLOSED":
            fail("ERR_INVALID_ALERT_STATE",
                 "An undisclosed-nesting alert is never a false positive.")
        if reason not in FALSE_POSITIVE_REASONS:
            fail("ERR_INVALID_REQUEST_BODY",
                 "A false-positive closure requires a data-quality, seasonality or "
                 "explained reason.")
    if action == "CLOSE_CONFIRMED" and reason is None:
        fail("ERR_INVALID_REQUEST_BODY",
             "disposition_reason is required to close an alert as confirmed.")
    _require_segregation(alert, ctx)
    if action == "ESCALATE":
        for rfi in store.rfis_of(resp["id"]):
            if rfi.get("monitoring_alert_id") == alert["id"] and \
                    rfi["state"] in ("SENT", "OVERDUE", "ESCALATED"):
                fail("ERR_INVALID_ALERT_STATE",
                     "An information request raised from this alert is still open.")
        cascade.escalate_alert(alert, resp)
        return ok(alert)
    if action == "INVESTIGATE":
        alert["state"] = "UNDER_INVESTIGATION"
        alert["investigated_by_user_id"] = ctx.user_id
    elif action == "CLOSE_FALSE_POSITIVE":
        alert["state"] = "CLOSED_FALSE_POSITIVE"
        alert["disposition_reason"] = reason
    else:
        alert["state"] = "CLOSED_CONFIRMED"
        alert["disposition_reason"] = reason
    store.touch(alert)
    if action == "CLOSE_CONFIRMED" and reason in ("UNRESOLVED_RISK",
                                                 "PROHIBITED_NESTING"):
        restriction_reason = "ADVERSE_MEDIA" if reason == "UNRESOLVED_RISK" \
            else "PROHIBITED_NESTING"
        if resp["dd_state"] in cascade.APPROVED_FAMILY:
            cascade.restrict(resp, restriction_reason, "BLOCKED")
    return ok(alert)


def _require_segregation(alert, ctx):
    for rfi in store.rfis_of(alert["respondent_bank_id"]):
        if rfi.get("monitoring_alert_id") != alert["id"]:
            continue
        if rfi.get("adjudicated_by_user_id") == ctx.user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The identity that adjudicated the linked information request may "
                 "not dispose of this alert.")
