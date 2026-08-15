"""Payload factories — one per entity, input fields only.

Every factory accepts **overrides so tests can control exactly the values
their scenario depends on while defaults keep the rest valid.
"""
from .constants import TEST_DEFAULTS


def create_program_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Program",
        "fiscal_year": TEST_DEFAULTS["FISCAL_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(**overrides) -> dict:
    defaults = {
        "name": "S1",
        "address": "1 A St",
        "capacity_kg": TEST_DEFAULTS["SITE_CAPACITY_KG"],
    }
    defaults.update(overrides)
    return defaults


def create_host_agreement_payload(site_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "host_name": "Host",
        "term_start": TEST_DEFAULTS["TERM_START"],
        "term_end": TEST_DEFAULTS["TERM_END"],
    }
    defaults.update(overrides)
    return defaults


def create_material_payload(**overrides) -> dict:
    defaults = {
        "code": "FOOD",
        "description": "food scraps",
        "accepted_start_month_day": TEST_DEFAULTS["MATERIAL_START_MD"],
        "accepted_end_month_day": TEST_DEFAULTS["MATERIAL_END_MD"],
        "contamination_sensitivity": "LOW",
    }
    defaults.update(overrides)
    return defaults


def register_participant_payload(**overrides) -> dict:
    defaults = {
        "email": "p@x.com",
        "full_name": "Participant",
        "household_size": 1,
    }
    defaults.update(overrides)
    return defaults


def create_grant_payload(site_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "bucket_quota": TEST_DEFAULTS["BUCKET_QUOTA"],
        "expires_at": TEST_DEFAULTS["GRANT_EXPIRES_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_drop_payload(participant_id, access_grant_id, material_category_id,
                        expected_site_version, **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "access_grant_id": access_grant_id,
        "material_category_id": material_category_id,
        "gross_weight_kg": 10.00,
        "contamination_kg": 0.00,
        "occurred_at": TEST_DEFAULTS["DROP_OCCURRED_AT"],
        "expected_site_version": expected_site_version,
    }
    defaults.update(overrides)
    return defaults


def create_contamination_report_payload(**overrides) -> dict:
    defaults = {
        "auditor_id": "aud-1",
        "severity": "MINOR",
        "finding_note": "contamination found",
    }
    defaults.update(overrides)
    return defaults


def create_partner_payload(**overrides) -> dict:
    defaults = {
        "name": "PP",
        "intake_capacity_kg_per_day": TEST_DEFAULTS["INTAKE_CAPACITY_KG_PER_DAY"],
        "yield_ratio": TEST_DEFAULTS["YIELD_RATIO"],
        "contamination_reject_threshold_pct": TEST_DEFAULTS["REJECT_THRESHOLD_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(partner_id, **overrides) -> dict:
    defaults = {
        "route_code": "R1",
        "vehicle_capacity_kg": TEST_DEFAULTS["VEHICLE_CAPACITY_KG"],
        "processing_partner_id": partner_id,
        "scheduled_start": TEST_DEFAULTS["ROUTE_START"],
        "scheduled_end": TEST_DEFAULTS["ROUTE_END"],
    }
    defaults.update(overrides)
    return defaults


def create_stop_payload(site_id, expected_route_version, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "planned_pickup_kg": 10,
        "stop_sequence": 1,
        "expected_route_version": expected_route_version,
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(**overrides) -> dict:
    defaults = {
        "reporter_contact": "neighbor-1",
        "kind": "ODOR",
        "description": "smell",
        "reported_at": "2026-08-01T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_diversion_report_payload(**overrides) -> dict:
    defaults = {
        "period_start": TEST_DEFAULTS["REPORT_PERIOD_START"],
        "period_end": TEST_DEFAULTS["REPORT_PERIOD_END"],
        "method": "PROVISIONAL_NET",
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(participant_id, expected_distribution_version,
                              **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "requested_kg": 5.00,
        "credits_redeemed": 5,
        "expected_distribution_version": expected_distribution_version,
    }
    defaults.update(overrides)
    return defaults
