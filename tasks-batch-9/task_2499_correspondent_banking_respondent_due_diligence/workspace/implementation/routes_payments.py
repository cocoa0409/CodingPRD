"""Payment screening and the officer decision (PRD 3.9)."""

from decimal import Decimal

from flask import Blueprint

import cascade
import clock
import store
from common import (ALL, arg, eq, list_scope, need, need_respondent, paged,
                    scoped_child, start, PREFIX)
from errors import fail
from response import ok, ok_list
from validate import body, dec, fbool, fenum, fnum, fstr, q2, validate

bp = Blueprint("payments", __name__)

PURPOSES = ("TRADE_SETTLEMENT", "REMITTANCE", "INTERBANK_PLACEMENT",
            "RETURN_OF_FUNDS", "SETTLEMENT")
REASONS = ("CLEARED_AFTER_REVIEW", "WIND_DOWN_PERMITTED", "SANCTIONS_MATCH",
           "UNRESOLVED_NESTED_RISK", "RESPONDENT_RESTRICTED")
REJECT_REASONS = ("SANCTIONS_MATCH", "UNRESOLVED_NESTED_RISK",
                  "RESPONDENT_RESTRICTED")
WIND_DOWN_PURPOSES = ("RETURN_OF_FUNDS", "SETTLEMENT")
DISCLOSED_STATES = ("DISCLOSED", "CONFIRMED")

SUBMIT_SPEC = [
    fstr("ordering_jurisdiction_code", True, 1, None),
    fstr("beneficiary_jurisdiction_code", True, 1, None),
    fnum("amount_usd", True, None, None, "0"),
    fenum("purpose_code", PURPOSES, True),
    fbool("involves_nested_party", False),
    fstr("nested_relationship_id", False, 1, None),
]


@bp.post(PREFIX + "/respondents/<respondent_id>/payment-instructions")
def submit(respondent_id):
    start(("FIGRelationshipManager", "RespondentContact", "PlatformAdmin"),
          respondent_id)
    resp = need_respondent(respondent_id)
    data = body()
    validate(data, SUBMIT_SPEC)
    if resp["payment_posture"] == "BLOCKED":
        fail("ERR_RESPONDENT_PAYMENT_POSTURE_BLOCKED",
             "This respondent's payment posture is blocked.")
    cascade.guard_not_closed(resp, allow_exiting=True)
    for field in ("ordering_jurisdiction_code", "beneficiary_jurisdiction_code"):
        if store.jurisdiction_by_code(data[field]) is None:
            fail("ERR_JURISDICTION_PROFILE_NOT_FOUND",
                 "%s %s does not resolve." % (field, data[field]))
    nested_id = data.get("nested_relationship_id")
    nested = None
    if nested_id is not None:
        nested = store.get("nested", nested_id)
        if nested is None:
            fail("ERR_NESTED_RELATIONSHIP_NOT_FOUND",
                 "nested_relationship_id does not resolve.")
    involves = bool(data.get("involves_nested_party"))
    if involves:
        if nested is None or nested["respondent_bank_id"] != resp["id"] \
                or nested["state"] not in DISCLOSED_STATES:
            fail("ERR_NESTED_DISCLOSURE_MISSING",
                 "A disclosed or confirmed nested relationship of this respondent is "
                 "required.")
    row = store.insert("payments", {
        "respondent_bank_id": resp["id"],
        "nested_relationship_id": nested_id,
        "ordering_jurisdiction_code": data["ordering_jurisdiction_code"],
        "beneficiary_jurisdiction_code": data["beneficiary_jurisdiction_code"],
        "amount_usd": q2(data["amount_usd"]),
        "purpose_code": data["purpose_code"],
        "involves_nested_party": involves,
        "screening_state": "RECEIVED",
        "hold_reason": None,
        "hold_threshold_applied": q2("0.00"),
        "decided_by_user_id": None,
        "decided_at": None,
        "decision_reason": None,
    })
    _screen(row, resp)
    return ok(row, 201)


def _screen(row, resp):
    """The first-match screening ladder of PRD 3.9."""
    row["hold_reason"] = None
    row["hold_threshold_applied"] = q2("0.00")
    ordering = store.jurisdiction_by_code(row["ordering_jurisdiction_code"])
    beneficiary = store.jurisdiction_by_code(row["beneficiary_jurisdiction_code"])
    statuses = [jp["sanctions_status"] for jp in (ordering, beneficiary)
                if jp is not None]
    if "COMPREHENSIVELY_SANCTIONED" in statuses:
        row["screening_state"] = "BLOCKED_SANCTIONS"
        return row
    profile = cascade.covering_profile(resp, clock.now())
    if profile is None:
        row["screening_state"] = "RECEIVED"
        return row
    if "RESTRICTED" in statuses:
        row["screening_state"] = "HELD_FOR_REVIEW"
        row["hold_reason"] = "SANCTIONS_RESTRICTED_JURISDICTION"
        return row
    if resp["payment_posture"] in ("SCREEN_ONLY", "WIND_DOWN_ONLY"):
        row["screening_state"] = "HELD_FOR_REVIEW"
        row["hold_reason"] = "POSTURE_SCREEN_ONLY"
        return row
    nested = store.get("nested", row["nested_relationship_id"]) \
        if row["nested_relationship_id"] else None
    if row["involves_nested_party"] and (nested is None
                                        or nested["state"] not in DISCLOSED_STATES):
        row["screening_state"] = "HELD_FOR_REVIEW"
        row["hold_reason"] = "UNDISCLOSED_NESTED_PARTY"
        return row
    hold = dec(profile["hold_threshold_usd"] or 0)
    if dec(row["amount_usd"]) >= hold:
        row["screening_state"] = "HELD_FOR_REVIEW"
        row["hold_reason"] = "AMOUNT_THRESHOLD"
        row["hold_threshold_applied"] = q2(hold)
        return row
    row["screening_state"] = "SCREENED_CLEAR"
    row["hold_threshold_applied"] = q2(hold)
    return row


@bp.get(PREFIX + "/payment-instructions")
def list_payments():
    ctx = start(ALL)
    scope_id = list_scope(ctx)
    rows = store.by_seq(store.all_rows("payments"))
    rows = eq(rows, "respondent_bank_id", scope_id)
    rows = eq(rows, "nested_relationship_id", arg("nested_relationship_id"))
    rows = eq(rows, "screening_state", arg("screening_state"))
    rows = eq(rows, "hold_reason", arg("hold_reason"))
    rows = eq(rows, "purpose_code", arg("purpose_code"))
    page, limit, offset, total = paged(rows)
    return ok_list(page, limit, offset, total)


@bp.get(PREFIX + "/payment-instructions/<payment_id>")
def read_payment(payment_id):
    ctx = start(ALL)
    return ok(scoped_child("payments", payment_id, ctx))


FROM_STATES = {
    "RELEASE": ("SCREENED_CLEAR", "HELD_FOR_REVIEW", "BLOCKED_SANCTIONS"),
    "HOLD": ("RECEIVED",),
    "RESCREEN": ("RECEIVED", "HELD_FOR_REVIEW"),
    "REJECT": ("RECEIVED", "SCREENED_CLEAR", "HELD_FOR_REVIEW", "BLOCKED_SANCTIONS"),
}


@bp.post(PREFIX + "/payment-instructions/<payment_id>/screening-decision")
def screening_decision(payment_id):
    ctx = start(("SanctionsOfficer",))
    row = need("payments", payment_id)
    data = body()
    validate(data, [
        fenum("action", ("RELEASE", "HOLD", "RESCREEN", "REJECT"), True),
        fenum("decision_reason", REASONS, True),
    ])
    resp = store.get("respondents", row["respondent_bank_id"])
    action = data["action"]
    reason = data["decision_reason"]
    if row["screening_state"] not in FROM_STATES[action]:
        fail("ERR_INVALID_PAYMENT_STATE",
             "Action %s is not declared from state %s."
             % (action, row["screening_state"]))
    if action == "RELEASE" and resp["payment_posture"] == "BLOCKED":
        fail("ERR_RESPONDENT_PAYMENT_POSTURE_BLOCKED",
             "A blocked respondent's payments cannot be released.")
    cascade.guard_not_closed(resp, allow_exiting=True)
    if action == "RELEASE" and row["screening_state"] == "BLOCKED_SANCTIONS":
        fail("ERR_SANCTIONED_PAYMENT_RELEASE_FORBIDDEN",
             "A sanctions-blocked instruction can only be rejected.")
    if action == "RELEASE":
        _release(row, resp)
    elif action == "HOLD":
        row["screening_state"] = "HELD_FOR_REVIEW"
    elif action == "RESCREEN":
        _screen(row, resp)
    else:
        if row["screening_state"] == "BLOCKED_SANCTIONS":
            if reason != "SANCTIONS_MATCH":
                fail("ERR_INVALID_REQUEST_BODY",
                     "A sanctions-blocked rejection requires SANCTIONS_MATCH.")
        elif reason not in REJECT_REASONS:
            fail("ERR_INVALID_REQUEST_BODY",
                 "This rejection requires a sanctions, nested-risk or restriction "
                 "reason.")
        row["screening_state"] = "REJECTED"
        row["hold_reason"] = None
    row["decided_by_user_id"] = ctx.user_id
    row["decision_reason"] = reason
    store.set_dt(row, "decided_at", clock.now())
    store.touch(row)
    return ok(row)


def _release(row, resp):
    if row["screening_state"] == "HELD_FOR_REVIEW" \
            and row["hold_reason"] == "UNDISCLOSED_NESTED_PARTY":
        nested = store.get("nested", row["nested_relationship_id"]) \
            if row["nested_relationship_id"] else None
        if nested is None or nested["state"] != "CONFIRMED":
            fail("ERR_NESTED_DISCLOSURE_MISSING",
                 "The referenced nested relationship has not reached CONFIRMED.")
    plan = cascade.live_plan(resp)
    if resp["payment_posture"] == "WIND_DOWN_ONLY":
        if row["purpose_code"] not in WIND_DOWN_PURPOSES:
            fail("ERR_INVALID_PAYMENT_STATE",
                 "Only a return of funds or a settlement may be released during "
                 "wind-down.")
        if plan is not None:
            end_at = store.dt(plan, "wind_down_end_at")
            if end_at is not None and clock.now() > end_at:
                fail("ERR_INVALID_PAYMENT_STATE",
                     "The wind-down window has closed.")
            released = dec(plan["wind_down_released_usd"])
            cap = dec(plan["wind_down_cap_usd"])
            if q2(released + dec(row["amount_usd"])) > cap:
                fail("ERR_WIND_DOWN_CAP_EXCEEDED",
                     "This release would exceed the wind-down cap.")
    row["screening_state"] = "RELEASED"
    row["hold_reason"] = None
    if plan is not None:
        plan["wind_down_released_usd"] = q2(dec(plan["wind_down_released_usd"])
                                            + dec(row["amount_usd"]))
        store.touch(plan)
