from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from db import (
    fee_schedules,
    shelters,
    animals,
    utc_now,
    parse_iso,
    iso_from_dt,
)
from services.rounding import floor_mul, mul_round_half_up
from services.animal_service import adopter_adoption_history_count


LOYALTY_THRESHOLD = 2
AGE_SENIOR_THRESHOLD_MONTHS = 84
SENIOR_DISCOUNT_RATE = Decimal("0.5")
LONG_STAY_THRESHOLD_DAYS = 14
LONG_STAY_DISCOUNT_RATE = Decimal("0.9")


def _is_active(schedule, at=None):
    if at is None:
        at = utc_now()
    eff_from = parse_iso(schedule["effective_from"])
    eff_to = parse_iso(schedule.get("effective_to"))
    if eff_from is None:
        return False
    if eff_from > at:
        return False
    if eff_to is not None and at >= eff_to:
        return False
    return True


def lookup_schedule(shelter_id, fee_type, species, at=None):
    """Look up an active FeeSchedule row with species-specific match; fallback to ALL."""
    if at is None:
        at = utc_now()
    specific = None
    all_row = None
    for s in fee_schedules.values():
        if s["shelter_id"] != shelter_id:
            continue
        if s["fee_type"] != fee_type:
            continue
        if not _is_active(s, at):
            continue
        if s["species"] == species:
            if specific is None or parse_iso(s["effective_from"]) > parse_iso(specific["effective_from"]):
                specific = s
        elif s["species"] == "ALL":
            if all_row is None or parse_iso(s["effective_from"]) > parse_iso(all_row["effective_from"]):
                all_row = s
    return specific or all_row


def serialize_fee_schedule(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "shelter_id": s["shelter_id"],
        "fee_type": s["fee_type"],
        "species": s["species"],
        "amount_cents": s["amount_cents"],
        "effective_from": s["effective_from"],
        "effective_to": s.get("effective_to"),
        "is_currently_active": _is_active(s),
    }


def compute_adoption_fee(animal, adopter, shelter, at=None):
    """Compute adoption fee line items. Returns dict with line_items, subtotal_cents,
    discount_cents, tax_cents, total_amount_cents."""
    if at is None:
        at = utc_now()
    species = animal["species"]
    shelter_id = shelter["id"]

    base_row = lookup_schedule(shelter_id, "ADOPTION_BASE", species, at)
    base = base_row["amount_cents"] if base_row else 0
    original_base = base

    if animal.get("age_months", 0) >= AGE_SENIOR_THRESHOLD_MONTHS:
        base = floor_mul(base, SENIOR_DISCOUNT_RATE)

    surcharge_row = lookup_schedule(shelter_id, "SPECIAL_NEEDS_SURCHARGE", species, at)
    surcharge_unit = surcharge_row["amount_cents"] if surcharge_row else 0
    special_needs_count = len(animal.get("special_needs", []))
    surcharge = surcharge_unit * special_needs_count

    subtotal_cents = base + surcharge

    loyalty_row = lookup_schedule(shelter_id, "LOYALTY_DISCOUNT_PCT", "ALL", at)
    history_count = adopter_adoption_history_count(adopter["id"])
    if loyalty_row and history_count >= LOYALTY_THRESHOLD:
        pct = loyalty_row["amount_cents"]
        d = Decimal(subtotal_cents) * Decimal(pct) / Decimal(100)
        discount_cents = int(d.quantize(Decimal("1"), rounding=ROUND_FLOOR))
    else:
        discount_cents = 0

    tax_rate = Decimal(str(shelter["tax_rate"]))
    tax_cents = mul_round_half_up(subtotal_cents - discount_cents, tax_rate)

    total_amount_cents = subtotal_cents - discount_cents + tax_cents
    if total_amount_cents < 0:
        total_amount_cents = 0

    line_items = []
    if original_base > 0 or base > 0:
        desc = f"Adoption base ({species})"
        if animal.get("age_months", 0) >= AGE_SENIOR_THRESHOLD_MONTHS:
            desc += " — senior discount applied"
        line_items.append({
            "description": desc,
            "quantity": 1,
            "unit_price_cents": base,
            "amount_cents": base,
        })
    if surcharge > 0:
        line_items.append({
            "description": "Special needs surcharge",
            "quantity": special_needs_count,
            "unit_price_cents": surcharge_unit,
            "amount_cents": surcharge,
        })

    return {
        "line_items": line_items,
        "subtotal_cents": subtotal_cents,
        "discount_cents": discount_cents,
        "tax_cents": tax_cents,
        "total_amount_cents": total_amount_cents,
    }


def compute_boarding_fee(animal, shelter, duration_days, at=None):
    if at is None:
        at = utc_now()
    species = animal["species"]
    shelter_id = shelter["id"]

    daily_row = lookup_schedule(shelter_id, "BOARDING_DAILY", species, at)
    daily = daily_row["amount_cents"] if daily_row else 0

    surcharge_row = lookup_schedule(shelter_id, "SPECIAL_NEEDS_SURCHARGE", species, at)
    surcharge_unit = surcharge_row["amount_cents"] if surcharge_row else 0
    special_needs_count = len(animal.get("special_needs", []))

    effective_daily = daily + surcharge_unit * special_needs_count
    long_stay = duration_days > LONG_STAY_THRESHOLD_DAYS
    if long_stay:
        effective_daily = floor_mul(effective_daily, LONG_STAY_DISCOUNT_RATE)

    subtotal_cents = effective_daily * duration_days
    discount_cents = 0

    tax_rate = Decimal(str(shelter["tax_rate"]))
    tax_cents = mul_round_half_up(subtotal_cents, tax_rate)

    total_amount_cents = subtotal_cents + tax_cents

    line_items = []
    desc = f"Boarding daily ({species})"
    if long_stay:
        desc += " — long stay discount"
    line_items.append({
        "description": desc,
        "quantity": duration_days,
        "unit_price_cents": effective_daily,
        "amount_cents": effective_daily * duration_days,
    })

    return {
        "line_items": line_items,
        "subtotal_cents": subtotal_cents,
        "discount_cents": discount_cents,
        "tax_cents": tax_cents,
        "total_amount_cents": total_amount_cents,
    }


def serialize_invoice(inv):
    total = inv["total_amount_cents"]
    paid = inv["paid_amount_cents"]
    balance = max(0, total - paid)
    return {
        "id": inv["id"],
        "created_at": inv["created_at"],
        "updated_at": inv["updated_at"],
        "version": inv["version"],
        "shelter_id": inv["shelter_id"],
        "reference_type": inv["reference_type"],
        "reference_id": inv["reference_id"],
        "line_items": inv["line_items"],
        "subtotal_cents": inv["subtotal_cents"],
        "discount_cents": inv["discount_cents"],
        "tax_cents": inv["tax_cents"],
        "total_amount_cents": inv["total_amount_cents"],
        "paid_amount_cents": inv["paid_amount_cents"],
        "refund_amount_cents": inv["refund_amount_cents"],
        "balance_due_cents": balance,
        "settlement_batch_id": inv.get("settlement_batch_id"),
        "status": inv["status"],
    }


def serialize_compliance_hold(h):
    return {
        "id": h["id"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
        "animal_id": h["animal_id"],
        "hold_type": h["hold_type"],
        "severity": h["severity"],
        "reason": h["reason"],
        "imposed_by": h["imposed_by"],
        "imposed_role": h["imposed_role"],
        "resolved_by": h.get("resolved_by"),
        "resolution_notes": h.get("resolution_notes"),
        "status": h["status"],
    }


def serialize_settlement_batch(b):
    return {
        "id": b["id"],
        "created_at": b["created_at"],
        "shelter_id": b["shelter_id"],
        "period_start": b["period_start"],
        "period_end": b["period_end"],
        "invoice_ids": b.get("invoice_ids", []),
        "gross_amount_cents": b["gross_amount_cents"],
        "refund_amount_cents": b["refund_amount_cents"],
        "net_amount_cents": b["net_amount_cents"],
        "approved_by": b.get("approved_by"),
        "status": b["status"],
    }
