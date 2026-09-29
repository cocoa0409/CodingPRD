"""Two resources whose collision test deliberately departs from plain overlap.

An off-site slot with an adjacency buffer widens the candidate flight before testing it,
so flights that merely touch do collide. A campaign's measurement calendar is compared by
clear gap instead of by overlap, so windows that are fully disjoint still collide when
they sit closer together than the washout period. Each rule is pinned twice: once where
it bites and once at the first position where it lets go.
"""

from test_helpers import (
    CATALOG_OPS,
    ERR_SLOT_BUFFER_CONFLICT,
    ERR_STUDY_WASHOUT_VIOLATION,
    MEASUREMENT_ANALYST,
    NETWORK_ADMIN,
    WASHOUT_HOURS,
    api_client,
    assert_occupancy_count,
    build_active_advertiser,
    build_active_budget_plan,
    build_catalog_product,
    build_draft_campaign,
    build_offsite_placement_slot,
    build_pending_eligibility_line_item,
    build_pending_review_campaign,
    build_placement_slot,
    factories,
    hours_between,
    parse_utc,
    reread_campaign,
    reread_line_item,
    reread_slot,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    whole_day_periods,
)

# --- The off-site adjacency buffer -----------------------------------------

BUFFER_MINUTES = 30
SLOT_CAPACITY = 3
LINE_ITEM_DAILY_BUDGET_CENTS = 100000
OCCUPANT_FLIGHT = ("2026-08-08T00:00:00Z", "2026-08-12T00:00:00Z")
TOUCHING_FLIGHT = ("2026-08-12T00:00:00Z", "2026-08-16T00:00:00Z")
CLEAR_OF_BUFFER_FLIGHT = ("2026-08-12T00:30:00Z", "2026-08-16T00:00:00Z")


def _buffered_slot_world(candidate_flight):
    """An off-site slot with a half-hour buffer, one occupant, and one candidate.

    The slot admits three concurrent line items and names no exclusivity category, so
    neither the aggregate-capacity rule nor the category rule can refuse anything. The
    occupant's flight closes on 2026-08-12; the candidate is placed relative to that
    instant by the caller.
    """
    world = build_active_advertiser()
    build_active_budget_plan(
        world,
        committed_total_cents=5000000,
        trade_fund_share_cents=0,
        window_start_at="2026-07-01T00:00:00Z",
        window_end_at="2026-10-01T00:00:00Z",
    )
    build_offsite_placement_slot(
        world,
        page_type="OFFSITE_DISPLAY",
        max_concurrent_line_items=SLOT_CAPACITY,
        floor_cpc_cents=50,
        buffer_minutes=BUFFER_MINUTES,
    )
    build_catalog_product(world, category_code="SNACKS")
    build_draft_campaign(
        world,
        channel_mix="OFFSITE_ONLY",
        flight_start_at="2026-08-05T00:00:00Z",
        flight_end_at="2026-08-25T00:00:00Z",
        allocated_budget_cents=2000000,
        daily_cap_cents=200000,
    )
    build_pending_eligibility_line_item(
        world,
        key="occupant",
        bid_cents=120,
        daily_budget_cents=LINE_ITEM_DAILY_BUDGET_CENTS,
        flight_start_at=OCCUPANT_FLIGHT[0],
        flight_end_at=OCCUPANT_FLIGHT[1],
        category_code="SNACKS",
        keyword_match_terms=["pretzel", "crisps"],
    )
    world["occupant"] = validate_success(
        api_client.decide_line_item_eligibility(
            world["occupant"]["id"],
            {"decision": "APPROVE", "decision_note": "first off-site flight"},
            CATALOG_OPS,
        )
    )
    build_pending_eligibility_line_item(
        world,
        key="candidate",
        bid_cents=130,
        daily_budget_cents=LINE_ITEM_DAILY_BUDGET_CENTS,
        flight_start_at=candidate_flight[0],
        flight_end_at=candidate_flight[1],
        category_code="SNACKS",
        keyword_match_terms=["pretzel", "snack"],
    )
    return world


def test_a_touching_flight_collides_with_the_widened_off_site_interval():
    """A candidate beginning where the occupant ends is refused by the buffer, not capacity.

    PRD 3.5: "Rule C is the adjacency buffer and applies only when the slot's `channel` is
    `OFFSITE` and `buffer_minutes` is greater than 0: the candidate's flight is widened by
    that many whole minutes at the start **and** at the end, and no occupying row may
    overlap the widened interval. Because of the widening, flights that merely touch — one
    ending exactly where another begins — do collide under Rule C even though they pass
    Rule A."

    PRD 2.12: "55. On the line item eligibility decision: the adjacency-buffer rule holds
    — on an off-site slot with a non-zero `buffer_minutes`, no occupying line item
    overlaps the candidate flight inflated by that buffer on both sides — otherwise
    `ERR_SLOT_BUFFER_CONFLICT`, 409."

    Design: Difficulty/resource_temporal_overlap/rto_offsite_slot_buffer_inflation_rejects_adjacent_flights
    """
    world = _buffered_slot_world(TOUCHING_FLIGHT)

    slot = reread_slot(world)
    assert slot["channel"] == "OFFSITE"
    assert slot["buffer_minutes"] == BUFFER_MINUTES
    assert slot["max_concurrent_line_items"] == SLOT_CAPACITY
    assert_occupancy_count(slot, 1)

    # The occupant reserved one day of budget for each whole day of its flight.
    occupant = reread_line_item(world, "occupant")
    assert occupant["line_item_status"] == "ELIGIBLE"
    occupant_days = whole_day_periods(*OCCUPANT_FLIGHT)
    assert occupant_days == 4
    assert occupant["reserved_cents"] == LINE_ITEM_DAILY_BUDGET_CENTS * occupant_days
    assert occupant["reserved_cents"] == 400000

    # The candidate's own flight touches the occupant's without overlapping it, so the
    # single occupant is invisible to the plain-overlap capacity rule.
    assert TOUCHING_FLIGHT[0] == OCCUPANT_FLIGHT[1]

    validate_error(
        api_client.decide_line_item_eligibility(
            world["candidate"]["id"],
            {"decision": "APPROVE", "decision_note": "second off-site flight"},
            CATALOG_OPS,
        ),
        ERR_SLOT_BUFFER_CONFLICT,
    )

    # No occupancy was granted and no decision was stamped.
    candidate = reread_line_item(world, "candidate")
    assert candidate["line_item_status"] == "PENDING_ELIGIBILITY"
    assert candidate["eligibility_decided_by_user_id"] is None
    assert candidate["reserved_cents"] == 0
    assert_occupancy_count(reread_slot(world), 1)
    assert reread_line_item(world, "occupant")["line_item_status"] == "ELIGIBLE"


def test_a_gap_of_exactly_the_buffer_clears_the_widened_interval():
    """Half an hour of clear air leaves the widened interval merely adjacent, which passes.

    PRD 2.8: "On an off-site placement slot that declares a non-zero adjacency buffer, the
    candidate line item's flight is inflated by that many whole minutes on **both** sides
    before the overlap test is applied, so touching and near-touching flights do collide
    even though they pass the plain-overlap capacity test."

    PRD 2.8: "Adjacency is consequently never a collision: a range that ends at exactly
    the instant another begins does not overlap it."

    Design: Difficulty/resource_temporal_overlap/rto_offsite_slot_buffer_inflation_rejects_adjacent_flights
    """
    world = _buffered_slot_world(CLEAR_OF_BUFFER_FLIGHT)

    # Widening the candidate by the buffer brings its start back to exactly the instant
    # the occupant's flight closes, so the widened interval only abuts the occupant.
    gap = parse_utc(CLEAR_OF_BUFFER_FLIGHT[0]) - parse_utc(OCCUPANT_FLIGHT[1])
    assert gap.total_seconds() / 60 == BUFFER_MINUTES

    approved = validate_success(
        api_client.decide_line_item_eligibility(
            world["candidate"]["id"],
            {"decision": "APPROVE", "decision_note": "clear of the buffer"},
            CATALOG_OPS,
        )
    )
    assert approved["line_item_status"] == "ELIGIBLE"

    candidate_days = whole_day_periods(*CLEAR_OF_BUFFER_FLIGHT)
    assert candidate_days == 3
    assert approved["reserved_cents"] == LINE_ITEM_DAILY_BUDGET_CENTS * candidate_days
    assert_occupancy_count(reread_slot(world), 2)


# ---------------------------------------------------------------------------
# The measurement washout gap
# ---------------------------------------------------------------------------

STUDY_A_WINDOW = ("2026-08-05T00:00:00Z", "2026-08-12T00:00:00Z")
TOO_CLOSE_WINDOW = ("2026-08-18T00:00:00Z", "2026-08-25T00:00:00Z")
EXACTLY_ONE_WASHOUT_LATER_WINDOW = ("2026-08-19T00:00:00Z", "2026-08-26T00:00:00Z")


def _running_study_world():
    """A scheduled campaign carrying one RUNNING study over 2026-08-05 to 2026-08-12.

    A study may only be started while its campaign is scheduled or delivering, so the
    campaign is carried through review to `SCHEDULED` on the strength of one line item
    awaiting its eligibility decision. The clock stands at the study window's opening
    instant, which is the earliest moment the study may start.
    """
    world = build_active_advertiser()
    set_clock(world, STUDY_A_WINDOW[0])
    build_active_budget_plan(
        world,
        committed_total_cents=5000000,
        trade_fund_share_cents=0,
        window_start_at="2026-07-01T00:00:00Z",
        window_end_at="2026-10-01T00:00:00Z",
    )
    build_placement_slot(world, floor_cpc_cents=50)
    build_catalog_product(world)
    build_draft_campaign(
        world,
        channel_mix="ONSITE_ONLY",
        flight_start_at="2026-08-01T00:00:00Z",
        flight_end_at="2026-09-01T00:00:00Z",
        allocated_budget_cents=2000000,
        daily_cap_cents=200000,
    )
    build_pending_eligibility_line_item(
        world,
        bid_cents=120,
        daily_budget_cents=100000,
        flight_start_at="2026-08-05T00:00:00Z",
        flight_end_at="2026-08-25T00:00:00Z",
    )
    build_pending_review_campaign(world, with_line_item=False)
    world["campaign"] = validate_success(
        api_client.decide_campaign_review(
            world["campaign"]["id"],
            {"decision": "APPROVE", "decision_note": "cleared for delivery"},
            NETWORK_ADMIN,
        )
    )
    assert world["campaign"]["delivery_status"] == "SCHEDULED"

    campaign = reread_campaign(world)
    world["study_a"] = validate_success(
        api_client.create_incrementality_study(
            factories.incrementality_study_payload(
                campaign["id"],
                campaign["version"],
                design_method="GEO_HOLDOUT",
                holdout_pct=0.2,
                window_start_at=STUDY_A_WINDOW[0],
                window_end_at=STUDY_A_WINDOW[1],
            ),
            MEASUREMENT_ANALYST,
        ),
        201,
    )
    world["study_a"] = validate_success(
        api_client.start_incrementality_study(
            world["study_a"]["id"],
            {"exposed_group_size": 50000, "control_group_size": 12500},
            MEASUREMENT_ANALYST,
        )
    )
    assert world["study_a"]["study_status"] == "RUNNING"
    return world


def _design_study(world, window, design_method="USER_HOLDOUT"):
    """Ask for a second study on the same campaign over the given window."""
    campaign = reread_campaign(world)
    return api_client.create_incrementality_study(
        factories.incrementality_study_payload(
            campaign["id"],
            campaign["version"],
            design_method=design_method,
            holdout_pct=0.2,
            window_start_at=window[0],
            window_end_at=window[1],
        ),
        MEASUREMENT_ANALYST,
    )


def test_a_fully_disjoint_window_inside_the_washout_period_is_refused():
    """Six days of clear air is not seven, so a window overlapping nothing still collides.

    PRD 2.8: "measurement study windows on the same campaign are compared by **clear gap**
    rather than by overlap: two windows collide when the gap between them is strictly less
    than the washout period, so even fully disjoint windows separated by three days
    collide."

    PRD 3.7: "the comparison set is every other study on the same campaign whose
    `study_status` is `RUNNING`, `MEASURING` or `PUBLISHED`, and for each such study the
    gap is the number of whole hours of clear air between the two windows — the later
    window's start less the earlier window's end."

    PRD 3.7: "A collision occurs when the gap is strictly less than one hundred and
    sixty-eight hours, which is the seven-day washout expressed in hours; a gap of exactly
    one hundred and sixty-eight hours passes."

    Design: Difficulty/resource_temporal_overlap/rto_study_washout_gap_rejects_disjoint_measurement_window
    """
    world = _running_study_world()

    # The candidate window opens after the running study's window closes, so a plain
    # overlap test would have admitted it.
    assert TOO_CLOSE_WINDOW[0] > STUDY_A_WINDOW[1]
    gap_hours = hours_between(STUDY_A_WINDOW[1], TOO_CLOSE_WINDOW[0])
    assert gap_hours == 144
    assert gap_hours < WASHOUT_HOURS == 168

    validate_error(_design_study(world, TOO_CLOSE_WINDOW), ERR_STUDY_WASHOUT_VIOLATION)

    # The refused design left the campaign with only the running study.
    studies, page = validate_paginated(
        api_client.list_incrementality_studies(
            MEASUREMENT_ANALYST, campaign_id=world["campaign"]["id"]
        )
    )
    assert len(studies) == 1
    assert page["total_count"] == 1
    study_a = validate_success(
        api_client.get_incrementality_study(world["study_a"]["id"], MEASUREMENT_ANALYST)
    )
    assert study_a["study_status"] == "RUNNING"
    assert parse_utc(study_a["window_end_at"]) == parse_utc(STUDY_A_WINDOW[1])


def test_a_gap_of_exactly_the_washout_period_admits_the_later_study():
    """One day further out makes the gap exactly the washout, which the rule admits.

    PRD 3.7: "A collision occurs when the gap is strictly less than one hundred and
    sixty-eight hours, which is the seven-day washout expressed in hours; a gap of exactly
    one hundred and sixty-eight hours passes."

    PRD 3.7: "The study is born `DESIGNED` with `exposed_group_size`,
    `control_group_size`, `exposed_conversions`, `control_conversions`,
    `exposed_sales_cents` and `control_sales_cents` all 0, every result figure null,
    `invalidated_reason` `NONE` and a null `published_by_user_id`; design increments the
    campaign's `version` by 1."

    Design: Difficulty/resource_temporal_overlap/rto_study_washout_gap_rejects_disjoint_measurement_window
    """
    world = _running_study_world()

    gap_hours = hours_between(STUDY_A_WINDOW[1], EXACTLY_ONE_WASHOUT_LATER_WINDOW[0])
    assert gap_hours == WASHOUT_HOURS

    study_b = validate_success(
        _design_study(world, EXACTLY_ONE_WASHOUT_LATER_WINDOW), 201
    )
    assert study_b["study_status"] == "DESIGNED"
    assert study_b["design_method"] == "USER_HOLDOUT"
    assert parse_utc(study_b["window_start_at"]) == parse_utc(
        EXACTLY_ONE_WASHOUT_LATER_WINDOW[0]
    )
    assert study_b["exposed_group_size"] == 0
    assert study_b["control_group_size"] == 0
    assert study_b["published_by_user_id"] is None
    assert study_b["invalidated_reason"] == "NONE"

    studies, page = validate_paginated(
        api_client.list_incrementality_studies(
            MEASUREMENT_ANALYST, campaign_id=world["campaign"]["id"]
        )
    )
    assert page["total_count"] == 2
    assert {s["id"] for s in studies} == {world["study_a"]["id"], study_b["id"]}
