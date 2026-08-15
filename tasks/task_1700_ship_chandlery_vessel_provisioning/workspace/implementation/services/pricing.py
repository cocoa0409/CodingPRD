"""Line pricing (provisional + final variants), order totals, volume rebate,
duty split, cold-chain hours. Implements SCAFFOLD.yaml §1.3 and PRD §2.5,
§2.8, §3.9, §3.11.

Pinned rounding order (PRD §2.8): every line is fully computed and rounded
at its duty step before any summation; the subtotal is the sum of those
rounded line totals.
"""
from decimal import Decimal

from db import _parse_iso
from services.money import mul_pct_round, round_half_up_cents

# --- volume rebate tiers (PRD §3.11) ---
TIER1_SUBTOTAL_CENTS = 500000
TIER1_PCT = 4
TIER2_SUBTOTAL_CENTS = 1000000
TIER2_PCT = 7

# --- cold chain constants (SCAFFOLD calculations.line_pricing) ---
COLD_TIER1_MAX_HOURS = 72
COLD_TIER1_RATE_CENTS = 5
COLD_TIER2_RATE_CENTS = 12

# --- credit note constants (SCAFFOLD calculations.credit_note_amount) ---
RESTOCKING_PCT = 5
RESTOCKING_MIN_CENTS = 500

# --- payment tolerance (SCAFFOLD calculations.fx_payment_settlement) ---
FX_CLOSING_TOLERANCE_CENTS = 50


def whole_hours(start_dt, end_dt):
    """floor(seconds / 3600); negative clamps to 0 (SCAFFOLD cold_chain_hours)."""
    if start_dt is None or end_dt is None:
        return 0
    seconds = (end_dt - start_dt).total_seconds()
    if seconds <= 0:
        return 0
    return int(seconds // 3600)


def cold_rate_per_unit(hours):
    """Tiered cold rate with kink at 72h: 5*h if h<=72 else 5*72+12*(h-72)."""
    if hours <= 0:
        return 0
    if hours <= COLD_TIER1_MAX_HOURS:
        return COLD_TIER1_RATE_CENTS * hours
    return (COLD_TIER1_RATE_CENTS * COLD_TIER1_MAX_HOURS
            + COLD_TIER2_RATE_CENTS * (hours - COLD_TIER1_MAX_HOURS))


def compute_line(*, qty, unit_price_cents, duty_rate_pct, requires_cold_chain,
                 duty_free_eligible, cold_hours):
    """One line of line_pricing. Returns a dict of line components.

    duty_cents rounded half-up at the duty step and nowhere else inside the
    line computation.
    """
    line_base_cents = unit_price_cents * qty
    if duty_free_eligible:
        duty_cents = 0
    else:
        duty_cents = mul_pct_round(line_base_cents, duty_rate_pct)
    if requires_cold_chain:
        cold_surcharge_cents = qty * cold_rate_per_unit(cold_hours)
    else:
        cold_surcharge_cents = 0
    line_total_cents = line_base_cents + duty_cents + cold_surcharge_cents
    return {
        "line_base_cents": line_base_cents,
        "duty_cents": duty_cents,
        "cold_surcharge_cents": cold_surcharge_cents,
        "line_total_cents": line_total_cents,
    }


def duty_free_eligible(vessel_call, catalog_item, clearance_at):
    """Conjunctive duty-free test (PRD §3.9): foreign_going AND clearance ==
    CLEARED AND bonded_eligible. Non-bonded items are ALWAYS dutiable."""
    return bool(vessel_call.get("foreign_going")) \
        and clearance_at == "CLEARED" \
        and bool(catalog_item.get("bonded_eligible"))


def volume_rebate(subtotal_cents):
    """Threshold rebate read from the PRE-REBATE subtotal (PRD §3.11).

    Boundary inclusive: subtotal == 500000 -> 4%. Tier never re-evaluated
    on the post-rebate total.
    """
    if subtotal_cents >= TIER2_SUBTOTAL_CENTS:
        pct = TIER2_PCT
    elif subtotal_cents >= TIER1_SUBTOTAL_CENTS:
        pct = TIER1_PCT
    else:
        pct = 0
    return mul_pct_round(subtotal_cents, pct)


def order_totals(line_totals):
    """subtotal = sum of rounded line totals; rebate; total = subtotal - rebate."""
    subtotal_cents = sum(line_totals)
    rebate_cents = volume_rebate(subtotal_cents)
    total_cents = subtotal_cents - rebate_cents
    return {
        "subtotal_cents": subtotal_cents,
        "rebate_cents": rebate_cents,
        "total_cents": total_cents,
    }


def provisional_pricing(quotation_lines, vessel_call, catalog_by_id):
    """Provisional variant (PRD §2.8): quoted qty; duty-free eligibility with
    the CURRENT customs_clearance_status; cold hours = planned port stay.

    Returns the full order_totals dict (subtotal_cents, rebate_cents,
    total_cents) so callers can freeze the whole breakdown."""
    cold_hours = whole_hours(_parse_iso(vessel_call["scheduled_eta"]),
                             _parse_iso(vessel_call["scheduled_etd"]))
    clearance_now = vessel_call["customs_clearance_status"]
    line_totals = []
    for line in quotation_lines:
        item = catalog_by_id[line["catalog_item_id"]]
        eligible = duty_free_eligible(vessel_call, item, clearance_now)
        computed = compute_line(
            qty=line["qty"],
            unit_price_cents=line["unit_price_cents"],
            duty_rate_pct=item.get("duty_rate_pct", 0),
            requires_cold_chain=bool(item.get("requires_cold_chain")),
            duty_free_eligible=eligible,
            cold_hours=cold_hours,
        )
        line_totals.append(computed["line_total_cents"])
    return order_totals(line_totals)


def final_invoice_pricing(order, vessel_call, catalog_by_id, last_confirmed_at):
    """Final variant (PRD §2.8 / §3.9): delivered qty; clearance at issuance;
    cold hours = whole hours between accepted_at and the last delivered
    delivery's confirmed_at. Returns invoice line records + duty split."""
    cold_hours = whole_hours(_parse_iso(order["accepted_at"]), last_confirmed_at)
    clearance_now = vessel_call["customs_clearance_status"]
    lines_out = []
    for line in order["lines"]:
        item = catalog_by_id[line["catalog_item_id"]]
        eligible = duty_free_eligible(vessel_call, item, clearance_now)
        computed = compute_line(
            qty=line["qty_delivered"],
            unit_price_cents=line["unit_price_cents"],
            duty_rate_pct=item.get("duty_rate_pct", 0),
            requires_cold_chain=bool(item.get("requires_cold_chain")),
            duty_free_eligible=eligible,
            cold_hours=cold_hours,
        )
        lines_out.append({
            "catalog_item_id": line["catalog_item_id"],
            "qty": line["qty_delivered"],
            "unit_price_cents": line["unit_price_cents"],
            "duty_free": eligible,
            "duty_cents": computed["duty_cents"],
            "cold_surcharge_cents": computed["cold_surcharge_cents"],
            "line_total_cents": computed["line_total_cents"],
        })
    # duty_split (SCAFFOLD calculations.duty_split)
    duty_free_subtotal_cents = sum(l["line_total_cents"] for l in lines_out if l["duty_free"])
    dutiable_subtotal_cents = sum(l["line_total_cents"] for l in lines_out if not l["duty_free"])
    total_duty_cents = sum(l["duty_cents"] for l in lines_out if not l["duty_free"])
    subtotal_cents = duty_free_subtotal_cents + dutiable_subtotal_cents
    rebate_cents = volume_rebate(subtotal_cents)
    total_usd_cents = subtotal_cents - rebate_cents
    return {
        "lines": lines_out,
        "duty_free_subtotal_cents": duty_free_subtotal_cents,
        "dutiable_subtotal_cents": dutiable_subtotal_cents,
        "total_duty_cents": total_duty_cents,
        "subtotal_cents": subtotal_cents,
        "rebate_cents": rebate_cents,
        "total_usd_cents": total_usd_cents,
    }
