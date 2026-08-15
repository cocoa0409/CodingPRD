"""Match accrual: tiered ratio selection, cap / pool guards, conservation
across accrual and forfeit, enrollment lifecycle gates (PRD §3.7, §2.9)."""
from test_helpers import (
    ApiErrorId,
    assert_pool_conservation,
    create_deposit_payload,
    create_deposit_on,
    create_match_enrollment_payload,
    create_pool,
    setup_active_enrollment,
    setup_case_with_active_plan,
    setup_case_with_draft_plan,
    create_participant,
    validate_error,
    validate_success,
)


def test_match_accrual_cap_boundary_exact_accepted(api, admin_headers):
    """PRD §3.7: "a candidate exceeding the cap room remaining — the pool's
    `per_participant_cap_cents` minus the enrollment's current
    `accrued_unpaid_cents` — fails with `ERR_MATCH_CAP_EXCEEDED`."

    A deposit whose candidate lands exactly on the remaining cap is accepted
    (exceeding, not reaching, is the rejection condition).

    Design: Difficulty/combinatorial_formula/match_accrual_tiered_guards
    """
    ctx = setup_active_enrollment(
        admin_headers,
        participant_income_cents=2000000,
        pool_overrides=dict(name="Pool A", total_funded_cents=1000000,
                            income_threshold_cents=3000000,
                            match_ratio_below=0.5, match_ratio_above=0.25,
                            per_participant_cap_cents=100000),
        savings_goal_cents=1000000,
    )
    enr_id = ctx["enrollment"]["id"]
    # Two deposits of 40000 each accrue 20000 each (0.5 tier): accrued = 40000.
    create_deposit_on(enr_id, 40000, admin_headers)
    create_deposit_on(enr_id, 40000, admin_headers)
    # Cap room remaining is 100000 - 40000 = 60000; a 120000 deposit accrues
    # exactly 60000 — equal to the cap room, so it is accepted.
    accepted = validate_success(
        api.create_deposit(enr_id, create_deposit_payload(120000), admin_headers),
        expected_status=201,
    )
    assert accepted["accrued_unpaid_cents"] == 100000
    assert accepted["total_deposited_cents"] == 200000
    pool = validate_success(api.get_match_pool(ctx["pool"]["id"], admin_headers))
    assert pool["uncommitted_cents"] == 900000


def test_match_accrual_deposit_over_cap_rejected_whole(api, admin_headers):
    """PRD §3.7: "Two fiscal guards can each reject the deposit in full, with
    pool solvency evaluated before the per-participant cap (§2.7): a candidate
    exceeding the pool's current `uncommitted_cents` fails with
    `ERR_POOL_INSUFFICIENT` (HTTP 402), and a candidate exceeding the cap room
    remaining — the pool's `per_participant_cap_cents` minus the enrollment's
    current `accrued_unpaid_cents` — fails with `ERR_MATCH_CAP_EXCEEDED`."

    Design: Difficulty/combinatorial_formula/match_accrual_tiered_guards
    """
    ctx = setup_active_enrollment(
        admin_headers,
        participant_income_cents=2000000,
        pool_overrides=dict(name="Pool A", total_funded_cents=1000000,
                            income_threshold_cents=3000000,
                            match_ratio_below=0.5, match_ratio_above=0.25,
                            per_participant_cap_cents=100000),
        savings_goal_cents=1000000,
    )
    enr_id = ctx["enrollment"]["id"]
    create_deposit_on(enr_id, 40000, admin_headers)
    create_deposit_on(enr_id, 40000, admin_headers)
    # Candidate 0.5 * 150000 = 75000 > cap room 60000 -> whole deposit rejected.
    resp = api.create_deposit(enr_id, create_deposit_payload(150000), admin_headers)
    validate_error(resp, ApiErrorId.ERR_MATCH_CAP_EXCEEDED)
    # The rejection is whole: accrued and totals unchanged.
    enr = validate_success(api.get_match_enrollment(enr_id, admin_headers))
    assert enr["accrued_unpaid_cents"] == 40000
    assert enr["total_deposited_cents"] == 80000


def test_match_tier_boundary_income_exactly_at_threshold(api, admin_headers):
    """PRD §3.7: "The applicable ratio is the pool's `match_ratio_below` when
    the participant's `annual_income_cents` is strictly below the pool's
    `income_threshold_cents`, and `match_ratio_above` when it is at or above
    the threshold."

    Design: Corner/calculations/match_tier_boundary_income_exactly_at_threshold
    """
    ctx = setup_active_enrollment(
        admin_headers,
        participant_income_cents=3000000,  # exactly at the threshold
        pool_overrides=dict(name="Pool T", total_funded_cents=1000000,
                            income_threshold_cents=3000000,
                            match_ratio_below=0.5, match_ratio_above=0.25,
                            per_participant_cap_cents=100000),
        savings_goal_cents=500000,
    )
    enr = create_deposit_on(ctx["enrollment"]["id"], 40000, admin_headers)
    # At-or-above branch: 0.25 * 40000 = 10000 (the below branch would give 20000).
    assert enr["accrued_unpaid_cents"] == 10000, (
        f"at-threshold income must select match_ratio_above; got {enr['accrued_unpaid_cents']}"
    )


def test_deposit_zero_amount_returns_400(api, admin_headers):
    """PRD §3.7: "The payload carries an `amount_cents` greater than 0 —
    anything else is `ERR_INVALID_REQUEST`".

    Design: Corner/validations/deposit_zero_amount_returns_400
    """
    ctx = setup_active_enrollment(admin_headers)
    resp = api.create_deposit(
        ctx["enrollment"]["id"], create_deposit_payload(0), admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_payout_before_goal_met_rejected(api, admin_headers):
    """PRD §3.7: "Payout requires the enrollment to be `GOAL_MET` — anything
    earlier fails with `ERR_GOAL_NOT_MET`".

    Design: Corner/validations/payout_before_goal_met_rejected
    """
    ctx = setup_active_enrollment(admin_headers, savings_goal_cents=500000)
    create_deposit_on(ctx["enrollment"]["id"], 40000, admin_headers)
    resp = api.payout_match_enrollment(ctx["enrollment"]["id"], admin_headers)
    validate_error(resp, ApiErrorId.ERR_GOAL_NOT_MET)


def test_pool_close_with_open_enrollment_rejected(api, admin_headers):
    """PRD §3.7: "Closing a pool is the final administrative act: the pool must
    be `ACTIVE` (`ERR_INVALID_STATE` otherwise) and must hold no enrollment
    still in `ACTIVE`, `MATCH_PAUSED`, or `GOAL_MET` — any such straggler
    blocks the close with `ERR_POOL_HAS_OPEN_ENROLLMENTS`."

    Design: Corner/validations/pool_close_with_open_enrollment_rejected
    """
    ctx = setup_active_enrollment(admin_headers)
    resp = api.close_match_pool(ctx["pool"]["id"], admin_headers)
    validate_error(resp, ApiErrorId.ERR_POOL_HAS_OPEN_ENROLLMENTS)


def test_pool_funds_conserved_after_deposit_accrual(api, admin_headers):
    """PRD §2.9: "For every match pool, the identity `total_funded_cents` equals
    `uncommitted_cents` plus the sum of `accrued_unpaid_cents` over that pool's
    non-terminal enrollments (those in `ACTIVE`, `MATCH_PAUSED`, or `GOAL_MET`)
    plus `paid_out_cents` must hold exactly after every deposit, payout, and
    forfeit. A deposit moves funds from uncommitted to accrued".

    Design: Difficulty/compensating_invariant/pool_funds_conserved_across_accrual_and_forfeit
    """
    ctx = setup_active_enrollment(
        admin_headers,
        participant_income_cents=2000000,
        pool_overrides=dict(name="Pool E", total_funded_cents=1000000,
                            income_threshold_cents=3000000,
                            match_ratio_below=0.5, match_ratio_above=0.25,
                            per_participant_cap_cents=100000),
        savings_goal_cents=1000000,
    )
    enr = create_deposit_on(ctx["enrollment"]["id"], 40000, admin_headers)
    # 0.5 * 40000 = 20000 accrued; uncommitted drops by the same amount.
    assert enr["accrued_unpaid_cents"] == 20000
    pool = validate_success(api.get_match_pool(ctx["pool"]["id"], admin_headers))
    assert pool["uncommitted_cents"] == 980000
    assert pool["paid_out_cents"] == 0
    assert_pool_conservation(pool, [enr])


def test_pool_funds_conserved_after_forfeit_returns_accrual(api, admin_headers):
    """PRD §3.7: "Forfeiture is permitted from `ACTIVE`, `MATCH_PAUSED`, or
    `GOAL_MET` (otherwise `ERR_INVALID_STATE`) and moves the enrollment to
    `FORFEITED`, returning the full `accrued_unpaid_cents` to the pool's
    `uncommitted_cents` and zeroing the accrual."

    Design: Difficulty/compensating_invariant/pool_funds_conserved_across_accrual_and_forfeit
    """
    ctx = setup_active_enrollment(
        admin_headers,
        participant_income_cents=2000000,
        pool_overrides=dict(name="Pool E", total_funded_cents=1000000,
                            income_threshold_cents=3000000,
                            match_ratio_below=0.5, match_ratio_above=0.25,
                            per_participant_cap_cents=100000),
        savings_goal_cents=1000000,
    )
    enr_id = ctx["enrollment"]["id"]
    create_deposit_on(enr_id, 40000, admin_headers)
    forfeited = validate_success(
        api.forfeit_match_enrollment(enr_id, admin_headers)
    )
    assert forfeited["status"] == "FORFEITED"
    assert forfeited["accrued_unpaid_cents"] == 0
    pool = validate_success(api.get_match_pool(ctx["pool"]["id"], admin_headers))
    # Conservation restored exactly: 1000000 == 1000000 + 0 + 0.
    assert pool["uncommitted_cents"] == 1000000
    assert pool["paid_out_cents"] == 0
    assert_pool_conservation(pool, [forfeited])


def test_enrollment_create_rejected_when_plan_draft(api, admin_headers):
    """PRD §3.7: "The referenced goal plan must be `ACTIVE`
    (`ERR_PLAN_NOT_ACTIVE`), and that check runs first".

    Design: Difficulty/cross_entity_state_dependency/enrollment_requires_active_goal_plan
    """
    participant = create_participant(admin_headers)
    ctx = setup_case_with_draft_plan(participant_id=participant["id"],
                                     admin_headers=admin_headers)
    pool = create_pool(admin_headers, name="Pool D", total_funded_cents=500000)
    resp = api.create_match_enrollment(
        create_match_enrollment_payload(
            participant["id"], pool["id"], ctx["plan"]["id"],
            savings_goal_cents=300000,
        ),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE)


def test_enrollment_create_succeeds_after_plan_activated(api, admin_headers):
    """PRD §3.7: "The referenced goal plan must be `ACTIVE`
    (`ERR_PLAN_NOT_ACTIVE`)". PRD §3.4: "`PLAN_DRAFT` → `PLAN_ACTIVE`: requires
    a goal plan for the case in `DRAFT` status to exist (`ERR_PLAN_REQUIRED`);
    that plan is activated, moving `DRAFT` → `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_requires_active_goal_plan
    """
    participant = create_participant(admin_headers)
    ctx = setup_case_with_active_plan(participant_id=participant["id"],
                                      admin_headers=admin_headers)
    pool = create_pool(admin_headers, name="Pool D", total_funded_cents=500000)
    enr = validate_success(
        api.create_match_enrollment(
            create_match_enrollment_payload(
                participant["id"], pool["id"], ctx["plan"]["id"],
                savings_goal_cents=300000,
            ),
            admin_headers,
        ),
        expected_status=201,
    )
    assert enr["status"] == "ACTIVE"
