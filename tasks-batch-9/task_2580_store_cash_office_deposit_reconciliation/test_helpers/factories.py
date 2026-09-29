"""Payload factories — one per record type, input fields only."""

import itertools

_STORE_CODE_SEQ = itertools.count(1)
_SAFE_CODE_SEQ = itertools.count(1)
_EMPLOYEE_CODE_SEQ = itertools.count(1)
_SEAL_SEQ = itertools.count(1)
_BANK_REF_SEQ = itertools.count(1)

DEFAULTS = {
    "REGION_CODE": "NORTH",
    "BUSINESS_DATE": "2026-08-03",
    "TARGET_WEEK_START": "2026-08-10",
    "OPENING_BALANCE_CENTS": 500000,
    "STARTING_BANK_CENTS": 20000,
    "BASELINE_DAILY_CASH_DEMAND_CENTS": 400000,
}


def unique_store_code() -> str:
    return f"S-{2000 + next(_STORE_CODE_SEQ)}"


def unique_safe_code() -> str:
    return f"SAFE-{next(_SAFE_CODE_SEQ)}"


def unique_employee_code() -> str:
    return f"E-{100 + next(_EMPLOYEE_CODE_SEQ)}"


def unique_seal_number() -> str:
    return f"SEAL-{next(_SEAL_SEQ):05d}"


def unique_bank_reference() -> str:
    return f"BREF-{next(_BANK_REF_SEQ):05d}"


def store_payload(**overrides) -> dict:
    """Registering a store requires store_code, name and region_code; every
    remaining parameter is optional and takes a chain default when omitted."""
    code = overrides.pop("store_code", None) or unique_store_code()
    payload = {
        "store_code": code,
        "name": f"Store {code}",
        "region_code": DEFAULTS["REGION_CODE"],
    }
    payload.update(overrides)
    return payload


def cashier_payload(store_id: str, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "employee_code": unique_employee_code(),
        "display_name": "Test Cashier",
    }
    payload.update(overrides)
    return payload


def safe_payload(store_id: str, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "safe_code": unique_safe_code(),
        "safe_type": "MANUAL",
        "opening_balance_cents": DEFAULTS["OPENING_BALANCE_CENTS"],
    }
    payload.update(overrides)
    return payload


def sales_journal_payload(store_id: str, **overrides) -> dict:
    payload = {"store_id": store_id, "business_date": DEFAULTS["BUSINESS_DATE"]}
    payload.update(overrides)
    return payload


def post_tenders_payload(cash_cents: int, card_cents: int, **overrides) -> dict:
    payload = {
        "journal_cash_sales_cents": cash_cents,
        "journal_card_sales_cents": card_cents,
    }
    payload.update(overrides)
    return payload


def till_session_payload(
    sales_journal_id: str, cashier_id: str, safe_id: str, **overrides
) -> dict:
    payload = {
        "sales_journal_id": sales_journal_id,
        "cashier_id": cashier_id,
        "safe_id": safe_id,
        "register_number": 1,
        "shift_start_at": "2026-08-03T09:00:00Z",
        "shift_end_at": "2026-08-03T17:00:00Z",
        "starting_bank_cents": DEFAULTS["STARTING_BANK_CENTS"],
    }
    payload.update(overrides)
    return payload


def drop_payload(declared_amount_cents: int, **overrides) -> dict:
    payload = {
        "txn_type": "CLOSING_DROP",
        "declared_amount_cents": declared_amount_cents,
    }
    payload.update(overrides)
    return payload


def close_payload(pos_cash_sales_cents=None, pos_card_sales_cents=None, **overrides):
    """Closing a till session requires pos_cash_sales_cents and
    pos_card_sales_cents unless forced_close is true."""
    payload = {}
    if pos_cash_sales_cents is not None:
        payload["pos_cash_sales_cents"] = pos_cash_sales_cents
    if pos_card_sales_cents is not None:
        payload["pos_card_sales_cents"] = pos_card_sales_cents
    payload.update(overrides)
    return payload


def blind_count_payload(counted_lines, **overrides) -> dict:
    payload = {"counted_lines": list(counted_lines)}
    payload.update(overrides)
    return payload


def deposit_payload(
    safe_id: str,
    sales_journal_id: str,
    counted_lines,
    expected_safe_version: int,
    **overrides,
) -> dict:
    payload = {
        "safe_id": safe_id,
        "sales_journal_id": sales_journal_id,
        "business_date": DEFAULTS["BUSINESS_DATE"],
        "counted_lines": list(counted_lines),
        "expected_safe_version": expected_safe_version,
    }
    payload.update(overrides)
    return payload


def smart_deposit_payload(sales_journal_id: str, counted_lines, **overrides) -> dict:
    payload = {
        "sales_journal_id": sales_journal_id,
        "business_date": DEFAULTS["BUSINESS_DATE"],
        "counted_lines": list(counted_lines),
    }
    payload.update(overrides)
    return payload


def seal_payload(**overrides) -> dict:
    payload = {"seal_number": unique_seal_number()}
    payload.update(overrides)
    return payload


def schedule_pickup_payload(window_start: str, window_end: str, **overrides) -> dict:
    payload = {
        "pickup_window_start": window_start,
        "pickup_window_end": window_end,
        "carrier_reference": "CR-0001",
    }
    payload.update(overrides)
    return payload


def pickup_payload(picked_up_at: str, **overrides) -> dict:
    payload = {"picked_up_at": picked_up_at, "carrier_signature": "J. CARRIER"}
    payload.update(overrides)
    return payload


def bank_credit_record_payload(store_id: str, amount_cents: int, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "credit_type": "FINAL",
        "amount_cents": amount_cents,
        "value_date": DEFAULTS["BUSINESS_DATE"],
        "bank_reference": unique_bank_reference(),
    }
    payload.update(overrides)
    return payload


def card_settlement_payload(
    sales_journal_id: str,
    gross_card_sales_cents: int,
    txn_count: int,
    monthly_volume_cents: int,
    funded_amount_cents: int,
    **overrides,
) -> dict:
    payload = {
        "sales_journal_id": sales_journal_id,
        "card_network": "VISA_MC",
        "gross_card_sales_cents": gross_card_sales_cents,
        "txn_count": txn_count,
        "monthly_volume_cents": monthly_volume_cents,
        "funded_amount_cents": funded_amount_cents,
    }
    payload.update(overrides)
    return payload


def attribution_payload(
    bucket: str, amount_cents: int, expected_variance_case_version: int, **overrides
) -> dict:
    payload = {
        "bucket": bucket,
        "amount_cents": amount_cents,
        "note": "Research note",
        "expected_variance_case_version": expected_variance_case_version,
    }
    payload.update(overrides)
    return payload


def change_order_payload(store_id: str, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "target_week_start": DEFAULTS["TARGET_WEEK_START"],
        "days_covered": 7,
        "baseline_daily_cash_demand_cents": DEFAULTS[
            "BASELINE_DAILY_CASH_DEMAND_CENTS"
        ],
    }
    payload.update(overrides)
    return payload


def lines(*pairs) -> list:
    """Build denomination lines from (denomination_cents, quantity) pairs."""
    return [
        {"denomination_cents": denom, "quantity": qty} for denom, qty in pairs
    ]
