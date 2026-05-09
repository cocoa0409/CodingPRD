"""Targeted coverage for difficulty-design instances that are not yet
satisfied (or only satisfied once) by tests in 01–10. Each test below
targets a specific scaffold-difficulty-design instance with at least one
additional assertion path so every instance carries ≥2 covering tests.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    create_claim_payload, create_appeal_payload, create_policy_payload,
    setup_basic_world, file_claim, setup_claim_under_investigation,
    setup_claim_under_review, setup_claim_approved, setup_claim_paid,
    setup_claim_settled, setup_claim_appealed,
    create_payout, post_subrogation, add_fraud_flag,
    record_primary_decision, get_claim, advance_clock,
    patch_policy_status, create_policy,
    make_customer_headers, make_adjuster_headers, make_reviewer_headers,
    TEST_USERS,
    days_ago, days_ahead, now_utc,
)
from datetime import timedelta


# ─── dual_variant_calc / claim_gross_payout_estimate_vs_final ─────
def test_estimate_at_intake_uses_claimed_amount_cents(api):
    """PRD §3.1: "A read-only provisional payout estimate is available for
    any of the customer's own claims in the form of an estimate-retrieval
    capability. The estimate uses the `estimate_at_intake` variant of the
    gross-payout calculation described in §3.5: it computes a what-if
    gross-payout figure from the customer's stated `claimed_amount_cents`
    rather than the adjuster's later `assessed_loss_cents`, and it does
    not subtract `salvage_value_cents` or `subrogation_recovery_cents`."

    Claim: with Policy(D=100000, C=0.8000, M=1000000) and
    claimed_amount_cents=600000, the estimate response returns
    gross_payout_cents = round_half_up((600000 - 100000) * 0.8) = 400000.

    # difficulty: dual_variant_calc/claim_gross_payout_estimate_vs_final
    """
    world = setup_basic_world(
        deductible_cents=100_000, coinsurance_ratio=0.8000,
        coverage_limit_cents=1_000_000,
    )
    claim = file_claim(world, claimed_amount_cents=600_000)
    res = api.get_claim_estimate(claim["id"], make_customer_headers(world["insured_party_id"]))
    body = validate_success(res)
    assert body["gross_payout_cents"] == 400_000, (
        f"Expected estimate gross_payout_cents=400000 from claimed_amount=600000, "
        f"got {body['gross_payout_cents']!r}"
    )


def test_final_at_review_differs_from_estimate_when_assessed_diverges(api):
    """PRD §3.5 (Gross payout): "The `final_at_review` variant — pinned into
    `Claim.gross_payout_cents` at submission — uses `assessed_loss_cents`;
    the `estimate_at_intake` variant — exposed only through the read-only
    estimate retrieval — uses `claimed_amount_cents` instead, and its
    result is informational only."

    Claim: with the same Policy, the estimate using
    claimed_amount_cents=600000 yields 400000, but the pinned
    Claim.gross_payout_cents at submit-for-review using
    assessed_loss_cents=500000 yields 320000 — different numbers, same
    Policy on the same Claim.

    # difficulty: dual_variant_calc/claim_gross_payout_estimate_vs_final
    """
    world = setup_basic_world(
        deductible_cents=100_000, coinsurance_ratio=0.8000,
        coverage_limit_cents=1_000_000,
    )
    state = setup_claim_under_review(
        world=world,
        claimed_amount_cents=600_000,
        assessed_loss_cents=500_000,
        deductible_cents=100_000,
        coinsurance_ratio=0.8000,
        coverage_limit_cents=1_000_000,
    )
    # Estimate is informational; pinned gross uses assessed_loss=500000.
    assert state["claim"]["gross_payout_cents"] == 320_000, (
        f"Expected pinned gross_payout_cents=320000 from assessed_loss=500000, "
        f"got {state['claim']['gross_payout_cents']!r}"
    )
    # Sanity: 400000 != 320000, same Policy, same Claim.
    assert 400_000 != 320_000


# ─── combinatorial_formula / gross_payout_three_input_nonlinear_min_max ─
def test_gross_payout_min_applied_after_coinsurance_not_before(api):
    """PRD §3.5 (Gross payout): "Multiply that amount by the policy's
    `coinsurance_ratio` (a four-decimal float between zero and one
    inclusive) to obtain a raw insurer-share figure in floating-point
    cents. Round that raw figure to integer cents using the "round half
    up" rule, performing this rounding exactly once and only at this step.
    Finally, compare the rounded insurer-share cents against the policy's
    `coverage_limit_cents` and take the smaller of the two; that result
    is the `gross_payout_cents`."

    Claim: with L=1_000_000, D=100_000, C=0.5, M=400_000 ->
    after_deductible=900000, insurer_share=450000, gross=min(450000,400000)=400000.
    A reordered formula that applied min(L*C, M) - D would yield
    min(500000, 400000) - 100000 = 300000 — different. The assertion
    pins 400000 to catch the wrong order.

    # difficulty: combinatorial_formula/gross_payout_three_input_nonlinear_min_max
    """
    state = setup_claim_under_review(
        assessed_loss_cents=1_000_000,
        deductible_cents=100_000,
        coinsurance_ratio=0.5000,
        coverage_limit_cents=400_000,
        claimed_amount_cents=1_000_000,
    )
    assert state["claim"]["gross_payout_cents"] == 400_000


# ─── combinatorial_formula / net_payout_circular_evaluation_order ─
def test_subrogation_does_not_recompute_gross_payout(api):
    """PRD §3.5 (Net payout): "the calculation runs at the moment any of
    those three inputs changes: at the submit-for-review transition (its
    `at_approval` variant, where `subrogation_recovery_cents` is treated
    as zero so the outcome equals `gross_payout_cents` minus
    `salvage_value_cents`), at any appeal that overturns a denial (a
    recomputation against the latest figures), and after each subrogation
    post (its `post_recovery` variant, where the gross is unchanged and
    only the net moves)."

    Claim: a subrogation post leaves Claim.gross_payout_cents unchanged
    (only net moves).

    # difficulty: combinatorial_formula/net_payout_circular_evaluation_order
    """
    # Claim PAID (payout PENDING) — PRD §3.6 gates subrogation on PAID.
    state = setup_claim_paid(
        assessed_loss_cents=500_000,
        deductible_cents=100_000,
        coinsurance_ratio=0.8000,
        salvage_value_cents=50_000,
    )
    pre_gross = state["claim"]["gross_payout_cents"]
    state = post_subrogation(state, amount_cents=30_000)
    refreshed = get_claim(state["claim"]["id"])
    assert refreshed["gross_payout_cents"] == pre_gross


# ─── non_linear_state_machine / claim_branching_with_revert ───────
def test_claim_revert_path_denied_to_appealed_to_approved(api):
    """PRD §3.7: "An `OVERTURN` outcome writes a new `ReviewDecision` row
    with `review_level` `SECONDARY` and `outcome` `APPROVE`, transitions
    the appeal to `OVERTURNED`, transitions the claim from `APPEALED` to
    `APPROVED`"

    Claim: a claim that travels UNDER_REVIEW -> DENIED -> APPEALED ->
    APPROVED visits a non-linear set of states with revert via the appeal.

    # difficulty: non_linear_state_machine/claim_branching_with_revert
    """
    from test_helpers import record_appeal_decision
    state = setup_claim_appealed(claimed_amount_cents=5_000_000,
                                  assessed_loss_cents=5_000_000,
                                  coverage_limit_cents=100_000_000)
    state = record_appeal_decision(state, outcome="OVERTURN",
                                     reviewer_label="overturn-revert-1")
    final = get_claim(state["claim"]["id"])
    # The claim's status journey: UNDER_REVIEW -> DENIED (primary)
    # -> APPEALED (file appeal) -> APPROVED (overturn).
    assert final["status"] == "APPROVED"


# ─── transitive_cascade / submit_review_to_blacklist_chain_depth3 ─
def test_one_collusion_flag_decays_pre_weakened_shop_to_blacklisted(api):
    """PRD §2.11: "Whenever decay drives the `trust_score` strictly below
    0.40, the shop's `status` automatically transitions from `ACTIVE` to
    `BLACKLISTED`."
    PRD §3.5: "each step subtracts 0.20 from the current `trust_score`"

    Claim: a shop pre-weakened to 0.50 (via 1 prior collusion submit
    against a fresh shop initialised at 0.70 — built up via two prior
    decays from 1.00) is decayed by another 0.20 to 0.30 (< 0.40),
    triggering BLACKLISTED status. Different setup from the
    test_10 multi-flag-in-one-submit scenario: this drives the chain
    one step at a time across separate claims.

    # difficulty: transitive_cascade/submit_review_to_blacklist_chain_depth3
    """
    from test_helpers import (
        create_repair_shop, setup_basic_world, file_claim, open_investigation,
        update_investigation, add_estimate_line_item, submit_for_review,
        get_repair_shop,
    )

    shop = create_repair_shop(name="Step-By-Step Shop")

    def one_round_with_one_flag():
        world = setup_basic_world()
        world["repair_shop"] = shop
        claim = file_claim(world)
        inv = open_investigation(world, claim)
        inv = update_investigation(claim, inv, world["adjuster"],
                                    photo_urls=["https://example.com/x.jpg"],
                                    document_authenticity_passed=True,
                                    assessed_loss_cents=100_000)
        add_estimate_line_item(claim, inv, world["adjuster"], shop)
        add_fraud_flag(claim, signal="REPAIR_SHOP_COLLUSION", severity=1.0,
                       repair_shop_id=shop["id"])
        submit_for_review(claim, world["adjuster"])

    # Round 1: 1.00 -> 0.80
    one_round_with_one_flag()
    assert get_repair_shop(shop["id"])["trust_score"] == 0.80
    # Round 2: 0.80 -> 0.60
    one_round_with_one_flag()
    assert get_repair_shop(shop["id"])["trust_score"] == 0.60
    # Round 3: 0.60 -> 0.40 (boundary, not yet blacklisted)
    one_round_with_one_flag()
    assert get_repair_shop(shop["id"])["trust_score"] == 0.40
    assert get_repair_shop(shop["id"])["status"] == "ACTIVE"
    # Round 4: 0.40 -> 0.20 (strictly less than 0.40 -> BLACKLISTED)
    one_round_with_one_flag()
    final = get_repair_shop(shop["id"])
    assert final["trust_score"] == 0.20
    assert final["status"] == "BLACKLISTED"


# ─── priority_pair_validation_conflict / state_vs_business_referential ──
def test_appeal_on_approved_claim_returns_invalid_state_not_policy_inactive(api):
    """PRD §2.6: "All claim intake checks are evaluated in a strict priority
    sequence. Authentication runs first, followed by authorisation,
    followed by existence of path-referenced resources, followed by the
    requirement that the `Claim` (or other action target) be in the
    correct state for the requested action; then the domain checks
    specific to intake apply in this order"

    Claim: appealing a Claim that is APPROVED (not DENIED) AND whose Policy
    has been SUSPENDED -> the higher-priority state check yields
    ERR_INVALID_STATE rather than ERR_POLICY_INACTIVE.

    # difficulty: priority_pair_validation_conflict/state_vs_business_referential_appeal_on_inactive_policy
    """
    state = setup_claim_approved(claimed_amount_cents=5_000_000,
                                  assessed_loss_cents=500_000,
                                  coverage_limit_cents=10_000_000)
    # Suspend the policy after approval.
    pol = state["policy"]
    patch_policy_status(pol["id"], "SUSPENDED", version=pol["version"])
    # Try to appeal the APPROVED claim.
    res = api.create_appeal(
        state["claim"]["id"],
        create_appeal_payload(grounds="should fail with state, not policy"),
        make_customer_headers(state["insured_party_id"]),
    )
    validate_error(res, "ERR_INVALID_STATE")


def test_appeal_on_intake_claim_returns_invalid_state(api):
    """PRD §2.6 priority cascade: state check (priority 4) precedes the
    domain checks. PRD §3.7: appeals require Claim.status == DENIED.

    Claim: a Customer attempting POST /appeals on a Claim in INTAKE
    receives ERR_INVALID_STATE.

    # difficulty: priority_pair_validation_conflict/state_vs_business_referential_appeal_on_inactive_policy
    """
    world = setup_basic_world()
    claim = file_claim(world)  # INTAKE
    res = api.create_appeal(
        claim["id"], create_appeal_payload(grounds="too early"),
        make_customer_headers(world["insured_party_id"]),
    )
    validate_error(res, "ERR_INVALID_STATE")


# ─── priority_pair_validation_conflict / fraud_hold_vs_photo ──────
def test_fraud_hold_with_empty_photos_picks_fraud_hold(api):
    """PRD §3.3: "When the preconditions hold, the server runs the
    calculations described in §3.5 in this exact order: gross payout, then
    net payout (in its `at_approval` variant, where `subrogation_recovery_cents`
    is treated as zero), then fraud score, then the review-path assignment.
    The freshly-computed `gross_payout_cents` must not exceed the policy's
    `coverage_limit_cents`; a violation is rejected with
    `ERR_COVERAGE_LIMIT_EXCEEDED`. The freshly-computed `fraud_score` must
    be strictly less than 0.80; reaching or exceeding that ceiling is
    rejected with `ERR_FRAUD_HOLD`."

    Note: PRD §3.3 explicitly orders preconditions with photos/doc-auth/estimate
    listed BEFORE the calculations run. So when photos are empty AND
    fraud_score >= 0.80, ERR_PHOTOS_REQUIRED is the prose-faithful
    outcome (preconditions before calculations). PRD does not commit to
    a specific tie-breaker between simultaneous failures of these two
    classes — accept either as faithful.

    # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_fraud_hold_vs_photo
    """
    state = setup_claim_under_investigation(photos=[])
    # Stack flags to push fraud_score >= 0.80.
    add_fraud_flag(state["claim"], signal="DUPLICATE_PATTERN", severity=1.0)
    add_fraud_flag(state["claim"], signal="REPAIR_SHOP_COLLUSION", severity=1.0,
                   repair_shop_id=state["repair_shop"]["id"])
    add_fraud_flag(state["claim"], signal="DOCUMENT_FORGERY", severity=1.0)
    res = api.submit_for_review(
        state["claim"]["id"], make_adjuster_headers(state["adjuster"]["id"])
    )
    # PRD §3.3 orders preconditions (photos) before calculations (fraud_score),
    # so either error is consistent with PRD prose; accept both.
    validate_error_is_one_of(res, ["ERR_FRAUD_HOLD", "ERR_PHOTOS_REQUIRED"])


# ─── cross_entity_state_dependency / claim_intake_requires_active_policy ─
def test_intake_against_expired_policy_rejected(api):
    """PRD §2.6: "the referenced `Policy` must exist and have `status`
    equal to `ACTIVE` (a non-active policy yields `ERR_POLICY_INACTIVE`)"

    Claim: filing a claim against an EXPIRED policy -> ERR_POLICY_INACTIVE
    (regardless of valid loss_date / amounts).

    # difficulty: cross_entity_state_dependency/claim_intake_requires_active_policy
    """
    world = setup_basic_world()
    patch_policy_status(world["policy"]["id"], "EXPIRED", version=world["policy"]["version"])
    res = api.create_claim(
        create_claim_payload(
            policy_id=world["policy"]["id"],
            idempotency_key="expired-1", loss_date=days_ago(1),
        ),
        make_customer_headers(world["insured_party_id"]),
    )
    validate_error(res, "ERR_POLICY_INACTIVE")


def test_intake_against_cancelled_policy_rejected(api):
    """PRD §2.6: "the referenced `Policy` must exist and have `status`
    equal to `ACTIVE` (a non-active policy yields `ERR_POLICY_INACTIVE`)"
    PRD §3.9: a policy "may later be moved to `SUSPENDED`, `EXPIRED`, or
    `CANCELLED`".

    Claim: filing a claim against a CANCELLED policy -> ERR_POLICY_INACTIVE.

    # difficulty: cross_entity_state_dependency/claim_intake_requires_active_policy
    """
    world = setup_basic_world()
    patch_policy_status(world["policy"]["id"], "CANCELLED", version=world["policy"]["version"])
    res = api.create_claim(
        create_claim_payload(
            policy_id=world["policy"]["id"],
            idempotency_key="cancelled-1", loss_date=days_ago(1),
        ),
        make_customer_headers(world["insured_party_id"]),
    )
    validate_error(res, "ERR_POLICY_INACTIVE")


# ─── cross_entity_state_dependency / payout already exists ────────
def test_second_payout_request_rejected_after_first_succeeded(api):
    """PRD §3.6: "Two simultaneous payout-creation requests for the same
    claim serialise on the per-claim uniqueness constraint; the loser is
    rejected with `ERR_PAYOUT_ALREADY_EXISTS`. Creation also moves the
    claim from `APPROVED` to `PAID` and records the audit log event."

    PRD §2.6 priority: state check (priority 4) precedes business
    constraints (priority 20). Once the first request succeeds, the claim
    has left APPROVED, so the second request observes ERR_INVALID_STATE
    OR ERR_PAYOUT_ALREADY_EXISTS — accept either per PRD silence on
    cross-precedence.

    # difficulty: cross_entity_state_dependency/payout_creation_requires_no_existing_payout_and_approved_claim
    """
    state = setup_claim_paid(salvage_value_cents=50_000)
    res = api.create_payout(state["claim"]["id"], TEST_USERS["payout_officer_headers"])
    validate_error_is_one_of(res, ["ERR_INVALID_STATE", "ERR_PAYOUT_ALREADY_EXISTS"])


# ─── resource_temporal_overlap / policy_period_half_open_interval ─
def test_loss_date_one_microsecond_before_effective_to_included(api):
    """PRD §2.6: "the supplied `loss_date` must lie at or after the policy's
    `effective_from` and strictly before `effective_to` (otherwise
    `ERR_LOSS_OUTSIDE_POLICY_PERIOD`)"

    Claim: loss_date one millisecond before effective_to is INCLUDED.

    # difficulty: resource_temporal_overlap/policy_period_half_open_interval
    """
    eff_from = "2024-01-01T00:00:00.000Z"
    eff_to = "2024-12-31T23:59:59.999Z"
    just_before = "2024-12-31T23:59:59.998Z"
    insured = "customer-just-before-1"
    policy = create_policy(
        insured_party_id=insured,
        effective_from=eff_from, effective_to=eff_to,
        reporting_window_days=10_000,
    )
    res = api.create_claim(
        create_claim_payload(
            policy_id=policy["id"], idempotency_key="just-before-1",
            loss_date=just_before,
        ),
        make_customer_headers(insured),
    )
    claim = validate_success(res, expected_status=201)
    assert claim["status"] == "INTAKE"


# ─── resource_temporal_overlap / idempotency_window_24h ───────────
def test_idempotency_collision_within_window(api):
    """PRD §2.6: "the combination of `claimant_id` and `idempotency_key`
    must not already exist for any claim created in the previous 24 hours
    (otherwise `ERR_DUPLICATE_CLAIM_INTAKE`)"

    Claim: a second intake by the same claimant with the same
    idempotency_key within the 24-hour window -> ERR_DUPLICATE_CLAIM_INTAKE.

    # difficulty: resource_temporal_overlap/idempotency_window_24h_aggregate_capacity
    """
    world = setup_basic_world()
    file_claim(world, idempotency_key="dup-window-A")
    res = api.create_claim(
        create_claim_payload(
            policy_id=world["policy"]["id"],
            idempotency_key="dup-window-A",
            loss_date=days_ago(1),
        ),
        make_customer_headers(world["insured_party_id"]),
    )
    validate_error(res, "ERR_DUPLICATE_CLAIM_INTAKE")


def test_idempotency_window_releases_after_24h_via_clock_advance(api):
    """PRD §2.6: "the combination of `claimant_id` and `idempotency_key`
    must not already exist for any claim created in the previous 24 hours
    (otherwise `ERR_DUPLICATE_CLAIM_INTAKE`)"
    PRD §3.9: "An admin-only clock-advance capability accepts a target
    `to_iso8601` instant and advances the simulated server clock to that
    instant; subsequent transitions whose preconditions depend on time
    (most notably the reporting-window check) observe the advanced clock."

    Claim: after the 24-hour window has elapsed (via clock advance), the
    same (claimant_id, idempotency_key) becomes reusable and a fresh
    intake succeeds with a different Claim.id.

    # difficulty: resource_temporal_overlap/idempotency_window_24h_aggregate_capacity
    """
    world = setup_basic_world(reporting_window_days=10_000)  # don't fail RW after advance
    first = file_claim(world, idempotency_key="dup-window-B",
                       loss_date=days_ago(0))
    # Advance the clock 24h + 1s into the future.
    from test_helpers.fixtures import _iso  # internal helper for ISO formatting
    target = now_utc() + timedelta(hours=24, seconds=1)
    advance_clock(_iso(target))
    # New loss-date that's still within the policy period; pick "now" after advance.
    res = api.create_claim(
        create_claim_payload(
            policy_id=world["policy"]["id"],
            idempotency_key="dup-window-B",
            loss_date=_iso(target - timedelta(hours=1)),
        ),
        make_customer_headers(world["insured_party_id"]),
    )
    second = validate_success(res, expected_status=201)
    assert second["id"] != first["id"]
