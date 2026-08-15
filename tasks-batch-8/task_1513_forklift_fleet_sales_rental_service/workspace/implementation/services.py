"""Business logic: calculations, cascades, sweeps, shared domain helpers."""
from datetime import timedelta
from decimal import Decimal

import clock
import store
from errors import (
    raise_err,
    ERR_ACCOUNT_CREDIT_HOLD,
    ERR_INVALID_STATE,
)
from util import round_half_up_cents, round_half_up_1dp, bump


# ---------------------------------------------------------------------------
# Quote pricing (calculation: quote_pricing)
# ---------------------------------------------------------------------------
TAX_RATE = Decimal("0.08")
TIER2_THRESHOLD_CENTS = 500000
TIER2_PCT = Decimal("0.10")
TIER1_THRESHOLD_CENTS = 100000
TIER1_PCT = Decimal("0.05")


def recompute_quote_pricing(quote):
    """Sum lines -> tier on subtotal -> discount once at quote level -> tax on net."""
    lines = [l for l in store.quote_lines.values() if l["quote_id"] == quote["id"]]
    subtotal = sum(l["extended_cents"] for l in lines)
    if subtotal >= TIER2_THRESHOLD_CENTS:
        tier_pct = TIER2_PCT
    elif subtotal >= TIER1_THRESHOLD_CENTS:
        tier_pct = TIER1_PCT
    else:
        tier_pct = Decimal("0")
    discount = round_half_up_cents(Decimal(subtotal) * tier_pct)
    tax = round_half_up_cents(Decimal(subtotal - discount) * TAX_RATE)
    quote["subtotal_cents"] = subtotal
    quote["discount_cents"] = discount
    quote["tax_cents"] = tax
    quote["total_cents"] = subtotal - discount + tax


# ---------------------------------------------------------------------------
# Rental billing (calculation: rental_billing)
# ---------------------------------------------------------------------------
def _ceil_div(a, b):
    return -(-a // b)


def scheduled_days_of(start_date, end_date):
    return (end_date - start_date).days


def rate_tier_of(scheduled_days):
    if scheduled_days >= 28:
        return "MONTHLY"
    if scheduled_days >= 7:
        return "WEEKLY"
    return "DAILY"


def provisional_estimate_cents(unit, customer, scheduled_days, tier):
    if tier == "DAILY":
        tier_amount = scheduled_days * unit["daily_rate_cents"]
    elif tier == "WEEKLY":
        tier_amount = _ceil_div(scheduled_days, 7) * unit["weekly_rate_cents"]
    else:  # MONTHLY
        tier_amount = _ceil_div(scheduled_days, 28) * unit["monthly_rate_cents"]
    discount_pct = Decimal(repr(float(customer.get("discount_pct", 0))))
    estimate = round_half_up_cents(Decimal(tier_amount) * (Decimal(1) - discount_pct))
    return max(estimate, unit["daily_rate_cents"])


def final_charge_cents(unit, customer, scheduled_days, tier, actual_days):
    overage_days = max(0, actual_days - scheduled_days)
    if tier == "DAILY":
        tier_final = scheduled_days * unit["daily_rate_cents"]
    elif tier == "WEEKLY":
        whole_weeks = scheduled_days // 7
        rem_days = scheduled_days % 7
        tier_final = whole_weeks * unit["weekly_rate_cents"] + min(
            rem_days * unit["daily_rate_cents"], unit["weekly_rate_cents"]
        )
    else:  # MONTHLY
        whole_months = scheduled_days // 28
        rem_days = scheduled_days % 28
        rem_weeks_ceil = _ceil_div(rem_days, 7) if rem_days > 0 else 0
        tier_final = whole_months * unit["monthly_rate_cents"] + min(
            rem_weeks_ceil * unit["weekly_rate_cents"], unit["monthly_rate_cents"]
        )
    discount_pct = Decimal(repr(float(customer.get("discount_pct", 0))))
    discounted_tier = round_half_up_cents(Decimal(tier_final) * (Decimal(1) - discount_pct))
    overage_day_charge = round_half_up_cents(Decimal("1.5") * Decimal(unit["daily_rate_cents"]))
    return discounted_tier + overage_days * overage_day_charge


# ---------------------------------------------------------------------------
# Fuel event cost (calculation: fuel_event_cost)
# ---------------------------------------------------------------------------
def fuel_event_cost(unit, event_type, kwh, cylinders):
    if unit["fuel_program"] == "BATTERY":
        if event_type == "CHARGE":
            return round_half_up_cents(Decimal(repr(float(kwh))) * Decimal(12))
        if event_type == "SWAP":
            return 2500 + round_half_up_cents(Decimal(repr(float(kwh))) * Decimal(12))
    else:  # LP
        if event_type == "LP_REFILL":
            return cylinders * 4500 + 1500
    return 0


# ---------------------------------------------------------------------------
# PM-due evaluation (calculation: pm_due_evaluation)
# ---------------------------------------------------------------------------
def recompute_posture(unit, skip_auto_call=False):
    """Recompute maintenance_posture from hour_meter; auto-create PM call on flip."""
    unit["next_pm_due_hours"] = unit["last_pm_hours"] + unit["pm_interval_hours"]
    was = unit["maintenance_posture"]
    if unit["hour_meter"] >= unit["next_pm_due_hours"]:
        if was != "PM_DUE":
            unit["maintenance_posture"] = "PM_DUE"
            if not skip_auto_call:
                create_auto_pm_call(unit, unit.get("_last_pm_trigger_customer_id"))
    else:
        unit["maintenance_posture"] = "PM_OK"


def create_auto_pm_call(unit, customer_id):
    from util import new_record
    rec = new_record()
    rec.update({
        "unit_id": unit["id"],
        "customer_id": customer_id,
        "call_type": "PM",
        "priority": "STANDARD",
        "operator_id": None,
        "technician_id": None,
        "required_parts": [],
        "used_parts": None,
        "scheduled_start": None,
        "scheduled_end": None,
        "auto_created": True,
        "status": "OPEN",
    })
    store.service_calls[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Fleet utilization (calculation: fleet_utilization)
# ---------------------------------------------------------------------------
def compute_utilization_pct_90d(unit):
    now_dt = clock.now()
    clock_date = now_dt.date()
    window_start = clock_date - timedelta(days=90)
    rented_days = 0
    for rc in store.rental_contracts.values():
        if rc["unit_id"] != unit["id"]:
            continue
        if rc["status"] == "RETURNED":
            end_d = min(rc["actual_return_date"], clock_date)
            start_d = max(rc["start_date"], window_start)
            days = (end_d - start_d).days
            rented_days += max(0, days)
        elif rc["status"] == "ON_RENT":
            start_d = max(rc["start_date"], window_start)
            days = (clock_date - start_d).days
            rented_days += max(0, days)
    return round_half_up_1dp(rented_days / 90 * 100)


# ---------------------------------------------------------------------------
# Credit cascade (PRD 2.10)
# ---------------------------------------------------------------------------
def post_charge_to_customer(customer, amount_cents):
    """Post charge to outstanding; flip CREDIT_HOLD on overflow; cascade cancels."""
    customer["outstanding_balance_cents"] = customer.get("outstanding_balance_cents", 0) + amount_cents
    if customer["outstanding_balance_cents"] > customer["credit_limit_cents"]:
        if customer.get("account_status", "ACTIVE") != "CREDIT_HOLD":
            customer["account_status"] = "CREDIT_HOLD"
            # Cancel every RESERVED rental contract and release its hold
            for rc in store.rental_contracts.values():
                if rc["customer_id"] == customer["id"] and rc["status"] == "RESERVED":
                    rc["status"] = "CANCELLED"
                    customer["credit_holds_cents"] = max(
                        0, customer.get("credit_holds_cents", 0) - rc["provisional_estimate_cents"]
                    )
                    bump(rc)


def customer_available_credit(customer):
    return (
        customer["credit_limit_cents"]
        - customer.get("outstanding_balance_cents", 0)
        - customer.get("credit_holds_cents", 0)
    )


# ---------------------------------------------------------------------------
# Lease settlement (calculation: lease_settlement)
# ---------------------------------------------------------------------------
WEAR_TABLE = {"A": 0, "B": 150000, "C": 400000, "D": 900000}
SETTLE_TIER1_THRESHOLD = 200000
SETTLE_TIER1_PCT = Decimal("0.05")
SETTLE_TIER2_THRESHOLD = 500000
SETTLE_TIER2_PCT = Decimal("0.10")


def lease_settlement_total(lease, inspection):
    hours_overage = max(0, inspection["hours_at_return"] - lease["allowed_hours"]) * lease["excess_hour_rate_cents"]
    wear = inspection["wear_charge_cents"]
    residual_shortfall = max(0, lease["residual_value_cents"] - inspection["appraised_value_cents"])
    pre_discount = hours_overage + wear + residual_shortfall
    if pre_discount >= SETTLE_TIER2_THRESHOLD:
        tier_pct = SETTLE_TIER2_PCT
    elif pre_discount >= SETTLE_TIER1_THRESHOLD:
        tier_pct = SETTLE_TIER1_PCT
    else:
        tier_pct = Decimal("0")
    return round_half_up_cents(Decimal(pre_discount) * (Decimal(1) - tier_pct))


# ---------------------------------------------------------------------------
# Certified operator check
# ---------------------------------------------------------------------------
def customer_has_active_certified_operator(customer_id):
    for op in store.operators.values():
        if op["customer_id"] != customer_id:
            continue
        for cert in store.certifications.values():
            if cert["operator_id"] == op["id"] and cert["status"] == "ACTIVE":
                return True
    return False


def operator_has_active_certification(operator_id):
    for cert in store.certifications.values():
        if cert["operator_id"] == operator_id and cert["status"] == "ACTIVE":
            return True
    return False


# ---------------------------------------------------------------------------
# Clock sweeps (PRD 2.9)
# ---------------------------------------------------------------------------
def run_expiry_sweeps():
    now = clock.now()
    for quote in store.quotes.values():
        if quote["status"] == "SUBMITTED" and quote.get("valid_until") is not None:
            if now > quote["valid_until"]:
                quote["status"] = "EXPIRED"
                bump(quote)
    for cert in store.certifications.values():
        if cert["status"] == "ACTIVE" and cert.get("expires_at") is not None:
            if now > cert["expires_at"]:
                cert["status"] = "EXPIRED"
                bump(cert)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
from util import fmt_value


def _fmt(d):
    """Format all datetime/date values in a dict in-place."""
    for k, v in d.items():
        d[k] = fmt_value(v)
    return d


def serialize_customer(c):
    return _fmt({
        "id": c["id"],
        "name": c["name"],
        "credit_limit_cents": c["credit_limit_cents"],
        "discount_pct": c["discount_pct"],
        "outstanding_balance_cents": c["outstanding_balance_cents"],
        "credit_holds_cents": c["credit_holds_cents"],
        "available_credit_cents": customer_available_credit(c),
        "account_status": c["account_status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    })


def serialize_unit(u):
    u["next_pm_due_hours"] = u["last_pm_hours"] + u["pm_interval_hours"]
    return _fmt({
        "id": u["id"],
        "serial_number": u["serial_number"],
        "model": u["model"],
        "power_type": u["power_type"],
        "fuel_program": u["fuel_program"],
        "disposition": u["disposition"],
        "daily_rate_cents": u["daily_rate_cents"],
        "weekly_rate_cents": u["weekly_rate_cents"],
        "monthly_rate_cents": u["monthly_rate_cents"],
        "pm_interval_hours": u["pm_interval_hours"],
        "hour_meter": u["hour_meter"],
        "last_pm_hours": u["last_pm_hours"],
        "next_pm_due_hours": u["next_pm_due_hours"],
        "maintenance_posture": u["maintenance_posture"],
        "availability_status": u["availability_status"],
        "resale_price_cents": u["resale_price_cents"],
        "utilization_pct_90d": compute_utilization_pct_90d(u),
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
    })


def serialize_quote(q):
    return _fmt({
        "id": q["id"],
        "customer_id": q["customer_id"],
        "kind": q["kind"],
        "unit_id": q["unit_id"],
        "valid_until": q["valid_until"],
        "status": q["status"],
        "submitted_at": q["submitted_at"],
        "revision_count": q["revision_count"],
        "subtotal_cents": q["subtotal_cents"],
        "discount_cents": q["discount_cents"],
        "tax_cents": q["tax_cents"],
        "total_cents": q["total_cents"],
        "created_at": q["created_at"],
        "updated_at": q["updated_at"],
        "version": q["version"],
    })


def serialize_quote_line(l):
    return _fmt({
        "id": l["id"],
        "quote_id": l["quote_id"],
        "description": l["description"],
        "qty": l["qty"],
        "unit_price_cents": l["unit_price_cents"],
        "extended_cents": l["extended_cents"],
        "created_at": l["created_at"],
    })


def serialize_rental_contract(rc):
    return _fmt({
        "id": rc["id"],
        "unit_id": rc["unit_id"],
        "customer_id": rc["customer_id"],
        "start_date": rc["start_date"],
        "end_date": rc["end_date"],
        "scheduled_days": rc["scheduled_days"],
        "rate_tier": rc["rate_tier"],
        "provisional_estimate_cents": rc["provisional_estimate_cents"],
        "final_charge_cents": rc["final_charge_cents"],
        "checkout_hours": rc["checkout_hours"],
        "return_hours": rc["return_hours"],
        "actual_return_date": rc["actual_return_date"],
        "status": rc["status"],
        "created_at": rc["created_at"],
        "updated_at": rc["updated_at"],
        "version": rc["version"],
    })


def serialize_meter_reading(m):
    return _fmt({
        "id": m["id"],
        "unit_id": m["unit_id"],
        "reading_hours": m["reading_hours"],
        "note": m["note"],
        "created_at": m["created_at"],
    })


def serialize_fuel_event(f):
    return _fmt({
        "id": f["id"],
        "unit_id": f["unit_id"],
        "event_type": f["event_type"],
        "kwh": f["kwh"],
        "cylinders": f["cylinders"],
        "cost_cents": f["cost_cents"],
        "created_at": f["created_at"],
    })


def serialize_service_call(sc):
    return _fmt({
        "id": sc["id"],
        "unit_id": sc["unit_id"],
        "customer_id": sc["customer_id"],
        "call_type": sc["call_type"],
        "priority": sc["priority"],
        "operator_id": sc["operator_id"],
        "technician_id": sc["technician_id"],
        "required_parts": sc["required_parts"],
        "used_parts": sc["used_parts"],
        "scheduled_start": sc["scheduled_start"],
        "scheduled_end": sc["scheduled_end"],
        "auto_created": sc["auto_created"],
        "status": sc["status"],
        "created_at": sc["created_at"],
        "updated_at": sc["updated_at"],
        "version": sc["version"],
    })


def serialize_technician(t):
    return _fmt({
        "id": t["id"],
        "full_name": t["full_name"],
        "home_branch": t["home_branch"],
        "van_stock": t["van_stock"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    })


def serialize_operator(o):
    return _fmt({
        "id": o["id"],
        "customer_id": o["customer_id"],
        "full_name": o["full_name"],
        "badge_number": o["badge_number"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    })


def serialize_certification(c):
    return _fmt({
        "id": c["id"],
        "operator_id": c["operator_id"],
        "cert_class": c["cert_class"],
        "issued_at": c["issued_at"],
        "expires_at": c["expires_at"],
        "renewed_count": c["renewed_count"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    })


def serialize_lease_contract(lc):
    return _fmt({
        "id": lc["id"],
        "unit_id": lc["unit_id"],
        "customer_id": lc["customer_id"],
        "start_date": lc["start_date"],
        "end_date": lc["end_date"],
        "allowed_hours": lc["allowed_hours"],
        "excess_hour_rate_cents": lc["excess_hour_rate_cents"],
        "residual_value_cents": lc["residual_value_cents"],
        "return_date": lc["return_date"],
        "settlement_total_cents": lc["settlement_total_cents"],
        "status": lc["status"],
        "created_at": lc["created_at"],
        "updated_at": lc["updated_at"],
        "version": lc["version"],
    })


def serialize_lease_inspection(i):
    return _fmt({
        "id": i["id"],
        "lease_id": i["lease_id"],
        "condition_grade": i["condition_grade"],
        "hours_at_return": i["hours_at_return"],
        "appraised_value_cents": i["appraised_value_cents"],
        "wear_charge_cents": i["wear_charge_cents"],
        "status": i["status"],
        "created_at": i["created_at"],
    })


def serialize_reconditioning_order(r):
    return _fmt({
        "id": r["id"],
        "unit_id": r["unit_id"],
        "notes": r["notes"],
        "qc_fail_count": r["qc_fail_count"],
        "listing_price_cents": r["listing_price_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    })
