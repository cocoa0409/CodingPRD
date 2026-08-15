"""Underwater funds: posture dimension, exception lifecycle, and expiry/rescind cascades."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_distribution,
    approve_exception,
    create_distribution,
    endorse_exception,
    finalize_open_quarter,
    get_success_data,
    make_board_member_headers,
    make_investment_officer_headers,
    propose_distribution,
    request_exception,
    rescind_exception,
    setup_exception_world,
    setup_funded_world,
    setup_underwater_world,
    validate_error,
    validate_success,
)

POLICY_500 = dict(spending_rate_bps=500, smoothing_window_quarters=4,
                  band_floor_bps=0, band_cap_bps=10_000, effective_from_fiscal_year=2026)


def _finalize_flat_quarter(ctx, mv):
    manager_id = ctx["manager"]["id"]
    finalize_open_quarter(ctx["pool"]["id"], mv, reports=[{
        "manager_id": manager_id, "beginning_mv_cents": mv, "ending_mv_cents": mv,
    }])


def test_fund_status_static_while_posture_moves_to_suspended(api):
    """PRD §3.1: 'A new fund starts in `DRAFT` lifecycle (`fund_status`) with a
    `spending_posture` of `NORMAL` — two parallel, independent dimensions'
    PRD §3.4: 'Funds whose refresh shows them underwater and non-exempt move
    `spending_posture` from `NORMAL` to `SPENDING_SUSPENDED`'

    Design: Difficulty/non_linear_state_machine/fund_parallel_dimensions_lifecycle_independent_of_spending_posture
    """
    ctx = setup_funded_world(corpus_cents=10_000_000, pool_name="Pool PD",
                             with_policy=True, policy_overrides=dict(POLICY_500))

    fund_q1 = get_success_data(api.get_fund(ctx["fund"]["id"], TEST_USERS["io_headers"]))
    assert fund_q1["fund_status"] == "ACTIVE"
    assert fund_q1["spending_posture"] == "NORMAL"

    # Q2 crash to price 40000: market value 4000000 < HGV 10000000.
    finalize_open_quarter(ctx["pool"]["id"], 4_000_000, reports=[{
        "manager_id": ctx["manager"]["id"], "beginning_mv_cents": 10_000_000,
        "ending_mv_cents": 4_000_000,
    }])

    fund_q2 = get_success_data(api.get_fund(ctx["fund"]["id"], TEST_USERS["io_headers"]))
    assert fund_q2["fund_status"] == "ACTIVE"
    assert fund_q2["spending_posture"] == "SPENDING_SUSPENDED"
    assert fund_q2["is_underwater"] is True


def test_fund_status_static_while_posture_moves_to_exception_active(api):
    """PRD §3.6: 'Approval stamps `approved_by_user_id` and flips the fund's
    `spending_posture` from `SPENDING_SUSPENDED` to `EXCEPTION_ACTIVE` — this
    approval is what flips the fund.'
    PRD §3.1: 'two parallel, independent dimensions'

    Design: Difficulty/non_linear_state_machine/fund_parallel_dimensions_lifecycle_independent_of_spending_posture
    """
    ctx = setup_underwater_world(pool_name="Pool PD", policy_overrides=dict(POLICY_500))

    exception = request_exception(ctx["fund"]["id"], 2026, 300_000)
    endorse_exception(exception["id"])
    approve_exception(exception["id"], 300_000)

    fund = get_success_data(api.get_fund(ctx["fund"]["id"], TEST_USERS["io_headers"]))
    assert fund["fund_status"] == "ACTIVE"
    assert fund["spending_posture"] == "EXCEPTION_ACTIVE"


def _setup_expiry_world():
    """Underwater fund; exception APPROVED; FY2026 distribution APPROVED citing it;
    Q3 finalized flat. The Q4 finalize (last quarter of FY2026) is the trigger."""
    ctx = setup_exception_world(pool_name="Pool EC3", policy_overrides=dict(POLICY_500))
    distribution = create_distribution(ctx["fund"]["id"], 2026)
    propose_distribution(distribution["id"])
    ctx["distribution"] = approve_distribution(distribution["id"])
    assert ctx["distribution"]["final_amount_cents"] == 300_000
    assert ctx["distribution"]["applied_exception_id"] == ctx["exception"]["id"]
    _finalize_flat_quarter(ctx, 4_000_000)
    return ctx


def test_finalize_expiry_reverts_distribution_and_expires_exception(api):
    """PRD §3.6: '**Expiry:** when a valuation finalize closes the last quarter of
    the exception's fiscal year — the quarter whose index equals 4 times (fiscal year
    minus `inception_fiscal_year` plus 1) — while the exception is still unused, it
    becomes `EXPIRED`; any distribution holding `applied_exception_id` equal to this
    exception in status `APPROVED` reverts from `APPROVED` to `PROPOSED` with
    `final_amount_cents` recomputed (0 while the fund remains underwater)'

    Design: Difficulty/transitive_cascade/finalize_exception_expiry_cascades_distribution_revert_and_posture_depth3
    """
    ctx = _setup_expiry_world()

    _finalize_flat_quarter(ctx, 4_000_000)  # Q4: last quarter of FY2026

    exception = get_success_data(api.get_exception(ctx["exception"]["id"],
                                                   TEST_USERS["io_headers"]))
    assert exception["exception_status"] == "EXPIRED"

    distribution = get_success_data(api.get_distribution(ctx["distribution"]["id"],
                                                         TEST_USERS["io_headers"]))
    assert distribution["distribution_status"] == "PROPOSED"
    assert distribution["final_amount_cents"] == 0
    assert distribution["applied_exception_id"] is None


def test_finalize_expiry_returns_posture_to_spending_suspended(api):
    """PRD §3.6: 'any distribution holding `applied_exception_id` equal to this
    exception in status `APPROVED` reverts from `APPROVED` to `PROPOSED` with
    `final_amount_cents` recomputed (0 while the fund remains underwater), and the
    fund's posture returns to `SPENDING_SUSPENDED`.'
    PRD §3.6: 'In both the expiry and rescission cases, if the fund is no longer
    underwater the next finalize moves its posture onward to `NORMAL`.'

    Design: Difficulty/transitive_cascade/finalize_exception_expiry_cascades_distribution_revert_and_posture_depth3
    """
    ctx = _setup_expiry_world()

    fund_before = get_success_data(api.get_fund(ctx["fund"]["id"], TEST_USERS["io_headers"]))
    assert fund_before["spending_posture"] == "EXCEPTION_ACTIVE"

    _finalize_flat_quarter(ctx, 4_000_000)

    fund_after = get_success_data(api.get_fund(ctx["fund"]["id"], TEST_USERS["io_headers"]))
    assert fund_after["is_underwater"] is True
    assert fund_after["spending_posture"] == "SPENDING_SUSPENDED"

    exception = get_success_data(api.get_exception(ctx["exception"]["id"],
                                                   TEST_USERS["io_headers"]))
    assert exception["exception_status"] == "EXPIRED"


def _setup_rescind_world():
    ctx = setup_exception_world(pool_name="Pool RC2", policy_overrides=dict(POLICY_500))
    distribution = create_distribution(ctx["fund"]["id"], 2026)
    propose_distribution(distribution["id"])
    ctx["distribution"] = approve_distribution(distribution["id"])
    return ctx


def test_rescind_reverts_distribution_and_marks_exception_rescinded(api):
    """PRD §3.6: '**Rescission:** a `BoardMember` may rescind an `APPROVED`
    exception, which applies the same distribution-reversion cascade — linked
    `APPROVED` distributions revert to `PROPOSED` with recomputed
    `final_amount_cents`'

    Design: Difficulty/transitive_cascade/exception_rescind_cascades_distribution_revert_and_posture_depth2
    """
    ctx = _setup_rescind_world()

    rescinded = rescind_exception(ctx["exception"]["id"], user_id="bm-2")
    assert rescinded["exception_status"] == "RESCINDED"

    distribution = get_success_data(api.get_distribution(ctx["distribution"]["id"],
                                                         TEST_USERS["io_headers"]))
    assert distribution["distribution_status"] == "PROPOSED"
    assert distribution["final_amount_cents"] == 0


def test_rescind_returns_posture_to_spending_suspended(api):
    """PRD §3.6: 'and returns the fund's posture from `EXCEPTION_ACTIVE` to
    `SPENDING_SUSPENDED`.'

    Design: Difficulty/transitive_cascade/exception_rescind_cascades_distribution_revert_and_posture_depth2
    """
    ctx = _setup_rescind_world()

    fund_before = get_success_data(api.get_fund(ctx["fund"]["id"], TEST_USERS["io_headers"]))
    assert fund_before["spending_posture"] == "EXCEPTION_ACTIVE"

    rescind_exception(ctx["exception"]["id"], user_id="bm-2")

    fund_after = get_success_data(api.get_fund(ctx["fund"]["id"], TEST_USERS["io_headers"]))
    assert fund_after["spending_posture"] == "SPENDING_SUSPENDED"
    assert fund_after["is_underwater"] is True


def test_underwater_flag_equality_is_not_underwater(api):
    """PRD §3.4: '`is_underwater` is set to true exactly when `market_value_cents` is
    strictly less than `historic_gift_value_cents` — equality is not underwater.'

    Design: Difficulty/boundary_precision_check/underwater_flag_strict_less_than_equality_is_not_underwater
    """
    ctx = setup_funded_world(corpus_cents=10_000_000, quarter1_ending_mv=10_000_000,
                             pool_name="Pool EQL")

    fund = get_success_data(api.get_fund(ctx["fund"]["id"], TEST_USERS["io_headers"]))
    assert fund["market_value_cents"] == 10_000_000
    assert fund["historic_gift_value_cents"] == 10_000_000
    assert fund["is_underwater"] is False, "MV == HGV must not be underwater"
    assert fund["spending_posture"] == "NORMAL"


def test_underwater_flag_flips_one_cent_below_parity(api):
    """PRD §3.4: '`is_underwater` is set to true exactly when `market_value_cents` is
    strictly less than `historic_gift_value_cents` — equality is not underwater.'
    PRD §3.4: 'Funds whose refresh shows them underwater and non-exempt move
    `spending_posture` from `NORMAL` to `SPENDING_SUSPENDED`'

    Design: Difficulty/boundary_precision_check/underwater_flag_strict_less_than_equality_is_not_underwater
    """
    ctx = setup_funded_world(corpus_cents=10_000_000, quarter1_ending_mv=10_000_000,
                             pool_name="Pool EQL")

    finalize_open_quarter(ctx["pool"]["id"], 9_999_900, reports=[{
        "manager_id": ctx["manager"]["id"], "beginning_mv_cents": 10_000_000,
        "ending_mv_cents": 9_999_900,
    }])

    fund = get_success_data(api.get_fund(ctx["fund"]["id"], TEST_USERS["io_headers"]))
    assert fund["market_value_cents"] == 9_999_900
    assert fund["is_underwater"] is True
    assert fund["spending_posture"] == "SPENDING_SUSPENDED"


def test_exception_approval_cannot_exceed_requested_amount(api):
    """PRD §3.6: 'Approval (`ENDORSED` → `APPROVED`) is a `BoardMember` action
    carrying `approved_amount_cents`, which must be strictly greater than 0 and no
    greater than `requested_amount_cents` — an excess is rejected with
    `ERR_EXCEPTION_AMOUNT_EXCEEDS_REQUESTED`.'

    Design: Corner/validations/exception_approval_cannot_exceed_requested_amount
    """
    ctx = setup_underwater_world(pool_name="Pool XA")
    exception = request_exception(ctx["fund"]["id"], 2026, 300_000)
    endorse_exception(exception["id"])

    res = api.approve_exception(
        exception["id"], {"approved_amount_cents": 300_001},
        make_board_member_headers("bm-1"),
    )
    validate_error(res, ApiErrorId.ERR_EXCEPTION_AMOUNT_EXCEEDS_REQUESTED, 422)

    approved = validate_success(api.approve_exception(
        exception["id"], {"approved_amount_cents": 300_000},
        make_board_member_headers("bm-1"),
    ), 200)
    assert approved["exception_status"] == "APPROVED"
    assert approved["approved_amount_cents"] == 300_000


def test_segregation_of_duties_exception_endorser_must_differ_from_requester(api):
    """PRD §2.1: 'endorsing an exception requires the endorser to differ from its
    `requested_by_user_id`'
    PRD §2.1: 'Any breach of these rules is rejected with
    `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403).'

    Design: Corner/rbac/segregation_of_duties_exception_endorser_must_differ_from_requester
    """
    ctx = setup_underwater_world(pool_name="Pool ES")
    exception = request_exception(ctx["fund"]["id"], 2026, 300_000,
                                  requester_user_id="dev-1")

    res = api.endorse_exception(
        exception["id"], make_investment_officer_headers("dev-1"),
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION, 403)

    endorsed = validate_success(api.endorse_exception(
        exception["id"], make_investment_officer_headers("io-2"),
    ), 200)
    assert endorsed["exception_status"] == "ENDORSED"
    assert endorsed["endorsed_by_user_id"] == "io-2"


def test_term_endowment_maturity_lifts_underwater_suspension_at_exact_quarter(api):
    """PRD §3.5: 'A fund is exempt from the gate when its `endowment_class` is
    `QUASI_ENDOWMENT`, or when it is a `TERM_ENDOWMENT` whose
    `term_end_quarter_index` has been reached — that is, the pool's
    `current_quarter_index` is at least `term_end_quarter_index`.'
    PRD §3.4: 'funds no longer underwater — or newly exempt by term maturity — move
    from `SPENDING_SUSPENDED` back to `NORMAL`.'

    Design: Corner/cross_cutting_complexity_layers/term_endowment_maturity_lifts_underwater_suspension_at_exact_quarter
    """
    ctx = setup_funded_world(corpus_cents=5_000_000, quarter1_ending_mv=5_000_000,
                             endowment_class="TERM_ENDOWMENT", term_end_quarter_index=3,
                             pool_name="Pool TM2")

    # Q2 (quarter 2 < term_end 3): crash -> underwater and suspended.
    finalize_open_quarter(ctx["pool"]["id"], 2_500_000, reports=[{
        "manager_id": ctx["manager"]["id"], "beginning_mv_cents": 5_000_000,
        "ending_mv_cents": 2_500_000,
    }])
    fund_q2 = get_success_data(api.get_fund(ctx["fund"]["id"], TEST_USERS["io_headers"]))
    assert fund_q2["is_underwater"] is True
    assert fund_q2["spending_posture"] == "SPENDING_SUSPENDED"

    # Q3 (quarter 3 >= term_end 3): maturity exempts the fund at the boundary.
    finalize_open_quarter(ctx["pool"]["id"], 2_500_000, reports=[{
        "manager_id": ctx["manager"]["id"], "beginning_mv_cents": 2_500_000,
        "ending_mv_cents": 2_500_000,
    }])
    fund_q3 = get_success_data(api.get_fund(ctx["fund"]["id"], TEST_USERS["io_headers"]))
    assert fund_q3["market_value_cents"] == 2_500_000
    assert fund_q3["is_underwater"] is True, "price flat — still below historic gift value"
    assert fund_q3["spending_posture"] == "NORMAL"
