"""Quarter-close pipeline ordering, valuation sequencing, supersede, and OCC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_fund,
    assert_valuation,
    create_donor,
    create_engaged_manager,
    create_fund,
    create_gift,
    create_pool,
    finalize_open_quarter,
    finalize_valuation,
    get_pool,
    get_success_data,
    open_valuation,
    receive_gift,
    resume_pool,
    set_target_allocations,
    setup_funded_world,
    setup_pool_world,
    setup_zero_manager_pool,
    suspend_pool,
    validate_error,
    validate_success,
)


def _setup_pipeline_world():
    """Fund underwater after a Q2 crash; a second CORPUS gift received in open Q3."""
    ctx = setup_funded_world(corpus_cents=10_000_000, pool_name="Pool PIPE")
    pool_id = ctx["pool"]["id"]
    manager_id = ctx["manager"]["id"]
    finalize_open_quarter(pool_id, 4_000_000, reports=[{
        "manager_id": manager_id, "beginning_mv_cents": 10_000_000,
        "ending_mv_cents": 4_000_000,
    }])
    gift2 = create_gift(ctx["fund"]["id"], ctx["donor"]["id"], "P2",
                        gift_type="CORPUS", amount_cents=6_000_000)
    receive_gift(gift2["id"])
    ctx["gift2"] = gift2
    return ctx


def test_pipeline_price_fixed_from_pre_flow_units_before_unitization(api):
    """PRD §3.4: 'The `final_unit_price_millicents` is computed from
    `final_pool_market_value_cents` and the pool's total units outstanding measured
    *before* any gift unitization or redemption of this close'
    PRD §3.4: 'Recomputing the price after unitization is forbidden.'

    Design: Difficulty/combinatorial_formula/quarter_close_pipeline_order_gift_cures_underwater_mode_c
    """
    ctx = _setup_pipeline_world()
    pool_id = ctx["pool"]["id"]

    valuation = finalize_open_quarter(pool_id, 10_400_000, reports=[{
        "manager_id": ctx["manager"]["id"], "beginning_mv_cents": 4_000_000,
        "ending_mv_cents": 10_400_000,
        "flows": [{"day_offset": 0, "amount_cents": 6_000_000}],
    }])
    assert valuation["final_unit_price_millicents"] == 104_000

    pool = get_success_data(api.get_pool(pool_id, TEST_USERS["io_headers"]))
    assert pool["current_unit_price_millicents"] == 104_000

    gift2 = get_success_data(api.get_gift(ctx["gift2"]["id"], TEST_USERS["io_headers"]))
    # round_half_up(6000000 * 1e9 / 104000) at the step-1 price.
    assert gift2["units_purchased_micro"] == 57_692_307_692
    assert gift2["unitized_quarter_index"] == 3


def test_pipeline_unitization_feeds_underwater_refresh_and_cures_fund(api):
    """PRD §3.4: '5. **Market value and underwater refresh.** Each fund's
    `market_value_cents` is recomputed as its post-unitization `units_held_micro`
    multiplied by the new `current_unit_price_millicents` and divided by one billion,
    rounded half up'
    PRD §3.4: '4. **HGV refresh.** For each `CORPUS` gift unitized in step 3, the
    fund's `historic_gift_value_cents` increases by the gift's `amount_cents`.'
    PRD §3.4: '6. **Posture transitions.** Funds whose refresh shows them underwater
    and non-exempt move `spending_posture` from `NORMAL` to `SPENDING_SUSPENDED`;
    funds no longer underwater — or newly exempt by term maturity — move from
    `SPENDING_SUSPENDED` back to `NORMAL`.'

    Design: Difficulty/combinatorial_formula/quarter_close_pipeline_order_gift_cures_underwater_mode_c
    """
    ctx = _setup_pipeline_world()
    pool_id = ctx["pool"]["id"]

    fund_suspended = get_success_data(api.get_fund(ctx["fund"]["id"], TEST_USERS["io_headers"]))
    assert fund_suspended["spending_posture"] == "SPENDING_SUSPENDED"
    assert fund_suspended["is_underwater"] is True

    finalize_open_quarter(pool_id, 10_400_000, reports=[{
        "manager_id": ctx["manager"]["id"], "beginning_mv_cents": 4_000_000,
        "ending_mv_cents": 10_400_000,
        "flows": [{"day_offset": 0, "amount_cents": 6_000_000}],
    }])

    fund = get_success_data(api.get_fund(ctx["fund"]["id"], TEST_USERS["io_headers"]))
    assert fund["historic_gift_value_cents"] == 16_000_000
    assert fund["market_value_cents"] == 16_400_000  # 157692307692 units at 104000
    assert fund["is_underwater"] is False
    assert fund["spending_posture"] == "NORMAL"


def test_double_finalize_and_terminal_valuation_lockdown(api):
    """PRD §3.4: 'Finalization converts the open `PRELIMINARY` valuation to `FINAL`.'
    PRD §2.8: '(6) lifecycle-state permission for the requested transition, failing
    as `ERR_INVALID_STATE_TRANSITION`'

    Design: Corner/state_machines/double_finalize_and_terminal_valuation_lockdown
    """
    ctx = setup_zero_manager_pool(pool_name="Pool DF")
    pool_id = ctx["pool"]["id"]
    valuation = open_valuation(pool_id, 0)
    finalize_valuation(valuation["id"], pool_id, 0)

    res = api.finalize_valuation(
        valuation["id"],
        {"final_pool_market_value_cents": 0,
         "expected_pool_version": get_pool(pool_id)["version"]},
        TEST_USERS["io_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)


def test_second_preliminary_valuation_for_open_quarter_rejected(api):
    """PRD §3.4: 'creating a valuation for any other quarter — or when a
    `PRELIMINARY` or `FINAL` valuation already exists for the open quarter — is
    rejected with `ERR_VALUATION_OUT_OF_ORDER`.'

    Design: Corner/validations/second_preliminary_valuation_for_open_quarter_rejected
    """
    ctx = setup_zero_manager_pool(pool_name="Pool VO")
    pool_id = ctx["pool"]["id"]
    first = open_valuation(pool_id, 0)

    res = api.create_valuation(
        {"pool_id": pool_id, "estimated_pool_market_value_cents": 0},
        TEST_USERS["io_headers"],
    )
    validate_error(res, ApiErrorId.ERR_VALUATION_OUT_OF_ORDER, 409)

    still = get_success_data(api.get_valuation(first["id"], TEST_USERS["io_headers"]))
    assert still["valuation_status"] == "PRELIMINARY"
    assert still["quarter_index"] == 1


def test_supersede_locked_once_quarter_unitized_a_gift(api):
    """PRD §3.4: 'The consumption lock rejects the supersede with
    `ERR_VALUATION_LOCKED` when any gift has `unitized_quarter_index` equal to that
    quarter, any payout was swept in that quarter, any manager report exists for that
    quarter, or any distribution reached `DISTRIBUTED` after that finalize'

    Design: Corner/validations/supersede_locked_once_quarter_unitized_a_gift
    """
    ctx = setup_zero_manager_pool(pool_name="Pool VL")
    pool_id = ctx["pool"]["id"]
    fund = create_fund(pool_id, fund_code="FVL", fund_name="Fund VL")
    donor = create_donor(donor_name="D VL")
    gift = create_gift(fund["id"], donor["id"], "VL1", gift_type="CORPUS",
                       amount_cents=5_000_000)
    activate_fund(fund["id"])
    receive_gift(gift["id"])
    valuation = finalize_open_quarter(pool_id, 0)

    res = api.supersede_valuation(
        valuation["id"],
        {"revised_pool_market_value_cents": 0,
         "expected_pool_version": get_pool(pool_id)["version"]},
        TEST_USERS["io_headers"],
    )
    validate_error(res, ApiErrorId.ERR_VALUATION_LOCKED, 409)

    still = get_success_data(api.get_valuation(valuation["id"], TEST_USERS["io_headers"]))
    assert still["valuation_status"] == "FINAL"
    pool = get_success_data(api.get_pool(pool_id, TEST_USERS["io_headers"]))
    assert pool["current_quarter_index"] == 1


def test_finalize_requires_all_manager_reports_and_matching_market_value(api):
    """PRD §3.4: 'every investment manager of the pool whose coverage interval
    contains the quarter (a `coverage_start_quarter` no later than the quarter, and a
    `coverage_end_quarter` either null or no earlier than the quarter) and whose
    `engagement_status` is neither `PROSPECT` nor `DECLINED` must have filed a report
    for that quarter, else `ERR_MANAGER_REPORT_MISSING`; the supplied
    `final_pool_market_value_cents` must exactly equal the sum of `ending_mv_cents`
    across those eligible reports, else `ERR_POOL_MV_MISMATCH`'

    Design: Corner/validations/finalize_requires_all_manager_reports_and_matching_market_value
    """
    ctx = setup_pool_world(pool_name="Pool RC")
    pool_id = ctx["pool"]["id"]
    manager_id = ctx["manager"]["id"]
    valuation = open_valuation(pool_id, 1_000_000)
    pool_version = get_pool(pool_id)["version"]

    res1 = api.finalize_valuation(
        valuation["id"],
        {"final_pool_market_value_cents": 1_000_000, "expected_pool_version": pool_version},
        TEST_USERS["io_headers"],
    )
    validate_error(res1, ApiErrorId.ERR_MANAGER_REPORT_MISSING, 422)

    from test_helpers import file_manager_report
    file_manager_report(manager_id, 1, 0, 1_000_000,
                        flows=[{"day_offset": 0, "amount_cents": 1_000_000}])

    res2 = api.finalize_valuation(
        valuation["id"],
        {"final_pool_market_value_cents": 1_000_001, "expected_pool_version": pool_version},
        TEST_USERS["io_headers"],
    )
    validate_error(res2, ApiErrorId.ERR_POOL_MV_MISMATCH, 422)

    finalized = validate_success(api.finalize_valuation(
        valuation["id"],
        {"final_pool_market_value_cents": 1_000_000, "expected_pool_version": pool_version},
        TEST_USERS["io_headers"],
    ), 200)
    assert finalized["valuation_status"] == "FINAL"


def test_occ_finalize_rejected_with_stale_pool_version_then_recovers(api):
    """PRD §2.7: 'Each such request must carry `expected_pool_version` as a
    non-optional field holding the pool's `version` as the client last read it. If
    the pool's current `version` has advanced since that read — for example because a
    suspend/resume cycle or another finalize intervened — the request is rejected
    with `ERR_STALE_POOL_VERSION` (HTTP 412).'
    PRD §2.6: 'Suspending a pool (an `EndowmentAdmin` action moving `pool_status`
    from `ACTIVE` to `SUSPENDED`) and resuming it (`SUSPENDED` back to `ACTIVE`)
    each increment the pool's `version` by 1.'

    Design: Corner/cross_cutting_complexity_layers/occ_finalize_rejected_with_stale_pool_version_then_recovers
    """
    ctx = setup_zero_manager_pool(pool_name="Pool OC")
    pool_id = ctx["pool"]["id"]
    stale_version = ctx["pool"]["version"]
    valuation = open_valuation(pool_id, 0)

    suspend_pool(pool_id)
    resume_pool(pool_id)
    pool_after = get_success_data(api.get_pool(pool_id, TEST_USERS["io_headers"]))
    assert pool_after["version"] == stale_version + 2

    res = api.finalize_valuation(
        valuation["id"],
        {"final_pool_market_value_cents": 0, "expected_pool_version": stale_version},
        TEST_USERS["io_headers"],
    )
    validate_error(res, ApiErrorId.ERR_STALE_POOL_VERSION, 412)

    finalized = validate_success(api.finalize_valuation(
        valuation["id"],
        {"final_pool_market_value_cents": 0,
         "expected_pool_version": pool_after["version"]},
        TEST_USERS["io_headers"],
    ), 200)
    assert finalized["valuation_status"] == "FINAL"

    pool_final = get_success_data(api.get_pool(pool_id, TEST_USERS["io_headers"]))
    assert pool_final["version"] == pool_after["version"] + 1


def test_supersede_rolls_back_unconsumed_quarter_and_refinalizes(api):
    """PRD §3.4: 'A successful supersede moves the valuation to `SUPERSEDED`, rolls
    the pool back to the end of the prior quarter — `current_quarter_index`
    decremented, `current_unit_price_millicents` and `total_market_value_cents`
    restored to the prior quarter's `FINAL` values (the inception price and 0 when
    the superseded quarter was quarter 1) ... then creates a corrective `PRELIMINARY`
    valuation for the same quarter with `supersedes_valuation_id` pointing at the
    superseded record and `estimated_pool_market_value_cents` taken from the
    request's `revised_pool_market_value_cents`.'

    Design: Corner/cross_cutting_complexity_layers/supersede_rolls_back_unconsumed_quarter_and_refinalizes
    """
    ctx = setup_zero_manager_pool(pool_name="Pool SS")
    pool_id = ctx["pool"]["id"]
    valuation = finalize_open_quarter(pool_id, 0)

    res = api.supersede_valuation(
        valuation["id"],
        {"revised_pool_market_value_cents": 0,
         "expected_pool_version": get_pool(pool_id)["version"]},
        TEST_USERS["io_headers"],
    )
    corrective = validate_success(res, 201)
    assert_valuation(corrective)
    assert corrective["quarter_index"] == 1
    assert corrective["valuation_status"] == "PRELIMINARY"
    assert corrective["supersedes_valuation_id"] == valuation["id"]

    old = get_success_data(api.get_valuation(valuation["id"], TEST_USERS["io_headers"]))
    assert old["valuation_status"] == "SUPERSEDED"

    pool = get_success_data(api.get_pool(pool_id, TEST_USERS["io_headers"]))
    assert pool["current_quarter_index"] == 0
    assert pool["current_unit_price_millicents"] == 100_000

    refinalized = finalize_valuation(corrective["id"], pool_id, 0)
    assert refinalized["valuation_status"] == "FINAL"
    pool_after = get_success_data(api.get_pool(pool_id, TEST_USERS["io_headers"]))
    assert pool_after["current_quarter_index"] == 1
