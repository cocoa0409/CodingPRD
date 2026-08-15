"""Payload factories — one per creatable resource, input fields only (PRD §3)."""

DEFAULTS = {
    "COUNTY_CODE": "06001",
    "STATE_CODE": "CA",
    "CROP_CODE": "CORN",
    "RATE_PER_100": 333,
    "REINSURANCE_ATTACHMENT_CENTS": 100_000_000,
    "RATE_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "POLICY_EFFECTIVE": "2026-08-02T00:00:00Z",
    "POLICY_EXPIRATION": "2026-12-31T00:00:00Z",
    "LOSS_DATE": "2026-08-04T00:00:00Z",
    "SCHEDULED_FOR": "2026-08-04T12:00:00Z",
}


def create_carrier_payload(**overrides) -> dict:
    defaults = {
        "carrier_code": "CHL-T1",
        "legal_name": "Test Carrier",
        "reinsurance_treaty_attachment_cents": DEFAULTS["REINSURANCE_ATTACHMENT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_grower_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Grower",
        "tax_id_last4": "1234",
        "email": "grower@example.com",
        "county_code": DEFAULTS["COUNTY_CODE"],
        "state_code": DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_adjuster_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Adjuster",
        "license_number": "ADJ-T-1",
        "county_codes": [DEFAULTS["COUNTY_CODE"]],
        "species_qualified": ["CATTLE"],
        "capacity_max_open_claims": 5,
    }
    defaults.update(overrides)
    return defaults


def create_crop_hail_rate_payload(**overrides) -> dict:
    defaults = {
        "rating_kind": "CROP_HAIL",
        "county_code": DEFAULTS["COUNTY_CODE"],
        "crop_code": DEFAULTS["CROP_CODE"],
        "rate_per_100_cents_of_liability": DEFAULTS["RATE_PER_100"],
        "effective_from": DEFAULTS["RATE_EFFECTIVE_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_livestock_rate_payload(**overrides) -> dict:
    defaults = {
        "rating_kind": "LIVESTOCK_MORTALITY",
        "species": "CATTLE",
        "value_band_floor_cents": 150_000,
        "value_band_ceiling_cents": 250_000,
        "rate_per_100_cents_of_liability": 400,
        "effective_from": DEFAULTS["RATE_EFFECTIVE_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_federal_crop_policy_payload(grower_id: str, **overrides) -> dict:
    defaults = {
        "grower_id": grower_id,
        "fci_policy_number": "FCI-T-1",
        "coverage_level_pct": 0.75,
        "crop_code": DEFAULTS["CROP_CODE"],
        "county_code": DEFAULTS["COUNTY_CODE"],
        "effective_date": "2026-01-01T00:00:00Z",
        "expiration_date": "2027-12-31T00:00:00Z",
        "liability_cents": 200_000,
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(grower_id: str, policy_kind: str = "CROP_HAIL", **overrides) -> dict:
    defaults = {
        "grower_id": grower_id,
        "policy_kind": policy_kind,
        "effective_date": DEFAULTS["POLICY_EFFECTIVE"],
        "expiration_date": DEFAULTS["POLICY_EXPIRATION"],
    }
    defaults.update(overrides)
    return defaults


def create_crop_hail_unit_payload(**overrides) -> dict:
    defaults = {
        "county_code": DEFAULTS["COUNTY_CODE"],
        "crop_code": DEFAULTS["CROP_CODE"],
        "declared_acres": 10,
    }
    defaults.update(overrides)
    return defaults


def create_livestock_unit_payload(**overrides) -> dict:
    defaults = {
        "species": "CATTLE",
        "declared_head_count": 10,
        "per_head_value_cents": 200_000,
    }
    defaults.update(overrides)
    return defaults


def create_acreage_report_payload(**overrides) -> dict:
    defaults = {"report_kind": "PLANTING", "reported_acres": 10}
    defaults.update(overrides)
    return defaults


def create_head_report_payload(**overrides) -> dict:
    defaults = {"report_kind": "INITIAL", "reported_head_count": 10}
    defaults.update(overrides)
    return defaults


def create_hail_claim_payload(coverage_unit_id: str, **overrides) -> dict:
    defaults = {
        "coverage_unit_id": coverage_unit_id,
        "loss_date": DEFAULTS["LOSS_DATE"],
        "percent_damage_estimate_pct": 10,
    }
    defaults.update(overrides)
    return defaults


def create_livestock_claim_payload(coverage_unit_id: str, **overrides) -> dict:
    defaults = {
        "coverage_unit_id": coverage_unit_id,
        "loss_date": DEFAULTS["LOSS_DATE"],
        "appraisal_value_cents": 100_000,
        "deceased_head_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_assign_adjuster_payload(adjuster_id: str, **overrides) -> dict:
    defaults = {"adjuster_id": adjuster_id}
    defaults.update(overrides)
    return defaults


def create_hail_inspection_payload(adjuster_id: str, **overrides) -> dict:
    defaults = {
        "adjuster_id": adjuster_id,
        "scheduled_for": DEFAULTS["SCHEDULED_FOR"],
        "observed_percent_damage_pct": 10,
        "notes": "field inspection",
    }
    defaults.update(overrides)
    return defaults


def create_livestock_inspection_payload(adjuster_id: str, **overrides) -> dict:
    defaults = {
        "adjuster_id": adjuster_id,
        "scheduled_for": DEFAULTS["SCHEDULED_FOR"],
        "observed_appraisal_cents": 95_000,
        "observed_deceased_count": 1,
        "notes": "field inspection",
    }
    defaults.update(overrides)
    return defaults


def create_veterinary_report_payload(**overrides) -> dict:
    defaults = {
        "veterinarian_license": "VET-T-1",
        "report_kind": "VETERINARY_CERTIFICATE",
        "cause_of_death": "lightning strike",
        "necropsy_performed": False,
        "death_date": DEFAULTS["LOSS_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_determination_payload(
    decision: str, approved_indemnity_cents: int, expected_policy_version: int, **overrides
) -> dict:
    defaults = {
        "decision": decision,
        "approved_indemnity_cents": approved_indemnity_cents,
        "expected_policy_version": expected_policy_version,
    }
    defaults.update(overrides)
    return defaults


def create_indemnity_payment_payload(**overrides) -> dict:
    defaults = {"payment_method": "ACH"}
    defaults.update(overrides)
    return defaults


def create_dual_coverage_link_payload(federal_crop_policy_id: str, **overrides) -> dict:
    defaults = {"federal_crop_policy_id": federal_crop_policy_id}
    defaults.update(overrides)
    return defaults


def create_renewal_payload(
    decision: str, effective_date: str, expiration_date: str,
    expected_prior_policy_version: int, **overrides,
) -> dict:
    defaults = {
        "decision": decision,
        "effective_date": effective_date,
        "expiration_date": expiration_date,
        "expected_prior_policy_version": expected_prior_policy_version,
    }
    defaults.update(overrides)
    return defaults


def create_premium_payment_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults
