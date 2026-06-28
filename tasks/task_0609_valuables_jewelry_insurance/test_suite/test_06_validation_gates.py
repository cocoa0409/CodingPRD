"""Single-violation validation gates: claim filing on a non-active policy, named-peril and
worldwide coverage checks, no-op endorsement, item-locked-by-claim, bind preconditions,
open-claim-blocks-cancel, and the cross-entity start_review-requires-active-policy gate.

Design queue A: priority_pair_validation_conflict (state-beats-policy-not-active variant),
cross_entity_state_dependency (claim review requires active policy).
Design queue B: validations, state_machines.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_risk_zone,
    create_policyholder,
    create_policy,
    create_scheduled_item,
    bind_policy,
    pay_premium,
    file_claim,
    draft_endorsement,
    live_policy_version,
    setup_quoted_policy_with_item,
    setup_bound_policy_with_item,
    setup_active_policy_with_item,
    setup_claim_under_review,
    make_policyholder_headers,
)

_UW = TEST_USERS["underwriter_headers"]
_CA = TEST_USERS["claims_adjuster_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Queue A: priority_pair_validation_conflict (instance 1) — claim file on QUOTED
# ─────────────────────────────────────────────────────────────────────────

def test_file_claim_on_quoted_policy_returns_policy_not_active(api):
    """PRD §3.11: "Filing requires the parent policy's coverage_status to be ACTIVE, or the
    file is rejected with ERR_POLICY_NOT_ACTIVE."

    Design: Difficulty/priority_pair_validation_conflict/claim_file_state_beats_policy_not_active
    """
    ctx = setup_quoted_policy_with_item()  # never bound -> QUOTED
    res = api.create_claim(ctx["policy"]["id"],
                           {"scheduled_item_id": ctx["item"]["id"], "peril": "THEFT",
                            "loss_type": "TOTAL_LOSS", "claimed_amount_cents": 1000000}, _CA)
    validate_error(res, ApiErrorId.ERR_POLICY_NOT_ACTIVE, 409)


def test_file_claim_on_bound_unpaid_policy_returns_policy_not_active(api):
    """PRD §3.11: "Filing requires the parent policy's coverage_status to be ACTIVE, or the
    file is rejected with ERR_POLICY_NOT_ACTIVE."

    Design: Difficulty/priority_pair_validation_conflict/claim_file_state_beats_policy_not_active
    """
    ctx = setup_bound_policy_with_item()  # BOUND, never paid -> not ACTIVE
    res = api.create_claim(ctx["policy"]["id"],
                           {"scheduled_item_id": ctx["item"]["id"], "peril": "THEFT",
                            "loss_type": "TOTAL_LOSS", "claimed_amount_cents": 1000000}, _CA)
    validate_error(res, ApiErrorId.ERR_POLICY_NOT_ACTIVE, 409)


# ─────────────────────────────────────────────────────────────────────────
# Queue A: cross_entity_state_dependency — claim review requires active policy
# ─────────────────────────────────────────────────────────────────────────

def test_start_review_requires_active_policy_single_item(api):
    """PRD §3.11: "A ClaimsAdjuster begins adjudication by starting review, which moves the
    claim from FNOL to UNDER_REVIEW. Starting review enforces three checks. The parent policy
    must be ACTIVE, or it is rejected with ERR_POLICY_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/claim_review_requires_policy_active
    """
    # File an FNOL claim while ACTIVE, then cancel the policy — FNOL is not an open status
    # that blocks cancel (PRD §3.8), so coverage_status drops to CANCELLED. start_review then
    # finds the parent policy not ACTIVE and rejects.
    ctx = setup_active_policy_with_item()
    claim = file_claim(ctx["policy"]["id"], ctx["item"]["id"], peril="THEFT",
                       loss_type="TOTAL_LOSS", claimed_amount_cents=1000000)
    validate_success(api.cancel_policy(ctx["policy"]["id"], _UW), 200)  # coverage CANCELLED
    res = api.start_review_claim(ctx["policy"]["id"], claim["id"], _CA)
    validate_error(res, ApiErrorId.ERR_POLICY_NOT_ACTIVE, 409)


def test_start_review_requires_active_policy_partial_claim(api):
    """PRD §3.11: "Starting review enforces three checks. The parent policy must be ACTIVE,
    or it is rejected with ERR_POLICY_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/claim_review_requires_policy_active
    """
    # Same gate exercised for a PARTIAL_DAMAGE FNOL claim whose parent policy is cancelled
    # (coverage_status CANCELLED) before review begins.
    ctx = setup_active_policy_with_item()
    claim = file_claim(ctx["policy"]["id"], ctx["item"]["id"], peril="ACCIDENTAL_DAMAGE",
                       loss_type="PARTIAL_DAMAGE", claimed_amount_cents=300000)
    validate_success(api.cancel_policy(ctx["policy"]["id"], _UW), 200)
    res = api.start_review_claim(ctx["policy"]["id"], claim["id"], _CA)
    validate_error(res, ApiErrorId.ERR_POLICY_NOT_ACTIVE, 409)


# ─────────────────────────────────────────────────────────────────────────
# Queue B: validations
# ─────────────────────────────────────────────────────────────────────────

def test_named_peril_claim_peril_not_listed_rejected(api):
    """PRD §3.11: "For a NAMED_PERIL policy, the claim's peril must be among the policy's
    listed_perils, or it is rejected with ERR_PERIL_NOT_COVERED."

    Design: Corner/validations/named_peril_claim_peril_not_covered
    """
    ctx = setup_active_policy_with_item(policy_overrides={
        "coverage_type": "NAMED_PERIL", "listed_perils": ["THEFT"]})
    claim = file_claim(ctx["policy"]["id"], ctx["item"]["id"], peril="FIRE",
                       loss_type="TOTAL_LOSS", claimed_amount_cents=1000000)
    res = api.start_review_claim(ctx["policy"]["id"], claim["id"], _CA)
    validate_error(res, ApiErrorId.ERR_PERIL_NOT_COVERED, 409)


def test_worldwide_loss_without_coverage_rejected(api):
    """PRD §3.11: "If occurred_outside_country is true, the policy's worldwide_coverage must
    be true, or it is rejected with ERR_WORLDWIDE_NOT_COVERED."

    Design: Corner/validations/worldwide_loss_not_covered
    """
    ctx = setup_active_policy_with_item(policy_overrides={"worldwide_coverage": False})
    claim = file_claim(ctx["policy"]["id"], ctx["item"]["id"], peril="THEFT",
                       loss_type="TOTAL_LOSS", claimed_amount_cents=1000000,
                       occurred_outside_country=True)
    res = api.start_review_claim(ctx["policy"]["id"], claim["id"], _CA)
    validate_error(res, ApiErrorId.ERR_WORLDWIDE_NOT_COVERED, 409)


def test_change_deductible_no_op_rejected(api):
    """PRD §3.9: "For a CHANGE_DEDUCTIBLE endorsement, the new_deductible_option must differ
    from the policy's current option, or the apply is rejected with ERR_NO_OP_ENDORSEMENT."

    Design: Corner/validations/change_deductible_no_op_rejected
    """
    ctx = setup_active_policy_with_item(policy_overrides={"deductible_option": "STANDARD"})
    end = draft_endorsement(ctx["policy"]["id"], "CHANGE_DEDUCTIBLE",
                            new_deductible_option="STANDARD")
    pol_v = live_policy_version(ctx["policy"]["id"])
    res = api.apply_endorsement(ctx["policy"]["id"], end["id"],
                                {"expected_policy_version": pol_v}, _UW)
    validate_error(res, ApiErrorId.ERR_NO_OP_ENDORSEMENT, 422)


def test_remove_item_locked_by_open_claim_rejected(api):
    """PRD §3.9: "For a REMOVE_ITEM endorsement, the target item must not be locked by an open
    claim (an item suspended by an open claim), or the apply is rejected with
    ERR_ITEM_LOCKED_BY_CLAIM."

    Design: Corner/validations/item_locked_by_claim_removal_rejected
    """
    set_clock("2026-02-01T00:00:00Z")
    create_risk_zone(zip_prefix="100", risk_band="MODERATE", rate_per_thousand_cents=300)
    ph = create_policyholder(email="v6@x.com", residence_zip="10001")
    policy = create_policy(ph["id"], coverage_type="ALL_RISK",
                           valuation_basis="AGREED_VALUE", deductible_option="STANDARD")
    it_a = create_scheduled_item(policy["id"], description="Ring A", category="RING",
                                 location_zip="10001", scheduled_value_cents=1000000)
    create_scheduled_item(policy["id"], description="Ring B", category="RING",
                          location_zip="10001", scheduled_value_cents=800000)
    bind_policy(policy["id"])
    pay_premium(policy["id"], ph["id"])
    claim = file_claim(policy["id"], it_a["id"], peril="THEFT",
                       loss_type="TOTAL_LOSS", claimed_amount_cents=1000000)
    validate_success(api.start_review_claim(policy["id"], claim["id"], _CA), 200)  # item A SUSPENDED
    end = draft_endorsement(policy["id"], "REMOVE_ITEM", target_item_id=it_a["id"])
    pol_v = live_policy_version(policy["id"])
    res = api.apply_endorsement(policy["id"], end["id"],
                                {"expected_policy_version": pol_v}, _UW)
    validate_error(res, ApiErrorId.ERR_ITEM_LOCKED_BY_CLAIM, 409)


def test_bind_with_no_items_rejected(api):
    """PRD §3.3: "The policy must hold at least one PENDING scheduled item, or the bind is
    rejected with ERR_NO_SCHEDULED_ITEMS."

    Design: Corner/validations/bind_no_items_rejected
    """
    set_clock("2026-02-01T00:00:00Z")
    ph = create_policyholder(email="v7@x.com", residence_zip="10001")
    policy = create_policy(ph["id"], coverage_type="ALL_RISK",
                           valuation_basis="AGREED_VALUE", deductible_option="STANDARD")
    res = api.bind_policy(policy["id"], _UW)
    validate_error(res, ApiErrorId.ERR_NO_SCHEDULED_ITEMS, 409)


# ─────────────────────────────────────────────────────────────────────────
# Queue B: state_machines — invalid transition & precondition enforcement
# ─────────────────────────────────────────────────────────────────────────

def test_bind_already_bound_policy_rejected(api):
    """PRD §3.3: "The policy must currently be QUOTED, or the bind is rejected with
    ERR_INVALID_STATE."

    Design: Corner/state_machines/bind_already_bound_policy_returns_invalid_state
    """
    ctx = setup_bound_policy_with_item()
    res = api.bind_policy(ctx["policy"]["id"], _UW)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)


def test_cancel_blocked_by_open_claim_under_review(api):
    """PRD §3.8: "The single guard is that no claim on the policy may be in UNDER_REVIEW,
    INFO_REQUESTED, or APPROVED; if any open claim sits in one of those statuses, the cancel
    is rejected with ERR_OPEN_CLAIM_BLOCKS_CANCEL."

    Design: Corner/state_machines/cancel_blocked_by_open_claim
    """
    ctx = setup_claim_under_review()  # claim is UNDER_REVIEW
    res = api.cancel_policy(ctx["policy"]["id"], _UW)
    validate_error(res, ApiErrorId.ERR_OPEN_CLAIM_BLOCKS_CANCEL, 409)
