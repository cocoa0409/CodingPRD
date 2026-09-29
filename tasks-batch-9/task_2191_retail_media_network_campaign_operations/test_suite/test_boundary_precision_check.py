"""Metrics sitting exactly on a stated threshold, against the value just past it.

Two thresholds are exercised. A study's significance score is compared inclusively
against 1.96, so exactly 1.9600 is significant and 1.9500 is not. A slot's overlap count
is compared strictly against the slot's concurrency limit, and the overlap test itself is
half-open, so a candidate that merely abuts an occupant overlaps nothing at all.
"""

from test_helpers import (
    CATALOG_OPS,
    ERR_SLOT_CAPACITY_EXCEEDED,
    ERR_STUDY_NOT_SIGNIFICANT,
    MEASUREMENT_ANALYST,
    NETWORK_ADMIN,
    SIGNIFICANCE_MIN,
    api_client,
    assert_occupancy_count,
    build_active_advertiser,
    build_active_budget_plan,
    build_catalog_product,
    build_draft_campaign,
    build_pending_eligibility_line_item,
    build_pending_review_campaign,
    build_placement_slot,
    hours_between,
    reread_campaign,
    reread_line_item,
    reread_slot,
    round_half_up,
    set_clock,
    validate_error,
    validate_success,
    whole_day_periods,
)

# --- The significance boundary ---------------------------------------------

# Both cohorts hold ten thousand shoppers, so the square-root factor in the
# significance score is exactly one hundred and a rate difference of 0.0196 lands the
# score exactly on the 1.96 floor.
GROUP_SIZE = 10000
EXPOSED_CONVERSIONS = 500
ON_BOUNDARY_CONTROL_CONVERSIONS = 304
BELOW_BOUNDARY_CONTROL_CONVERSIONS = 305
EXPOSED_SALES_CENTS = 5000000
CONTROL_SALES_CENTS = 1200000


def _two_study_world():
    """A scheduled campaign carrying two designed studies exactly one washout apart.

    The clock stands at 2026-08-22, past the close of both study windows, so both may be
    started and both may be measured without moving it again. The first window closes on
    2026-08-08 and the second opens on 2026-08-15, leaving exactly one hundred and
    sixty-eight hours of clear air between them.
    """
    world = build_active_advertiser()
    set_clock(world, "2026-08-22T00:00:00Z")
    build_active_budget_plan(
        world,
        committed_total_cents=1000000,
        trade_fund_share_cents=0,
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-11-01T00:00:00Z",
    )
    build_placement_slot(world, floor_cpc_cents=1000)
    build_catalog_product(world)
    build_draft_campaign(
        world,
        flight_start_at="2026-08-01T00:00:00Z",
        flight_end_at="2026-09-01T00:00:00Z",
        allocated_budget_cents=500000,
        daily_cap_cents=400000,
    )
    # One line item awaiting its eligibility decision satisfies the review-submission
    # precondition; the studies do not depend on it going any further.
    build_pending_eligibility_line_item(
        world,
        bid_cents=2000,
        daily_budget_cents=1000,
        flight_start_at="2026-08-02T00:00:00Z",
        flight_end_at="2026-08-30T00:00:00Z",
    )
    build_pending_review_campaign(world, with_line_item=False)
    world["campaign"] = validate_success(
        api_client.decide_campaign_review(
            world["campaign"]["id"],
            {"decision": "APPROVE", "decision_note": "scheduled"},
            NETWORK_ADMIN,
        )
    )

    for key, start, end in (
        ("first_study", "2026-08-01T00:00:00Z", "2026-08-08T00:00:00Z"),
        ("second_study", "2026-08-15T00:00:00Z", "2026-08-22T00:00:00Z"),
    ):
        campaign = reread_campaign(world)
        world[key] = validate_success(
            api_client.create_incrementality_study(
                {
                    "campaign_id": campaign["id"],
                    "design_method": "GEO_HOLDOUT",
                    "holdout_pct": 0.1,
                    "window_start_at": start,
                    "window_end_at": end,
                    "expected_campaign_version": campaign["version"],
                },
                MEASUREMENT_ANALYST,
            ),
            201,
        )
        world[key] = validate_success(
            api_client.start_incrementality_study(
                world[key]["id"],
                {
                    "exposed_group_size": GROUP_SIZE,
                    "control_group_size": GROUP_SIZE,
                },
                MEASUREMENT_ANALYST,
            )
        )
    return world


def test_significance_score_exactly_at_the_floor_is_significant_and_publishes():
    """A score of exactly 1.9600 clears the inclusive floor and the study publishes.

    PRD 3.7: "`significance_flag` is true when `significance_score` is at or above 1.96
    and false below it, so a score of exactly 1.9600 is significant."

    PRD 3.7: "Publication moves a `MEASURING` study to `PUBLISHED`, accepts an optional
    `publication_note`, and requires `significance_flag` to be true and no other study on
    the same campaign to be `PUBLISHED` with an overlapping window. It stamps
    `published_by_user_id` with the acting `X-User-ID`, writes the study's
    `incremental_sales_cents` onto the campaign's `incremental_revenue_cents` and
    recomputes `iroas`."

    Design: Difficulty/boundary_precision_check/bpc_significance_score_exactly_at_minimum_versus_one_ulp_below
    """
    world = _two_study_world()

    measured = validate_success(
        api_client.measure_incrementality_study(
            world["first_study"]["id"],
            {
                "exposed_conversions": EXPOSED_CONVERSIONS,
                "control_conversions": ON_BOUNDARY_CONTROL_CONVERSIONS,
                "exposed_sales_cents": EXPOSED_SALES_CENTS,
                "control_sales_cents": CONTROL_SALES_CENTS,
            },
            MEASUREMENT_ANALYST,
        )
    )

    exposed_rate = EXPOSED_CONVERSIONS / GROUP_SIZE
    control_rate = ON_BOUNDARY_CONTROL_CONVERSIONS / GROUP_SIZE
    expected_score = round_half_up(abs(exposed_rate - control_rate) * GROUP_SIZE**0.5, 4)
    assert expected_score == SIGNIFICANCE_MIN
    assert measured["significance_score"] == expected_score
    assert measured["significance_flag"] is True
    assert measured["lift_pct"] == round_half_up(exposed_rate / control_rate - 1.0, 4)
    assert measured["lift_pct"] == 0.6447
    assert measured["incremental_sales_cents"] == 1959932
    assert measured["study_status"] == "MEASURING"

    published = validate_success(
        api_client.publish_incrementality_study(
            world["first_study"]["id"],
            {"publication_note": "on-boundary significance"},
            MEASUREMENT_ANALYST,
        )
    )
    assert published["study_status"] == "PUBLISHED"

    # Publication writes the study's incremental figure onto the campaign.
    campaign = reread_campaign(world)
    assert campaign["incremental_revenue_cents"] == 1959932


def test_significance_score_below_the_floor_is_refused_publication():
    """A score of 1.9500 falls below the floor, so the study stays in MEASURING.

    PRD 3.7: "`significance_flag` is true when `significance_score` is at or above 1.96
    and false below it, so a score of exactly 1.9600 is significant."

    PRD 3.7: "requires `significance_flag` to be true"

    PRD 3.7: "A collision occurs when the gap is strictly less than one hundred and
    sixty-eight hours, which is the seven-day washout expressed in hours; a gap of
    exactly one hundred and sixty-eight hours passes."

    Design: Difficulty/boundary_precision_check/bpc_significance_score_exactly_at_minimum_versus_one_ulp_below
    """
    world = _two_study_world()

    # The second study exists at all only because the clear gap to the first is exactly
    # the washout period, which the washout rule admits.
    gap_hours = hours_between("2026-08-08T00:00:00Z", "2026-08-15T00:00:00Z")
    assert gap_hours == 168
    assert world["second_study"]["study_status"] == "RUNNING"

    measured = validate_success(
        api_client.measure_incrementality_study(
            world["second_study"]["id"],
            {
                "exposed_conversions": EXPOSED_CONVERSIONS,
                "control_conversions": BELOW_BOUNDARY_CONTROL_CONVERSIONS,
                "exposed_sales_cents": EXPOSED_SALES_CENTS,
                "control_sales_cents": CONTROL_SALES_CENTS,
            },
            MEASUREMENT_ANALYST,
        )
    )

    exposed_rate = EXPOSED_CONVERSIONS / GROUP_SIZE
    control_rate = BELOW_BOUNDARY_CONTROL_CONVERSIONS / GROUP_SIZE
    expected_score = round_half_up(abs(exposed_rate - control_rate) * GROUP_SIZE**0.5, 4)
    assert expected_score == 1.95
    assert expected_score < SIGNIFICANCE_MIN
    assert measured["significance_score"] == expected_score
    assert measured["significance_flag"] is False
    assert measured["lift_pct"] == round_half_up(exposed_rate / control_rate - 1.0, 4)
    assert measured["lift_pct"] == 0.6393
    assert measured["incremental_sales_cents"] == 1949918

    validate_error(
        api_client.publish_incrementality_study(
            world["second_study"]["id"],
            {"publication_note": "just below significance"},
            MEASUREMENT_ANALYST,
        ),
        ERR_STUDY_NOT_SIGNIFICANT,
    )

    # The refused publication leaves the study where it was.
    assert (
        validate_success(
            api_client.get_incrementality_study(
                world["second_study"]["id"], MEASUREMENT_ANALYST
            )
        )["study_status"]
        == "MEASURING"
    )


# ---------------------------------------------------------------------------
# The slot capacity boundary
# ---------------------------------------------------------------------------

OCCUPANT_A_FLIGHT = ("2026-08-01T00:00:00Z", "2026-08-10T00:00:00Z")
OCCUPANT_B_FLIGHT = ("2026-08-05T00:00:00Z", "2026-08-15T00:00:00Z")
OVERLAPPING_CANDIDATE_FLIGHT = ("2026-08-08T00:00:00Z", "2026-08-12T00:00:00Z")
ABUTTING_CANDIDATE_FLIGHT = ("2026-08-15T00:00:00Z", "2026-08-20T00:00:00Z")
LINE_ITEM_DAILY_BUDGET_CENTS = 1000


def _slot_at_capacity_world():
    """A two-occupant slot whose limit is two, plus two candidates awaiting a decision.

    The slot names no exclusivity category and carries no adjacency buffer, and it is an
    on-site slot, so only the aggregate capacity rule can refuse anything here. The
    campaign stays in DRAFT throughout, so the plan reserves nothing.

    Occupants A and B are eligible and their flights overlap each other. The first
    candidate's flight overlaps both of them; the second candidate's flight begins at the
    exact instant B's flight ends and runs past A's, so it overlaps neither.
    """
    world = build_active_advertiser()
    build_active_budget_plan(
        world,
        committed_total_cents=1000000,
        trade_fund_share_cents=0,
        window_start_at="2026-07-01T00:00:00Z",
        window_end_at="2026-11-01T00:00:00Z",
    )
    build_placement_slot(
        world,
        page_type="HOMEPAGE",
        max_concurrent_line_items=2,
        floor_cpc_cents=1000,
        buffer_minutes=0,
    )
    build_catalog_product(world)
    build_draft_campaign(
        world,
        flight_start_at="2026-07-25T00:00:00Z",
        flight_end_at="2026-09-01T00:00:00Z",
        allocated_budget_cents=500000,
        daily_cap_cents=400000,
    )

    for key, (start, end) in (
        ("occupant_a", OCCUPANT_A_FLIGHT),
        ("occupant_b", OCCUPANT_B_FLIGHT),
    ):
        build_pending_eligibility_line_item(
            world,
            key=key,
            bid_cents=2000,
            daily_budget_cents=LINE_ITEM_DAILY_BUDGET_CENTS,
            flight_start_at=start,
            flight_end_at=end,
        )
        world[key] = validate_success(
            api_client.decide_line_item_eligibility(
                world[key]["id"],
                {"decision": "APPROVE", "decision_note": "occupant"},
                CATALOG_OPS,
            )
        )

    for key, (start, end) in (
        ("overlapping_candidate", OVERLAPPING_CANDIDATE_FLIGHT),
        ("abutting_candidate", ABUTTING_CANDIDATE_FLIGHT),
    ):
        build_pending_eligibility_line_item(
            world,
            key=key,
            bid_cents=2000,
            daily_budget_cents=LINE_ITEM_DAILY_BUDGET_CENTS,
            flight_start_at=start,
            flight_end_at=end,
        )
    return world


def test_candidate_overlapping_exactly_max_concurrent_occupants_is_refused():
    """Two overlapping occupants against a limit of two fails the strict comparison.

    PRD 3.5: "Rule A is aggregate capacity and applies to every slot regardless of
    channel: the number of those rows whose flight overlaps the candidate's flight must
    be strictly less than `max_concurrent_line_items`."

    PRD 3.5: "Both branches stamp `eligibility_decided_by_user_id`, and the two branches
    diverge on what they do with capacity."

    Design: Difficulty/boundary_precision_check/bpc_slot_overlap_count_exactly_at_capacity_versus_adjacent_window
    """
    world = _slot_at_capacity_world()

    assert world["slot"]["max_concurrent_line_items"] == 2
    assert_occupancy_count(reread_slot(world), 2)

    validate_error(
        api_client.decide_line_item_eligibility(
            world["overlapping_candidate"]["id"],
            {"decision": "APPROVE", "decision_note": "overlaps A and B"},
            CATALOG_OPS,
        ),
        ERR_SLOT_CAPACITY_EXCEEDED,
    )

    # Neither eligibility branch was taken, so nothing was stamped and no capacity moved.
    refused = reread_line_item(world, "overlapping_candidate")
    assert refused["line_item_status"] == "PENDING_ELIGIBILITY"
    assert refused["eligibility_decided_by_user_id"] is None
    assert refused["reserved_cents"] == 0
    assert_occupancy_count(reread_slot(world), 2)
    assert reread_line_item(world, "occupant_a")["line_item_status"] == "ELIGIBLE"
    assert reread_line_item(world, "occupant_b")["line_item_status"] == "ELIGIBLE"


def test_candidate_abutting_an_occupant_overlaps_nothing_and_is_approved():
    """A flight beginning where an occupant's ends overlaps nothing, so capacity is free.

    PRD 2.8: "Adjacency is consequently never a collision: a range that ends at exactly
    the instant another begins does not overlap it."

    PRD 3.5: "It lands the line item in `ELIGIBLE`, raises the slot's `occupancy_count`
    by 1, and computes `reserved_cents` as `daily_budget_cents` multiplied by the number
    of whole twenty-four-hour periods in the line item's flight, with that day count
    floored at 1"

    Design: Difficulty/boundary_precision_check/bpc_slot_overlap_count_exactly_at_capacity_versus_adjacent_window
    """
    world = _slot_at_capacity_world()

    # The candidate opens at the exact instant occupant B's flight closes.
    assert ABUTTING_CANDIDATE_FLIGHT[0] == OCCUPANT_B_FLIGHT[1]

    approved = validate_success(
        api_client.decide_line_item_eligibility(
            world["abutting_candidate"]["id"],
            {"decision": "APPROVE", "decision_note": "adjacency is not overlap"},
            CATALOG_OPS,
        )
    )
    assert approved["line_item_status"] == "ELIGIBLE"
    assert approved["eligible_product_count"] == 1

    flight_days = whole_day_periods(*ABUTTING_CANDIDATE_FLIGHT)
    assert flight_days == 5
    assert approved["reserved_cents"] == LINE_ITEM_DAILY_BUDGET_CENTS * flight_days
    assert approved["reserved_cents"] == 5000

    # Occupancy counts every eligible line item on the slot, overlapping or not.
    assert_occupancy_count(reread_slot(world), 3)
    assert reread_line_item(world, "occupant_a")["line_item_status"] == "ELIGIBLE"
    assert reread_line_item(world, "occupant_b")["line_item_status"] == "ELIGIBLE"
