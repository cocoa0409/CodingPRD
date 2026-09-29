"""One capacity hold breaks two rules at once.

The unit is in DIVERT, which the refusal ladder places in band 8.02, and the
day's bed-minute budget cannot absorb the booking, which the ladder places at
priority 15 and checks after everything else. The posture refusal must win.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    activate_hypertension_bundle,
    assert_bed,
    assert_induction_booking,
    assert_instant_is_null,
    assert_labor_encounter,
    assert_obstetric_unit,
    bootstrap_unit,
    checklist_items_by_code,
    complete_item,
    create_active_shift,
    create_booking,
    create_encounter,
    get_success_data,
    reload_booking,
    reload_encounter,
)

INDUCTION_DAY = "2026-08-13"
REQUESTED_START = "2026-08-13T08:00:00Z"
ACTIVATION_INSTANT = "2026-08-12T10:00:00Z"

DIVERT_STAFF = {
    "charge": {"staff_role": "RN_LABOR_DELIVERY", "fetal_monitoring_cert_level": "ADVANCED"},
}


@pytest.fixture
def divert_unit_with_an_over_budget_hold():
    """Drive the unit to DIVERT on the deficit alone, then attempt a hold that
    also exceeds the day's whole bed-minute budget.

    Two magnesium-loaded hypertension bundles each pin their encounter at 4.0
    required units with nothing assigned, so the deficit is exactly 8.0. Neither
    encounter holds a bed, so both LDR beds stay AVAILABLE and no bed rule can
    pre-empt the pair. The booking is MEDICALLY_INDICATED, so the elective
    compliance rule cannot interfere either.
    """
    world = bootstrap_unit(
        clock="2026-08-12T10:00:00Z",
        ldr_beds=3,
        or_rooms=1,
        max_daily_induction_bed_minutes=600,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR")],
        staff_specs=DIVERT_STAFF,
    )
    create_active_shift(
        world, "charge", "CHARGE", "2026-08-12T08:00:00Z", "2026-08-12T18:00:00Z"
    )

    encounters = []
    for record, parity, weeks, systolic, diastolic in (
        ("A1", 1, 38, 168, 112),
        ("B2", 2, 37, 172, 118),
    ):
        encounter = create_encounter(
            world,
            patient_record_code=f"PRC-DIVERT-{record}",
            parity=parity,
            gestational_age_weeks=weeks,
            prior_cesarean=False,
            fetus_count=1,
            presentation="VERTEX",
        )
        activation = activate_hypertension_bundle(
            world,
            encounter,
            acting_key="charge",
            systolic_mmhg=systolic,
            diastolic_mmhg=diastolic,
        )
        magnesium = checklist_items_by_code(world, activation, acting_key="charge")[
            "MAGNESIUM_LOADED"
        ]
        complete_item(
            world,
            activation,
            magnesium,
            ACTIVATION_INSTANT,
            performed_key="charge",
            acting_key="charge",
        )
        encounters.append(reload_encounter(world, encounter["id"]))

    booking = create_booking(
        world,
        patient_record_code="PRC-DIVERT-BK9",
        gestational_age_weeks=38,
        indication_code="PREECLAMPSIA",
        requested_start_utc=REQUESTED_START,
        expected_labor_minutes=600,
    )
    unit_before = world.reload_unit()

    response = api_client.hold_capacity(
        booking["id"],
        {
            "bed_id": world.bed_id("LDR-01"),
            "expected_unit_version": unit_before["version"],
        },
        world.access_headers,
    )

    return {
        "world": world,
        "encounters": encounters,
        "booking": booking,
        "unit_before": unit_before,
        "response": response,
    }


def test_the_posture_band_outranks_the_capacity_band(divert_unit_with_an_over_budget_hold):
    """Band 8.02 is "the unit's posture must permit the operation, yielding
    `ERR_UNIT_POSTURE_BLOCKS_OPERATION`, on walk-in encounter creation, phase
    advance, induction capacity holding, induction confirmation, induction
    admission and drill start", while priority 15 is "capacity and quota,
    checked after everything else and always with an inclusive boundary".

    Design: Difficulty/priority_pair_validation_conflict/divert_posture_at_8_02_outranks_exceeded_day_bed_minute_budget_at_15_on_induction_hold
    """
    response = divert_unit_with_an_over_budget_hold["response"]
    validate_error(response, ApiErrorId.ERR_UNIT_POSTURE_BLOCKS_OPERATION.value, 409)
    assert response.json()["data"]["error_id"] != (
        ApiErrorId.ERR_INDUCTION_CAPACITY_EXCEEDED.value
    )


def test_both_halves_of_the_pair_are_genuinely_violated(
    divert_unit_with_an_over_budget_hold,
):
    """The posture is DIVERT because "`DIVERT` when the deficit is 8.0 or
    greater", and the buffer that DIVERT installs is what puts the projection
    over the tiny budget: 600 expected minutes plus a 75-minute buffer is 675
    against a whole-day allowance of 600.

    Design: Difficulty/priority_pair_validation_conflict/divert_posture_at_8_02_outranks_exceeded_day_bed_minute_budget_at_15_on_induction_hold
    """
    unit = divert_unit_with_an_over_budget_hold["unit_before"]
    assert_obstetric_unit(unit)
    assert unit["coverage_deficit_units"] == pytest.approx(8.0, abs=1e-9)
    assert unit["staffing_posture"] == "DIVERT"
    assert unit["turnover_buffer_minutes"] == 75
    assert unit["max_daily_induction_bed_minutes"] == 600


def test_the_deficit_comes_from_two_magnesium_loaded_encounters(
    divert_unit_with_an_over_budget_hold,
):
    """"completing `MAGNESIUM_LOADED` on a hypertension bundle additionally sets
    `magnesium_infusion_active` to true, which forces one-to-one coverage and
    the whole cascade that follows from it", and the requirement is then "4.0
    when one-to-one coverage is required".

    Design: Difficulty/priority_pair_validation_conflict/divert_posture_at_8_02_outranks_exceeded_day_bed_minute_budget_at_15_on_induction_hold
    """
    for encounter in divert_unit_with_an_over_budget_hold["encounters"]:
        assert_labor_encounter(encounter)
        assert encounter["magnesium_infusion_active"] is True
        assert encounter["one_to_one_required"] is True
        assert encounter["required_coverage_units"] == pytest.approx(4.0, abs=1e-9)
        assert encounter["assigned_coverage_units"] == pytest.approx(0.0, abs=1e-9)
        assert encounter["bed_id"] is None


def test_the_refused_hold_reserves_no_bed_minutes(divert_unit_with_an_over_budget_hold):
    """A hold is the moment "The day's `held_bed_minutes_by_day` entry for the
    UTC date of `requested_start_utc` is increased by it", so a refused hold must
    leave both ledgers exactly as they were.

    Design: Difficulty/priority_pair_validation_conflict/divert_posture_at_8_02_outranks_exceeded_day_bed_minute_budget_at_15_on_induction_hold
    """
    unit = divert_unit_with_an_over_budget_hold["world"].reload_unit()
    assert unit["held_bed_minutes_by_day"].get(INDUCTION_DAY, 0) == 0
    assert unit["committed_bed_minutes_by_day"].get(INDUCTION_DAY, 0) == 0


def test_the_booking_is_untouched_by_the_refusal(divert_unit_with_an_over_budget_hold):
    """"The booking opens in `REQUESTED` with `bump_count` at 0, `bed_id`,
    `encounter_id`, `hold_expires_at` and `projected_occupancy_minutes` all
    null, and consumes no budget at all." A refused hold neither freezes a
    projection nor moves the version.

    Design: Difficulty/priority_pair_validation_conflict/divert_posture_at_8_02_outranks_exceeded_day_bed_minute_budget_at_15_on_induction_hold
    """
    setup = divert_unit_with_an_over_budget_hold
    booking = reload_booking(setup["world"], setup["booking"]["id"])
    assert_induction_booking(booking)
    assert booking["status"] == "REQUESTED"
    assert booking["priority_class"] == "MEDICALLY_INDICATED"
    assert booking["projected_occupancy_minutes"] is None
    assert booking["bed_id"] is None
    assert_instant_is_null(booking["hold_expires_at"], "hold_expires_at")
    assert booking["version"] == 1


def test_the_named_bed_stays_available(divert_unit_with_an_over_budget_hold):
    """A successful hold is where "the named `LDR` bed moves `AVAILABLE` to
    `HELD` with `held_booking_id` written", so the refusal must leave the bed
    free — and both LDR beds being free is what rules out the empty-bed route
    into DIVERT.

    Design: Difficulty/priority_pair_validation_conflict/divert_posture_at_8_02_outranks_exceeded_day_bed_minute_budget_at_15_on_induction_hold
    """
    world = divert_unit_with_an_over_budget_hold["world"]
    for label in ("LDR-01", "LDR-02"):
        bed = get_success_data(
            api_client.get_bed(world.bed_id(label), world.charge_headers)
        )
        assert_bed(bed)
        assert bed["status"] == "AVAILABLE"
        assert bed["held_booking_id"] is None
