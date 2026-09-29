"""One hemorrhage bundle walked from a refused activation to a blocked stage three.

Every refusal here is gated by a different rung of the same endpoint family, and
the order between the rungs is the point. With a gate-one step still pending the
checklist rung answers even though the supplied blood loss already clears the
stage threshold; once the steps are terminal the identical call with a smaller
figure flips to the clinical rung. The theatre-staffing rung is only observable
after every gate-two step is terminal, and the resolution rung compares the new
figure against the reading supplied at stage two rather than the one that opened
the bundle.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_error_is_one_of

from test_helpers import (
    ApiErrorId,
    api_client,
    activate_shift,
    assert_bundle_activation,
    assert_checklist_item,
    assert_labor_encounter,
    assert_obstetric_unit,
    bootstrap_unit,
    checklist_items_by_code,
    create_encounter,
    create_shift,
    get_success_data,
    reload_activation,
    reload_encounter,
)

CLOCK_START = "2026-08-01T06:00:00Z"
SHIFT_WINDOW = ("2026-08-01T05:00:00Z", "2026-08-01T15:00:00Z")
LIVE_CREDENTIAL = "2027-06-30T00:00:00Z"
BELOW_ACTIVATION_THRESHOLD = 900
ACTIVATION_READING = 1200
BELOW_STAGE_TWO_THRESHOLD = 1400
STAGE_TWO_READING = 1600
STAGE_THREE_READING = 2600
RISING_READING = 1700
ONE_TO_ONE_UNITS = 4.0

BRAMBLEWOOD_STAFF = {
    "charge": {
        "full_name": "Wren Kalinowski RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "ob": {
        "full_name": "Dr Ottoline Marsh",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
}


def _hemorrhage(encounter_id, blood_loss):
    return {
        "encounter_id": encounter_id,
        "bundle_type": "OBSTETRIC_HEMORRHAGE",
        "activation_trigger": "QBL_THRESHOLD",
        "quantitative_blood_loss_ml": blood_loss,
    }


@pytest.fixture
def one_bundle_pushed_against_every_rung():
    """The clock never moves, so every completion lands on its own activation instant.

    The performer holds an ACTIVE `CHARGE` roster entry and no care assignment,
    which is what makes her a legal performer while leaving her load at zero. No
    OR_STANDBY entry exists anywhere on the unit, which is what makes the stage
    three probe reachable.
    """
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=3,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR")],
        staff_specs=BRAMBLEWOOD_STAFF,
        unit_overrides={"unit_name": "Bramblewood Regional Maternity LDR"},
    )
    charge_shift = activate_shift(
        world, create_shift(world, "charge", "CHARGE", *SHIFT_WINDOW)
    )
    encounter = create_encounter(
        world,
        patient_record_code="PRC-BRAM-5501",
        parity=2,
        gestational_age_weeks=39,
    )
    performer = world.staff_id("charge")

    def _complete(item):
        return api_client.complete_checklist_item(
            activation["id"],
            item["id"],
            {"completed_at": CLOCK_START, "performed_by_staff_id": performer},
            world.charge_headers,
        )

    def _escalate(target_stage, blood_loss):
        return api_client.escalate_stage(
            activation["id"],
            {
                "target_stage": target_stage,
                "quantitative_blood_loss_ml": blood_loss,
            },
            world.ob_headers,
        )

    below_threshold = api_client.create_activation(
        _hemorrhage(encounter["id"], BELOW_ACTIVATION_THRESHOLD), world.ob_headers
    )
    opened = api_client.create_activation(
        _hemorrhage(encounter["id"], ACTIVATION_READING), world.ob_headers
    )
    activation = get_success_data(opened)
    second_bundle = api_client.create_activation(
        _hemorrhage(encounter["id"], ACTIVATION_READING), world.ob_headers
    )
    items = checklist_items_by_code(world, activation)
    gate_two_too_early = _complete(items["TYPE_AND_SCREEN"])
    first_step = get_success_data(_complete(items["QBL_MEASURE"]))
    activation_after_first_step = reload_activation(world, activation["id"])
    sibling_still_pending = _escalate(2, STAGE_TWO_READING)
    second_step = get_success_data(_complete(items["UTEROTONIC_GIVEN"]))
    under_the_threshold = _escalate(2, BELOW_STAGE_TWO_THRESHOLD)
    stage_two = _escalate(2, STAGE_TWO_READING)
    encounter_at_stage_two = reload_encounter(world, encounter["id"])
    unit_at_stage_two = world.reload_unit()
    blocked_transfer = api_client.transfer_out_encounter(
        encounter["id"], {}, world.ob_headers
    )
    third_step = get_success_data(_complete(items["TYPE_AND_SCREEN"]))
    no_theatre_cover = _escalate(3, STAGE_THREE_READING)
    still_bleeding = api_client.resolve_activation(
        activation["id"], {"quantitative_blood_loss_ml": RISING_READING}, world.ob_headers
    )
    return {
        "world": world,
        "charge_shift": charge_shift,
        "encounter": encounter,
        "activation": activation,
        "items": items,
        "below_threshold": below_threshold,
        "opened": opened,
        "second_bundle": second_bundle,
        "gate_two_too_early": gate_two_too_early,
        "first_step": first_step,
        "activation_after_first_step": activation_after_first_step,
        "sibling_still_pending": sibling_still_pending,
        "second_step": second_step,
        "under_the_threshold": under_the_threshold,
        "stage_two": stage_two,
        "encounter_at_stage_two": encounter_at_stage_two,
        "unit_at_stage_two": unit_at_stage_two,
        "blocked_transfer": blocked_transfer,
        "third_step": third_step,
        "no_theatre_cover": no_theatre_cover,
        "still_bleeding": still_bleeding,
    }


def test_a_blood_loss_under_the_activation_threshold_is_refused(
    one_bundle_pushed_against_every_rung,
):
    """"`QBL_THRESHOLD` requires `quantitative_blood_loss_ml`, an integer no smaller
    than 0, to be 1000 or greater." "A trigger whose threshold is not met is refused
    with `ERR_ACTIVATION_CRITERIA_NOT_MET`."

    Design: Corner/errors/ten_hemorrhage_bundle_ids_walked_from_a_failed_activation_to_a_blocked_stage_three_escalation
    """
    setup = one_bundle_pushed_against_every_rung
    validate_error(
        setup["below_threshold"], ApiErrorId.ERR_ACTIVATION_CRITERIA_NOT_MET.value, 422
    )


def test_the_activation_that_clears_the_threshold_opens_with_nothing_scored(
    one_bundle_pushed_against_every_rung,
):
    """"The activation opens in `ACTIVATED` with `activated_at` at the current instant,
    `unit_id` denormalised from the encounter, `highest_stage_reached` at 0,
    `on_time_step_count`, `late_step_count` and `missed_step_count` at 0, both scores
    null and `rescind_reason` null."

    Design: Corner/errors/ten_hemorrhage_bundle_ids_walked_from_a_failed_activation_to_a_blocked_stage_three_escalation
    """
    setup = one_bundle_pushed_against_every_rung
    assert setup["opened"].status_code == 201
    activation = setup["activation"]
    assert_bundle_activation(activation)
    assert activation["status"] == "ACTIVATED"
    assert activation["highest_stage_reached"] == 0
    assert activation["on_time_step_count"] == 0
    assert activation["late_step_count"] == 0
    assert activation["missed_step_count"] == 0
    assert activation["timeliness_score"] is None
    assert activation["sequence_adjusted_score"] is None
    assert activation["rescind_reason"] is None
    assert activation["unit_id"] == setup["world"].unit_id


def test_a_second_live_bundle_of_the_same_type_is_refused(
    one_bundle_pushed_against_every_rung,
):
    """"At most one activation per encounter and `bundle_type` may sit in the six
    non-terminal statuses at a time; a second is refused with
    `ERR_BUNDLE_ALREADY_ACTIVE`."

    Design: Corner/errors/ten_hemorrhage_bundle_ids_walked_from_a_failed_activation_to_a_blocked_stage_three_escalation
    """
    setup = one_bundle_pushed_against_every_rung
    validate_error(
        setup["second_bundle"], ApiErrorId.ERR_BUNDLE_ALREADY_ACTIVE.value, 409
    )
    body = api_client.list_activations(
        setup["world"].ob_headers,
        params={"limit": 10, "encounter_id": setup["encounter"]["id"]},
    ).json()
    assert body["meta"]["total_count"] == 1
    assert [row["id"] for row in body["data"]] == [setup["activation"]["id"]]


def test_a_gate_two_step_cannot_be_completed_at_stage_zero(
    one_bundle_pushed_against_every_rung,
):
    """"The activation's `highest_stage_reached` must be at least the item's
    `stage_gate`, refused otherwise with `ERR_CHECKLIST_STAGE_NOT_REACHED` — with the
    deliberate exception that a gate-1 item may be completed while the activation is
    still `ACTIVATED`, since that first completion is what moves the activation
    forward."

    Design: Corner/errors/ten_hemorrhage_bundle_ids_walked_from_a_failed_activation_to_a_blocked_stage_three_escalation
    """
    setup = one_bundle_pushed_against_every_rung
    validate_error(
        setup["gate_two_too_early"],
        ApiErrorId.ERR_CHECKLIST_STAGE_NOT_REACHED.value,
        409,
    )
    gated = setup["items"]["TYPE_AND_SCREEN"]
    assert_checklist_item(gated)
    assert gated["stage_gate"] == 2
    assert gated["status"] == "PENDING"


def test_the_first_gate_one_step_lands_on_time_and_starts_the_stage(
    one_bundle_pushed_against_every_rung,
):
    """"The landing state is decided by the authoritative date alone: `completed_at` at
    or before `due_at_activation_anchored` yields `COMPLETED` and increments
    `on_time_step_count`, and the boundary instant counts as on time; `completed_at`
    strictly after it yields `LATE_COMPLETED` and increments `late_step_count`." "The
    first completion of a gate-1 item also moves the activation from `ACTIVATED` to
    `STAGE_1_IN_PROGRESS`, which floors the encounter at `TIER_III` and re-prices
    coverage; completing `MAGNESIUM_LOADED` on a hypertension bundle additionally sets
    `magnesium_infusion_active` to true, which forces one-to-one coverage and the whole
    cascade that follows from it."

    Design: Corner/errors/ten_hemorrhage_bundle_ids_walked_from_a_failed_activation_to_a_blocked_stage_three_escalation
    """
    setup = one_bundle_pushed_against_every_rung
    step = setup["first_step"]
    assert_checklist_item(step)
    assert step["step_code"] == "QBL_MEASURE"
    assert step["status"] == "COMPLETED"
    assert step["minutes_from_activation"] == 0
    started = setup["activation_after_first_step"]
    assert_bundle_activation(started)
    assert started["status"] == "STAGE_1_IN_PROGRESS"
    assert started["on_time_step_count"] == 1
    assert started["late_step_count"] == 0
    # Gate 1 is now reached: "The activation's `highest_stage_reached` must be at
    # least the item's `stage_gate`" with the exception granted only "while the
    # activation is still `ACTIVATED`", so the sibling gate-1 step completed
    # later in this same fixture needs the counter at 1 -- which is also the
    # value "while `highest_stage_reached` is 1 or less" presupposes.
    assert started["highest_stage_reached"] == 1


def test_a_pending_sibling_blocks_the_escalation_that_the_reading_would_allow(
    one_bundle_pushed_against_every_rung,
):
    """"Every checklist item of a lower gate must first be terminal — status
    `COMPLETED`, `LATE_COMPLETED` or `MISSED` — meaning stage 2 requires every gate-1
    item and stage 3 requires every item of gate 1 and gate 2; otherwise the escalation
    is refused with `ERR_CHECKLIST_STAGE_INCOMPLETE`." The same call carries a reading
    that already clears the stage-two threshold, so only the checklist rung can be
    speaking.

    Design: Corner/errors/ten_hemorrhage_bundle_ids_walked_from_a_failed_activation_to_a_blocked_stage_three_escalation
    """
    setup = one_bundle_pushed_against_every_rung
    refused = setup["sibling_still_pending"]
    validate_error(refused, ApiErrorId.ERR_CHECKLIST_STAGE_INCOMPLETE.value, 409)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_BUNDLE_STAGE_CRITERIA_NOT_MET.value
    )
    assert setup["items"]["UTEROTONIC_GIVEN"]["stage_gate"] == 1
    assert setup["second_step"]["status"] == "COMPLETED"


def test_a_reading_under_the_stage_two_threshold_is_refused_once_the_steps_are_terminal(
    one_bundle_pushed_against_every_rung,
):
    """"For an `OBSTETRIC_HEMORRHAGE` bundle the request must carry
    `quantitative_blood_loss_ml`, which must be 1500 or greater for stage 2 and 2500 or
    greater for stage 3; for a `SEVERE_HYPERTENSION` bundle stage 2 requires a second
    severe-range reading, supplied as `systolic_mmhg` or `diastolic_mmhg` — either one
    alone suffices — and stage 3 is unavailable to it entirely because massive
    transfusion belongs only to haemorrhage." "A threshold that is unmet, or a stage 3
    attempted on a hypertension bundle, is refused with
    `ERR_BUNDLE_STAGE_CRITERIA_NOT_MET`."

    Design: Corner/errors/ten_hemorrhage_bundle_ids_walked_from_a_failed_activation_to_a_blocked_stage_three_escalation
    """
    setup = one_bundle_pushed_against_every_rung
    refused = setup["under_the_threshold"]
    validate_error(refused, ApiErrorId.ERR_BUNDLE_STAGE_CRITERIA_NOT_MET.value, 422)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_CHECKLIST_STAGE_INCOMPLETE.value
    )


def test_the_reading_that_clears_the_threshold_raises_the_high_water_mark(
    one_bundle_pushed_against_every_rung,
):
    """"On success `highest_stage_reached` is set to `target_stage` and never decreases,
    which is what makes the newly gated items completable."

    Design: Corner/errors/ten_hemorrhage_bundle_ids_walked_from_a_failed_activation_to_a_blocked_stage_three_escalation
    """
    setup = one_bundle_pushed_against_every_rung
    assert setup["stage_two"].status_code == 200
    escalated = get_success_data(setup["stage_two"])
    assert_bundle_activation(escalated)
    assert escalated["status"] == "STAGE_2_ESCALATED"
    assert escalated["highest_stage_reached"] == 2
    assert escalated["timeliness_score"] is None


def test_stage_two_reprices_the_patient_and_freezes_the_units_inductions(
    one_bundle_pushed_against_every_rung,
):
    """"Stage 2 forces the encounter's acuity to `TIER_IV` and mandatory one-to-one
    coverage; stage 3 additionally mints an `EmergencyCesareanEvent` of urgency
    `CATEGORY_1_CRASH` in `DECISION_DECLARED` with `triggering_activation_id` set to this
    activation, and drives the unit to `DIVERT`, bumping every `CAPACITY_HELD` and
    `CONFIRMED` booking of the elective and patient-request classes and returning their
    beds from `HELD` to `AVAILABLE`." The third step produces
    `required_coverage_units`: "otherwise 4.0 when one-to-one coverage is required".

    Design: Corner/errors/ten_hemorrhage_bundle_ids_walked_from_a_failed_activation_to_a_blocked_stage_three_escalation
    """
    setup = one_bundle_pushed_against_every_rung
    encounter = setup["encounter_at_stage_two"]
    assert_labor_encounter(encounter)
    assert encounter["acuity_tier"] == "TIER_IV"
    assert encounter["one_to_one_required"] is True
    assert encounter["required_coverage_units"] == pytest.approx(
        ONE_TO_ONE_UNITS, abs=1e-9
    )
    assert encounter["assigned_coverage_units"] == pytest.approx(0.0, abs=1e-9)
    unit = setup["unit_at_stage_two"]
    assert_obstetric_unit(unit)
    assert unit["coverage_deficit_units"] == pytest.approx(ONE_TO_ONE_UNITS, abs=1e-9)
    assert unit["staffing_posture"] == "INDUCTION_FROZEN"


def test_a_stage_two_bundle_blocks_the_patient_from_being_transferred_out(
    one_bundle_pushed_against_every_rung,
):
    """"It is blocked while a cesarean event on the encounter is in `TEAM_MOBILIZED` or
    `INCISION_RECORDED`, with `ERR_CESAREAN_EVENT_IN_PROGRESS`, and then blocked while an
    activation is in `STAGE_2_ESCALATED` or `STAGE_3_MASSIVE_TRANSFUSION`, with
    `ERR_BUNDLE_STAGE_BLOCKS_TRANSFER`, in that order."

    Design: Corner/errors/ten_hemorrhage_bundle_ids_walked_from_a_failed_activation_to_a_blocked_stage_three_escalation
    """
    setup = one_bundle_pushed_against_every_rung
    refused = setup["blocked_transfer"]
    validate_error(refused, ApiErrorId.ERR_BUNDLE_STAGE_BLOCKS_TRANSFER.value, 409)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_CESAREAN_EVENT_IN_PROGRESS.value
    )
    still_here = reload_encounter(setup["world"], setup["encounter"]["id"])
    assert_labor_encounter(still_here)
    assert still_here["labor_phase"] == "ANTEPARTUM"


def test_stage_three_needs_a_staffed_theatre_and_says_so_only_at_the_last_rung(
    one_bundle_pushed_against_every_rung,
):
    """"Stage 3 further requires the unit to hold an `ACTIVE` `OR_STANDBY` roster entry,
    refused otherwise with `ERR_OR_STANDBY_NOT_STAFFED`." Every gate-two step is terminal
    and the reading clears 2500, so no earlier rung can answer instead.

    Design: Corner/errors/ten_hemorrhage_bundle_ids_walked_from_a_failed_activation_to_a_blocked_stage_three_escalation
    """
    setup = one_bundle_pushed_against_every_rung
    assert setup["third_step"]["status"] == "COMPLETED"
    assert setup["third_step"]["step_code"] == "TYPE_AND_SCREEN"
    refused = setup["no_theatre_cover"]
    validate_error(refused, ApiErrorId.ERR_OR_STANDBY_NOT_STAFFED.value, 422)
    reported = refused.json()["data"]["error_id"]
    assert reported != ApiErrorId.ERR_CHECKLIST_STAGE_INCOMPLETE.value
    assert reported != ApiErrorId.ERR_BUNDLE_STAGE_CRITERIA_NOT_MET.value
    assert setup["charge_shift"]["role_slot"] == "CHARGE"
    assert setup["charge_shift"]["status"] == "ACTIVE"


def test_a_rising_figure_is_not_a_controlled_bleed(
    one_bundle_pushed_against_every_rung,
):
    """"A haemorrhage resolution must carry `quantitative_blood_loss_ml`, and that figure
    must not be greater than the reading supplied at stage 2, since bleeding that is
    still increasing is not controlled; a greater figure is refused with
    `ERR_BUNDLE_NOT_CONTROLLED`." "Both scores stay null until the activation reaches
    `CONTROLLED`, and a timeliness report read exposes the two variants side by side with
    the per-item on-time and late classification under each anchoring."

    Design: Corner/errors/ten_hemorrhage_bundle_ids_walked_from_a_failed_activation_to_a_blocked_stage_three_escalation
    """
    setup = one_bundle_pushed_against_every_rung
    validate_error(
        setup["still_bleeding"], ApiErrorId.ERR_BUNDLE_NOT_CONTROLLED.value, 422
    )
    final = reload_activation(setup["world"], setup["activation"]["id"])
    assert_bundle_activation(final)
    assert final["status"] == "STAGE_2_ESCALATED"
    assert final["highest_stage_reached"] == 2
    assert final["on_time_step_count"] == 3
    assert final["late_step_count"] == 0
    assert final["missed_step_count"] == 0
    assert final["timeliness_score"] is None
    assert final["sequence_adjusted_score"] is None


def test_a_bundle_that_reached_stage_two_can_no_longer_be_erased(
    one_bundle_pushed_against_every_rung,
):
    """"A bundle that reached stage 2 or 3 is a real clinical event and must be closed
    rather than erased; an attempt is refused with `ERR_BUNDLE_STAGE_BLOCKS_RESCIND`."
    Rescission is declared only "from `ACTIVATED` or `STAGE_1_IN_PROGRESS`", so the
    refusal is one of the two guards priority 8 carries at 409.

    Design: Corner/errors/ten_hemorrhage_bundle_ids_walked_from_a_failed_activation_to_a_blocked_stage_three_escalation
    """
    setup = one_bundle_pushed_against_every_rung
    world = setup["world"]
    live = reload_activation(world, setup["activation"]["id"])
    refused = api_client.rescind_activation(
        live["id"],
        {
            "rescind_reason": "Charted in error during the corner sweep; expected to be refused.",
            "expected_activation_version": live["version"],
        },
        world.ob_headers,
    )
    assert refused.status_code == 409
    validate_error_is_one_of(
        refused,
        [
            ApiErrorId.ERR_BUNDLE_STAGE_BLOCKS_RESCIND.value,
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        ],
    )
    survivor = reload_activation(world, setup["activation"]["id"])
    assert survivor["status"] == "STAGE_2_ESCALATED"
    assert survivor["rescind_reason"] is None
    assert survivor["on_time_step_count"] == 3
    items = checklist_items_by_code(world, survivor)
    assert items["QBL_MEASURE"]["status"] == "COMPLETED"
    assert items["MTP_ACTIVATED"]["status"] == "PENDING"
