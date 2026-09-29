"""The two encounter state axes move independently.

`labor_phase` walks forward while `staffing_state` cycles
RATIO_COVERED -> COVERAGE_BREACH -> RATIO_COVERED underneath it, and the same
encounter is re-priced at every phase stop because the phase multiplier moves.
"""

import pytest

from test_helpers import (
    advance_phase,
    api_client,
    assert_care_assignment,
    assert_labor_encounter,
    assert_obstetric_unit,
    assert_shift_assignment,
    assign_bed,
    bootstrap_unit,
    create_active_shift,
    create_assessment,
    create_care_assignment,
    create_encounter,
    get_success_data,
    lift_unit_off_not_ready,
    reload_encounter,
    set_clock,
)

SHIFT_START = "2026-08-10T06:00:00Z"
SHIFT_END = "2026-08-10T16:00:00Z"

AXIS_STAFF = {
    "charge": {"staff_role": "RN_LABOR_DELIVERY", "fetal_monitoring_cert_level": "ADVANCED"},
    "bedside": {"staff_role": "RN_LABOR_DELIVERY", "fetal_monitoring_cert_level": "ADVANCED"},
}


@pytest.fixture
def encounter_walked_up_two_phases_through_two_breaches():
    """Drive one encounter ANTEPARTUM -> LATENT -> ACTIVE_FIRST_STAGE while the
    coverage axis is breached and repaired once inside each of the two phases.

    An ADVANCED nurse in the BEDSIDE slot freezes capacity at 4.0, so every
    successive shared debit fits and no capacity refusal can mask the shape.
    The encounter is NTSV-eligible, so it starts at TIER_I and only the phase
    multiplier moves the price until ACTIVE_FIRST_STAGE lifts the tier.
    """
    world = bootstrap_unit(
        clock="2026-08-10T07:00:00Z",
        ldr_beds=3,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR")],
        staff_specs=AXIS_STAFF,
    )
    lift_unit_off_not_ready(world, "2026-08-10T07:00:00Z")
    create_active_shift(world, "charge", "CHARGE", SHIFT_START, SHIFT_END)
    bedside_shift = create_active_shift(world, "bedside", "BEDSIDE", SHIFT_START, SHIFT_END)

    encounter = create_encounter(
        world,
        parity=0,
        gestational_age_weeks=39,
        prior_cesarean=False,
        fetus_count=1,
        presentation="VERTEX",
    )
    assign_bed(world, encounter, "LDR-01")

    version_1 = reload_encounter(world, encounter["id"])["version"]
    first_row = create_care_assignment(
        world, encounter, bedside_shift, expected_encounter_version=version_1
    )

    set_clock("2026-08-10T07:05:00Z")
    advance_phase(world, encounter, "LATENT")
    get_success_data(
        api_client.release_care_assignment(first_row["id"], world.charge_headers)
    )
    after_first_release = reload_encounter(world, encounter["id"])

    second_row = create_care_assignment(
        world,
        encounter,
        bedside_shift,
        expected_encounter_version=after_first_release["version"],
    )

    set_clock("2026-08-10T07:10:00Z")
    create_assessment(
        world,
        encounter,
        interpreted_key="charge",
        acting_key="charge",
        category="CATEGORY_I",
        baseline_rate_bpm=141,
        variability="MODERATE",
        recurrent_decelerations=False,
        assessed_at="2026-08-10T07:10:00Z",
    )

    set_clock("2026-08-10T07:15:00Z")
    advance_phase(world, encounter, "ACTIVE_FIRST_STAGE")
    get_success_data(
        api_client.release_care_assignment(second_row["id"], world.charge_headers)
    )
    after_second_release = reload_encounter(world, encounter["id"])

    third_row = create_care_assignment(
        world,
        encounter,
        bedside_shift,
        expected_encounter_version=after_second_release["version"],
    )

    return {
        "world": world,
        "shift": bedside_shift,
        "encounter_id": encounter["id"],
        "encounter": reload_encounter(world, encounter["id"]),
        "first_row_at_creation": first_row,
        "second_row_at_creation": second_row,
        "third_row_at_creation": third_row,
        "after_first_release": after_first_release,
        "after_second_release": after_second_release,
    }


def _row(world, row_id):
    return get_success_data(api_client.get_care_assignment(row_id, world.charge_headers))


def test_phase_axis_reaches_active_first_stage_with_the_coverage_axis_repaired(
    encounter_walked_up_two_phases_through_two_breaches,
):
    """The phase axis ends at ACTIVE_FIRST_STAGE and the coverage axis is back
    at RATIO_COVERED, because "It reaches `RATIO_COVERED` only once
    `assigned_coverage_units` is at least `required_coverage_units`."

    Design: Difficulty/non_linear_state_machine/encounter_staffing_axis_breaches_twice_while_phase_axis_advances_to_active_first_stage
    """
    encounter = encounter_walked_up_two_phases_through_two_breaches["encounter"]
    assert_labor_encounter(encounter)
    assert encounter["labor_phase"] == "ACTIVE_FIRST_STAGE"
    assert encounter["staffing_state"] == "RATIO_COVERED"
    assert encounter["assigned_coverage_units"] == pytest.approx(
        encounter["required_coverage_units"], abs=1e-9
    )


def test_active_first_stage_lifts_the_tier_and_the_requirement_to_two_point_three(
    encounter_walked_up_two_phases_through_two_breaches,
):
    """"`TIER_II` fires when `gestational_age_weeks` is below 37, or
    `fetus_count` is above 1, or `presentation` is anything other than
    `VERTEX`, or `prior_cesarean` is true, or `labor_phase` is
    `ACTIVE_FIRST_STAGE` or `THIRD_STAGE_DELIVERED`." The 1.5 weight times the
    1.5 ACTIVE_FIRST_STAGE multiplier is 2.25, and coverage arithmetic is
    "carried at one decimal place, rounding half away from zero".

    Design: Difficulty/non_linear_state_machine/encounter_staffing_axis_breaches_twice_while_phase_axis_advances_to_active_first_stage
    """
    encounter = encounter_walked_up_two_phases_through_two_breaches["encounter"]
    assert encounter["acuity_tier"] == "TIER_II"
    assert encounter["one_to_one_required"] is False
    assert encounter["required_coverage_units"] == pytest.approx(2.3, abs=1e-9)
    assert encounter["assigned_coverage_units"] == pytest.approx(2.3, abs=1e-9)


def test_each_release_records_a_breach_instead_of_refusing_the_release(
    encounter_walked_up_two_phases_through_two_breaches,
):
    """"Releasing the last `ACTIVE` row drives the encounter to `RELEASED` when
    its `labor_phase` is `POSTPARTUM_RECOVERY`, `DISCHARGED` or
    `TRANSFERRED_OUT`, and to `COVERAGE_BREACH` in any earlier phase — again
    recorded rather than refused." Both releases happen in earlier phases, and
    the phase axis does not move on either of them.

    Design: Difficulty/non_linear_state_machine/encounter_staffing_axis_breaches_twice_while_phase_axis_advances_to_active_first_stage
    """
    setup = encounter_walked_up_two_phases_through_two_breaches
    first = setup["after_first_release"]
    second = setup["after_second_release"]
    assert first["staffing_state"] == "COVERAGE_BREACH"
    assert first["labor_phase"] == "LATENT"
    assert second["staffing_state"] == "COVERAGE_BREACH"
    assert second["labor_phase"] == "ACTIVE_FIRST_STAGE"


def test_the_same_encounter_is_repriced_at_every_phase_stop(
    encounter_walked_up_two_phases_through_two_breaches,
):
    """"Whenever a tier or a phase changes, every affected row is re-priced in
    place, and the order of the two ledger movements is fixed: the old value is
    credited back first and the new value debited second, never the reverse."
    The first row is born at 0.5 in ANTEPARTUM and settles at 1.0 in LATENT;
    the second is born at 1.0 and settles at 2.3 in ACTIVE_FIRST_STAGE.

    Design: Difficulty/non_linear_state_machine/encounter_staffing_axis_breaches_twice_while_phase_axis_advances_to_active_first_stage
    """
    setup = encounter_walked_up_two_phases_through_two_breaches
    world = setup["world"]
    assert setup["first_row_at_creation"]["acuity_units_consumed"] == pytest.approx(
        0.5, abs=1e-9
    )
    assert setup["second_row_at_creation"]["acuity_units_consumed"] == pytest.approx(
        1.0, abs=1e-9
    )
    assert _row(world, setup["first_row_at_creation"]["id"])[
        "acuity_units_consumed"
    ] == pytest.approx(1.0, abs=1e-9)
    assert _row(world, setup["second_row_at_creation"]["id"])[
        "acuity_units_consumed"
    ] == pytest.approx(2.3, abs=1e-9)
    assert setup["third_row_at_creation"]["acuity_units_consumed"] == pytest.approx(
        2.3, abs=1e-9
    )


def test_only_the_newest_row_stays_active_and_the_two_earlier_rows_are_released(
    encounter_walked_up_two_phases_through_two_breaches,
):
    """"Releasing a row is a `ChargeNurse` act: `status` becomes `RELEASED`,
    `released_at` becomes the current instant, and the covering entry is
    credited back exactly `acuity_units_consumed`."

    Design: Difficulty/non_linear_state_machine/encounter_staffing_axis_breaches_twice_while_phase_axis_advances_to_active_first_stage
    """
    setup = encounter_walked_up_two_phases_through_two_breaches
    world = setup["world"]
    first = _row(world, setup["first_row_at_creation"]["id"])
    second = _row(world, setup["second_row_at_creation"]["id"])
    third = _row(world, setup["third_row_at_creation"]["id"])
    for row in (first, second, third):
        assert_care_assignment(row)
    assert first["status"] == "RELEASED"
    assert first["released_at"] is not None
    assert second["status"] == "RELEASED"
    assert second["released_at"] is not None
    assert third["status"] == "ACTIVE"
    assert third["released_at"] is None


def test_shift_load_and_unit_posture_settle_on_the_single_surviving_debit(
    encounter_walked_up_two_phases_through_two_breaches,
):
    """"For every roster entry in `SCHEDULED` or `ACTIVE`,
    `assigned_acuity_load_units` equals the sum of `acuity_units_consumed` over
    that entry's `ACTIVE` rows." With the deficit back at zero the unit is OPEN,
    and "After the posture is settled, and only then, `turnover_buffer_minutes`
    is set to 45 when the posture is `OPEN` and 75 otherwise."

    Design: Difficulty/non_linear_state_machine/encounter_staffing_axis_breaches_twice_while_phase_axis_advances_to_active_first_stage
    """
    setup = encounter_walked_up_two_phases_through_two_breaches
    world = setup["world"]
    shift = get_success_data(
        api_client.get_shift(setup["shift"]["id"], world.charge_headers)
    )
    assert_shift_assignment(shift)
    assert shift["capacity_units_effective"] == pytest.approx(4.0, abs=1e-9)
    assert shift["assigned_acuity_load_units"] == pytest.approx(2.3, abs=1e-9)

    unit = world.reload_unit()
    assert_obstetric_unit(unit)
    assert unit["coverage_deficit_units"] == pytest.approx(0.0, abs=1e-9)
    assert unit["staffing_posture"] == "OPEN"
    assert unit["turnover_buffer_minutes"] == 45

    bed = get_success_data(
        api_client.get_bed(world.bed_id("LDR-01"), world.charge_headers)
    )
    assert bed["status"] == "OCCUPIED"
    assert bed["current_encounter_id"] == setup["encounter_id"]
