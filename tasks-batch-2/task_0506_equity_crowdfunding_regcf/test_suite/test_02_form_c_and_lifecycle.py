"""Form C disclosure cycle, offering state transitions, branching FUNDED/FAILED,
cross-entity go-live guard, and Reg A+ secondary listing.

Queue-A: non_linear_state_machine, cross_entity_state_dependency (go-live), branching.
Queue-B: state_machines + endpoints + validations corners.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_anonymous_headers, make_issuer_headers, make_compliance_officer_headers,
    create_offering_payload,
    create_issuer, create_verified_issuer, create_draft_offering,
    create_qualified_offering, create_live_offering,
    setup_funded_offering, setup_committed_offering,
    create_accredited_investor, set_clock, commit, get_cap_table_list,
)

ANON = make_anonymous_headers()
CO = make_compliance_officer_headers()


# ============================================================================
# Form C cyclic revision loop (queue A: non_linear_state_machine)
# ============================================================================

def test_form_c_reject_resubmit_then_qualify(api):
    """PRD §3.2: "A `REJECTED` disclosure may be revised and resubmitted, advancing
    `REJECTED → SUBMITTED`, and this revision loop may repeat."
    PRD §3.2: "A `ComplianceOfficer` then reviews a `SUBMITTED` disclosure: qualifying it advances
    `SUBMITTED → QUALIFIED`, while rejecting it advances `SUBMITTED → REJECTED`."

    Design: Difficulty/non_linear_state_machine/form_c_cyclic_reject_resubmit_loop_on_offering
    """
    issuer = create_verified_issuer(legal_name="Loop Co")
    issuer_headers = make_issuer_headers(issuer["id"])
    offering = create_draft_offering(issuer["id"], min_target_cents=100_000,
                                     max_target_cents=1_000_000, deadline_at="2026-12-01T00:00:00Z")
    validate_success(api.submit_form_c(offering["id"], headers=issuer_headers))
    validate_success(api.reject_form_c(offering["id"], headers=CO))
    validate_success(api.submit_form_c(offering["id"], headers=issuer_headers))
    final = validate_success(api.qualify_form_c(offering["id"], headers=CO))
    assert final["form_c_status"] == "QUALIFIED"


def test_form_c_loops_through_submitted_twice_before_qualified(api):
    """PRD §3.2: "A `ComplianceOfficer` then reviews a `SUBMITTED` disclosure: qualifying it
    advances `SUBMITTED → QUALIFIED`, while rejecting it advances `SUBMITTED → REJECTED`."
    PRD §3.2: "A `REJECTED` disclosure may be revised and resubmitted, advancing
    `REJECTED → SUBMITTED`, and this revision loop may repeat."

    Design: Difficulty/non_linear_state_machine/form_c_cyclic_reject_resubmit_loop_on_offering
    """
    issuer = create_verified_issuer(legal_name="Loop2 Co")
    issuer_headers = make_issuer_headers(issuer["id"])
    offering = create_draft_offering(issuer["id"])
    # First submit -> reject
    s1 = validate_success(api.submit_form_c(offering["id"], headers=issuer_headers))
    assert s1["form_c_status"] == "SUBMITTED"
    r1 = validate_success(api.reject_form_c(offering["id"], headers=CO))
    assert r1["form_c_status"] == "REJECTED"
    # Resubmit (REJECTED -> SUBMITTED) then qualify
    s2 = validate_success(api.submit_form_c(offering["id"], headers=issuer_headers))
    assert s2["form_c_status"] == "SUBMITTED"
    q = validate_success(api.qualify_form_c(offering["id"], headers=CO))
    assert q["form_c_status"] == "QUALIFIED"


# ============================================================================
# Offering branching LIVE -> FUNDED vs FAILED (queue A)
# ============================================================================

def test_offering_branches_to_funded_when_minimum_met(api):
    """PRD §3.6: "A final close, when the minimum is met, advances `LIVE → FUNDED`, sets the
    offering's `close_at` to the current logical-clock instant, and is gated on the offering being
    `LIVE` with a `form_c_status` of `QUALIFIED` (not pending a material-amendment
    re-qualification)."

    Design: Difficulty/non_linear_state_machine/offering_branching_live_to_funded_vs_failed
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Fork P Co")
    investor = create_accredited_investor()
    offering = create_live_offering(issuer["id"], min_target_cents=500_000,
                                    max_target_cents=2_000_000, deadline_at="2026-08-01T00:00:00Z")
    _, offering = commit(offering, investor["id"], 600_000)
    issuer_headers = make_issuer_headers(issuer["id"])
    closed = validate_success(api.close_offering(offering["id"], headers=issuer_headers))
    assert closed["status"] == "FUNDED"


def test_offering_branches_to_failed_when_minimum_not_met(api):
    """PRD §3.5: "An offering moves `LIVE → FAILED` when a final close is attempted (or the
    deadline passes) and the minimum cannot be met — that is, when its `swept_amount_cents` plus
    its `committed_amount_cents` is less than `min_target_cents`. On failure, every investment on
    the offering in `COMMITTED` or `RECONFIRMED` status moves to `REFUNDED` with its
    `refund_amount_cents` set to the full `amount_cents` and that amount credited to the investor's
    wallet".

    Design: Difficulty/non_linear_state_machine/offering_branching_live_to_funded_vs_failed
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Fork Q Co")
    investor = create_accredited_investor()
    offering = create_live_offering(issuer["id"], min_target_cents=500_000,
                                    max_target_cents=2_000_000, deadline_at="2026-09-15T00:00:00Z")
    investment, offering = commit(offering, investor["id"], 100_000)
    issuer_headers = make_issuer_headers(issuer["id"])
    closed = validate_success(api.close_offering(offering["id"], headers=issuer_headers))
    assert closed["status"] == "FAILED"
    inv = validate_success(api.get_investment(investment["id"], headers=issuer_headers))
    assert inv["status"] == "REFUNDED"
    assert inv["refund_amount_cents"] == 100_000


# ============================================================================
# Cross-entity state dependency: go-live requires VERIFIED issuer (queue A)
# ============================================================================

def test_golive_requires_issuer_verified(api):
    """PRD §3.3: "its parent issuer must be in the `VERIFIED` status, with a failure here rejected
    as `ERR_ISSUER_NOT_VERIFIED`".

    Design: Difficulty/cross_entity_state_dependency/offering_golive_requires_issuer_verified
    """
    # Issuer left in ONBOARDING (NOT verified); offering Form C qualified.
    issuer = create_issuer(legal_name="Unv Co")
    issuer_headers = make_issuer_headers(issuer["id"])
    offering = create_draft_offering(issuer["id"])
    validate_success(api.submit_form_c(offering["id"], headers=issuer_headers))
    validate_success(api.qualify_form_c(offering["id"], headers=CO))
    resp = api.go_live(offering["id"], headers=issuer_headers)
    validate_error(resp, ApiErrorId.ERR_ISSUER_NOT_VERIFIED, expected_status=409)
    after = validate_success(api.get_offering(offering["id"], headers=issuer_headers))
    assert after["status"] == "DRAFT"


def test_golive_unverified_issuer_offering_stays_draft(api):
    """PRD §3.3: "its parent issuer must be in the `VERIFIED` status, with a failure here rejected
    as `ERR_ISSUER_NOT_VERIFIED`".
    PRD §3.1: "Only a `VERIFIED` issuer may take an offering live."

    Design: Difficulty/cross_entity_state_dependency/offering_golive_requires_issuer_verified
    """
    issuer = create_issuer(legal_name="Unv2 Co")
    issuer_headers = make_issuer_headers(issuer["id"])
    offering = create_draft_offering(issuer["id"])
    validate_success(api.submit_form_c(offering["id"], headers=issuer_headers))
    validate_success(api.qualify_form_c(offering["id"], headers=CO))
    resp = api.go_live(offering["id"], headers=issuer_headers)
    validate_error(resp, ApiErrorId.ERR_ISSUER_NOT_VERIFIED, expected_status=409)
    after = validate_success(api.get_offering(offering["id"], headers=issuer_headers))
    assert after["status"] == "DRAFT"
    assert after["live_at"] in (None, "")


# ============================================================================
# State-machine corners (queue B)
# ============================================================================

def test_verify_issuer_twice_second_returns_invalid_state(api):
    """PRD §2.8: "then whether the target is in a legal state for the requested transition
    (`ERR_INVALID_STATE`)."
    PRD §3.1: "A `ComplianceOfficer` reviews an `ONBOARDING` issuer and either verifies it,
    advancing it `ONBOARDING → VERIFIED`".

    Design: Corner/state_machines/verify_issuer_twice_second_returns_invalid_state
    """
    issuer = create_verified_issuer(legal_name="Idv Co")
    resp = api.verify_issuer(issuer["id"], headers=CO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_issuer(issuer["id"], headers=CO))
    assert after["status"] == "VERIFIED"


def test_golive_without_qualified_form_c_returns_invalid_state(api):
    """PRD §3.3: "Going live is gated on four conditions: the offering must currently be in
    `DRAFT`; its `form_c_status` must be `QUALIFIED`".

    Design: Corner/state_machines/golive_from_draft_without_qualified_form_c_returns_invalid_state
    """
    issuer = create_verified_issuer(legal_name="Gd Co")
    issuer_headers = make_issuer_headers(issuer["id"])
    offering = create_draft_offering(issuer["id"])  # Form C still DRAFT
    resp = api.go_live(offering["id"], headers=issuer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_offering(offering["id"], headers=issuer_headers))
    assert after["status"] == "DRAFT"


def test_cancel_terminal_funded_offering_returns_invalid_state(api):
    """PRD §3.5: "Cancelling a `LIVE` offering advances `LIVE → CANCELLED`".
    PRD §2.8: "then whether the target is in a legal state for the requested transition
    (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/cancel_terminal_funded_offering_returns_invalid_state
    """
    issuer, investor, offering, _ = setup_funded_offering(amount_cents=200_000)
    issuer_headers = make_issuer_headers(issuer["id"])
    resp = api.cancel_offering(offering["id"], headers=issuer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_offering(offering["id"], headers=issuer_headers))
    assert after["status"] == "FUNDED"


def test_reconfirm_not_required_investment_returns_invalid_state(api):
    """PRD §3.5: "The affected `Investor` reconfirms their own such investment, advancing it
    `COMMITTED → RECONFIRMED`; reconfirmation is permitted only when the investment is in
    `COMMITTED` and its `reconfirm_required` is `true`."

    Design: Corner/state_machines/reconfirm_not_required_investment_returns_invalid_state
    """
    from test_helpers import make_investor_headers
    issuer, investor, offering, investment = setup_committed_offering(amount_cents=300_000)
    # reconfirm_required is false (no amendment fired).
    resp = api.reconfirm_investment(investment["id"], headers=make_investor_headers(investor["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_investment(investment["id"], headers=make_issuer_headers(issuer["id"])))
    assert after["status"] == "COMMITTED"


# ============================================================================
# Reg A+ secondary listing (queue B endpoints + validations)
# ============================================================================

def test_enable_secondary_on_funded_reg_a_tier_2_succeeds(api):
    """PRD §3.7: "A `ComplianceOfficer` enables secondary listing on an offering, a self-loop that
    keeps the offering in `FUNDED` while setting its `secondary_listing_enabled` to `true` and
    incrementing its `version` by one. This is permitted only when the offering is in `FUNDED`,
    its `regulation` is `REG_A_TIER_2`, and its `secondary_listing_enabled` is currently `false`".

    Design: Corner/endpoints/enable_secondary_on_funded_reg_a_tier_2_succeeds
    """
    issuer, investor, offering, _ = setup_funded_offering(
        amount_cents=200_000, offering_overrides={"regulation": "REG_A_TIER_2"})
    data = validate_success(api.enable_secondary(offering["id"], headers=CO))
    assert data["secondary_listing_enabled"] is True
    assert data["status"] == "FUNDED"


def test_enable_secondary_on_reg_cf_returns_not_permitted(api):
    """PRD §3.7: "an attempt to enable secondary on an offering whose regulation is not
    `REG_A_TIER_2` is rejected with `ERR_SECONDARY_NOT_PERMITTED`."

    Design: Corner/endpoints/enable_secondary_on_reg_cf_returns_not_permitted
    """
    issuer, investor, offering, _ = setup_funded_offering(
        amount_cents=200_000, offering_overrides={"regulation": "REG_CF"})
    resp = api.enable_secondary(offering["id"], headers=CO)
    validate_error(resp, ApiErrorId.ERR_SECONDARY_NOT_PERMITTED, expected_status=422)
    issuer_headers = make_issuer_headers(issuer["id"])
    after = validate_success(api.get_offering(offering["id"], headers=issuer_headers))
    assert after["secondary_listing_enabled"] is False


# ============================================================================
# Consistency model (queue B)
# ============================================================================

def test_close_response_immediately_shows_funded(api):
    """PRD §3.6: "A final close, when the minimum is met, advances `LIVE → FUNDED`".
    PRD §3.6: "The offering's `swept_amount_cents` is advanced to the sum of `amount_cents` over
    its investments now in `ISSUED`".

    Design: Corner/consistency_model/immediate_visibility_of_status_after_close
    """
    issuer, investor, offering, _ = setup_committed_offering(
        amount_cents=200_000, offering_overrides={"min_target_cents": 100_000, "max_target_cents": 1_000_000})
    issuer_headers = make_issuer_headers(issuer["id"])
    closed = validate_success(api.close_offering(offering["id"], headers=issuer_headers))
    assert closed["status"] == "FUNDED"
    assert closed["swept_amount_cents"] == 200_000
