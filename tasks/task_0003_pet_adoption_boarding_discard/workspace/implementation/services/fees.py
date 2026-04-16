"""Fee calculation and invoice management."""

from decimal import Decimal, ROUND_HALF_UP
import math
from datetime import datetime, timezone
import db
from db import new_id, now_iso


AGE_SENIOR_THRESHOLD = 84
SENIOR_DISCOUNT_RATE = Decimal("0.5")
LOYALTY_THRESHOLD = 2
LONG_STAY_THRESHOLD = 14
LONG_STAY_DISCOUNT_RATE = Decimal("0.9")
DEFAULT_TAX_RATE = Decimal("0.0")


def _dec(val):
    """Convert to Decimal safely."""
    if isinstance(val, Decimal):
        return val
    return Decimal(str(val))


def _round2(val):
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _parse_dt(s):
    if isinstance(s, datetime):
        return s
    s_clean = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s_clean)


def lookup_fee_schedule(shelter_id, fee_type, species):
    """Find the active fee schedule entry matching shelter, type, species."""
    now = datetime.now(timezone.utc)
    candidates = []
    for fs in db.fee_schedules.values():
        if fs["shelter_id"] != shelter_id:
            continue
        if fs["fee_type"] != fee_type:
            continue
        if fs["species"] != species and fs["species"] != "ALL":
            continue
        eff_from = _parse_dt(fs["effective_from"])
        if eff_from > now:
            continue
        if fs.get("effective_to"):
            eff_to = _parse_dt(fs["effective_to"])
            if eff_to <= now:
                continue
        candidates.append(fs)

    # Prefer exact species match over ALL
    for c in candidates:
        if c["species"] == species:
            return _dec(c["amount"])
    for c in candidates:
        if c["species"] == "ALL":
            return _dec(c["amount"])
    return Decimal("0")


def compute_adoption_fee(shelter_id, animal, adopter):
    """Compute adoption fee. Returns (line_items, subtotal, tax_amount, discount_amount, total_amount)."""
    base_fee = lookup_fee_schedule(shelter_id, "ADOPTION_BASE", animal["species"])

    if animal["age_months"] >= AGE_SENIOR_THRESHOLD:
        base_fee = _round2(base_fee * SENIOR_DISCOUNT_RATE)

    special_needs = animal.get("special_needs", [])
    surcharge_per = lookup_fee_schedule(shelter_id, "SPECIAL_NEEDS_SURCHARGE", animal["species"])
    surcharge = _round2(surcharge_per * Decimal(str(len(special_needs))))

    loyalty_discount = Decimal("0")
    if adopter.get("adoption_history_count", 0) >= LOYALTY_THRESHOLD:
        loyalty_rate = lookup_fee_schedule(shelter_id, "LOYALTY_DISCOUNT", "ALL")
        loyalty_discount = _round2((base_fee + surcharge) * loyalty_rate)

    subtotal = _round2(base_fee + surcharge)
    discount_amount = _round2(loyalty_discount)

    # Tax rate: look for a configured one or default to 0
    tax_rate = _get_shelter_tax_rate(shelter_id)
    taxable = subtotal - discount_amount
    tax_amount = _round2(taxable * tax_rate)
    total_amount = _round2(subtotal - discount_amount + tax_amount)

    line_items = []
    line_items.append({
        "description": f"Adoption fee - {animal['species']}",
        "quantity": 1,
        "unit_price": float(base_fee),
        "amount": float(base_fee),
    })
    if surcharge > 0:
        line_items.append({
            "description": "Special needs surcharge",
            "quantity": len(special_needs),
            "unit_price": float(surcharge_per),
            "amount": float(surcharge),
        })

    return line_items, float(subtotal), float(tax_amount), float(discount_amount), float(total_amount)


def compute_boarding_fee(shelter_id, animal, check_in_date_str, check_out_date_str):
    """Compute boarding fee. Returns (line_items, subtotal, tax_amount, discount_amount, total_amount, duration_days)."""
    ci = _parse_dt(check_in_date_str)
    co = _parse_dt(check_out_date_str)
    diff_seconds = (co - ci).total_seconds()
    duration_days = math.ceil(diff_seconds / 86400)
    if duration_days < 1:
        duration_days = 1

    daily_rate = lookup_fee_schedule(shelter_id, "BOARDING_DAILY", animal["species"])
    special_needs = animal.get("special_needs", [])
    daily_surcharge = lookup_fee_schedule(shelter_id, "SPECIAL_NEEDS_SURCHARGE", animal["species"])
    daily_surcharge_total = _round2(daily_surcharge * Decimal(str(len(special_needs))))

    effective_daily = daily_rate + daily_surcharge_total
    if duration_days > LONG_STAY_THRESHOLD:
        effective_daily = _round2(effective_daily * LONG_STAY_DISCOUNT_RATE)

    subtotal = _round2(effective_daily * Decimal(str(duration_days)))
    tax_rate = _get_shelter_tax_rate(shelter_id)
    tax_amount = _round2(subtotal * tax_rate)
    total_amount = _round2(subtotal + tax_amount)

    line_items = []
    line_items.append({
        "description": f"Boarding - {animal['species']} ({duration_days} days)",
        "quantity": duration_days,
        "unit_price": float(effective_daily),
        "amount": float(subtotal),
    })

    return line_items, float(subtotal), float(tax_amount), 0.0, float(total_amount), duration_days


def create_invoice(shelter_id, reference_type, reference_id, line_items, subtotal, tax_amount, discount_amount, total_amount):
    """Create a FeeInvoice and transition to ISSUED."""
    tax_rate = _get_shelter_tax_rate(shelter_id)
    ts = now_iso()
    invoice = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "shelter_id": shelter_id,
        "reference_type": reference_type,
        "reference_id": reference_id,
        "line_items": line_items,
        "subtotal": subtotal,
        "tax_rate": float(tax_rate),
        "tax_amount": tax_amount,
        "discount_amount": discount_amount,
        "total_amount": total_amount,
        "paid_amount": 0.0,
        "refund_amount": 0.0,
        "balance_due": total_amount,
        "status": "ISSUED",
    }
    db.fee_invoices[invoice["id"]] = invoice
    return invoice


def recompute_shelter_revenue(shelter_id):
    """Recompute shelter revenue_balance from invoices."""
    shelter = db.shelters.get(shelter_id)
    if not shelter:
        return
    paid_total = Decimal("0")
    refund_total = Decimal("0")
    for inv in db.fee_invoices.values():
        if inv["shelter_id"] != shelter_id:
            continue
        if inv["status"] in ("PAID", "PARTIALLY_PAID"):
            paid_total += _dec(inv["paid_amount"])
        if inv["status"] == "REFUNDED":
            refund_total += _dec(inv["refund_amount"])
    shelter["revenue_balance"] = float(_round2(paid_total - refund_total))


def _get_shelter_tax_rate(shelter_id):
    """Get configured tax rate for shelter from shelter record."""
    shelter = db.shelters.get(shelter_id)
    if shelter and "tax_rate" in shelter:
        return _dec(shelter["tax_rate"])
    return DEFAULT_TAX_RATE
