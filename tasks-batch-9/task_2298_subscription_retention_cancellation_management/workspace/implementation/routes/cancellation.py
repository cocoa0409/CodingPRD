"""The cancellation conversation and save offers (PRD §3.5, §3.6)."""
from flask import Blueprint, g

import constants as K
import serializers as S
import validation as V
from db import base_record, days, hours, store, touch
from errors import fail
from middleware import auth, own
from response import created, ok
from routes import send_list
from services import calc, ops

bp = Blueprint("cancellation", __name__)

PRE_COMPLETION_BUDGET = K.MAX_CANCELLATION_STEPS - 1


@bp.post("/cancellation-sessions")
@auth("Subscriber", "RetentionSpecialist")
def create_session():
    data = V.body()
    sub = V.fk(data, "subscription_id", "subscriptions")
    V.req_str(data, "subscription_id")
    entry_channel = V.req_enum(data, "entry_channel", K.ENTRY_CHANNELS)
    own(sub["subscriber_id"])

    if sub["lifecycle_state"] not in ("ACTIVE", "PAUSED"):
        fail("ERR_SUBSCRIPTION_NOT_MODIFIABLE", "The subscription can no longer be modified.")
    for other in calc.sessions_of_subscription(sub["id"]):
        if other["state"] in ("STARTED", "REASON_CAPTURED", "OFFERS_PRESENTED"):
            fail("ERR_SESSION_ALREADY_OPEN",
                 "Another cancellation session is already open on this subscription.")

    rec = base_record()
    rec.update({
        "subscription_id": sub["id"],
        "state": "STARTED",
        "reason_code": None,
        "reason_detail": None,
        "step_count": 1,
        "offers_presented_count": 0,
        "entry_channel": entry_channel,
        "started_at": store.now(),
        "completed_at": None,
        "presented_by_user_id": None,
    })
    store.cancellation_sessions[rec["id"]] = rec
    return created(S.session(rec))


@bp.get("/cancellation-sessions/<session_id>")
@auth()
def read_session(session_id):
    return ok(S.session(V.must_exist("cancellation_sessions", session_id)))


@bp.get("/cancellation-sessions")
@auth()
def list_sessions():
    return send_list(store.cancellation_sessions.values(), S.session,
                     {"subscription_id": "subscription_id", "state": "state"})


@bp.post("/cancellation-sessions/<session_id>/reason")
@auth("Subscriber", "RetentionSpecialist")
def capture_reason(session_id):
    session = V.must_exist("cancellation_sessions", session_id)
    data = V.body()
    reason_code = V.req_enum(data, "reason_code", K.REASON_CODES)
    reason_detail = V.opt_str(data, "reason_detail")
    sub = store.subscriptions[session["subscription_id"]]
    own(sub["subscriber_id"])

    if session["state"] in K.SESSION_TERMINAL:
        fail("ERR_SESSION_ALREADY_TERMINAL", "The cancellation session is already closed.")
    if session["step_count"] + 1 > PRE_COMPLETION_BUDGET:
        fail("ERR_SIMPLE_CANCELLATION_VIOLATION",
             "The simple-cancellation step budget is exhausted.")

    session["reason_code"] = reason_code
    session["reason_detail"] = reason_detail
    session["state"] = "REASON_CAPTURED"
    session["step_count"] += 1
    touch(session)
    return ok(S.session(session))


@bp.post("/cancellation-sessions/<session_id>/present-offers")
@auth("RetentionSpecialist")
def present_offers(session_id):
    session = V.must_exist("cancellation_sessions", session_id)
    sub = store.subscriptions[session["subscription_id"]]
    subscriber = store.subscribers[sub["subscriber_id"]]

    if session["state"] in K.SESSION_TERMINAL:
        fail("ERR_SESSION_ALREADY_TERMINAL", "The cancellation session is already closed.")
    if session["reason_code"] is None:
        fail("ERR_REASON_NOT_CAPTURED", "The cancellation reason has not been captured.")
    if session["step_count"] + 1 > PRE_COMPLETION_BUDGET or session["offers_presented_count"] != 0:
        fail("ERR_SIMPLE_CANCELLATION_VIOLATION",
             "Only one offer round is permitted inside the step budget.")

    template, margins = ops.select_offer(session, sub, subscriber)
    plan = ops.plan_of(sub)
    required = margins["blended_term_margin_pct"] < plan["margin_floor_pct"]

    grant = base_record()
    grant.update({
        "cancellation_session_id": session["id"],
        "save_offer_template_id": template["id"],
        "subscription_id": sub["id"],
        "state": "PRESENTED",
        "per_cycle_margin_pct": margins["per_cycle_margin_pct"],
        "blended_term_margin_pct": margins["blended_term_margin_pct"],
        "margin_exception_required": required,
        "margin_exception_state": "PENDING" if required else "NOT_REQUIRED",
        "presented_by_user_id": g.user_id,
        "decided_by_user_id": None,
        "expires_at": store.now() + hours(template["expires_after_hours"]),
        "accepted_at": None,
        "retention_value_cents": margins["retention_value_cents"],
    })
    store.save_offer_grants[grant["id"]] = grant

    session["state"] = "OFFERS_PRESENTED"
    session["presented_by_user_id"] = g.user_id
    session["offers_presented_count"] = 1
    session["step_count"] += 1
    touch(session)
    return created(S.grant(grant))


@bp.post("/cancellation-sessions/<session_id>/complete")
@auth("Subscriber", "RetentionSpecialist")
def complete_session(session_id):
    session = V.must_exist("cancellation_sessions", session_id)
    data = V.body()
    V.req_bool(data, "confirm")
    sub = store.subscriptions[session["subscription_id"]]
    own(sub["subscriber_id"])

    if session["state"] in K.SESSION_TERMINAL:
        fail("ERR_SESSION_ALREADY_TERMINAL", "The cancellation session is already closed.")
    if session["reason_code"] is None:
        fail("ERR_REASON_NOT_CAPTURED", "The cancellation reason has not been captured.")

    now = store.now()
    session["state"] = "COMPLETED_CANCELLED"
    session["completed_at"] = now
    session["step_count"] += 1
    touch(session)

    sub["lifecycle_state"] = "PENDING_CANCEL"
    sub["cancel_effective_at"] = sub["next_renewal_at"]
    touch(sub)

    ops.expire_presented_grants(session)
    ops.create_notice(sub, "CANCELLATION_CONFIRMATION", "SENT", None,
                      ops.upcoming_cycle_index(sub), sent_at=now)
    return ok(S.session(session))


# --------------------------------------------------------------------------
# Save-offer grants
# --------------------------------------------------------------------------
@bp.get("/save-offer-grants/<grant_id>")
@auth()
def read_grant(grant_id):
    return ok(S.grant(V.must_exist("save_offer_grants", grant_id)))


@bp.get("/save-offer-grants")
@auth()
def list_grants():
    return send_list(store.save_offer_grants.values(), S.grant,
                     {"cancellation_session_id": "cancellation_session_id",
                      "save_offer_template_id": "save_offer_template_id",
                      "subscription_id": "subscription_id", "state": "state"})


@bp.post("/save-offer-grants/<grant_id>/accept")
@auth("Subscriber")
def accept_grant(grant_id):
    grant = V.must_exist("save_offer_grants", grant_id)
    sub = store.subscriptions[grant["subscription_id"]]
    own(sub["subscriber_id"])

    if grant["state"] != "PRESENTED":
        fail("ERR_OFFER_ALREADY_RESOLVED", "The offer has already been resolved.")
    now = store.now()
    if now >= grant["expires_at"]:
        fail("ERR_OFFER_EXPIRED", "The offer has expired.")
    template = store.save_offer_templates[grant["save_offer_template_id"]]
    if template["offer_type"] in ("DISCOUNT", "PLAN_DOWNGRADE") \
            and sub["billing_state"] != "CURRENT":
        fail("ERR_SUBSCRIPTION_PAST_DUE",
             "The subscription is not current on its billing axis.")
    if grant["margin_exception_required"] and grant["margin_exception_state"] != "APPROVED":
        fail("ERR_MARGIN_FLOOR_BREACH",
             "The offer breaches the plan's margin floor without an approved exception.")

    grant["state"] = "ACCEPTED"
    grant["accepted_at"] = now
    touch(grant)

    ops.accept_offer_modification(grant, template, sub)

    subscriber = store.subscribers[sub["subscriber_id"]]
    subscriber["winback_suppressed_until"] = now + days(K.VOLUNTARY_SAVE_SUPPRESSION_DAYS)
    subscriber["_suppression_grant_id"] = grant["id"]
    touch(subscriber)

    session = store.cancellation_sessions[grant["cancellation_session_id"]]
    session["state"] = "OFFER_ACCEPTED"
    session["completed_at"] = now
    session["step_count"] += 1
    touch(session)

    touch(sub)
    return ok(S.grant(grant))


@bp.post("/save-offer-grants/<grant_id>/decline")
@auth("Subscriber")
def decline_grant(grant_id):
    grant = V.must_exist("save_offer_grants", grant_id)
    data = V.body()
    V.opt_str(data, "decline_note")
    sub = store.subscriptions[grant["subscription_id"]]
    own(sub["subscriber_id"])

    if grant["state"] != "PRESENTED":
        fail("ERR_OFFER_ALREADY_RESOLVED", "The offer has already been resolved.")
    grant["state"] = "DECLINED"
    touch(grant)
    return ok(S.grant(grant))


@bp.post("/save-offer-grants/<grant_id>/margin-exception")
@auth("ComplianceOfficer")
def decide_exception(grant_id):
    grant = V.must_exist("save_offer_grants", grant_id)
    data = V.body()
    decision = V.req_enum(data, "decision", K.DECISIONS)
    V.opt_str(data, "justification")

    if g.user_id == grant["presented_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The deciding officer may not be the presenting specialist.")
    if grant["margin_exception_state"] != "PENDING":
        fail("ERR_MARGIN_EXCEPTION_NOT_REQUIRED",
             "No margin-floor exception is pending on this grant.")

    grant["margin_exception_state"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    grant["decided_by_user_id"] = g.user_id
    touch(grant)
    return ok(S.grant(grant))
