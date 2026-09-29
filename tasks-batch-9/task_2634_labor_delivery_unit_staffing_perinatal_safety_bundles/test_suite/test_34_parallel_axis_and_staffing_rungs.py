"""Two refusals chosen from among rivals that share an HTTP status.

A second-stage advance arms three independent gates at once, and only the one
reading a second field on the encounter's own row is allowed to answer. A
one-to-one attachment arms two adjacent staffing gates that both answer 422, and
repairing the higher one exposes the lower one under an otherwise identical
request.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    advance_phase,
    assert_care_assignment,
    assert_fetal_assessment,
    assert_labor_encounter,
    assert_obstetric_unit,
    assert_shift_assignment,
    assign_bed,
    bootstrap_unit,
    BOOTSTRAP_OFFICER_HEADERS,
    create_active_shift,
    create_assessment,
    create_care_assignment,
    create_encounter,
    get_success_data,
    reload_encounter,
    set_clock,
)

CLOCK_START = "2026-08-01T06:00:00Z"
CLOCK_AGED = "2026-08-01T06:20:00Z"
SHIFT_START = "2026-08-01T05:00:00Z"
SHIFT_END = "2026-08-01T15:00:00Z"
ELAPSED_CREDENTIAL = "2026-07-01T00:00:00Z"
LIVE_CREDENTIAL = "2027-01-01T00:00:00Z"
FIRST_STAGE_REQUIREMENT = 2.3
BEDSIDE_CAPACITY = 4.0
CHARGE_CAPACITY = 2.0

RN_STAFF = {
    "charge": {
        "full_name": "Dana Alvarez RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def a_first_stage_patient_whose_three_gates_all_fail():
    """Ratio coverage only, a twenty-minute-old reading, and no validated drill."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR")],
        staff_specs=RN_STAFF,
        unit_overrides={"unit_name": "Rowan Perinatal Center LDR"},
    )
    shift = create_active_shift(world, "charge", "BEDSIDE", SHIFT_START, SHIFT_END)
    encounter = create_encounter(
        world,
        patient_record_code="PRC-SECOND-8031",
        parity=1,
        gestational_age_weeks=39,
    )
    assign_bed(world, encounter, "LDR-01")
    assignment = create_care_assignment(
        world, encounter, shift, coverage_mode="RATIO_SHARED"
    )
    advance_phase(world, encounter, "LATENT")
    assessment = create_assessment(
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
    at_first_stage = advance_phase(world, encounter, "ACTIVE_FIRST_STAGE")
    set_clock(CLOCK_AGED)
    refused = api_client.advance_phase(
        encounter["id"], {"target_phase": "SECOND_STAGE"}, world.charge_headers
    )
    return {
        "world": world,
        "shift": shift,
        "encounter": encounter,
        "assignment": assignment,
        "assessment": assessment,
        "at_first_stage": at_first_stage,
        "refused": refused,
    }


def test_the_parallel_axis_answers_before_either_clinical_gate(
    a_first_stage_patient_whose_three_gates_all_fail,
):
    """"Moving `ACTIVE_FIRST_STAGE` to `SECOND_STAGE` is the most heavily gated
    step in the system. The coverage axis must be exactly `ONE_TO_ONE_COVERED`,
    refused otherwise with `ERR_ONE_TO_ONE_COVERAGE_REQUIRED`."

    Design: Corner/validations/one_to_one_coverage_gate_at_8_03_outranks_the_stale_assessment_at_11_3_and_readiness_at_11_4
    """
    refused = a_first_stage_patient_whose_three_gates_all_fail["refused"]
    validate_error(
        refused, ApiErrorId.ERR_ONE_TO_ONE_COVERAGE_REQUIRED.value, 409
    )
    reported = refused.json()["data"]["error_id"]
    assert reported != ApiErrorId.ERR_FETAL_ASSESSMENT_STALE.value
    assert reported != ApiErrorId.ERR_CESAREAN_READINESS_NOT_MET.value


def test_both_suppressed_gates_were_genuinely_armed(
    a_first_stage_patient_whose_three_gates_all_fail,
):
    """"The latest assessment must have been taken within 15 minutes of the
    current instant, with exactly 15 minutes still acceptable, refused otherwise
    with `ERR_FETAL_ASSESSMENT_STALE`." The reading is twenty minutes old and the
    unit has validated no drill, so both later rungs would also have fired.

    Design: Corner/validations/one_to_one_coverage_gate_at_8_03_outranks_the_stale_assessment_at_11_3_and_readiness_at_11_4
    """
    setup = a_first_stage_patient_whose_three_gates_all_fail
    assessment = setup["assessment"]
    assert_fetal_assessment(assessment)
    assert assessment["category"] == "CATEGORY_I"
    assert assessment["escalation_status"] == "NOT_REQUIRED"
    unit = setup["world"].reload_unit()
    assert_obstetric_unit(unit)
    assert unit["cesarean_readiness_state"] == "NOT_READY"
    assert unit["staffing_posture"] == "INDUCTION_FROZEN"


def test_the_ratio_row_left_the_patient_exactly_covered(
    a_first_stage_patient_whose_three_gates_all_fail,
):
    """"It reaches `RATIO_COVERED` only once `assigned_coverage_units` is at least
    `required_coverage_units`." The shared debit exactly meets the first-stage
    requirement, so the axis is short of one-to-one without being in breach.

    Design: Corner/validations/one_to_one_coverage_gate_at_8_03_outranks_the_stale_assessment_at_11_3_and_readiness_at_11_4
    """
    setup = a_first_stage_patient_whose_three_gates_all_fail
    encounter = reload_encounter(setup["world"], setup["encounter"]["id"])
    assert_labor_encounter(encounter)
    assert encounter["labor_phase"] == "ACTIVE_FIRST_STAGE"
    assert encounter["staffing_state"] == "RATIO_COVERED"
    assert encounter["acuity_tier"] == "TIER_II"
    assert encounter["one_to_one_required"] is False
    assert encounter["required_coverage_units"] == pytest.approx(
        FIRST_STAGE_REQUIREMENT, abs=1e-9
    )
    assert encounter["assigned_coverage_units"] == pytest.approx(
        FIRST_STAGE_REQUIREMENT, abs=1e-9
    )


def test_the_refused_advance_moved_no_ledger(
    a_first_stage_patient_whose_three_gates_all_fail,
):
    """"A `RATIO_SHARED` row debits the product of two factors: the acuity weight,
    which is 1.0 for `TIER_I`, 1.5 for `TIER_II`, 2.0 for `TIER_III` and 4.0 for
    `TIER_IV`; and the phase multiplier, which is 0.5 for `ANTEPARTUM`, 1.0 for
    `LATENT`, 1.5 for `ACTIVE_FIRST_STAGE`, 2.0 for `SECOND_STAGE`, 1.5 for
    `THIRD_STAGE_DELIVERED`, 0.5 for `POSTPARTUM_RECOVERY`, 0.0 for `DISCHARGED`
    and 0.0 for `TRANSFERRED_OUT`." The refusal left the phase where it was, so
    the row is still priced for first stage rather than for second.

    Design: Corner/validations/one_to_one_coverage_gate_at_8_03_outranks_the_stale_assessment_at_11_3_and_readiness_at_11_4
    """
    setup = a_first_stage_patient_whose_three_gates_all_fail
    world = setup["world"]
    row = get_success_data(
        api_client.get_care_assignment(setup["assignment"]["id"], world.charge_headers)
    )
    assert_care_assignment(row)
    assert row["status"] == "ACTIVE"
    assert row["acuity_units_consumed"] == pytest.approx(
        FIRST_STAGE_REQUIREMENT, abs=1e-9
    )
    shift = get_success_data(
        api_client.get_shift(setup["shift"]["id"], world.charge_headers)
    )
    assert_shift_assignment(shift)
    assert shift["capacity_units_effective"] == pytest.approx(BEDSIDE_CAPACITY, abs=1e-9)
    assert shift["assigned_acuity_load_units"] == pytest.approx(
        FIRST_STAGE_REQUIREMENT, abs=1e-9
    )


@pytest.fixture
def one_to_one_asked_of_a_charge_slot_held_by_a_lapsed_nurse():
    """The same attachment sent twice, differing only in the credential date."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=RN_STAFF,
        unit_overrides={"unit_name": "Halloway Perinatal Center LDR"},
    )
    shift = create_active_shift(world, "charge", "CHARGE", SHIFT_START, SHIFT_END)
    encounter = create_encounter(
        world,
        patient_record_code="PRC-SLOT-1102",
        parity=1,
        gestational_age_weeks=39,
    )
    get_success_data(
        api_client.patch_staff_member(
            world.staff_id("charge"),
            {"credential_expires_at": ELAPSED_CREDENTIAL},
            BOOTSTRAP_OFFICER_HEADERS,
        )
    )
    payload = {
        "encounter_id": encounter["id"],
        "shift_assignment_id": shift["id"],
        "coverage_mode": "ONE_TO_ONE",
        "expected_encounter_version": encounter["version"],
    }
    while_the_credential_is_stale = api_client.create_care_assignment(
        payload, world.charge_headers
    )
    get_success_data(
        api_client.patch_staff_member(
            world.staff_id("charge"),
            {"credential_expires_at": LIVE_CREDENTIAL},
            BOOTSTRAP_OFFICER_HEADERS,
        )
    )
    once_the_credential_is_repaired = api_client.create_care_assignment(
        payload, world.charge_headers
    )
    return {
        "world": world,
        "shift": shift,
        "encounter": encounter,
        "while_the_credential_is_stale": while_the_credential_is_stale,
        "once_the_credential_is_repaired": once_the_credential_is_repaired,
    }


def test_the_credential_rung_answers_before_the_slot_rung(
    one_to_one_asked_of_a_charge_slot_held_by_a_lapsed_nurse,
):
    """"**11.1** staff credential and employment status, yielding
    `ERR_STAFF_CREDENTIAL_EXPIRED`, on care-assignment creation, shift-assignment
    creation, shift activation, shift relief, cesarean team mobilisation, drill
    documentation and fetal assessment recording."

    Design: Corner/validations/expired_credential_at_11_1_outranks_the_ineligible_one_to_one_role_slot_at_11_2
    """
    setup = one_to_one_asked_of_a_charge_slot_held_by_a_lapsed_nurse
    refused = setup["while_the_credential_is_stale"]
    validate_error(refused, ApiErrorId.ERR_STAFF_CREDENTIAL_EXPIRED.value, 422)
    assert (
        refused.json()["data"]["error_id"] != ApiErrorId.ERR_ROLE_SLOT_NOT_ELIGIBLE.value
    )


def test_repairing_the_credential_exposes_the_ineligible_slot(
    one_to_one_asked_of_a_charge_slot_held_by_a_lapsed_nurse,
):
    """"It reaches `ONE_TO_ONE_COVERED` from `UNASSIGNED`, `RATIO_COVERED` or
    `COVERAGE_BREACH` when a `ONE_TO_ONE` row is created, and that creation carries
    three extra gates: the covering entry's `role_slot` must be `BEDSIDE` or
    `ONE_TO_ONE_FLOAT`, refused otherwise with `ERR_ROLE_SLOT_NOT_ELIGIBLE`; the
    staff member must hold no other `ACTIVE` care assignment on a different
    encounter, refused otherwise with `ERR_STAFF_NOT_EXCLUSIVELY_AVAILABLE`; and the
    member's `fetal_monitoring_cert_level` must be `BASIC` or `ADVANCED`, and must
    be `ADVANCED` when the encounter's tier is `TIER_IV`, refused otherwise with
    `ERR_MONITORING_CERT_INSUFFICIENT`."

    Design: Corner/validations/expired_credential_at_11_1_outranks_the_ineligible_one_to_one_role_slot_at_11_2
    """
    setup = one_to_one_asked_of_a_charge_slot_held_by_a_lapsed_nurse
    validate_error(
        setup["once_the_credential_is_repaired"],
        ApiErrorId.ERR_ROLE_SLOT_NOT_ELIGIBLE.value,
        422,
    )
    assert setup["shift"]["role_slot"] == "CHARGE"


def test_neither_rejection_bumped_the_encounter_or_the_ledger(
    one_to_one_asked_of_a_charge_slot_held_by_a_lapsed_nurse,
):
    """"Creating a `CareAssignment` requires `expected_encounter_version` to equal
    the current `version` of the named `LaborEncounter`; when the echoed value does
    not match, the write is refused with `ERR_STALE_ENCOUNTER_VERSION` and HTTP
    412, and nothing is created or debited." The same echoed value served both
    attempts, so neither rejection can have moved the revision.

    Design: Corner/validations/expired_credential_at_11_1_outranks_the_ineligible_one_to_one_role_slot_at_11_2
    """
    setup = one_to_one_asked_of_a_charge_slot_held_by_a_lapsed_nurse
    world = setup["world"]
    assert setup["encounter"]["version"] == 1
    encounter = reload_encounter(world, setup["encounter"]["id"])
    assert_labor_encounter(encounter)
    assert encounter["version"] == 1
    assert encounter["staffing_state"] == "UNASSIGNED"
    shift = get_success_data(
        api_client.get_shift(setup["shift"]["id"], world.charge_headers)
    )
    assert_shift_assignment(shift)
    assert shift["assigned_acuity_load_units"] == pytest.approx(0.0, abs=1e-9)
    assert shift["capacity_units_effective"] == pytest.approx(CHARGE_CAPACITY, abs=1e-9)
