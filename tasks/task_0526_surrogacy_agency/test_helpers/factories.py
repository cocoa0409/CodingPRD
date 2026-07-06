"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "IP_LEGAL_NAME": "Test Intended Parent",
    "CARRIER_LEGAL_NAME": "Test Carrier",
    "STATE_CODE": "CA",
    "CARRIER_STATE_CODE": "TX",
    "IP_BUDGET_CENTS": 6_000_000,
    "CARRIER_PRIOR_DELIVERIES": 2,
    "CARRIER_BASE_COMP_CENTS": 4_000_000,
    "DONOR_CODE": "D-001",
    "DONOR_COMP_CENTS": 800_000,
    "PROPOSED_CARRIER_COMP_CENTS": 4_000_000,
}


def create_intended_parent_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["IP_LEGAL_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "budget_cents": DEFAULTS["IP_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_carrier_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["CARRIER_LEGAL_NAME"],
        "state_code": DEFAULTS["CARRIER_STATE_CODE"],
        "prior_deliveries": DEFAULTS["CARRIER_PRIOR_DELIVERIES"],
        "base_compensation_cents": DEFAULTS["CARRIER_BASE_COMP_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_egg_donor_payload(**overrides) -> dict:
    defaults = {
        "donor_code": DEFAULTS["DONOR_CODE"],
        "state_code": DEFAULTS["CARRIER_STATE_CODE"],
        "donor_compensation_cents": DEFAULTS["DONOR_COMP_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_insurance_review_payload(carrier_id, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "policy_kind": "SURROGACY_FRIENDLY",
    }
    defaults.update(overrides)
    return defaults


def create_match_payload(intended_parent_id, carrier_id, **overrides) -> dict:
    defaults = {
        "intended_parent_id": intended_parent_id,
        "carrier_id": carrier_id,
        "proposed_carrier_comp_cents": DEFAULTS["PROPOSED_CARRIER_COMP_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(match_id, **overrides) -> dict:
    defaults = {"match_id": match_id}
    defaults.update(overrides)
    return defaults


def create_journey_payload(match_id, **overrides) -> dict:
    defaults = {"match_id": match_id}
    defaults.update(overrides)
    return defaults


def create_milestone_payload(milestone_type, scheduled_utc="2026-05-15T00:00:00Z", **overrides) -> dict:
    defaults = {
        "milestone_type": milestone_type,
        "scheduled_utc": scheduled_utc,
    }
    defaults.update(overrides)
    return defaults


def create_comp_schedule_payload(trigger_milestone_type, recipient, amount_cents, **overrides) -> dict:
    defaults = {
        "trigger_milestone_type": trigger_milestone_type,
        "recipient": recipient,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_disbursement_payload(schedule_id, escrow_account_id, **overrides) -> dict:
    defaults = {
        "schedule_id": schedule_id,
        "escrow_account_id": escrow_account_id,
    }
    defaults.update(overrides)
    return defaults


def deposit_payload(amount_cents, expected_escrow_version, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "expected_escrow_version": expected_escrow_version,
    }
    defaults.update(overrides)
    return defaults


def set_psych_payload(psych_clearance="PASSED", **overrides) -> dict:
    defaults = {"psych_clearance": psych_clearance}
    defaults.update(overrides)
    return defaults


def parentage_decide_payload(decision="GRANTED", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults
