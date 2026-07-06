"""Payload factories — one per entity, input fields only."""


def create_zone_payload(**overrides) -> dict:
    defaults = {
        "zone_code": "R1",
        "str_eligible": True,
        "whole_home_allowed": True,
        "permit_cap": 5,
        "lottery_enabled": False,
    }
    defaults.update(overrides)
    return defaults


def create_host_payload(**overrides) -> dict:
    defaults = {
        "email": "host@example.com",
        "full_name": "Test Host",
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(host_id, zone_id, **overrides) -> dict:
    defaults = {
        "host_id": host_id,
        "zone_id": zone_id,
        "street_address": "1 Test St",
        "bedroom_count": 3,
    }
    defaults.update(overrides)
    return defaults


def attest_primary_residence_payload(property_id) -> dict:
    return {"property_id": property_id}


def create_permit_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "permit_type": "PRIMARY_RESIDENCE",
        "attested_occupancy": 5,
        "safety_attested": True,
        "nightly_base_rate_cents": 20000,
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(permit_id, category="NOISE", **overrides) -> dict:
    defaults = {"permit_id": permit_id, "category": category}
    defaults.update(overrides)
    return defaults


def create_tax_filing_payload(permit_id, **overrides) -> dict:
    defaults = {
        "permit_id": permit_id,
        "period_year": 2026,
        "period_month": 3,
        "nights_booked": 10,
        "gross_revenue_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def remit_payload(payment_cents) -> dict:
    return {"payment_cents": payment_cents}


def renew_payload(expected_permit_version) -> dict:
    return {"expected_permit_version": expected_permit_version}


def create_lottery_round_payload(zone_id, seats_available=1, **overrides) -> dict:
    defaults = {"zone_id": zone_id, "seats_available": seats_available}
    defaults.update(overrides)
    return defaults


def draw_payload(expected_lottery_round_version) -> dict:
    return {"expected_lottery_round_version": expected_lottery_round_version}


def create_platform_payload(platform_name="Test Platform", **overrides) -> dict:
    defaults = {"platform_name": platform_name}
    defaults.update(overrides)
    return defaults


def create_listing_report_payload(platform_id, street_address, reported_nights=3, **overrides) -> dict:
    defaults = {
        "platform_id": platform_id,
        "street_address": street_address,
        "reported_nights": reported_nights,
    }
    defaults.update(overrides)
    return defaults
