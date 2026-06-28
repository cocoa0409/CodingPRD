"""Entity assertions and domain invariant checkers for the Musical Instrument Store."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version (entities that carry the full set)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _assert_append_only(data: dict):
    """Append-only ledger event: id + created_at only, NO updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["credit_score"], int)
    assert 300 <= data["credit_score"] <= 850, "credit_score must be in [300, 850]"
    assert isinstance(data["store_credit_cents"], int)
    assert data["store_credit_cents"] >= 0, "store_credit_cents is floored at 0"


def assert_inventory_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["model_name"], str) and len(data["model_name"]) > 0
    assert data["category"] in ["BAND", "ORCHESTRA", "GUITAR", "KEYBOARD", "OTHER"]
    assert data["condition"] in ["NEW", "USED", "VINTAGE"]
    assert isinstance(data["serial_number"], str) and len(data["serial_number"]) > 0
    assert data["acquisition_cost_cents"] >= 0
    assert data["list_price_cents"] >= 0
    assert data["monthly_rent_cents"] >= 0
    assert data["status"] in [
        "AVAILABLE", "RESERVED", "ON_RENT", "ON_LAYAWAY",
        "SOLD", "IN_REPAIR", "CONSIGNED", "RETIRED",
    ]
    assert data["source_kind"] in ["STORE_PURCHASE", "TRADE_IN", "CONSIGNMENT"]


def assert_rental_agreement(data: dict):
    _assert_common(data)
    assert data["plan"] in ["RENTAL", "RENT_TO_OWN"]
    assert data["status"] in ["ACTIVE", "BOUGHT_OUT", "RETURNED", "DEFAULTED", "REPOSSESSED"]
    assert isinstance(data["monthly_rate_cents"], int)
    assert isinstance(data["purchase_price_cents"], int)
    assert isinstance(data["months_paid"], int) and data["months_paid"] >= 0
    assert isinstance(data["accrued_equity_cents"], int) and data["accrued_equity_cents"] >= 0
    assert isinstance(data["late_fee_balance_cents"], int) and data["late_fee_balance_cents"] >= 0
    assert isinstance(data["missed_streak"], int) and data["missed_streak"] >= 0


def assert_payment_record(data: dict):
    _assert_append_only(data)
    assert data["kind"] in ["RENT", "LATE_FEE", "BUYOUT", "REFUND"]
    assert data["status"] in ["POSTED", "WAIVED"]
    assert isinstance(data["amount_cents"], int)


def assert_layaway_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "COMPLETED", "CANCELLED"]
    assert isinstance(data["total_price_cents"], int)
    assert isinstance(data["paid_cents"], int) and data["paid_cents"] >= 0
    assert isinstance(data["remaining_cents"], int) and data["remaining_cents"] >= 0


def assert_layaway_payment(data: dict):
    _assert_append_only(data)
    assert isinstance(data["amount_cents"], int)


def assert_repair_ticket(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "INTAKE", "IN_PROGRESS", "AWAITING_PARTS", "READY", "CLOSED", "CANCELLED",
    ]
    assert isinstance(data["quoted_total_cents"], int) and data["quoted_total_cents"] >= 0


def assert_consignment_listing(data: dict):
    _assert_common(data)
    assert data["status"] in ["LISTED", "SOLD", "WITHDRAWN"]
    assert isinstance(data["ask_price_cents"], int) and data["ask_price_cents"] > 0
    assert isinstance(data["consignor_payout_cents"], int) and data["consignor_payout_cents"] >= 0


def assert_trade_in(data: dict):
    _assert_common(data)
    assert data["status"] in ["OFFERED", "ACCEPTED", "DECLINED"]
    assert data["condition"] in ["NEW", "USED", "VINTAGE"]
    assert isinstance(data["offer_cents"], int) and data["offer_cents"] >= 0


def assert_financing_application(data: dict):
    _assert_common(data)
    assert data["status"] in ["SUBMITTED", "APPROVED", "DENIED", "CANCELLED"]
    assert isinstance(data["principal_cents"], int) and data["principal_cents"] > 0
    assert data["term_months"] in [6, 12, 24, 36]


def assert_special_order(data: dict):
    _assert_common(data)
    assert data["status"] in ["QUOTED", "DEPOSITED", "ORDERED", "ARRIVED", "FULFILLED", "CANCELLED"]
    assert isinstance(data["quoted_price_cents"], int) and data["quoted_price_cents"] > 0
    assert isinstance(data["required_deposit_cents"], int) and data["required_deposit_cents"] >= 0
    assert isinstance(data["deposit_paid_cents"], int) and data["deposit_paid_cents"] >= 0


def assert_lesson_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "PAUSED", "ENDED"]
    assert data["instrument_family"] in ["BAND", "ORCHESTRA", "GUITAR", "KEYBOARD", "OTHER"]
    assert isinstance(data["sessions_per_month"], int) and data["sessions_per_month"] > 0
    assert isinstance(data["monthly_tuition_cents"], int) and data["monthly_tuition_cents"] >= 0
