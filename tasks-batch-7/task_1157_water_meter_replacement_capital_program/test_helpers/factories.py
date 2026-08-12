"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1000)


def _n() -> int:
    return next(_counter)


def create_program_payload(**overrides) -> dict:
    defaults = {
        "name": f"{TEST_DEFAULTS['PROGRAM_NAME']}-{_n()}",
        "fiscal_year": TEST_DEFAULTS["FISCAL_YEAR"],
        "budget_total_cents": TEST_DEFAULTS["BUDGET_TOTAL_CENTS"],
        "target_meter_count": TEST_DEFAULTS["TARGET_METER_COUNT"],
        "rate_per_ccf_cents": TEST_DEFAULTS["RATE_PER_CCF_CENTS"],
        "default_unit_allowance_cents": TEST_DEFAULTS["DEFAULT_UNIT_ALLOWANCE_CENTS"],
        "notice_days": TEST_DEFAULTS["NOTICE_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_contractor_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "name": f"{TEST_DEFAULTS['CONTRACTOR_NAME']}-{_n()}",
        "crew_capacity_per_window": TEST_DEFAULTS["CREW_CAPACITY_PER_WINDOW"],
        "unit_price_cents": TEST_DEFAULTS["UNIT_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "account_number": f"A-{n}",
        "service_address": f"{n} Test Way",
        "meter_location": "OUTSIDE",
        "customer_name": f"Customer-{n}",
        "customer_phone": f"555-{n % 10000:04d}",
        "avg_daily_usage_ccf": TEST_DEFAULTS["AVG_DAILY_USAGE_CCF"],
        "last_billed_read_value": TEST_DEFAULTS["LAST_BILLED_READ_VALUE"],
        "last_billed_read_at": TEST_DEFAULTS["LAST_BILLED_READ_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_meter_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "serial_number": f"M-{n}",
        "size_code": "S_5_8",
        "technology": "LEGACY",
    }
    defaults.update(overrides)
    return defaults


def create_wave_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "wave_number": 1,
        "window_start": TEST_DEFAULTS["WAVE1_WINDOW_START"],
        "window_end": TEST_DEFAULTS["WAVE1_WINDOW_END"],
        "capacity": TEST_DEFAULTS["WAVE_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(wave_id, service_account_id, **overrides) -> dict:
    payload = {"wave_id": wave_id, "service_account_id": service_account_id}
    payload.update(overrides)
    return payload


def create_notification_payload(work_order_id, **overrides) -> dict:
    payload = {"work_order_id": work_order_id, "channel": "USPS_MAIL"}
    payload.update(overrides)
    return payload


def confirm_delivery_payload(**overrides) -> dict:
    payload = {"outcome": "DELIVERED", "delivered_at": TEST_DEFAULTS["DELIVERED_AT"]}
    payload.update(overrides)
    return payload


def create_appointment_payload(work_order_id, expected_work_order_version, **overrides) -> dict:
    payload = {
        "work_order_id": work_order_id,
        "slot_date": TEST_DEFAULTS["SLOT_DATE"],
        "window": "AM",
        "expected_work_order_version": expected_work_order_version,
    }
    payload.update(overrides)
    return payload


def create_reading_payload(work_order_id, meter_id, **overrides) -> dict:
    payload = {
        "work_order_id": work_order_id,
        "meter_id": meter_id,
        "read_type": "FINAL",
        "value": TEST_DEFAULTS["SWAP_FINAL_READ"],
        "source": "FIELD_CREW",
        "read_at": TEST_DEFAULTS["READ_AT"],
    }
    payload.update(overrides)
    return payload


def create_endpoint_registration_payload(work_order_id, **overrides) -> dict:
    payload = {
        "work_order_id": work_order_id,
        "endpoint_serial": f"EP-{_n()}",
    }
    payload.update(overrides)
    return payload


def ingest_read_payload(endpoint_registration_id, **overrides) -> dict:
    payload = {
        "endpoint_registration_id": endpoint_registration_id,
        "rssi_dbm": -90,
        "read_at": "2026-05-06T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_bench_test_payload(meter_id, **overrides) -> dict:
    payload = {
        "meter_id": meter_id,
        "measured_low_ccf": 1.96,
        "measured_mid_ccf": 19.90,
        "measured_high_ccf": 29.90,
    }
    payload.update(overrides)
    return payload


def create_complaint_payload(service_account_id, work_order_id, **overrides) -> dict:
    payload = {
        "service_account_id": service_account_id,
        "work_order_id": work_order_id,
        "claimed_bill_cents": 16800,
        "baseline_bill_cents": 12000,
        "billing_period_start": TEST_DEFAULTS["BILLING_PERIOD_START"],
        "billing_period_end": TEST_DEFAULTS["BILLING_PERIOD_END"],
    }
    payload.update(overrides)
    return payload


def create_quality_audit_payload(work_order_id, **overrides) -> dict:
    payload = {"work_order_id": work_order_id, "audit_type": "FOR_CAUSE"}
    payload.update(overrides)
    return payload


def record_audit_payload(**overrides) -> dict:
    payload = {"checks_total": 10, "checks_passed": 9, "defects_found": 1}
    payload.update(overrides)
    return payload


def create_invoice_payload(contractor_id, **overrides) -> dict:
    payload = {
        "contractor_id": contractor_id,
        "period_start": TEST_DEFAULTS["INVOICE_PERIOD_START"],
        "period_end": TEST_DEFAULTS["INVOICE_PERIOD_END"],
    }
    payload.update(overrides)
    return payload
