"""Two figures that do not follow the patient's own numbers.

A one-to-one row is priced from the covering nurse's whole frozen capacity, so
a 0.5-unit patient consumes 4.0 units and the entry lands exactly on its
inclusive limit. A posture rises to DIVERT on a bed count alone, while the
deficit that would have explained it is only 0.5.
"""

import pytest

from test_helpers import (
    api_client,
    assert_bed,
    assert_care_assignment,
    assert_labor_encounter,
    assert_obstetric_unit,
    assert_shift_assignment,
    assign_bed,
    bootstrap_unit,
    create_active_shift,
    create_care_assignment,
    create_encounter,
    get_success_data,
    reload_encounter,
)

CLOCK_START = "2026-08-01T06:00:00Z"
SHIFT_START = "2026-08-01T05:00:00Z"
SHIFT_END = "2026-08-01T15:00:00Z"
BEDSIDE_CAPACITY = 4.0
TIER_ONE_ANTEPARTUM_REQUIREMENT = 0.5

EXCLUSIVE_STAFF = {
    "charge": {
        "full_name": "Rosalind Ferraro RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
}

POSTURE_STAFF = {
    "charge": {
        "full_name": "Havilah Sinclair RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def a_half_unit_patient_covered_one_to_one():
    """A TIER_I ANTEPARTUM encounter given a ONE_TO_ONE row on a 4.0 entry."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=5,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=EXCLUSIVE_STAFF,
        unit_overrides={"unit_name": "Larkspur Perinatal Institute LDR"},
    )
    shift = create_active_shift(world, "charge", "BEDSIDE", SHIFT_START, SHIFT_END)
    encounter = create_encounter(
        world,
        patient_record_code="PRC-ONE21-2323",
        parity=2,
        gestational_age_weeks=40,
    )
    assignment = create_care_assignment(
        world, encounter, shift, coverage_mode="ONE_TO_ONE"
    )
    return {
        "world": world,
        "shift": shift,
        "encounter": encounter,
        "assignment": assignment,
    }


@pytest.fixture
def the_last_ldr_bed_taken_by_one_patient():
    """A unit with a single LDR bed, occupied by an uncovered encounter."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=5,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=POSTURE_STAFF,
        unit_overrides={"unit_name": "Quillbrook Womens Hospital LDR"},
    )
    bed_before = get_success_data(
        api_client.get_bed(world.bed_id("LDR-01"), world.charge_headers)
    )
    encounter = create_encounter(
        world,
        patient_record_code="PRC-DIVERT-2424",
        parity=3,
        gestational_age_weeks=40,
    )
    occupied = assign_bed(world, encounter, "LDR-01")
    return {
        "world": world,
        "bed_before": bed_before,
        "encounter": encounter,
        "occupied": occupied,
    }


def test_the_one_to_one_row_is_priced_from_the_nurse_not_the_patient(
    a_half_unit_patient_covered_one_to_one,
):
    """"A `ONE_TO_ONE` row debits the covering entry's entire
    `capacity_units_effective`, whatever that value is."

    Design: Corner/calculations/one_to_one_coverage_consumes_the_whole_4_0_bedside_capacity_whatever_the_acuity
    """
    setup = a_half_unit_patient_covered_one_to_one
    assert setup["shift"]["capacity_units_effective"] == pytest.approx(
        BEDSIDE_CAPACITY, abs=1e-9
    )
    row = setup["assignment"]
    assert_care_assignment(row)
    assert row["coverage_mode"] == "ONE_TO_ONE"
    assert row["status"] == "ACTIVE"
    assert row["acuity_units_consumed"] == pytest.approx(BEDSIDE_CAPACITY, abs=1e-9)


def test_the_patients_own_requirement_stays_at_half_a_unit(
    a_half_unit_patient_covered_one_to_one,
):
    """"The third step produces `required_coverage_units`: 0.0 when `labor_phase`
    is `DISCHARGED` or `TRANSFERRED_OUT`; otherwise 4.0 when one-to-one coverage is
    required; otherwise the acuity weight multiplied by the phase multiplier from
    the table above." No one-to-one requirement was raised, so the figure stays at
    the ANTEPARTUM product while 4.0 units are committed against it.

    Design: Corner/calculations/one_to_one_coverage_consumes_the_whole_4_0_bedside_capacity_whatever_the_acuity
    """
    setup = a_half_unit_patient_covered_one_to_one
    encounter = reload_encounter(setup["world"], setup["encounter"]["id"])
    assert_labor_encounter(encounter)
    assert encounter["labor_phase"] == "ANTEPARTUM"
    assert encounter["acuity_tier"] == "TIER_I"
    assert encounter["one_to_one_required"] is False
    assert encounter["required_coverage_units"] == pytest.approx(
        TIER_ONE_ANTEPARTUM_REQUIREMENT, abs=1e-9
    )
    assert encounter["assigned_coverage_units"] == pytest.approx(
        BEDSIDE_CAPACITY, abs=1e-9
    )
    assert encounter["staffing_state"] == "ONE_TO_ONE_COVERED"


def test_the_entry_lands_exactly_on_its_inclusive_limit(
    a_half_unit_patient_covered_one_to_one,
):
    """"Capacity is the last thing checked when a row is created or a shift
    relieved: the covering entry's `assigned_acuity_load_units` plus the new debit
    must be no greater than its `capacity_units_effective`, with the boundary
    allowed, and an excess is refused with `ERR_STAFF_ACUITY_CAPACITY_EXCEEDED`."

    Design: Corner/calculations/one_to_one_coverage_consumes_the_whole_4_0_bedside_capacity_whatever_the_acuity
    """
    setup = a_half_unit_patient_covered_one_to_one
    world = setup["world"]
    shift = get_success_data(
        api_client.get_shift(setup["shift"]["id"], world.charge_headers)
    )
    assert_shift_assignment(shift)
    assert shift["assigned_acuity_load_units"] == pytest.approx(
        BEDSIDE_CAPACITY, abs=1e-9
    )
    assert shift["assigned_acuity_load_units"] == pytest.approx(
        shift["capacity_units_effective"], abs=1e-9
    )
    unit = world.reload_unit()
    assert_obstetric_unit(unit)
    assert unit["coverage_deficit_units"] == pytest.approx(0.0, abs=1e-9)


def test_taking_the_last_bed_moves_it_to_occupied(
    the_last_ldr_bed_taken_by_one_patient,
):
    """"Attaching a bed is a separate `ChargeNurse` act naming `bed_id`; the bed
    must be of type `LDR` and `AVAILABLE`, it moves to `OCCUPIED` with
    `current_encounter_id` pointing at the encounter, and an encounter that already
    occupies a bed is refused with `ERR_ENCOUNTER_ALREADY_IN_BED`."

    Design: Corner/calculations/occupying_the_last_available_ldr_bed_drives_divert_with_a_deficit_of_only_0_5
    """
    setup = the_last_ldr_bed_taken_by_one_patient
    world = setup["world"]
    assert setup["bed_before"]["status"] == "AVAILABLE"
    encounter = setup["occupied"]
    assert_labor_encounter(encounter)
    assert encounter["bed_id"] == world.bed_id("LDR-01")
    bed = get_success_data(
        api_client.get_bed(world.bed_id("LDR-01"), world.charge_headers)
    )
    assert_bed(bed)
    assert bed["status"] == "OCCUPIED"
    assert bed["current_encounter_id"] == encounter["id"]


def test_the_bed_count_alone_drives_the_posture_to_divert(
    the_last_ldr_bed_taken_by_one_patient,
):
    """"`DIVERT` when the deficit is 8.0 or greater, or no `LDR` bed is available,
    or any activation in the unit is in `STAGE_3_MASSIVE_TRANSFUSION`."

    Design: Corner/calculations/occupying_the_last_available_ldr_bed_drives_divert_with_a_deficit_of_only_0_5
    """
    setup = the_last_ldr_bed_taken_by_one_patient
    unit = setup["world"].reload_unit()
    assert_obstetric_unit(unit)
    assert unit["staffing_posture"] == "DIVERT"
    assert unit["coverage_deficit_units"] == pytest.approx(0.5, abs=1e-9)


def test_the_deficit_alone_would_only_have_strained_the_unit(
    the_last_ldr_bed_taken_by_one_patient,
):
    """"The thresholds are exact: a deficit of 4.0 freezes inductions and a deficit
    of 3.9 does not; a deficit of 0.1 strains the unit and a deficit of exactly 0.0
    does not." A 0.5 deficit reaches none of the DIVERT thresholds, so only the
    bed count explains the posture.

    Design: Corner/calculations/occupying_the_last_available_ldr_bed_drives_divert_with_a_deficit_of_only_0_5
    """
    setup = the_last_ldr_bed_taken_by_one_patient
    world = setup["world"]
    unit = world.reload_unit()
    assert unit["coverage_deficit_units"] < 4.0
    assert unit["escalation_breach_count"] == 0
    assert unit["bundle_breach_count"] == 0
    encounter = reload_encounter(world, setup["encounter"]["id"])
    assert encounter["staffing_state"] == "UNASSIGNED"
    assert encounter["required_coverage_units"] == pytest.approx(
        TIER_ONE_ANTEPARTUM_REQUIREMENT, abs=1e-9
    )
    assert encounter["assigned_coverage_units"] == pytest.approx(0.0, abs=1e-9)
