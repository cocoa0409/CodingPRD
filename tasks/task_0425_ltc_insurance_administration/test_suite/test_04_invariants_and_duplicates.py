"""Conserved-quantity invariants and duplicate-period guards.

Queue A (Difficulty): resource_temporal_overlap, compensating_invariant.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_policyholder,
    create_issued_policy,
    create_eligible_provider,
    add_premium_invoice,
    pay_invoice,
    record_trigger_certification,
    author_and_activate_care_plan,
    open_claim,
    add_lines,
    approve_claim,
    deny_claim,
    current_policy_version,
    setup_active_claimable_policy,
    setup_claim_under_review,
    read_benefit_pool,
    read_partnership_disregard,
    TEST_USERS,
)

UW = TEST_USERS["underwriter_headers"]
CE = TEST_USERS["claims_examiner_headers"]
REG = TEST_USERS["regulator_headers"]


# ===========================================================================
# resource_temporal_overlap / claim_line_service_date_unique_per_claim_day
# ===========================================================================
def test_duplicate_service_date_on_claim_rejected(api):
    """PRD 3.5: "The `service_date` must also be unique within the claim; a second
    line for the same day is rejected with `ERR_DUPLICATE_SERVICE_PERIOD`."

    Design: Difficulty/resource_temporal_overlap/claim_line_service_date_unique_per_claim_day_granularity
    """
    ctx = setup_active_claimable_policy()
    claim = open_claim(ctx["pol_id"], ctx["cp_id"], service_month="2026-03")
    get_success_data(api.add_claim_line(
        claim["id"], {"service_date": "2026-03-01", "billed_charge_cents": 15000}, CE))
    res = api.add_claim_line(
        claim["id"], {"service_date": "2026-03-01", "billed_charge_cents": 18000}, CE)
    validate_error(res, "ERR_DUPLICATE_SERVICE_PERIOD")


def test_distinct_service_dates_on_claim_accepted(api):
    """PRD 3.5: "The `service_date` must also be unique within the claim; a second
    line for the same day is rejected with `ERR_DUPLICATE_SERVICE_PERIOD`."
    PRD 3.5: "Service days are then attached to a `SUBMITTED` claim as `ClaimLine`
    records. Each line carries the `service_date` of the single day it bills"

    Two lines on distinct days of the same claim are both accepted (the
    uniqueness guard is per service DAY, not per claim).

    Design: Difficulty/resource_temporal_overlap/claim_line_service_date_unique_per_claim_day_granularity
    """
    ctx = setup_active_claimable_policy()
    claim = open_claim(ctx["pol_id"], ctx["cp_id"], service_month="2026-03")
    l1 = validate_success(api.add_claim_line(
        claim["id"], {"service_date": "2026-03-01", "billed_charge_cents": 15000}, CE), 201)
    l2 = validate_success(api.add_claim_line(
        claim["id"], {"service_date": "2026-03-02", "billed_charge_cents": 18000}, CE), 201)
    assert l1["service_date"] == "2026-03-01", l1
    assert l2["service_date"] == "2026-03-02", l2


# ===========================================================================
# resource_temporal_overlap / claim_service_month_unique_per_policy_month
# ===========================================================================
def test_duplicate_service_month_on_policy_rejected(api):
    """PRD 3.5: "The service month must be unique for the policy — opening a second
    claim for a month already claimed on that policy is rejected with
    `ERR_DUPLICATE_SERVICE_PERIOD`."

    Design: Difficulty/resource_temporal_overlap/claim_service_month_unique_per_policy_month_granularity
    """
    ctx = setup_active_claimable_policy()
    open_claim(ctx["pol_id"], ctx["cp_id"], service_month="2026-03")

    version = current_policy_version(ctx["pol_id"])
    res = api.create_claim(
        {"policy_id": ctx["pol_id"], "care_plan_id": ctx["cp_id"],
         "service_month": "2026-03", "expected_policy_version": version}, CE)
    validate_error(res, "ERR_DUPLICATE_SERVICE_PERIOD")


def test_distinct_service_month_accepted_after_prior_resolved(api):
    """PRD 3.5: "The service month must be unique for the policy — opening a second
    claim for a month already claimed on that policy is rejected with
    `ERR_DUPLICATE_SERVICE_PERIOD`."
    PRD 3.7: "if no other non-terminal claim remains, coverage returns from
    `CLAIM_OPEN` to `IN_FORCE`."

    After denying the first month's claim (coverage back to IN_FORCE), a claim for
    a DIFFERENT service_month opens successfully — month-granularity uniqueness is
    per calendar month, not a blanket per-policy lock.

    Design: Difficulty/resource_temporal_overlap/claim_service_month_unique_per_policy_month_granularity
    """
    ctx = setup_active_claimable_policy()
    claim1 = open_claim(ctx["pol_id"], ctx["cp_id"], service_month="2026-03")
    get_success_data(api.start_review(claim1["id"], CE))
    deny_claim(ctx["pol_id"], claim1["id"])

    back = validate_success(api.get_policy(ctx["pol_id"], CE))
    assert back["coverage_status"] == "IN_FORCE", back

    claim2 = open_claim(ctx["pol_id"], ctx["cp_id"], service_month="2026-04")
    assert claim2["service_month"] == "2026-04", claim2
    assert claim2["status"] == "SUBMITTED", claim2


# ===========================================================================
# compensating_invariant / nonforfeiture_split_conserves_pool
# ===========================================================================
def test_nonforfeiture_split_conserves_pool(api):
    """PRD 3.10: "The paid-up pool is the greater of two figures — the total of
    all `PAID` premium `amount_cents` for the policy, and the benefits already
    paid (`BenefitPool.lifetime_paid_cents`) — but never more than the
    pre-reduction inflated pool. The `nonforfeiture_reduction_cents` is the
    pre-reduction inflated pool minus that paid-up pool, and it is floored at 0"
    PRD 3.10: "The split conserves the pool: the paid-up pool plus the reduction
    always equals the pre-reduction inflated pool. After the reduction, the pool's
    reported `inflated_pool_cents` reflects the grown pool less this reduction."
    PRD 3.10: "In that case `premium_status` is set to `NONFORFEITURE_PAID_UP`
    rather than `LAPSED`"

    pool 1000000, one PAID premium 120000, one approved claim paying 53000
    (lifetime_paid 53000): paid_up = min(1000000, max(120000,53000)) = 120000;
    reduction = 880000; reported inflated_pool after reduction = 120000.

    Design: Difficulty/compensating_invariant/nonforfeiture_split_conserves_pool
    """
    ph = create_policyholder(full_name="Non Forf")
    provider = create_eligible_provider()
    policy = create_issued_policy(ph["id"], initial_pool_cents=1000000, inflation_rider="NONE")
    inv0 = add_premium_invoice(policy["id"], 0, base_premium_cents=120000)
    pay_invoice(inv0["id"], ph["id"])
    record_trigger_certification(policy["id"])
    plan = author_and_activate_care_plan(policy["id"], provider["id"])

    claim = open_claim(policy["id"], plan["id"], service_month="2026-03")
    add_lines(claim["id"], [("2026-03-01", 15000), ("2026-03-02", 25000), ("2026-03-03", 18000)])
    get_success_data(api.start_review(claim["id"], CE))
    approved = approve_claim(policy["id"], claim["id"])
    assert approved["month_paid_cents"] == 53000, approved

    # Period-1 invoice left OPEN with a short grace; advance the clock past it.
    add_premium_invoice(policy["id"], 1, base_premium_cents=120000,
                        due_date="2026-02-28", grace_deadline="2026-03-15")
    get_success_data(api.advance_clock({"to_iso8601": "2026-04-01T00:00:00Z"}, UW))

    refreshed = validate_success(api.get_policy(policy["id"], CE))
    assert refreshed["premium_status"] == "NONFORFEITURE_PAID_UP", refreshed

    pool = read_benefit_pool(policy["id"])
    assert pool["nonforfeiture_reduction_cents"] == 880000, pool
    assert pool["inflated_pool_cents"] == 120000, pool
    assert pool["inflated_pool_cents"] + pool["nonforfeiture_reduction_cents"] == 1000000, pool


def test_nonforfeiture_reduction_floored_at_zero_conserves_pool(api):
    """PRD 3.10: "The `nonforfeiture_reduction_cents` is the pre-reduction inflated
    pool minus that paid-up pool, and it is floored at 0 (when the greater of
    premiums-paid and benefits-paid already meets or exceeds the pool, the
    reduction is 0)."
    PRD 3.10: "The split conserves the pool: the paid-up pool plus the reduction
    always equals the pre-reduction inflated pool."
    PRD 3.10: "The vested branch applies when the policy has nonforfeiture value —
    that is, when its `inflation_rider` is anything other than `NONE`"

    pool 100000, one PAID premium of 100000, vested via COMPOUND_3PCT rider with
    no anniversaries applied (inflated pool stays 100000), no benefits paid:
    paid_up = min(100000, max(100000, 0)) = 100000; reduction floored to 0.

    Design: Difficulty/compensating_invariant/nonforfeiture_split_conserves_pool
    """
    ph = create_policyholder(full_name="Zero Red")
    policy = create_issued_policy(ph["id"], initial_pool_cents=100000, inflation_rider="COMPOUND_3PCT")
    inv0 = add_premium_invoice(policy["id"], 0, base_premium_cents=100000)
    pay_invoice(inv0["id"], ph["id"])
    # Second invoice OPEN with a short grace; advance the clock past grace.
    add_premium_invoice(policy["id"], 1, base_premium_cents=100000,
                        due_date="2026-02-28", grace_deadline="2026-03-15")
    get_success_data(api.advance_clock({"to_iso8601": "2026-04-01T00:00:00Z"}, UW))

    refreshed = validate_success(api.get_policy(policy["id"], CE))
    assert refreshed["premium_status"] == "NONFORFEITURE_PAID_UP", refreshed

    pool = read_benefit_pool(policy["id"])
    assert pool["nonforfeiture_reduction_cents"] == 0, pool
    assert pool["inflated_pool_cents"] == 100000, pool
    assert pool["inflated_pool_cents"] + pool["nonforfeiture_reduction_cents"] == 100000, pool


# ===========================================================================
# compensating_invariant / partnership_disregard_tracks_lifetime_paid_exactly
# ===========================================================================
def test_partnership_disregard_equals_lifetime_paid(api):
    """PRD 3.9: "While a `PartnershipDisregard` is `ACCRUING`, its
    `protected_asset_cents` equals the policy's `BenefitPool.lifetime_paid_cents`
    exactly — every cent of LTC benefit paid out shields an equal cent of the
    insured's assets from Medicaid spend-down."

    A partnership claim paying 53000 leaves protected_asset_cents == 53000 ==
    lifetime_paid_cents.

    Design: Difficulty/compensating_invariant/partnership_disregard_tracks_lifetime_paid_exactly
    """
    ctx = setup_claim_under_review(
        lines=[("2026-03-01", 15000), ("2026-03-02", 25000), ("2026-03-03", 18000)],
        policyholder_overrides={"medicaid_state_eligible": True},
        policy_overrides={"product_mode": "REIMBURSEMENT", "is_partnership_policy": True})
    approve_claim(ctx["pol_id"], ctx["claim_id"])

    pool = read_benefit_pool(ctx["pol_id"])
    assert pool["lifetime_paid_cents"] == 53000, pool

    disregards, _ = read_partnership_disregard(ctx["pol_id"])
    assert len(disregards) == 1, disregards
    assert disregards[0]["protected_asset_cents"] == 53000, disregards[0]
    assert disregards[0]["protected_asset_cents"] == pool["lifetime_paid_cents"]


def test_partnership_disregard_tracks_cumulative_lifetime_paid(api):
    """PRD 3.9: "While a `PartnershipDisregard` is `ACCRUING`, its
    `protected_asset_cents` equals the policy's `BenefitPool.lifetime_paid_cents`
    exactly"
    PRD 3.9: "This recomputation rides on each claim approval, immediately after
    `lifetime_paid_cents` is updated."

    Two approved partnership claims (15000 then 18000) leave lifetime_paid_cents
    33000 and protected_asset_cents 33000 — the shield tracks cumulative dollars
    paid across approvals.

    Design: Difficulty/compensating_invariant/partnership_disregard_tracks_lifetime_paid_exactly
    """
    ph = create_policyholder(full_name="Cum Part", medicaid_state_eligible=True)
    provider = create_eligible_provider()
    policy = create_issued_policy(
        ph["id"], product_mode="REIMBURSEMENT", is_partnership_policy=True)
    inv0 = add_premium_invoice(policy["id"], 0)
    pay_invoice(inv0["id"], ph["id"])
    record_trigger_certification(policy["id"])
    plan = author_and_activate_care_plan(policy["id"], provider["id"])

    claim1 = open_claim(policy["id"], plan["id"], service_month="2026-03")
    add_lines(claim1["id"], [("2026-03-01", 15000)])
    get_success_data(api.start_review(claim1["id"], CE))
    approve_claim(policy["id"], claim1["id"])

    back = validate_success(api.get_policy(policy["id"], CE))
    assert back["coverage_status"] == "IN_FORCE", back

    claim2 = open_claim(policy["id"], plan["id"], service_month="2026-04")
    add_lines(claim2["id"], [("2026-04-01", 18000)])
    get_success_data(api.start_review(claim2["id"], CE))
    approve_claim(policy["id"], claim2["id"])

    pool = read_benefit_pool(policy["id"])
    assert pool["lifetime_paid_cents"] == 33000, pool
    disregards, _ = read_partnership_disregard(policy["id"])
    assert disregards[0]["protected_asset_cents"] == 33000, disregards[0]
