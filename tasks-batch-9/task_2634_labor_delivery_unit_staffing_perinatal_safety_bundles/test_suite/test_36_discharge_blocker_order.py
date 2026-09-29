"""One rung that hides an ordered list of four, three of them armed at once.

The patient has reached postpartum recovery with an open newborn review, a
partner still at the bedside and a one-to-one nurse still assigned. A discharge
in that state must be refused for the review, and neither of the other two
blockers may be the one reported.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    advance_phase,
    assert_bed,
    assert_care_assignment,
    assert_labor_encounter,
    assert_newborn_review,
    assert_obstetric_unit,
    assert_support_pass,
    assign_bed,
    bootstrap_unit,
    check_in_pass,
    create_active_shift,
    create_assessment,
    create_care_assignment,
    create_encounter,
    create_pass,
    create_review,
    get_success_data,
    reload_encounter,
    reload_pass,
    setup_validated_drill,
)

CLOCK_START = "2026-08-01T06:00:00Z"
SHIFT_START = "2026-08-01T05:00:00Z"
SHIFT_END = "2026-08-01T15:00:00Z"
DRILL_DECISION = "2026-08-01T05:50:00Z"
DRILL_INCISION = "2026-08-01T06:00:00Z"
BEDSIDE_CAPACITY = 4.0
POSTPARTUM_REQUIREMENT = 0.5

DISCHARGE_STAFF = {
    "charge": {
        "full_name": "Dana Alvarez RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-01-01T00:00:00Z",
        "or_circulating_qualified": False,
    },
    "ob": {
        "full_name": "Priya Raman MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-01-01T00:00:00Z",
        "or_circulating_qualified": True,
    },
    "anesthesia": {
        "full_name": "Marc Feld MD",
        "staff_role": "ANESTHESIOLOGIST",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": "2027-01-01T00:00:00Z",
        "or_circulating_qualified": False,
    },
    "officer": {
        "full_name": "Ottoline Basara RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": "2027-01-01T00:00:00Z",
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def a_recovering_patient_with_three_blockers_at_once():
    """POSTPARTUM_RECOVERY with an OPEN review, a CHECKED_IN pass and an ACTIVE
    one-to-one row, then a discharge attempt."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR")],
        staff_specs=DISCHARGE_STAFF,
        unit_overrides={"unit_name": "Rowan Perinatal Center LDR"},
    )
    shift = create_active_shift(world, "charge", "BEDSIDE", SHIFT_START, SHIFT_END)
    drill = setup_validated_drill(
        world,
        scheduled_for_utc=CLOCK_START,
        decision_at=DRILL_DECISION,
        incision_at=DRILL_INCISION,
        documented_key="ob",
        validator_key="officer",
        participant_keys=["ob", "anesthesia"],
    )
    encounter = create_encounter(
        world,
        patient_record_code="PRC-DISCHARGE-8041",
        parity=1,
        gestational_age_weeks=39,
    )
    assign_bed(world, encounter, "LDR-01")
    assignment = create_care_assignment(
        world, encounter, shift, coverage_mode="ONE_TO_ONE"
    )
    create_assessment(
        world,
        encounter,
        interpreted_key="charge",
        acting_key="charge",
        category="CATEGORY_I",
        baseline_rate_bpm=140,
        variability="MODERATE",
        recurrent_decelerations=False,
        assessed_at=CLOCK_START,
    )
    advance_phase(world, encounter, "LATENT")
    advance_phase(world, encounter, "ACTIVE_FIRST_STAGE")
    advance_phase(world, encounter, "SECOND_STAGE")
    delivered = get_success_data(
        api_client.advance_phase(
            encounter["id"],
            {
                "target_phase": "THIRD_STAGE_DELIVERED",
                "delivery_mode": "SPONTANEOUS_VAGINAL",
                "episiotomy_performed": False,
            },
            world.ob_headers,
        )
    )
    recovering = advance_phase(world, encounter, "POSTPARTUM_RECOVERY")
    support_pass = create_pass(
        world, encounter, person_name="Jordan Alvarez", credential_type="PARTNER"
    )
    check_in_pass(world, support_pass)
    review = create_review(
        world,
        encounter,
        facilitator_key="ob",
        complication_code="APGAR5_UNDER_7",
    )
    refused = api_client.discharge_encounter(encounter["id"], world.charge_headers)
    return {
        "world": world,
        "drill": drill,
        "shift": shift,
        "encounter": encounter,
        "assignment": assignment,
        "delivered": delivered,
        "recovering": recovering,
        "pass": support_pass,
        "review": review,
        "refused": refused,
    }


def test_the_open_review_is_the_blocker_that_answers(
    a_recovering_patient_with_three_blockers_at_once,
):
    """"Discharge is a `ChargeNurse` act from `POSTPARTUM_RECOVERY` to
    `DISCHARGED`, and its four blockers are checked in exactly this order: any
    newborn complication review on the encounter not yet `CLOSED` yields
    `ERR_NEWBORN_REVIEW_OPEN`; any activation not yet `CLOSED` or `RESCINDED`
    yields `ERR_BUNDLE_NOT_CLOSED`; any support pass still `ISSUED`, `CHECKED_IN`
    or `CHECKED_OUT` yields `ERR_SUPPORT_PASS_STILL_PRESENT`; and a
    `staffing_state` that is not yet `RELEASED` yields
    `ERR_CARE_ASSIGNMENT_STILL_ACTIVE`."

    Design: Corner/validations/discharge_blocker_order_returns_the_open_newborn_review_before_the_checked_in_pass
    """
    refused = a_recovering_patient_with_three_blockers_at_once["refused"]
    validate_error(refused, ApiErrorId.ERR_NEWBORN_REVIEW_OPEN.value, 409)
    reported = refused.json()["data"]["error_id"]
    assert reported != ApiErrorId.ERR_SUPPORT_PASS_STILL_PRESENT.value
    assert reported != ApiErrorId.ERR_CARE_ASSIGNMENT_STILL_ACTIVE.value
    assert reported != ApiErrorId.ERR_BUNDLE_NOT_CLOSED.value


def test_the_two_suppressed_blockers_were_both_standing(
    a_recovering_patient_with_three_blockers_at_once,
):
    """"**8.04** blocking children, checked in exactly the order
    `ERR_NEWBORN_REVIEW_OPEN`, then `ERR_BUNDLE_NOT_CLOSED`, then
    `ERR_SUPPORT_PASS_STILL_PRESENT`, then `ERR_CARE_ASSIGNMENT_STILL_ACTIVE`, and
    for the transfer path `ERR_CESAREAN_EVENT_IN_PROGRESS` then
    `ERR_BUNDLE_STAGE_BLOCKS_TRANSFER`, on encounter discharge and encounter
    transfer-out."

    Design: Corner/validations/discharge_blocker_order_returns_the_open_newborn_review_before_the_checked_in_pass
    """
    setup = a_recovering_patient_with_three_blockers_at_once
    world = setup["world"]
    review = setup["review"]
    assert_newborn_review(review)
    assert review["status"] == "OPEN"
    assert review["facilitator_staff_id"] == world.staff_id("ob")
    still_present = reload_pass(world, setup["pass"]["id"])
    assert_support_pass(still_present)
    assert still_present["status"] == "CHECKED_IN"
    row = get_success_data(
        api_client.get_care_assignment(setup["assignment"]["id"], world.charge_headers)
    )
    assert_care_assignment(row)
    assert row["status"] == "ACTIVE"
    assert row["coverage_mode"] == "ONE_TO_ONE"
    assert row["acuity_units_consumed"] == pytest.approx(BEDSIDE_CAPACITY, abs=1e-9)


def test_the_refusal_left_the_patient_in_recovery(
    a_recovering_patient_with_three_blockers_at_once,
):
    """"The third step produces `required_coverage_units`: 0.0 when `labor_phase`
    is `DISCHARGED` or `TRANSFERRED_OUT`; otherwise 4.0 when one-to-one coverage is
    required; otherwise the acuity weight multiplied by the phase multiplier from
    the table above." Recovery is not terminal, so the requirement is the shared
    figure while the debit remains the whole entry.

    Design: Corner/validations/discharge_blocker_order_returns_the_open_newborn_review_before_the_checked_in_pass
    """
    setup = a_recovering_patient_with_three_blockers_at_once
    encounter = reload_encounter(setup["world"], setup["encounter"]["id"])
    assert_labor_encounter(encounter)
    assert encounter["labor_phase"] == "POSTPARTUM_RECOVERY"
    assert encounter["staffing_state"] == "ONE_TO_ONE_COVERED"
    assert encounter["delivery_mode"] == "SPONTANEOUS_VAGINAL"
    assert encounter["required_coverage_units"] == pytest.approx(
        POSTPARTUM_REQUIREMENT, abs=1e-9
    )
    assert encounter["assigned_coverage_units"] == pytest.approx(
        BEDSIDE_CAPACITY, abs=1e-9
    )


def test_recovery_freed_one_bed_and_left_the_spare_alone(
    a_recovering_patient_with_three_blockers_at_once,
):
    """"The step sends the occupied bed to `TURNOVER` with `turnover_clear_at` set
    to the current instant plus the unit's `turnover_buffer_minutes`, and clears the
    encounter's `bed_id`."

    Design: Corner/validations/discharge_blocker_order_returns_the_open_newborn_review_before_the_checked_in_pass
    """
    setup = a_recovering_patient_with_three_blockers_at_once
    world = setup["world"]
    vacated = get_success_data(
        api_client.get_bed(world.bed_id("LDR-01"), world.charge_headers)
    )
    assert_bed(vacated)
    assert vacated["status"] == "TURNOVER"
    spare = get_success_data(
        api_client.get_bed(world.bed_id("LDR-02"), world.charge_headers)
    )
    assert_bed(spare)
    assert spare["status"] == "AVAILABLE"
    unit = world.reload_unit()
    assert_obstetric_unit(unit)
    assert unit["cesarean_readiness_state"] == "DEGRADED"
    assert setup["drill"]["status"] == "VALIDATED"
