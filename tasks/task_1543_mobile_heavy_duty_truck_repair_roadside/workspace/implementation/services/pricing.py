"""Pricing engine: rate card resolution, estimate (provisional) and invoice
(final) variants, warranty valuation, payment waterfall (SCAFFOLD 1.3)."""
from decimal import Decimal

from db import store
from errors import ApiError
from serializers import fleet_mtd, tier_for_mtd
from util import rhu

TIER_PCT = {
    "STANDARD": Decimal("0"),
    "GOLD": Decimal("0.05"),
    "PLATINUM": Decimal("0.10"),
}

# pinned waterfall bucket order (payment_waterfall_allocation)
WATERFALL_BUCKETS = [
    "tax_cents", "parts_subtotal_cents", "tow_charge_cents", "labor_amount_cents",
    "travel_time_amount_cents", "travel_amount_cents", "callout_fee_cents",
]


def resolve_rate_card(call):
    """Fleet-pinned card wins regardless of window; otherwise the single card
    whose closed window contains call.received_at."""
    fleet_id = call.get("fleet_account_id")
    if fleet_id:
        fleet = store.fleets.get(fleet_id)
        if fleet and fleet.get("rate_card_id"):
            card = store.rate_cards.get(fleet["rate_card_id"])
            if card is not None:
                return card
    received = call["received_at"]
    candidates = [
        c for c in store.rate_cards.values()
        if c["effective_from"] <= received <= c["effective_to"]
    ]
    if not candidates:
        raise ApiError("ERR_NO_ACTIVE_RATE_CARD",
                       "No rate card resolves for the call", 409)
    return candidates[0]


def active_dispatch(call):
    """The call's single in-flight dispatch (ACCEPTED / EN_ROUTE / ON_SITE)."""
    for d in store.dispatches.values():
        if (d["service_call_id"] == call["id"]
                and d["status"] in ("ACCEPTED", "EN_ROUTE", "ON_SITE")):
            return d
    return None


def service_dispatch(call):
    """The dispatch that served the call: COMPLETED (latest) else ON_SITE."""
    completed = [d for d in store.dispatches.values()
                 if d["service_call_id"] == call["id"] and d["status"] == "COMPLETED"]
    if completed:
        completed.sort(key=lambda d: (d.get("completed_at") or d["_created_dt"],
                                      d["_seq"]))
        return completed[-1]
    onsite = [d for d in store.dispatches.values()
              if d["service_call_id"] == call["id"] and d["status"] == "ON_SITE"]
    if onsite:
        onsite.sort(key=lambda d: d["_seq"])
        return onsite[-1]
    return None


def _class_rate(card, technician):
    if technician is not None and technician["labor_rate_class"] == "MASTER":
        return card["labor_rate_master_cents"]
    return card["labor_rate_standard_cents"]


def _after_hours_mult(card, call):
    if call["after_hours"]:
        return Decimal(card["after_hours_multiplier_bp"]) / Decimal(10000)
    return Decimal(1)


def _call_tier(call):
    fleet_id = call.get("fleet_account_id")
    if not fleet_id:
        return "STANDARD"
    return tier_for_mtd(fleet_mtd(fleet_id))


def estimate_total(call, labor_hours_est, travel_miles_est, parts_estimate_cents,
                   includes_tow, tow_estimate_cents):
    """Provisional variant: estimates, one-way travel with free-mile deduction
    even after hours, no travel-time component."""
    card = resolve_rate_card(call)
    disp = active_dispatch(call)
    tech = store.technicians.get(disp["technician_id"]) if disp else None
    class_rate = _class_rate(card, tech)
    mult = _after_hours_mult(card, call)
    labor = rhu(Decimal(str(labor_hours_est)) * class_rate * mult)
    travel = (max(0, travel_miles_est - card["travel_free_miles"])
              * card["travel_per_mile_cents"])
    callout = (card["emergency_callout_fee_cents"]
               if call.get("priority") == "P1_EMERGENCY" else 0)
    gross = labor + travel + callout
    tier = _call_tier(call)
    discount = rhu(Decimal(gross) * TIER_PCT[tier])
    tax = rhu(Decimal(parts_estimate_cents)
              * Decimal(card["parts_tax_rate_bp"]) / Decimal(10000))
    total = (gross - discount + parts_estimate_cents
             + (tow_estimate_cents if includes_tow else 0) + tax)
    return total


def comeback_policy(call):
    """Charge policy of the confirmed comeback case naming this call as new."""
    if not call.get("is_comeback"):
        return None
    for case in store.repeat_cases.values():
        if (case["new_service_call_id"] == call["id"]
                and case["status"] in ("CONFIRMED_COMEBACK", "RESOLVED")):
            return case["charge_policy"]
    return None


def invoice_pricing(call):
    """Final variant: actuals, after-hours portal-to-portal travel, travel time
    included, comeback adjustment, tier snapshot from mtd BEFORE this invoice."""
    card = resolve_rate_card(call)
    disp = service_dispatch(call)
    tech = store.technicians.get(disp["technician_id"]) if disp else None
    class_rate = _class_rate(card, tech)
    mult = _after_hours_mult(card, call)
    policy = comeback_policy(call)

    hours = call.get("labor_hours_actual") or 0
    labor_amount = rhu(Decimal(str(hours)) * class_rate * mult)
    if policy == "REDUCED":
        labor_amount = rhu(Decimal(labor_amount) / Decimal(2))

    actual_miles = disp["actual_travel_miles"] if disp else 0
    if call["after_hours"]:
        travel_miles_billable = 2 * actual_miles
    else:
        travel_miles_billable = max(0, actual_miles - card["travel_free_miles"])
    travel_amount = travel_miles_billable * card["travel_per_mile_cents"]
    travel_minutes = disp.get("actual_travel_minutes") or 0 if disp else 0
    travel_time_amount = travel_minutes * card["travel_time_per_minute_cents"]
    callout = (card["emergency_callout_fee_cents"]
               if call.get("priority") == "P1_EMERGENCY" else 0)
    if policy == "NO_CHARGE":
        labor_amount = 0
        travel_amount = 0
        travel_time_amount = 0
        callout = 0

    gross = labor_amount + travel_amount + travel_time_amount + callout
    tier = _call_tier(call)  # snapshot BEFORE this invoice feeds mtd
    discount = rhu(Decimal(gross) * TIER_PCT[tier])
    parts_subtotal = sum(
        p["line_total_cents"] for p in store.part_usages.values()
        if p["service_call_id"] == call["id"] and p["status"] == "POSTED"
        and p["charge_type"] == "CUSTOMER_PAY")
    tow_charge = sum(
        t["tow_fee_cents"] for t in store.tow_orders.values()
        if t["service_call_id"] == call["id"] and t["status"] == "DELIVERED")
    tax = rhu(Decimal(parts_subtotal)
              * Decimal(card["parts_tax_rate_bp"]) / Decimal(10000))
    pre_offset = gross - discount + parts_subtotal + tow_charge + tax
    claim_sum = sum(
        c["recovered_cents"] for c in store.warranty_claims.values()
        if c["service_call_id"] == call["id"]
        and c["status"] in ("APPROVED", "SETTLED")
        and c.get("recovered_cents") is not None)
    warranty_offset = max(0, min(claim_sum, pre_offset))
    total = max(0, pre_offset - warranty_offset)
    return {
        "labor_hours_actual": call.get("labor_hours_actual"),
        "labor_rate_cents": class_rate,
        "after_hours": call["after_hours"],
        "labor_amount_cents": labor_amount,
        "travel_miles_actual": actual_miles,
        "travel_miles_billable": travel_miles_billable,
        "travel_amount_cents": travel_amount,
        "travel_minutes_actual": travel_minutes,
        "travel_time_amount_cents": travel_time_amount,
        "callout_fee_cents": callout,
        "parts_subtotal_cents": parts_subtotal,
        "tow_charge_cents": tow_charge,
        "discount_tier": tier,
        "discount_cents": discount,
        "tax_cents": tax,
        "warranty_offset_cents": warranty_offset,
        "total_cents": total,
    }


def warranty_retail_value(claim, call):
    """Retail basis at submission: actual hours at the STANDARD class rate plus
    POSTED CUSTOMER_PAY part line totals."""
    card = resolve_rate_card(call)
    hours = call.get("labor_hours_actual") or 0
    labor = rhu(Decimal(str(hours)) * card["labor_rate_standard_cents"])
    parts = sum(
        p["line_total_cents"] for p in store.part_usages.values()
        if p["service_call_id"] == call["id"] and p["status"] == "POSTED"
        and p["charge_type"] == "CUSTOMER_PAY")
    return labor + parts


def waterfall_allocate(invoice, amount_cents):
    """Greedy fill across pinned buckets; remaining = face - prior POSTED
    allocations. Returns the per-bucket split for this payment."""
    prior = {b: 0 for b in WATERFALL_BUCKETS}
    for p in store.payments.values():
        if p["invoice_id"] == invoice["id"] and p["status"] == "POSTED":
            for b, v in p["allocation_json"].items():
                prior[b] = prior.get(b, 0) + v
    allocation = {}
    left = amount_cents
    for b in WATERFALL_BUCKETS:
        remaining = invoice[b] - prior[b]
        take = min(max(remaining, 0), left)
        allocation[b] = take
        left -= take
    return allocation
