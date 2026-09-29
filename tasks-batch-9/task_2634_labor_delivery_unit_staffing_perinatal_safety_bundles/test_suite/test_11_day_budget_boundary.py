"""The day bed-minute budget is an inclusive ceiling.

The same booking, the same bed and the same day are held twice, with nothing
moving between the two attempts except the unit's budget: one minute below the
day's projected load the hold is refused, and landing exactly on the budget the
identical hold is admitted.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_bed,
    assert_induction_booking,
    assert_instant_equals,
    assert_obstetric_unit,
    bootstrap_unit,
    create_booking,
    get_success_data,
    hold_booking,
    lift_unit_off_not_ready,
    reload_booking,
)

CLOCK_NOW = "2026-08-19T07:00:00Z"
INDUCTION_DAY = "2026-08-20"
REQUESTED_START = "2026-08-20T06:00:00Z"
EXPECTED_HOLD_EXPIRY = "2026-08-19T09:00:00Z"

GENEROUS_BUDGET = 2000
BUDGET_ONE_SHORT = 1289
BUDGET_EXACT = 1290
FROZEN_PROJECTION = 645


def _patch_budget(world, minutes):
    return get_success_data(
        api_client.patch_unit(
            world.unit_id,
            {"max_daily_induction_bed_minutes": minutes},
            world.officer_headers,
        )
    )


QUIET_STAFF = {
    "charge": {"staff_role": "RN_LABOR_DELIVERY", "fetal_monitoring_cert_level": "ADVANCED"},
    "officer": {"staff_role": "RN_LABOR_DELIVERY", "fetal_monitoring_cert_level": "BASIC"},
}


@pytest.fixture
def budget_walked_across_the_boundary():
    """Two identical 645-minute holds on the same day, with the budget moved
    from 1289 to 1290 between the two attempts on the second one."""
    world = bootstrap_unit(
        clock=CLOCK_NOW,
        ldr_beds=4,
        or_rooms=1,
        max_daily_induction_bed_minutes=GENEROUS_BUDGET,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR"), ("LDR-03", "LDR")],
        staff_specs=QUIET_STAFF,
        unit_overrides={"unit_name": "Pemberley Heights Perinatal"},
    )
    lift_unit_off_not_ready(world, CLOCK_NOW)
    booking_a = create_booking(
        world,
        patient_record_code="PRC-EDGE-A17",
        gestational_age_weeks=38,
        indication_code="PREECLAMPSIA",
        requested_start_utc=REQUESTED_START,
        expected_labor_minutes=600,
    )
    booking_b = create_booking(
        world,
        patient_record_code="PRC-EDGE-B24",
        gestational_age_weeks=39,
        indication_code="PREECLAMPSIA",
        requested_start_utc=REQUESTED_START,
        expected_labor_minutes=600,
    )
    unit_before = world.reload_unit()
    held_a = hold_booking(world, booking_a, "LDR-01", expected_unit_version=unit_before["version"])

    unit_under = _patch_budget(world, BUDGET_ONE_SHORT)
    refused = api_client.hold_capacity(
        booking_b["id"],
        {"bed_id": world.bed_id("LDR-02"), "expected_unit_version": unit_under["version"]},
        world.access_headers,
    )
    unit_after_refusal = world.reload_unit()
    booking_b_after_refusal = reload_booking(world, booking_b["id"])
    bed_2_after_refusal = get_success_data(
        api_client.get_bed(world.bed_id("LDR-02"), world.charge_headers)
    )

    unit_exact = _patch_budget(world, BUDGET_EXACT)
    admitted = api_client.hold_capacity(
        booking_b["id"],
        {"bed_id": world.bed_id("LDR-02"), "expected_unit_version": unit_exact["version"]},
        world.access_headers,
    )
    return {
        "world": world,
        "booking_a": booking_a,
        "booking_b": booking_b,
        "held_a": held_a,
        "unit_before": unit_before,
        "unit_under": unit_under,
        "unit_exact": unit_exact,
        "refused": refused,
        "admitted": admitted,
        "unit_after_refusal": unit_after_refusal,
        "booking_b_after_refusal": booking_b_after_refusal,
        "bed_2_after_refusal": bed_2_after_refusal,
    }


def test_the_hold_is_refused_one_minute_below_the_boundary(
    budget_walked_across_the_boundary,
):
    """"the day's existing load, meaning that date's committed minutes plus its
    held minutes, plus the new projection, must be no greater than
    `max_daily_induction_bed_minutes`, with the boundary allowed and an excess
    refused as `ERR_INDUCTION_CAPACITY_EXCEEDED`" — 645 + 645 is one minute over
    a budget of 1289.

    Design: Difficulty/boundary_precision_check/day_bed_minute_budget_rejects_1290_against_1289_and_admits_1290_against_1290
    """
    setup = budget_walked_across_the_boundary
    assert setup["unit_under"]["max_daily_induction_bed_minutes"] == BUDGET_ONE_SHORT
    validate_error(
        setup["refused"], ApiErrorId.ERR_INDUCTION_CAPACITY_EXCEEDED.value, 409
    )


def test_the_identical_hold_is_admitted_landing_on_the_budget(
    budget_walked_across_the_boundary,
):
    """"The booking moves `REQUESTED` to `CAPACITY_HELD`, the named `LDR` bed
    moves `AVAILABLE` to `HELD` with `held_booking_id` written, and
    `hold_expires_at` is set to the current instant plus 120 minutes."

    Design: Difficulty/boundary_precision_check/day_bed_minute_budget_rejects_1290_against_1289_and_admits_1290_against_1290
    """
    setup = budget_walked_across_the_boundary
    assert setup["unit_exact"]["max_daily_induction_bed_minutes"] == BUDGET_EXACT
    booking = get_success_data(setup["admitted"])
    assert_induction_booking(booking)
    assert booking["status"] == "CAPACITY_HELD"
    assert booking["priority_class"] == "MEDICALLY_INDICATED"
    assert booking["bed_id"] == setup["world"].bed_id("LDR-02")
    assert_instant_equals(booking["hold_expires_at"], EXPECTED_HOLD_EXPIRY, "hold_expires_at")


def test_the_frozen_projection_is_labor_minutes_plus_the_current_buffer(
    budget_walked_across_the_boundary,
):
    """"This is also the moment `projected_occupancy_minutes` is frozen, as
    `expected_labor_minutes` plus the unit's current `turnover_buffer_minutes`" —
    600 plus the 45 a quiet unit carries, never the bare 600 and never the
    DIVERT buffer of 75.

    Design: Difficulty/boundary_precision_check/day_bed_minute_budget_rejects_1290_against_1289_and_admits_1290_against_1290
    """
    setup = budget_walked_across_the_boundary
    assert setup["unit_before"]["turnover_buffer_minutes"] == 45
    assert setup["held_a"]["projected_occupancy_minutes"] == FROZEN_PROJECTION
    booking_b = reload_booking(setup["world"], setup["booking_b"]["id"])
    assert booking_b["projected_occupancy_minutes"] == FROZEN_PROJECTION
    assert booking_b["expected_labor_minutes"] == 600


def test_the_day_ledger_lands_exactly_on_the_budget(
    budget_walked_across_the_boundary,
):
    """"The day's `held_bed_minutes_by_day` entry for the UTC date of
    `requested_start_utc` is increased by it." Two 645-minute holds fill a
    1290-minute budget to the last minute, and no minute is committed.

    Design: Difficulty/boundary_precision_check/day_bed_minute_budget_rejects_1290_against_1289_and_admits_1290_against_1290
    """
    unit = budget_walked_across_the_boundary["world"].reload_unit()
    assert_obstetric_unit(unit)
    assert unit["max_daily_induction_bed_minutes"] == BUDGET_EXACT
    assert unit["held_bed_minutes_by_day"].get(INDUCTION_DAY, 0) == 2 * FROZEN_PROJECTION
    assert unit["committed_bed_minutes_by_day"].get(INDUCTION_DAY, 0) == 0
    assert unit["turnover_buffer_minutes"] == 45


def test_the_refusal_reserved_nothing_at_all(budget_walked_across_the_boundary):
    """"Bookings in `REQUESTED`, `BUMPED`, `CANCELLED` and `EXPIRED` all
    contribute zero minutes to both ledgers" — so between the two attempts the
    second booking is still `REQUESTED`, the day still carries only the first
    hold's 645, and the named bed is still free.

    Design: Difficulty/boundary_precision_check/day_bed_minute_budget_rejects_1290_against_1289_and_admits_1290_against_1290
    """
    setup = budget_walked_across_the_boundary
    booking = setup["booking_b_after_refusal"]
    assert booking["status"] == "REQUESTED"
    assert booking["projected_occupancy_minutes"] is None
    assert booking["bed_id"] is None
    unit = setup["unit_after_refusal"]
    assert unit["held_bed_minutes_by_day"].get(INDUCTION_DAY, 0) == FROZEN_PROJECTION
    assert unit["committed_bed_minutes_by_day"].get(INDUCTION_DAY, 0) == 0
    bed = setup["bed_2_after_refusal"]
    assert_bed(bed)
    assert bed["status"] == "AVAILABLE"
    assert bed["held_booking_id"] is None


def test_the_third_bed_keeps_the_unit_out_of_divert(
    budget_walked_across_the_boundary,
):
    """"`DIVERT` when the deficit is 8.0 or greater, or no `LDR` bed is
    available" — a third LDR bed stays `AVAILABLE` through both holds, so the
    posture that gates a hold never moves and cannot explain either outcome.

    Design: Difficulty/boundary_precision_check/day_bed_minute_budget_rejects_1290_against_1289_and_admits_1290_against_1290
    """
    setup = budget_walked_across_the_boundary
    world = setup["world"]
    beds = {
        label: get_success_data(api_client.get_bed(world.bed_id(label), world.charge_headers))
        for label in ("LDR-01", "LDR-02", "LDR-03")
    }
    for bed in beds.values():
        assert_bed(bed)
    assert beds["LDR-01"]["status"] == "HELD"
    assert beds["LDR-01"]["held_booking_id"] == setup["booking_a"]["id"]
    assert beds["LDR-02"]["status"] == "HELD"
    assert beds["LDR-02"]["held_booking_id"] == setup["booking_b"]["id"]
    assert beds["LDR-03"]["status"] == "AVAILABLE"
    unit = world.reload_unit()
    assert unit["staffing_posture"] == "OPEN"
    assert unit["coverage_deficit_units"] == pytest.approx(0.0, abs=1e-9)
