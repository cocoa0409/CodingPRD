"""Win-back campaigns, targeting, sending and re-evaluation (PRD §3.8)."""
from decimal import Decimal

from flask import Blueprint

import constants as K
import serializers as S
import validation as V
from db import base_record, days, store, touch
from errors import fail
from middleware import auth
from response import created, ok
from routes import send_list
from services import calc, ops

bp = Blueprint("winback", __name__)


@bp.post("/winback-campaigns")
@auth("RetentionSpecialist")
def create_campaign():
    data = V.body()
    code = V.req_str(data, "code")
    if any(c["code"] == code for c in store.winback_campaigns.values()):
        V.bad("code", "must be unique across campaigns")
    name = V.req_str(data, "name")
    min_days = V.req_int(data, "min_days_since_lapse", minimum=0)
    max_days = V.req_int(data, "max_days_since_lapse", minimum=0)
    if max_days < min_days:
        V.bad("max_days_since_lapse", "must be at least min_days_since_lapse")
    discount = V.req_frac(data, "offer_discount_pct", minimum=Decimal("0"),
                          exclusive_max=Decimal("1"))
    channels = V.opt_array(data, "target_channels", [])
    for channel in channels:
        if channel not in K.ACQUISITION_CHANNELS:
            V.bad("target_channels", "must contain declared acquisition channels")
    reasons = V.opt_array(data, "target_reason_codes", [])
    for reason in reasons:
        if reason not in K.REASON_CODES:
            V.bad("target_reason_codes", "must contain declared reason codes")
    send_window = V.opt_int(data, "send_window_days", 14, minimum=0)
    suppression = V.opt_int(data, "suppression_days", 60, minimum=0)

    rec = base_record()
    rec.update({
        "code": code,
        "name": name,
        "target_channels": list(channels),
        "target_reason_codes": list(reasons),
        "min_days_since_lapse": min_days,
        "max_days_since_lapse": max_days,
        "offer_discount_pct": discount,
        "send_window_days": send_window,
        "suppression_days": suppression,
        "state": "DRAFT",
    })
    store.winback_campaigns[rec["id"]] = rec
    return created(S.campaign(rec))


@bp.post("/winback-campaigns/<campaign_id>/launch")
@auth("RetentionSpecialist")
def launch_campaign(campaign_id):
    campaign = V.must_exist("winback_campaigns", campaign_id)
    if campaign["state"] != "DRAFT":
        fail("ERR_CAMPAIGN_NOT_LAUNCHED", "Only a draft campaign may be launched.")
    campaign["state"] = "LAUNCHED"
    touch(campaign)
    return ok(S.campaign(campaign))


@bp.get("/winback-campaigns/<campaign_id>")
@auth("PlatformAdmin", "RetentionSpecialist", "ComplianceOfficer")
def read_campaign(campaign_id):
    return ok(S.campaign(V.must_exist("winback_campaigns", campaign_id)))


@bp.post("/winback-campaigns/<campaign_id>/targets")
@auth("RetentionSpecialist")
def add_target(campaign_id):
    campaign = V.must_exist("winback_campaigns", campaign_id)
    data = V.body()
    subscriber = V.fk(data, "subscriber_id", "subscribers")
    V.req_str(data, "subscriber_id")
    expected = V.req_int(data, "expected_campaign_version")

    if expected != campaign["version"]:
        fail("ERR_STALE_CAMPAIGN_VERSION",
             "expected_campaign_version does not match the campaign's version.")
    if campaign["state"] != "LAUNCHED":
        fail("ERR_CAMPAIGN_NOT_LAUNCHED", "The campaign is not launched.")

    now = store.now()
    lapsed_at = subscriber.get("lapsed_at")
    if lapsed_at is None:
        fail("ERR_SUBSCRIBER_NOT_LAPSED", "The subscriber has not lapsed.")
    since = calc.floor_days(now - lapsed_at)
    if since < campaign["min_days_since_lapse"] or since > campaign["max_days_since_lapse"]:
        fail("ERR_SUBSCRIBER_NOT_LAPSED",
             "The subscriber's days since lapse fall outside the campaign window.")
    suppressed_until = subscriber.get("winback_suppressed_until")
    if suppressed_until is not None and suppressed_until > now:
        fail("ERR_WINBACK_SUPPRESSION_ACTIVE",
             "The subscriber is inside a win-back suppression window.")
    for other in calc.targets_of_campaign(campaign["id"]):
        if other["subscriber_id"] == subscriber["id"]:
            fail("ERR_DUPLICATE_TARGET",
                 "The subscriber is already targeted by this campaign.")

    reason = ops.suppression_reason(subscriber)
    rec = base_record()
    rec.update({
        "winback_campaign_id": campaign["id"],
        "subscriber_id": subscriber["id"],
        "state": "ELIGIBLE" if reason == "NONE" else "SUPPRESSED",
        "suppression_reason": reason,
        "priority_score": calc.winback_priority_score(subscriber, campaign, since),
        "projected_ltv_cents": calc.projected_ltv(subscriber),
        "sent_at": None,
        "expires_at": None,
        "converted_at": None,
        "days_since_lapse_at_target": since,
    })
    store.winback_targets[rec["id"]] = rec
    touch(campaign)
    return created(S.target(rec))


@bp.post("/winback-targets/<target_id>/send")
@auth("RetentionSpecialist")
def send_target(target_id):
    target = V.must_exist("winback_targets", target_id)
    campaign = store.winback_campaigns[target["winback_campaign_id"]]

    if campaign["state"] != "LAUNCHED":
        fail("ERR_CAMPAIGN_NOT_LAUNCHED", "The campaign is not launched.")
    if target["state"] != "ELIGIBLE":
        fail("ERR_TARGET_SUPPRESSED", "The target is not eligible for a send.")
    if ops.contacts_in_window(target["subscriber_id"]) >= K.CONTACT_CAP:
        fail("ERR_CONTACT_CAP_EXCEEDED",
             "The subscriber has already been contacted inside the 30-day window.")

    now = store.now()
    target["state"] = "SENT"
    target["sent_at"] = now
    target["expires_at"] = now + days(campaign["send_window_days"])
    touch(target)
    return ok(S.target(target))


@bp.post("/winback-targets/<target_id>/reevaluate")
@auth("RetentionSpecialist")
def reevaluate_target(target_id):
    target = V.must_exist("winback_targets", target_id)
    campaign = store.winback_campaigns[target["winback_campaign_id"]]
    subscriber = store.subscribers[target["subscriber_id"]]
    now = store.now()
    reason = ops.suppression_reason(subscriber)

    state = target["state"]
    if state == "SENT":
        if target["expires_at"] is not None and now >= target["expires_at"]:
            target["state"] = "EXPIRED"
            touch(target)
    elif state == "EXPIRED":
        if target["sent_at"] is not None \
                and now >= target["sent_at"] + days(campaign["suppression_days"]) \
                and reason == "NONE":
            target["state"] = "ELIGIBLE"
            target["expires_at"] = None
            target["suppression_reason"] = "NONE"
            touch(target)
    elif state == "SUPPRESSED":
        if reason == "NONE":
            target["state"] = "ELIGIBLE"
            target["suppression_reason"] = "NONE"
            touch(target)
    elif state == "ELIGIBLE":
        if reason != "NONE":
            target["state"] = "SUPPRESSED"
            target["suppression_reason"] = reason
            touch(target)

    ops.maybe_close_campaign(campaign)
    return ok(S.target(target))


@bp.get("/winback-targets/<target_id>")
@auth("PlatformAdmin", "RetentionSpecialist", "ComplianceOfficer", "Subscriber")
def read_target(target_id):
    return ok(S.target(V.must_exist("winback_targets", target_id)))


@bp.get("/winback-targets")
@auth("PlatformAdmin", "RetentionSpecialist", "ComplianceOfficer", "Subscriber")
def list_targets():
    return send_list(store.winback_targets.values(), S.target,
                     {"winback_campaign_id": "winback_campaign_id",
                      "subscriber_id": "subscriber_id", "state": "state"})
