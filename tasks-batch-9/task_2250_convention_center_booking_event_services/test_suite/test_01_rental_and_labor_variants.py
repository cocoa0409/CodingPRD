"""Rental basis variants and union labor charge variants."""

from test_helpers import (
    ApiClient,
    MEETING_ROOM_301,
    SEIU_LOCAL_3,
    assert_crew_hours,
    assert_fields,
    assert_money_cents,
    assert_settlement_money,
    dispatch_labor_call,
    actualize_labor_call,
    read_booking,
    read_labor_call,
    read_settlement,
    read_union_jurisdiction,
    register_union_local,
    schedule_labor_call,
    setup_event_lifecycle,
)

FIVE_ATTESTED_DAYS = (
    ("2027-03-01", "MOVE_IN"),
    ("2027-03-02", "SHOW"),
    ("2027-03-03", "DARK"),
    ("2027-03-04", "DARK"),
    ("2027-03-05", "MOVE_OUT"),
)

ACTUAL_USAGE_RENTAL_CENTS = 204526


def _actual_usage_settlement(api: ApiClient):
    """Close a five-day Meeting Room 301 booking and issue an ACTUAL_USAGE settlement."""
    return setup_event_lifecycle(
        api,
        "settlement_issued",
        space=dict(MEETING_ROOM_301),
        deposit_cents=200000,
        usage_records=FIVE_ATTESTED_DAYS,
        settlement_basis="ACTUAL_USAGE",
        rental_line_cents=ACTUAL_USAGE_RENTAL_CENTS,
    )


def test_actual_usage_basis_reprices_each_attested_day_before_summing(api: ApiClient):
    """Under the ACTUAL_USAGE basis the five attested days re-price to 204526 cents.

    PRD: "Under the `ACTUAL_USAGE` variant the settlement re-prices each attested
    day at its own factor."
    PRD: "The order is pinned: round each usage day first, then sum, then apply the
    class discount and round again."
    PRD: "Step three: `facility_service_fee_cents` is the subtotal multiplied by
    that percentage, rounded half up to whole cents, once."

    Design: Difficulty/dual_variant_calc/actual_usage_rental_basis_diverges_from_contracted_rental_on_same_booking
    """
    world = _actual_usage_settlement(api)

    settlement = read_settlement(api, world["settlement"]["id"])
    assert_settlement_money(
        settlement,
        line_subtotal_cents=204526,
        facility_service_fee_cents=18407,
        grand_total_cents=222933,
    )


def test_actual_usage_subtotal_diverges_from_the_contracted_rental(api: ApiClient):
    """The same booking's contracted rental stays 363600 while the settlement bills 204526.

    PRD: "Under the `CONTRACTED` variant the rental basis is simply the booking's
    `contracted_rental_cents`, and every attested usage record is ignored: the
    licensee is billed the rental exactly as contracted."
    PRD: "`contracted_rental_cents` is `gross_rental_cents` multiplied by one minus
    the class's `rental_discount_pct`, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/actual_usage_rental_basis_diverges_from_contracted_rental_on_same_booking
    """
    world = _actual_usage_settlement(api)

    booking = read_booking(api, world["booking"]["id"])
    assert_money_cents(booking["gross_rental_cents"], 363600, "gross_rental_cents")
    assert_money_cents(booking["contracted_rental_cents"], 363600, "contracted_rental_cents")

    settlement = read_settlement(api, world["settlement"]["id"])
    assert settlement["line_subtotal_cents"] != booking["contracted_rental_cents"], (
        "the actual-usage subtotal must not collapse onto the contracted rental"
    )


def _dispatched_cleaning_call(api: ApiClient):
    """An IN_HOUSE booking with a 3-person 06:00-10:30 cleaning call already dispatched."""
    world = setup_event_lifecycle(
        api,
        "in_house",
        space=dict(MEETING_ROOM_301),
        deposit_cents=200000,
    )
    local = register_union_local(api, **dict(SEIU_LOCAL_3))
    call = schedule_labor_call(
        api,
        world["booking"]["id"],
        local["id"],
        "CLEANING",
        "2027-03-01",
        6.0,
        10.5,
        3,
    )
    dispatch_labor_call(api, call["id"])
    world["union_local"] = local
    world["labor_call"] = call
    return world


def test_scheduled_estimate_prices_every_hour_at_straight_time(api: ApiClient):
    """A 06:00-10:30 call for three cleaners is estimated at 128696 cents.

    PRD: "The estimate prices every hour at straight time and never applies the
    overtime multiplier, no matter where the scheduled hours fall relative to the
    straight-time window."
    PRD: "A call's `billed_hours` is its `crew_size` multiplied by the greater of
    the local's `min_call_hours` and the call's own span — the scheduled span while
    the call is `SCHEDULED` or `DISPATCHED`, and the actual span once it is
    `ACTUALIZED`."

    Design: Difficulty/dual_variant_calc/actualized_union_labor_charge_diverges_from_scheduled_estimate
    """
    world = _dispatched_cleaning_call(api)

    call = read_labor_call(api, world["labor_call"]["id"])
    assert_money_cents(call["estimated_charge_cents"], 128696, "estimated_charge_cents")
    assert_crew_hours(call["billed_hours"], 13.5, "billed_hours")


def test_actualized_charge_splits_the_span_at_the_window_edge(api: ApiClient):
    """Working 06:00-12:30 splits into 4.5 straight-time and 2 overtime hours for 214493 cents.

    PRD: "`actual_charge_cents` is the sum of those three rounded integers."
    PRD: "Rounding each band before adding is binding; a single rounding of the
    summed real number is wrong."
    PRD: "The local's `committed_crew_hours` is the sum of `billed_hours` over its
    calls whose `status` is `SCHEDULED`, `DISPATCHED` or `ACTUALIZED`, and
    cancelled calls contribute nothing."

    Design: Difficulty/dual_variant_calc/actualized_union_labor_charge_diverges_from_scheduled_estimate
    """
    world = _dispatched_cleaning_call(api)

    actualize_labor_call(api, world["labor_call"]["id"], 6.0, 12.5)

    call = read_labor_call(api, world["labor_call"]["id"])
    assert_fields(call, status="ACTUALIZED")
    assert_money_cents(call["actual_charge_cents"], 214493, "actual_charge_cents")
    assert_crew_hours(call["billed_hours"], 19.5, "billed_hours")

    local = read_union_jurisdiction(api, world["union_local"]["id"])
    assert_crew_hours(local["committed_crew_hours"], 19.5, "committed_crew_hours")
