"""Forecast projection against day-close reconciliation.

The projection reads the room-type inventory mix; the reconciliation reads the
work actually performed.  The two readings are deliberately different numbers.
"""

from test_helpers import (
    DEFAULT_BUSINESS_DATE,
    DIRECTOR_HEADERS,
    FORECAST_CLOSED,
    ASSIGN_INSPECTED_PASS,
    OCCUPANCY_DUE_OUT,
    SERVICE_CHECKOUT,
    SERVICE_DEEP_CLEAN,
    assert_credits,
    assert_variance_pct,
    build_scenario,
    close_day,
    forecast_day_payload,
    read_assignment,
    read_property,
    validate_paginated,
    validate_success,
)


def _mixed_inventory_day(api):
    """Three KING rooms and one SUITE, with two departures cleaned and one deep clean."""
    scenario = build_scenario(
        api,
        room_type_codes=("KING", "SUITE"),
        rooms=[
            {"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT},
            {"number": "102", "occupancy_state": OCCUPANCY_DUE_OUT},
            "103",
            ("201", "SUITE"),
        ],
        linen={"total_owned_sets": 20},
        forecast={
            "forecast_occupied_rooms": 4,
            "forecast_arrivals": 1,
            "forecast_departures": 2,
            "planned_deep_clean_rooms": 1,
        },
    )
    first = scenario.clean(
        "101",
        SERVICE_CHECKOUT,
        "2026-08-03T10:00:00.000Z",
        "2026-08-03T10:30:00.000Z",
    )
    scenario.clean(
        "102",
        SERVICE_CHECKOUT,
        "2026-08-03T10:50:00.000Z",
        "2026-08-03T11:20:00.000Z",
    )
    scenario.clean(
        "103",
        SERVICE_DEEP_CLEAN,
        "2026-08-03T11:40:00.000Z",
        "2026-08-03T12:10:00.000Z",
    )
    scenario.inspect(first["id"])
    scenario.close_roster(400, 20)
    return scenario, first


def test_day_close_reconciles_performed_credits_against_the_inventory_projection(api):
    """The closed day carries both readings of the same demand quantity, and they diverge.

    PRD 3.2: "Where the projection derived demand from the inventory mix, the
    reconciliation derives it from the work actually performed: it sums the
    `credits` of every room assignment sitting on a roster of this day whose
    `status` is `COMPLETED`, `INSPECTED_PASS` or `RECLEAN_REQUIRED`, and rounds
    that sum half up to two decimals."

    Design: Difficulty/dual_variant_calc/forecast_projected_inventory_mix_versus_actual_reconciled_credits
    """
    scenario, _ = _mixed_inventory_day(api)

    day = close_day(api, scenario.day_id)

    assert_credits(day["projected_required_credits"], 6.76, "projected_required_credits")
    assert_credits(day["actual_reconciled_credits"], 4.00, "actual_reconciled_credits")
    assert day["actual_reconciled_credits"] != day["projected_required_credits"], (
        "the inventory-mix projection and the performed-work reconciliation must "
        "be two different readings of the day"
    )
    assert day["status"] == FORECAST_CLOSED


def test_day_close_variance_is_signed_against_the_projection_and_leaves_the_pass_counted(api):
    """The signed variance is measured against the projection, and an inspected pass still counts.

    PRD 3.2: "The close finally writes `credit_variance_pct`, the signed
    percentage by which reality diverged from plan: `actual_reconciled_credits`
    minus `projected_required_credits`, divided by
    `projected_required_credits`, multiplied by 100, and rounded half up to two
    decimals."

    Design: Difficulty/dual_variant_calc/forecast_projected_inventory_mix_versus_actual_reconciled_credits
    """
    scenario, first = _mixed_inventory_day(api)

    day = close_day(api, scenario.day_id)

    assert_variance_pct(day["credit_variance_pct"], -40.83)
    assert day["required_attendants"] == 1, (
        f"required_attendants should be 1, got {day['required_attendants']}"
    )
    inspected = read_assignment(api, first["id"])
    assert inspected["status"] == ASSIGN_INSPECTED_PASS
    assert_credits(inspected["credits"], 1.00, "inspected assignment credits")


def test_forecast_projection_rounds_each_room_type_before_summing(api):
    """Per-type rounding before the final sum yields 6.76, not the 6.75 of a single rounding.

    PRD 3.2: "Iterate the property's room types in ascending order of `code`;
    round **each** room type's raw credit demand half up to two decimal places;
    and only then add the rounded per-type figures together, rounding that sum
    half up to two decimals one final time."

    Design: Difficulty/combinatorial_formula/forecast_credits_round_per_room_type_before_summing
    """
    scenario = build_scenario(
        api,
        room_type_codes=("KING", "SUITE"),
        rooms=["101", "102", "103", ("201", "SUITE")],
        with_worker=False,
        with_inspector=False,
        with_day=False,
        with_roster=False,
    )

    day = validate_success(
        api.create_forecast_day(
            forecast_day_payload(
                scenario.property_id,
                forecast_occupied_rooms=4,
                forecast_arrivals=1,
                forecast_departures=2,
                planned_deep_clean_rooms=1,
            ),
            DIRECTOR_HEADERS,
        ),
        201,
    )

    assert_credits(day["projected_required_credits"], 6.76, "projected_required_credits")
    assert day["projected_required_credits"] != 6.75, (
        "adding the raw per-type figures and rounding once at the end is the "
        "rejected reading"
    )
    assert day["business_date"] == DEFAULT_BUSINESS_DATE


def test_forecast_headcount_reads_the_inventory_mix_that_produced_the_projection(api):
    """The headcount is derived from the projection the same inventory mix produced.

    PRD 3.2: "Each room type of the property then takes a share of all three
    figures equal to that type's `room_count` divided by the property's
    `total_rooms`; this share is an exact rational and is never rounded."

    Design: Difficulty/combinatorial_formula/forecast_credits_round_per_room_type_before_summing
    """
    scenario = build_scenario(
        api,
        room_type_codes=("KING", "SUITE"),
        rooms=["101", "102", "103", ("201", "SUITE")],
        with_worker=False,
        with_inspector=False,
        with_day=False,
        with_roster=False,
    )

    day = validate_success(
        api.create_forecast_day(
            forecast_day_payload(
                scenario.property_id,
                forecast_occupied_rooms=4,
                forecast_arrivals=1,
                forecast_departures=2,
                planned_deep_clean_rooms=1,
            ),
            DIRECTOR_HEADERS,
        ),
        201,
    )

    assert day["required_attendants"] == 1, (
        f"required_attendants should be 1, got {day['required_attendants']}"
    )
    types, _ = validate_paginated(
        api.list_room_types({"property_id": scenario.property_id}, DIRECTOR_HEADERS)
    )
    by_code = {row["code"]: row for row in types}
    assert by_code["KING"]["room_count"] == 3, "KING should carry three rooms"
    assert by_code["SUITE"]["room_count"] == 1, "SUITE should carry one room"
    assert read_property(api, scenario.property_id)["total_rooms"] == 4
