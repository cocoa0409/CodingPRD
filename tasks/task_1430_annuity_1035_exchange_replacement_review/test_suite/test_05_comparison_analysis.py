"""The comparison analysis: dual surrender-charge variants, pinned rounding
and evaluation order, benefit-loss cap, break-even projection, supersession,
and the OCC guard (PRD §2.7, §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_analysis,
    assert_basis_conservation,
    create_analysis,
    get_case,
    make_reviewer_headers,
    open_case,
    register_client,
    register_contract,
    register_producer,
    setup_case_in_review,
    start_review,
    submit_case,
    validate_error,
    validate_paginated,
    validate_success,
)

# Canonical contract: issued 2021-09-01, value 10,000,000, basis 8,000,000,
# schedule 700..100 bps years 1..7, rider base 12,000,000 at 95 bps.
# At the 2026-08-01 default clock: 4 completed years -> year 5 -> 300 bps.
# At settlement (+45d = 2026-09-15): the 2026-09-01 anniversary has passed
# -> 5 completed years -> year 6 -> 200 bps.


def test_surrender_charge_today_variant_reads_current_band(api):
    """PRD §3.4: "The chronological variant reads the percentage as of the
    `analysis_date` itself, yielding `surrender_pct_bps_today`, and
    `surrender_charge_today_cents` is the `exchange_base_cents` multiplied by
    that percentage and divided by 10,000, rounded down."
    PRD §3.4: "the number of completed contract years at a given as-of date is
    the largest count of whole anniversaries of `issue_date` that fall on or
    before that date — the exact anniversary day itself counts as completed —
    and the applicable schedule year is that count plus one."

    Design: Difficulty/dual_variant_calc/surrender_charge_today_vs_settlement
    """
    bundle = setup_case_in_review()
    analysis = create_analysis(bundle["case_id"], bundle["case_version"])
    assert_analysis(analysis)
    # 2021-09-01 issue at 2026-08-01: 4 completed anniversaries -> year 5.
    assert analysis["surrender_pct_bps_today"] == 300
    assert analysis["surrender_charge_today_cents"] == 300000


def test_surrender_charge_settlement_variant_crosses_anniversary(api):
    """PRD §3.4: "The forward-looking variant projects to the estimated carrier
    settlement date, 45 days after the `analysis_date`, yielding
    `surrender_pct_bps_at_settlement` and `surrender_charge_at_settlement_cents`
    by the same multiplication and single rounding-down division; an
    anniversary falling inside the 45-day settlement lag drops the charge into
    the next, lower schedule band, so the at-settlement charge is smaller than
    the today's charge whenever an anniversary intervenes."

    Design: Difficulty/dual_variant_calc/surrender_charge_today_vs_settlement
    """
    bundle = setup_case_in_review()
    analysis = create_analysis(bundle["case_id"], bundle["case_version"])
    # 2026-08-01 + 45d = 2026-09-15: the 2026-09-01 anniversary intervenes.
    assert analysis["surrender_pct_bps_at_settlement"] == 200
    assert analysis["surrender_charge_at_settlement_cents"] == 200000
    assert (
        analysis["surrender_charge_at_settlement_cents"]
        < analysis["surrender_charge_today_cents"]
    ), "identical contract data must price the two variants differently here"


def test_partial_basis_allocation_multiplies_before_dividing(api):
    """PRD §3.4: "For a `PARTIAL` exchange, `basis_transferred_cents` is the
    `tax_basis_cents` multiplied by `exchange_amount_cents` and then divided by
    `account_value_cents`, rounded down — the integer multiplication happens
    first and the division happens exactly once; the ratio itself must never be
    rounded to a decimal before multiplying, because the orders genuinely
    differ (8,000,000 cents of basis on a 3,333,333-cent partial out of a
    10,000,000-cent contract yields 2,666,666 cents transferred by
    multiply-then-divide, but 2,666,400 cents if the ratio is first rounded to
    0.3333)."

    Design: Difficulty/combinatorial_formula/partial_basis_allocation_rounding_order
    """
    bundle = setup_case_in_review(
        case_overrides={"exchange_type": "PARTIAL", "exchange_amount_cents": 3333333}
    )
    analysis = create_analysis(bundle["case_id"], bundle["case_version"])
    assert analysis["basis_transferred_cents"] == 2666666, (
        "pinned multiply-then-divide order, never ratio-first rounding"
    )
    assert analysis["basis_remaining_cents"] == 5333334
    assert_basis_conservation(
        analysis["basis_transferred_cents"],
        analysis["basis_remaining_cents"],
        8000000,
    )


def test_partial_exchange_base_and_charge_fields(api):
    """PRD §3.4: "The gross base to which the surrender charge applies,
    `exchange_base_cents`, is the contract's `account_value_cents` for a `FULL`
    exchange and the case's `exchange_amount_cents` for a `PARTIAL` one."
    PRD §3.4: "The forward-looking variant projects to the estimated carrier
    settlement date, 45 days after the `analysis_date`, yielding
    `surrender_pct_bps_at_settlement` and `surrender_charge_at_settlement_cents`
    by the same multiplication and single rounding-down division"

    Design: Difficulty/combinatorial_formula/partial_basis_allocation_rounding_order
    """
    bundle = setup_case_in_review(
        case_overrides={"exchange_type": "PARTIAL", "exchange_amount_cents": 3333333}
    )
    analysis = create_analysis(bundle["case_id"], bundle["case_version"])
    assert analysis["exchange_base_cents"] == 3333333
    # floor(3333333 * 300 / 10000) and floor(3333333 * 200 / 10000).
    assert analysis["surrender_charge_today_cents"] == 99999
    assert analysis["surrender_charge_at_settlement_cents"] == 66666


def test_bonus_credit_computed_on_net_amount_received(api):
    """PRD §3.4: "From those, `amount_received_cents` is the
    `exchange_base_cents` minus the at-settlement charge. The
    `bonus_credit_cents` is the `amount_received_cents` multiplied by
    `new_product_bonus_bps` and divided by 10,000, rounded down — the bonus is
    computed on the net amount received, never on the gross base."

    Design: Difficulty/combinatorial_formula/net_replacement_cost_pinned_order
    """
    bundle = setup_case_in_review()
    analysis = create_analysis(bundle["case_id"], bundle["case_version"])
    assert analysis["amount_received_cents"] == 9800000  # 10,000,000 - 200,000
    # floor(9,800,000 * 100 / 10000); the gross base would wrongly give 100,000.
    assert analysis["bonus_credit_cents"] == 98000


def test_net_replacement_cost_pinned_evaluation_order(api):
    """PRD §3.4: "The `net_replacement_cost_cents` is then pinned to this exact
    evaluation order: the at-settlement surrender charge, plus the benefit
    loss, minus the bonus credit."
    PRD §3.4: "The `benefit_loss_cents` is zero when the contract has no
    living-benefit rider; otherwise it is the amount by which
    `rider_benefit_base_cents` exceeds `account_value_cents`, floored at zero
    and capped at 2,000,000 cents."
    PRD §3.4: "The first year from 1 through 30 in which the new balance is
    greater than or equal to the old balance is the result; if the replacement
    never catches up inside the 30-year horizon, the analysis records 99."

    Design: Difficulty/combinatorial_formula/net_replacement_cost_pinned_order
    """
    bundle = setup_case_in_review()
    analysis = create_analysis(bundle["case_id"], bundle["case_version"])
    # rider base 12,000,000 - value 10,000,000 = 2,000,000 (exactly the cap).
    assert analysis["benefit_loss_cents"] == 2000000
    # 200,000 (at-settlement charge) + 2,000,000 - 98,000.
    assert analysis["net_replacement_cost_cents"] == 2102000
    # Net rates 405 bps old vs 485 bps new with floored annual compounding:
    # year 1 new 10,378,053 < old 10,405,000; year 2 new 10,881,388 >= old
    # 10,826,402.
    assert analysis["break_even_years"] == 2


def test_benefit_loss_capped_at_rider_loss_cap(api):
    """PRD §3.4: "The `benefit_loss_cents` is zero when the contract has no
    living-benefit rider; otherwise it is the amount by which
    `rider_benefit_base_cents` exceeds `account_value_cents`, floored at zero
    and capped at 2,000,000 cents."
    With a 35,000,000-cent benefit base the raw excess is 25,000,000 cents, so
    the cap — not the raw difference — is the recorded loss.

    Design: Difficulty/combinatorial_formula/benefit_loss_cap_branch
    """
    bundle = setup_case_in_review(
        contract_overrides={"rider_benefit_base_cents": 35000000}
    )
    analysis = create_analysis(bundle["case_id"], bundle["case_version"])
    assert analysis["benefit_loss_cents"] == 2000000, (
        "the 2,000,000-cent cap binds over the raw 25,000,000-cent excess"
    )


def test_net_cost_reflects_capped_benefit_loss(api):
    """PRD §3.4: "The `net_replacement_cost_cents` is then pinned to this exact
    evaluation order: the at-settlement surrender charge, plus the benefit
    loss, minus the bonus credit."
    PRD §3.4: "The `benefit_loss_cents` is zero when the contract has no
    living-benefit rider; otherwise it is the amount by which
    `rider_benefit_base_cents` exceeds `account_value_cents`, floored at zero
    and capped at 2,000,000 cents."

    Design: Difficulty/combinatorial_formula/benefit_loss_cap_branch
    """
    bundle = setup_case_in_review(
        contract_overrides={"rider_benefit_base_cents": 35000000}
    )
    analysis = create_analysis(bundle["case_id"], bundle["case_version"])
    # 200,000 (at-settlement charge) + 2,000,000 (capped loss) - 98,000 (bonus).
    assert analysis["net_replacement_cost_cents"] == 2102000


def test_surrender_charge_counts_anniversary_day_as_completed(api):
    """PRD §3.4: "the number of completed contract years at a given as-of date
    is the largest count of whole anniversaries of `issue_date` that fall on or
    before that date — the exact anniversary day itself counts as completed —
    and the applicable schedule year is that count plus one."

    Design: Corner/calculations/surrender_charge_anniversary_boundary
    """
    bundle = setup_case_in_review(
        contract_overrides={
            "issue_date": "2021-08-01",  # 5th anniversary is the clock date
            "living_benefit_rider": False,
        },
        case_overrides={"new_product_bonus_bps": 0, "new_product_annual_fee_bps": 0},
    )
    analysis = create_analysis(bundle["case_id"], bundle["case_version"])
    # Exactly 5 years completed at 2026-08-01 -> year 6 -> 200 bps.
    assert analysis["surrender_pct_bps_today"] == 200
    assert analysis["surrender_charge_today_cents"] == 200000


def test_surrender_charge_zero_beyond_schedule_length(api):
    """PRD §3.4: "The schedule entry whose `contract_year` equals that year
    supplies the percentage; when the year runs past the end of the schedule,
    the percentage is zero."

    Design: Corner/calculations/surrender_charge_zero_beyond_schedule
    """
    bundle = setup_case_in_review(
        contract_overrides={
            "issue_date": "2018-08-01",  # 8 years completed; schedule has 7
            "living_benefit_rider": False,
        },
        case_overrides={"new_product_bonus_bps": 0, "new_product_annual_fee_bps": 0},
    )
    analysis = create_analysis(bundle["case_id"], bundle["case_version"])
    assert analysis["surrender_pct_bps_today"] == 0
    assert analysis["surrender_charge_today_cents"] == 0
    assert analysis["surrender_pct_bps_at_settlement"] == 0
    assert analysis["surrender_charge_at_settlement_cents"] == 0


def test_break_even_sentinel_when_never_catches_up(api):
    """PRD §3.4: "The first year from 1 through 30 in which the new balance is
    greater than or equal to the old balance is the result; if the replacement
    never catches up inside the 30-year horizon, the analysis records 99."
    Here the replacement's net rate is 100 - 115 = -15 bps against the old
    contract's 500 - 95 = 405 bps, and it also starts 102,000 cents behind.

    Design: Corner/calculations/break_even_never_sentinel
    """
    bundle = setup_case_in_review()
    analysis = create_analysis(
        bundle["case_id"],
        bundle["case_version"],
        assumed_new_growth_bps=100,
    )
    assert analysis["break_even_years"] == 99


def test_second_analysis_supersedes_first(api):
    """PRD §3.4: "Creating an analysis on a case that already has one flips the
    prior `FINAL` analysis to `SUPERSEDED`, points the new analysis's
    `supersedes_analysis_id` at it (null for the first), and increments the
    parent case's `version` by one."
    PRD §3.4: "A case's analyses, both `FINAL` and `SUPERSEDED`, are listable
    with an optional `status` filter."

    Design: Corner/endpoints/analysis_supersede_on_second_create
    """
    bundle = setup_case_in_review()
    case_id = bundle["case_id"]
    v1 = bundle["case_version"]

    first = create_analysis(case_id, v1)
    assert first["status"] == "FINAL"
    assert first.get("supersedes_analysis_id") is None
    assert get_case(case_id)["version"] == v1 + 1

    second = create_analysis(
        case_id, v1 + 1, assumed_old_growth_bps=450, assumed_new_growth_bps=650
    )
    assert second["status"] == "FINAL"
    assert second["supersedes_analysis_id"] == first["id"]
    assert get_case(case_id)["version"] == v1 + 2

    analyses, meta = validate_paginated(
        api.list_comparison_analyses(case_id, make_reviewer_headers("rev-1"))
    )
    assert meta["total_count"] == 2
    by_id = {a["id"]: a for a in analyses}
    assert by_id[first["id"]]["status"] == "SUPERSEDED"
    assert by_id[second["id"]]["status"] == "FINAL"

    finals, meta_f = validate_paginated(
        api.list_comparison_analyses(
            case_id, make_reviewer_headers("rev-1"), params={"status": "FINAL"}
        )
    )
    assert meta_f["total_count"] == 1
    assert finals[0]["id"] == second["id"]


def test_stale_case_version_rejected_then_fresh_succeeds(api):
    """PRD §2.7: "That request must carry `expected_case_version`, a
    non-optional input field holding the case `version` the client last
    observed. If the value does not match the case's current `version` —
    because another writer has since created an analysis (which itself
    supersedes the prior final analysis) or otherwise mutated the case — the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the
    client from acting on a stale view of the case."

    Design: Corner/cross_cutting_layers/occ_stale_version_rejected
    """
    bundle = setup_case_in_review()
    case_id = bundle["case_id"]
    current = bundle["case_version"]

    stale = api.create_comparison_analysis(
        case_id,
        {
            "expected_case_version": current - 1,
            "assumed_old_growth_bps": 500,
            "assumed_new_growth_bps": 600,
        },
        make_reviewer_headers("rev-1"),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    analyses, meta = validate_paginated(
        api.list_comparison_analyses(case_id, make_reviewer_headers("rev-1"))
    )
    assert meta["total_count"] == 0, "the stale attempt must not create a row"

    fresh = create_analysis(case_id, current)
    assert fresh["status"] == "FINAL"
    assert get_case(case_id)["version"] == current + 1, (
        "a successful analysis creation increments the case version by one"
    )
