"""Spending distributions: smoothing, band clamp, review loop, underwater gate, OCC-adjacent rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_distribution,
    approve_exception,
    assert_distribution,
    create_adopted_policy,
    create_distribution,
    create_donor,
    create_engaged_manager,
    create_fund,
    create_gift,
    create_pool,
    distribute_distribution,
    endorse_exception,
    finalize_open_quarter,
    get_success_data,
    make_board_member_headers,
    propose_distribution,
    receive_gift,
    activate_fund,
    repropose_distribution,
    request_exception,
    request_revision_distribution,
    set_target_allocations,
    setup_funded_world,
    setup_pool_world,
    setup_underwater_world,
    validate_error,
    validate_success,
)

POLICY_500 = dict(spending_rate_bps=500, smoothing_window_quarters=4,
                  band_floor_bps=0, band_cap_bps=10_000, effective_from_fiscal_year=2026)


def _setup_band_world():
    """Pool BAND: fund unitized at Q1; Q1-Q4 finalized at rising prices; the FY2026
    distribution DISTRIBUTED at 747500; Q5 finalized. FY2027 is now projectable."""
    ctx = setup_funded_world(
        corpus_cents=10_000_000, pool_name="Pool BAND", with_policy=True,
        policy_overrides=dict(spending_rate_bps=650, smoothing_window_quarters=4,
                              band_floor_bps=100, band_cap_bps=800,
                              effective_from_fiscal_year=2026),
    )
    pool_id = ctx["pool"]["id"]
    manager_id = ctx["manager"]["id"]
    for quarter, mv in ((2, 11_000_000), (3, 12_000_000), (4, 13_000_000)):
        finalize_open_quarter(pool_id, mv, reports=[{
            "manager_id": manager_id, "beginning_mv_cents": mv - 1_000_000,
            "ending_mv_cents": mv,
        }])
    distribution = create_distribution(ctx["fund"]["id"], 2026)
    propose_distribution(distribution["id"])
    approve_distribution(distribution["id"])
    ctx["distribution_2026"] = distribute_distribution(distribution["id"])
    assert ctx["distribution_2026"]["final_amount_cents"] == 747_500
    finalize_open_quarter(pool_id, 15_080_000, reports=[{
        "manager_id": manager_id, "beginning_mv_cents": 13_000_000,
        "ending_mv_cents": 15_080_000,
        "flows": [{"day_offset": 0, "amount_cents": -747_500}],
    }])
    return ctx


def test_band_cap_clamps_raw_amount_on_create(api):
    """PRD §3.5: 'With a prior value, the cap is the prior amount multiplied by 10000
    plus `band_cap_bps` and divided by 10000, rounded half up; the floor is the prior
    amount multiplied by 10000 minus `band_floor_bps` and divided by 10000, rounded
    half up; and `band_adjusted_amount_cents` is the raw amount first clamped to at
    most the cap and then raised to at least the floor — the cap is evaluated first,
    then the floor.'
    PRD §3.5: '`prior_year_distribution_cents` holds that distribution's
    `final_amount_cents` and is null when none exists, which disables the clamp.'

    Design: Difficulty/combinatorial_formula/spending_distribution_band_cap_clamps_raw_amount_mode_a
    """
    ctx = _setup_band_world()

    created = create_distribution(ctx["fund"]["id"], 2027)
    assert_distribution(created)
    assert created["distribution_status"] == "PROJECTED"
    assert created["prior_year_distribution_cents"] == 747_500
    # Window Q2..Q5 fund MVs: 11000000, 12000000, 13000000, 15080000.
    assert created["smoothed_base_cents"] == 12_770_000
    assert created["raw_amount_cents"] == 830_050
    # cap = round_half_up(747500 * 10800 / 10000) = 807300 < raw 830050.
    assert created["band_adjusted_amount_cents"] == 807_300
    assert created["final_amount_cents"] == 807_300  # fund not underwater


def test_band_cap_clamped_amount_stable_through_propose(api):
    """PRD §3.5: 'The review loop runs `PROJECTED` → `PROPOSED` (propose by a
    `DevelopmentOfficer`, requiring an `ACTIVE` pool and fund, recomputing every
    derived amount against current data and stamping `proposed_by_user_id`)'

    Design: Difficulty/combinatorial_formula/spending_distribution_band_cap_clamps_raw_amount_mode_a
    """
    ctx = _setup_band_world()

    created = create_distribution(ctx["fund"]["id"], 2027)
    proposed = propose_distribution(created["id"])
    assert proposed["distribution_status"] == "PROPOSED"
    assert proposed["proposed_by_user_id"] == "dev-1"
    assert proposed["raw_amount_cents"] == 830_050
    assert proposed["band_adjusted_amount_cents"] == 807_300
    assert proposed["final_amount_cents"] == 807_300
    assert proposed["prior_year_distribution_cents"] == 747_500


def _setup_review_loop_world():
    ctx = setup_funded_world(corpus_cents=10_000_000, pool_name="Pool RL",
                             with_policy=True, policy_overrides=dict(POLICY_500))
    ctx["distribution"] = create_distribution(ctx["fund"]["id"], 2026)
    return ctx


def test_distribution_review_loop_cycles_twice_then_approves(api):
    """PRD §3.5: 'then `PROPOSED` → `REVISION_REQUESTED` (a `BoardMember` requesting
    revision) → back to `PROPOSED` via repropose by a `DevelopmentOfficer`, which
    recomputes identically and refreshes `proposed_by_user_id`; the
    propose/request-revision/repropose loop may iterate without bound.'

    Design: Difficulty/non_linear_state_machine/distribution_review_loop_cycles_proposed_revision_proposed
    """
    ctx = _setup_review_loop_world()
    dist_id = ctx["distribution"]["id"]

    propose_distribution(dist_id)
    for _ in range(2):
        revision = request_revision_distribution(dist_id)
        assert revision["distribution_status"] == "REVISION_REQUESTED"
        reproposed = repropose_distribution(dist_id)
        assert reproposed["distribution_status"] == "PROPOSED"

    approved = approve_distribution(dist_id)
    assert approved["distribution_status"] == "APPROVED"
    # Base 10000000 (single eligible quarter Q1) * 500 bps; no prior-year clamp.
    assert approved["final_amount_cents"] == 500_000


def test_distribution_review_loop_recomputes_amounts_each_pass(api):
    """PRD §3.5: 'recomputing every derived amount against current data and stamping
    `proposed_by_user_id`'
    PRD §3.5: 'The **raw amount** is the smoothed base multiplied by the policy's
    `spending_rate_bps` and divided by 10000, rounded half up.'

    Design: Difficulty/non_linear_state_machine/distribution_review_loop_cycles_proposed_revision_proposed
    """
    ctx = _setup_review_loop_world()
    dist_id = ctx["distribution"]["id"]

    first = propose_distribution(dist_id, user_id="dev-1")
    assert first["raw_amount_cents"] == 500_000
    assert first["smoothed_base_cents"] == 10_000_000
    assert first["proposed_by_user_id"] == "dev-1"

    request_revision_distribution(dist_id)
    second = repropose_distribution(dist_id, user_id="dev-2")
    assert second["distribution_status"] == "PROPOSED"
    assert second["raw_amount_cents"] == 500_000
    assert second["proposed_by_user_id"] == "dev-2"


def _setup_blocked_distribution_world():
    """Underwater fund; FY2026 distribution PROPOSED with no exception on file."""
    ctx = setup_underwater_world(pool_name="Pool XD", policy_overrides=dict(POLICY_500))
    ctx["distribution"] = create_distribution(ctx["fund"]["id"], 2026)
    ctx["distribution"] = propose_distribution(ctx["distribution"]["id"])
    return ctx


def test_approve_blocked_while_underwater_without_exception(api):
    """PRD §3.5: 'when the fund is underwater and non-exempt, an `APPROVED` exception
    for the fund and fiscal year must exist, failing which the approval is rejected
    with `ERR_UNDERWATER_SPENDING_BLOCKED`.'

    Design: Difficulty/cross_entity_state_dependency/distribution_approve_gated_by_exception_state_distribution_exception_pair
    """
    ctx = _setup_blocked_distribution_world()

    res = api.approve_distribution(ctx["distribution"]["id"], TEST_USERS["board_headers"])
    validate_error(res, ApiErrorId.ERR_UNDERWATER_SPENDING_BLOCKED, 422)

    still = get_success_data(api.get_distribution(
        ctx["distribution"]["id"], TEST_USERS["io_headers"],
    ))
    assert still["distribution_status"] == "PROPOSED"


def test_approve_succeeds_once_exception_reaches_approved(api):
    """PRD §3.5: 'Approval recomputes all derived amounts, sets `final_amount_cents`
    per the gate (0 when underwater without exception; the exception-capped minimum
    with one; otherwise the band-adjusted amount), records `applied_exception_id`
    when an exception is used, and stamps `approved_by_user_id`.'
    PRD §3.5: 'in which case it is the smaller of that exception's
    `approved_amount_cents` and `band_adjusted_amount_cents`.'

    Design: Difficulty/cross_entity_state_dependency/distribution_approve_gated_by_exception_state_distribution_exception_pair
    """
    ctx = _setup_blocked_distribution_world()
    dist_id = ctx["distribution"]["id"]

    res = api.approve_distribution(dist_id, TEST_USERS["board_headers"])
    validate_error(res, ApiErrorId.ERR_UNDERWATER_SPENDING_BLOCKED, 422)

    # Context check: window Q1+Q2 eligible MVs 10000000 and 4000000 -> base 7000000.
    proposed = get_success_data(api.get_distribution(dist_id, TEST_USERS["io_headers"]))
    assert proposed["smoothed_base_cents"] == 7_000_000
    assert proposed["raw_amount_cents"] == 350_000

    exception = request_exception(ctx["fund"]["id"], 2026, 300_000)
    endorse_exception(exception["id"])
    approve_exception(exception["id"], 300_000)

    approved = approve_distribution(dist_id)
    assert approved["distribution_status"] == "APPROVED"
    assert approved["final_amount_cents"] == 300_000  # min(300000, 350000)
    assert approved["applied_exception_id"] == exception["id"]


def test_approve_projected_underwater_returns_state_error_not_safety_error(api):
    """PRD §2.8: '(6) lifecycle-state permission for the requested transition,
    failing as `ERR_INVALID_STATE_TRANSITION`;'
    PRD §2.8: '(10) the underwater spending lock, failing as
    `ERR_UNDERWATER_SPENDING_BLOCKED`;'
    PRD §2.8: 'the server evaluates them in a fixed priority order and reports the
    earliest failure.'

    Design: Difficulty/priority_pair_validation_conflict/approve_projected_underwater_returns_409_state_over_422_safety
    """
    ctx = setup_underwater_world(pool_name="Pool PC1", policy_overrides=dict(POLICY_500))
    # Distribution stays PROJECTED (never proposed) while the fund is underwater.
    distribution = create_distribution(ctx["fund"]["id"], 2026)

    res = api.approve_distribution(distribution["id"], TEST_USERS["board_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)


def test_approve_proposed_underwater_without_exception_reaches_safety_error(api):
    """PRD §2.8: 'the server evaluates them in a fixed priority order and reports the
    earliest failure.'
    PRD §3.5: 'failing which the approval is rejected with
    `ERR_UNDERWATER_SPENDING_BLOCKED`.'

    Design: Difficulty/priority_pair_validation_conflict/approve_projected_underwater_returns_409_state_over_422_safety
    """
    ctx = setup_underwater_world(pool_name="Pool PC1", policy_overrides=dict(POLICY_500))
    distribution = create_distribution(ctx["fund"]["id"], 2026)
    propose_distribution(distribution["id"])

    res = api.approve_distribution(distribution["id"], TEST_USERS["board_headers"])
    validate_error(res, ApiErrorId.ERR_UNDERWATER_SPENDING_BLOCKED, 422)


def test_distribution_create_without_applicable_policy_or_in_range_window(api):
    """PRD §3.5: 'the fiscal year must lie between the pool's
    `inception_fiscal_year` and one past the current fiscal year inclusive, where the
    current fiscal year is the inception year plus the whole number of times 4
    divides into `current_quarter_index` — out-of-range years are
    `ERR_WINDOW_CONFLICT`.'
    PRD §3.3: 'if none qualifies, the operation is rejected with
    `ERR_NO_APPLICABLE_POLICY`.'

    Design: Corner/validations/distribution_create_without_applicable_policy_or_in_range_window
    """
    pool = create_pool(pool_name="Pool NP", inception_fiscal_year=2026)
    fund = create_fund(pool["id"], fund_code="FNP", fund_name="Fund NP")
    donor = create_donor(donor_name="D NP")
    create_gift(fund["id"], donor["id"], "NP1", gift_type="CORPUS", amount_cents=5_000_000)
    activate_fund(fund["id"])

    # Quarter 0: current fiscal year 2026; 2028 is beyond current + 1.
    res1 = api.create_distribution({"fund_id": fund["id"], "fiscal_year": 2028},
                                   TEST_USERS["dev_headers"])
    validate_error(res1, ApiErrorId.ERR_WINDOW_CONFLICT, 409)

    res2 = api.create_distribution({"fund_id": fund["id"], "fiscal_year": 2026},
                                   TEST_USERS["dev_headers"])
    validate_error(res2, ApiErrorId.ERR_NO_APPLICABLE_POLICY, 422)


def test_scoped_uniqueness_enforced_for_gifts_reports_distributions(api):
    """PRD §2.9: 'Create endpoints reject duplicates with `ERR_DUPLICATE_RECORD`
    (HTTP 409).'
    PRD §2.9: 'the pair of `fund_id` and `external_ref` among all non-`CANCELLED`
    gifts of a fund;'
    PRD §2.9: 'the pair of `manager_id` and `quarter_index` for manager reports;'
    PRD §2.9: 'the pair of `fund_id` and `fiscal_year` among non-`CANCELLED`
    distributions;'
    PRD §2.8: '(13) uniqueness constraints, failing as `ERR_DUPLICATE_RECORD`; (14)
    temporal window rules, failing as `ERR_WINDOW_CONFLICT`;'
    PRD §2.8: 'the server evaluates them in a fixed priority order and reports the
    earliest failure.'

    Design: Corner/validations/scoped_uniqueness_enforced_for_gifts_reports_distributions
    """
    ctx = setup_funded_world(corpus_cents=5_000_000, quarter1_ending_mv=5_000_000,
                             pool_name="Pool DP", with_policy=True,
                             policy_overrides=dict(POLICY_500))
    create_distribution(ctx["fund"]["id"], 2026)

    # (fund, external_ref) — DP's seed gift used external_ref GIFT-SEED.
    res1 = api.create_gift(
        {"fund_id": ctx["fund"]["id"], "donor_id": ctx["donor"]["id"],
         "external_ref": "GIFT-SEED", "gift_type": "EXPENDABLE", "amount_cents": 100},
        TEST_USERS["dev_headers"],
    )
    validate_error(res1, ApiErrorId.ERR_DUPLICATE_RECORD, 409)

    # (manager, quarter_index) — quarter 1 already has a report; uniqueness (13)
    # fires even though the quarter is also no longer open (14).
    res2 = api.create_manager_report(
        {"manager_id": ctx["manager"]["id"], "quarter_index": 1,
         "beginning_mv_cents": 0, "ending_mv_cents": 5_000_000,
         "flows": [], "benchmark_return_bps": 0},
        TEST_USERS["io_headers"],
    )
    validate_error(res2, ApiErrorId.ERR_DUPLICATE_RECORD, 409)

    # (fund, fiscal_year) — a FY2026 distribution already exists.
    res3 = api.create_distribution({"fund_id": ctx["fund"]["id"], "fiscal_year": 2026},
                                   TEST_USERS["dev_headers"])
    validate_error(res3, ApiErrorId.ERR_DUPLICATE_RECORD, 409)


def test_distribute_rejected_when_redemption_exceeds_held_units(api):
    """PRD §3.5: 'the redemption burns `units_redeemed_micro` computed as
    `final_amount_cents` multiplied by one billion and divided by the pool's
    `current_unit_price_millicents`, rounded half up, and that quantity must not
    exceed the fund's `units_held_micro`, failing which the request is rejected with
    `ERR_INSUFFICIENT_UNITS`.'
    PRD §3.5: 'A fund is exempt from the gate when its `endowment_class` is
    `QUASI_ENDOWMENT`'

    Design: Corner/validations/distribute_rejected_when_redemption_exceeds_held_units
    """
    # QUASI fund at the 2000 bps rate cap; Q2 crash to price 2000 millicents.
    ctx = setup_funded_world(
        corpus_cents=5_000_000, quarter1_ending_mv=5_000_000,
        endowment_class="QUASI_ENDOWMENT", pool_name="Pool IU",
        with_policy=True,
        policy_overrides=dict(spending_rate_bps=2000, smoothing_window_quarters=4,
                              band_floor_bps=0, band_cap_bps=10_000,
                              effective_from_fiscal_year=2026),
    )
    pool_id = ctx["pool"]["id"]
    finalize_open_quarter(pool_id, 100_000, reports=[{
        "manager_id": ctx["manager"]["id"], "beginning_mv_cents": 5_000_000,
        "ending_mv_cents": 100_000,
    }])

    distribution = create_distribution(ctx["fund"]["id"], 2026)
    # Base (5000000 + 100000) / 2 = 2550000; raw = 2550000 * 2000 / 10000 = 510000.
    assert distribution["raw_amount_cents"] == 510_000
    propose_distribution(distribution["id"])
    approved = approve_distribution(distribution["id"])
    assert approved["final_amount_cents"] == 510_000  # QUASI exempt from the gate

    res = api.distribute_distribution(distribution["id"], TEST_USERS["io_headers"])
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_UNITS, 422)

    still = get_success_data(api.get_distribution(distribution["id"], TEST_USERS["io_headers"]))
    assert still["distribution_status"] == "APPROVED"
    fund = get_success_data(api.get_fund(ctx["fund"]["id"], TEST_USERS["io_headers"]))
    assert fund["units_held_micro"] == 50_000_000_000


def test_segregation_of_duties_distribution_approver_must_differ_from_proposer(api):
    """PRD §2.1: 'approving a distribution requires the approver to differ from the
    distribution's `proposed_by_user_id`'
    PRD §2.1: 'Any breach of these rules is rejected with
    `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403).'

    Design: Corner/rbac/segregation_of_duties_distribution_approver_must_differ_from_proposer
    """
    ctx = setup_funded_world(corpus_cents=10_000_000, pool_name="Pool DS",
                             with_policy=True, policy_overrides=dict(POLICY_500))
    distribution = create_distribution(ctx["fund"]["id"], 2026, creator_user_id="dev-1")
    propose_distribution(distribution["id"], user_id="dev-1")

    # The proposer's user id, acting with a board role, still cannot approve.
    res = api.approve_distribution(
        distribution["id"], make_board_member_headers("dev-1"),
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION, 403)

    approved = approve_distribution(distribution["id"], user_id="bm-1")
    assert approved["distribution_status"] == "APPROVED"
