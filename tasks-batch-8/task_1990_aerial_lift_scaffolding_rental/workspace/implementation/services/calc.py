"""Calculation rules: billable days, best-rate segment charge, standby/labor,
damage chargeback, recovery credit, contract totals, customer balance.

All monetary values are integer cents. Percentage computations use Decimal with
ROUND_HALF_UP and are rounded per component at computation time; aggregates sum
stored integers and are never re-rounded.
"""
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
from db import store

US_PER_DAY = 86400 * 1_000_000
FREE_STANDBY_MINUTES = 30
STANDBY_RATE_CENTS_PER_MINUTE = 250
LABOR_RATE_CENTS_PER_HOUR = 9500
WAIVER_LIABILITY_PCT = Decimal("0.10")
RECOVERY_CREDIT_PCT = Decimal("0.80")
TRIP_FEE_CENTS = 15000
DAYS_PER_WEEK = 7
DAYS_PER_MONTH = 28


def _ceil_div(a, b):
    return -(-a // b)


def billable_days(start_dt, end_dt, min_rental_days):
    """ceil((end - start) / 86400s), floored at the class minimum."""
    delta = end_dt - start_dt
    us = delta.days * US_PER_DAY + delta.seconds * 1_000_000 + delta.microseconds
    raw = _ceil_div(us, US_PER_DAY)
    return max(min_rental_days, raw)


def best_rate_cents(cls, days):
    """Lowest of the three rate applications over the billable day count."""
    daily = cls["daily_rate_cents"] * days
    weekly = cls["weekly_rate_cents"] * _ceil_div(days, DAYS_PER_WEEK)
    monthly = cls["monthly_rate_cents"] * _ceil_div(days, DAYS_PER_MONTH)
    return min(daily, weekly, monthly)


def _midnight_utc(d):
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def segment_charge_cents(cls, start_dt, end_dt):
    return best_rate_cents(cls, billable_days(start_dt, end_dt, cls["min_rental_days"]))


def provisional_charge_cents(line):
    """Status-dependent forward-looking quote for a RentalLine."""
    st = line["status"]
    if st == "CANCELLED":
        return 0
    if st == "RETURNED":
        return line["final_charge_cents"] or 0
    if st == "OFF_RENT":
        return line["accrued_charge_cents"]
    cls = store.classes[line["class_id"]]
    if st == "RESERVED":
        start = _midnight_utc(db.parse_date(line["requested_start_date"]))
        end = _midnight_utc(db.parse_date(line["requested_end_date"]) + timedelta(days=1))
        return segment_charge_cents(cls, start, end)
    # OUT_ON_RENT: projected segment on_rent_at -> max(clock, requested_end + 1 day)
    start = db.parse_datetime(line["on_rent_at"])
    req_end = _midnight_utc(db.parse_date(line["requested_end_date"]) + timedelta(days=1))
    end = max(db.LOGICAL_CLOCK, req_end)
    return line["accrued_charge_cents"] + segment_charge_cents(cls, start, end)


def standby_charge_cents(standby_minutes):
    return max(0, standby_minutes - FREE_STANDBY_MINUTES) * STANDBY_RATE_CENTS_PER_MINUTE


def labor_charge_cents(category, crew_labor_hours):
    if category == "SCAFFOLD":
        cents = Decimal(str(crew_labor_hours)) * LABOR_RATE_CENTS_PER_HOUR
        return int(cents.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return 0


def damage_chargeback_cents(claim, contract, cls):
    if claim["claim_type"] == "DAMAGE":
        base = claim["repair_estimate_cents"]
        if contract["damage_waiver_elected"]:
            cents = Decimal(base) * WAIVER_LIABILITY_PCT
            return int(cents.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return base
    # LOST | STOLEN — damage waiver never applies
    return cls["replacement_value_cents"]


def recovery_credit_cents(chargeback_cents):
    cents = Decimal(chargeback_cents) * RECOVERY_CREDIT_PCT
    return int(cents.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rental_subtotal_cents(contract_id):
    total = 0
    for line in store.lines.values():
        if line["contract_id"] != contract_id:
            continue
        st = line["status"]
        if st == "RETURNED":
            total += line["final_charge_cents"] or 0
        elif st == "OFF_RENT":
            total += line["accrued_charge_cents"]
        elif st in ("RESERVED", "OUT_ON_RENT"):
            total += provisional_charge_cents(line)
        # CANCELLED contributes 0
    return total


def logistics_subtotal_cents(contract_id):
    total = 0
    for trip in store.trips.values():
        if trip["contract_id"] == contract_id and trip["status"] == "COMPLETED":
            total += (trip["trip_fee_cents"] + trip["standby_charge_cents"]
                      + trip["labor_charge_cents"])
    return total


def damage_subtotal_cents(contract_id):
    total = 0
    for claim in store.claims.values():
        if claim["contract_id"] == contract_id and claim["status"] == "CHARGED":
            total += claim["chargeback_cents"] or 0
            total -= claim["recovery_credit_cents"] or 0
    return total


def invoice_total_cents(contract_id):
    return (rental_subtotal_cents(contract_id)
            + logistics_subtotal_cents(contract_id)
            + damage_subtotal_cents(contract_id))


def customer_balance_cents(customer_id):
    """Sum of invoice totals over the customer's ACTIVE contracts only."""
    total = 0
    for c in store.contracts.values():
        if c["customer_id"] == customer_id and c["status"] == "ACTIVE":
            total += invoice_total_cents(c["id"])
    return total


def maybe_suspend(customer):
    """ACTIVE -> SUSPENDED cascade when the recomputed balance exceeds the limit."""
    if (customer["status"] == "ACTIVE"
            and customer_balance_cents(customer["id"]) > customer["credit_limit_cents"]):
        customer["status"] = "SUSPENDED"
        db.touch(customer)
