"""Payload factories - one per resource, input fields only.

The defaults spell out the canonical builders risk account used across the
suite: a NON_COMBUSTIBLE new-construction project in WIND_TIER_2 with a
$20,000,000 hard cost, insured for a 302-day term under an ELEVATED_100K
deductible tier.
"""
import itertools

DEFAULTS = {
    "PROJECT_NAME": "Harborline Logistics Center",
    "SITE_ADDRESS": "410 Dock Rd, Newport",
    "CONSTRUCTION_TYPE": "NON_COMBUSTIBLE",
    "PROJECT_KIND": "NEW_CONSTRUCTION",
    "HARD_COST_VALUE_CENTS": 2000000000,
    "CAT_ZONE": "WIND_TIER_2",
    "PLANNED_START_DATE": "2026-09-01T00:00:00Z",
    "PROJECTED_COMPLETION_DATE": "2027-06-01T00:00:00Z",
    "TERM_START_DATE": "2026-09-01T00:00:00Z",
    "TERM_END_DATE": "2027-06-30T00:00:00Z",
    "DEDUCTIBLE_TIER": "ELEVATED_100K",
    "LIMIT_CENTS": 2500000000,
    "DAILY_DELAY_RATE_CENTS": 1200000,
    "MATERIALS_SUBLIMIT_CENTS": 1000000000,
    "PARTY_NAME": "Harborline Owner LLC",
    "FACILITY_CAPACITY_CENTS": 800000000,
    "FACILITY_DISTANCE_MILES": 22.5,
}

_site_code_counter = itertools.count(1)


def unique_site_code(prefix: str = "WH") -> str:
    """Facility site codes are unique across every facility on the books."""
    return f"{prefix}-{next(_site_code_counter):04d}"


def create_project_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PROJECT_NAME"],
        "site_address": DEFAULTS["SITE_ADDRESS"],
        "construction_type": DEFAULTS["CONSTRUCTION_TYPE"],
        "project_kind": DEFAULTS["PROJECT_KIND"],
        "hard_cost_value_cents": DEFAULTS["HARD_COST_VALUE_CENTS"],
        "cat_zone": DEFAULTS["CAT_ZONE"],
        "planned_start_date": DEFAULTS["PLANNED_START_DATE"],
        "projected_completion_date": DEFAULTS["PROJECTED_COMPLETION_DATE"],
    }
    payload.update(overrides)
    return payload


def screen_project_payload(**overrides) -> dict:
    payload = {"engineering_grade": "B"}
    payload.update(overrides)
    return payload


def substantial_completion_payload(actual_substantial_completion_date, **overrides) -> dict:
    payload = {
        "actual_substantial_completion_date": actual_substantial_completion_date}
    payload.update(overrides)
    return payload


def create_policy_payload(project_id, expected_project_version, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "expected_project_version": expected_project_version,
        "term_start_date": DEFAULTS["TERM_START_DATE"],
        "term_end_date": DEFAULTS["TERM_END_DATE"],
        "includes_existing_structure": False,
        "deductible_tier": DEFAULTS["DEDUCTIBLE_TIER"],
        "limit_cents": DEFAULTS["LIMIT_CENTS"],
        "daily_delay_rate_cents": DEFAULTS["DAILY_DELAY_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_coverage_part_payload(policy_id, part_type="MATERIALS_ON_SITE",
                                 sublimit_cents=None, **overrides) -> dict:
    payload = {
        "policy_id": policy_id,
        "part_type": part_type,
        "sublimit_cents": (DEFAULTS["MATERIALS_SUBLIMIT_CENTS"]
                           if sublimit_cents is None else sublimit_cents),
    }
    payload.update(overrides)
    return payload


def create_interest_payload(policy_id, party_role="OWNER",
                           insurable_interest_pct=100, **overrides) -> dict:
    payload = {
        "policy_id": policy_id,
        "party_name": DEFAULTS["PARTY_NAME"],
        "party_role": party_role,
        "insurable_interest_pct": insurable_interest_pct,
    }
    payload.update(overrides)
    return payload


def create_endorsement_payload(policy_id, expected_policy_version,
                               requested_extension_days,
                               revised_completion_date, **overrides) -> dict:
    payload = {
        "policy_id": policy_id,
        "expected_policy_version": expected_policy_version,
        "requested_extension_days": requested_extension_days,
        "slip_reason": "WEATHER",
        "revised_completion_date": revised_completion_date,
    }
    payload.update(overrides)
    return payload


def resubmit_endorsement_payload(requested_extension_days,
                                 revised_completion_date, **overrides) -> dict:
    payload = {
        "requested_extension_days": requested_extension_days,
        "revised_completion_date": revised_completion_date,
    }
    payload.update(overrides)
    return payload


def create_claim_payload(policy_id, peril="FIRE",
                         loss_date="2027-02-10T00:00:00Z", **overrides) -> dict:
    payload = {
        "policy_id": policy_id,
        "peril": peril,
        "loss_date": loss_date,
        "description": "Loss reported by the site contact at first notice",
    }
    payload.update(overrides)
    return payload


def adjust_claim_payload(outcome="ADJUST", adjustment_basis="ACTUAL_LOSS",
                         loss_items=None, **overrides) -> dict:
    payload = {"outcome": outcome}
    if outcome == "ADJUST":
        payload["adjustment_basis"] = adjustment_basis
        if loss_items is not None:
            payload["loss_items"] = loss_items
    payload.update(overrides)
    return payload


def loss_item(part_type, gross_loss_cents) -> dict:
    return {"part_type": part_type, "gross_loss_cents": gross_loss_cents}


def create_loss_payment_payload(claim_id, expected_claim_version, payee_interest_id,
                                part_type, amount_cents, **overrides) -> dict:
    payload = {
        "claim_id": claim_id,
        "expected_claim_version": expected_claim_version,
        "payee_interest_id": payee_interest_id,
        "part_type": part_type,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


def create_testing_notice_payload(project_id, window_start, window_end,
                                  system_type="SPRINKLER_HYDROSTATIC", **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "system_type": system_type,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def create_facility_payload(**overrides) -> dict:
    payload = {
        "name": "Newport Bonded Warehouse",
        "site_code": unique_site_code(),
        "distance_from_site_miles": DEFAULTS["FACILITY_DISTANCE_MILES"],
        "aggregate_capacity_cents": DEFAULTS["FACILITY_CAPACITY_CENTS"],
        "protection_class": "SPRINKLERED",
    }
    payload.update(overrides)
    return payload


def create_storage_assignment_payload(policy_id, facility_id, stored_value_cents,
                                      window_start, window_end, **overrides) -> dict:
    payload = {
        "policy_id": policy_id,
        "facility_id": facility_id,
        "stored_value_cents": stored_value_cents,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def cancel_policy_payload(cancel_reason, cancel_effective_date, **overrides) -> dict:
    payload = {
        "cancel_reason": cancel_reason,
        "cancel_effective_date": cancel_effective_date,
    }
    payload.update(overrides)
    return payload
