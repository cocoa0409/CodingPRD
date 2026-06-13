"""Pricing and SLA calculations (PRD §3.5, scaffold §1.3).

All monetary amounts are integer cents. Where a non-integer factor is applied,
the FULL product is formed first and rounded ONCE, half-up.
"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

import db

# --- Constants (scaffold §1.3) ---
MARKUP_MULTIPLIER = Decimal("1.35")      # RETAIL
AT_COST_MULTIPLIER = Decimal("1.0")      # WARRANTY_REDO

RUSH_TIER1_CAP = 5000
RUSH_TIER2_CAP = 20000
RUSH_RATE_1 = Decimal("0.30")
RUSH_RATE_2 = Decimal("0.20")
RUSH_RATE_3 = Decimal("0.10")
RUSH_FLOOR_CENTS = 1500

RUSH_SLA_FACTOR = Decimal("0.5")
RUSH_MIN_DAYS = 1

UNCLAIMED_GRACE_DAYS = 30
DISPOSAL_DAYS = 90


def round_half_up(value):
    """Round a Decimal (or numeric) to the nearest integer, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# parts_markup (scaffold §1.3 / PRD §3.5)
# ---------------------------------------------------------------------------
def parts_markup(supplier_cost_cents, quantity, is_redo):
    """marked_up_cost_cents = round_half_up(supplier_cost * quantity * multiplier).

    One rounding after the full product. RETAIL multiplier 1.35 on a normal
    ticket; AT_COST 1.0 on a warranty-redo ticket.
    """
    multiplier = AT_COST_MULTIPLIER if is_redo else MARKUP_MULTIPLIER
    product = Decimal(supplier_cost_cents) * Decimal(quantity) * multiplier
    return round_half_up(product)


# ---------------------------------------------------------------------------
# rush_surcharge (scaffold §1.3 / PRD §3.5) — marginal tiered, half-open
# ---------------------------------------------------------------------------
def rush_surcharge(pre_rush, priority):
    if priority != "RUSH":
        return 0
    pre = pre_rush
    # tier portions, half-open boundaries
    tier1_portion = max(0, min(pre, RUSH_TIER1_CAP))
    tier2_portion = max(0, min(pre, RUSH_TIER2_CAP) - RUSH_TIER1_CAP)
    tier3_portion = max(0, pre - RUSH_TIER2_CAP)
    surcharge_raw = (
        Decimal(tier1_portion) * RUSH_RATE_1
        + Decimal(tier2_portion) * RUSH_RATE_2
        + Decimal(tier3_portion) * RUSH_RATE_3
    )
    rounded = round_half_up(surcharge_raw)
    return max(RUSH_FLOOR_CENTS, rounded)


# ---------------------------------------------------------------------------
# estimate_total (scaffold §1.3 / PRD §3.5) — two variants, pinned order
# ---------------------------------------------------------------------------
def estimate_total(ticket_id, priority, variant):
    """Return dict with labor_subtotal, parts_subtotal, rush_surcharge, total.

    PROVISIONAL: line_price = quoted_price_cents; lines QUOTED;
                 parts in {REQUESTED, ORDERED, RECEIVED}.
    FINAL:       line_price = adjusted_price_cents if not None else quoted;
                 lines COMPLETED; parts RECEIVED only.
    Evaluation order is PINNED: labor, parts, pre_rush, rush, total.
    """
    lines = [sl for sl in db.service_lines.values() if sl["ticket_id"] == ticket_id]
    parts = [po for po in db.parts_orders.values() if po["ticket_id"] == ticket_id]

    if variant == "PROVISIONAL":
        in_scope_lines = [sl for sl in lines if sl["status"] == "QUOTED"]
        labor_subtotal = sum(sl["quoted_price_cents"] for sl in in_scope_lines)
        in_scope_parts = [po for po in parts if po["status"] in ("REQUESTED", "ORDERED", "RECEIVED")]
    elif variant == "FINAL":
        in_scope_lines = [sl for sl in lines if sl["status"] == "COMPLETED"]
        labor_subtotal = 0
        for sl in in_scope_lines:
            adj = sl.get("adjusted_price_cents")
            labor_subtotal += adj if adj is not None else sl["quoted_price_cents"]
        in_scope_parts = [po for po in parts if po["status"] == "RECEIVED"]
    else:
        raise ValueError("unknown variant %s" % variant)

    parts_subtotal = sum(po["marked_up_cost_cents"] for po in in_scope_parts)
    pre_rush = labor_subtotal + parts_subtotal
    surcharge = rush_surcharge(pre_rush, priority)
    total = pre_rush + surcharge
    return {
        "labor_subtotal_cents": labor_subtotal,
        "parts_subtotal_cents": parts_subtotal,
        "rush_surcharge_cents": surcharge,
        "estimate_total_cents": total,
    }


# ---------------------------------------------------------------------------
# ready_by_sla (scaffold §1.3 / PRD §3.5)
# ---------------------------------------------------------------------------
def ceil_div_for_rush(sla_days):
    """RUSH: max(RUSH_MIN_DAYS, ceil(sla_days * 0.5))."""
    raw = Decimal(sla_days) * RUSH_SLA_FACTOR
    ceil_days = int(raw.to_integral_value(rounding="ROUND_CEILING"))
    return max(RUSH_MIN_DAYS, ceil_days)


def ready_by_sla(ticket):
    """Compute ready_by datetime at estimate approval.

    base_days = max over non-VOIDED ServiceLines of ServiceType.standard_turnaround_days
    parts_days = max over non-CANCELLED PartsOrders of lead_time_days (0 if none)
    sla_days = base_days + parts_days
    RUSH: sla_days = max(RUSH_MIN_DAYS, ceil(sla_days * 0.5))
    ready_by = drop_off_at + sla_days calendar days (UTC)
    """
    tid = ticket["id"]
    lines = [sl for sl in db.service_lines.values()
             if sl["ticket_id"] == tid and sl["status"] != "VOIDED"]
    base_days = 0
    for sl in lines:
        st = db.service_types.get(sl["service_type_id"])
        if st is not None:
            base_days = max(base_days, st["standard_turnaround_days"])

    parts = [po for po in db.parts_orders.values()
             if po["ticket_id"] == tid and po["status"] != "CANCELLED"]
    parts_days = 0
    for po in parts:
        parts_days = max(parts_days, po["lead_time_days"])

    sla_days = base_days + parts_days
    if ticket["priority"] == "RUSH":
        sla_days = ceil_div_for_rush(sla_days)

    return ticket["drop_off_at"] + timedelta(days=sla_days)


# ---------------------------------------------------------------------------
# warranty_window (scaffold §1.3 / PRD §3.6)
# ---------------------------------------------------------------------------
def warranty_window(ticket):
    """warranty_expires_at = picked_up_at + max(warranty_days over COMPLETED lines).

    0 days (so expiry == picked_up_at) when no completed lines.
    """
    tid = ticket["id"]
    completed = [sl for sl in db.service_lines.values()
                 if sl["ticket_id"] == tid and sl["status"] == "COMPLETED"]
    cover_days = 0
    for sl in completed:
        st = db.service_types.get(sl["service_type_id"])
        if st is not None:
            cover_days = max(cover_days, st["warranty_days"])
    return ticket["picked_up_at"] + timedelta(days=cover_days)


# ---------------------------------------------------------------------------
# amount_paid (scaffold §1.3 / PRD §3.6)
# ---------------------------------------------------------------------------
def amount_paid(ticket_id):
    """Sum of CAPTURED Payment.amount_cents for the ticket."""
    return sum(p["amount_cents"] for p in db.payments.values()
               if p["ticket_id"] == ticket_id and p["state"] == "CAPTURED")
