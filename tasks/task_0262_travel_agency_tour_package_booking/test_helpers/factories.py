"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "AGENCY_NAME": "Globe Tours",
    "CURRENCY": "USD",
    "CUSTOMER_EMAIL": "c@x.com",
    "CUSTOMER_NAME": "C One",
    "SUPPLIER_NAME": "AutoAir",
    "PACKAGE_TITLE": "Alps Tour",
    "BASE_PRICE_PER_PERSON_CENTS": 100000,
    "TRAVELER_NAME": "T1",
    "DEPARTURE_DATE": "2026-06-01T00:00:00.000Z",
}


def create_agency_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["AGENCY_NAME"],
        "currency": DEFAULTS["CURRENCY"],
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(now_utc: str, **overrides) -> dict:
    defaults = {"now_utc": now_utc}
    defaults.update(overrides)
    return defaults


def create_customer_payload(agency_id: str, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "email": DEFAULTS["CUSTOMER_EMAIL"],
        "full_name": DEFAULTS["CUSTOMER_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_supplier_payload(agency_id: str, kind: str = "FLIGHT", **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "name": DEFAULTS["SUPPLIER_NAME"],
        "kind": kind,
        "auto_confirm": False,
    }
    defaults.update(overrides)
    return defaults


def create_tour_package_payload(agency_id: str, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "title": DEFAULTS["PACKAGE_TITLE"],
        "base_price_per_person_cents": DEFAULTS["BASE_PRICE_PER_PERSON_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(agency_id: str, customer_id: str, tour_package_id: str,
                           departure_date: str = None, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "customer_id": customer_id,
        "tour_package_id": tour_package_id,
        "departure_date": departure_date or DEFAULTS["DEPARTURE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def add_traveler_payload(expected_booking_version: int, full_name: str = None, **overrides) -> dict:
    defaults = {
        "full_name": full_name or DEFAULTS["TRAVELER_NAME"],
        "expected_booking_version": expected_booking_version,
    }
    defaults.update(overrides)
    return defaults


def create_component_payload(booking_id: str, supplier_id: str, kind: str,
                             starts_at: str, ends_at: str, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "supplier_id": supplier_id,
        "kind": kind,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "is_mandatory": True,
    }
    defaults.update(overrides)
    return defaults


def create_insurance_payload(booking_id: str, coverage_tier: str, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "coverage_tier": coverage_tier,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(booking_id: str, milestone_id: str, amount_cents: int,
                           method: str = "CARD", **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "milestone_id": milestone_id,
        "amount_cents": amount_cents,
        "method": method,
    }
    defaults.update(overrides)
    return defaults


def reserve_payload(expected_booking_version: int, **overrides) -> dict:
    defaults = {"expected_booking_version": expected_booking_version}
    defaults.update(overrides)
    return defaults


def confirm_payload(expected_booking_version: int, **overrides) -> dict:
    defaults = {"expected_booking_version": expected_booking_version}
    defaults.update(overrides)
    return defaults


def cancel_payload(expected_booking_version: int, refund_destination: str = None, **overrides) -> dict:
    defaults = {"expected_booking_version": expected_booking_version}
    if refund_destination is not None:
        defaults["refund_destination"] = refund_destination
    defaults.update(overrides)
    return defaults
