"""One nested POST, five levels down, and a bed-minute figure at the bottom.

Completing a single magnesium step flips a flag on the encounter, which the
pricing calculation reads twice — once as a tier trigger and once as a
one-to-one trigger — which re-prices the covering junction row in place, which
strands the encounter below what it needs, which raises the unit's deficit,
which moves the posture, which moves the turnover buffer, which is frozen into
the projection of a booking that has nothing to do with any of it. Every level
carries a number, so a chain that breaks anywhere reports a different figure at
the bottom. Two further properties are pinned beside the chain: a stage-2 step
completed first is refused and provably writes nothing at any level, and the
out-of-sequence predecessor landing afterwards rewrites only the advisory
anchor of the already-completed row while the debit, the deficit and the
posture all hold still.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_bundle_activation,
    assert_care_assignment,
    assert_checklist_item,
    assert_induction_booking,
    assert_instant_equals,
    assert_instant_is_null,
    assert_labor_encounter,
    assert_obstetric_unit,
    assert_shift_assignment,
    assign_bed,
    bootstrap_unit,
    checklist_items_by_code,
    complete_item,
    create_active_shift,
    create_care_assignment,
    create_encounter,
    get_success_data,
    reload_activation,
    reload_encounter,
    set_clock,
    setup_validated_drill,
)

CLOCK_BOOTSTRAP = "2026-08-01T05:45:00Z"
CLOCK_DRILL_DUE = "2026-08-01T05:50:00Z"
CLOCK_ACTIVATED = "2026-08-01T06:00:00Z"
CLOCK_MAGNESIUM = "2026-08-01T06:05:00Z"
CLOCK_ANTIHYPERTENSIVE = "2026-08-01T06:10:00Z"
DRILL_SCHEDULED_FOR = "2026-08-01T05:50:00Z"
SIMULATED_DECISION_AT = "2026-08-01T05:52:00Z"
SIMULATED_INCISION_AT = "2026-08-01T05:55:00Z"
SHIFT_WINDOW = ("2026-08-01T05:00:00Z", "2026-08-01T15:00:00Z")
LIVE_CREDENTIAL = "2027-06-30T00:00:00Z"
UNIT_NAME = "Ravensworth Glen Womens Hospital LDR"
SEVERE_SYSTOLIC = 168
SEVERE_DIASTOLIC = 112
MAGNESIUM_ACTIVATION_ANCHOR = "2026-08-01T07:30:00Z"
MAGNESIUM_SEQUENCE_ANCHOR = "2026-08-01T07:10:00Z"
MAGNESIUM_MINUTES = 5
ANTIHYPERTENSIVE_MINUTES = 10
BEDSIDE_CAPACITY = 4.0
TIER_I_ANTEPARTUM_UNITS = 0.5
TIER_II_ANTEPARTUM_UNITS = 0.8
TIER_IV_ANTEPARTUM_UNITS = 2.0
ONE_TO_ONE_UNITS = 4.0
LOAD_BEFORE = 1.3
LOAD_AFTER = 2.8
DEFICIT_AFTER = 2.0
OPEN_BUFFER_MINUTES = 45
STRAINED_BUFFER_MINUTES = 75
BOOKING_START_PR = "2026-08-02T09:00:00Z"
BOOKING_START_MI = "2026-08-02T21:00:00Z"
INDUCTION_DAY = "2026-08-02"
EXPECTED_LABOR_MINUTES = 720
STRAINED_PROJECTION = 795

RAVENSWORTH_STAFF = {
    "charge": {
        "full_name": "Marisol Ravensworth RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "bedside": {
        "full_name": "Perpetua Lindqvist RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "anesthesia": {
        "full_name": "Ignatius Solberg MD",
        "staff_role": "ANESTHESIOLOGIST",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
    "ob": {
        "full_name": "Wilhelmina Trescothick MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "officer": {
        "full_name": "Bartholomew Achterberg RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def one_magnesium_step_and_everything_downstream_of_it():
    """Two encounters sharing one nurse, a hypertension bundle on the first only.

    The unit is lifted off `NOT_READY` by a validated drill so the last level of
    the chain — an induction hold — is legal at all, and it opens `OPEN` with a
    zero deficit, which is the only reason the buffer starts at 45.
    """
    world = bootstrap_unit(
        clock=CLOCK_BOOTSTRAP,
        ldr_beds=6,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR"), ("LDR-03", "LDR")],
        staff_specs=RAVENSWORTH_STAFF,
        unit_overrides={"unit_name": UNIT_NAME},
    )
    set_clock(CLOCK_DRILL_DUE)
    setup_validated_drill(
        world,
        scheduled_for_utc=DRILL_SCHEDULED_FOR,
        decision_at=SIMULATED_DECISION_AT,
        incision_at=SIMULATED_INCISION_AT,
        documented_key="anesthesia",
        validator_key="officer",
        participant_keys=["ob", "anesthesia"],
        document_clock=CLOCK_ACTIVATED,
    )
    shift = create_active_shift(world, "bedside", "BEDSIDE", *SHIFT_WINDOW)
    encounter = create_encounter(
        world,
        patient_record_code="PRC-RAVN-3301",
        parity=1,
        gestational_age_weeks=39,
    )
    assign_bed(world, encounter, "LDR-01")
    sibling = create_encounter(
        world,
        patient_record_code="PRC-RAVN-3302",
        parity=0,
        gestational_age_weeks=39,
        prior_cesarean=True,
    )
    assign_bed(world, sibling, "LDR-02")
    assignment = create_care_assignment(world, encounter, shift, "RATIO_SHARED")
    sibling_assignment = create_care_assignment(world, sibling, shift, "RATIO_SHARED")
    activation = get_success_data(
        api_client.create_activation(
            {
                "encounter_id": encounter["id"],
                "bundle_type": "SEVERE_HYPERTENSION",
                "activation_trigger": "BP_THRESHOLD",
                "systolic_mmhg": SEVERE_SYSTOLIC,
                "diastolic_mmhg": SEVERE_DIASTOLIC,
            },
            world.ob_headers,
        )
    )
    items = checklist_items_by_code(world, activation)
    patient_request_booking = get_success_data(
        api_client.create_booking(
            {
                "unit_id": world.unit_id,
                "patient_record_code": "PRC-RAVN-BK-PR",
                "gestational_age_weeks": 38,
                "indication_code": "ELECTIVE_NO_INDICATION",
                "requested_start_utc": BOOKING_START_PR,
                "expected_labor_minutes": EXPECTED_LABOR_MINUTES,
            },
            world.access_headers,
        )
    )
    indicated_booking = get_success_data(
        api_client.create_booking(
            {
                "unit_id": world.unit_id,
                "patient_record_code": "PRC-RAVN-BK-MI",
                "gestational_age_weeks": 41,
                "indication_code": "POST_DATES_41W",
                "requested_start_utc": BOOKING_START_MI,
                "expected_labor_minutes": EXPECTED_LABOR_MINUTES,
            },
            world.access_headers,
        )
    )
    unit_at_the_start = world.reload_unit()
    stage_two_first = api_client.complete_checklist_item(
        activation["id"],
        items["REPEAT_BP"]["id"],
        {
            "completed_at": CLOCK_ACTIVATED,
            "performed_by_staff_id": world.staff_id("bedside"),
        },
        world.bedside_headers,
    )
    activation_after_the_refusal = reload_activation(world, activation["id"])
    encounter_after_the_refusal = reload_encounter(world, encounter["id"])
    unit_after_the_refusal = world.reload_unit()
    set_clock(CLOCK_MAGNESIUM)
    magnesium = complete_item(
        world, activation, items["MAGNESIUM_LOADED"], CLOCK_MAGNESIUM
    )
    activation_after_magnesium = reload_activation(world, activation["id"])
    encounter_after_magnesium = reload_encounter(world, encounter["id"])
    assignment_after_magnesium = get_success_data(
        api_client.get_care_assignment(assignment["id"], world.charge_headers)
    )
    shift_after_magnesium = get_success_data(
        api_client.get_shift(shift["id"], world.charge_headers)
    )
    coverage_report = api_client.get_coverage_report(
        world.unit_id, world.charge_headers, params={"limit": 10, "offset": 0}
    )
    unit_after_magnesium = world.reload_unit()
    set_clock(CLOCK_ANTIHYPERTENSIVE)
    antihypertensive = complete_item(
        world, activation, items["ANTIHYPERTENSIVE_GIVEN"], CLOCK_ANTIHYPERTENSIVE
    )
    magnesium_after_its_predecessor = get_success_data(
        api_client.get_checklist_item(
            activation["id"], items["MAGNESIUM_LOADED"]["id"], world.ob_headers
        )
    )
    assignment_at_the_end = get_success_data(
        api_client.get_care_assignment(assignment["id"], world.charge_headers)
    )
    unit_at_the_end = world.reload_unit()
    indicated_hold = api_client.hold_capacity(
        indicated_booking["id"],
        {
            "bed_id": world.bed_id("LDR-03"),
            "expected_unit_version": unit_at_the_end["version"],
        },
        world.access_headers,
    )
    return {
        "world": world,
        "shift": shift,
        "encounter": encounter,
        "sibling": sibling,
        "assignment": assignment,
        "sibling_assignment": sibling_assignment,
        "activation": activation,
        "items": items,
        "patient_request_booking": patient_request_booking,
        "indicated_booking": indicated_booking,
        "unit_at_the_start": unit_at_the_start,
        "stage_two_first": stage_two_first,
        "activation_after_the_refusal": activation_after_the_refusal,
        "encounter_after_the_refusal": encounter_after_the_refusal,
        "unit_after_the_refusal": unit_after_the_refusal,
        "magnesium": magnesium,
        "activation_after_magnesium": activation_after_magnesium,
        "encounter_after_magnesium": encounter_after_magnesium,
        "assignment_after_magnesium": assignment_after_magnesium,
        "shift_after_magnesium": shift_after_magnesium,
        "coverage_report": coverage_report,
        "unit_after_magnesium": unit_after_magnesium,
        "antihypertensive": antihypertensive,
        "magnesium_after_its_predecessor": magnesium_after_its_predecessor,
        "assignment_at_the_end": assignment_at_the_end,
        "unit_at_the_end": unit_at_the_end,
        "indicated_hold": indicated_hold,
        "sibling_at_the_end": reload_encounter(world, sibling["id"]),
        "patient_request_at_the_end": get_success_data(
            api_client.get_booking(patient_request_booking["id"], world.access_headers)
        ),
    }


def test_the_two_shared_rows_price_off_tier_and_phase(
    one_magnesium_step_and_everything_downstream_of_it,
):
    """"A `RATIO_SHARED` row debits the product of two factors: the acuity weight, which is
    1.0 for `TIER_I`, 1.5 for `TIER_II`, 2.0 for `TIER_III` and 4.0 for `TIER_IV`; and the
    phase multiplier, which is 0.5 for `ANTEPARTUM`, 1.0 for `LATENT`, 1.5 for
    `ACTIVE_FIRST_STAGE`, 2.0 for `SECOND_STAGE`, 1.5 for `THIRD_STAGE_DELIVERED`, 0.5 for
    `POSTPARTUM_RECOVERY`, 0.0 for `DISCHARGED` and 0.0 for `TRANSFERRED_OUT`." Also: "The
    price of a row is computed at one decimal place with halves rounded away from zero."

    Design: Corner/cross_cutting_complexity_layers/magnesium_step_completion_cascades_five_levels_from_one_checklist_item_to_a_frozen_induction_projection
    """
    setup = one_magnesium_step_and_everything_downstream_of_it
    first = setup["assignment"]
    assert_care_assignment(first)
    assert first["coverage_mode"] == "RATIO_SHARED"
    assert first["acuity_units_consumed"] == pytest.approx(
        TIER_I_ANTEPARTUM_UNITS, abs=1e-9
    )
    second = setup["sibling_assignment"]
    assert_care_assignment(second)
    assert second["acuity_units_consumed"] == pytest.approx(
        TIER_II_ANTEPARTUM_UNITS, abs=1e-9
    )
    shift = setup["shift"]
    assert_shift_assignment(shift)
    assert shift["capacity_units_effective"] == pytest.approx(BEDSIDE_CAPACITY, abs=1e-9)


def test_the_unit_opens_the_run_unfrozen_with_the_open_buffer(
    one_magnesium_step_and_everything_downstream_of_it,
):
    """"`RATIO_STRAINED` when the deficit is greater than 0.0, or any encounter is in
    `COVERAGE_BREACH`." Also: "After the posture is settled, and only then,
    `turnover_buffer_minutes` is set to 45 when the posture is `OPEN` and 75 otherwise."

    Design: Corner/cross_cutting_complexity_layers/magnesium_step_completion_cascades_five_levels_from_one_checklist_item_to_a_frozen_induction_projection
    """
    setup = one_magnesium_step_and_everything_downstream_of_it
    unit = setup["unit_at_the_start"]
    assert_obstetric_unit(unit)
    assert unit["cesarean_readiness_state"] == "DEGRADED"
    assert unit["coverage_deficit_units"] == pytest.approx(0.0, abs=1e-9)
    assert unit["staffing_posture"] == "OPEN"
    assert unit["turnover_buffer_minutes"] == OPEN_BUFFER_MINUTES
    activation = setup["activation"]
    assert_bundle_activation(activation)
    assert activation["status"] == "ACTIVATED"
    assert activation["highest_stage_reached"] == 0


def test_the_two_waiting_bookings_derive_different_priority_classes(
    one_magnesium_step_and_everything_downstream_of_it,
):
    """"It is `ELECTIVE_39_WEEK` when `indication_code` is `GDM_CONTROLLED` or
    `ELECTIVE_NO_INDICATION` and `gestational_age_weeks` is 39 or greater." Also: "An elective
    request at 39 weeks is `ELECTIVE_39_WEEK`; the same request at 38 weeks is
    `PATIENT_REQUEST`, and a hold or confirmation attempted on an `ELECTIVE_39_WEEK` booking
    whose `gestational_age_weeks` is below 39 is refused with
    `ERR_ELECTIVE_INDUCTION_GESTATIONAL_AGE`."

    Design: Corner/cross_cutting_complexity_layers/magnesium_step_completion_cascades_five_levels_from_one_checklist_item_to_a_frozen_induction_projection
    """
    setup = one_magnesium_step_and_everything_downstream_of_it
    requested = setup["patient_request_booking"]
    assert_induction_booking(requested)
    assert requested["gestational_age_weeks"] == 38
    assert requested["priority_class"] == "PATIENT_REQUEST"
    indicated = setup["indicated_booking"]
    assert_induction_booking(indicated)
    assert indicated["priority_class"] == "MEDICALLY_INDICATED"
    for booking in (requested, indicated):
        assert booking["status"] == "REQUESTED"
        assert booking["projected_occupancy_minutes"] is None


def test_the_stage_two_step_completed_first_is_refused(
    one_magnesium_step_and_everything_downstream_of_it,
):
    """"The activation's `highest_stage_reached` must be at least the item's `stage_gate`,
    refused otherwise with `ERR_CHECKLIST_STAGE_NOT_REACHED` — with the deliberate exception
    that a gate-1 item may be completed while the activation is still `ACTIVATED`, since that
    first completion is what moves the activation forward." Also: "**8.05** prerequisite
    children of a bundle step, yielding `ERR_CHECKLIST_STAGE_INCOMPLETE`,
    `ERR_CHECKLIST_STAGE_NOT_REACHED` or `ERR_CESAREAN_EVENT_IN_PROGRESS`, on bundle stage
    escalation, checklist item completion and bundle resolution."

    Design: Corner/cross_cutting_complexity_layers/magnesium_step_completion_cascades_five_levels_from_one_checklist_item_to_a_frozen_induction_projection
    """
    setup = one_magnesium_step_and_everything_downstream_of_it
    assert setup["items"]["REPEAT_BP"]["stage_gate"] == 2
    validate_error(
        setup["stage_two_first"],
        ApiErrorId.ERR_CHECKLIST_STAGE_NOT_REACHED.value,
        409,
    )


def test_the_refused_step_fired_no_level_of_the_chain(
    one_magnesium_step_and_everything_downstream_of_it,
):
    """"The second step sets `one_to_one_required` to true when `labor_phase` is
    `SECOND_STAGE`, or the tier resolved to `TIER_IV`, or `magnesium_infusion_active` is true,
    and to false otherwise." Also: "The thresholds are exact: a deficit of 4.0 freezes
    inductions and a deficit of 3.9 does not; a deficit of 0.1 strains the unit and a deficit
    of exactly 0.0 does not."

    Design: Corner/cross_cutting_complexity_layers/magnesium_step_completion_cascades_five_levels_from_one_checklist_item_to_a_frozen_induction_projection
    """
    setup = one_magnesium_step_and_everything_downstream_of_it
    activation = setup["activation_after_the_refusal"]
    assert activation["status"] == "ACTIVATED"
    assert activation["highest_stage_reached"] == 0
    encounter = setup["encounter_after_the_refusal"]
    assert_labor_encounter(encounter)
    assert encounter["magnesium_infusion_active"] is False
    assert encounter["one_to_one_required"] is False
    assert encounter["acuity_tier"] == "TIER_I"
    assert encounter["required_coverage_units"] == pytest.approx(
        TIER_I_ANTEPARTUM_UNITS, abs=1e-9
    )
    assert encounter["staffing_state"] == "RATIO_COVERED"
    unit = setup["unit_after_the_refusal"]
    assert unit["coverage_deficit_units"] == pytest.approx(0.0, abs=1e-9)
    assert unit["staffing_posture"] == "OPEN"
    assert unit["turnover_buffer_minutes"] == OPEN_BUFFER_MINUTES


def test_level_one_the_step_lands_on_its_authoritative_anchor(
    one_magnesium_step_and_everything_downstream_of_it,
):
    """"A `SEVERE_HYPERTENSION` bundle receives: sequence 1, `ANTIHYPERTENSIVE_GIVEN`, gate 1,
    30 minutes; sequence 2, `MAGNESIUM_LOADED`, gate 1, 60 minutes; sequence 3, `REPEAT_BP`,
    gate 2, 15 minutes; sequence 4, `OB_AT_BEDSIDE`, gate 2, 20 minutes." Also:
    "`due_at_activation_anchored`, the authoritative date, is `activated_at` plus the sum of
    `required_within_minutes` across every item whose `step_sequence` is less than or equal to
    this item's."

    Design: Corner/cross_cutting_complexity_layers/magnesium_step_completion_cascades_five_levels_from_one_checklist_item_to_a_frozen_induction_projection
    """
    setup = one_magnesium_step_and_everything_downstream_of_it
    magnesium = setup["magnesium"]
    assert_checklist_item(magnesium)
    assert magnesium["step_code"] == "MAGNESIUM_LOADED"
    assert magnesium["step_sequence"] == 2
    assert magnesium["stage_gate"] == 1
    assert magnesium["required_within_minutes"] == 60
    assert magnesium["status"] == "COMPLETED"
    assert magnesium["minutes_from_activation"] == MAGNESIUM_MINUTES
    assert_instant_equals(
        magnesium["due_at_activation_anchored"],
        MAGNESIUM_ACTIVATION_ANCHOR,
        "due_at_activation_anchored",
    )
    assert_instant_is_null(
        magnesium["due_at_sequence_anchored"], "due_at_sequence_anchored"
    )


def test_level_two_the_first_completion_drives_the_activation_forward(
    one_magnesium_step_and_everything_downstream_of_it,
):
    """"The first completion of a gate-1 item also moves the activation from `ACTIVATED` to
    `STAGE_1_IN_PROGRESS`, which floors the encounter at `TIER_III` and re-prices coverage;
    completing `MAGNESIUM_LOADED` on a hypertension bundle additionally sets
    `magnesium_infusion_active` to true, which forces one-to-one coverage and the whole cascade
    that follows from it." Also: "The landing state is decided by the authoritative date alone:
    `completed_at` at or before `due_at_activation_anchored` yields `COMPLETED` and increments
    `on_time_step_count`, and the boundary instant counts as on time; `completed_at` strictly
    after it yields `LATE_COMPLETED` and increments `late_step_count`."

    Design: Corner/cross_cutting_complexity_layers/magnesium_step_completion_cascades_five_levels_from_one_checklist_item_to_a_frozen_induction_projection
    """
    setup = one_magnesium_step_and_everything_downstream_of_it
    activation = setup["activation_after_magnesium"]
    assert_bundle_activation(activation)
    assert activation["status"] == "STAGE_1_IN_PROGRESS"
    assert activation["highest_stage_reached"] == 1
    assert activation["on_time_step_count"] == 1
    assert activation["late_step_count"] == 0


def test_level_three_the_encounter_is_re_derived_to_the_one_to_one_floor(
    one_magnesium_step_and_everything_downstream_of_it,
):
    """"`TIER_IV` fires when an activation is in `STAGE_2_ESCALATED` or
    `STAGE_3_MASSIVE_TRANSFUSION`, or `magnesium_infusion_active` is true, or the latest
    assessment is `CATEGORY_III` with an `escalation_status` other than `RESOLVED`, or a
    cesarean event on the encounter is in `DECISION_DECLARED`, `TEAM_MOBILIZED` or
    `INCISION_RECORDED`." Also: "The third step produces `required_coverage_units`: 0.0 when
    `labor_phase` is `DISCHARGED` or `TRANSFERRED_OUT`; otherwise 4.0 when one-to-one coverage
    is required; otherwise the acuity weight multiplied by the phase multiplier from the table
    above."

    Design: Corner/cross_cutting_complexity_layers/magnesium_step_completion_cascades_five_levels_from_one_checklist_item_to_a_frozen_induction_projection
    """
    setup = one_magnesium_step_and_everything_downstream_of_it
    encounter = setup["encounter_after_magnesium"]
    assert_labor_encounter(encounter)
    assert encounter["magnesium_infusion_active"] is True
    assert encounter["acuity_tier"] == "TIER_IV"
    assert encounter["one_to_one_required"] is True
    assert encounter["required_coverage_units"] == pytest.approx(
        ONE_TO_ONE_UNITS, abs=1e-9
    )
    assert encounter["assigned_coverage_units"] == pytest.approx(
        TIER_IV_ANTEPARTUM_UNITS, abs=1e-9
    )
    assert encounter["staffing_state"] == "COVERAGE_BREACH"


def test_level_four_the_shared_row_is_re_priced_in_place_and_not_to_capacity(
    one_magnesium_step_and_everything_downstream_of_it,
):
    """"Whenever a tier or a phase changes, every affected row is re-priced in place, and the
    order of the two ledger movements is fixed: the old value is credited back first and the new
    value debited second, never the reverse." Also: "For every roster entry in `SCHEDULED` or
    `ACTIVE`, `assigned_acuity_load_units` equals the sum of `acuity_units_consumed` over that
    entry's `ACTIVE` rows."

    Design: Corner/cross_cutting_complexity_layers/magnesium_step_completion_cascades_five_levels_from_one_checklist_item_to_a_frozen_induction_projection
    """
    setup = one_magnesium_step_and_everything_downstream_of_it
    repriced = setup["assignment_after_magnesium"]
    assert_care_assignment(repriced)
    assert repriced["status"] == "ACTIVE"
    assert repriced["coverage_mode"] == "RATIO_SHARED"
    assert repriced["acuity_units_consumed"] == pytest.approx(
        TIER_IV_ANTEPARTUM_UNITS, abs=1e-9
    )
    assert repriced["acuity_units_consumed"] != pytest.approx(ONE_TO_ONE_UNITS, abs=1e-9)
    shift = setup["shift_after_magnesium"]
    assert_shift_assignment(shift)
    assert shift["assigned_acuity_load_units"] == pytest.approx(LOAD_AFTER, abs=1e-9)
    assert LOAD_BEFORE + TIER_IV_ANTEPARTUM_UNITS - TIER_I_ANTEPARTUM_UNITS == pytest.approx(
        LOAD_AFTER, abs=1e-9
    )


def test_level_four_b_the_frozen_capacity_snapshot_does_not_move(
    one_magnesium_step_and_everything_downstream_of_it,
):
    """"Activation, a `ChargeNurse` act, is where a roster entry becomes real: `SCHEDULED`
    becomes `ACTIVE` and `capacity_units_effective` is frozen." Also: "From that raw figure an
    administrative offset of 1.0 is subtracted when the slot is `CHARGE`, and a focus penalty of
    1.0 is subtracted when the member currently holds an `ACTIVE` care assignment on this shift
    covering an encounter whose `acuity_tier` is `TIER_IV`."

    Design: Corner/cross_cutting_complexity_layers/magnesium_step_completion_cascades_five_levels_from_one_checklist_item_to_a_frozen_induction_projection
    """
    setup = one_magnesium_step_and_everything_downstream_of_it
    shift = setup["shift_after_magnesium"]
    assert shift["status"] == "ACTIVE"
    assert shift["role_slot"] == "BEDSIDE"
    assert shift["capacity_units_effective"] == pytest.approx(BEDSIDE_CAPACITY, abs=1e-9)
    assert shift["assigned_acuity_load_units"] <= shift["capacity_units_effective"]


def test_level_five_the_unit_strains_and_lengthens_its_turnover_buffer(
    one_magnesium_step_and_everything_downstream_of_it,
):
    """"A unit's coverage report exposes this whole derivation: one row per non-terminal
    encounter with its required units, its assigned units and its own contribution to the
    deficit, ordered by `created_at` ascending and paginated by `limit` and `offset`, together
    with the rolled-up `coverage_deficit_units` and the reason code for the branch that fired —
    `DIVERT_DEFICIT`, `NO_AVAILABLE_LDR_BED`, `STAGE_3_BUNDLE`, `FREEZE_DEFICIT`,
    `ESCALATION_BREACH`, `BUNDLE_BREACH`, `READINESS_NOT_READY`, `STAGE_2_WITH_DEFICIT`,
    `DEFICIT_POSITIVE`, `BREACHED_ENCOUNTER` or `NONE`."

    Design: Corner/cross_cutting_complexity_layers/magnesium_step_completion_cascades_five_levels_from_one_checklist_item_to_a_frozen_induction_projection
    """
    setup = one_magnesium_step_and_everything_downstream_of_it
    assert setup["coverage_report"].status_code == 200
    report = get_success_data(setup["coverage_report"])
    assert report["staffing_posture"] == "RATIO_STRAINED"
    assert report["posture_reason"] == "DEFICIT_POSITIVE"
    assert report["coverage_deficit_units"] == pytest.approx(DEFICIT_AFTER, abs=1e-9)
    rows = {row["encounter_id"]: row for row in report["encounters"]}
    assert set(rows) == {setup["encounter"]["id"], setup["sibling"]["id"]}
    assert rows[setup["encounter"]["id"]]["deficit_units"] == pytest.approx(
        DEFICIT_AFTER, abs=1e-9
    )
    assert rows[setup["sibling"]["id"]]["deficit_units"] == pytest.approx(0.0, abs=1e-9)
    unit = setup["unit_after_magnesium"]
    assert unit["staffing_posture"] == "RATIO_STRAINED"
    assert unit["coverage_deficit_units"] == pytest.approx(DEFICIT_AFTER, abs=1e-9)
    assert unit["turnover_buffer_minutes"] == STRAINED_BUFFER_MINUTES


def test_the_late_predecessor_rewrites_only_the_advisory_anchor(
    one_magnesium_step_and_everything_downstream_of_it,
):
    """"`due_at_sequence_anchored`, the advisory date, is instead the predecessor item's
    `completed_at` plus this item's own `required_within_minutes`; for the first item it is
    `activated_at` plus that item's own allowance, and for any item whose predecessor has not
    been completed it is null." Also: "Either way `minutes_from_activation` is recorded as the
    whole minutes elapsed from `activated_at`, and the successor item's
    `due_at_sequence_anchored` is recomputed from this `completed_at` — an advisory
    recomputation that never rewrites any authoritative date."

    Design: Corner/cross_cutting_complexity_layers/magnesium_step_completion_cascades_five_levels_from_one_checklist_item_to_a_frozen_induction_projection
    """
    setup = one_magnesium_step_and_everything_downstream_of_it
    predecessor = setup["antihypertensive"]
    assert_checklist_item(predecessor)
    assert predecessor["step_code"] == "ANTIHYPERTENSIVE_GIVEN"
    assert predecessor["step_sequence"] == 1
    assert predecessor["status"] == "COMPLETED"
    assert predecessor["minutes_from_activation"] == ANTIHYPERTENSIVE_MINUTES
    rewritten = setup["magnesium_after_its_predecessor"]
    assert_checklist_item(rewritten)
    assert rewritten["status"] == "COMPLETED"
    assert_instant_equals(
        rewritten["due_at_sequence_anchored"],
        MAGNESIUM_SEQUENCE_ANCHOR,
        "due_at_sequence_anchored",
    )
    assert_instant_equals(
        rewritten["due_at_activation_anchored"],
        MAGNESIUM_ACTIVATION_ANCHOR,
        "due_at_activation_anchored",
    )
    assert_instant_equals(
        rewritten["completed_at"], CLOCK_MAGNESIUM, "completed_at"
    )


def test_the_second_completion_re_fires_none_of_the_cascade(
    one_magnesium_step_and_everything_downstream_of_it,
):
    """"The first completion of a gate-1 item also moves the activation from `ACTIVATED` to
    `STAGE_1_IN_PROGRESS`, which floors the encounter at `TIER_III` and re-prices coverage;
    completing `MAGNESIUM_LOADED` on a hypertension bundle additionally sets
    `magnesium_infusion_active` to true, which forces one-to-one coverage and the whole cascade
    that follows from it." Also: "For every encounter, `assigned_coverage_units` equals the sum
    of `acuity_units_consumed` over its own `ACTIVE` rows."

    Design: Corner/cross_cutting_complexity_layers/magnesium_step_completion_cascades_five_levels_from_one_checklist_item_to_a_frozen_induction_projection
    """
    setup = one_magnesium_step_and_everything_downstream_of_it
    still_priced = setup["assignment_at_the_end"]
    assert_care_assignment(still_priced)
    assert still_priced["acuity_units_consumed"] == pytest.approx(
        TIER_IV_ANTEPARTUM_UNITS, abs=1e-9
    )
    unit = setup["unit_at_the_end"]
    assert unit["coverage_deficit_units"] == pytest.approx(DEFICIT_AFTER, abs=1e-9)
    assert unit["staffing_posture"] == "RATIO_STRAINED"
    assert unit["turnover_buffer_minutes"] == STRAINED_BUFFER_MINUTES


def test_level_six_the_cascade_is_frozen_into_an_unrelated_projection(
    one_magnesium_step_and_everything_downstream_of_it,
):
    """"This is also the moment `projected_occupancy_minutes` is frozen, as
    `expected_labor_minutes` plus the unit's current `turnover_buffer_minutes`, and that frozen
    integer is the exact quantum every later credit and debit moves." Also: "The day's
    `held_bed_minutes_by_day` entry for the UTC date of `requested_start_utc` is increased by
    it."

    Design: Corner/cross_cutting_complexity_layers/magnesium_step_completion_cascades_five_levels_from_one_checklist_item_to_a_frozen_induction_projection
    """
    setup = one_magnesium_step_and_everything_downstream_of_it
    world = setup["world"]
    assert setup["indicated_hold"].status_code == 200
    held = get_success_data(setup["indicated_hold"])
    assert_induction_booking(held)
    assert held["status"] == "CAPACITY_HELD"
    assert held["projected_occupancy_minutes"] == STRAINED_PROJECTION
    assert EXPECTED_LABOR_MINUTES + STRAINED_BUFFER_MINUTES == STRAINED_PROJECTION
    assert held["bed_id"] == world.bed_id("LDR-03")
    unit = world.reload_unit()
    assert unit["held_bed_minutes_by_day"].get(INDUCTION_DAY, 0) == STRAINED_PROJECTION


def test_the_blast_radius_stops_at_the_sibling_and_the_waiting_booking(
    one_magnesium_step_and_everything_downstream_of_it,
):
    """"`TIER_II` fires when `gestational_age_weeks` is below 37, or `fetus_count` is above 1,
    or `presentation` is anything other than `VERTEX`, or `prior_cesarean` is true, or
    `labor_phase` is `ACTIVE_FIRST_STAGE` or `THIRD_STAGE_DELIVERED`." Also: "It reaches
    `RATIO_COVERED` only once `assigned_coverage_units` is at least `required_coverage_units`."

    Design: Corner/cross_cutting_complexity_layers/magnesium_step_completion_cascades_five_levels_from_one_checklist_item_to_a_frozen_induction_projection
    """
    setup = one_magnesium_step_and_everything_downstream_of_it
    sibling = setup["sibling_at_the_end"]
    assert_labor_encounter(sibling)
    assert sibling["prior_cesarean"] is True
    assert sibling["acuity_tier"] == "TIER_II"
    assert sibling["magnesium_infusion_active"] is False
    assert sibling["required_coverage_units"] == pytest.approx(
        TIER_II_ANTEPARTUM_UNITS, abs=1e-9
    )
    assert sibling["assigned_coverage_units"] == pytest.approx(
        TIER_II_ANTEPARTUM_UNITS, abs=1e-9
    )
    assert sibling["staffing_state"] == "RATIO_COVERED"
    waiting = setup["patient_request_at_the_end"]
    assert_induction_booking(waiting)
    assert waiting["status"] == "REQUESTED"
    assert waiting["bump_count"] == 0
    assert waiting["projected_occupancy_minutes"] is None
