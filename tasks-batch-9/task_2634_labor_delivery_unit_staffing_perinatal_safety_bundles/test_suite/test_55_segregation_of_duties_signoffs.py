"""Two sign-offs refused to the very people who did the work underneath them.

Neither caller is refused for wearing the wrong hat: both hold the officer role,
so the authorisation band passes and only the identity comparison fails. Each
refusal is then re-run under a different acting identity on the identical payload
and identical record state, which is the only way to show that the first answer
was about who was asking. The bundle probe is the declared conflict pair — the
duty band is checked before the clinical band, so a caller who documented a step
is told about the duty and never about the score.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_bundle_activation,
    assert_drill,
    assert_instant_equals,
    assert_obstetric_unit,
    assert_staff_member,
    bootstrap_unit,
    checklist_items_by_code,
    create_active_shift,
    create_encounter,
    get_success_data,
    set_clock,
)

CLOCK_SCHEDULING = "2026-08-01T05:45:00Z"
CLOCK_DRILL_DUE = "2026-08-01T05:50:00Z"
CLOCK_DOCUMENTED = "2026-08-01T06:00:00Z"
DRILL_SCHEDULED_FOR = "2026-08-01T05:50:00Z"
SIMULATED_DECISION_AT = "2026-08-01T05:50:00Z"
SIMULATED_INCISION_AT = "2026-08-01T06:00:00Z"
EXPIRES_NINETY_DAYS_ON = "2026-10-30T06:00:00Z"
CHARGE_SHIFT = ("2026-08-01T05:45:00Z", "2026-08-01T13:45:00Z")
LIVE_CREDENTIAL = "2027-01-01T00:00:00Z"
MEASURED_MINUTES = 10
DRILL_PASS_CEILING = 30
ACTIVATION_QBL = 1200
STAGE_TWO_QBL = 1500
RESOLUTION_QBL = 1500
APPLICABLE_ITEMS = 3
PERFECT_SCORE = 100.0
DEBRIEF_NOTES = (
    "Hemorrhage bundle reviewed at the bedside with the whole team; every gate-one "
    "and gate-two step landed inside its cumulative allowance and no transfusion was "
    "required."
)

PEMBERLY_STAFF = {
    "charge": {
        "full_name": "Rosalind Twickenham RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "ob": {
        "full_name": "Ignatius Bellweather MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "anesthesia": {
        "full_name": "Sunniva Kastellan MD",
        "staff_role": "ANESTHESIOLOGIST",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
    "officer": {
        "full_name": "Perpetua Lindenmayer RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def two_sign_offs_refused_to_the_people_who_did_the_work():
    """One documented drill and one hemorrhage bundle walked to its debrief.

    The charge nurse's `ACTIVE` `CHARGE` entry is what lets her document the
    checklist steps without ever holding a care assignment, and it is also what makes
    her the barred signatory afterwards. No `OR_STANDBY` entry exists anywhere on the
    unit, which pins the post-validation readiness one rung below `READY`.
    """
    world = bootstrap_unit(
        clock=CLOCK_SCHEDULING,
        ldr_beds=4,
        or_rooms=2,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=PEMBERLY_STAFF,
        unit_overrides={"unit_name": "Pemberly Hollow Womens Hospital LDR"},
    )
    create_active_shift(world, "charge", "CHARGE", *CHARGE_SHIFT)
    encounter = create_encounter(
        world,
        patient_record_code="PRC-PEMB-7701",
        parity=2,
        gestational_age_weeks=39,
    )
    drill = get_success_data(
        api_client.create_drill(
            world.unit_id,
            {
                "drill_type": "DECISION_TO_INCISION",
                "scheduled_for_utc": DRILL_SCHEDULED_FOR,
                "participant_staff_ids": [
                    world.staff_id("ob"),
                    world.staff_id("anesthesia"),
                ],
            },
            world.anesthesia_headers,
        )
    )
    set_clock(CLOCK_DRILL_DUE)
    get_success_data(api_client.start_drill(drill["id"], world.charge_headers))
    set_clock(CLOCK_DOCUMENTED)
    documented = get_success_data(
        api_client.document_drill(
            drill["id"],
            {
                "decision_at": SIMULATED_DECISION_AT,
                "incision_at": SIMULATED_INCISION_AT,
                "documented_by_staff_id": world.staff_id("anesthesia"),
            },
            world.anesthesia_headers,
        )
    )
    activation = get_success_data(
        api_client.create_activation(
            {
                "encounter_id": encounter["id"],
                "bundle_type": "OBSTETRIC_HEMORRHAGE",
                "activation_trigger": "QBL_THRESHOLD",
                "quantitative_blood_loss_ml": ACTIVATION_QBL,
            },
            world.ob_headers,
        )
    )
    items = checklist_items_by_code(world, activation)

    def _complete(step_code):
        return get_success_data(
            api_client.complete_checklist_item(
                activation["id"],
                items[step_code]["id"],
                {
                    "completed_at": CLOCK_DOCUMENTED,
                    "performed_by_staff_id": world.staff_id("charge"),
                },
                world.charge_headers,
            )
        )

    _complete("QBL_MEASURE")
    _complete("UTEROTONIC_GIVEN")
    get_success_data(
        api_client.escalate_stage(
            activation["id"],
            {"target_stage": 2, "quantitative_blood_loss_ml": STAGE_TWO_QBL},
            world.ob_headers,
        )
    )
    _complete("TYPE_AND_SCREEN")
    resolved = get_success_data(
        api_client.resolve_activation(
            activation["id"],
            {"quantitative_blood_loss_ml": RESOLUTION_QBL},
            world.ob_headers,
        )
    )
    close_by_the_performer = api_client.close_debrief(
        activation["id"], {"debrief_notes": DEBRIEF_NOTES}, world.officer_headers_for("charge")
    )
    activation_after_the_refusal = get_success_data(
        api_client.get_activation(activation["id"], world.ob_headers)
    )
    close_by_a_bystander = api_client.close_debrief(
        activation["id"], {"debrief_notes": DEBRIEF_NOTES}, world.officer_headers
    )
    validate_by_the_documenter = api_client.validate_drill(
        drill["id"], world.officer_headers_for("anesthesia")
    )
    drill_after_the_refusal = get_success_data(
        api_client.get_drill(drill["id"], world.officer_headers)
    )
    validate_by_a_bystander = api_client.validate_drill(drill["id"], world.officer_headers)
    participants_at_the_end = {
        key: get_success_data(
            api_client.get_staff_member(world.staff_id(key), world.charge_headers)
        )
        for key in ("ob", "anesthesia")
    }
    return {
        "world": world,
        "encounter": encounter,
        "drill": drill,
        "documented": documented,
        "activation": activation,
        "items": items,
        "resolved": resolved,
        "close_by_the_performer": close_by_the_performer,
        "activation_after_the_refusal": activation_after_the_refusal,
        "close_by_a_bystander": close_by_a_bystander,
        "validate_by_the_documenter": validate_by_the_documenter,
        "drill_after_the_refusal": drill_after_the_refusal,
        "validate_by_a_bystander": validate_by_a_bystander,
        "participants_at_the_end": participants_at_the_end,
        "unit_at_the_end": world.reload_unit(),
    }


def test_the_drill_is_documented_as_a_comfortable_pass(
    two_sign_offs_refused_to_the_people_who_did_the_work,
):
    """"`measured_d2i_minutes` is computed by the same truncating rule as a real event: the
    elapsed seconds from `decision_at` to `incision_at` divided by 60 with the remainder
    discarded."

    Design: Corner/rbac/sod_1_and_sod_2_refuse_the_checklist_performer_and_the_drill_documenter_wearing_the_officer_role
    """
    setup = two_sign_offs_refused_to_the_people_who_did_the_work
    documented = setup["documented"]
    assert_drill(documented)
    assert documented["status"] == "DOCUMENTED"
    assert documented["measured_d2i_minutes"] == MEASURED_MINUTES
    assert MEASURED_MINUTES <= DRILL_PASS_CEILING
    assert documented["documented_by_staff_id"] == setup["world"].staff_id("anesthesia")
    assert documented["revision_count"] == 0


def test_the_bundle_lands_in_its_debrief_with_a_computed_score(
    two_sign_offs_refused_to_the_people_who_did_the_work,
):
    """"Reaching `CONTROLLED` voids to `NOT_APPLICABLE` every still-`PENDING` item whose
    `stage_gate` was never reached, then computes both scores, then — in the very same
    request — moves the activation on from `CONTROLLED` to `DEBRIEF_PENDING` if
    `missed_step_count` is 1 or more, or `late_step_count` is 2 or more, or
    `highest_stage_reached` is 2 or more."

    Design: Corner/rbac/sod_1_and_sod_2_refuse_the_checklist_performer_and_the_drill_documenter_wearing_the_officer_role
    """
    setup = two_sign_offs_refused_to_the_people_who_did_the_work
    resolved = setup["resolved"]
    assert_bundle_activation(resolved)
    assert resolved["status"] == "DEBRIEF_PENDING"
    assert resolved["highest_stage_reached"] == 2
    assert resolved["on_time_step_count"] == APPLICABLE_ITEMS
    assert resolved["late_step_count"] == 0
    assert resolved["missed_step_count"] == 0
    assert resolved["timeliness_score"] == pytest.approx(PERFECT_SCORE, abs=1e-9)


def test_the_clinician_who_documented_the_steps_cannot_sign_them_off(
    two_sign_offs_refused_to_the_people_who_did_the_work,
):
    """"The acting `X-User-ID` must not match any `performed_by_staff_id` recorded on this
    activation's checklist items — nobody signs off the review of steps they documented
    themselves — refused otherwise with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`." Also: "A
    clinician who steps into the `PerinatalSafetyOfficer` role in order to perform a
    sign-off is still the same individual who performed the step, and is still refused."

    Design: Corner/rbac/sod_1_and_sod_2_refuse_the_checklist_performer_and_the_drill_documenter_wearing_the_officer_role
    """
    setup = two_sign_offs_refused_to_the_people_who_did_the_work
    refused = setup["close_by_the_performer"]
    validate_error(
        refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value, 403
    )
    reported = refused.json()["data"]["error_id"]
    assert reported != ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value
    assert reported != ApiErrorId.ERR_BUNDLE_SCORE_NOT_COMPUTED.value
    assert reported != ApiErrorId.ERR_INVALID_STATE_TRANSITION.value


def test_the_refused_close_wrote_nothing_at_all(
    two_sign_offs_refused_to_the_people_who_did_the_work,
):
    """"**Priority 10** — segregation of duties, `ERR_SEGREGATION_OF_DUTIES_VIOLATION` at
    HTTP 403, on bundle debrief closure, drill validation, review debrief scheduling, review
    rework request, review closure, emergency cesarean closure and snapshot certification."

    Design: Corner/rbac/sod_1_and_sod_2_refuse_the_checklist_performer_and_the_drill_documenter_wearing_the_officer_role
    """
    setup = two_sign_offs_refused_to_the_people_who_did_the_work
    survivor = setup["activation_after_the_refusal"]
    assert_bundle_activation(survivor)
    assert survivor["status"] == "DEBRIEF_PENDING"
    assert survivor["timeliness_score"] == pytest.approx(PERFECT_SCORE, abs=1e-9)
    assert survivor["highest_stage_reached"] == 2


def test_the_identical_payload_closes_under_a_bystander_identity(
    two_sign_offs_refused_to_the_people_who_did_the_work,
):
    """"A `PerinatalSafetyOfficer` closes the activation from either `CONTROLLED` or
    `DEBRIEF_PENDING`, landing on `CLOSED`."

    Design: Corner/rbac/sod_1_and_sod_2_refuse_the_checklist_performer_and_the_drill_documenter_wearing_the_officer_role
    """
    setup = two_sign_offs_refused_to_the_people_who_did_the_work
    accepted = setup["close_by_a_bystander"]
    assert accepted.status_code == 200
    closed = get_success_data(accepted)
    assert_bundle_activation(closed)
    assert closed["status"] == "CLOSED"
    assert closed["timeliness_score"] == pytest.approx(PERFECT_SCORE, abs=1e-9)


def test_the_clinician_who_documented_the_drill_cannot_validate_it(
    two_sign_offs_refused_to_the_people_who_did_the_work,
):
    """"This requires `measured_d2i_minutes` to be less than or equal to 30, with exactly 30
    passing, refused otherwise with `ERR_DRILL_PERFORMANCE_FAILED`, and requires the acting
    `X-User-ID` to differ from `documented_by_staff_id`, refused otherwise with
    `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."

    Design: Corner/rbac/sod_1_and_sod_2_refuse_the_checklist_performer_and_the_drill_documenter_wearing_the_officer_role
    """
    setup = two_sign_offs_refused_to_the_people_who_did_the_work
    refused = setup["validate_by_the_documenter"]
    validate_error(
        refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value, 403
    )
    reported = refused.json()["data"]["error_id"]
    assert reported != ApiErrorId.ERR_DRILL_PERFORMANCE_FAILED.value
    assert reported != ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value


def test_the_refused_validation_left_the_drill_unstamped(
    two_sign_offs_refused_to_the_people_who_did_the_work,
):
    """"Second, a clinician recorded as the documenter of a readiness drill may never
    validate that drill." Also: "A clinician who steps into the `PerinatalSafetyOfficer` role
    in order to perform a sign-off is still the same individual who performed the step, and
    is still refused."

    Design: Corner/rbac/sod_1_and_sod_2_refuse_the_checklist_performer_and_the_drill_documenter_wearing_the_officer_role
    """
    setup = two_sign_offs_refused_to_the_people_who_did_the_work
    survivor = setup["drill_after_the_refusal"]
    assert_drill(survivor)
    assert survivor["status"] == "DOCUMENTED"
    assert survivor["validated_at"] is None
    assert survivor["expires_at"] is None
    assert survivor["validated_by_user_id"] is None


def test_a_bystander_officer_validates_the_same_measurement(
    two_sign_offs_refused_to_the_people_who_did_the_work,
):
    """"Validation sets `validated_at` to the current instant, `expires_at` to `validated_at`
    plus 90 days, and `validated_by_user_id` to the acting user; it stamps every
    participant's `last_validated_drill_at` with the drill's simulated `decision_at` and
    moves each participant's `drill_currency_state` from `LAPSED` to `CURRENT`."

    Design: Corner/rbac/sod_1_and_sod_2_refuse_the_checklist_performer_and_the_drill_documenter_wearing_the_officer_role
    """
    setup = two_sign_offs_refused_to_the_people_who_did_the_work
    world = setup["world"]
    accepted = setup["validate_by_a_bystander"]
    assert accepted.status_code == 200
    validated = get_success_data(accepted)
    assert_drill(validated)
    assert validated["status"] == "VALIDATED"
    assert_instant_equals(validated["validated_at"], CLOCK_DOCUMENTED, "validated_at")
    assert_instant_equals(validated["expires_at"], EXPIRES_NINETY_DAYS_ON, "expires_at")
    assert validated["validated_by_user_id"] == world.staff_id("officer")


def test_the_barred_documenter_still_collects_the_currency(
    two_sign_offs_refused_to_the_people_who_did_the_work,
):
    """"Currency is granted by exactly one act in the entire system — the validation of a
    readiness drill — and by nothing else."

    Design: Corner/rbac/sod_1_and_sod_2_refuse_the_checklist_performer_and_the_drill_documenter_wearing_the_officer_role
    """
    setup = two_sign_offs_refused_to_the_people_who_did_the_work
    participants = setup["participants_at_the_end"]
    assert len(participants) == 2
    for member in participants.values():
        assert_staff_member(member)
        assert member["drill_currency_state"] == "CURRENT"
        assert_instant_equals(
            member["last_validated_drill_at"],
            SIMULATED_DECISION_AT,
            "last_validated_drill_at",
        )


def test_the_validated_drill_lifts_the_unit_only_as_far_as_degraded(
    two_sign_offs_refused_to_the_people_who_did_the_work,
):
    """"The state is then decided by the first matching branch: `NOT_READY` when the current
    drill is null, or when the mean is non-null and strictly greater than 45.00; otherwise
    `DEGRADED` when the standby test is not satisfied, or when the mean is non-null and
    strictly greater than 30.00; otherwise `READY`."

    Design: Corner/rbac/sod_1_and_sod_2_refuse_the_checklist_performer_and_the_drill_documenter_wearing_the_officer_role
    """
    setup = two_sign_offs_refused_to_the_people_who_did_the_work
    unit = setup["unit_at_the_end"]
    assert_obstetric_unit(unit)
    assert unit["cesarean_readiness_state"] == "DEGRADED"
    assert unit["mean_d2i_minutes"] is None
    assert unit["current_drill_id"] == setup["documented"]["id"]
    assert_instant_equals(
        unit["current_drill_expires_at"], EXPIRES_NINETY_DAYS_ON, "current_drill_expires_at"
    )
