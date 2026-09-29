"""Ostomy education: one error code standing guard over three unrelated
preconditions on two endpoints, and the double state hop that still moves the
patient's follow-up counter exactly once."""
from test_helpers import (
    as_instant,
    assert_ostomy_education_plan,
    assign_consult,
    create_candidate_nurse,
    create_consult,
    create_ostomy_education_plan_payload,
    create_patient,
    create_unit,
    education_session_payload,
    file_assessment,
    get_success_data,
    transition_supplies_payload,
    triage_consult,
    validate_error,
    validate_success,
)
from test_helpers.test_users import make_director_headers, make_nurse_headers


DIRECTOR = make_director_headers()


def _plan(api, plan_id):
    """Re-read one education plan."""
    return get_success_data(api.get_ostomy_education_plan(plan_id, DIRECTOR))


def _patient(api, patient_id):
    """Re-read one patient."""
    return get_success_data(api.get_patient(patient_id, DIRECTOR))


def test_a_stoma_an_ostomy_consult_and_a_future_visit_are_three_separate_gates(api):
    """One code, three preconditions, and 2026-08-01T00:00:00Z is not in the future.

    PRD §3.9: "Three eligibility conditions apply and all three surface as
    `ERR_OSTOMY_PLAN_NOT_ELIGIBLE`: the patient's `ostomy_present` must be true,
    the consult's `consult_type` must be `OSTOMY`, and — on the later supply
    transition — the booked appointment must be in the future."
    PRD §3.9: "A new plan starts with `status` `ACTIVE`, `sessions_completed` 0,
    `teach_back_score` null, `supply_transition_status` `PENDING` and
    `followup_appointment_at` null."
    PRD §3.9: "Whether the plan advances depends on the score: a score of 80 or
    higher moves the plan `ACTIVE → TEACH_BACK_PASSED`, while a score below 80
    leaves the plan at `ACTIVE` — the session still counts and the score is still
    recorded, but the teaching is not yet done, and further sessions may be
    recorded until the patient passes."
    PRD §3.9: "The nurse supplies a `followup_appointment_at` instant that must be
    strictly later than the logical clock; booking a follow-up in the past or
    exactly at the current instant is refused."
    PRD §3.9: "That counter increment is a consequence of the appointment being
    booked and is applied exactly once per plan — never twice, even though two
    state advances occur in the one request."

    Design: Corner/validations/ostomy_plan_rejects_non_ostomy_patient_and_backdated_followup
    """
    unit = create_unit(
        api=api, unit_code="3E", name="Three East", bed_count=18,
        rental_budget_cap_cents=0,
    )
    nurse = create_candidate_nurse(unit, api=api, full_name="Nina Stage")
    nurse_headers = make_nurse_headers(nurse["id"])

    without_stoma = create_patient(
        unit,
        api=api,
        mrn="MRN-X1",
        admitted_at="2026-07-31T00:00:00Z",
        ostomy_present=False,
    )
    with_stoma = create_patient(
        unit,
        api=api,
        mrn="MRN-X2",
        admitted_at="2026-07-31T00:00:00Z",
        ostomy_present=True,
    )
    assert without_stoma["ostomy_present"] is False
    assert with_stoma["ostomy_present"] is True

    ostomy_consult_wrong_patient = create_consult(
        unit,
        without_stoma,
        api=api,
        consult_type="OSTOMY",
        reported_stage="MUCOSAL",
        clinical_note="Charge nurse suspects a stoma issue.",
    )
    wound_consult_right_patient = create_consult(
        unit,
        with_stoma,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_2",
        clinical_note="Sacral wound alongside the established colostomy.",
    )
    eligible_consult = create_consult(
        unit,
        with_stoma,
        api=api,
        consult_type="OSTOMY",
        reported_stage="MUCOSAL",
        clinical_note="Peristomal irritation with frequent pouch leaks.",
    )
    for consult in (
        ostomy_consult_wrong_patient,
        wound_consult_right_patient,
        eligible_consult,
    ):
        triage_consult(consult, nurse, api=api)
        assign_consult(consult, nurse, api=api)

    file_assessment(
        ostomy_consult_wrong_patient,
        without_stoma,
        nurse,
        api=api,
        anatomic_location="OTHER",
        observed_stage="MUCOSAL",
        measured_area_cm2=2,
    )
    file_assessment(
        wound_consult_right_patient,
        with_stoma,
        nurse,
        api=api,
        anatomic_location="SACRUM",
        observed_stage="STAGE_2",
        measured_area_cm2=6,
    )
    file_assessment(
        eligible_consult,
        with_stoma,
        nurse,
        api=api,
        anatomic_location="OTHER",
        observed_stage="MUCOSAL",
        measured_area_cm2=2,
    )

    no_stoma_attempt = api.create_ostomy_education_plan(
        create_ostomy_education_plan_payload(
            ostomy_consult_wrong_patient["id"], without_stoma["id"]
        ),
        nurse_headers,
    )
    validate_error(no_stoma_attempt, "ERR_OSTOMY_PLAN_NOT_ELIGIBLE", expected_status=422)

    wrong_type_attempt = api.create_ostomy_education_plan(
        create_ostomy_education_plan_payload(
            wound_consult_right_patient["id"], with_stoma["id"]
        ),
        nurse_headers,
    )
    validate_error(
        wrong_type_attempt, "ERR_OSTOMY_PLAN_NOT_ELIGIBLE", expected_status=422
    )

    plan = validate_success(
        api.create_ostomy_education_plan(
            create_ostomy_education_plan_payload(
                eligible_consult["id"], with_stoma["id"]
            ),
            nurse_headers,
        ),
        expected_status=201,
    )
    assert_ostomy_education_plan(plan)
    assert plan["status"] == "ACTIVE"
    assert plan["sessions_completed"] == 0
    assert plan["teach_back_score"] is None
    assert plan["supply_transition_status"] == "PENDING"
    assert plan["followup_appointment_at"] is None

    passed = validate_success(
        api.create_education_session(
            plan["id"], education_session_payload(80), nurse_headers
        )
    )
    assert passed["sessions_completed"] == 1
    assert passed["teach_back_score"] == 80
    assert passed["status"] == "TEACH_BACK_PASSED", (
        "a score of 80 or higher passes, so the pass mark is inclusive"
    )

    booked_on_the_clock = api.transition_supplies(
        plan["id"],
        transition_supplies_payload("2026-08-01T00:00:00Z"),
        nurse_headers,
    )
    validate_error(
        booked_on_the_clock, "ERR_OSTOMY_PLAN_NOT_ELIGIBLE", expected_status=422
    )
    stalled = _plan(api, plan["id"])
    assert stalled["status"] == "TEACH_BACK_PASSED"
    assert stalled["supply_transition_status"] == "PENDING"
    assert stalled["followup_appointment_at"] is None
    assert _patient(api, with_stoma["id"])["pending_outpatient_followup_count"] == 0

    transitioned = validate_success(
        api.transition_supplies(
            plan["id"],
            transition_supplies_payload("2026-08-15T00:00:00Z"),
            nurse_headers,
        )
    )
    assert transitioned["supply_transition_status"] == "TRANSITIONED"
    assert as_instant(transitioned["followup_appointment_at"]) == as_instant(
        "2026-08-15T00:00:00Z"
    )
    assert transitioned["status"] == "FOLLOWUP_SCHEDULED", (
        "the transition hop is immediately followed by the system's own hop"
    )
    assert _patient(api, with_stoma["id"])["pending_outpatient_followup_count"] == 1, (
        "two state advances in the one request still count the appointment once"
    )
