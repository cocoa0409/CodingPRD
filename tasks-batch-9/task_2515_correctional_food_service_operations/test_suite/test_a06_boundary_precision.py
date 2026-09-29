"""Inclusive-limit boundaries probed one unit either side.

The intermediate chill gate is inclusive on both a temperature and an elapsed
minute count; the waste allowance tier is chosen from `line_trays` alone and flips
between 500 and 501 trays.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import ApiClient, assertions, factories, fixtures
from test_helpers import test_users as users


# ---------------------------------------------------------------------------
# Intermediate chill gate: 80.0 degrees, 120 minutes
# ---------------------------------------------------------------------------


def _cooked_batch(api: ApiClient) -> dict:
    """A batch whose only reading so far is an in-range cook-end at ten o'clock,
    advanced onto the COOKED stage with ten trays produced."""
    ctx = fixtures.locked_forecast(
        api,
        contract_overrides={"contract_code": "CFS-2515-BP1"},
        facility_overrides={
            "facility_code": "FAC-BP1",
            "sharps_authorized_count": 12,
        },
    )
    ctx = fixtures.planned_batch(
        api,
        ctx,
        planned_trays=10,
        scheduled_cook_start_at="2026-08-01T06:00:00Z",
        service_site="MAIN_KITCHEN",
    )
    batch_id = ctx["batch"]["id"]

    fixtures.set_clock(api, "2026-08-01T10:00:00Z")
    cook_end = validate_success(
        api.post_temperature_log(
            batch_id,
            factories.temperature_log_payload("COOK_END", 170.0),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    assert cook_end["in_range"] is True
    assert cook_end["minutes_since_cook_end"] is None
    ctx["batch"] = validate_success(
        api.advance_stage(
            batch_id,
            factories.advance_stage_payload("COOKED", produced_trays=10),
            users.FOOD_SUPERVISOR,
        )
    )
    ctx["cook_end_reading"] = cook_end
    return ctx


def _chill_intermediate_at(api: ApiClient, batch_id: str, instant: str) -> dict:
    fixtures.set_clock(api, instant)
    return validate_success(
        api.post_temperature_log(
            batch_id,
            factories.temperature_log_payload("CHILL_INTERMEDIATE", 80.0),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )


def test_intermediate_chill_is_in_range_at_exactly_eighty_degrees_and_120_minutes(
    api: ApiClient,
) -> None:
    """Both limits are inclusive, so a reading sitting exactly on each passes.

    The PRD states: "`in_range` is then decided per control point, and every
    comparison is inclusive at its limit — exactly 80.0 degrees at exactly 120
    minutes is in range, while 80.1 degrees or 121 minutes is not", and specifies
    that "A `CHILL_INTERMEDIATE` reading is in range when `temperature_f` is at or
    below 80.0 **and** `minutes_since_cook_end` is at most 120."

    Design: Difficulty/boundary_precision_check/chill_intermediate_inclusive_at_exactly_120_minutes_and_80_0_degrees
    """
    ctx = _cooked_batch(api)
    batch_id = ctx["batch"]["id"]

    at_119 = _chill_intermediate_at(api, batch_id, "2026-08-01T11:59:00Z")
    assert at_119["minutes_since_cook_end"] == 119
    assert at_119["in_range"] is True

    at_120 = _chill_intermediate_at(api, batch_id, "2026-08-01T12:00:00Z")
    assert at_120["minutes_since_cook_end"] == 120
    assert at_120["in_range"] is True

    held_free = fixtures.read_batch(api, batch_id)
    assert held_free["qa_status"] == "QA_PENDING"
    assert held_free["qa_reason"] is None
    assert held_free["production_stage"] == "COOKED"


def test_one_minute_past_the_chill_window_falls_out_of_range_and_holds_the_batch(
    api: ApiClient,
) -> None:
    """At 121 minutes the identical temperature is out of range and the QA axis is
    pulled back, while the production axis stands still.

    The PRD states that "exactly 80.0 degrees at exactly 120 minutes is in range,
    while 80.1 degrees or 121 minutes is not", and that "an out-of-range
    `CHILL_INTERMEDIATE` or `CHILL_FINAL` reading moves `qa_status` to `QA_HELD` with
    `qa_reason` set to the literal string `CHILL_GATE_FAILED`". It also states that
    temperature readings "have no `updated_at` and no `version`".

    Design: Difficulty/boundary_precision_check/chill_intermediate_inclusive_at_exactly_120_minutes_and_80_0_degrees
    """
    ctx = _cooked_batch(api)
    batch_id = ctx["batch"]["id"]

    _chill_intermediate_at(api, batch_id, "2026-08-01T11:59:00Z")
    _chill_intermediate_at(api, batch_id, "2026-08-01T12:00:00Z")
    at_121 = _chill_intermediate_at(api, batch_id, "2026-08-01T12:01:00Z")

    assert at_121["minutes_since_cook_end"] == 121
    assert at_121["in_range"] is False
    assertions.assert_temperature_log(at_121)

    batch = fixtures.read_batch(api, batch_id)
    assert batch["qa_status"] == "QA_HELD"
    assert batch["qa_reason"] == "CHILL_GATE_FAILED"
    assert batch["production_stage"] == "COOKED"
    assert batch["chill_final_at"] is None
    assert batch["chill_minutes"] is None

    readings, meta = validate_paginated(
        api.list_temperature_logs(
            batch_id, users.FOOD_SUPERVISOR, {"log_point": "CHILL_INTERMEDIATE"}
        )
    )
    assert meta["total_count"] == 3
    for reading in readings:
        assertions.assert_versionless_entity(reading)


# ---------------------------------------------------------------------------
# Waste allowance tier: 500 versus 501 line trays
# ---------------------------------------------------------------------------


def _tier_boundary_context(api: ApiClient) -> dict:
    """Two population counts at the same facility: one landing the serving line on
    exactly 500 trays, the other one tray above."""
    ctx = fixtures.facility_with_active_cycle(
        api,
        contract_overrides={"contract_code": "CFS-2515-BP2"},
        facility_overrides={
            "facility_code": "FAC-BP2",
            "sharps_authorized_count": 12,
        },
    )
    facility_id = ctx["facility"]["id"]
    ctx["count_at_500"] = fixtures.create_population_count(
        api,
        facility_id,
        general_population=500,
        segregation_population=30,
        satellite_population=0,
        medical_population=0,
    )
    ctx["count_at_501"] = fixtures.create_population_count(
        api,
        facility_id,
        general_population=500,
        segregation_population=31,
        satellite_population=0,
        medical_population=0,
    )
    return ctx


def _forecast_from(api: ApiClient, ctx: dict, count: dict, meal_slot: str) -> dict:
    return validate_success(
        api.create_meal_forecast(
            factories.meal_forecast_payload(
                ctx["facility"]["id"],
                count["id"],
                service_date="2026-08-02",
                meal_slot=meal_slot,
                forecast_variant="COUNT_DRIVEN",
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )


def test_a_line_demand_of_exactly_500_trays_takes_the_flat_allowance(
    api: ApiClient,
) -> None:
    """The lowest tier is inclusive at 500 trays, so the allowance is the flat 8.

    The PRD states: "A line demand of 500 trays or fewer takes a flat allowance of 8
    trays." The serving line is 500 general heads at 94 percent rounded up, which is
    470 trays, plus 30 mandatory segregation trays, giving exactly 500.

    Design: Difficulty/boundary_precision_check/waste_allowance_tier_flips_between_line_trays_500_and_501
    """
    ctx = _tier_boundary_context(api)

    assert ctx["count_at_500"]["total_population"] == 530
    forecast = _forecast_from(api, ctx, ctx["count_at_500"], "BREAKFAST")

    assertions.assert_meal_forecast(forecast)
    assert forecast["line_trays"] == 500
    assert forecast["waste_allowance_trays"] == 8
    assert forecast["total_forecast_trays"] == 508
    assert forecast["forecast_special_diet_trays"] == 0
    assert forecast["status"] == "DRAFT"


def test_one_tray_above_the_boundary_switches_to_the_two_percent_allowance(
    api: ApiClient,
) -> None:
    """At 501 trays the middle tier applies and the allowance jumps from 8 to 11.

    The PRD states: "A line demand above 500 and up to 2000 takes 2 percent of
    `line_trays`, rounded up to a whole tray." It also states that "Because the tier
    is chosen from `line_trays` and never from the combined figure, the allowance can
    never feed back into its own tier selection." Two percent of 501 is 10.02,
    rounded up to 11, so the totals are 508 and 512 respectively.

    Design: Difficulty/boundary_precision_check/waste_allowance_tier_flips_between_line_trays_500_and_501
    """
    ctx = _tier_boundary_context(api)

    assert ctx["count_at_501"]["total_population"] == 531
    at_500 = _forecast_from(api, ctx, ctx["count_at_500"], "BREAKFAST")
    at_501 = _forecast_from(api, ctx, ctx["count_at_501"], "LUNCH")

    assert at_501["line_trays"] == 501
    assert at_501["waste_allowance_trays"] == 11
    assert at_501["total_forecast_trays"] == 512
    assert at_501["forecast_special_diet_trays"] == 0
    assert at_501["status"] == "DRAFT"

    assert at_501["line_trays"] - at_500["line_trays"] == 1
    assert at_501["waste_allowance_trays"] - at_500["waste_allowance_trays"] == 3
