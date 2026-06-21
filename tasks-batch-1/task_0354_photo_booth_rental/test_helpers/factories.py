"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS


def create_booth_model_payload(**overrides) -> dict:
    """PRD §3.1: name, booth_type, footprint_sqft, max_prints_per_hour, active?."""
    defaults = {
        "name": "Open-Air Mirror",
        "booth_type": "MIRROR",
        "footprint_sqft": 80,
        "max_prints_per_hour": 120,
    }
    defaults.update(overrides)
    return defaults


def create_package_payload(booth_model_id, **overrides) -> dict:
    """PRD §3.1: a pricing plan sold on a booth model."""
    defaults = {
        "booth_model_id": booth_model_id,
        "name": "Premium 4hr",
        "base_price": TEST_DEFAULTS["BASE_PRICE"],
        "included_hours": TEST_DEFAULTS["INCLUDED_HOURS"],
        "included_prints": TEST_DEFAULTS["INCLUDED_PRINTS"],
        "overtime_rate_per_hour": TEST_DEFAULTS["OVERTIME_RATE_PER_HOUR"],
        "idle_rate_per_hour": TEST_DEFAULTS["IDLE_RATE_PER_HOUR"],
        "overage_print_rate": TEST_DEFAULTS["OVERAGE_PRINT_RATE"],
    }
    defaults.update(overrides)
    return defaults


def create_booth_payload(booth_model_id, asset_tag="BTH-001", **overrides) -> dict:
    """PRD §3.1: a physical booth unit registered on a model."""
    defaults = {
        "booth_model_id": booth_model_id,
        "asset_tag": asset_tag,
    }
    defaults.update(overrides)
    return defaults


def create_attendant_payload(full_name="Sam Staff", **overrides) -> dict:
    """PRD §3.1: an on-site attendant."""
    defaults = {"full_name": full_name}
    defaults.update(overrides)
    return defaults


def create_add_on_payload(code="PROPS", name="Prop Box", unit_price=50.00, **overrides) -> dict:
    """PRD §3.1: a catalog add-on (PROPS/BACKDROP/ATTENDANT/ALBUM)."""
    defaults = {
        "code": code,
        "name": name,
        "unit_price": unit_price,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(email="c1@x.com", full_name="Cara One", **overrides) -> dict:
    """PRD §3.2: self-registration of a customer."""
    defaults = {
        "email": email,
        "full_name": full_name,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(customer_id, package_id,
                           event_start="2026-09-12T18:00:00Z",
                           event_end="2026-09-12T22:00:00Z",
                           venue_distance_miles=0,
                           **overrides) -> dict:
    """PRD §3.2: draft a booking. requested_setup_lead_min is optional (default 0)."""
    defaults = {
        "customer_id": customer_id,
        "package_id": package_id,
        "event_start": event_start,
        "event_end": event_end,
        "venue_distance_miles": venue_distance_miles,
    }
    defaults.update(overrides)
    return defaults


def create_booking_add_on_payload(add_on_id, qty=1, **overrides) -> dict:
    """PRD §3.3: add an add-on line to a DRAFT booking."""
    defaults = {
        "add_on_id": add_on_id,
        "qty": qty,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(kind, amount, **overrides) -> dict:
    """PRD §3.6: record a DEPOSIT / BALANCE / REFUND money event."""
    defaults = {
        "kind": kind,
        "amount": amount,
    }
    defaults.update(overrides)
    return defaults


def create_finalize_payload(actual_setup_start, actual_coverage_start,
                            actual_coverage_end, actual_teardown_end,
                            actual_print_count, expected_eventlog_version,
                            **overrides) -> dict:
    """PRD §3.5: finalize OPEN actuals with the OCC version assertion."""
    defaults = {
        "actual_setup_start": actual_setup_start,
        "actual_coverage_start": actual_coverage_start,
        "actual_coverage_end": actual_coverage_end,
        "actual_teardown_end": actual_teardown_end,
        "actual_print_count": actual_print_count,
        "expected_eventlog_version": expected_eventlog_version,
    }
    defaults.update(overrides)
    return defaults
