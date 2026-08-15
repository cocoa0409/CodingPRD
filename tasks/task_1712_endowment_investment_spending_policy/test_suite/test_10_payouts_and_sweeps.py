"""Program payouts: caps, spending reports, unit identity, and the lapse sweep."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_distribution,
    assert_pool_unit_identity,
    create_distribution,
    create_fund,
    create_gift,
    create_donor,
    create_payout,
    disburse_payout,
    distribute_distribution,
    finalize_open_quarter,
    get_success_data,
    propose_distribution,
    receive_gift,
    activate_fund,
    report_payout_spending,
    setup_distributed_world,
    setup_disbursed_payout_world,
    setup_pool_world,
    create_adopted_policy,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_two_fund_world():
    """FU1 (TRUE_ENDOWMENT, corpus 10000000) and FU2 (QUASI_ENDOWMENT, corpus
    5000000), both gifts RECEIVED in Q1; Q1 finalize unitizes both at inception."""
    ctx = setup_pool_world(pool_name="Pool UI")
    pool_id = ctx["pool"]["id"]
    ctx["policy"] = create_adopted_policy(pool_id)
    fund1 = create_fund(pool_id, fund_code="FU1", fund_name="Fund U1",
                        endowment_class="TRUE_ENDOWMENT")
    fund2 = create_fund(pool_id, fund_code="FU2", fund_name="Fund U2",
                        endowment_class="QUASI_ENDOWMENT")
    donor = create_donor(donor_name="D UI")
    gift1 = create_gift(fund1["id"], donor["id"], "U1", gift_type="CORPUS",
                        amount_cents=10_000_000)
    gift2 = create_gift(fund2["id"], donor["id"], "U2", gift_type="CORPUS",
                        amount_cents=5_000_000)
    activate_fund(fund1["id"])
    activate_fund(fund2["id"])
    receive_gift(gift1["id"])
    receive_gift(gift2["id"])
    finalize_open_quarter(pool_id, 15_000_000, reports=[{
        "manager_id": ctx["manager"]["id"], "beginning_mv_cents": 0,
        "ending_mv_cents": 15_000_000,
        "flows": [{"day_offset": 0, "amount_cents": 15_000_000}],
    }])
    ctx.update({"fund1": fund1, "fund2": fund2, "donor": donor})
    distribution = create_distribution(fund1["id"], 2026)
    propose_distribution(distribution["id"])
    approve_distribution(distribution["id"])
    ctx["distribution"] = distribution
    return ctx


def test_distribution_redemption_conserves_pool_unit_identity(api):
    """PRD §3.5: 'On success the fund's `units_held_micro` and the pool's
    `total_units_outstanding_micro` decrease by the redeemed amount'
    PRD §2.5: 'The pool's `total_units_outstanding_micro` is the exact integer sum of
    every fund's `units_held_micro`, maintained by construction'

    Design: Difficulty/compensating_invariant/pool_unit_identity_conserved_across_unitize_redeem_and_corpus_redeem
    """
    ctx = _setup_two_fund_world()

    distributed = distribute_distribution(ctx["distribution"]["id"])
    assert distributed["distribution_status"] == "DISTRIBUTED"
    # round_half_up(500000 * 1e9 / 100000) at the flat price.
    assert distributed["units_redeemed_micro"] == 5_000_000_000
    assert distributed["distributed_amount_cents"] == 500_000

    fund1 = get_success_data(api.get_fund(ctx["fund1"]["id"], TEST_USERS["io_headers"]))
    fund2 = get_success_data(api.get_fund(ctx["fund2"]["id"], TEST_USERS["io_headers"]))
    pool = get_success_data(api.get_pool(ctx["pool"]["id"], TEST_USERS["io_headers"]))
    assert fund1["units_held_micro"] == 95_000_000_000
    assert fund2["units_held_micro"] == 50_000_000_000
    assert_pool_unit_identity(pool, [fund1, fund2])
    assert pool["total_units_outstanding_micro"] == 145_000_000_000


def test_corpus_redemption_conserves_pool_unit_identity_and_moves_hgv(api):
    """PRD §3.8: 'The fund's `historic_gift_value_cents` decreases by `amount_cents`,
    floored at 0 — the only operation besides corpus gift unitization that moves
    historic gift value, which is never moved by market swings or spending —
    `market_value_cents` and `is_underwater` are refreshed, the pool's
    `total_units_outstanding_micro` decreases, and a `UnitLedgerEntry` of type
    `CORPUS_REDEEM` is emitted.'
    PRD §2.5: 'The pool's `total_units_outstanding_micro` is the exact integer sum of
    every fund's `units_held_micro`, maintained by construction'

    Design: Difficulty/compensating_invariant/pool_unit_identity_conserved_across_unitize_redeem_and_corpus_redeem
    """
    ctx = _setup_two_fund_world()
    distribute_distribution(ctx["distribution"]["id"])

    # QUASI fund may redeem corpus: 1000000 cents burns 10000000000 micro at 100000.
    redeemed = validate_success(api.redeem_corpus(
        ctx["fund2"]["id"], {"amount_cents": 1_000_000}, TEST_USERS["board_headers"],
    ), 200)
    assert redeemed["units_held_micro"] == 40_000_000_000
    assert redeemed["historic_gift_value_cents"] == 4_000_000

    fund1 = get_success_data(api.get_fund(ctx["fund1"]["id"], TEST_USERS["io_headers"]))
    pool = get_success_data(api.get_pool(ctx["pool"]["id"], TEST_USERS["io_headers"]))
    assert_pool_unit_identity(pool, [fund1, redeemed])
    assert pool["total_units_outstanding_micro"] == 135_000_000_000

    entries, _ = validate_paginated(api.list_ledger_entries(
        TEST_USERS["io_headers"],
        params={"fund_id": ctx["fund2"]["id"], "entry_type": "CORPUS_REDEEM"},
    ))
    assert len(entries) == 1
    assert entries[0]["units_delta_micro"] == -10_000_000_000


def _setup_sweep_world():
    """Payout of 500000 DISBURSED in open quarter 5 with 200000 spent; Q5 finalized."""
    ctx = setup_distributed_world(corpus_cents=10_000_000, pool_name="Pool SW")
    ctx["payout"] = create_payout(ctx["distribution"]["id"], "ENG-101",
                                  "SCHOLARSHIP", 500_000)
    ctx["payout"] = disburse_payout(ctx["payout"]["id"])
    report_payout_spending(ctx["payout"]["id"], 200_000)
    finalize_open_quarter(ctx["pool"]["id"], 9_500_000, reports=[{
        "manager_id": ctx["manager"]["id"], "beginning_mv_cents": 10_000_000,
        "ending_mv_cents": 9_500_000,
        "flows": [{"day_offset": 0, "amount_cents": -500_000}],
    }])
    return ctx


def _advance_flat_quarters(ctx, count):
    for _ in range(count):
        finalize_open_quarter(ctx["pool"]["id"], 9_500_000, reports=[{
            "manager_id": ctx["manager"]["id"], "beginning_mv_cents": 9_500_000,
            "ending_mv_cents": 9_500_000,
        }])


def test_payout_still_disbursed_three_quarters_after_disbursement(api):
    """PRD §3.7: 'During step 2 of the quarter close pipeline, any payout still
    `DISBURSED` whose age — the finalized quarter index minus
    `disbursed_quarter_index` — is at least 4 quarters lapses: an age of exactly 4
    sweeps.'

    Design: Difficulty/compensating_invariant/payout_cash_conservation_allocated_equals_spent_plus_swept
    """
    ctx = _setup_sweep_world()
    _advance_flat_quarters(ctx, 3)  # Q6, Q7, Q8 -> ages 1, 2, 3

    payout = get_success_data(api.get_payout(ctx["payout"]["id"], TEST_USERS["io_headers"]))
    assert payout["payout_status"] == "DISBURSED", "age 3 < LAPSE_QUARTERS 4"
    assert payout["unspent_amount_cents"] == 300_000


def test_lapse_sweep_at_exactly_four_quarters_conserves_cash(api):
    """PRD §3.7: 'The sweep computes the unspent remainder as `allocated_amount_cents`
    minus `spent_amount_cents`, closes the payout as `CLOSED_RETURNED` with
    `unspent_amount_cents` zeroed, and creates a system gift on the fund: `gift_type`
    `EXPENDABLE`, `gift_status` `RECEIVED` in the finalized quarter, `amount_cents`
    equal to the unspent remainder, `donor_id` null (the only case where a gift's
    donor may be null), `source_payout_id` pointing at the swept payout'
    PRD §3.7: 'Conservation holds exactly per payout: `allocated_amount_cents` equals
    `spent_amount_cents` plus the swept remainder.'
    PRD §3.7: 'The reinvestment gift then unitizes at the new price in step 3 of the
    same close pipeline'

    Design: Difficulty/compensating_invariant/payout_cash_conservation_allocated_equals_spent_plus_swept
    """
    ctx = _setup_sweep_world()
    _advance_flat_quarters(ctx, 4)  # Q6..Q9 -> age exactly 4 at Q9

    payout = get_success_data(api.get_payout(ctx["payout"]["id"], TEST_USERS["io_headers"]))
    assert payout["payout_status"] == "CLOSED_RETURNED"
    assert payout["unspent_amount_cents"] == 0
    assert payout["swept_gift_id"] is not None
    # Conservation: 500000 == 200000 spent + 300000 swept.
    assert payout["allocated_amount_cents"] == 500_000
    assert payout["spent_amount_cents"] == 200_000

    gifts, _ = validate_paginated(api.list_gifts(
        TEST_USERS["io_headers"], params={"source_payout_id": ctx["payout"]["id"]},
    ))
    assert len(gifts) == 1
    sweep_gift = gifts[0]
    assert sweep_gift["gift_type"] == "EXPENDABLE"
    assert sweep_gift["amount_cents"] == 300_000
    assert sweep_gift["gift_status"] == "UNITIZED"
    assert sweep_gift["units_purchased_micro"] == 3_000_000_000  # at price 100000

    fund = get_success_data(api.get_fund(ctx["fund"]["id"], TEST_USERS["io_headers"]))
    pool = get_success_data(api.get_pool(ctx["pool"]["id"], TEST_USERS["io_headers"]))
    assert fund["units_held_micro"] == 98_000_000_000
    assert_pool_unit_identity(pool, [fund])


def test_payout_full_spend_closes_and_locks(api):
    """PRD §3.7: 'A report reaching exactly the full allocation closes the payout as
    `CLOSED_FULLY_SPENT` with `unspent_amount_cents` set to 0.'
    PRD §2.8: '(6) lifecycle-state permission for the requested transition, failing
    as `ERR_INVALID_STATE_TRANSITION`'

    Design: Corner/state_machines/payout_full_spend_closes_and_locks
    """
    ctx = setup_disbursed_payout_world(allocated_amount_cents=200_000,
                                       program_code="LIB-1")

    closed = validate_success(api.report_spending(
        ctx["payout"]["id"], {"spent_amount_cents": 200_000},
        TEST_USERS["program_headers"],
    ), 200)
    assert closed["payout_status"] == "CLOSED_FULLY_SPENT"
    assert closed["unspent_amount_cents"] == 0

    res = api.report_spending(
        ctx["payout"]["id"], {"spent_amount_cents": 200_000},
        TEST_USERS["program_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)


def test_payout_aggregate_cap_enforced_cumulatively(api):
    """PRD §3.7: 'The sum of `allocated_amount_cents` over the distribution's
    non-cancelled payouts, including the new one, must not exceed the distribution's
    `distributed_amount_cents`, failing which the create is rejected with
    `ERR_ALLOCATION_EXCEEDS_DISTRIBUTION`.'

    Design: Corner/validations/payout_aggregate_cap_enforced_cumulatively
    """
    ctx = setup_distributed_world(corpus_cents=10_000_000, pool_name="Pool AG")
    dist_id = ctx["distribution"]["id"]
    assert ctx["distribution"]["distributed_amount_cents"] == 500_000

    first = validate_success(api.create_payout(
        {"distribution_id": dist_id, "program_code": "LIB-1",
         "program_purpose": "RESEARCH", "allocated_amount_cents": 300_000},
        TEST_USERS["dev_headers"],
    ), 201)
    assert first["payout_status"] == "SCHEDULED"

    res = api.create_payout(
        {"distribution_id": dist_id, "program_code": "LIB-2",
         "program_purpose": "RESEARCH", "allocated_amount_cents": 200_001},
        TEST_USERS["dev_headers"],
    )
    validate_error(res, ApiErrorId.ERR_ALLOCATION_EXCEEDS_DISTRIBUTION, 422)

    # Cumulative exactly 500000: the cap is inclusive.
    third = validate_success(api.create_payout(
        {"distribution_id": dist_id, "program_code": "LIB-3",
         "program_purpose": "RESEARCH", "allocated_amount_cents": 200_000},
        TEST_USERS["dev_headers"],
    ), 201)
    assert third["payout_status"] == "SCHEDULED"


def test_spending_report_must_be_monotonic_and_within_allocation(api):
    """PRD §3.7: 'A `ProgramManager` reports cumulative program spending by
    submitting `spent_amount_cents`, which must be at least the currently recorded
    value and at most `allocated_amount_cents` — a decrease or an over-allocation
    report is rejected with `ERR_INVALID_SPENT_AMOUNT`. A partial report (greater
    than the current value, less than the allocation) keeps the payout in
    `DISBURSED` and shrinks `unspent_amount_cents` to the remaining difference.'

    Design: Corner/validations/spending_report_must_be_monotonic_and_within_allocation
    """
    ctx = setup_disbursed_payout_world(allocated_amount_cents=200_000,
                                       program_code="LIB-1", pool_name="Pool IS")
    payout_id = ctx["payout"]["id"]

    partial = validate_success(api.report_spending(
        payout_id, {"spent_amount_cents": 150_000}, TEST_USERS["program_headers"],
    ), 200)
    assert partial["payout_status"] == "DISBURSED"
    assert partial["unspent_amount_cents"] == 50_000

    res1 = api.report_spending(payout_id, {"spent_amount_cents": 100_000},
                               TEST_USERS["program_headers"])
    validate_error(res1, ApiErrorId.ERR_INVALID_SPENT_AMOUNT, 422)

    res2 = api.report_spending(payout_id, {"spent_amount_cents": 250_000},
                               TEST_USERS["program_headers"])
    validate_error(res2, ApiErrorId.ERR_INVALID_SPENT_AMOUNT, 422)


def _setup_purpose_priority_world():
    """SCHOLARSHIP-restricted fund with a DISTRIBUTED 500000 distribution."""
    return setup_distributed_world(
        corpus_cents=10_000_000, pool_name="Pool PC2",
        purpose_restriction="SCHOLARSHIP",
    )


def test_payout_purpose_mismatch_beats_allocation_cap(api):
    """PRD §2.8: '(9) donor-restriction compliance on payouts, failing as
    `ERR_PURPOSE_MISMATCH`;'
    PRD §2.8: '(26) the payout aggregate cap, failing as
    `ERR_ALLOCATION_EXCEEDS_DISTRIBUTION`;'
    PRD §2.8: 'the server evaluates them in a fixed priority order and reports the
    earliest failure.'

    Design: Difficulty/priority_pair_validation_conflict/payout_purpose_mismatch_beats_allocation_cap_safety_over_fiscal
    """
    ctx = _setup_purpose_priority_world()
    assert ctx["distribution"]["distributed_amount_cents"] == 500_000

    # Violates both: RESEARCH purpose against a SCHOLARSHIP fund AND 600000 > 500000.
    res = api.create_payout(
        {"distribution_id": ctx["distribution"]["id"], "program_code": "LAB-9",
         "program_purpose": "RESEARCH", "allocated_amount_cents": 600_000},
        TEST_USERS["dev_headers"],
    )
    validate_error(res, ApiErrorId.ERR_PURPOSE_MISMATCH, 422)


def test_payout_allocation_cap_fires_when_purpose_complies(api):
    """PRD §3.7: 'the payout's `program_purpose` — one of `SCHOLARSHIP`,
    `PROFESSORSHIP`, `RESEARCH`, or `CAPITAL_PROJECTS` — must equal the fund's
    `purpose_restriction` unless that restriction is `UNRESTRICTED`, failing which
    the create is rejected with `ERR_PURPOSE_MISMATCH`.'
    PRD §3.7: 'The sum of `allocated_amount_cents` over the distribution's
    non-cancelled payouts, including the new one, must not exceed the distribution's
    `distributed_amount_cents`, failing which the create is rejected with
    `ERR_ALLOCATION_EXCEEDS_DISTRIBUTION`.'

    Design: Difficulty/priority_pair_validation_conflict/payout_purpose_mismatch_beats_allocation_cap_safety_over_fiscal
    """
    ctx = _setup_purpose_priority_world()

    # Purpose complies (SCHOLARSHIP == SCHOLARSHIP); only the cap fails.
    res = api.create_payout(
        {"distribution_id": ctx["distribution"]["id"], "program_code": "LAB-10",
         "program_purpose": "SCHOLARSHIP", "allocated_amount_cents": 600_000},
        TEST_USERS["dev_headers"],
    )
    validate_error(res, ApiErrorId.ERR_ALLOCATION_EXCEEDS_DISTRIBUTION, 422)

    ok = validate_success(api.create_payout(
        {"distribution_id": ctx["distribution"]["id"], "program_code": "LAB-11",
         "program_purpose": "SCHOLARSHIP", "allocated_amount_cents": 500_000},
        TEST_USERS["dev_headers"],
    ), 201)
    assert ok["payout_status"] == "SCHEDULED"
