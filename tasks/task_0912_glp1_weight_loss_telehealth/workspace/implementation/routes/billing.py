"""Subscriptions, billing cycles, pricing, settlement and reversal (PRD 3.9)."""

from flask import Blueprint

import calculations as calc
import envelope
import errors
import serializers
import services
import validation as v
from auth import ANY_ROLE, guard, require_owner
from errors import ApiError
from store import new_record, ordered, parse_iso, store, touch

bp = Blueprint("billing", __name__)

VOID_REASONS_ENDPOINT = ("ADMIN_REVERSAL",)


# --- subscriptions ---------------------------------------------------------
@bp.post("/subscriptions")
def create_subscription():
    guard(["BillingAdmin"])
    body = v.body()

    patient_id = v.string_field(body, "patient_id", required=True)
    prescription_id = v.string_field(body, "prescription_id", required=True)
    anchor_at = v.datetime_field(body, "anchor_at", required=True)
    coaching_addon_enabled = v.bool_field(body, "coaching_addon_enabled",
                                          required=False, default=False)

    services.get_patient(patient_id)
    services.get_prescription(prescription_id)

    subscription = new_record(store.subscriptions, {
        "patient_id": patient_id,
        "prescription_id": prescription_id,
        "anchor_at": anchor_at,
        "coaching_addon_enabled": coaching_addon_enabled,
        "status": "ACTIVE",
        "coaching_credits_granted": 0,
        "coaching_credits_reserved": 0,
        "coaching_credits_consumed": 0,
        "coaching_credits_forfeited": 0,
        "coaching_credits_available": 0,
        "paused_at": None,
        "pause_days_used": 0,
        "cycle_count": 0,
    })
    services.open_billing_cycle(subscription, anchor_at)

    return envelope.success(serializers.dump("subscription", subscription), 201)


@bp.get("/subscriptions/<subscription_id>")
def read_subscription(subscription_id):
    guard(ANY_ROLE)
    subscription = services.get_subscription(subscription_id)
    return envelope.success(serializers.dump("subscription", subscription), 200)


@bp.get("/subscriptions")
def list_subscriptions():
    guard(ANY_ROLE)
    limit, offset = v.pagination()
    filters = v.query_filters("patient_id", "prescription_id", "status")
    records = v.apply_filters(ordered(list(store.subscriptions.values())), filters)
    page, total = v.paginate(records, limit, offset)
    return envelope.collection(serializers.dump_many("subscription", page),
                               limit, offset, total)


@bp.post("/subscriptions/<subscription_id>/pause")
def pause_subscription(subscription_id):
    guard(["BillingAdmin", "Patient"])
    subscription = services.get_subscription(subscription_id)

    if subscription["status"] != "ACTIVE":
        raise ApiError(errors.ERR_INVALID_STATE)
    if subscription["pause_days_used"] >= calc.PAUSE_MAX_DAYS:
        raise ApiError(errors.ERR_PAUSE_LIMIT_EXCEEDED)

    subscription["status"] = "PAUSED"
    subscription["paused_at"] = store.now_iso()
    touch(subscription)

    services.cascade_cycle_void(subscription, "SUBSCRIPTION_PAUSED")

    return envelope.success(serializers.dump("subscription", subscription), 200)


@bp.post("/subscriptions/<subscription_id>/resume")
def resume_subscription(subscription_id):
    guard(["BillingAdmin", "Patient"])
    subscription = services.get_subscription(subscription_id)

    if subscription["status"] != "PAUSED":
        raise ApiError(errors.ERR_INVALID_STATE)

    subscription["pause_days_used"] += services.pause_days_elapsed(subscription)
    subscription["paused_at"] = None
    subscription["status"] = "ACTIVE"
    touch(subscription)

    services.open_billing_cycle(subscription, store.now_iso())

    return envelope.success(serializers.dump("subscription", subscription), 200)


@bp.post("/subscriptions/<subscription_id>/cancel")
def cancel_subscription(subscription_id):
    user_id, role = guard(["BillingAdmin", "Patient"])
    subscription = services.get_subscription(subscription_id)
    if role == "Patient":
        require_owner(subscription["patient_id"] == user_id)

    if subscription["status"] not in ("ACTIVE", "PAUSED"):
        raise ApiError(errors.ERR_INVALID_STATE)

    was_active = subscription["status"] == "ACTIVE"
    subscription["status"] = "CANCELLED"
    touch(subscription)

    if was_active:
        services.cascade_cycle_void(subscription, "SUBSCRIPTION_CANCELLED")

    return envelope.success(serializers.dump("subscription", subscription), 200)


# --- billing cycles --------------------------------------------------------
@bp.get("/billing-cycles/<billing_cycle_id>")
def read_billing_cycle(billing_cycle_id):
    guard(ANY_ROLE)
    cycle = services.get_billing_cycle(billing_cycle_id)
    return envelope.success(serializers.dump("billing_cycle", cycle), 200)


@bp.get("/billing-cycles")
def list_billing_cycles():
    guard(ANY_ROLE)
    limit, offset = v.pagination()
    filters = v.query_filters("subscription_id", "status")
    records = v.apply_filters(ordered(list(store.billing_cycles.values())), filters)
    page, total = v.paginate(records, limit, offset)
    return envelope.collection(serializers.dump_many("billing_cycle", page),
                               limit, offset, total)


@bp.post("/billing-cycles/<billing_cycle_id>/invoice")
def invoice_billing_cycle(billing_cycle_id):
    guard(["BillingAdmin"])
    cycle = services.get_billing_cycle(billing_cycle_id)

    if cycle["status"] != "OPEN":
        raise ApiError(errors.ERR_INVALID_STATE)

    subscription = services.get_subscription(cycle["subscription_id"])
    if subscription["status"] != "ACTIVE":
        raise ApiError(errors.ERR_SUBSCRIPTION_NOT_ACTIVE)

    period_start = parse_iso(cycle["period_start_at"])
    if store.now_dt() < period_start:
        raise ApiError(errors.ERR_INVALID_STATE)

    prescription = services.get_prescription(subscription["prescription_id"])
    charge_basis, medication_charge_cents = calc.medication_charge(
        prescription["active_route_mode"], prescription["dose_level"],
        prescription["units_per_cycle"])

    triaged_count = services.triaged_count_in_window(
        prescription["id"], cycle["period_start_at"], cycle["period_end_at"])
    totals = calc.invoice_total(medication_charge_cents,
                                subscription["coaching_addon_enabled"], triaged_count)

    cycle["charge_basis"] = charge_basis
    cycle["medication_charge_cents"] = medication_charge_cents
    cycle["coaching_addon_fee_cents"] = totals["coaching_addon_fee_cents"]
    cycle["dispensing_fee_cents"] = totals["dispensing_fee_cents"]
    cycle["adherence_credit_cents"] = totals["adherence_credit_cents"]
    cycle["total_due_cents"] = totals["total_due_cents"]
    cycle["status"] = "INVOICED"
    cycle["invoiced_at"] = store.now_iso()
    touch(cycle)

    return envelope.success(serializers.dump("billing_cycle", cycle), 200)


@bp.post("/billing-cycles/<billing_cycle_id>/settle")
def settle_billing_cycle(billing_cycle_id):
    guard(["BillingAdmin"])
    cycle = services.get_billing_cycle(billing_cycle_id)

    body = v.body()
    v.string_field(body, "payment_reference", required=False, default=None)

    if cycle["status"] != "INVOICED":
        raise ApiError(errors.ERR_INVALID_STATE)

    subscription = services.get_subscription(cycle["subscription_id"])
    if subscription["status"] != "ACTIVE":
        raise ApiError(errors.ERR_SUBSCRIPTION_NOT_ACTIVE)

    unused_credit = calc.coaching_unused_credit(subscription)
    settled = max(0, cycle["total_due_cents"] - unused_credit)

    cycle["coaching_unused_credit_cents"] = unused_credit
    cycle["settled_amount_cents"] = settled
    cycle["status"] = "SETTLED"
    touch(cycle)

    patient = services.get_patient(subscription["patient_id"])
    patient["lifetime_charged_cents"] += settled
    touch(patient)

    services.open_billing_cycle(subscription, cycle["period_end_at"])

    return envelope.success(serializers.dump("billing_cycle", cycle), 200)


@bp.post("/billing-cycles/<billing_cycle_id>/void")
def void_billing_cycle(billing_cycle_id):
    guard(["BillingAdmin"])
    cycle = services.get_billing_cycle(billing_cycle_id)

    body = v.body()
    void_reason = v.enum_field(body, "void_reason", VOID_REASONS_ENDPOINT,
                               required=True)

    if cycle["status"] not in ("OPEN", "INVOICED", "SETTLED"):
        raise ApiError(errors.ERR_INVALID_STATE)

    services.void_cycle(cycle, void_reason)
    return envelope.success(serializers.dump("billing_cycle", cycle), 200)
