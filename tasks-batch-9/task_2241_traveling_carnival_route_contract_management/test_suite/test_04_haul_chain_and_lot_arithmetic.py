"""Travel time on the haul chain, the charged footprint and abated weather."""

from test_helpers import (
    CHAIR_SWINGS,
    CLOCK_START,
    GIANT_WHEEL,
    ROUTE_MANAGER,
    ApiErrorId,
    add_route_stop,
    adjudicate_closure,
    assert_lot_ledgers,
    cancel_lot,
    log_closure,
    open_route,
    read_route,
    read_route_stop,
    read_weather_closure,
    register_jurisdiction,
    register_ride,
    register_venue,
    reserve_allocation,
    set_logical_clock,
    setup_open_lot,
    validate_error,
    validate_success,
)

SECOND_STOP_CALENDAR = {
    "open_date": "2026-09-12T12:00:00Z",
    "close_date": "2026-09-15T12:00:00Z",
    "teardown_deadline": "2026-09-16T12:00:00Z",
}
OPEN_LOT_CONTRACT = {
    "revenue_split_pct_operator": 65,
    "guarantee_cents": 900000,
    "ride_minimum_count": 1,
    "settlement_basis": "SPLIT_ONLY",
}
OPEN_LOT_RIDE = dict(GIANT_WHEEL, requires_state_inspection=False)
OPEN_LOT_OPERATOR = {
    "full_name": "Op One",
    "employment_type": "PERMANENT",
    "hourly_rate_cents": 1600,
    "certified_ride_classes": ["MAJOR"],
}


def _two_lot_route(second_load_in: str):
    """Two lots in one state with a 495-mile haul between them."""
    set_logical_clock(CLOCK_START)
    jurisdiction = register_jurisdiction()
    franklin = register_venue(jurisdiction["id"])
    union = register_venue(
        jurisdiction["id"],
        name="Union County Fairgrounds",
        city="Marysville",
        lot_area_sqft=200000,
        power_amps_available=1000,
        expected_attendance=10001,
        lot_surface="PAVED",
    )
    route = open_route()
    head = add_route_stop(route["id"], franklin["id"])
    second = add_route_stop(
        route["id"],
        union["id"],
        load_in_start=second_load_in,
        previous_stop_id=head["id"],
        haul_miles_from_previous=495,
        **SECOND_STOP_CALENDAR,
    )
    return jurisdiction, route, head, second


def test_sequencing_pads_a_495_mile_haul_with_one_mandated_rest_block(api):
    """PRD §3.1: "Raw driving hours are the stop's `haul_miles_from_previous`
    divided by an average haul speed of 45 miles per hour. Federal rest rules
    oblige a ten-hour break after each full eleven-hour driving shift, so the
    number of rest blocks is the raw driving hours divided by eleven, rounded
    **down** to a whole number; note that this floor is taken on the unrounded
    ratio. The stop's `travel_hours_from_previous` is then the raw driving hours
    plus ten hours for each rest block, rounded half-up to two decimals."

    PRD §3.1: "Walking the validated chain from its head, the system assigns `sequence_index` — 0 for
    the head, then one more for each link walked forward — and computes travel time
    for each stop."

    Design: Corner/calculations/sequencing_pads_a_495_mile_haul_with_one_mandated_rest_block
    """
    _jurisdiction, route, head, second = _two_lot_route("2026-09-09T15:00:00Z")

    sequenced = validate_success(api.sequence_route(route["id"], ROUTE_MANAGER))
    assert sequenced["status"] == "SEQUENCED"

    head_row = read_route_stop(head["id"])
    assert head_row["sequence_index"] == 0
    assert head_row["travel_hours_from_previous"] == 0

    second_row = read_route_stop(second["id"])
    assert second_row["sequence_index"] == 1
    assert second_row["travel_hours_from_previous"] == 21.0

    assert sequenced["total_haul_miles"] == 495
    assert sequenced["total_travel_hours"] == 21.0
    assert sequenced["stop_count"] == 2
    assert sequenced["closed_stop_count"] == 0


def test_sequencing_rejects_a_load_in_one_hour_short_of_the_required_gap(api):
    """PRD §3.1: "For every stop after the head, the itinerary must actually
    leave room for that haul: the gap from the previous stop's
    `teardown_deadline` to this stop's `load_in_start`, measured in hours, must
    be at least this stop's `travel_hours_from_previous` plus a six-hour load-out
    buffer. A gap smaller than that required total is refused with
    `ERR_INSUFFICIENT_TRAVEL_WINDOW`."

    Design: Corner/calculations/sequencing_rejects_a_load_in_one_hour_short_of_the_required_gap
    """
    _jurisdiction, route, _head, second = _two_lot_route("2026-09-09T14:00:00Z")

    validate_error(
        api.sequence_route(route["id"], ROUTE_MANAGER),
        ApiErrorId.ERR_INSUFFICIENT_TRAVEL_WINDOW.value,
    )

    unsequenced = read_route(route["id"])
    assert unsequenced["status"] == "DRAFT"
    assert unsequenced["total_travel_hours"] == 0

    second_row = read_route_stop(second["id"])
    assert second_row["sequence_index"] == 0
    assert second_row["travel_hours_from_previous"] == 0


def test_a_darkened_lot_drops_out_of_the_route_travel_totals(api):
    """PRD §3.1: "Sequencing then re-derives the route's aggregates: `stop_count`
    is re-counted over the non-`DARK` stops, `total_haul_miles` is the plain sum
    of `haul_miles_from_previous` across the chain, and `total_travel_hours` is
    the sum of the per-stop travel hours, rounded half-up to two decimals. Stops
    that have gone `DARK` are excluded from the chain and from all three
    figures."

    PRD §3.7: "The two terminal lot states, `CLOSED` and `DARK`, are both counted
    by the route's `closed_stop_count`."

    Design: Corner/calculations/darkened_stops_drop_out_of_the_route_travel_totals
    """
    jurisdiction, route, head, second = _two_lot_route("2026-09-09T15:00:00Z")
    village_green = register_venue(
        jurisdiction["id"],
        name="Village Green",
        city="Delaware",
        lot_area_sqft=60000,
        power_amps_available=800,
        expected_attendance=5001,
        lot_surface="GRASS",
    )
    third = add_route_stop(
        route["id"],
        village_green["id"],
        load_in_start="2026-09-20T06:00:00Z",
        open_date="2026-09-23T12:00:00Z",
        close_date="2026-09-26T12:00:00Z",
        teardown_deadline="2026-09-27T12:00:00Z",
        previous_stop_id=second["id"],
        haul_miles_from_previous=300,
    )
    darkened = cancel_lot(third["id"])
    assert darkened["status"] == "DARK"

    sequenced = validate_success(api.sequence_route(route["id"], ROUTE_MANAGER))
    assert sequenced["status"] == "SEQUENCED"
    assert sequenced["total_haul_miles"] == 495
    assert sequenced["total_travel_hours"] == 21.0
    assert sequenced["stop_count"] == 2
    assert sequenced["closed_stop_count"] == 1

    assert read_route_stop(head["id"])["sequence_index"] == 0
    assert read_route_stop(second["id"])["sequence_index"] == 1

    third_row = read_route_stop(third["id"])
    assert third_row["status"] == "DARK"
    assert third_row["sequence_index"] == 0
    assert third_row["travel_hours_from_previous"] == 0


def test_the_charged_footprint_ceils_while_the_amperage_keeps_one_decimal(api):
    """PRD §2.6: "a ride's charged footprint rounds **up** to the next whole
    square foot, a lot's usable area rounds **down**, and a lot's circulation
    reserve rounds **up**."

    PRD §3.3: "Its **charged amperage**, `power_charged_amps`, is its
    `power_amps` inflated by a startup surge of 25 percent for `MAJOR`, 15
    percent for `FLAT` and none at all for `KIDDIE`, rounded half-up to one
    decimal place."

    Design: Corner/calculations/lot_capacity_charge_ceils_the_footprint_and_keeps_amps_at_one_decimal
    """
    set_logical_clock(CLOCK_START)
    jurisdiction = register_jurisdiction()
    venue = register_venue(jurisdiction["id"])
    route = open_route()
    stop = add_route_stop(route["id"], venue["id"])

    wheel = register_ride(dict(GIANT_WHEEL, requires_state_inspection=False))
    wheel_allocation = reserve_allocation(wheel["id"], stop["id"])
    assert wheel_allocation["footprint_charged_sqft"] == 5414
    assert wheel_allocation["power_charged_amps"] == 375.0

    swings = register_ride(dict(CHAIR_SWINGS, requires_state_inspection=False))
    swings_allocation = reserve_allocation(swings["id"], stop["id"])
    assert swings_allocation["footprint_charged_sqft"] == 1924
    assert swings_allocation["power_charged_amps"] == 103.5

    assert_lot_ledgers(read_route_stop(stop["id"]), 7338, 478.5)
    assert wheel_allocation["status"] == "RESERVED"
    assert swings_allocation["status"] == "RESERVED"


def test_overlapping_closures_merge_and_stay_below_the_abatement_floor(api):
    """PRD §3.8: "their clipped intervals are sorted by start then end and joined
    whenever the next interval's start is at or before the current interval's
    end, so that a gap of exactly zero merges. The merged total is the sum of the
    merged intervals' lengths in hours, rounded half-up to two decimals. That
    total becomes the lot's `closure_hours_adjudicated` only if it is at least
    two hours; a merged total below two hours abates nothing at all and the lot's
    figure is 0."

    PRD §3.8: "a row's `abated_hours` is the length in hours of its clipped
    interval minus whatever earlier rows have already claimed, rounded half-up to
    two decimals; the row's clipped interval is then added to the claimed set."

    Design: Corner/calculations/overlapping_closures_merge_and_stay_below_the_two_hour_abatement_floor
    """
    ctx = setup_open_lot(
        contract_overrides=OPEN_LOT_CONTRACT,
        ride_specs=[OPEN_LOT_RIDE],
        worker_specs=[OPEN_LOT_OPERATOR],
    )
    stop_id = ctx["stop"]["id"]
    set_logical_clock("2026-09-05T00:00:00Z")
    wind = log_closure(
        stop_id, "WIND", "2026-09-04T14:00:00Z", "2026-09-04T15:00:00Z"
    )
    rain = log_closure(
        stop_id, "RAIN", "2026-09-04T14:30:00Z", "2026-09-04T15:30:00Z"
    )

    adjudicate_closure(wind["id"])
    second = adjudicate_closure(rain["id"])
    assert second["status"] == "ADJUDICATED"

    wind_row = read_weather_closure(wind["id"])
    assert wind_row["closure_hours_raw"] == 1.0
    assert wind_row["abated_hours"] == 1.0

    rain_row = read_weather_closure(rain["id"])
    assert rain_row["closure_hours_raw"] == 1.0
    assert rain_row["abated_hours"] == 0.5

    assert wind_row["abated_hours"] + rain_row["abated_hours"] == 1.5

    stop = read_route_stop(stop_id)
    assert stop["closure_hours_adjudicated"] == 0
    assert stop["status"] == "OPEN"
    assert stop["operating_ride_count"] == 1
