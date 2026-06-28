"""Entity creation, mutation (version/timestamp bump), derived-figure recompute,
and serialization helpers.

All entities are plain dicts stored in db. System-managed common fields:
id, created_at, updated_at, version. PaymentRecord and LayawayPayment are
append-only (id + created_at only).
"""

import calc
from db import db


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------

def new_common(extra=None):
    """Create the system common fields for a full entity (id/created/updated/version)."""
    ts = db.stamp()
    record = {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),  # internal tiebreaker, not serialized
    }
    if extra:
        record.update(extra)
    return record


def touch(record):
    """Bump version + updated_at on a mutation (including cascades)."""
    record["version"] += 1
    record["updated_at"] = db.stamp()


# ---------------------------------------------------------------------------
# Agreement derived figures
# ---------------------------------------------------------------------------

def agreement_payments(agreement_id):
    rows = [p for p in db.payment_records.values() if p["agreement_id"] == agreement_id]
    rows.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return rows


def compute_months_paid(agreement_id):
    return sum(
        1 for p in db.payment_records.values()
        if p["agreement_id"] == agreement_id and p["kind"] == "RENT" and p["status"] == "POSTED"
    )


def compute_late_fee_balance(agreement_id):
    posted = sum(
        p["amount_cents"] for p in db.payment_records.values()
        if p["agreement_id"] == agreement_id and p["kind"] == "LATE_FEE" and p["status"] == "POSTED"
    )
    waived = sum(
        p["amount_cents"] for p in db.payment_records.values()
        if p["agreement_id"] == agreement_id and p["kind"] == "LATE_FEE" and p["status"] == "WAIVED"
    )
    return max(0, posted - waived)


def recompute_agreement(agr):
    """Recompute the live derived figures stored on the agreement record."""
    months_paid = compute_months_paid(agr["id"])
    late_fee_balance = compute_late_fee_balance(agr["id"])
    accrued = calc.equity_accrual(
        months_paid,
        agr["monthly_rate_cents"],
        agr["equity_rate_pct"],
        agr["purchase_price_cents"],
        agr["equity_cap_pct"],
        agr["plan"],
    )
    payoff = calc.buyout_payoff(agr["purchase_price_cents"], accrued, late_fee_balance)
    agr["months_paid"] = months_paid
    agr["late_fee_balance_cents"] = late_fee_balance
    agr["accrued_equity_cents"] = accrued
    agr["payoff_quote_cents"] = payoff
    return agr


# ---------------------------------------------------------------------------
# Layaway derived figures
# ---------------------------------------------------------------------------

def recompute_layaway(plan):
    installments = [
        p["amount_cents"] for p in db.layaway_payments.values()
        if p["layaway_plan_id"] == plan["id"]
    ]
    paid = calc.layaway_paid(plan["deposit_cents"], installments)
    plan["paid_cents"] = paid
    plan["remaining_cents"] = calc.layaway_remaining(plan["total_price_cents"], paid)
    return plan


# ---------------------------------------------------------------------------
# Customer store credit cascade
# ---------------------------------------------------------------------------

def credit_customer(customer_id, amount_cents):
    cust = db.customers[customer_id]
    cust["store_credit_cents"] = max(0, cust["store_credit_cents"] + amount_cents)
    touch(cust)


# ---------------------------------------------------------------------------
# Inventory unit mint / cascade helpers
# ---------------------------------------------------------------------------

def mint_unit(model_name, category, condition, serial_number, acquisition_cost_cents,
              list_price_cents, monthly_rent_cents, status, source_kind,
              consignment_listing_id=None, reserved_for_customer_id=None):
    unit = new_common({
        "model_name": model_name,
        "category": category,
        "condition": condition,
        "serial_number": serial_number,
        "acquisition_cost_cents": acquisition_cost_cents,
        "list_price_cents": list_price_cents,
        "monthly_rent_cents": monthly_rent_cents,
        "status": status,
        "source_kind": source_kind,
        "consignment_listing_id": consignment_listing_id,
        "reserved_for_customer_id": reserved_for_customer_id,
    })
    db.units[unit["id"]] = unit
    return unit


# ---------------------------------------------------------------------------
# Serialization (strip internal fields)
# ---------------------------------------------------------------------------

_UNIT_PUBLIC = [
    "id", "model_name", "category", "condition", "serial_number",
    "acquisition_cost_cents", "list_price_cents", "monthly_rent_cents",
    "status", "source_kind", "consignment_listing_id",
    "created_at", "updated_at", "version",
]

_CUSTOMER_PUBLIC = [
    "id", "full_name", "email", "credit_score", "store_credit_cents",
    "created_at", "updated_at", "version",
]

_AGREEMENT_PUBLIC = [
    "id", "customer_id", "inventory_unit_id", "plan", "monthly_rate_cents",
    "purchase_price_cents", "equity_rate_pct", "equity_cap_pct", "months_paid",
    "accrued_equity_cents", "payoff_quote_cents", "late_fee_balance_cents",
    "missed_streak", "status", "created_at", "updated_at", "version",
]

_PAYMENT_PUBLIC = [
    "id", "agreement_id", "kind", "amount_cents", "billing_cycle_index",
    "status", "created_at",
]

_LAYAWAY_PUBLIC = [
    "id", "customer_id", "inventory_unit_id", "total_price_cents", "deposit_cents",
    "paid_cents", "remaining_cents", "restock_fee_pct", "status",
    "created_at", "updated_at", "version",
]

_LAYAWAY_PAYMENT_PUBLIC = [
    "id", "layaway_plan_id", "amount_cents", "created_at",
]

_REPAIR_PUBLIC = [
    "id", "customer_id", "inventory_unit_id", "assigned_luthier_id", "labor_hours",
    "labor_rate_cents", "parts_cost_cents", "rush", "quoted_total_cents", "status",
    "created_at", "updated_at", "version",
]

_CONSIGNMENT_PUBLIC = [
    "id", "consignor_id", "model_name", "ask_price_cents", "commission_pct",
    "consignor_payout_cents", "status", "created_at", "updated_at", "version",
]

_TRADEIN_PUBLIC = [
    "id", "customer_id", "model_name", "condition", "appraised_value_cents",
    "offer_cents", "resulting_unit_id", "status", "created_at", "updated_at", "version",
]

_FINANCING_PUBLIC = [
    "id", "customer_id", "special_order_id", "principal_cents", "term_months",
    "apr_pct", "monthly_payment_cents", "status", "created_at", "updated_at", "version",
]

_SPECIAL_ORDER_PUBLIC = [
    "id", "customer_id", "model_name", "quoted_price_cents", "deposit_pct",
    "required_deposit_cents", "deposit_paid_cents", "fulfilled_unit_id", "status",
    "created_at", "updated_at", "version",
]

_LESSON_PUBLIC = [
    "id", "student_id", "rental_agreement_id", "instrument_family",
    "sessions_per_month", "base_rate_cents", "monthly_tuition_cents", "status",
    "created_at", "updated_at", "version",
]


def _project(record, fields):
    return {k: record.get(k) for k in fields}


def ser_customer(r):
    return _project(r, _CUSTOMER_PUBLIC)


def ser_unit(r):
    return _project(r, _UNIT_PUBLIC)


def ser_agreement(r):
    return _project(r, _AGREEMENT_PUBLIC)


def ser_payment(r):
    return _project(r, _PAYMENT_PUBLIC)


def ser_layaway(r):
    return _project(r, _LAYAWAY_PUBLIC)


def ser_layaway_payment(r):
    return _project(r, _LAYAWAY_PAYMENT_PUBLIC)


def ser_repair(r):
    return _project(r, _REPAIR_PUBLIC)


def ser_consignment(r):
    return _project(r, _CONSIGNMENT_PUBLIC)


def ser_tradein(r):
    return _project(r, _TRADEIN_PUBLIC)


def ser_financing(r):
    return _project(r, _FINANCING_PUBLIC)


def ser_special_order(r):
    return _project(r, _SPECIAL_ORDER_PUBLIC)


def ser_lesson(r):
    return _project(r, _LESSON_PUBLIC)
