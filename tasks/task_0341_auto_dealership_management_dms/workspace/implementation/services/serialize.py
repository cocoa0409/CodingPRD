"""Output serialization for each entity. Computed/back-link fields are derived
fresh so reads always reflect the current state.
"""
import db
from services import calc

VEHICLE_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "vin", "condition", "make", "model", "model_year",
    "msrp_cents", "list_price_cents", "status",
    "acquired_from_trade_in_id", "active_floor_plan_line_id",
]

FLOOR_PLAN_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "vehicle_id", "lender_name", "principal_cents", "annual_rate_bps",
    "floored_on", "principal_outstanding_cents", "curtailments_applied", "status",
]

CUSTOMER_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "full_name", "email", "monthly_income_cents", "credit_tier", "drivers_license_valid",
]

TRADEIN_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "deal_id", "vin", "acv_cents", "allowance_cents", "payoff_cents",
    "gross_equity_cents", "status", "acquired_vehicle_id",
]

DEAL_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "vehicle_id", "customer_id", "deal_type", "sale_price_cents", "accessories_cents",
    "doc_fee_cents", "title_fee_cents", "registration_fee_cents", "tax_rate_bps",
    "cash_down_cents", "applied_incentive_id", "rebate_cents", "trade_allowance_cents",
    "trade_equity_cents", "total_tax_cents", "fi_products_total_cents",
    "amount_financed_cents", "front_gross_cents", "back_gross_cents",
    "estimated_payment_cents", "status", "approved_lender_program_id",
]

LENDER_PROGRAM_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "lender_name", "tier", "buy_rate_bps", "max_markup_bps", "max_ltv_bps",
    "max_pti_bps", "max_term_months", "active",
]

FINANCE_PRODUCT_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "code", "name", "cost_cents", "max_retail_cents", "taxable",
]

DEAL_PRODUCT_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "deal_id", "finance_product_id", "sold_price_cents", "product_cost_cents", "status",
]

FINANCE_CONTRACT_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "deal_id", "lender_program_id", "markup_bps", "term_months", "sell_rate_bps",
    "amount_financed_snapshot_cents", "monthly_payment_cents", "finance_reserve_cents", "status",
]

OEM_INCENTIVE_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "program_code", "rebate_cents", "eligible_condition", "eligible_make",
    "min_model_year", "stackable_with_finance", "active",
]

TEST_DRIVE_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "vehicle_id", "customer_id", "start_at", "end_at", "status",
]

REPAIR_ORDER_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "vehicle_id", "deal_id", "ro_type", "bay", "scheduled_start_at", "scheduled_end_at",
    "parts_cents", "labor_cents", "total_cents", "status",
]

TITLE_REG_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "deal_id", "owner_name", "plate_type", "rejection_reason", "resubmit_count", "status",
]

DOCUMENT_FIELDS = ["id", "created_at", "deal_id", "doc_type", "uri"]


def _pick(record, fields):
    return {f: record.get(f) for f in fields}


def vehicle(rec):
    out = _pick(rec, VEHICLE_FIELDS)
    line = calc.active_floor_plan_line(rec["id"])
    out["active_floor_plan_line_id"] = line["id"] if line else None
    return out


def floor_plan_line(rec):
    return _pick(rec, FLOOR_PLAN_FIELDS)


def customer(rec):
    return _pick(rec, CUSTOMER_FIELDS)


def trade_in(rec):
    return _pick(rec, TRADEIN_FIELDS)


def deal(rec):
    return _pick(rec, DEAL_FIELDS)


def lender_program(rec):
    return _pick(rec, LENDER_PROGRAM_FIELDS)


def finance_product(rec):
    return _pick(rec, FINANCE_PRODUCT_FIELDS)


def deal_product(rec):
    return _pick(rec, DEAL_PRODUCT_FIELDS)


def finance_contract(rec):
    return _pick(rec, FINANCE_CONTRACT_FIELDS)


def oem_incentive(rec):
    return _pick(rec, OEM_INCENTIVE_FIELDS)


def test_drive(rec):
    return _pick(rec, TEST_DRIVE_FIELDS)


def repair_order(rec):
    return _pick(rec, REPAIR_ORDER_FIELDS)


def title_registration(rec):
    return _pick(rec, TITLE_REG_FIELDS)


def document(rec):
    return _pick(rec, DOCUMENT_FIELDS)
