"""The pinned order: posture, then buffer, then the frozen bed-minute projection."""

import pytest

from test_helpers import (
    api_client,
    bootstrap_unit,
    create_booking,
    create_encounter,
    get_success_data,
    hold_booking,
    lift_unit_off_not_ready,
    reload_booking,
    reload_encounter,
)

INDUCTION_DAY = "2026-08-05"


@pytest.fixture
def two_holds_frozen_under_different_buffers():
    """One hold placed while the unit is OPEN and a second placed after an
    uncovered walk-in has strained it."""
    world = bootstrap_unit(
        clock="2026-08-04T09:00:00Z",
        ldr_beds=3,
        or_rooms=1,
        max_daily_induction_bed_minutes=1400,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR"), ("LDR-03", "LDR")],
        staff_specs={
            "charge": {
                "staff_role": "RN_LABOR_DELIVERY",
                "fetal_monitoring_cert_level": "ADVANCED",
                "credential_expires_at": "2027-06-30T00:00:00Z",
            }
        },
    )
    lift_unit_off_not_ready(world, "2026-08-04T09:00:00Z")
    unit_while_open = world.reload_unit()

    booking_open = create_booking(
        world,
        gestational_age_weeks=41,
        indication_code="POST_DATES_41W",
        requested_start_utc="2026-08-05T08:00:00Z",
        expected_labor_minutes=600,
    )
    booking_open = hold_booking(world, booking_open, "LDR-01")

    walk_in = create_encounter(world, parity=0, gestational_age_weeks=39)
    unit_while_strained = world.reload_unit()

    booking_strained = create_booking(
        world,
        gestational_age_weeks=37,
        indication_code="PREECLAMPSIA",
        requested_start_utc="2026-08-05T20:00:00Z",
        expected_labor_minutes=600,
    )
    booking_strained = hold_booking(world, booking_strained, "LDR-02")

    return {
        "world": world,
        "unit_while_open": unit_while_open,
        "unit_while_strained": unit_while_strained,
        "booking_open": booking_open,
        "booking_strained": booking_strained,
        "walk_in": reload_encounter(world, walk_in["id"]),
    }


@pytest.fixture
def first_hold_cancelled(two_holds_frozen_under_different_buffers):
    """Cancel the hold that froze under the 45-minute buffer."""
    state = two_holds_frozen_under_different_buffers
    world = state["world"]
    state["cancelled"] = get_success_data(
        api_client.cancel_booking(
            state["booking_open"]["id"], world.access_headers
        )
    )
    state["unit_after_cancel"] = world.reload_unit()
    return state


def test_a_hold_on_an_open_unit_freezes_the_forty_five_minute_buffer(
    two_holds_frozen_under_different_buffers,
):
    """While the unit is OPEN the buffer is 45, so a 600-minute labour projection
    freezes at 645.

    PRD 3.5: "This is also the moment `projected_occupancy_minutes` is frozen, as
    `expected_labor_minutes` plus the unit's current `turnover_buffer_minutes`,
    and that frozen integer is the exact quantum every later credit and debit
    moves."

    Design: Difficulty/combinatorial_formula/posture_buffer_projection_cycle_pinned_order_freezes_645_beside_675
    """
    state = two_holds_frozen_under_different_buffers
    assert state["unit_while_open"]["staffing_posture"] == "OPEN"
    assert state["unit_while_open"]["turnover_buffer_minutes"] == 45
    assert state["booking_open"]["projected_occupancy_minutes"] == 645
    assert state["booking_open"]["status"] == "CAPACITY_HELD"


def test_the_buffer_is_derived_after_the_posture_and_never_feeds_back_into_it(
    two_holds_frozen_under_different_buffers,
):
    """An uncovered walk-in worth 0.5 units strains the unit, and only then does
    the buffer move to 75.

    PRD 3.3: "After the posture is settled, and only then,
    `turnover_buffer_minutes` is set to 45 when the posture is `OPEN` and 75
    otherwise."

    Design: Difficulty/combinatorial_formula/posture_buffer_projection_cycle_pinned_order_freezes_645_beside_675
    """
    state = two_holds_frozen_under_different_buffers
    unit = state["unit_while_strained"]
    assert unit["coverage_deficit_units"] == pytest.approx(0.5, abs=0.01)
    assert unit["staffing_posture"] == "RATIO_STRAINED"
    assert unit["turnover_buffer_minutes"] == 75
    assert state["walk_in"]["required_coverage_units"] == pytest.approx(0.5, abs=0.01)
    assert state["walk_in"]["assigned_coverage_units"] == pytest.approx(0.0, abs=0.01)


def test_the_second_hold_on_the_same_day_freezes_the_seventy_five_minute_buffer(
    two_holds_frozen_under_different_buffers,
):
    """The same 600-minute labour projection freezes at 675 once the strained
    buffer is in force, so two holds on one day carry different quanta.

    PRD 3.5: "The day's `held_bed_minutes_by_day` entry for the UTC date of
    `requested_start_utc` is increased by it."

    Design: Difficulty/combinatorial_formula/posture_buffer_projection_cycle_pinned_order_freezes_645_beside_675
    """
    state = two_holds_frozen_under_different_buffers
    assert state["booking_strained"]["projected_occupancy_minutes"] == 675
    held = state["world"].reload_unit()["held_bed_minutes_by_day"]
    assert held[INDUCTION_DAY] == 1320


def test_both_indications_derive_the_medically_indicated_priority_class(
    two_holds_frozen_under_different_buffers,
):
    """Post-dates and pre-eclampsia are both medical indications regardless of
    gestational age.

    PRD 3.5: "It is `MEDICALLY_INDICATED` when `indication_code` is
    `PREECLAMPSIA`, `POST_DATES_41W`, `FGR` or `PROM`."

    Design: Difficulty/combinatorial_formula/posture_buffer_projection_cycle_pinned_order_freezes_645_beside_675
    """
    state = two_holds_frozen_under_different_buffers
    assert state["booking_open"]["priority_class"] == "MEDICALLY_INDICATED"
    assert state["booking_strained"]["priority_class"] == "MEDICALLY_INDICATED"


def test_cancelling_credits_back_exactly_the_frozen_figure(first_hold_cancelled):
    """The cancellation returns 645 rather than a figure recomputed from the
    current 75-minute buffer, leaving 675 on the day.

    PRD 2.10: "A booking's `projected_occupancy_minutes` is frozen when its
    capacity hold is placed, and every later credit or debit of the day's
    bed-minute budget moves exactly that frozen figure, so that a change in the
    unit's turnover buffer between hold and release cannot leave the budget
    drifting."

    Design: Difficulty/combinatorial_formula/posture_buffer_projection_cycle_pinned_order_freezes_645_beside_675
    """
    unit = first_hold_cancelled["unit_after_cancel"]
    assert unit["held_bed_minutes_by_day"][INDUCTION_DAY] == 675
    assert unit["committed_bed_minutes_by_day"].get(INDUCTION_DAY, 0) == 0
    assert unit["turnover_buffer_minutes"] == 75


def test_cancelling_releases_the_bed_and_leaves_the_other_hold_alone(
    first_hold_cancelled,
):
    """The cancelled booking's bed returns to AVAILABLE with its hold pointer
    cleared, while the surviving hold keeps its own bed.

    PRD 3.5: "A cancellation, also a `PatientAccessCoordinator` act, is available
    from `REQUESTED`, `CAPACITY_HELD` or `CONFIRMED`, releases any held bed and
    credits back exactly `projected_occupancy_minutes`; an `ADMITTED` booking can
    never be cancelled, and the attempt is refused with
    `ERR_INDUCTION_ALREADY_ADMITTED`."

    Design: Difficulty/combinatorial_formula/posture_buffer_projection_cycle_pinned_order_freezes_645_beside_675
    """
    state = first_hold_cancelled
    world = state["world"]
    cancelled = reload_booking(world, state["booking_open"]["id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["bed_id"] is None

    released_bed = get_success_data(
        api_client.get_bed(world.bed_id("LDR-01"), world.charge_headers)
    )
    assert released_bed["status"] == "AVAILABLE"
    assert released_bed["held_booking_id"] is None

    still_held = get_success_data(
        api_client.get_bed(world.bed_id("LDR-02"), world.charge_headers)
    )
    assert still_held["status"] == "HELD"
    assert still_held["held_booking_id"] == state["booking_strained"]["id"]
    assert reload_booking(world, state["booking_strained"]["id"])["status"] == "CAPACITY_HELD"
