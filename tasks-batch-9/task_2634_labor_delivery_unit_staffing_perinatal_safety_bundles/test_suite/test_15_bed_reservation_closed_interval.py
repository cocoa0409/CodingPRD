"""A bed reservation is a closed interval carrying the frozen buffer.

Three probes hit the same bed on the same day: one inside the existing hold's
frozen turnover buffer, one exactly touching its end, and one a single minute
clear. Only the last one is admitted.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_bed,
    assert_induction_booking,
    assert_instant_equals,
    assert_instant_is_null,
    assert_labor_encounter,
    assert_obstetric_unit,
    bootstrap_unit,
    capacity_sweep,
    confirm_booking,
    create_booking,
    get_success_data,
    hold_booking,
    reload_booking,
    reload_encounter,
    set_clock,
    setup_validated_drill,
)

CLOCK_START = "2026-08-20T06:00:00Z"
CLOCK_DOCUMENT = "2026-08-20T06:30:00Z"
CLOCK_ADMIT = "2026-08-20T07:30:00Z"
CLOCK_PROBE = "2026-08-20T09:00:00Z"
DRILL_SCHEDULED = "2026-08-20T06:05:00Z"
DRILL_INCISION = "2026-08-20T06:25:00Z"
INDUCTION_DAY = "2026-08-20"
ANCHOR_START = "2026-08-20T08:00:00Z"
PROBE_INSIDE_BUFFER = "2026-08-20T18:30:00Z"
PROBE_TOUCHING = "2026-08-20T18:45:00Z"
PROBE_CLEAR = "2026-08-20T18:46:00Z"
EXPECTED_PROBE_HOLD_EXPIRY = "2026-08-20T11:00:00Z"
ANCHOR_PROJECTION = 645
PROBE_PROJECTION = 165

OVERLAP_STAFF = {
    "charge": {
        "full_name": "Rosalind Achterberg RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
    },
    "ob": {
        "full_name": "Ignatius Ferreira MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
    },
    "anesthesia": {
        "full_name": "Beatrix Nyffenegger MD",
        "staff_role": "ANESTHESIOLOGIST",
        "fetal_monitoring_cert_level": "BASIC",
    },
    "officer": {
        "full_name": "Delphine Ravensworth RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "BASIC",
    },
}


def _probe_booking(world, code, requested_start_utc):
    return create_booking(
        world,
        patient_record_code=code,
        gestational_age_weeks=39,
        indication_code="GDM_CONTROLLED",
        requested_start_utc=requested_start_utc,
        expected_labor_minutes=120,
    )


@pytest.fixture
def three_probes_against_a_frozen_bed_window():
    """One ADMITTED booking still owns LDR-01's [08:00, 18:45] reservation while
    the bed itself has been cleared back to AVAILABLE."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=3,
        or_rooms=1,
        max_daily_induction_bed_minutes=20000,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR"), ("LDR-03", "LDR")],
        staff_specs=OVERLAP_STAFF,
        unit_overrides={"unit_name": "Torrance Bay Perinatal Center"},
    )
    setup_validated_drill(
        world,
        scheduled_for_utc=CLOCK_START,
        decision_at=DRILL_SCHEDULED,
        incision_at=DRILL_INCISION,
        document_clock=CLOCK_DOCUMENT,
    )
    anchor = create_booking(
        world,
        patient_record_code="PRC-IND-4180",
        gestational_age_weeks=39,
        indication_code="PREECLAMPSIA",
        requested_start_utc=ANCHOR_START,
        expected_labor_minutes=600,
    )
    held_anchor = hold_booking(world, anchor, "LDR-01")
    confirm_booking(world, anchor)
    set_clock(CLOCK_ADMIT)
    admitted_anchor = get_success_data(
        api_client.admit_booking(anchor["id"], world.charge_headers)
    )
    encounter_id = admitted_anchor["encounter_id"]
    get_success_data(
        api_client.transfer_out_encounter(encounter_id, {}, world.ob_headers)
    )
    set_clock(CLOCK_PROBE)
    sweep = capacity_sweep(world)
    bed_after_sweep = get_success_data(
        api_client.get_bed(world.bed_id("LDR-01"), world.charge_headers)
    )

    inside = _probe_booking(world, "PRC-IND-4181", PROBE_INSIDE_BUFFER)
    touching = _probe_booking(world, "PRC-IND-4182", PROBE_TOUCHING)
    clear = _probe_booking(world, "PRC-IND-4183", PROBE_CLEAR)
    unit_at_probe = world.reload_unit()

    def _hold(booking):
        return api_client.hold_capacity(
            booking["id"],
            {
                "bed_id": world.bed_id("LDR-01"),
                "expected_unit_version": unit_at_probe["version"],
            },
            world.access_headers,
        )

    inside_response = _hold(inside)
    touching_response = _hold(touching)
    clear_response = _hold(clear)
    return {
        "world": world,
        "anchor": anchor,
        "held_anchor": held_anchor,
        "encounter_id": encounter_id,
        "sweep": sweep,
        "bed_after_sweep": bed_after_sweep,
        "inside": inside,
        "touching": touching,
        "clear": clear,
        "inside_response": inside_response,
        "touching_response": touching_response,
        "clear_response": clear_response,
    }


def test_a_hold_inside_the_frozen_buffer_collides(
    three_probes_against_a_frozen_bed_window,
):
    """"For an existing hold on the same bed the window runs from its own
    `requested_start_utc` to that instant plus its frozen
    `projected_occupancy_minutes` — the frozen figure, not a freshly computed
    one." Labour ends at 18:00 but the reservation runs to 18:45.

    Design: Difficulty/resource_temporal_overlap/bed_hold_collides_inside_the_frozen_buffer_and_on_the_touching_endpoint_but_admits_one_minute_later
    """
    setup = three_probes_against_a_frozen_bed_window
    assert setup["held_anchor"]["projected_occupancy_minutes"] == ANCHOR_PROJECTION
    response = setup["inside_response"]
    validate_error(response, ApiErrorId.ERR_BED_TURNOVER_CONFLICT.value, 409)
    code = response.json()["data"]["error_id"]
    assert code != ApiErrorId.ERR_INDUCTION_CAPACITY_EXCEEDED.value
    assert code != ApiErrorId.ERR_BED_NOT_RELEASABLE.value


def test_a_hold_touching_the_existing_end_collides(
    three_probes_against_a_frozen_bed_window,
):
    """"Touching endpoints therefore do collide: a hold that would begin at the
    exact minute an earlier reservation is projected to release the bed is
    refused with `ERR_BED_TURNOVER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/bed_hold_collides_inside_the_frozen_buffer_and_on_the_touching_endpoint_but_admits_one_minute_later
    """
    validate_error(
        three_probes_against_a_frozen_bed_window["touching_response"],
        ApiErrorId.ERR_BED_TURNOVER_CONFLICT.value,
        409,
    )


def test_a_hold_one_minute_clear_is_admitted(three_probes_against_a_frozen_bed_window):
    """"For a new hold the window runs from `requested_start_utc` to that instant
    plus `expected_labor_minutes`" — no buffer on the new side, so a start one
    minute past 18:45 clears the existing window entirely.

    Design: Difficulty/resource_temporal_overlap/bed_hold_collides_inside_the_frozen_buffer_and_on_the_touching_endpoint_but_admits_one_minute_later
    """
    setup = three_probes_against_a_frozen_bed_window
    booking = get_success_data(setup["clear_response"])
    assert_induction_booking(booking)
    assert booking["status"] == "CAPACITY_HELD"
    assert booking["priority_class"] == "ELECTIVE_39_WEEK"
    assert booking["bed_id"] == setup["world"].bed_id("LDR-01")
    assert booking["projected_occupancy_minutes"] == PROBE_PROJECTION
    assert_instant_equals(
        booking["hold_expires_at"], EXPECTED_PROBE_HOLD_EXPIRY, "hold_expires_at"
    )


def test_the_two_refused_probes_reserved_nothing(
    three_probes_against_a_frozen_bed_window,
):
    """A refused hold never reaches the moment "`projected_occupancy_minutes` is
    frozen", so both probes are still `REQUESTED` on their opening version with
    no bed and no projection.

    Design: Difficulty/resource_temporal_overlap/bed_hold_collides_inside_the_frozen_buffer_and_on_the_touching_endpoint_but_admits_one_minute_later
    """
    setup = three_probes_against_a_frozen_bed_window
    for key in ("inside", "touching"):
        booking = reload_booking(setup["world"], setup[key]["id"])
        assert_induction_booking(booking)
        assert booking["status"] == "REQUESTED"
        assert booking["bed_id"] is None
        assert booking["projected_occupancy_minutes"] is None
        assert_instant_is_null(booking["hold_expires_at"], "hold_expires_at")
        assert booking["version"] == 1


def test_the_bed_was_genuinely_available_before_the_probes(
    three_probes_against_a_frozen_bed_window,
):
    """The sweep "clears beds in `TURNOVER` whose `turnover_clear_at` is at or
    before the current instant, returning them to `AVAILABLE`", so the collision
    cannot be the bed lifecycle standing in for the interval rule.

    Design: Difficulty/resource_temporal_overlap/bed_hold_collides_inside_the_frozen_buffer_and_on_the_touching_endpoint_but_admits_one_minute_later
    """
    setup = three_probes_against_a_frozen_bed_window
    bed = setup["bed_after_sweep"]
    assert_bed(bed)
    assert bed["status"] == "AVAILABLE"
    assert bed["held_booking_id"] is None
    assert bed["current_encounter_id"] is None
    encounter = reload_encounter(setup["world"], setup["encounter_id"])
    assert_labor_encounter(encounter)
    assert encounter["labor_phase"] == "TRANSFERRED_OUT"
    assert encounter["bed_id"] is None


def test_the_admitted_booking_still_owns_the_window(
    three_probes_against_a_frozen_bed_window,
):
    """"The committed minutes stay committed, since `CONFIRMED` and `ADMITTED`
    both count against the day" — the anchor keeps its status, its bed reference
    and its frozen 645, which is what keeps its window in force.

    Design: Difficulty/resource_temporal_overlap/bed_hold_collides_inside_the_frozen_buffer_and_on_the_touching_endpoint_but_admits_one_minute_later
    """
    setup = three_probes_against_a_frozen_bed_window
    world = setup["world"]
    anchor = reload_booking(world, setup["anchor"]["id"])
    assert_induction_booking(anchor)
    assert anchor["status"] == "ADMITTED"
    assert anchor["bed_id"] == world.bed_id("LDR-01")
    assert anchor["projected_occupancy_minutes"] == ANCHOR_PROJECTION
    unit = world.reload_unit()
    assert_obstetric_unit(unit)
    assert unit["committed_bed_minutes_by_day"].get(INDUCTION_DAY, 0) == ANCHOR_PROJECTION
    assert unit["held_bed_minutes_by_day"].get(INDUCTION_DAY, 0) == PROBE_PROJECTION
    assert unit["staffing_posture"] == "OPEN"
    assert unit["turnover_buffer_minutes"] == 45


def test_the_bed_ends_up_held_by_the_clear_probe(
    three_probes_against_a_frozen_bed_window,
):
    """The one admitted hold is the one that moved "The booking moves `REQUESTED` to `CAPACITY_HELD`, the named `LDR` bed moves
    `AVAILABLE` to `HELD` with `held_booking_id` written, and `hold_expires_at` is
    set to the current instant plus 120 minutes.".

    Design: Difficulty/resource_temporal_overlap/bed_hold_collides_inside_the_frozen_buffer_and_on_the_touching_endpoint_but_admits_one_minute_later
    """
    setup = three_probes_against_a_frozen_bed_window
    world = setup["world"]
    bed = get_success_data(api_client.get_bed(world.bed_id("LDR-01"), world.charge_headers))
    assert_bed(bed)
    assert bed["status"] == "HELD"
    assert bed["held_booking_id"] == setup["clear"]["id"]
    assert bed["current_encounter_id"] is None
