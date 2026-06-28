"""Appraisal validity windows and supersession; endorsement proration and the
draft-then-reject / deny compensating invariants on policy aggregates.

Design queue A: resource_temporal_overlap (appraisal window), compensating_invariant.
Design queue B: state_machines (appraisal supersede), calculations (add-item proration).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    set_clock,
    create_risk_zone,
    create_policyholder,
    create_appraisal,
    create_policy,
    create_scheduled_item,
    bind_policy,
    pay_premium,
    file_claim,
    draft_endorsement,
    live_policy_version,
    setup_active_policy_with_item,
    setup_claim_under_review,
)

_UW = TEST_USERS["underwriter_headers"]
_CA = TEST_USERS["claims_adjuster_headers"]
_AP = TEST_USERS["appraiser_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Queue A: resource_temporal_overlap — appraisal half-open validity window
# ─────────────────────────────────────────────────────────────────────────

def test_appraisal_expires_at_half_open_window_end(api):
    """PRD §3.1: "An appraisal opens in status VALID and remains valid over the half-open
    window beginning at effective_date_iso and ending the instant valid_months later — valid
    for instants at or after the effective date and strictly before the effective date plus
    valid_months. When the logical clock reaches or passes that window end, a clock advance
    moves the appraisal from VALID to EXPIRED."

    Design: Difficulty/resource_temporal_overlap/appraisal_validity_halfopen_window_expiry
    """
    set_clock("2026-01-01T00:00:00Z")
    ph = create_policyholder(email="ap@x.com", residence_zip="10001")
    appraisal = create_appraisal(ph["id"], appraised_value_cents=2000000,
                                 effective_date_iso="2026-01-01T00:00:00Z", valid_months=12)
    assert appraisal["status"] == "VALID"

    set_clock("2027-01-01T00:00:00Z")  # exactly window end -> EXPIRED
    after = validate_success(api.get_appraisal(appraisal["id"], _UW), 200)
    assert after["status"] == "EXPIRED"


def test_appraisal_remains_valid_before_window_end(api):
    """PRD §3.1: "remains valid over the half-open window beginning at effective_date_iso and
    ending the instant valid_months later — valid for instants at or after the effective date
    and strictly before the effective date plus valid_months."

    Design: Difficulty/resource_temporal_overlap/appraisal_validity_halfopen_window_expiry
    """
    set_clock("2026-01-01T00:00:00Z")
    ph = create_policyholder(email="ap2@x.com", residence_zip="10001")
    appraisal = create_appraisal(ph["id"], appraised_value_cents=2000000,
                                 effective_date_iso="2026-01-01T00:00:00Z", valid_months=12)
    set_clock("2026-12-31T00:00:00Z")  # one day before window end -> still VALID
    after = validate_success(api.get_appraisal(appraisal["id"], _UW), 200)
    assert after["status"] == "VALID"


# ─────────────────────────────────────────────────────────────────────────
# Queue A: compensating_invariant — endorsement reject conserves premium
# ─────────────────────────────────────────────────────────────────────────

def test_endorsement_reject_conserves_annual_premium(api):
    """PRD §3.9: "A draft endorsement may be rejected by an Underwriter, which moves it to the
    terminal REJECTED status and leaves the policy's annual_premium_cents untouched — the
    reject is a compensating no-op, so a draft followed by a reject leaves the premium exactly
    at its pre-draft value."

    Design: Difficulty/compensating_invariant/endorsement_reject_conserves_annual_premium
    """
    ctx = setup_active_policy_with_item()
    pol = ctx["policy"]
    assert pol["annual_premium_cents"] == 3947  # RING cv 1,000,000, rate 300, ALL_RISK, STANDARD
    # Draft an ADD_ITEM endorsement for a second item, then reject it.
    it2 = create_scheduled_item(pol["id"], description="Ring 2", category="RING",
                                location_zip="10001", scheduled_value_cents=800000)
    end = draft_endorsement(pol["id"], "ADD_ITEM", target_item_id=it2["id"])
    rejected = validate_success(api.reject_endorsement(pol["id"], end["id"], _UW), 200)
    assert rejected["status"] == "REJECTED"

    after = validate_success(api.get_policy(pol["id"], _UW), 200)
    assert after["annual_premium_cents"] == 3947


def test_endorsement_reject_is_terminal_and_premium_unchanged(api):
    """PRD §3.9: "the reject is a compensating no-op, so a draft followed by a reject leaves
    the premium exactly at its pre-draft value."
    PRD §3.9: "which moves it to the terminal REJECTED status and leaves the policy's
    annual_premium_cents untouched"

    Design: Difficulty/compensating_invariant/endorsement_reject_conserves_annual_premium
    """
    ctx = setup_active_policy_with_item()
    pol = ctx["policy"]
    premium_before = validate_success(api.get_policy(pol["id"], _UW), 200)["annual_premium_cents"]
    it2 = create_scheduled_item(pol["id"], description="Ring 2", category="RING",
                                location_zip="10001", scheduled_value_cents=500000)
    end = draft_endorsement(pol["id"], "ADD_ITEM", target_item_id=it2["id"])
    validate_success(api.reject_endorsement(pol["id"], end["id"], _UW), 200)
    premium_after = validate_success(api.get_policy(pol["id"], _UW), 200)["annual_premium_cents"]
    assert premium_after == premium_before


# ─────────────────────────────────────────────────────────────────────────
# Queue A: compensating_invariant — claim deny conserves insured value
# ─────────────────────────────────────────────────────────────────────────

def test_claim_deny_returns_item_to_active_and_conserves_insured_value(api):
    """PRD §3.11: "Denial moves the claim to the terminal DENIED status, unlocks the
    referenced item by returning it from SUSPENDED to ACTIVE, and leaves settlement_cents at
    zero"
    PRD §3.4: "The policy's total_insured_value_cents is the sum of current_value_cents over
    those same ACTIVE-or-SUSPENDED items."

    Design: Difficulty/compensating_invariant/claim_deny_conserves_total_insured_value
    """
    ctx = setup_claim_under_review()  # item SUSPENDED, TIV unchanged (SUSPENDED counts)
    pol, claim, item = ctx["policy"], ctx["claim"], ctx["item"]
    denied = validate_success(api.deny_claim(pol["id"], claim["id"], _CA), 200)
    assert denied["status"] == "DENIED"

    item_after = validate_success(api.get_scheduled_item(item["id"], _UW), 200)
    assert item_after["item_status"] == "ACTIVE"
    pol_after = validate_success(api.get_policy(pol["id"], _UW), 200)
    assert pol_after["total_insured_value_cents"] == 1000000


def test_claim_deny_keeps_settlement_zero(api):
    """PRD §3.11: "Denial moves the claim to the terminal DENIED status, unlocks the
    referenced item by returning it from SUSPENDED to ACTIVE, and leaves settlement_cents at
    zero"

    Design: Difficulty/compensating_invariant/claim_deny_conserves_total_insured_value
    """
    ctx = setup_claim_under_review()
    pol, claim = ctx["policy"], ctx["claim"]
    denied = validate_success(api.deny_claim(pol["id"], claim["id"], _CA), 200)
    assert denied["settlement_cents"] == 0
    pol_after = validate_success(api.get_policy(pol["id"], _UW), 200)
    assert pol_after["total_insured_value_cents"] == 1000000


# ─────────────────────────────────────────────────────────────────────────
# Queue B: state_machines — appraisal supersession
# ─────────────────────────────────────────────────────────────────────────

def test_newer_appraisal_supersedes_prior_on_same_item(api):
    """PRD §3.1: "When a newer valid appraisal is attached to the same scheduled item, the
    prior one moves from VALID to SUPERSEDED."

    Design: Corner/state_machines/appraisal_supersede_on_reappraisal
    """
    set_clock("2026-02-01T00:00:00Z")
    create_risk_zone(zip_prefix="100", risk_band="MODERATE", rate_per_thousand_cents=300)
    ph = create_policyholder(email="s7@x.com", residence_zip="10001")
    ap1 = create_appraisal(ph["id"], appraised_value_cents=2000000,
                           effective_date_iso="2026-01-10T00:00:00Z")
    policy = create_policy(ph["id"], coverage_type="ALL_RISK",
                           valuation_basis="AGREED_VALUE", deductible_option="STANDARD")
    create_scheduled_item(policy["id"], description="Big ring", category="RING",
                          location_zip="10001", scheduled_value_cents=2000000,
                          appraisal_id=ap1["id"])
    ap2 = create_appraisal(ph["id"], appraised_value_cents=2200000,
                           effective_date_iso="2026-01-20T00:00:00Z")
    create_scheduled_item(policy["id"], description="Big ring", category="RING",
                          location_zip="10001", scheduled_value_cents=2200000,
                          appraisal_id=ap2["id"])

    ap1_after = validate_success(api.get_appraisal(ap1["id"], _UW), 200)
    ap2_after = validate_success(api.get_appraisal(ap2["id"], _UW), 200)
    assert ap1_after["status"] == "SUPERSEDED"
    assert ap2_after["status"] == "VALID"


# ─────────────────────────────────────────────────────────────────────────
# Queue B: calculations — add-item endorsement proration
# ─────────────────────────────────────────────────────────────────────────

def test_add_item_endorsement_prorated_delta_applied(api):
    """PRD §3.10: "For an ADD_ITEM endorsement, compute the target item's full annual premium
    (per §3.4) and set premium_delta_cents to that figure multiplied by the proration fraction,
    rounded half up."
    PRD §3.9: "An ADD_ITEM apply transitions its target scheduled item from PENDING to ACTIVE."

    Design: Corner/calculations/endorsement_add_item_proration_applied
    """
    set_clock("2026-02-01T00:00:00Z")
    create_risk_zone(zip_prefix="100", risk_band="MODERATE", rate_per_thousand_cents=300)
    create_risk_zone(zip_prefix="500", risk_band="MODERATE", rate_per_thousand_cents=160)
    ph = create_policyholder(email="c2@x.com", residence_zip="10001")
    policy = create_policy(ph["id"], coverage_type="ALL_RISK",
                           valuation_basis="AGREED_VALUE", deductible_option="LOW")
    create_scheduled_item(policy["id"], description="Ring", category="RING",
                          location_zip="10001", scheduled_value_cents=1000000)
    bind_policy(policy["id"])
    pay_premium(policy["id"], ph["id"])
    it2 = create_scheduled_item(policy["id"], description="Necklace", category="NECKLACE",
                                location_zip="50001", scheduled_value_cents=800000)
    end = draft_endorsement(policy["id"], "ADD_ITEM", target_item_id=it2["id"])

    set_clock("2026-04-15T00:00:00Z")  # 73 days into policy year
    pol_v = live_policy_version(policy["id"])
    applied = validate_success(
        api.apply_endorsement(policy["id"], end["id"],
                              {"expected_policy_version": pol_v}, _UW), 200)
    assert applied["premium_delta_cents"] == 2000
    assert applied["status"] == "APPLIED"

    item_after = validate_success(api.get_scheduled_item(it2["id"], _UW), 200)
    assert item_after["item_status"] == "ACTIVE"
