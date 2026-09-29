"""A second-stage advance turns on the state of an entity it never names.

The encounter is perfect on every one of its own axes, yet the advance is
refused because the unit's derived readiness is NOT_READY. Validating a drill
that belongs to the unit — a call that touches no encounter field and does not
move the clock — makes the byte-identical advance succeed.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    advance_phase,
    assert_bed,
    assert_care_assignment,
    assert_drill,
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
    reload_encounter,
    set_clock,
)

CLOCK_START = "2026-08-22T07:00:00Z"
CLOCK_SETTLED = "2026-08-22T07:20:00Z"
SHIFT_START = "2026-08-22T06:00:00Z"
SHIFT_END = "2026-08-22T16:00:00Z"
SIMULATED_DECISION = "2026-08-22T07:00:00Z"
SIMULATED_INCISION = "2026-08-22T07:18:00Z"

XENT_STAFF = {
    "ob": {
        "full_name": "Perpetua Anand MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-11-30T00:00:00Z",
        "or_circulating_qualified": True,
    },
    "anesthesia": {
        "full_name": "Casimir Bujnowski MD",
        "staff_role": "ANESTHESIOLOGIST",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": "2027-11-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
    "charge": {
        "full_name": "Adaeze Nwachukwu RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-11-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
    "bedside": {
        "full_name": "Sindre Haugland RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-11-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
    "officer": {
        "full_name": "Rosalba Ferreira RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": "2027-11-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def advance_gated_only_by_unit_readiness():
    """An encounter parked in ACTIVE_FIRST_STAGE under one-to-one coverage, with
    the unit's only drill left at DOCUMENTED so readiness is still NOT_READY."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=3,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR")],
        staff_specs=XENT_STAFF,
        unit_overrides={"unit_name": "Glenmarrow Family Birth Place"},
    )
    drill = get_success_data(
        api_client.create_drill(
            world.unit_id,
            {
                "drill_type": "DECISION_TO_INCISION",
                "scheduled_for_utc": CLOCK_START,
                "participant_staff_ids": [world.staff_id("ob"), world.staff_id("anesthesia")],
            },
            world.anesthesia_headers,
        )
    )
    get_success_data(api_client.start_drill(drill["id"], world.charge_headers))
    set_clock(CLOCK_SETTLED)
    documented = get_success_data(
        api_client.document_drill(
            drill["id"],
            {
                "decision_at": SIMULATED_DECISION,
                "incision_at": SIMULATED_INCISION,
                "documented_by_staff_id": world.staff_id("anesthesia"),
            },
            world.anesthesia_headers,
        )
    )
    unit_before = world.reload_unit()

    create_active_shift(world, "charge", "CHARGE", SHIFT_START, SHIFT_END)
    bedside_shift = create_active_shift(world, "bedside", "BEDSIDE", SHIFT_START, SHIFT_END)
    encounter = create_encounter(
        world,
        patient_record_code="PRC-XENT-5150",
        parity=0,
        gestational_age_weeks=39,
        prior_cesarean=False,
        fetus_count=1,
        presentation="VERTEX",
    )
    assign_bed(world, encounter, "LDR-01")
    create_assessment(
        world,
        encounter,
        interpreted_key="charge",
        acting_key="charge",
        category="CATEGORY_I",
        baseline_rate_bpm=138,
        variability="MODERATE",
        recurrent_decelerations=False,
        assessed_at=CLOCK_SETTLED,
    )
    assignment = create_care_assignment(
        world, encounter, bedside_shift, coverage_mode="ONE_TO_ONE"
    )
    advance_phase(world, encounter, "LATENT")
    at_first_stage = advance_phase(world, encounter, "ACTIVE_FIRST_STAGE")

    refused = api_client.advance_phase(
        encounter["id"], {"target_phase": "SECOND_STAGE"}, world.charge_headers
    )
    encounter_after_refusal = reload_encounter(world, encounter["id"])
    validated = get_success_data(
        api_client.validate_drill(drill["id"], world.officer_headers)
    )
    unit_after_validation = world.reload_unit()
    admitted = api_client.advance_phase(
        encounter["id"], {"target_phase": "SECOND_STAGE"}, world.charge_headers
    )
    return {
        "world": world,
        "drill": drill,
        "documented": documented,
        "validated": validated,
        "unit_before": unit_before,
        "unit_after_validation": unit_after_validation,
        "encounter": encounter,
        "assignment": assignment,
        "bedside_shift": bedside_shift,
        "at_first_stage": at_first_stage,
        "encounter_after_refusal": encounter_after_refusal,
        "refused": refused,
        "admitted": admitted,
    }


def test_the_advance_is_refused_while_the_unit_is_not_ready(
    advance_gated_only_by_unit_readiness,
):
    """"And the unit's `cesarean_readiness_state` must be anything other than
    `NOT_READY`, refused otherwise with `ERR_CESAREAN_READINESS_NOT_MET`."

    Design: Difficulty/cross_entity_state_dependency/second_stage_advance_blocked_by_unit_not_ready_then_unblocked_by_validating_a_drill_nothing_on_the_encounter_changing
    """
    setup = advance_gated_only_by_unit_readiness
    assert setup["unit_before"]["cesarean_readiness_state"] == "NOT_READY"
    validate_error(
        setup["refused"], ApiErrorId.ERR_CESAREAN_READINESS_NOT_MET.value, 422
    )


def test_the_encounter_was_faultless_on_its_own_axes(
    advance_gated_only_by_unit_readiness,
):
    """The step's own three encounter-level gates were all satisfied: "The
    coverage axis must be exactly `ONE_TO_ONE_COVERED`", the latest assessment
    was zero minutes old, and it was `CATEGORY_I`.

    Design: Difficulty/cross_entity_state_dependency/second_stage_advance_blocked_by_unit_not_ready_then_unblocked_by_validating_a_drill_nothing_on_the_encounter_changing
    """
    setup = advance_gated_only_by_unit_readiness
    encounter = setup["encounter_after_refusal"]
    assert_labor_encounter(encounter)
    assert encounter["labor_phase"] == "ACTIVE_FIRST_STAGE"
    assert encounter["staffing_state"] == "ONE_TO_ONE_COVERED"
    assert encounter["acuity_tier"] == "TIER_II"
    assert encounter["required_coverage_units"] == pytest.approx(2.3, abs=1e-9)
    assert encounter["assigned_coverage_units"] == pytest.approx(4.0, abs=1e-9)
    bed = get_success_data(
        api_client.get_bed(setup["world"].bed_id("LDR-01"), setup["world"].charge_headers)
    )
    assert_bed(bed)
    assert bed["status"] == "OCCUPIED"
    assert bed["current_encounter_id"] == encounter["id"]


def test_an_unvalidated_drill_grants_no_currency(
    advance_gated_only_by_unit_readiness,
):
    """"Documentation alone still changes no readiness" — the measurement is
    already inside the pass window, yet the drill sits at `DOCUMENTED` and
    "`NOT_READY` when the current drill is null" still holds.

    Design: Difficulty/cross_entity_state_dependency/second_stage_advance_blocked_by_unit_not_ready_then_unblocked_by_validating_a_drill_nothing_on_the_encounter_changing
    """
    setup = advance_gated_only_by_unit_readiness
    assert setup["documented"]["status"] == "DOCUMENTED"
    assert setup["documented"]["measured_d2i_minutes"] == 18
    unit = setup["unit_before"]
    assert unit["cesarean_readiness_state"] == "NOT_READY"
    assert unit["current_drill_id"] is None


def test_validating_the_drill_lifts_readiness_to_degraded(
    advance_gated_only_by_unit_readiness,
):
    """"It then recomputes unit readiness, which can rise to `READY` and thereby
    unblock induction confirmations and second-stage advances" — with no
    `OR_STANDBY` entry the rise stops at `DEGRADED`, which is enough.

    Design: Difficulty/cross_entity_state_dependency/second_stage_advance_blocked_by_unit_not_ready_then_unblocked_by_validating_a_drill_nothing_on_the_encounter_changing
    """
    setup = advance_gated_only_by_unit_readiness
    drill = setup["validated"]
    assert_drill(drill)
    assert drill["status"] == "VALIDATED"
    assert drill["measured_d2i_minutes"] == 18
    unit = setup["unit_after_validation"]
    assert_obstetric_unit(unit)
    assert unit["cesarean_readiness_state"] == "DEGRADED"
    assert unit["current_drill_id"] == setup["drill"]["id"]


def test_the_identical_advance_now_succeeds(advance_gated_only_by_unit_readiness):
    """The repeated step fires its own consequences: "The encounter's
    `acuity_tier` is floored at `TIER_III` and `one_to_one_required` becomes
    true", and "otherwise 4.0 when one-to-one coverage is required".

    Design: Difficulty/cross_entity_state_dependency/second_stage_advance_blocked_by_unit_not_ready_then_unblocked_by_validating_a_drill_nothing_on_the_encounter_changing
    """
    setup = advance_gated_only_by_unit_readiness
    encounter = get_success_data(setup["admitted"])
    assert_labor_encounter(encounter)
    assert encounter["labor_phase"] == "SECOND_STAGE"
    assert encounter["staffing_state"] == "ONE_TO_ONE_COVERED"
    assert encounter["acuity_tier"] == "TIER_III"
    assert encounter["one_to_one_required"] is True
    assert encounter["required_coverage_units"] == pytest.approx(4.0, abs=1e-9)
    assert encounter["assigned_coverage_units"] == pytest.approx(4.0, abs=1e-9)


def test_the_one_to_one_row_holds_the_whole_capacity_throughout(
    advance_gated_only_by_unit_readiness,
):
    """"A `ONE_TO_ONE` row debits the covering entry's entire
    `capacity_units_effective`, whatever that value is" — so the re-pricing at
    second stage moves nothing, and the ledger conservation rule that
    "`assigned_acuity_load_units` equals the sum of `acuity_units_consumed` over
    that entry's `ACTIVE` rows" still holds.

    Design: Difficulty/cross_entity_state_dependency/second_stage_advance_blocked_by_unit_not_ready_then_unblocked_by_validating_a_drill_nothing_on_the_encounter_changing
    """
    setup = advance_gated_only_by_unit_readiness
    world = setup["world"]
    row = get_success_data(
        api_client.get_care_assignment(setup["assignment"]["id"], world.charge_headers)
    )
    assert_care_assignment(row)
    assert row["status"] == "ACTIVE"
    assert row["coverage_mode"] == "ONE_TO_ONE"
    assert row["acuity_units_consumed"] == pytest.approx(4.0, abs=1e-9)
    shift = get_success_data(
        api_client.get_shift(setup["bedside_shift"]["id"], world.charge_headers)
    )
    assert_shift_assignment(shift)
    assert shift["capacity_units_effective"] == pytest.approx(4.0, abs=1e-9)
    assert shift["assigned_acuity_load_units"] == pytest.approx(4.0, abs=1e-9)


def test_the_unit_never_left_open(advance_gated_only_by_unit_readiness):
    """"`OPEN` otherwise" — the covered encounter leaves no deficit and a second
    `LDR` bed stays available, so the posture never explains either outcome.

    Design: Difficulty/cross_entity_state_dependency/second_stage_advance_blocked_by_unit_not_ready_then_unblocked_by_validating_a_drill_nothing_on_the_encounter_changing
    """
    unit = advance_gated_only_by_unit_readiness["world"].reload_unit()
    assert_obstetric_unit(unit)
    assert unit["coverage_deficit_units"] == pytest.approx(0.0, abs=1e-9)
    assert unit["staffing_posture"] == "OPEN"
