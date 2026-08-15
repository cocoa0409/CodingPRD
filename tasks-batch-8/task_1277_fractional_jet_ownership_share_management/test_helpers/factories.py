"""Payload factories — one per creatable entity, input fields only."""

DEFAULTS = {
    "PROGRAM_CODE": "FJX-TST",
    "CURRENCY": "USD",
    "CONTRACT_YEAR_START_MONTH": 8,
    "HOURLY_RATE_CENTS": 450000,
    "MULTIPLIER_BP": 12500,
    "MONTHLY_FEE_BASE_CENTS": 2500000,
    "SEATS": 8,
    "TAIL_NUMBER": "N100TS",
    "LEGAL_NAME": "Test Owner LLC",
    "INITIAL_DEPOSIT_CENTS": 0,
    "FRACTION_NUMERATOR": 1,
    "FRACTION_DENOMINATOR": 8,
    "PURCHASE_PRICE_CENTS": 12000000,
    "SCHEDULE_METHOD": "STRAIGHT_LINE",
    "RECOVERY_YEARS": 5,
    "ESTIMATED_BLOCK_HOURS": 1.00,
    "ASKING_PRICE_CENTS": 10000000,
}


def create_program_payload(**overrides) -> dict:
    defaults = {
        "program_code": DEFAULTS["PROGRAM_CODE"],
        "currency": DEFAULTS["CURRENCY"],
        "contract_year_start_month": DEFAULTS["CONTRACT_YEAR_START_MONTH"],
        "peak_day_calendar": [],
    }
    defaults.update(overrides)
    return defaults


def create_aircraft_class_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "class_code": "MID",
        "hourly_rate_cents": DEFAULTS["HOURLY_RATE_CENTS"],
        "interchange_upgrade_multiplier_bp": DEFAULTS["MULTIPLIER_BP"],
        "monthly_fee_base_cents": DEFAULTS["MONTHLY_FEE_BASE_CENTS"],
        "seats": DEFAULTS["SEATS"],
    }
    defaults.update(overrides)
    return defaults


def create_aircraft_payload(program_id, class_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "tail_number": DEFAULTS["TAIL_NUMBER"],
        "class_id": class_id,
    }
    defaults.update(overrides)
    return defaults


def create_owner_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "initial_deposit_cents": DEFAULTS["INITIAL_DEPOSIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_share_payload(owner_id, class_id, **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "class_id": class_id,
        "fraction_numerator": DEFAULTS["FRACTION_NUMERATOR"],
        "fraction_denominator": DEFAULTS["FRACTION_DENOMINATOR"],
        "purchase_price_cents": DEFAULTS["PURCHASE_PRICE_CENTS"],
        "schedule_method": DEFAULTS["SCHEDULE_METHOD"],
        "recovery_years": DEFAULTS["RECOVERY_YEARS"],
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(share_id, requested_class_id, expected_share_version, **overrides) -> dict:
    defaults = {
        "share_id": share_id,
        "requested_class_id": requested_class_id,
        "scheduled_departure_utc": "2026-09-10T15:00:00Z",
        "estimated_block_hours": DEFAULTS["ESTIMATED_BLOCK_HOURS"],
        "expected_share_version": expected_share_version,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(owner_id, billing_period, **overrides) -> dict:
    defaults = {"owner_id": owner_id, "billing_period": billing_period}
    defaults.update(overrides)
    return defaults


def create_transfer_listing_payload(share_id, expected_share_version, **overrides) -> dict:
    defaults = {
        "share_id": share_id,
        "asking_price_cents": DEFAULTS["ASKING_PRICE_CENTS"],
        "program_repurchase_flag": False,
        "expected_share_version": expected_share_version,
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_event_payload(aircraft_id, **overrides) -> dict:
    defaults = {
        "aircraft_id": aircraft_id,
        "window_start_utc": "2026-09-10T00:00:00Z",
        "window_end_utc": "2026-09-11T00:00:00Z",
        "cost_cents": 0,
        "unscheduled_flag": False,
    }
    defaults.update(overrides)
    return defaults
