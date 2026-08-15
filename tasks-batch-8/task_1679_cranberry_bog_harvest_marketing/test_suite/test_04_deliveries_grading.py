"""Delivery scheduling, weigh-in, grading tiers, and station capacity
(PRD §3.6)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    approve_ticket,
    assert_delivery,
    assert_money,
    create_active_member,
    create_bog_for,
    create_delivery,
    create_delivery_payload,
    create_season,
    create_station,
    create_ticket,
    get_delivery,
    grade_delivery,
    make_grower_headers,
    make_station_operator_headers,
    open_season,
    receive_delivery,
    setup_campaign,
    setup_campaign_with_station,
    setup_received_delivery,
    setup_scheduled_delivery,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["coop_admin_headers"]
OFFICER = TEST_USERS["field_officer_headers"]


def test_delivery_create_with_unknown_bog_returns_not_found(api):
    """PRD §2.8: "**Existence** — path identifiers and body-referenced ids (such
    as `season_id`, `bog_id`, `receiving_station_id`, and `harvest_ticket_id`)
    resolve to live records, validated left to right so the first missing
    reference surfaces; otherwise `ERR_NOT_FOUND`."

    Design: Corner/entities/delivery_create_with_unknown_bog_returns_not_found
    """
    member = create_active_member()
    season = create_season()
    open_season(season["id"])
    station = create_station()

    resp = api.create_delivery(
        create_delivery_payload(season["id"], NON_EXISTENT_UUID, station["id"],
                                expected_barrels=100),
        make_grower_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_delivery_create_in_setup_season_rejected(api):
    """PRD §3.6: "Scheduling requires the season to be `OPEN`
    (`ERR_SEASON_NOT_OPEN` otherwise)".

    Design: Corner/validations/delivery_create_in_setup_season_rejected
    """
    member = create_active_member()
    bog = create_bog_for(member["id"])
    season = create_season()  # stays SETUP
    station = create_station()

    resp = api.create_delivery(
        create_delivery_payload(season["id"], bog["id"], station["id"],
                                expected_barrels=100),
        make_grower_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_SEASON_NOT_OPEN)


def test_delivery_net_barrels_computed_with_precision(api):
    """PRD §3.6: "the delivery moves `SCHEDULED → RECEIVED` with `net_barrels`
    computed as the gross minus the tare, rounded half-up to two decimals."

    Design: Corner/entities/delivery_net_barrels_computed_with_precision
    """
    ctx = setup_campaign_with_station()
    delivery = setup_scheduled_delivery(ctx, expected_barrels=150)

    received = receive_delivery(delivery["id"], ctx.station["id"],
                                100.55, 20.25)
    assert_delivery(received)
    assert received["status"] == "RECEIVED"
    assert_money(received["net_barrels"], 80.30)


def test_tare_exceeds_gross_rejected_at_receive(api):
    """PRD §3.6: "the request carries `gross_barrels` and `tare_barrels`, and a
    `tare_barrels` greater than `gross_barrels` is rejected with
    `ERR_TARE_EXCEEDS_GROSS`."

    Design: Corner/validations/tare_exceeds_gross_rejected_at_receive
    """
    ctx = setup_campaign_with_station()
    delivery = setup_scheduled_delivery(ctx, expected_barrels=150)

    resp = api.receive_delivery(
        delivery["id"], {"gross_barrels": 100, "tare_barrels": 150},
        make_station_operator_headers(ctx.station["id"]))
    validate_error(resp, ApiErrorId.ERR_TARE_EXCEEDS_GROSS)
    assert get_delivery(delivery["id"])["status"] == "SCHEDULED"


def test_delivery_grade_before_receive_invalid_state(api):
    """PRD §3.6: "Grading follows at the same station." (after receiving).
    PRD §2.8: "the target resource is in a state from which the requested
    transition is defined, including terminal lockdown (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/delivery_grade_before_receive_invalid_state
    """
    ctx = setup_campaign_with_station()
    delivery = setup_scheduled_delivery(ctx, expected_barrels=150)

    resp = api.grade_delivery(
        delivery["id"],
        {"color_score": 9.0, "firmness_score": 9.0, "foreign_matter_pct": 1.0},
        make_station_operator_headers(ctx.station["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_delivery(delivery["id"])["status"] == "SCHEDULED"


def test_grade_tier_three_input_branching_forces_b(api):
    """PRD §3.6: "Otherwise the tiers are tested from the top down: `A` requires
    color and firmness each at least 8.0 with foreign matter at most 2.0
    percent; `B` requires color and firmness each at least 7.0 with foreign
    matter at most 4.0 percent".
    PRD §3.6: "The grade fixes the `premium_multiplier`: 1.10 for `A`, 1.00 for
    `B`, 0.90 for `C`, and 0 for `REJECT`; `weighted_barrels` is the
    `net_barrels` multiplied by that multiplier, rounded half-up to two
    decimals."

    Design: Difficulty/combinatorial_formula/grade_tier_assignment_three_input_branching
    """
    ctx = setup_campaign_with_station()
    delivery = setup_received_delivery(ctx, 200, 10, expected_barrels=200)

    graded = grade_delivery(delivery["id"], ctx.station["id"],
                            9.0, 9.0, 3.0)
    assert graded["grade"] == "B", (
        "foreign_matter_pct 3.0 exceeds the A cap of 2.0 despite 9.0/9.0 scores")
    assert_money(graded["premium_multiplier"], 1.00)
    assert_money(graded["weighted_barrels"], 190.00)  # net 190 * 1.00
    assert graded["status"] == "GRADED"


def test_grade_tier_branching_firmness_shortfall_forces_c(api):
    """PRD §3.6: "`C` requires color and firmness each at least 6.0 with foreign
    matter at most 6.0 percent; fruit failing all three tiers is `REJECT`."
    PRD §3.6: "The grade fixes the `premium_multiplier`: 1.10 for `A`, 1.00 for
    `B`, 0.90 for `C`, and 0 for `REJECT`".

    Design: Difficulty/combinatorial_formula/grade_tier_assignment_three_input_branching
    """
    ctx = setup_campaign_with_station()
    delivery = setup_received_delivery(ctx, 200, 10, expected_barrels=200)

    # color 8.5 meets A/B color, but firmness 6.5 fails both; C tier catches it.
    graded = grade_delivery(delivery["id"], ctx.station["id"],
                            8.5, 6.5, 1.0)
    assert graded["grade"] == "C"
    assert_money(graded["premium_multiplier"], 0.90)
    assert_money(graded["weighted_barrels"], 171.00)  # net 190 * 0.90
    assert graded["status"] == "GRADED"


def test_grade_boundaries_exactly_at_a_threshold(api):
    """PRD §3.6: "Every boundary is inclusive — scores of exactly 8.0, 8.0, and
    2.0 percent earn grade `A`."
    PRD §3.6: "The grade fixes the `premium_multiplier`: 1.10 for `A`, 1.00 for
    `B`, 0.90 for `C`, and 0 for `REJECT`; `weighted_barrels` is the
    `net_barrels` multiplied by that multiplier, rounded half-up to two
    decimals."

    Design: Difficulty/boundary_precision_check/grade_color_exactly_at_grade_a_threshold
    """
    ctx = setup_campaign_with_station()
    delivery = setup_received_delivery(ctx, 150, 50, expected_barrels=150)

    graded = grade_delivery(delivery["id"], ctx.station["id"],
                            8.0, 8.0, 2.0)
    assert graded["grade"] == "A", "all three boundaries sit exactly at the inclusive thresholds"
    assert_money(graded["premium_multiplier"], 1.10)
    assert_money(graded["weighted_barrels"], 110.00)  # net 100 * 1.10
    assert graded["status"] == "GRADED"


def test_grade_just_below_a_threshold_lands_b(api):
    """PRD §3.6: "`A` requires color and firmness each at least 8.0 with foreign
    matter at most 2.0 percent; `B` requires color and firmness each at least
    7.0 with foreign matter at most 4.0 percent".

    Design: Difficulty/boundary_precision_check/grade_color_exactly_at_grade_a_threshold
    """
    ctx = setup_campaign_with_station()
    delivery = setup_received_delivery(ctx, 150, 50, expected_barrels=150)

    graded = grade_delivery(delivery["id"], ctx.station["id"],
                            7.99, 8.0, 2.0)
    assert graded["grade"] == "B", "color 7.99 falls just under the A threshold"
    assert_money(graded["premium_multiplier"], 1.00)
    assert_money(graded["weighted_barrels"], 100.00)  # net 100 * 1.00


def test_grade_c_discount_multiplier_applied(api):
    """PRD §3.6: "`C` requires color and firmness each at least 6.0 with foreign
    matter at most 6.0 percent".
    PRD §3.6: "The grade fixes the `premium_multiplier`: 1.10 for `A`, 1.00 for
    `B`, 0.90 for `C`, and 0 for `REJECT`; `weighted_barrels` is the
    `net_barrels` multiplied by that multiplier, rounded half-up to two
    decimals."

    Design: Corner/calculations/grade_c_discount_multiplier_applied
    """
    ctx = setup_campaign_with_station()
    delivery = setup_received_delivery(ctx, 1050, 50, expected_barrels=1050)

    graded = grade_delivery(delivery["id"], ctx.station["id"],
                            6.5, 6.0, 5.5)
    assert graded["grade"] == "C"
    assert_money(graded["premium_multiplier"], 0.90)
    assert_money(graded["weighted_barrels"], 900.00)  # net 1000 * 0.90


def test_grade_reject_by_foreign_matter_only(api):
    """PRD §3.6: "Foreign matter above 6.0 percent rejects the fruit outright
    before any tier is considered."
    PRD §3.6: "A passing grade moves the delivery `RECEIVED → GRADED`; a
    `REJECT` result moves it to `REJECTED`, which is terminal."

    Design: Corner/calculations/grade_reject_by_foreign_matter_only
    """
    ctx = setup_campaign_with_station()
    delivery = setup_received_delivery(ctx, 150, 50, expected_barrels=150)

    graded = grade_delivery(delivery["id"], ctx.station["id"],
                            10.0, 10.0, 7.0)
    assert graded["grade"] == "REJECT"
    assert graded["status"] == "REJECTED"
    assert_money(graded["weighted_barrels"], 0)
    assert_money(graded["premium_multiplier"], 0)

    # REJECTED is terminal: dispute is not defined from it.
    resp = api.dispute_delivery(delivery["id"],
                                make_grower_headers(ctx.member["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_station_capacity_exact_fill_then_overflow(api):
    """PRD §3.6: "a new booking is rejected with `ERR_STATION_CAPACITY_EXCEEDED`
    when that load plus the new `expected_barrels` would exceed the station's
    `daily_capacity_barrels` — a total exactly equal to the daily capacity is
    allowed."

    Design: Difficulty/resource_temporal_overlap/station_daily_aggregate_capacity_bucket
    """
    ctx = setup_campaign_with_station(capacity=500)
    d1 = setup_scheduled_delivery(ctx, expected_barrels=300)
    d2 = setup_scheduled_delivery(ctx, expected_barrels=200)
    assert d1["status"] == "SCHEDULED" and d2["status"] == "SCHEDULED", (
        "300 + 200 == 500 is exactly the daily capacity and must be allowed")

    resp = api.create_delivery(
        create_delivery_payload(ctx.season["id"], ctx.bog["id"],
                                ctx.station["id"], expected_barrels=1),
        make_grower_headers(ctx.member["id"]))
    validate_error(resp, ApiErrorId.ERR_STATION_CAPACITY_EXCEEDED)


def test_graded_delivery_frees_station_capacity(api):
    """PRD §3.6: "the day's load at a station is the sum of `expected_barrels`
    over all deliveries at that station on the same `scheduled_date` in
    `SCHEDULED` or `RECEIVED` status" — a GRADED delivery no longer counts.

    Design: Difficulty/resource_temporal_overlap/station_daily_aggregate_capacity_bucket
    """
    ctx = setup_campaign_with_station(capacity=500)
    delivery = setup_scheduled_delivery(ctx, expected_barrels=300)
    receive_delivery(delivery["id"], ctx.station["id"], 300, 0)
    graded = grade_delivery(delivery["id"], ctx.station["id"], 9.0, 9.0, 1.0)
    assert graded["status"] == "GRADED"

    # The GRADED delivery's 300 expected barrels have left the day bucket.
    d2 = create_delivery(ctx.season["id"], ctx.bog["id"], ctx.station["id"],
                         ctx.member["id"], expected_barrels=400)
    assert d2["status"] == "SCHEDULED"


def test_delivery_with_ticket_of_other_bog_rejected(api):
    """PRD §3.6: "When a `harvest_ticket_id` is supplied, the ticket must be
    `APPROVED` and must belong to the same bog as the delivery, else the request
    fails with `ERR_TICKET_INVALID`."

    Design: Corner/endpoints/ticket_invalid_error_triggerability
    """
    member = create_active_member()
    bog1 = create_bog_for(member["id"], name="North Bog")
    bog2 = create_bog_for(member["id"], name="South Bog", acres=8,
                          variety="BEN_LEAR", sprinkler_demand_gpm=400)
    season = create_season()
    ticket = create_ticket(bog1["id"], season["id"], member["id"],
                           window_start="2026-10-01T00:00:00Z",
                           window_end="2026-10-05T00:00:00Z")
    approve_ticket(ticket["id"])
    open_season(season["id"])
    station = create_station()

    resp = api.create_delivery(
        create_delivery_payload(season["id"], bog2["id"], station["id"],
                                harvest_ticket_id=ticket["id"],
                                expected_barrels=100),
        make_grower_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_TICKET_INVALID)
