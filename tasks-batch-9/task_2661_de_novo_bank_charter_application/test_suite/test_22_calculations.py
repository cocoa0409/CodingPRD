"""
Derived arithmetic: subscores and composites, the vendor diligence floor, the
deviation magnitude, the escrow position and the supervision clock.

The canonical board's persisted integer subscores are 68, 76, 54, 97 and 64, so
four seats average 73.75 and five average 71.80.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import (
    CHARTERING_EXAMINER_HEADERS,
    COUNSEL_HEADERS,
    ESCROW_AGENT_HEADERS,
    fixtures as fx,
    make_lead_organizer_headers,
)
from test_helpers.assertions import (
    assert_fields_equal,
    assert_two_decimal_places,
    assert_waterfall_reconciles,
)
from test_helpers.factories import (
    background_result_payload,
    deviation_request_payload,
    organizer_payload,
    screening_payload,
    stress_scenario_payload,
    vendor_advance_payload,
)
from test_helpers.types import (
    CLEARANCE_CLEARED,
    COMPOSITION_FORMING,
    COMPOSITION_MET,
    CREDIT_CLEARED,
    CRITICALITY_CRITICAL,
    DEVIATION_AUTO_ACCEPTED,
    DEVIATION_SUBMITTED,
    DIMENSION_CREDIT,
    DIMENSION_FINGERPRINT,
    FINGERPRINT_CLEARED,
    METRIC_ASSET_GROWTH,
    METRIC_DEPOSIT_GROWTH,
    QUALIFICATION_PENDING,
    QUALIFICATION_QUALIFIED,
    ROLE_ON_BOARD_INVESTOR_ONLY,
    SCENARIO_BASELINE,
    SERVICE_CORE_PROCESSING,
    SERVICE_DIGITAL_BANKING,
    STAGE_OPEN,
    VARIANT_STATIC,
    VENDOR_EVALUATING,
    VENDOR_SELECTED,
)


# ---------------------------------------------------------------------------
# Corner / calculations
# ---------------------------------------------------------------------------
def test_the_fifth_seat_meets_the_composition_test_and_then_earns_its_integrity_points(
    api, four_seat_group
):
    """
    Four cleared seats average 73.75 and are still short of a board. The fifth arrives with
    both background dimensions pending, so it contributes 39 rather than 64 — the integrity
    quarter is withheld until the fingerprint clears — and drags the average down to 66.80
    even though the composition test is already satisfied, because composition reads every
    row regardless of standing. Clearing the fingerprint restores the missing 25 points and
    lifts the average to 71.80; clearing the credit dimension only settles the standing and
    moves the average not at all.

    PRD: "The integrity component contributes a weighted twenty-five percent of one hundred — that is, twenty-five points — when and only when `fingerprint_state` is `CLEARED`, and contributes nothing otherwise."
    PRD: "Note carefully what does *not* enter this figure: `credit_state` has no effect on `qualification_subscore` at all, and reaches the organizer's standing only through the status ladder below."
    PRD: "If `organizer_count` is below five, the status is `FORMING`."
    PRD: "Qualification standing does not filter this population: a `DISQUALIFIED` or `PENDING` organizer with a board role still drags the average down, which is why a group can hold a `COMPOSITION_DEFICIENT` verdict and a low score simultaneously and must fix both."

    Design: Corner/calculations/calc_composition_flips_to_met_on_the_fifth_organizer
    """
    world = four_seat_group
    before = fx.read_group(api, world["group_id"])
    assert_fields_equal(
        before, composition_status=COMPOSITION_FORMING, organizer_count=4
    )
    assert_two_decimal_places(
        before["management_composite_score"], 73.75, "management_composite_score"
    )

    fifth = fx.CANONICAL_ORGANIZERS[4]
    o5 = get_success_data(
        api.create_organizer(
            world["group_id"],
            organizer_payload(
                full_name=fifth["full_name"],
                role_on_board=fifth["role_on_board"],
                is_independent=fifth["is_independent"],
                affiliation_code=fifth["affiliation_code"],
                banking_years=fifth["banking_years"],
                regulatory_experience_score=fifth["regulatory_experience_score"],
            ),
            COUNSEL_HEADERS,
        ),
        expected_status=201,
    )
    assert_fields_equal(
        o5, qualification_subscore=39, qualification_status=QUALIFICATION_PENDING
    )
    seated = fx.read_group(api, world["group_id"])
    assert_fields_equal(
        seated,
        organizer_count=5,
        independent_organizer_count=3,
        max_affiliation_count=2,
        composition_status=COMPOSITION_MET,
    )
    assert_two_decimal_places(
        seated["management_composite_score"], 66.80, "management_composite_score"
    )

    fingerprinted = get_success_data(
        api.record_background_result(
            o5["id"],
            background_result_payload(dimension=DIMENSION_FINGERPRINT, outcome=FINGERPRINT_CLEARED),
            CHARTERING_EXAMINER_HEADERS,
        )
    )
    assert_fields_equal(fingerprinted, qualification_subscore=64)
    assert_two_decimal_places(
        fx.read_group(api, world["group_id"])["management_composite_score"],
        71.80,
        "management_composite_score",
    )

    credited = get_success_data(
        api.record_background_result(
            o5["id"],
            background_result_payload(dimension=DIMENSION_CREDIT, outcome=CREDIT_CLEARED),
            CHARTERING_EXAMINER_HEADERS,
        )
    )
    assert_fields_equal(
        credited, qualification_subscore=64, qualification_status=QUALIFICATION_QUALIFIED
    )
    assert_two_decimal_places(
        fx.read_group(api, world["group_id"])["management_composite_score"],
        71.80,
        "management_composite_score",
    )


def test_a_passive_investor_is_counted_by_the_board_but_not_by_the_composite(
    api, composition_met_group
):
    """
    A sixth seat holding no board role has its own subscore computed and persisted like
    anyone else's, but it is outside the eligible population for the management average, so
    the composite stays at 71.80 while the head count rises to six. The two derivations read
    different input sets from the same six rows.

    PRD: "The eligible population is every organizer of the group whose `role_on_board` is anything other than `INVESTOR_ONLY`, taken in ascending `created_at` order; investors who hold no board seat never affect management quality."
    PRD: "`organizer_count` is the number of organizer rows with that group's id."

    Design: Corner/calculations/calc_composite_score_excludes_investor_only_organizer
    """
    world = composition_met_group

    investor = get_success_data(
        api.create_organizer(
            world["group_id"],
            organizer_payload(
                full_name="Roland Achebe",
                role_on_board=ROLE_ON_BOARD_INVESTOR_ONLY,
                is_independent=False,
                affiliation_code="INV_D",
                banking_years=2,
                regulatory_experience_score=40,
            ),
            COUNSEL_HEADERS,
        ),
        expected_status=201,
    )
    assert_fields_equal(
        investor, qualification_subscore=18, qualification_status=QUALIFICATION_PENDING
    )

    group = fx.read_group(api, world["group_id"])
    assert_fields_equal(
        group,
        organizer_count=6,
        independent_organizer_count=3,
        max_affiliation_count=2,
        composition_status=COMPOSITION_MET,
    )
    assert_two_decimal_places(
        group["management_composite_score"], 71.80, "management_composite_score"
    )


def test_the_diligence_floor_of_seventy_bites_at_sixty_nine_and_clears_at_seventy(api):
    """
    The floor is a constant, not a proportion: a critical contract rated 69 cannot be
    selected and stays under evaluation, while an otherwise identical critical contract in a
    different service domain rated 70 is selected on the spot. One point of diligence is the
    whole difference.

    PRD: "`SELECTED` is reachable only from `EVALUATING`, and carries two extra gates: no other contract of the same group and the same `service_domain` may already be `SELECTED` or `SIGNED` — a second core provider is refused with `ERR_VENDOR_DOMAIN_ALREADY_SELECTED` — and a contract whose `criticality` is `CRITICAL` must have a `due_diligence_score` of at least 70, with a score of 69 on a critical vendor refused by `ERR_DUE_DILIGENCE_INSUFFICIENT` while the same score on a `SIGNIFICANT` or `ROUTINE` vendor passes untouched."

    Design: Corner/calculations/calc_critical_vendor_due_diligence_floor_of_seventy_applied
    """
    world = fx.open_group(api)
    below = fx.add_vendor_contract(
        api,
        world,
        service_domain=SERVICE_CORE_PROCESSING,
        criticality=CRITICALITY_CRITICAL,
        due_diligence_score=69,
    )
    at_floor = fx.add_vendor_contract(
        api,
        world,
        service_domain=SERVICE_DIGITAL_BANKING,
        vendor_name="Northlight Digital",
        criticality=CRITICALITY_CRITICAL,
        due_diligence_score=70,
    )

    validate_error(
        api.advance_vendor_contract(
            below, vendor_advance_payload(VENDOR_SELECTED), COUNSEL_HEADERS
        ),
        "ERR_DUE_DILIGENCE_INSUFFICIENT",
        expected_status=409,
    )
    assert_fields_equal(fx.read_contract(api, below), status=VENDOR_EVALUATING)

    selected = validate_success(
        api.advance_vendor_contract(
            at_floor, vendor_advance_payload(VENDOR_SELECTED), COUNSEL_HEADERS
        ),
        expected_status=200,
    )
    assert_fields_equal(
        selected, status=VENDOR_SELECTED, due_diligence_score=70
    )


def test_a_ten_percent_departure_needs_a_regulator_and_nine_point_nine_nine_does_not(api):
    """
    Both reports are filed in supervision year one, so both read the year-one figure of their
    own metric family. Assets running 2,500,000,000 cents over a 25,000,000,000 cent plan is
    exactly 1000 basis points and lands on the threshold, so that report waits for a
    supervisor. Deposits running 2,097,900,000 over 21,000,000,000 floor to 999 basis points
    and the report clears itself in the same breath as its creation.

    PRD: "For `ASSET_GROWTH` the baseline is the plan's projected assets for that year; for `LOAN_GROWTH`, its projected loans for that year; for `DEPOSIT_GROWTH`, its projected deposits for that year."
    PRD: "When the baseline is non-zero, take the absolute difference between `actual_value` and the baseline, multiply by 10000, divide by the absolute value of the baseline, and floor the result to a whole number of basis points."
    PRD: "A deviation of exactly 1000 basis points therefore requires approval, while 999 does not."
    PRD: "When `requires_regulator_approval` is false the request self-clears: its `status` is `AUTO_ACCEPTED` immediately, `decision_note` stays null, and no examiner ever sees it."

    Design: Corner/calculations/calc_deviation_threshold_at_exactly_one_thousand_bps_requires_approval
    """
    world = fx.opened_bank(api)
    lead_headers = make_lead_organizer_headers(world["o1"])

    on_threshold = get_success_data(
        api.create_deviation_request(
            deviation_request_payload(
                world["group_id"],
                world["plan_id"],
                27_500_000_000,
                metric=METRIC_ASSET_GROWTH,
            ),
            lead_headers,
        ),
        expected_status=201,
    )
    assert_fields_equal(
        on_threshold,
        supervision_year_index_at_request=1,
        baseline_value=25_000_000_000,
        deviation_bps=1000,
        requires_regulator_approval=True,
        status=DEVIATION_SUBMITTED,
    )

    below_threshold = get_success_data(
        api.create_deviation_request(
            deviation_request_payload(
                world["group_id"],
                world["plan_id"],
                23_097_900_000,
                metric=METRIC_DEPOSIT_GROWTH,
            ),
            lead_headers,
        ),
        expected_status=201,
    )
    assert_fields_equal(
        below_threshold,
        baseline_value=21_000_000_000,
        deviation_bps=999,
        requires_regulator_approval=False,
        status=DEVIATION_AUTO_ACCEPTED,
        decision_note=None,
    )


def test_only_rows_that_are_both_funded_and_cleared_sit_inside_escrow(api):
    """
    Three subscriptions, each satisfying a different pair of the two dimensions. Money in
    escrow counts only the row that is funded and cleared at once, so a funded but unscreened
    row and a cleared but unfunded row are both outside it. Screening the funded row clear
    pulls its 500,000,000 cents in, taking escrow to 1,500,000,000 while the pledged total
    stays at 1,750,000,000 — and the cleared-but-unfunded row still does not count. On the
    new gross figure the five percent cap is 75,000,000, which trims the 150,000,000 cent
    expense claim by half.

    PRD: "The two dimensions advance in either order and impose no ordering on each other; `counts_toward_escrow` is true for exactly those rows where `funding_state` is `FUNDED` **and** `clearance_state` is `CLEARED`."
    PRD: "The **cleared basis** is `cleared_escrow_cents`, the sum of `amount_cents` over exactly those rows whose `counts_toward_escrow` is true."
    PRD: "Bucket one is the organizational-expense reimbursement, capped at five percent of that **gross** figure: five percent of gross cleared escrow is rounded half up to whole cents to form the cap, and `projected_reimbursement_cents` is the smaller of `organizational_expense_claim_cents` and that cap."

    Design: Corner/calculations/calc_escrow_position_sums_only_funded_and_cleared_rows
    """
    world = fx.bare_open_raise(api)
    s1 = fx.add_subscription(api, world["raise_id"], "Harbor Trust LP", 1_000_000)
    s2 = fx.add_subscription(api, world["raise_id"], "Puget Founders Fund", 500_000)
    s3 = fx.add_subscription(api, world["raise_id"], "Olympic Coast Holdings", 250_000)
    fx.fund(api, s1)
    fx.screen(api, s1, CLEARANCE_CLEARED)
    fx.fund(api, s2)
    fx.screen(api, s3, CLEARANCE_CLEARED)

    assert_fields_equal(
        fx.read_raise(api, world["raise_id"]), cleared_escrow_cents=1_000_000_000
    )

    cleared = validate_success(
        api.record_screening_result(
            s2, screening_payload(CLEARANCE_CLEARED), ESCROW_AGENT_HEADERS
        ),
        expected_status=200,
    )
    assert_fields_equal(
        cleared, clearance_state=CLEARANCE_CLEARED, counts_toward_escrow=True
    )
    assert_fields_equal(fx.read_subscription(api, s3), counts_toward_escrow=False)

    raise_row = fx.read_raise(api, world["raise_id"])
    assert_fields_equal(
        raise_row,
        cleared_escrow_cents=1_500_000_000,
        funded_gross_cents=1_500_000_000,
        pledged_gross_cents=1_750_000_000,
        refunded_gross_cents=0,
        subscribed_shares=1_750_000,
        projected_reimbursement_cents=75_000_000,
        projected_net_release_cents=1_425_000_000,
    )
    assert_waterfall_reconciles(raise_row)


def test_the_supervision_year_rolls_on_day_365_and_lapses_on_day_1095(api):
    """
    Supervision is measured in whole elapsed days from the instant the bank opened, not by
    calendar year. Day 364 is still the first year; day 365 is the first day of the second.
    Day 1095 is the first day outside the window entirely, and the index falls back to zero
    without the bank ceasing to be open and without the start instant moving — it is the
    start instant that tells a zero index apart from a project that has not opened.

    PRD: "Once it is set, the elapsed time from `supervision_started_at` to the current logical clock is taken in whole seconds and divided by 86400 with the remainder discarded, giving whole elapsed days; that day count is divided by 365 with the remainder discarded and one is added, giving the raw supervision year."
    PRD: "If the raw year is 1, 2 or 3 the index takes that value; if it is 4 or more the group has graduated and `supervision_year_index` becomes 0 again."
    PRD: "The boundaries are therefore exact: elapsed day 0 through day 364 is year 1, day 365 is the first day of year 2, day 730 is the first day of year 3, and day 1095 is the first day outside the supervision window, at which point the index returns to 0."

    Design: Corner/calculations/calc_supervision_year_index_rolls_at_day_365_and_expires_at_day_1095
    """
    world = fx.opened_bank(api)
    opening = fx.read_group(api, world["group_id"])
    assert_fields_equal(opening, stage=STAGE_OPEN, supervision_year_index=1)
    assert opening["supervision_started_at"].startswith("2026-10-05T09:00:00"), (
        f"supervision must start at the opening instant: "
        f"{opening['supervision_started_at']!r}"
    )

    for instant, expected_index in (
        ("2027-10-04T09:00:00Z", 1),
        ("2027-10-05T09:00:00Z", 2),
        ("2029-10-04T09:00:00Z", 0),
    ):
        fx.set_clock(api, instant)
        group = fx.read_group(api, world["group_id"])
        assert group["supervision_year_index"] == expected_index, (
            f"at {instant} the supervision year index must be {expected_index}, "
            f"got {group['supervision_year_index']}"
        )
        assert_fields_equal(group, stage=STAGE_OPEN)
        assert group["supervision_started_at"].startswith("2026-10-05T09:00:00"), (
            "the start instant never moves as the clock advances"
        )


def test_a_baseline_overlay_is_judged_on_the_frozen_balance_sheet(api):
    """
    With no credit loss, no margin compression and no overrun, a baseline overlay is the
    plan's own income story run twice. Frozen at the year-one balance sheet the ratio bottoms
    out at 1500 basis points in the loss year, while following the plan's growth it sinks to
    1006 by year three as the denominator grows faster than capital. The scenario code alone
    picks the frozen path to govern, so the plan rolls up 1500 and no year breaches.

    PRD: "Under the `STATIC_BALANCE_SHEET` variant, the assets figure is `projected_assets_y1_cents` and the loans figure is `projected_loans_y1_cents` for all three years, so the balance sheet is frozen at the year-one projection, losses do not scale with growth, and the ratio denominator never grows."
    PRD: "Which run **governs** is decided purely by the scenario code: `governing_variant` is `STATIC_BALANCE_SHEET` when `scenario_code` is `BASELINE`, and `DYNAMIC_GROWTH` when `scenario_code` is `ADVERSE` or `SEVERELY_ADVERSE`."
    PRD: "Attaching a scenario then re-derives three aggregates on the parent plan: `stress_scenario_count` is the number of scenarios attached to that plan; `breach_scenario_count` is the number of those scenarios whose `governing_breach_year_index` is anything other than 0; and `worst_governing_min_leverage_ratio_bps` is the smallest `governing_min_leverage_ratio_bps` across that plan's scenarios, or 0 when the plan has no scenario at all."

    Design: Corner/calculations/calc_baseline_scenario_is_governed_by_the_static_variant
    """
    world = fx.open_group(api)
    plan_id = fx.add_business_plan(api, world)

    scenario = get_success_data(
        api.create_stress_scenario(
            plan_id,
            stress_scenario_payload(
                SCENARIO_BASELINE,
                credit_loss_rate_bps=0,
                nim_compression_bps=0,
                expense_overrun_cents=0,
            ),
            COUNSEL_HEADERS,
        ),
        expected_status=201,
    )
    assert_fields_equal(
        scenario,
        static_min_leverage_ratio_bps=1500,
        static_breach_year_index=0,
        dynamic_min_leverage_ratio_bps=1006,
        dynamic_breach_year_index=0,
        governing_variant=VARIANT_STATIC,
        governing_min_leverage_ratio_bps=1500,
        governing_breach_year_index=0,
    )
    assert_fields_equal(
        fx.read_plan(api, plan_id),
        stress_scenario_count=1,
        breach_scenario_count=0,
        worst_governing_min_leverage_ratio_bps=1500,
    )
