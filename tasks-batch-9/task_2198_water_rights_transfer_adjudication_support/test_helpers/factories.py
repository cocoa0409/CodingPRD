"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS

DEFAULTS = {
    "CLAIMANT_LEGAL_NAME": "Vega Ditch Company",
    "CLAIMANT_EMAIL": "ops@vega.example",
    "RIGHT_NUMBER": "WR-2198-001",
    "POD_LEGAL_DESCRIPTION": "NE1/4 SEC 12 T3N R4E headgate",
    "POD_STREAM_REACH_CODE": "SNK-14-A",
    "LESSEE_NAME": "Bitterroot Feedlot",
    "BASIN_CODE": "BASIN-01",
    "DOCKET_NUMBER": "DKT-2198-A",
}


def create_claimant_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["CLAIMANT_LEGAL_NAME"],
        "contact_email": DEFAULTS["CLAIMANT_EMAIL"],
        "entity_type": "IRRIGATION_DISTRICT",
    }
    payload.update(overrides)
    return payload


def create_water_right_payload(claimant_id: str, **overrides) -> dict:
    payload = {
        "claimant_id": claimant_id,
        "right_number": DEFAULTS["RIGHT_NUMBER"],
        "priority_date": TEST_DEFAULTS["PRIORITY_DATE"],
        "source_stream_code": TEST_DEFAULTS["SOURCE_STREAM_CODE"],
        "purpose_of_use": "IRRIGATION",
        "place_of_use_acres": TEST_DEFAULTS["PLACE_OF_USE_ACRES"],
        "authorized_diversion_af": TEST_DEFAULTS["AUTHORIZED_DIVERSION_AF"],
        "authorized_rate_cfs": TEST_DEFAULTS["AUTHORIZED_RATE_CFS"],
    }
    payload.update(overrides)
    return payload


def create_point_of_diversion_payload(**overrides) -> dict:
    payload = {
        "legal_description": DEFAULTS["POD_LEGAL_DESCRIPTION"],
        "stream_reach_code": DEFAULTS["POD_STREAM_REACH_CODE"],
        "max_rate_cfs": 5.000,
        "stream_miles_from_headwater": 41.20,
    }
    payload.update(overrides)
    return payload


def create_beneficial_use_record_payload(use_year: int, **overrides) -> dict:
    payload = {
        "use_year": use_year,
        "reported_diversion_af": TEST_DEFAULTS["REPORTED_DIVERSION_AF"],
        "irrigated_acres": TEST_DEFAULTS["IRRIGATED_ACRES"],
        "verification_source": "METER",
    }
    payload.update(overrides)
    return payload


def create_hcu_study_payload(
    start_year: int = 2023, end_year: int = 2025, **overrides
) -> dict:
    payload = {
        "method": "DIVERSION_BASED",
        "study_period_start_year": start_year,
        "study_period_end_year": end_year,
    }
    payload.update(overrides)
    return payload


def create_transfer_application_payload(
    water_right_id: str, hcu_study_id: str, requested_af: float, **overrides
) -> dict:
    payload = {
        "water_right_id": water_right_id,
        "hcu_study_id": hcu_study_id,
        "application_type": "CHANGE_OF_USE",
        "requested_af": requested_af,
        "proposed_purpose_of_use": "MUNICIPAL",
    }
    payload.update(overrides)
    return payload


def create_injury_analysis_payload(
    method: str = "SEASONAL_AVERAGE", pod_move_miles: float = 0.00, **overrides
) -> dict:
    payload = {"method": method, "pod_move_miles": pod_move_miles}
    payload.update(overrides)
    return payload


def create_protest_payload(
    transfer_application_id: str,
    protestant_claimant_id: str,
    claimed_injury_af: float,
    **overrides,
) -> dict:
    payload = {
        "transfer_application_id": transfer_application_id,
        "protestant_claimant_id": protestant_claimant_id,
        "claimed_injury_af": claimed_injury_af,
        "basis": "INJURY_TO_SENIOR_RIGHT",
    }
    payload.update(overrides)
    return payload


def resolve_protest_payload(outcome: str = "STIPULATE", **overrides) -> dict:
    payload = {"outcome": outcome, "resolution_note": "Resolved on the record."}
    payload.update(overrides)
    return payload


def decide_payload(disposition: str, **overrides) -> dict:
    payload = {"disposition": disposition, "decision_note": "Findings of record."}
    payload.update(overrides)
    return payload


def condition_entry(
    condition_type: str, required_af: float, compliance_due_date=None
) -> dict:
    return {
        "condition_type": condition_type,
        "required_af": required_af,
        "compliance_due_date": compliance_due_date,
    }


def create_water_bank_account_payload(claimant_id: str, **overrides) -> dict:
    payload = {"claimant_id": claimant_id, "basin_code": DEFAULTS["BASIN_CODE"]}
    payload.update(overrides)
    return payload


def create_deposit_payload(
    water_right_id: str, deposit_af: float, expected_water_bank_account_version: int
) -> dict:
    return {
        "water_right_id": water_right_id,
        "deposit_af": deposit_af,
        "expected_water_bank_account_version": expected_water_bank_account_version,
    }


def create_lease_assignment_payload(
    water_bank_account_id: str,
    water_right_id: str,
    point_of_diversion_id: str,
    lease_start_date: str,
    lease_end_date: str,
    requested_af: float,
    **overrides,
) -> dict:
    payload = {
        "water_bank_account_id": water_bank_account_id,
        "water_right_id": water_right_id,
        "point_of_diversion_id": point_of_diversion_id,
        "lessee_name": DEFAULTS["LESSEE_NAME"],
        "lease_start_date": lease_start_date,
        "lease_end_date": lease_end_date,
        "requested_af": requested_af,
        "diversion_rate_cfs": 1.000,
        "rental_rate_usd_per_af": 12.00,
        "valuation_method": "PRO_RATA_DAILY",
    }
    payload.update(overrides)
    return payload


def create_decree_docket_payload(
    claim_filing_deadline: str = "2026-06-01T00:00:00Z", **overrides
) -> dict:
    payload = {
        "basin_code": DEFAULTS["BASIN_CODE"],
        "docket_number": DEFAULTS["DOCKET_NUMBER"],
        "claim_filing_deadline": claim_filing_deadline,
    }
    payload.update(overrides)
    return payload


def create_adjudication_claim_payload(
    decree_docket_id: str,
    water_right_id: str,
    claimed_priority_date: str,
    claimed_af: float,
    **overrides,
) -> dict:
    payload = {
        "decree_docket_id": decree_docket_id,
        "water_right_id": water_right_id,
        "claimed_priority_date": claimed_priority_date,
        "claimed_af": claimed_af,
    }
    payload.update(overrides)
    return payload
