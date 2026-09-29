"""Nested correspondents: discovery, depth and the prohibition ladder (PRD 3.5)."""

from flask import Blueprint

import calc
import cascade
import clock
import store
from common import (ALL, OPS, arg, eq, list_scope, need, need_respondent, paged,
                    scoped_child, start, PREFIX)
from errors import fail
from response import ok, ok_list
from validate import body, fenum, fstr, validate

bp = Blueprint("nested", __name__)

TYPES = ("DOWNSTREAM_CORRESPONDENT", "PAYABLE_THROUGH", "NESTED_PSP")
SOURCES = ("QUESTIONNAIRE", "TRANSACTION_MONITORING", "RFI", "ADVERSE_MEDIA")
STATES = ("DISCLOSED", "UNDISCLOSED_DETECTED", "CONFIRMED", "SUSPENDED",
          "PROHIBITED", "TERMINATED")
REASONS = ("CYCLE", "SANCTIONED_JURISDICTION", "JURISDICTION_PROHIBITS_NESTING",
           "DEPTH_EXCEEDED", "PAYABLE_THROUGH_NOT_PERMITTED")

CREATE_SPEC = [
    fstr("downstream_institution_name", True, 1, 160),
    fstr("downstream_jurisdiction_code", True, 1, None),
    fenum("relationship_type", TYPES, True),
    fenum("discovery_source", SOURCES, True),
    fstr("downstream_respondent_bank_id", False, 1, None),
]


@bp.post(PREFIX + "/respondents/<respondent_id>/nested-relationships")
def create_nested(respondent_id):
    ctx = start(("ComplianceAnalyst", "RespondentContact", "SanctionsOfficer"),
                respondent_id)
    resp = need_respondent(respondent_id)
    data = body()
    validate(data, CREATE_SPEC)
    source = data["discovery_source"]
    if ctx.is_contact and source != "QUESTIONNAIRE":
        fail("ERR_FORBIDDEN_ROLE",
             "A respondent contact may only declare questionnaire-sourced rows.")
    if store.jurisdiction_by_code(data["downstream_jurisdiction_code"]) is None:
        fail("ERR_JURISDICTION_PROFILE_NOT_FOUND",
             "downstream_jurisdiction_code %s does not resolve."
             % data["downstream_jurisdiction_code"])
    downstream_id = data.get("downstream_respondent_bank_id")
    if downstream_id is not None:
        if store.get("respondents", downstream_id) is None:
            fail("ERR_RESPONDENT_NOT_FOUND",
                 "downstream_respondent_bank_id does not resolve.")
    cascade.guard_not_closed(resp)
    for other in store.nested_of(resp["id"]):
        if (other["downstream_institution_name"] == data["downstream_institution_name"]
                and other["downstream_jurisdiction_code"]
                == data["downstream_jurisdiction_code"]
                and other["state"] not in ("PROHIBITED", "TERMINATED")):
            fail("ERR_DUPLICATE_RESOURCE",
                 "This downstream institution is already recorded for the respondent.")
    row = store.insert("nested", {
        "respondent_bank_id": resp["id"],
        "downstream_respondent_bank_id": downstream_id,
        "downstream_institution_name": data["downstream_institution_name"],
        "downstream_jurisdiction_code": data["downstream_jurisdiction_code"],
        "relationship_type": data["relationship_type"],
        "discovery_source": source,
        "state": "DISCLOSED" if source == "QUESTIONNAIRE" else "UNDISCLOSED_DETECTED",
        "depth": 1,
        "prohibition_reason": None,
        "adjudicated_by_user_id": None,
        "adjudicated_at": None,
    })
    depth, cycle = cascade.compute_nested_depth(row)
    if not cycle and depth > 4:
        del store.db["nested"][row["id"]]
        fail("ERR_NESTED_DEPTH_EXCEEDED",
             "A computed depth of %d exceeds the ceiling of 4." % depth)
    row["depth"] = depth
    reason, error_id = cascade.prohibition_ladder(row, resp, depth, cycle)
    if reason is not None:
        if source == "QUESTIONNAIRE":
            del store.db["nested"][row["id"]]
            fail(error_id, "The prohibition ladder refuses this relationship.")
        row["state"] = "PROHIBITED"
        row["prohibition_reason"] = reason
    cascade.nested_rollup(resp)
    return ok(row, 201)


@bp.get(PREFIX + "/nested-relationships")
def list_nested():
    ctx = start(ALL)
    scope_id = list_scope(ctx)
    rows = store.by_seq(store.all_rows("nested"))
    rows = eq(rows, "respondent_bank_id", scope_id)
    rows = eq(rows, "downstream_respondent_bank_id",
              arg("downstream_respondent_bank_id"))
    rows = eq(rows, "state", arg("state"))
    rows = eq(rows, "relationship_type", arg("relationship_type"))
    rows = eq(rows, "discovery_source", arg("discovery_source"))
    page, limit, offset, total = paged(rows)
    return ok_list(page, limit, offset, total)


@bp.get(PREFIX + "/nested-relationships/<nested_id>")
def read_nested(nested_id):
    ctx = start(ALL)
    return ok(scoped_child("nested", nested_id, ctx))


@bp.get(PREFIX + "/respondents/<respondent_id>/nested-chain")
def nested_chain(respondent_id):
    start(OPS)
    resp = need_respondent(respondent_id)
    collected = []
    _expand(resp["id"], 1, {resp["id"]}, collected)
    state = arg("state")
    if state is not None:
        collected = [r for r in collected if r["state"] == state]
    collected.sort(key=lambda r: (int(r["depth"]), r["_seq"]))
    page, limit, offset, total = paged(collected)
    return ok_list(page, limit, offset, total)


def _expand(respondent_id, depth, visited, out):
    if depth > 4:
        return
    for row in store.by_seq(store.nested_of(respondent_id)):
        view = dict(row)
        view["depth"] = cascade.compute_nested_depth(row)[0]
        out.append(view)
        nxt = row.get("downstream_respondent_bank_id")
        if not nxt or row["state"] not in calc.NESTED_LIVE:
            continue
        if nxt in visited:
            continue
        _expand(nxt, depth + 1, visited | {nxt}, out)


# ------------------------------------------------------------ adjudication ----

ACTIONS = ("CONFIRM", "PROHIBIT", "SUSPEND", "REVERT", "TERMINATE")
FROM_STATES = {
    "CONFIRM": ("DISCLOSED", "UNDISCLOSED_DETECTED"),
    "PROHIBIT": ("DISCLOSED", "UNDISCLOSED_DETECTED", "CONFIRMED"),
    "SUSPEND": (),
    "REVERT": ("CONFIRMED",),
    "TERMINATE": ("DISCLOSED", "UNDISCLOSED_DETECTED", "CONFIRMED", "SUSPENDED"),
}


@bp.post(PREFIX + "/nested-relationships/<nested_id>/adjudication")
def adjudication(nested_id):
    ctx = start(("ComplianceAnalyst", "SanctionsOfficer"))
    row = need("nested", nested_id)
    data = body()
    validate(data, [
        fenum("action", ACTIONS, True),
        fenum("prohibition_reason", REASONS, False),
    ])
    resp = store.get("respondents", row["respondent_bank_id"])
    action = data["action"]
    if action in ("CONFIRM", "PROHIBIT", "SUSPEND"):
        if resp["dd_state"] in ("DECLINED", "TERMINATED", "EXITING") and action == "CONFIRM":
            fail("ERR_INVALID_RESPONDENT_STATE",
                 "This respondent state permits no confirmation.")
    if action == "REVERT" and resp["dd_state"] in ("EXITING", "TERMINATED"):
        fail("ERR_INVALID_RESPONDENT_STATE",
             "This respondent state permits no reversion.")
    cascade.guard_not_closed(resp)
    if row["state"] not in FROM_STATES[action]:
        fail("ERR_INVALID_NESTED_STATE",
             "Action %s is not declared from state %s." % (action, row["state"]))
    depth, cycle = cascade.compute_nested_depth(row)
    row["depth"] = depth
    reason, error_id = cascade.prohibition_ladder(row, resp, depth, cycle)
    if action == "CONFIRM":
        _confirm(row, resp, reason, error_id, depth)
    elif action == "PROHIBIT":
        _prohibit(row, resp, reason, error_id)
    elif action == "REVERT":
        _revert(row, resp)
    else:
        _terminate(row, resp)
    row["adjudicated_by_user_id"] = ctx.user_id
    store.set_dt(row, "adjudicated_at", clock.now())
    store.touch(row)
    cascade.nested_rollup(resp)
    return ok(row)


def _confirm(row, resp, reason, error_id, depth):
    if not resp["nested_activity_permitted"]:
        fail("ERR_INVALID_RESPONDENT_STATE",
             "This respondent does not permit nested activity.")
    if reason is not None:
        fail(error_id, "The prohibition ladder refuses this confirmation.")
    if row["state"] == "UNDISCLOSED_DETECTED":
        accepted = any(r["request_topic"] == "NESTED_DISCLOSURE"
                       and r["state"] == "ACCEPTED"
                       for r in store.rfis_of(resp["id"]))
        if not accepted:
            fail("ERR_UNDISCLOSED_NESTING_OUTSTANDING",
                 "An accepted nested-disclosure information request is required first.")
    previous_max = int(resp["max_nested_depth"])
    row["state"] = "CONFIRMED"
    row["prohibition_reason"] = None
    if depth > previous_max:
        cascade.require_recalibration(resp, "NESTED_DISCOVERY")


def _prohibit(row, resp, reason, error_id):
    if reason is None:
        fail("ERR_NESTED_JURISDICTION_PROHIBITS_NESTING",
             "The prohibition ladder yields no reason for this relationship.")
    row["state"] = "PROHIBITED"
    row["prohibition_reason"] = reason
    store.touch(row)
    if resp["dd_state"] in cascade.APPROVED_FAMILY:
        cascade.restrict(resp, "PROHIBITED_NESTING", "BLOCKED")
    if reason == "SANCTIONED_JURISDICTION":
        rows = [p for p in store.payments_of(resp["id"])
                if p.get("nested_relationship_id") == row["id"]]
        cascade.block_payments_for_sanctions(rows)
    for alert in store.by_seq(store.alerts_of(resp["id"])):
        if alert["alert_type"] == "NESTED_ACTIVITY_UNDISCLOSED" and alert["state"] == "OPEN":
            alert["state"] = "CLOSED_CONFIRMED"
            alert["disposition_reason"] = "PROHIBITED_NESTING"
            store.touch(alert)


def _revert(row, resp):
    for pay in store.payments_of(resp["id"]):
        if (pay.get("nested_relationship_id") == row["id"]
                and pay["screening_state"] in ("RELEASED", "HELD_FOR_REVIEW")):
            fail("ERR_INVALID_NESTED_STATE",
                 "A live payment instruction references this relationship.")
    row["state"] = "DISCLOSED"


def _terminate(row, resp):
    if row["state"] in ("CONFIRMED", "SUSPENDED"):
        for pay in store.payments_of(resp["id"]):
            if (pay.get("nested_relationship_id") == row["id"]
                    and pay["screening_state"] == "HELD_FOR_REVIEW"):
                fail("ERR_INVALID_NESTED_STATE",
                     "A held payment instruction references this relationship.")
    row["state"] = "TERMINATED"
