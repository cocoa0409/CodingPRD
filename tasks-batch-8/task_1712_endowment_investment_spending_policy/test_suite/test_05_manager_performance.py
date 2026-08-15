"""Manager return math (Modified Dietz vs flow-blind), watchlist streaks, coverage intervals."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_manager_report,
    create_engaged_manager,
    create_manager_payload,
    create_pool,
    file_manager_report,
    finalize_open_quarter,
    get_pool,
    get_success_data,
    make_board_member_headers,
    set_target_allocations,
    setup_pool_world,
    create_allocation_item,
    validate_error,
    validate_success,
)


def test_modified_dietz_diverges_from_simple_flow_blind(api):
    """PRD §3.10: 'The official **Modified Dietz** return `return_bps`: let sumF be
    the sum of all flow amounts, and the Dietz denominator be `beginning_mv_cents`
    times 90 plus the sum over flows of (90 minus the flow's `day_offset`) times the
    flow's amount, weighting each flow by the fraction of the 90-day quarter it was
    invested — a mid-quarter inflow halves its weight.'
    PRD §3.10: 'Identical inputs yield a different basis-point figure from the Dietz
    value whenever `flows` is non-empty.'
    PRD §3.10: 'Finally `excess_bps` is `return_bps` minus `benchmark_return_bps`'

    Design: Difficulty/dual_variant_calc/manager_return_modified_dietz_diverges_from_simple_flow_blind
    """
    ctx = setup_pool_world(pool_name="Pool MR")
    report = file_manager_report(
        ctx["manager"]["id"], 1,
        1_000_000, 1_650_000,
        flows=[{"day_offset": 45, "amount_cents": 500_000}],
        benchmark_return_bps=300,
    )
    assert_manager_report(report)
    # Dietz: round_half_up(10000 * 150000 * 90 / (1000000*90 + 45*500000)) = 1200.
    assert report["return_bps"] == 1200
    # Flow-blind: round_half_up(10000 * 150000 / 1000000) = 1500.
    assert report["simple_return_bps"] == 1500
    assert report["excess_bps"] == 900
    assert report["return_bps"] != report["simple_return_bps"]


def test_dietz_and_simple_agree_only_when_flows_empty(api):
    """PRD §3.10: 'Identical inputs yield a different basis-point figure from the
    Dietz value whenever `flows` is non-empty.'
    PRD §3.10: 'the array may be empty'

    Design: Difficulty/dual_variant_calc/manager_return_modified_dietz_diverges_from_simple_flow_blind
    """
    ctx = setup_pool_world(pool_name="Pool MR")
    report = file_manager_report(
        ctx["manager"]["id"], 1,
        1_000_000, 1_100_000,
        flows=[],
        benchmark_return_bps=0,
    )
    # With no flows the weighting term vanishes: both formulas give 1000 bps.
    assert report["return_bps"] == 1000
    assert report["simple_return_bps"] == 1000
    assert report["excess_bps"] == 1000


def test_dietz_zero_denominator_and_zero_beginning_yield_zero_return(api):
    """PRD §3.10: 'When the denominator is 0 the return is 0'
    PRD §3.10: 'The **flow-blind** comparator `simple_return_bps`: 0 when
    `beginning_mv_cents` is 0'
    PRD §3.10: 'a negative `excess_bps` increments `neg_excess_streak` by 1 and
    resets `nonneg_excess_streak` to 0'

    Design: Corner/calculations/dietz_zero_denominator_and_zero_beginning_yield_zero_return
    """
    ctx = setup_pool_world(pool_name="Pool ZD")
    report = file_manager_report(
        ctx["manager"]["id"], 1, 0, 0, flows=[], benchmark_return_bps=250,
    )
    assert report["return_bps"] == 0
    assert report["simple_return_bps"] == 0
    assert report["excess_bps"] == -250

    manager = get_success_data(api.get_manager(ctx["manager"]["id"], TEST_USERS["io_headers"]))
    assert manager["neg_excess_streak"] == 1
    assert manager["nonneg_excess_streak"] == 0


def _file_negative_excess_report(manager_id, quarter):
    """BMV == EMV with no flows: return 0 bps; benchmark 100 -> excess -100."""
    return file_manager_report(manager_id, quarter, 1_000_000, 1_000_000,
                               flows=[], benchmark_return_bps=100)


def test_watchlist_does_not_fire_before_third_negative_streak(api):
    """PRD §3.10: 'Immediately after the streak update, auto-transitions fire on
    exact-equality thresholds: an `ENGAGED` manager whose `neg_excess_streak` reaches
    exactly 3 drops to `WATCHLIST`'

    Design: Difficulty/boundary_precision_check/manager_watchlist_fires_at_exactly_third_negative_excess_streak
    """
    ctx = setup_pool_world(pool_name="Pool STK")
    pool_id = ctx["pool"]["id"]
    manager_id = ctx["manager"]["id"]

    _file_negative_excess_report(manager_id, 1)
    finalize_open_quarter(pool_id, 1_000_000)
    _file_negative_excess_report(manager_id, 2)

    manager = get_success_data(api.get_manager(manager_id, TEST_USERS["io_headers"]))
    assert manager["neg_excess_streak"] == 2
    assert manager["engagement_status"] == "ENGAGED"


def test_watchlist_fires_at_exactly_third_negative_streak(api):
    """PRD §3.10: 'Immediately after the streak update, auto-transitions fire on
    exact-equality thresholds: an `ENGAGED` manager whose `neg_excess_streak` reaches
    exactly 3 drops to `WATCHLIST`'
    PRD §3.10: 'a negative `excess_bps` increments `neg_excess_streak` by 1 and
    resets `nonneg_excess_streak` to 0'

    Design: Difficulty/boundary_precision_check/manager_watchlist_fires_at_exactly_third_negative_excess_streak
    """
    ctx = setup_pool_world(pool_name="Pool STK")
    pool_id = ctx["pool"]["id"]
    manager_id = ctx["manager"]["id"]

    _file_negative_excess_report(manager_id, 1)
    finalize_open_quarter(pool_id, 1_000_000)
    _file_negative_excess_report(manager_id, 2)
    finalize_open_quarter(pool_id, 1_000_000)
    _file_negative_excess_report(manager_id, 3)

    manager = get_success_data(api.get_manager(manager_id, TEST_USERS["io_headers"]))
    assert manager["neg_excess_streak"] == 3
    assert manager["engagement_status"] == "WATCHLIST"


def test_engaged_manager_cannot_be_terminated_until_watchlisted(api):
    """PRD §3.10: 'Termination is a `BoardMember` governance action available only
    from `WATCHLIST` or `PROBATION`; an `ENGAGED` manager may not be terminated and
    the attempt is rejected with `ERR_INVALID_STATE_TRANSITION`.'

    Design: Corner/state_machines/engaged_manager_cannot_be_terminated_until_watchlisted
    """
    ctx = setup_pool_world(pool_name="Pool TM")
    manager_id = ctx["manager"]["id"]

    res = api.terminate_manager(manager_id, TEST_USERS["board_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

    manager = get_success_data(api.get_manager(manager_id, TEST_USERS["io_headers"]))
    assert manager["engagement_status"] == "ENGAGED"
    assert manager["coverage_end_quarter"] is None


def test_manager_report_beginning_mv_must_continue_prior_ending(api):
    """PRD §3.10: 'market-value continuity requires `beginning_mv_cents` to equal the
    manager's prior-quarter `ending_mv_cents` whenever a prior report exists
    (`ERR_MV_CONTINUITY_BREAK`)'

    Design: Corner/validations/manager_report_beginning_mv_must_continue_prior_ending
    """
    ctx = setup_pool_world(pool_name="Pool CT")
    pool_id = ctx["pool"]["id"]
    manager_id = ctx["manager"]["id"]
    file_manager_report(manager_id, 1, 0, 1_000_000,
                        flows=[{"day_offset": 0, "amount_cents": 1_000_000}])
    finalize_open_quarter(pool_id, 1_000_000)

    res = api.create_manager_report(
        {"manager_id": manager_id, "quarter_index": 2, "beginning_mv_cents": 999_999,
         "ending_mv_cents": 1_000_000, "flows": [], "benchmark_return_bps": 0},
        TEST_USERS["io_headers"],
    )
    validate_error(res, ApiErrorId.ERR_MV_CONTINUITY_BREAK, 422)

    ok = validate_success(api.create_manager_report(
        {"manager_id": manager_id, "quarter_index": 2, "beginning_mv_cents": 1_000_000,
         "ending_mv_cents": 1_000_000, "flows": [], "benchmark_return_bps": 0},
        TEST_USERS["io_headers"],
    ), 201)
    assert_manager_report(ok)
    assert ok["quarter_index"] == 2


def _setup_terminated_manager_world(api):
    """Manager A driven ENGAGED -> WATCHLIST over Q1-Q3, then terminated at quarter 3."""
    ctx = setup_pool_world(pool_name="Pool MC")
    pool_id = ctx["pool"]["id"]
    manager_id = ctx["manager"]["id"]
    for quarter in (1, 2, 3):
        _file_negative_excess_report(manager_id, quarter)
        finalize_open_quarter(pool_id, 1_000_000)
    terminated = get_success_data(api.terminate_manager(
        manager_id, make_board_member_headers("bm-1"),
    ))
    ctx["manager"] = terminated
    return ctx


def test_manager_coverage_adjacent_start_after_termination_engages(api):
    """PRD §3.10: 'Intervals are inclusive at both ends, so the candidate's start
    must be strictly greater than any terminated predecessor's end; adjacency —
    starting exactly one quarter after a predecessor's end — is allowed.'
    PRD §3.10: 'Termination sets `coverage_end_quarter` to the pool's
    `current_quarter_index`'

    Design: Difficulty/resource_temporal_overlap/manager_coverage_intervals_inclusive_overlap_vs_adjacency
    """
    ctx = _setup_terminated_manager_world(api)
    assert ctx["manager"]["coverage_end_quarter"] == 3

    manager_d = get_success_data(api.create_manager(
        create_manager_payload(ctx["pool"]["id"], manager_name="M D",
                               coverage_start_quarter=4),
        TEST_USERS["io_headers"],
    ))
    engaged = validate_success(api.engage_manager(manager_d["id"], TEST_USERS["io_headers"]), 200)
    assert engaged["engagement_status"] == "ENGAGED"


def test_manager_coverage_start_inside_closed_interval_conflicts(api):
    """PRD §3.10: 'Engagement (`PROSPECT` → `ENGAGED`) requires an `ACTIVE` pool and
    enforces a coverage-exclusivity rule per pool and asset class, failing as
    `ERR_WINDOW_CONFLICT`: the candidate's coverage interval — `coverage_start_quarter`
    onward, open-ended — must not intersect the interval of any other manager of the
    same pool and asset class whose status is not `PROSPECT` or `DECLINED`.'
    PRD §3.10: 'Historical quarters may never be double-covered.'

    Design: Difficulty/resource_temporal_overlap/manager_coverage_intervals_inclusive_overlap_vs_adjacency
    """
    ctx = _setup_terminated_manager_world(api)

    manager_e = get_success_data(api.create_manager(
        create_manager_payload(ctx["pool"]["id"], manager_name="M E",
                               coverage_start_quarter=3),
        TEST_USERS["io_headers"],
    ))
    res = api.engage_manager(manager_e["id"], TEST_USERS["io_headers"])
    validate_error(res, ApiErrorId.ERR_WINDOW_CONFLICT, 409)
