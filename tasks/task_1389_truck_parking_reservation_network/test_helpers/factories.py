"""Payload factories — one per entity, input fields only (PRD section 4)."""
from .constants import TEST_DEFAULTS


def create_site_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Site",
        "base_nightly_rate_cents": TEST_DEFAULTS["BASE_NIGHTLY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_stall_payload(stall_number, stall_class="STANDARD",
                         is_reservable=True, **overrides) -> dict:
    defaults = {
        "stall_number": stall_number,
        "stall_class": stall_class,
        "is_reservable": is_reservable,
    }
    defaults.update(overrides)
    return defaults


def create_rate_plan_payload(**overrides) -> dict:
    return dict(overrides)


def create_amenity_product_payload(code, name=None, price_cents=1500,
                                   **overrides) -> dict:
    defaults = {
        "code": code,
        "name": name or f"{code.title()} product",
        "price_cents": price_cents,
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(cdl_number, full_name="Test Driver",
                          **overrides) -> dict:
    defaults = {"cdl_number": cdl_number, "full_name": full_name}
    defaults.update(overrides)
    return defaults


def create_fleet_account_payload(company_name="Fleet Co",
                                 credit_limit_cents=None,
                                 **overrides) -> dict:
    defaults = {
        "company_name": company_name,
        "credit_limit_cents": (
            credit_limit_cents
            if credit_limit_cents is not None
            else TEST_DEFAULTS["CREDIT_LIMIT_CENTS"]
        ),
    }
    defaults.update(overrides)
    return defaults


def create_driver_authorization_payload(driver_id, fleet_account_id,
                                        **overrides) -> dict:
    defaults = {"driver_id": driver_id, "fleet_account_id": fleet_account_id}
    defaults.update(overrides)
    return defaults


def create_booking_payload(driver_id, site_id, arrival_date, night_count=1,
                           booking_kind="RESERVED", payment_mode="DRIVER_DIRECT",
                           **overrides) -> dict:
    defaults = {
        "driver_id": driver_id,
        "site_id": site_id,
        "booking_kind": booking_kind,
        "arrival_date": arrival_date,
        "night_count": night_count,
        "payment_mode": payment_mode,
    }
    defaults.update(overrides)
    return defaults


def create_booking_amenity_payload(amenity_product_id, quantity=1,
                                   **overrides) -> dict:
    defaults = {"amenity_product_id": amenity_product_id, "quantity": quantity}
    defaults.update(overrides)
    return defaults


def create_waitlist_entry_payload(driver_id, site_id, arrival_date,
                                  night_count=1, stall_class="STANDARD",
                                  payment_mode="DRIVER_DIRECT",
                                  **overrides) -> dict:
    defaults = {
        "driver_id": driver_id,
        "site_id": site_id,
        "arrival_date": arrival_date,
        "night_count": night_count,
        "stall_class": stall_class,
        "payment_mode": payment_mode,
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(category, severity, description, **overrides) -> dict:
    defaults = {
        "category": category,
        "severity": severity,
        "description": description,
    }
    defaults.update(overrides)
    return defaults
