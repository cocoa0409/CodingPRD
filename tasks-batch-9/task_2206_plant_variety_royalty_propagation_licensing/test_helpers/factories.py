"""Payload factories -- one per entity, carrying only client-supplied fields."""

from typing import Any, Dict

from .constants import TEST_DEFAULTS


def create_variety_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "denomination": "Aurora Bramble",
        "species": TEST_DEFAULTS["SPECIES"],
        "breeder_code": "AB",
        "royalty_basis_default": "PER_PLANT",
        "base_royalty_cents_per_plant": TEST_DEFAULTS["BASE_ROYALTY_CENTS_PER_PLANT"],
        "base_royalty_cents_per_acre": TEST_DEFAULTS["BASE_ROYALTY_CENTS_PER_ACRE"],
    }
    payload.update(overrides)
    return payload


def brand_register_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "brand_mark_text": "SABLECREST",
        "brand_registry_class": 31,
        "brand_renewal_due_at": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def brand_renew_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "brand_mark_text": "SABLECREST",
        "brand_renewal_due_at": "2027-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_protection_filing_payload(variety_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "variety_id": variety_id,
        "instrument_type": "PLANT_PATENT",
        "jurisdiction_code": TEST_DEFAULTS["JURISDICTION_CODE"],
        "term_years": 20,
        "annuity_base_cents": TEST_DEFAULTS["ANNUITY_BASE_CENTS"],
    }
    payload.update(overrides)
    return payload


def schedule_annuity_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "annuity_due_date": "2026-09-01T00:00:00Z",
        "annuity_grace_days": 90,
    }
    payload.update(overrides)
    return payload


def pay_annuity_payload(paid_amount_cents: int, **overrides) -> Dict[str, Any]:
    payload = {"paid_amount_cents": paid_amount_cents}
    payload.update(overrides)
    return payload


def create_trial_site_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "site_name": "Aurora Station",
        "region_code": TEST_DEFAULTS["REGION_CODE"],
        "plot_capacity": 60,
    }
    payload.update(overrides)
    return payload


def create_variety_trial_payload(variety_id: str, trial_site_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "variety_id": variety_id,
        "trial_site_id": trial_site_id,
        "plot_count": 10,
        "plant_date": "2026-08-05T00:00:00Z",
        "harvest_date": "2026-09-20T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def evaluate_trial_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "yield_index": 80.00,
        "vigor_score": 75.00,
        "uniformity_score": 70.00,
        "disease_resistance_score": 65.00,
        "propagation_pass_rate": 0.9600,
    }
    payload.update(overrides)
    return payload


def create_propagator_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "legal_name": "Aurora Lane Nursery",
        "home_territory_code": TEST_DEFAULTS["TERRITORY_CODE"],
    }
    payload.update(overrides)
    return payload


def create_propagator_agreement_payload(propagator_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "propagator_id": propagator_id,
        "quality_tier": "TIER_B",
        "territory_codes": [TEST_DEFAULTS["TERRITORY_CODE"]],
        "term_start": TEST_DEFAULTS["TERM_START"],
        "term_end": TEST_DEFAULTS["TERM_END"],
    }
    payload.update(overrides)
    return payload


def create_production_quota_payload(agreement_id: str, variety_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "agreement_id": agreement_id,
        "variety_id": variety_id,
        "season_code": TEST_DEFAULTS["SEASON_CODE"],
        "basis": "PER_PLANT",
        "territory_code": TEST_DEFAULTS["TERRITORY_CODE"],
        "territory_class": "DOMESTIC",
        "allocated_units": 5000,
    }
    payload.update(overrides)
    return payload


def create_tag_order_payload(quota_id: str, expected_quota_version: int, **overrides) -> Dict[str, Any]:
    payload = {
        "quota_id": quota_id,
        "requested_units": 1000,
        "expected_quota_version": expected_quota_version,
    }
    payload.update(overrides)
    return payload


def reconcile_tag_order_payload(activated_units: int, **overrides) -> Dict[str, Any]:
    payload = {"activated_units": activated_units}
    payload.update(overrides)
    return payload


def create_royalty_report_payload(agreement_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "agreement_id": agreement_id,
        "period_code": "2026Q3",
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-11-01T00:00:00Z",
        "due_at": "2026-11-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_royalty_line_item_payload(quota_id: str, reported_units: int,
                                     expected_report_version: int, **overrides) -> Dict[str, Any]:
    payload = {
        "quota_id": quota_id,
        "reported_units": reported_units,
        "expected_report_version": expected_report_version,
    }
    payload.update(overrides)
    return payload


def create_sublicense_grant_payload(agreement_id: str, variety_id: str,
                                    expected_agreement_version: int, **overrides) -> Dict[str, Any]:
    payload = {
        "agreement_id": agreement_id,
        "variety_id": variety_id,
        "sublicensee_name": "Aurora Retail Programme",
        "territory_code": TEST_DEFAULTS["TERRITORY_CODE"],
        "jurisdiction_code": TEST_DEFAULTS["JURISDICTION_CODE"],
        "exclusivity": "NON_EXCLUSIVE",
        "effective_date": "2026-10-01T00:00:00Z",
        "expiry_date": "2026-12-31T00:00:00Z",
        "expected_agreement_version": expected_agreement_version,
    }
    payload.update(overrides)
    return payload


def create_surveillance_case_payload(variety_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "variety_id": variety_id,
        "market_survey_ref": "MS-2026-014",
    }
    payload.update(overrides)
    return payload


def sample_case_payload(sampled_unit_count: int = 40, **overrides) -> Dict[str, Any]:
    payload = {"sampled_unit_count": sampled_unit_count}
    payload.update(overrides)
    return payload


def create_genetic_test_payload(match_confidence: float, **overrides) -> Dict[str, Any]:
    payload = {
        "lab_code": TEST_DEFAULTS["LAB_CODE"],
        "marker_panel": TEST_DEFAULTS["MARKER_PANEL"],
        "match_confidence": match_confidence,
    }
    payload.update(overrides)
    return payload


def resolve_case_payload(recovered_damages_cents: int, enforcement_cost_cents: int,
                         **overrides) -> Dict[str, Any]:
    payload = {
        "recovered_damages_cents": recovered_damages_cents,
        "enforcement_cost_cents": enforcement_cost_cents,
    }
    payload.update(overrides)
    return payload


def create_audit_engagement_payload(agreement_id: str, royalty_report_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "agreement_id": agreement_id,
        "royalty_report_id": royalty_report_id,
    }
    payload.update(overrides)
    return payload


def finalize_engagement_payload(finding_severity: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"finding_severity": finding_severity}
    payload.update(overrides)
    return payload


def set_clock_payload(current_utc: str) -> Dict[str, Any]:
    return {"current_utc": current_utc}
