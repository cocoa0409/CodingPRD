"""Three more adjacent rungs, each probed with a request that trips both.

A terminal patient record silences the expired credential the same request also
carries; a unit with no available labour bed refuses the next walk-in even
though nothing at all is wrong with the request; and a rescission built from a
stale read is refused for the stale read rather than for the reason field it
also forgot. Each pair is followed by a control proving the lower rung was
genuinely reachable.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_bed,
    assert_labor_encounter,
    assert_obstetric_unit,
    assert_bundle_activation,
    assert_shift_assignment,
    assign_bed,
    bootstrap_unit,
    activate_hemorrhage_bundle,
    checklist_items_by_code,
    complete_item,
    create_active_shift,
    create_bed,
    create_encounter,
    get_success_data,
    reload_activation,
    reload_encounter,
)

CLOCK_START = "2026-08-01T06:00:00Z"
SHIFT_START = "2026-08-01T05:00:00Z"
SHIFT_END = "2026-08-01T15:00:00Z"
ELAPSED_CREDENTIAL = "2026-07-01T00:00:00Z"
LIVE_CREDENTIAL = "2027-01-01T00:00:00Z"
CHARGE_CAPACITY = 2.0
ANTEPARTUM_DEFICIT = 0.5
NON_OPEN_TURNOVER_BUFFER = 75
RESCIND_REASON = (
    "Quantified blood loss re-measured at 400 mL; activation opened on a charting error."
)

LADDER_STAFF = {
    "charge": {
        "full_name": "Dana Alvarez RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "ob": {
        "full_name": "Teodoro Marchetti MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
}


def _unit(unit_name, staff_specs=LADDER_STAFF, bed_specs=(("LDR-01", "LDR"),)):
    """One unit with the given beds and roster, clock parked at 06:00."""
    return bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=list(bed_specs),
        staff_specs=staff_specs,
        unit_overrides={"unit_name": unit_name},
    )


@pytest.fixture
def two_encounters_one_terminal_covered_by_a_lapsed_nurse():
    """One transferred-out record and one live one, both named alongside a nurse
    whose credential was retro-dated after her shift was already ACTIVE."""
    world = _unit("Rowan Perinatal Center LDR")
    shift = create_active_shift(world, "charge", "CHARGE", SHIFT_START, SHIFT_END)
    gone = create_encounter(
        world,
        patient_record_code="PRC-TERMINAL-8001",
        parity=1,
        gestational_age_weeks=39,
    )
    live = create_encounter(
        world,
        patient_record_code="PRC-TERMINAL-8002",
        parity=1,
        gestational_age_weeks=39,
    )
    transferred = get_success_data(
        api_client.transfer_out_encounter(gone["id"], {}, world.ob_headers)
    )
    lapsed = get_success_data(
        api_client.patch_staff_member(
            world.staff_id("charge"),
            {"credential_expires_at": ELAPSED_CREDENTIAL},
            world.charge_headers,
        )
    )
    on_the_terminal_record = api_client.create_care_assignment(
        {
            "encounter_id": gone["id"],
            "shift_assignment_id": shift["id"],
            "coverage_mode": "RATIO_SHARED",
            "expected_encounter_version": reload_encounter(world, gone["id"])["version"],
        },
        world.charge_headers,
    )
    on_the_live_record = api_client.create_care_assignment(
        {
            "encounter_id": live["id"],
            "shift_assignment_id": shift["id"],
            "coverage_mode": "RATIO_SHARED",
            "expected_encounter_version": reload_encounter(world, live["id"])["version"],
        },
        world.charge_headers,
    )
    return {
        "world": world,
        "shift": shift,
        "gone": gone,
        "live": live,
        "transferred": transferred,
        "lapsed": lapsed,
        "on_the_terminal_record": on_the_terminal_record,
        "on_the_live_record": on_the_live_record,
    }


def test_the_terminal_phase_is_reported_and_the_credential_is_not(
    two_encounters_one_terminal_covered_by_a_lapsed_nurse,
):
    """"A care-assignment creation that names an encounter already `DISCHARGED`
    and also names a staff member whose credential has elapsed fails at 8.01 with
    `ERR_ENCOUNTER_PHASE_TERMINAL` and HTTP 409, not at 11.1 with
    `ERR_STAFF_CREDENTIAL_EXPIRED`."

    Design: Corner/validations/terminal_encounter_phase_at_priority_8_01_outranks_the_expired_credential_at_priority_11_1
    """
    setup = two_encounters_one_terminal_covered_by_a_lapsed_nurse
    refused = setup["on_the_terminal_record"]
    validate_error(refused, ApiErrorId.ERR_ENCOUNTER_PHASE_TERMINAL.value, 409)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_STAFF_CREDENTIAL_EXPIRED.value
    )
    assert setup["transferred"]["labor_phase"] == "TRANSFERRED_OUT"
    assert setup["lapsed"]["credential_expires_at"].startswith("2026-07-01T00:00:00")


def test_the_credential_refusal_is_reachable_on_a_live_record(
    two_encounters_one_terminal_covered_by_a_lapsed_nurse,
):
    """"**11.1** staff credential and employment status, yielding
    `ERR_STAFF_CREDENTIAL_EXPIRED`, on care-assignment creation, shift-assignment
    creation, shift activation, shift relief, cesarean team mobilisation, drill
    documentation and fetal assessment recording."

    Design: Corner/validations/terminal_encounter_phase_at_priority_8_01_outranks_the_expired_credential_at_priority_11_1
    """
    setup = two_encounters_one_terminal_covered_by_a_lapsed_nurse
    validate_error(
        setup["on_the_live_record"],
        ApiErrorId.ERR_STAFF_CREDENTIAL_EXPIRED.value,
        422,
    )
    live = reload_encounter(setup["world"], setup["live"]["id"])
    assert_labor_encounter(live)
    assert live["labor_phase"] == "ANTEPARTUM"
    assert live["staffing_state"] == "UNASSIGNED"


def test_neither_refusal_debited_the_roster_entry(
    two_encounters_one_terminal_covered_by_a_lapsed_nurse,
):
    """"For every roster entry in `SCHEDULED` or `ACTIVE`,
    `assigned_acuity_load_units` equals the sum of `acuity_units_consumed` over
    that entry's `ACTIVE` rows." Both creations were refused, so that sum is empty.

    Design: Corner/validations/terminal_encounter_phase_at_priority_8_01_outranks_the_expired_credential_at_priority_11_1
    """
    setup = two_encounters_one_terminal_covered_by_a_lapsed_nurse
    shift = get_success_data(
        api_client.get_shift(setup["shift"]["id"], setup["world"].charge_headers)
    )
    assert_shift_assignment(shift)
    assert shift["status"] == "ACTIVE"
    assert shift["assigned_acuity_load_units"] == pytest.approx(0.0, abs=1e-9)
    assert shift["capacity_units_effective"] == pytest.approx(CHARGE_CAPACITY, abs=1e-9)
    rows = api_client.list_care_assignments(
        setup["world"].charge_headers, params={"limit": 100}
    ).json()["data"]
    assert rows == []


@pytest.fixture
def the_only_labour_bed_taken_by_the_first_walk_in():
    """One LDR bed, occupied, so the count of AVAILABLE LDR beds is zero."""
    world = _unit("Thistledown Perinatal Center LDR")
    first = create_encounter(
        world,
        patient_record_code="PRC-DIVERT-8021",
        parity=1,
        gestational_age_weeks=39,
    )
    assign_bed(world, first, "LDR-01")
    unit_on_divert = world.reload_unit()
    refused = api_client.create_encounter(
        {
            "unit_id": world.unit_id,
            "patient_record_code": "PRC-DIVERT-8022",
            "parity": 1,
            "gestational_age_weeks": 39,
        },
        world.charge_headers,
    )
    second_bed = create_bed(world.unit_id, "LDR-02", "LDR")
    unit_after_the_second_bed = world.reload_unit()
    admitted = api_client.create_encounter(
        {
            "unit_id": world.unit_id,
            "patient_record_code": "PRC-DIVERT-8022",
            "parity": 1,
            "gestational_age_weeks": 39,
        },
        world.charge_headers,
    )
    return {
        "world": world,
        "first": first,
        "unit_on_divert": unit_on_divert,
        "refused": refused,
        "second_bed": second_bed,
        "unit_after_the_second_bed": unit_after_the_second_bed,
        "admitted": admitted,
    }


def test_no_available_labour_bed_is_a_divert_all_by_itself(
    the_only_labour_bed_taken_by_the_first_walk_in,
):
    """"`DIVERT` when the deficit is 8.0 or greater, or no `LDR` bed is available,
    or any activation in the unit is in `STAGE_3_MASSIVE_TRANSFUSION`."

    Design: Corner/validations/zero_available_ldr_beds_derives_divert_and_blocks_the_next_encounter_creation
    """
    unit = the_only_labour_bed_taken_by_the_first_walk_in["unit_on_divert"]
    assert_obstetric_unit(unit)
    assert unit["staffing_posture"] == "DIVERT"
    assert unit["coverage_deficit_units"] == pytest.approx(ANTEPARTUM_DEFICIT, abs=1e-9)
    assert unit["licensed_ldr_beds"] == 4


def test_the_buffer_lengthens_for_every_posture_but_open(
    the_only_labour_bed_taken_by_the_first_walk_in,
):
    """"After the posture is settled, and only then, `turnover_buffer_minutes` is
    set to 45 when the posture is `OPEN` and 75 otherwise."

    Design: Corner/validations/zero_available_ldr_beds_derives_divert_and_blocks_the_next_encounter_creation
    """
    setup = the_only_labour_bed_taken_by_the_first_walk_in
    assert setup["unit_on_divert"]["turnover_buffer_minutes"] == (
        NON_OPEN_TURNOVER_BUFFER
    )
    assert setup["unit_after_the_second_bed"]["turnover_buffer_minutes"] == (
        NON_OPEN_TURNOVER_BUFFER
    )


def test_a_diverting_unit_refuses_the_next_walk_in(
    the_only_labour_bed_taken_by_the_first_walk_in,
):
    """"Creation is blocked by posture: a unit in `DIVERT` refuses new walk-ins
    with `ERR_UNIT_POSTURE_BLOCKS_OPERATION`."

    Design: Corner/validations/zero_available_ldr_beds_derives_divert_and_blocks_the_next_encounter_creation
    """
    setup = the_only_labour_bed_taken_by_the_first_walk_in
    validate_error(
        setup["refused"], ApiErrorId.ERR_UNIT_POSTURE_BLOCKS_OPERATION.value, 409
    )
    bed = get_success_data(
        api_client.get_bed(setup["world"].bed_id("LDR-01"), setup["world"].charge_headers)
    )
    assert_bed(bed)
    assert bed["status"] == "OCCUPIED"
    assert bed["current_encounter_id"] == setup["first"]["id"]


def test_one_more_bed_lifts_the_divert_and_admits_the_same_request(
    the_only_labour_bed_taken_by_the_first_walk_in,
):
    """"The first `AVAILABLE` bed of type `LDR` in a unit can by itself lift a
    bed-exhaustion divert, so bed creation re-derives the unit's posture and
    increments the unit's `version`." The unit has no validated drill, so the
    posture lands on the next branch down rather than on `OPEN`.

    Design: Corner/validations/zero_available_ldr_beds_derives_divert_and_blocks_the_next_encounter_creation
    """
    setup = the_only_labour_bed_taken_by_the_first_walk_in
    unit = setup["unit_after_the_second_bed"]
    assert_obstetric_unit(unit)
    assert unit["cesarean_readiness_state"] == "NOT_READY"
    assert unit["staffing_posture"] == "INDUCTION_FROZEN"
    assert unit["version"] > setup["unit_on_divert"]["version"]
    admitted = get_success_data(setup["admitted"])
    assert_labor_encounter(admitted)
    assert admitted["labor_phase"] == "ANTEPARTUM"
    assert admitted["patient_record_code"] == "PRC-DIVERT-8022"
    assert admitted["bed_id"] is None


@pytest.fixture
def a_rescission_built_from_a_version_the_checklist_moved_on():
    """A stage-1 hemorrhage activation rescinded three times: once on a stale
    version with no reason, once on a fresh version with no reason, once fully."""
    world = _unit("Cinderfell Womens Hospital LDR")
    create_active_shift(world, "charge", "CHARGE", SHIFT_START, SHIFT_END)
    encounter = create_encounter(
        world,
        patient_record_code="PRC-RESCIND-6009",
        parity=1,
        gestational_age_weeks=39,
    )
    activation = activate_hemorrhage_bundle(
        world,
        encounter,
        activation_trigger="QBL_THRESHOLD",
        quantitative_blood_loss_ml=1200,
    )
    stale_version = activation["version"]
    items = checklist_items_by_code(world, activation)
    in_progress = complete_item(
        world,
        activation,
        items["QBL_MEASURE"],
        CLOCK_START,
        performed_by_staff_id=world.staff_id("charge"),
        acting_key="charge",
    )
    on_a_stale_version = api_client.rescind_activation(
        activation["id"],
        {"expected_activation_version": stale_version},
        world.ob_headers,
    )
    fresh_version = reload_activation(world, activation["id"])["version"]
    with_no_reason = api_client.rescind_activation(
        activation["id"],
        {"expected_activation_version": fresh_version},
        world.ob_headers,
    )
    # Captured before the third call, because the successful rescission that
    # follows is what proves the row was rescindable all along.
    still_open_after_the_refusals = reload_activation(world, activation["id"])
    rescinded = api_client.rescind_activation(
        activation["id"],
        {
            "rescind_reason": RESCIND_REASON,
            "expected_activation_version": fresh_version,
        },
        world.ob_headers,
    )
    return {
        "world": world,
        "encounter": encounter,
        "activation": activation,
        "stale_version": stale_version,
        "fresh_version": fresh_version,
        "in_progress": in_progress,
        "on_a_stale_version": on_a_stale_version,
        "with_no_reason": with_no_reason,
        "still_open_after_the_refusals": still_open_after_the_refusals,
        "rescinded": rescinded,
    }


def test_the_revision_guard_outranks_the_missing_reason(
    a_rescission_built_from_a_version_the_checklist_moved_on,
):
    """"Rescinding a safety bundle requires `expected_activation_version` to equal
    the current `version` of the `SafetyBundleActivation`, and a mismatch is
    refused with `ERR_STALE_ACTIVATION_VERSION` and HTTP 412 with no checklist
    item voided and no coverage restored."

    Design: Corner/validations/stale_activation_version_at_priority_6_outranks_the_missing_rescind_reason_at_priority_9
    """
    setup = a_rescission_built_from_a_version_the_checklist_moved_on
    refused = setup["on_a_stale_version"]
    validate_error(refused, ApiErrorId.ERR_STALE_ACTIVATION_VERSION.value, 412)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_RESCIND_REASON_REQUIRED.value
    )
    assert setup["stale_version"] == 1
    assert setup["fresh_version"] == 2
    assert setup["in_progress"]["status"] == "COMPLETED"


def test_the_context_field_rung_sits_below_the_revision_guard(
    a_rescission_built_from_a_version_the_checklist_moved_on,
):
    """"**Priority 9** — context-required fields and their length bounds, at HTTP
    422: `ERR_RESCIND_REASON_REQUIRED`, `ERR_INVALIDATION_REASON_REQUIRED`,
    `ERR_DEBRIEF_NOTES_REQUIRED`, `ERR_CONTRIBUTING_FACTORS_REQUIRED` and
    `ERR_DELIVERY_MODE_REQUIRED`, on bundle rescission, bundle debrief closure,
    drill invalidation, review findings submission, review closure and phase
    advance."

    Design: Corner/validations/stale_activation_version_at_priority_6_outranks_the_missing_rescind_reason_at_priority_9
    """
    setup = a_rescission_built_from_a_version_the_checklist_moved_on
    validate_error(
        setup["with_no_reason"], ApiErrorId.ERR_RESCIND_REASON_REQUIRED.value, 422
    )
    still_open = setup["still_open_after_the_refusals"]
    assert_bundle_activation(still_open)
    assert still_open["status"] == "STAGE_1_IN_PROGRESS"
    assert still_open["highest_stage_reached"] == 1


def test_a_complete_rescission_erases_the_counters_and_leaves_the_scores_null(
    a_rescission_built_from_a_version_the_checklist_moved_on,
):
    """"Rescission voids every checklist item to `NOT_APPLICABLE` irrespective of
    its prior status, resets `on_time_step_count`, `late_step_count` and
    `missed_step_count` to 0, leaves both scores null forever, clears
    `magnesium_infusion_active`, and restores the encounter's
    `required_coverage_units`, every affected roster entry's
    `assigned_acuity_load_units` and the unit's `coverage_deficit_units` to exactly
    their pre-activation values by crediting the new price and debiting the old,
    which may return the encounter from `COVERAGE_BREACH` to `RATIO_COVERED` or
    `ONE_TO_ONE_COVERED`."

    Design: Corner/validations/stale_activation_version_at_priority_6_outranks_the_missing_rescind_reason_at_priority_9
    """
    setup = a_rescission_built_from_a_version_the_checklist_moved_on
    rescinded = get_success_data(setup["rescinded"])
    assert_bundle_activation(rescinded)
    assert rescinded["status"] == "RESCINDED"
    assert rescinded["on_time_step_count"] == 0
    assert rescinded["late_step_count"] == 0
    assert rescinded["missed_step_count"] == 0
    assert rescinded["timeliness_score"] is None
    assert rescinded["sequence_adjusted_score"] is None
    assert rescinded["rescind_reason"] == RESCIND_REASON
