"""Subscriptions, modifications, the renewal run and compliance notices."""
from decimal import Decimal

from flask import Blueprint, g

import constants as K
import serializers as S
import validation as V
from db import base_record, days, store, touch
from errors import fail
from middleware import auth, own
from response import created, ok
from routes import send_list
from services import calc, ops

bp = Blueprint("subscriptions", __name__)


# --------------------------------------------------------------------------
# Signup (PRD §3.2)
# --------------------------------------------------------------------------
@bp.post("/subscriptions")
@auth("Subscriber", "PlatformAdmin")
def create_subscription():
    data = V.body()
    subscriber = V.fk(data, "subscriber_id", "subscribers")
    plan = V.fk(data, "plan_id", "plans")
    method = V.fk(data, "payment_method_id", "payment_methods")
    target = V.fk(data, "winback_target_id", "winback_targets")

    V.req_str(data, "subscriber_id")
    V.req_str(data, "plan_id")
    V.req_str(data, "payment_method_id")
    frequency = V.req_int(data, "frequency_weeks", minimum=1)
    acknowledged = V.req_bool(data, "disclosure_acknowledged")
    addons_raw = V.opt_array(data, "addons", [])
    requested = []
    for entry in addons_raw:
        if not isinstance(entry, dict):
            V.bad("addons", "entries must be objects")
        requested.append((V.req_str(entry, "code"), V.opt_int(entry, "qty", 1, minimum=1)))

    own(subscriber["id"])

    if plan["status"] != "ACTIVE":
        fail("ERR_PLAN_RETIRED", "The plan is retired and takes no new subscriptions.")
    if plan["is_negative_option"] and not acknowledged:
        fail("ERR_DISCLOSURE_NOT_ACKNOWLEDGED",
             "The negative-option disclosure must be acknowledged.")
    if frequency not in plan["allowed_frequency_weeks"]:
        fail("ERR_FREQUENCY_NOT_ALLOWED", "The cadence is not allowed on this plan.")
    addons = []
    for code, qty in requested:
        entry = ops.catalog_entry(plan, code)
        if entry is None:
            fail("ERR_ADDON_NOT_AVAILABLE", "Addon %s is not in the plan catalogue." % code)
        addons.append({
            "code": entry["code"],
            "qty": qty,
            "unit_price_cents": entry["unit_price_cents"],
            "unit_cogs_cents": entry["unit_cogs_cents"],
        })
    if method["status"] != "ACTIVE":
        fail("ERR_PAYMENT_METHOD_INACTIVE", "The payment method is not chargeable.")

    now = store.now()
    sub = base_record()
    cycle = days(frequency * 7)
    sub.update({
        "subscriber_id": subscriber["id"],
        "plan_id": plan["id"],
        "payment_method_id": method["id"],
        "lifecycle_state": "ACTIVE",
        "billing_state": "CURRENT",
        "frequency_weeks": frequency,
        "addons": addons,
        "active_discount_pct": Decimal("0.0000"),
        "discount_remaining_cycles": 0,
        "baseline_price_cents": 0,
        "committed_price_cents": 0,
        "next_renewal_at": now + cycle,
        "next_ship_at": now + cycle,
        "paused_until": None,
        "pause_cycles_used": 0,
        "term_shipments_delivered": 1,
        "term_shipments_skipped": 0,
        "cancel_effective_at": None,
        "first_failed_at": None,
        "grace_end_at": None,
        "consecutive_failed_attempts": 0,
        "disclosure_acknowledged": acknowledged,
    })
    store.subscriptions[sub["id"]] = sub
    ops.recompute_committed(sub)
    sub["baseline_price_cents"] = sub["committed_price_cents"]

    if subscriber["first_subscribed_at"] is None:
        subscriber["first_subscribed_at"] = now
        subscriber["cohort_month"] = "%04d-%02d" % (now.year, now.month)
        touch(subscriber)

    if plan["is_negative_option"]:
        ops.create_notice(sub, "NEGATIVE_OPTION_DISCLOSURE", "SENT", None, 0, sent_at=now)
        ops.create_notice(sub, "RENEWAL_REMINDER", "SCHEDULED",
                          sub["next_renewal_at"] - days(plan["renewal_reminder_days_before"]), 1)

    ops.issue_invoice(sub, 0, False)

    if target is not None and target["state"] == "SENT" \
            and target["subscriber_id"] == subscriber["id"]:
        target["state"] = "CONVERTED"
        target["converted_at"] = now
        touch(target)
        subscriber["churn_type"] = "NONE"
        subscriber["lapsed_at"] = None
        subscriber["won_back_at"] = now
        touch(subscriber)
        campaign = store.winback_campaigns.get(target["winback_campaign_id"])
        if campaign is not None:
            touch(campaign)
    return created(S.subscription(sub))


@bp.get("/subscriptions/<subscription_id>")
@auth()
def read_subscription(subscription_id):
    return ok(S.subscription(V.must_exist("subscriptions", subscription_id)))


@bp.get("/subscriptions")
@auth()
def list_subscriptions():
    return send_list(store.subscriptions.values(), S.subscription,
                     {"subscriber_id": "subscriber_id", "plan_id": "plan_id",
                      "payment_method_id": "payment_method_id",
                      "lifecycle_state": "lifecycle_state", "billing_state": "billing_state"})


# --------------------------------------------------------------------------
# Modifications (PRD §3.3)
# --------------------------------------------------------------------------
@bp.post("/subscriptions/<subscription_id>/modifications")
@auth("Subscriber", "RetentionSpecialist")
def create_modification(subscription_id):
    sub = V.must_exist("subscriptions", subscription_id)
    data = V.body()
    target_plan = V.fk(data, "target_plan_id", "plans")

    mod_type = V.req_enum(data, "mod_type", K.MOD_TYPES)
    expected = V.req_int(data, "expected_subscription_version")
    frequency = V.opt_int(data, "frequency_weeks", None, minimum=1)
    addon_code = V.opt_str(data, "addon_code")
    addon_qty = V.opt_int(data, "addon_qty", None, minimum=1)
    skip_ship_at = V.opt_dt(data, "skip_ship_at")
    pause_start_at = V.opt_dt(data, "pause_start_at")
    pause_end_at = V.opt_dt(data, "pause_end_at")
    effective_at = V.opt_dt(data, "effective_at")
    discount_pct = V.opt_frac(data, "discount_pct", None, minimum=Decimal("0"),
                              exclusive_max=Decimal("1"))
    discount_cycles = V.opt_int(data, "discount_cycles", None, minimum=0)

    own(sub["subscriber_id"])

    if expected != sub["version"]:
        fail("ERR_STALE_SUBSCRIPTION_VERSION",
             "expected_subscription_version does not match the subscription's version.")

    now = store.now()
    if effective_at is None:
        effective_at = now
    cdays = ops.cycle_days(sub)
    if mod_type == "PAUSE":
        if pause_start_at is None:
            pause_start_at = now
        if pause_end_at is None:
            pause_end_at = pause_start_at + days(cdays)
    if mod_type == "SKIP_SHIPMENT" and skip_ship_at is None:
        skip_ship_at = sub["next_ship_at"]

    # -- domain guards, in the pinned order
    if sub["lifecycle_state"] not in ("ACTIVE", "PAUSED"):
        fail("ERR_SUBSCRIPTION_NOT_MODIFIABLE",
             "The subscription can no longer be modified.")

    if mod_type == "PAUSE":
        for other in calc.mods_of_subscription(sub["id"]):
            if other["mod_type"] != "PAUSE" or other["state"] not in ("APPLIED", "SCHEDULED"):
                continue
            if other["pause_start_at"] is None or other["pause_end_at"] is None:
                continue
            if pause_start_at < other["pause_end_at"] and other["pause_start_at"] < pause_end_at:
                fail("ERR_PAUSE_WINDOW_OVERLAP",
                     "The requested pause window overlaps an existing pause.")

    plan = ops.plan_of(sub)
    if mod_type == "FREQUENCY_CHANGE":
        if frequency is None or frequency not in plan["allowed_frequency_weeks"]:
            fail("ERR_FREQUENCY_NOT_ALLOWED", "The cadence is not allowed on this plan.")
    if mod_type in ("ADDON_ADD", "ADDON_REMOVE"):
        if addon_code is None or ops.catalog_entry(plan, addon_code) is None:
            fail("ERR_ADDON_NOT_AVAILABLE", "The addon is not in the plan catalogue.")
    if mod_type == "PAUSE":
        span = ops.pause_span_cycles(pause_start_at, pause_end_at, cdays)
        if span > plan["max_pause_cycles"]:
            fail("ERR_PAUSE_EXCEEDS_MAX_CYCLES",
                 "The pause spans more cycles than the plan allows.")
    if mod_type == "SKIP_SHIPMENT":
        remaining = (plan["shipments_per_term"] - sub["term_shipments_delivered"]
                     - sub["term_shipments_skipped"])
        if remaining <= 0:
            fail("ERR_SKIP_BUDGET_EXHAUSTED", "The term's shipment allotment is exhausted.")
    if mod_type == "PLAN_DOWNGRADE":
        if not plan.get("downgrade_target_plan_id") or target_plan is None \
                or target_plan["id"] != plan["downgrade_target_plan_id"]:
            fail("ERR_DOWNGRADE_TARGET_MISSING",
                 "target_plan_id must equal the plan's downgrade target.")

    mod = ops.new_modification(
        sub, mod_type, effective_at,
        frequency_weeks=frequency,
        addon_code=addon_code,
        addon_qty=addon_qty,
        skip_ship_at=skip_ship_at,
        pause_start_at=pause_start_at,
        pause_end_at=pause_end_at,
        target_plan_id=target_plan["id"] if target_plan else None,
    )
    if mod_type == "DISCOUNT_APPLY":
        mod["_discount_pct"] = discount_pct
        mod["_discount_cycles"] = discount_cycles

    if effective_at > now:
        mod["state"] = "SCHEDULED"
        mod["delta_price_cents"] = 0
    else:
        ops.apply_modification(mod, sub)
    touch(sub)
    return created(S.modification(mod))


@bp.post("/subscriptions/<subscription_id>/renewals")
@auth("BillingOperator")
def run_renewal(subscription_id):
    sub = V.must_exist("subscriptions", subscription_id)
    ops.renewal_run(sub)
    return ok(S.subscription(sub))


# --------------------------------------------------------------------------
# Compliance notices (PRD §2.11, §3.4)
# --------------------------------------------------------------------------
@bp.get("/subscriptions/<subscription_id>/compliance-notices")
@auth()
def list_notices(subscription_id):
    V.must_exist("subscriptions", subscription_id)
    rows = [n for n in store.compliance_notices.values()
            if n["subscription_id"] == subscription_id]
    return send_list(rows, S.notice, {"notice_type": "notice_type", "state": "state"})


@bp.post("/subscriptions/<subscription_id>/compliance-notices")
@auth("BillingOperator", "ComplianceOfficer")
def schedule_notice(subscription_id):
    sub = V.must_exist("subscriptions", subscription_id)
    data = V.body()
    notice_type = V.req_enum(data, "notice_type", K.NOTICE_TYPES)
    scheduled_for = V.req_dt(data, "scheduled_for")
    channel = V.opt_enum(data, "channel", K.NOTICE_CHANNELS, "EMAIL")
    body_ref = V.opt_str(data, "body_ref")

    if notice_type == "RENEWAL_REMINDER":
        opens, closes = ops.reminder_window(sub, ops.plan_of(sub))
        if opens is None or not (opens <= scheduled_for <= closes):
            fail("ERR_NOTICE_WINDOW_INVALID",
                 "scheduled_for lies outside the statutory reminder window.")

    notice = ops.create_notice(sub, notice_type, "SCHEDULED", scheduled_for,
                               ops.upcoming_cycle_index(sub), channel=channel,
                               body_ref=body_ref)
    return created(S.notice(notice))


@bp.post("/compliance-notices/<notice_id>/send")
@auth("BillingOperator")
def send_notice(notice_id):
    notice = V.must_exist("compliance_notices", notice_id)
    sub = store.subscriptions[notice["subscription_id"]]
    now = store.now()

    if notice["state"] != "SCHEDULED":
        fail("ERR_NOTICE_ALREADY_SENT", "The notice is no longer scheduled.")

    prior = [n for n in calc.notices_of_subscription(sub["id"])
             if n["state"] == "SENT" and n["notice_type"] == notice["notice_type"]
             and n["renewal_cycle_index"] == notice["renewal_cycle_index"]
             and n.get("sent_at") is not None]
    if prior:
        prior.sort(key=lambda n: (n["sent_at"], n["created_at"], n["_seq"]))
        latest = prior[-1]
        if now - latest["sent_at"] < days(K.NOTICE_COOLDOWN_DAYS):
            fail("ERR_NOTICE_COOLDOWN_ACTIVE",
                 "A notice of this type was sent for this cycle less than three days ago.")

    if notice["notice_type"] == "RENEWAL_REMINDER":
        opens, closes = ops.reminder_window(sub, ops.plan_of(sub))
        if opens is None or not (opens <= now <= closes):
            fail("ERR_NOTICE_WINDOW_INVALID",
                 "The clock lies outside the statutory reminder window.")

    notice["state"] = "SENT"
    notice["sent_at"] = now
    touch(notice)
    return ok(S.notice(notice))


# --------------------------------------------------------------------------
# Reversal (PRD §3.3)
# --------------------------------------------------------------------------
TOUCHED_FIELDS = {
    "FREQUENCY_CHANGE": {"frequency_weeks"},
    "ADDON_ADD": {"addons"},
    "ADDON_REMOVE": {"addons"},
    "SKIP_SHIPMENT": {"term_shipments_skipped"},
    "PLAN_DOWNGRADE": {"plan_id", "addons"},
    "PAUSE": set(),
    "RESUME": set(),
    "DISCOUNT_APPLY": {"active_discount_pct", "discount_remaining_cycles"},
}


@bp.post("/subscription-modifications/<modification_id>/reverse")
@auth("RetentionSpecialist", "PlatformAdmin")
def reverse_modification(modification_id):
    mod = V.must_exist("subscription_modifications", modification_id)
    data = V.body()
    V.opt_str(data, "reason_note")

    if mod["state"] not in ("APPLIED", "SCHEDULED"):
        fail("ERR_MODIFICATION_NOT_REVERSIBLE", "This modification cannot be reversed.")

    sub = store.subscriptions[mod["subscription_id"]]

    if mod["state"] == "SCHEDULED":
        mod["state"] = "CANCELLED"
        mod["delta_price_cents"] = 0
        touch(mod)
        touch(sub)
        return ok(S.modification(mod))

    own_fields = TOUCHED_FIELDS.get(mod["mod_type"], set())
    for later in calc.mods_of_subscription(sub["id"]):
        if later["id"] == mod["id"] or later["state"] != "APPLIED":
            continue
        if (later["created_at"], later["_seq"]) <= (mod["created_at"], mod["_seq"]):
            continue
        if own_fields & TOUCHED_FIELDS.get(later["mod_type"], set()):
            fail("ERR_MODIFICATION_NOT_REVERSIBLE",
                 "A later applied modification supersedes the fields this row captured.")

    snapshot = mod["prior_snapshot"] or {}
    compensating = ops.new_modification(
        sub, mod["mod_type"], store.now(),
        reverses_modification_id=mod["id"],
        save_offer_grant_id=mod.get("save_offer_grant_id"),
        target_plan_id=mod.get("target_plan_id"),
        frequency_weeks=mod.get("frequency_weeks"),
        addon_code=mod.get("addon_code"),
        addon_qty=mod.get("addon_qty"),
        skip_ship_at=mod.get("skip_ship_at"),
        pause_start_at=mod.get("pause_start_at"),
        pause_end_at=mod.get("pause_end_at"),
    )
    compensating["prior_snapshot"] = ops.snapshot_of(sub)
    compensating["state"] = "APPLIED"
    compensating["applied_at"] = store.now()
    compensating["delta_price_cents"] = -mod["delta_price_cents"]

    mod["state"] = "REVERSED"
    touch(mod)
    ops.restore_snapshot(sub, snapshot)

    grant_id = mod.get("save_offer_grant_id")
    if grant_id:
        grant = store.save_offer_grants.get(grant_id)
        if grant is not None and grant["state"] == "ACCEPTED":
            grant["state"] = "REVOKED"
            touch(grant)
            subscriber = store.subscribers[sub["subscriber_id"]]
            if subscriber.get("_suppression_grant_id") == grant["id"]:
                subscriber["winback_suppressed_until"] = None
                subscriber["_suppression_grant_id"] = None
                touch(subscriber)
    touch(sub)
    return ok(S.modification(mod))


@bp.get("/subscription-modifications/<modification_id>")
@auth()
def read_modification(modification_id):
    return ok(S.modification(V.must_exist("subscription_modifications", modification_id)))


@bp.get("/subscription-modifications")
@auth()
def list_modifications():
    return send_list(store.subscription_modifications.values(), S.modification,
                     {"subscription_id": "subscription_id",
                      "save_offer_grant_id": "save_offer_grant_id",
                      "reverses_modification_id": "reverses_modification_id",
                      "target_plan_id": "target_plan_id",
                      "state": "state", "mod_type": "mod_type"})
