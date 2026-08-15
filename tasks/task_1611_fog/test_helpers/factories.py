"""Payload factories — one per creatable resource, input fields only."""
from .constants import TEST_DEFAULTS


def create_establishment_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Establishment",
        "street_address": "1 Test Way",
        "seating_capacity": 10,
        "fryer_count": 0,
        "cuisine_profile": "LOW_GREASE",
    }
    defaults.update(overrides)
    return defaults


def patch_establishment_payload(expected_establishment_version, **overrides) -> dict:
    defaults = {"expected_establishment_version": expected_establishment_version}
    defaults.update(overrides)
    return defaults


def create_interceptor_payload(establishment_id, nominal_capacity_gal=50,
                               **overrides) -> dict:
    defaults = {
        "establishment_id": establishment_id,
        "nominal_capacity_gal": nominal_capacity_gal,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(establishment_id, items=None, **overrides) -> dict:
    defaults = {
        "establishment_id": establishment_id,
        "items": items if items is not None else [],
    }
    defaults.update(overrides)
    return defaults


def create_pump_manifest_payload(establishment_id, interceptor_id, hauler_id,
                                 **overrides) -> dict:
    defaults = {
        "establishment_id": establishment_id,
        "interceptor_id": interceptor_id,
        "hauler_id": hauler_id,
        "pump_date": TEST_DEFAULTS["PUMP_DATE"],
        "pumped_volume_gal": TEST_DEFAULTS["PUMPED_VOLUME_GAL"],
    }
    defaults.update(overrides)
    return defaults


def create_hauler_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Haul",
        "permit_number": "PN-TEST",
        "insurance_expires_on": TEST_DEFAULTS["INSURANCE_EXPIRES_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_disposal_record_payload(hauler_id, manifest_id, **overrides) -> dict:
    defaults = {
        "hauler_id": hauler_id,
        "manifest_id": manifest_id,
        "disposed_volume_gal": TEST_DEFAULTS["PUMPED_VOLUME_GAL"],
        "disposal_site_name": "Receiving Site",
        "disposed_at": TEST_DEFAULTS["DISPOSED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_blockage_event_payload(**overrides) -> dict:
    defaults = {"location_description": "Test sewer segment"}
    defaults.update(overrides)
    return defaults


def assess_blockage_payload(total_cleanup_cost_cents, contributions) -> dict:
    return {
        "total_cleanup_cost_cents": total_cleanup_cost_cents,
        "contributions": contributions,
    }


def create_variance_request_payload(establishment_id, scope="INTERCEPTOR_SIZE",
                                    **overrides) -> dict:
    defaults = {
        "establishment_id": establishment_id,
        "scope": scope,
        "justification": "test justification",
        "effective_from": TEST_DEFAULTS["VARIANCE_EFFECTIVE_FROM"],
        "effective_to": TEST_DEFAULTS["VARIANCE_EFFECTIVE_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Campaign",
        "outreach_zone": "ZTEST",
        "start_date": "2026-09-01T00:00:00Z",
        "end_date": "2026-10-01T00:00:00Z",
        "budget_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_outreach_event_payload(**overrides) -> dict:
    defaults = {
        "event_date": "2026-09-10T00:00:00Z",
        "venue_name": "Community Hall",
        "attendance_count": 25,
        "cost_cents": 1000,
    }
    defaults.update(overrides)
    return defaults
