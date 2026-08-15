"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

_npi_counter = itertools.count(1000000001)
_fips_counter = itertools.count(6001)
_member_ref_counter = itertools.count(1)
_cycle_counter = itertools.count(1)


def next_npi() -> str:
    return str(next(_npi_counter))


def next_fips() -> str:
    return f"0{next(_fips_counter)}"


def create_region_payload(**overrides) -> dict:
    defaults = {
        "county_fips": next_fips(),
        "name": "Test County",
        "geo_class": "URBAN",
        "enrolled_member_count": 100,
    }
    defaults.update(overrides)
    return defaults


def create_standard_payload(**overrides) -> dict:
    defaults = {
        "specialty": "CARDIOLOGY",
        "geo_class": "URBAN",
        "max_members_per_provider": 1200,
        "max_travel_minutes": 30,
        "max_travel_miles": 15,
        "max_wait_days_routine": 15,
        "max_wait_days_urgent": 2,
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "npi": next_npi(),
        "legal_name": "Test Provider",
        "specialty": "CARDIOLOGY",
        "contract_effective_date": "2026-04-01",
    }
    defaults.update(overrides)
    return defaults


def create_location_payload(provider_id, region_id, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "region_id": region_id,
        "address_line": "1 Test St",
        "avg_travel_minutes": 10,
        "avg_travel_miles": 5,
    }
    defaults.update(overrides)
    return defaults


def create_listing_payload(provider_id, location_id, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "location_id": location_id,
        "specialty": "CARDIOLOGY",
        "display_name": "Test Listing",
        "phone": "555-0100",
        "accepts_new_patients": True,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(region_id, **overrides) -> dict:
    defaults = {
        "region_id": region_id,
        "member_ref": f"M-{next(_member_ref_counter)}",
        "full_name": "Test Member",
        "enrolled_on": "2026-04-15",
    }
    defaults.update(overrides)
    return defaults


def create_cycle_payload(**overrides) -> dict:
    n = next(_cycle_counter)
    defaults = {
        "cycle_label": f"CYCLE-{n}",
        "open_date": "2026-05-01",
        "due_date": "2026-05-10",
        "outreach_close_date": "2026-05-20",
    }
    defaults.update(overrides)
    return defaults


def create_probe_payload(listing_id, **overrides) -> dict:
    defaults = {
        "listing_id": listing_id,
        "probe_type": "ROUTINE",
        "requested_date": "2026-05-02",
    }
    defaults.update(overrides)
    return defaults


def record_probe_payload(**overrides) -> dict:
    defaults = {"outcome": "KEPT", "offered_appointment_date": "2026-05-05"}
    defaults.update(overrides)
    return defaults


def create_evaluation_payload(**overrides) -> dict:
    defaults = {
        "measurement_period": "2026-Q2",
        "period_start_date": "2026-06-01",
        "period_end_date": "2026-06-11",
    }
    defaults.update(overrides)
    return defaults


def create_access_plan_request_payload(expected_deficiency_version, **overrides) -> dict:
    defaults = {
        "expected_deficiency_version": expected_deficiency_version,
        "remedy_summary": "Remediation plan",
        "excuse_start_date": "2026-07-01",
        "excuse_through_date": "2026-07-31",
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(listing_id, **overrides) -> dict:
    defaults = {
        "listing_id": listing_id,
        "error_type": "WRONG_PHONE",
        "error_observed_date": "2026-04-25",
        "description": "Directory data is wrong",
    }
    defaults.update(overrides)
    return defaults


def create_correction_payload(listing_id, **overrides) -> dict:
    defaults = {
        "listing_id": listing_id,
        "changes": {"phone": "555-9999"},
    }
    defaults.update(overrides)
    return defaults
