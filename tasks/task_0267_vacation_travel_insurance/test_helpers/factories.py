"""Payload factories — one per entity, input fields only.

All amounts are whole integer cents (PRD §2.6). Each factory provides the
full set of REQUIRED input fields; optional fields are added only via overrides
so that "missing required field" tests can delete them cleanly.
"""
from .constants import STANDARD_PLAN, TEST_DEFAULTS

_PLAN_COUNTER = {"n": 0}


def _next_code(prefix="PLAN"):
    _PLAN_COUNTER["n"] += 1
    return f"{prefix}-{_PLAN_COUNTER['n']:05d}"


def create_plan_payload(**overrides) -> dict:
    """Required Plan input fields (§3.1). senior_age_threshold is optional (default 70)."""
    defaults = {
        "code": _next_code(),
        "tier": STANDARD_PLAN["tier"],
        "base_rate_bps": STANDARD_PLAN["base_rate_bps"],
        "cancellation_limit_pct": STANDARD_PLAN["cancellation_limit_pct"],
        "medical_limit_cents": STANDARD_PLAN["medical_limit_cents"],
        "delay_block_cap_cents": STANDARD_PLAN["delay_block_cap_cents"],
        "delay_limit_cents": STANDARD_PLAN["delay_limit_cents"],
        "baggage_item_sublimit_cents": STANDARD_PLAN["baggage_item_sublimit_cents"],
        "baggage_limit_cents": STANDARD_PLAN["baggage_limit_cents"],
        "baggage_depreciation_bps": STANDARD_PLAN["baggage_depreciation_bps"],
        "waiver_window_days": STANDARD_PLAN["waiver_window_days"],
        "free_look_days": STANDARD_PLAN["free_look_days"],
        "claim_filing_window_days": STANDARD_PLAN["claim_filing_window_days"],
        "cfar_loading_bps": STANDARD_PLAN["cfar_loading_bps"],
        "cfar_reimbursement_pct": STANDARD_PLAN["cfar_reimbursement_pct"],
        "senior_loading_bps": STANDARD_PLAN["senior_loading_bps"],
    }
    defaults.update(overrides)
    return defaults


_TRAVELER_COUNTER = {"n": 0}


def create_traveler_payload(**overrides) -> dict:
    """Required Traveler input fields (§3.1)."""
    _TRAVELER_COUNTER["n"] += 1
    n = _TRAVELER_COUNTER["n"]
    defaults = {
        "email": f"traveler-{n:05d}@example.com",
        "full_name": f"Test Traveler {n}",
        "date_of_birth": "1990-01-01",
    }
    defaults.update(overrides)
    return defaults


_STORM_COUNTER = {"n": 0}


def create_named_storm_payload(**overrides) -> dict:
    """Required NamedStorm input fields (§3.1)."""
    _STORM_COUNTER["n"] += 1
    n = _STORM_COUNTER["n"]
    defaults = {
        "name": f"Storm-{n:05d}",
        "basin": "ATLANTIC",
        "named_at": "2026-06-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(plan_id: str, owner_traveler_id: str, **overrides) -> dict:
    """Required Policy input fields (§3.2). cfar_opted is optional (default false)."""
    defaults = {
        "plan_id": plan_id,
        "owner_traveler_id": owner_traveler_id,
        "trip_cost_cents": TEST_DEFAULTS["TRIP_COST_CENTS"],
        "initial_deposit_at": TEST_DEFAULTS["INITIAL_DEPOSIT_AT"],
        "trip_start_at": TEST_DEFAULTS["TRIP_START_AT"],
        "trip_end_at": TEST_DEFAULTS["TRIP_END_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_insured_traveler_payload(traveler_id: str, **overrides) -> dict:
    """Required InsuredTraveler input fields (§3.2). has_preexisting_condition optional (default false)."""
    defaults = {
        "traveler_id": traveler_id,
        "age_at_departure": TEST_DEFAULTS["ADULT_AGE"],
        "covered_trip_cost_cents": TEST_DEFAULTS["TRIP_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def record_payment_payload(expected_policy_version: int, **overrides) -> dict:
    """Required record-payment input (§2.9): expected_policy_version is mandatory."""
    defaults = {"expected_policy_version": expected_policy_version}
    defaults.update(overrides)
    return defaults


def create_claim_payload(policy_id: str, insured_traveler_id: str, peril: str,
                         incident_at: str, **overrides) -> dict:
    """Required Claim input fields (§3.4). Conditional fields (named_storm_id,
    cancellation_reason, delay_hours, involves_preexisting) supplied via overrides."""
    defaults = {
        "policy_id": policy_id,
        "insured_traveler_id": insured_traveler_id,
        "peril": peril,
        "incident_at": incident_at,
    }
    defaults.update(overrides)
    return defaults


def create_expense_payload(category: str, description: str,
                           documented_amount_cents: int, **overrides) -> dict:
    """Required ClaimExpense input fields (§3.4). prepaid_nonrefundable_cents,
    supplier_refund_received_cents, item_value_cents are optional (default 0)."""
    defaults = {
        "category": category,
        "description": description,
        "documented_amount_cents": documented_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(doc_type: str, file_ref: str, **overrides) -> dict:
    """Required ClaimDocument input fields (§3.4)."""
    defaults = {
        "doc_type": doc_type,
        "file_ref": file_ref,
    }
    defaults.update(overrides)
    return defaults


def create_payout_payload(claim_id: str, **overrides) -> dict:
    """Required Payout input field (§3.8)."""
    defaults = {"claim_id": claim_id}
    defaults.update(overrides)
    return defaults


def deny_payload(denial_reason: str = "INSUFFICIENT_PROOF", **overrides) -> dict:
    """Required deny input field (§3.6): denial_reason."""
    defaults = {"denial_reason": denial_reason}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    """Required clock input field (§3.1)."""
    return {"to_iso8601": to_iso8601}
