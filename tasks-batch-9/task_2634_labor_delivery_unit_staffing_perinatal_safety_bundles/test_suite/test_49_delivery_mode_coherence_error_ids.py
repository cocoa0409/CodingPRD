"""Four delivery-step preconditions violated one at a time, each repaired before the next.

The second-stage category gate is about a pair, not a reading: the identical
advance call is refused while a CATEGORY_III tracing stands alone and accepted
once a theatre event stands beside it, with no new interpretation in between. The
chain is deliberately stood down into a reassessment window first, so the
category refusal is not masked by the unresolved-escalation refusal. Above that
the delivery step is walked four times, each attempt fixing the clause that
answered last time, which is the only way to see all four in their declared
order on one encounter.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    activate_shift,
    assert_bed,
    assert_cesarean_event,
    assert_fetal_assessment,
    assert_instant_equals,
    assert_labor_encounter,
    assert_obstetric_unit,
    assign_bed,
    bootstrap_unit,
    create_care_assignment,
    create_encounter,
    create_shift,
    get_success_data,
    reload_encounter,
    set_clock,
    setup_validated_drill,
)

CLOCK_START = "2026-08-01T05:50:00Z"
CLOCK_AT_THE_DRILL_INCISION = "2026-08-01T06:00:00Z"
CLOCK_AFTER_THE_INCISION = "2026-08-01T06:10:00Z"
SHIFT_WINDOW = ("2026-08-01T05:00:00Z", "2026-08-01T15:00:00Z")
LIVE_CREDENTIAL = "2027-06-30T00:00:00Z"
CATEGORY_THREE_ESCALATION_DUE = "2026-08-01T06:05:00Z"
REASSESSMENT_DUE = "2026-08-01T06:30:00Z"
INCISION_INSTANT = "2026-08-01T06:05:00Z"
DELIVERY_INSTANT = "2026-08-01T06:08:00Z"
TURNOVER_CLEAR_AT = "2026-08-01T06:55:00Z"
OPEN_BUFFER = 45
MEASURED_MINUTES = 5
ONE_TO_ONE_UNITS = 4.0

QUILLFEATHER_STAFF = {
    "bedside": {
        "full_name": "Solveig Amundsen RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "charge": {
        "full_name": "Delphine Achterberg RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "ob": {
        "full_name": "Everard Blackwood MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
    "anesthesia": {
        "full_name": "Ingeborg Halvorsen MD",
        "staff_role": "ANESTHESIOLOGIST",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
    "tech": {
        "full_name": "Bartholomew Quintero ST",
        "staff_role": "SURGICAL_TECH",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
    "neonatal": {
        "full_name": "Cordelia Mwangi NNP",
        "staff_role": "NEONATAL_RESUSCITATOR",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "officer": {
        "full_name": "Ottilie Strand RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
}


def _reading(encounter_id, interpreter_id, category, baseline, variability, **extra):
    payload = {
        "encounter_id": encounter_id,
        "interpreted_by_staff_id": interpreter_id,
        "category": category,
        "baseline_rate_bpm": baseline,
        "variability": variability,
    }
    payload.update(extra)
    return payload


@pytest.fixture
def one_prior_cesarean_patient_walked_up_two_gates():
    """The standby entry is activated only after the drill is validated.

    Competency refuses to open an `OR_STANDBY` slot for a holder who is not yet
    drill-current, so the order matters: schedule, start, document and validate
    the drill first, and only then activate the anaesthetist's standby entry. That
    is what carries the unit to `READY`, which in turn keeps the posture `OPEN` and
    the turnover buffer at 45 minutes for the whole run.
    """
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR"), ("OR-01", "OR")],
        staff_specs=QUILLFEATHER_STAFF,
        unit_overrides={"unit_name": "Quillfeather Valley Womens Center LDR"},
    )
    bedside_shift = activate_shift(
        world, create_shift(world, "bedside", "BEDSIDE", *SHIFT_WINDOW)
    )
    activate_shift(world, create_shift(world, "charge", "CHARGE", *SHIFT_WINDOW))
    activate_shift(world, create_shift(world, "tech", "TRIAGE", *SHIFT_WINDOW))
    activate_shift(world, create_shift(world, "neonatal", "TRIAGE", *SHIFT_WINDOW))
    standby_shift = create_shift(world, "anesthesia", "OR_STANDBY", *SHIFT_WINDOW)
    drill = setup_validated_drill(
        world,
        scheduled_for_utc=CLOCK_START,
        decision_at=CLOCK_START,
        incision_at=CLOCK_AT_THE_DRILL_INCISION,
        documented_key="anesthesia",
        validator_key="officer",
        participant_keys=["ob", "anesthesia"],
        document_clock=CLOCK_AT_THE_DRILL_INCISION,
    )
    activate_shift(world, standby_shift)
    unit_after_the_drill = world.reload_unit()
    encounter = create_encounter(
        world,
        patient_record_code="PRC-QUIL-8801",
        parity=1,
        gestational_age_weeks=39,
        prior_cesarean=True,
    )
    assign_bed(world, encounter, "LDR-01")
    create_care_assignment(world, encounter, bedside_shift, coverage_mode="ONE_TO_ONE")
    interpreter = world.staff_id("charge")
    reassuring = get_success_data(
        api_client.create_assessment(
            _reading(encounter["id"], interpreter, "CATEGORY_I", 138, "MODERATE"),
            world.charge_headers,
        )
    )
    for target_phase in ("LATENT", "ACTIVE_FIRST_STAGE"):
        get_success_data(
            api_client.advance_phase(
                encounter["id"], {"target_phase": target_phase}, world.charge_headers
            )
        )
    ominous_response = api_client.create_assessment(
        _reading(
            encounter["id"],
            interpreter,
            "CATEGORY_III",
            102,
            "ABSENT",
            recurrent_decelerations=True,
        ),
        world.charge_headers,
    )
    ominous = get_success_data(ominous_response)
    get_success_data(
        api_client.escalate_assessment(
            ominous["id"],
            {"target_tier": 1, "notified_staff_id": interpreter},
            world.bedside_headers,
        )
    )
    stood_down = get_success_data(
        api_client.resolve_assessment(ominous["id"], {}, world.ob_headers)
    )

    def _advance(**payload):
        return api_client.advance_phase(encounter["id"], payload, world.ob_headers)

    no_theatre_event = _advance(target_phase="SECOND_STAGE")
    still_first_stage = reload_encounter(world, encounter["id"])
    event = get_success_data(
        api_client.create_cesarean(
            {
                "encounter_id": encounter["id"],
                "urgency_class": "CATEGORY_1_CRASH",
                "triggering_assessment_id": ominous["id"],
            },
            world.ob_headers,
        )
    )
    second_stage = _advance(target_phase="SECOND_STAGE")
    no_mode = _advance(target_phase="THIRD_STAGE_DELIVERED")
    event_not_delivered = _advance(
        target_phase="THIRD_STAGE_DELIVERED", delivery_mode="CESAREAN_REPEAT"
    )
    get_success_data(
        api_client.mobilize_team(
            event["id"],
            {
                "or_bed_id": world.bed_id("OR-01"),
                "staff_ids": [
                    world.staff_id("anesthesia"),
                    world.staff_id("tech"),
                    world.staff_id("neonatal"),
                ],
            },
            world.ob_headers,
        )
    )
    set_clock(CLOCK_AFTER_THE_INCISION)
    incised = get_success_data(
        api_client.record_incision(
            event["id"], {"incision_at": INCISION_INSTANT}, world.ob_headers
        )
    )
    delivered = get_success_data(
        api_client.record_delivery(
            event["id"], {"delivery_at": DELIVERY_INSTANT}, world.ob_headers
        )
    )
    after_the_delivery = reload_encounter(world, encounter["id"])
    theatre_bed = get_success_data(
        api_client.get_bed(world.bed_id("OR-01"), world.charge_headers)
    )
    wrong_history = _advance(
        target_phase="THIRD_STAGE_DELIVERED", delivery_mode="CESAREAN_PRIMARY"
    )
    wrong_episiotomy = _advance(
        target_phase="THIRD_STAGE_DELIVERED",
        delivery_mode="CESAREAN_REPEAT",
        episiotomy_performed=True,
    )
    before_the_last_attempt = reload_encounter(world, encounter["id"])
    third_stage = _advance(
        target_phase="THIRD_STAGE_DELIVERED", delivery_mode="CESAREAN_REPEAT"
    )
    return {
        "world": world,
        "drill": drill,
        "unit_after_the_drill": unit_after_the_drill,
        "encounter": encounter,
        "reassuring": reassuring,
        "ominous_response": ominous_response,
        "ominous": ominous,
        "stood_down": stood_down,
        "no_theatre_event": no_theatre_event,
        "still_first_stage": still_first_stage,
        "event": event,
        "second_stage": second_stage,
        "no_mode": no_mode,
        "event_not_delivered": event_not_delivered,
        "incised": incised,
        "delivered": delivered,
        "after_the_delivery": after_the_delivery,
        "theatre_bed": theatre_bed,
        "wrong_history": wrong_history,
        "wrong_episiotomy": wrong_episiotomy,
        "before_the_last_attempt": before_the_last_attempt,
        "third_stage": third_stage,
    }


def test_the_validated_drill_and_a_staffed_standby_open_the_unit(
    one_prior_cesarean_patient_walked_up_two_gates,
):
    """"The empty rolling window is not a failure: a unit with a current validated
    drill, standby staffed and no measured emergency events at all is `READY`."

    Design: Corner/errors/five_delivery_mode_coherence_ids_walked_up_the_second_and_third_stage_gates_on_a_prior_cesarean_encounter
    """
    setup = one_prior_cesarean_patient_walked_up_two_gates
    assert setup["drill"]["status"] == "VALIDATED"
    unit = setup["unit_after_the_drill"]
    assert_obstetric_unit(unit)
    assert unit["cesarean_readiness_state"] == "READY"
    assert unit["mean_d2i_minutes"] is None
    assert unit["current_drill_id"] == setup["drill"]["id"]
    assert unit["staffing_posture"] == "OPEN"
    assert unit["turnover_buffer_minutes"] == OPEN_BUFFER


def test_the_ominous_reading_supersedes_the_reassuring_one(
    one_prior_cesarean_patient_walked_up_two_gates,
):
    """"When the `category` is not `CATEGORY_I`, `escalation_due_at` is set to
    `assessed_at` plus 20 minutes for a `CATEGORY_II` reading and plus 5 minutes for a
    `CATEGORY_III` reading."

    Design: Corner/errors/five_delivery_mode_coherence_ids_walked_up_the_second_and_third_stage_gates_on_a_prior_cesarean_encounter
    """
    setup = one_prior_cesarean_patient_walked_up_two_gates
    assert setup["ominous_response"].status_code == 201
    ominous = setup["ominous"]
    assert_fetal_assessment(ominous)
    assert ominous["escalation_status"] == "ESCALATION_DUE"
    assert ominous["supersedes_assessment_id"] == setup["reassuring"]["id"]
    assert_instant_equals(
        ominous["escalation_due_at"],
        CATEGORY_THREE_ESCALATION_DUE,
        "escalation_due_at",
    )
    assert setup["reassuring"]["escalation_status"] == "NOT_REQUIRED"


def test_the_stood_down_chain_waits_in_a_reassessment_window(
    one_prior_cesarean_patient_walked_up_two_gates,
):
    """"It sets `reassessment_due_at` to the current instant plus 30 minutes and clears
    `next_tier_due_at` to null."

    Design: Corner/errors/five_delivery_mode_coherence_ids_walked_up_the_second_and_third_stage_gates_on_a_prior_cesarean_encounter
    """
    setup = one_prior_cesarean_patient_walked_up_two_gates
    stood_down = setup["stood_down"]
    assert_fetal_assessment(stood_down)
    assert stood_down["escalation_status"] == "REASSESSMENT_PENDING"
    assert stood_down["escalation_tier_high_water"] == 1
    assert stood_down["next_tier_due_at"] is None
    assert_instant_equals(
        stood_down["reassessment_due_at"], REASSESSMENT_DUE, "reassessment_due_at"
    )


def test_an_ominous_tracing_with_no_theatre_event_blocks_the_second_stage(
    one_prior_cesarean_patient_walked_up_two_gates,
):
    """"That assessment must be `CATEGORY_I` or `CATEGORY_II`, or else `CATEGORY_III`
    accompanied by a cesarean event on the encounter in `DECISION_DECLARED` or
    `TEAM_MOBILIZED`, refused otherwise with `ERR_FETAL_CATEGORY_BLOCKS_PHASE`."

    Design: Corner/errors/five_delivery_mode_coherence_ids_walked_up_the_second_and_third_stage_gates_on_a_prior_cesarean_encounter
    """
    setup = one_prior_cesarean_patient_walked_up_two_gates
    refused = setup["no_theatre_event"]
    validate_error(refused, ApiErrorId.ERR_FETAL_CATEGORY_BLOCKS_PHASE.value, 422)
    reported = refused.json()["data"]["error_id"]
    assert reported != ApiErrorId.ERR_FETAL_ESCALATION_UNRESOLVED.value
    assert reported != ApiErrorId.ERR_FETAL_ASSESSMENT_STALE.value
    assert reported != ApiErrorId.ERR_ONE_TO_ONE_COVERAGE_REQUIRED.value
    assert reported != ApiErrorId.ERR_CESAREAN_READINESS_NOT_MET.value
    stalled = setup["still_first_stage"]
    assert_labor_encounter(stalled)
    assert stalled["labor_phase"] == "ACTIVE_FIRST_STAGE"
    assert stalled["staffing_state"] == "ONE_TO_ONE_COVERED"


def test_the_declared_theatre_event_unlocks_the_identical_advance(
    one_prior_cesarean_patient_walked_up_two_gates,
):
    """"That same step then fires five consequences in a fixed order. The encounter's
    `acuity_tier` is floored at `TIER_III` and `one_to_one_required` becomes true."

    Design: Corner/errors/five_delivery_mode_coherence_ids_walked_up_the_second_and_third_stage_gates_on_a_prior_cesarean_encounter
    """
    setup = one_prior_cesarean_patient_walked_up_two_gates
    assert setup["event"]["status"] == "DECISION_DECLARED"
    assert setup["second_stage"].status_code == 200
    advanced = get_success_data(setup["second_stage"])
    assert_labor_encounter(advanced)
    assert advanced["labor_phase"] == "SECOND_STAGE"
    assert advanced["acuity_tier"] == "TIER_IV"
    assert advanced["one_to_one_required"] is True
    assert advanced["required_coverage_units"] == pytest.approx(
        ONE_TO_ONE_UNITS, abs=1e-9
    )
    assert advanced["assigned_coverage_units"] == pytest.approx(
        ONE_TO_ONE_UNITS, abs=1e-9
    )
    assert advanced["staffing_state"] == "ONE_TO_ONE_COVERED"


def test_the_delivery_step_will_not_guess_the_mode(
    one_prior_cesarean_patient_walked_up_two_gates,
):
    """"Moving `SECOND_STAGE` to `THIRD_STAGE_DELIVERED` requires `delivery_mode` to be
    supplied, refused otherwise with `ERR_DELIVERY_MODE_REQUIRED`, and accepts
    `episiotomy_performed` only on this step."

    Design: Corner/errors/five_delivery_mode_coherence_ids_walked_up_the_second_and_third_stage_gates_on_a_prior_cesarean_encounter
    """
    setup = one_prior_cesarean_patient_walked_up_two_gates
    validate_error(setup["no_mode"], ApiErrorId.ERR_DELIVERY_MODE_REQUIRED.value, 422)


def test_a_cesarean_mode_needs_an_event_that_actually_delivered(
    one_prior_cesarean_patient_walked_up_two_gates,
):
    """"A `delivery_mode` of `CESAREAN_PRIMARY` or `CESAREAN_REPEAT` requires a cesarean
    event on the encounter in `DELIVERED`, `REVIEW_PENDING` or `CLOSED`, refused
    otherwise with `ERR_CESAREAN_EVENT_NOT_DELIVERED`."

    Design: Corner/errors/five_delivery_mode_coherence_ids_walked_up_the_second_and_third_stage_gates_on_a_prior_cesarean_encounter
    """
    setup = one_prior_cesarean_patient_walked_up_two_gates
    refused = setup["event_not_delivered"]
    validate_error(refused, ApiErrorId.ERR_CESAREAN_EVENT_NOT_DELIVERED.value, 422)
    reported = refused.json()["data"]["error_id"]
    assert reported != ApiErrorId.ERR_DELIVERY_MODE_CONFLICTS_HISTORY.value
    assert reported != ApiErrorId.ERR_EPISIOTOMY_MODE_CONFLICT.value


def test_the_recorded_delivery_chooses_the_mode_itself_and_opens_a_review(
    one_prior_cesarean_patient_walked_up_two_gates,
):
    """"The system, not the caller, chooses the delivery mode: the encounter's
    `delivery_mode` becomes `CESAREAN_REPEAT` when its `prior_cesarean` is true and
    `CESAREAN_PRIMARY` otherwise, and `delivery_recorded_at` is set to `delivery_at`."

    Design: Corner/errors/five_delivery_mode_coherence_ids_walked_up_the_second_and_third_stage_gates_on_a_prior_cesarean_encounter
    """
    setup = one_prior_cesarean_patient_walked_up_two_gates
    assert setup["incised"]["decision_to_incision_minutes"] == MEASURED_MINUTES
    assert setup["incised"]["met_target"] is True
    delivered = setup["delivered"]
    assert_cesarean_event(delivered)
    assert delivered["status"] == "REVIEW_PENDING"
    encounter = setup["after_the_delivery"]
    assert_labor_encounter(encounter)
    assert encounter["prior_cesarean"] is True
    assert encounter["delivery_mode"] == "CESAREAN_REPEAT"
    assert encounter["review_required"] is True


def test_the_theatre_bed_turns_over_on_the_open_units_buffer(
    one_prior_cesarean_patient_walked_up_two_gates,
):
    """"The OR bed moves from `OCCUPIED` to `TURNOVER` with `turnover_clear_at` set to
    the current instant plus the unit's `turnover_buffer_minutes`."

    Design: Corner/errors/five_delivery_mode_coherence_ids_walked_up_the_second_and_third_stage_gates_on_a_prior_cesarean_encounter
    """
    setup = one_prior_cesarean_patient_walked_up_two_gates
    theatre = setup["theatre_bed"]
    assert_bed(theatre)
    assert theatre["status"] == "TURNOVER"
    assert_instant_equals(
        theatre["turnover_clear_at"], TURNOVER_CLEAR_AT, "turnover_clear_at"
    )
    assert setup["unit_after_the_drill"]["turnover_buffer_minutes"] == OPEN_BUFFER


def test_a_primary_cesarean_contradicts_a_prior_cesarean_history(
    one_prior_cesarean_patient_walked_up_two_gates,
):
    """"An encounter whose `prior_cesarean` is true may not be recorded as
    `CESAREAN_PRIMARY`, refused with `ERR_DELIVERY_MODE_CONFLICTS_HISTORY`."

    Design: Corner/errors/five_delivery_mode_coherence_ids_walked_up_the_second_and_third_stage_gates_on_a_prior_cesarean_encounter
    """
    setup = one_prior_cesarean_patient_walked_up_two_gates
    refused = setup["wrong_history"]
    validate_error(
        refused, ApiErrorId.ERR_DELIVERY_MODE_CONFLICTS_HISTORY.value, 422
    )
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_CESAREAN_EVENT_NOT_DELIVERED.value
    )


def test_an_episiotomy_cannot_accompany_a_cesarean(
    one_prior_cesarean_patient_walked_up_two_gates,
):
    """"An `episiotomy_performed` of true is coherent only with `SPONTANEOUS_VAGINAL` or
    `OPERATIVE_VAGINAL`, refused otherwise with `ERR_EPISIOTOMY_MODE_CONFLICT`."

    Design: Corner/errors/five_delivery_mode_coherence_ids_walked_up_the_second_and_third_stage_gates_on_a_prior_cesarean_encounter
    """
    setup = one_prior_cesarean_patient_walked_up_two_gates
    validate_error(
        setup["wrong_episiotomy"], ApiErrorId.ERR_EPISIOTOMY_MODE_CONFLICT.value, 422
    )
    unmoved = setup["before_the_last_attempt"]
    assert_labor_encounter(unmoved)
    assert unmoved["labor_phase"] == "SECOND_STAGE"
    assert unmoved["episiotomy_performed"] is False


def test_the_fourth_attempt_records_the_delivery_at_the_current_instant(
    one_prior_cesarean_patient_walked_up_two_gates,
):
    """"The step writes `delivery_recorded_at` as the current instant and recomputes
    every snapshot in `DRAFT` whose reporting window contains that instant, leaving
    snapshots in `CERTIFIED` or `SUPERSEDED` untouched."

    Design: Corner/errors/five_delivery_mode_coherence_ids_walked_up_the_second_and_third_stage_gates_on_a_prior_cesarean_encounter
    """
    setup = one_prior_cesarean_patient_walked_up_two_gates
    assert setup["third_stage"].status_code == 200
    delivered = get_success_data(setup["third_stage"])
    assert_labor_encounter(delivered)
    assert delivered["labor_phase"] == "THIRD_STAGE_DELIVERED"
    assert delivered["delivery_mode"] == "CESAREAN_REPEAT"
    assert delivered["episiotomy_performed"] is False
    assert_instant_equals(
        delivered["delivery_recorded_at"],
        CLOCK_AFTER_THE_INCISION,
        "delivery_recorded_at",
    )
