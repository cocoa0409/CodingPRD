"""Payload factories: one builder per request body the PRD declares.

Every builder produces a valid default body and accepts ``**overrides`` so a
test can perturb exactly one field. Optional fields are omitted unless the
caller supplies them, which is what lets the default-value tests observe the
server applying `commissioning_buffer_days` 90, `queue_policy`
`FIRST_COME_FIRST_SERVED` and `premium_credit_pct` 0.5 for themselves.
"""

from typing import Optional

from .constants import (
    APPLICATION_REQUESTED_MW,
    APPLICATION_WINDOW_END,
    APPLICATION_WINDOW_START,
    AUTHORITY_TERMS,
    COMPANY_TERMS,
    LOAD_STUDY_BASE,
    PPA_AT_COVERAGE_FLOOR,
    PROGRAM_CAPITAL_BUDGET_USD,
    PROGRAM_NAME,
    PROGRAM_REQUIRED_ENERGIZATION_DATE,
    PROGRAM_TARGET_LOAD_MW,
    SCREEN_EVAPORATIVE,
    SITE_COUNTY,
    SITE_GROSS_ACRES,
    SITE_NAME,
    SITE_STATE_CODE,
    UTILITY_BALANCING_AUTHORITY,
    UTILITY_ENERGIZATION_LEAD_DAYS,
    UTILITY_NAME,
    UTILITY_STATE_CODE,
    UTILITY_STUDY_FEE_PER_MW_USD,
    UTILITY_TOTAL_CAPACITY_MW,
    UTILITY_UPGRADE_RATE_USD_PER_MW,
    WATER_SOURCE_ANNUAL_PERMITTED_MGAL,
    WATER_SOURCE_BASIN_CODE,
    WATER_SOURCE_NAME,
)


# --------------------------------------------------------------------------- #
# programs, utilities and water sources
# --------------------------------------------------------------------------- #
def create_siting_program_payload(**overrides) -> dict:
    payload = {
        "name": PROGRAM_NAME,
        "target_load_mw": PROGRAM_TARGET_LOAD_MW,
        "required_energization_date": PROGRAM_REQUIRED_ENERGIZATION_DATE,
        "capital_budget_usd": PROGRAM_CAPITAL_BUDGET_USD,
    }
    payload.update(overrides)
    return payload


def create_utility_payload(**overrides) -> dict:
    """The canonical utility declares both optional fields explicitly; drop them
    with ``create_utility_payload(commissioning_buffer_days=None)`` style calls
    through :func:`omit` when the default is the thing under test."""
    payload = {
        "name": UTILITY_NAME,
        "state_code": UTILITY_STATE_CODE,
        "balancing_authority": UTILITY_BALANCING_AUTHORITY,
        "total_transmission_capacity_mw": UTILITY_TOTAL_CAPACITY_MW,
        "interconnect_study_fee_per_mw_usd": UTILITY_STUDY_FEE_PER_MW_USD,
        "network_upgrade_rate_usd_per_mw": UTILITY_UPGRADE_RATE_USD_PER_MW,
        "commissioning_buffer_days": 90,
        "energization_lead_days": UTILITY_ENERGIZATION_LEAD_DAYS,
        "queue_policy": "FIRST_COME_FIRST_SERVED",
    }
    payload.update(overrides)
    return payload


def create_minimal_utility_payload(**overrides) -> dict:
    """Only the required fields, so the server must supply
    `commissioning_buffer_days` 90 and `queue_policy`
    `FIRST_COME_FIRST_SERVED` itself."""
    payload = {
        "name": UTILITY_NAME,
        "state_code": UTILITY_STATE_CODE,
        "balancing_authority": UTILITY_BALANCING_AUTHORITY,
        "total_transmission_capacity_mw": UTILITY_TOTAL_CAPACITY_MW,
        "interconnect_study_fee_per_mw_usd": UTILITY_STUDY_FEE_PER_MW_USD,
        "network_upgrade_rate_usd_per_mw": UTILITY_UPGRADE_RATE_USD_PER_MW,
        "energization_lead_days": UTILITY_ENERGIZATION_LEAD_DAYS,
    }
    payload.update(overrides)
    return payload


def create_water_source_payload(**overrides) -> dict:
    payload = {
        "name": WATER_SOURCE_NAME,
        "basin_code": WATER_SOURCE_BASIN_CODE,
        "state_code": UTILITY_STATE_CODE,
        "annual_permitted_mgal": WATER_SOURCE_ANNUAL_PERMITTED_MGAL,
    }
    payload.update(overrides)
    return payload


def create_drought_declaration_payload(
    drought_stage: str, effective_date: str, **overrides
) -> dict:
    payload = {"drought_stage": drought_stage, "effective_date": effective_date}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# candidate sites
# --------------------------------------------------------------------------- #
def create_candidate_site_payload(
    program_id: str, utility_id: str, water_source_id: str, **overrides
) -> dict:
    payload = {
        "program_id": program_id,
        "utility_id": utility_id,
        "water_source_id": water_source_id,
        "name": SITE_NAME,
        "state_code": SITE_STATE_CODE,
        "county": SITE_COUNTY,
        "gross_acres": SITE_GROSS_ACRES,
    }
    payload.update(overrides)
    return payload


def create_screening_payload(**overrides) -> dict:
    """The ten screening measurements of §3.2."""
    payload = dict(SCREEN_EVAPORATIVE)
    payload.update(overrides)
    return payload


def create_disqualification_payload(
    disqualification_reason: str = "TRANSMISSION_RISK", **overrides
) -> dict:
    payload = {"disqualification_reason": disqualification_reason}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# interconnection applications and load studies
# --------------------------------------------------------------------------- #
def create_interconnection_application_payload(
    site_id: str, utility_id: str, **overrides
) -> dict:
    payload = {
        "site_id": site_id,
        "utility_id": utility_id,
        "requested_mw": APPLICATION_REQUESTED_MW,
        "window_start": APPLICATION_WINDOW_START,
        "window_end": APPLICATION_WINDOW_END,
    }
    payload.update(overrides)
    return payload


def create_load_study_payload(**overrides) -> dict:
    payload = dict(LOAD_STUDY_BASE)
    payload.update(overrides)
    return payload


def create_energization_commitment_payload(
    committed_energization_date: str, **overrides
) -> dict:
    payload = {"committed_energization_date": committed_energization_date}
    payload.update(overrides)
    return payload


def create_withdrawal_payload(
    withdrawal_reason: str = "SPONSOR_DEFERRED", **overrides
) -> dict:
    payload = {"withdrawal_reason": withdrawal_reason}
    payload.update(overrides)
    return payload


def create_capacity_revision_payload(
    revised_total_capacity_mw: float,
    reason: str = "Substation transformer derate",
    **overrides,
) -> dict:
    payload = {
        "revised_total_capacity_mw": revised_total_capacity_mw,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# zoning
# --------------------------------------------------------------------------- #
def create_zoning_application_payload(site_id: str, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "jurisdiction": "Rowan County Board",
        "hearing_date": "2027-03-15T00:00:00Z",
        "noise_limit_dba": 55,
        "projected_noise_dba": 62,
        "visual_mitigation_tier": "FULL_ENCLOSURE",
    }
    payload.update(overrides)
    return payload


def create_community_objection_payload(
    objection_type: str = "NOISE",
    commenter_reference: str = "COMMENT-001",
    **overrides,
) -> dict:
    payload = {
        "objection_type": objection_type,
        "commenter_reference": commenter_reference,
    }
    payload.update(overrides)
    return payload


def create_zoning_decision_payload(
    outcome: str = "APPROVED_WITH_CONDITIONS",
    decision_note: Optional[str] = "Approved with enclosure conditions.",
    **overrides,
) -> dict:
    payload = {"outcome": outcome}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# incentive negotiations
# --------------------------------------------------------------------------- #
def create_incentive_negotiation_payload(
    site_id: str, authority_level: str = "STATE", **overrides
) -> dict:
    payload = {
        "site_id": site_id,
        "authority_level": authority_level,
        "counterparty_name": "NC Dept of Commerce",
    }
    payload.update(overrides)
    return payload


def create_company_round_payload(**overrides) -> dict:
    payload = {"submitted_by_party": "COMPANY"}
    payload.update(COMPANY_TERMS)
    payload.update(overrides)
    return payload


def create_authority_round_payload(**overrides) -> dict:
    payload = {"submitted_by_party": "AUTHORITY"}
    payload.update(AUTHORITY_TERMS)
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# power purchase agreements
# --------------------------------------------------------------------------- #
def create_power_purchase_agreement_payload(program_id: str, **overrides) -> dict:
    payload = {"program_id": program_id}
    payload.update(PPA_AT_COVERAGE_FLOOR)
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# land parcel options
# --------------------------------------------------------------------------- #
def create_parcel_option_payload(
    site_id: str, expected_site_version: int, **overrides
) -> dict:
    """§2.10: `expected_site_version` "is not optional and has no default", so it
    is a positional argument here rather than a default."""
    payload = {
        "site_id": site_id,
        "parcel_apn": "APN-100",
        "phase_index": 1,
        "acres": 240,
        "option_premium_usd": 1250000,
        "purchase_price_usd": 42000000,
        "premium_credit_pct": 0.5,
        "window_start": "2027-01-01T00:00:00Z",
        "window_end": "2027-12-31T00:00:00Z",
        "expected_site_version": expected_site_version,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# the logical clock
# --------------------------------------------------------------------------- #
def create_clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


def omit(payload: dict, *keys: str) -> dict:
    """Return a copy of ``payload`` without the named keys.

    Used by the request-shape tests to drop a required field and by the
    default-value tests to leave an optional field for the server to fill in.
    """
    return {k: v for k, v in payload.items() if k not in keys}
