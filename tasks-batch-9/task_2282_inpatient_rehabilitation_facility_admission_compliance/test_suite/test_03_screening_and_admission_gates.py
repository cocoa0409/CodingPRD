"""The screening revision loop and the gates guarding admission opening."""

from test_helpers import (
    OFFICER_HEADERS,
    ApiErrorId,
    admit_admission_payload,
    api_client,
    create_admission_payload,
    create_concurred_screening,
    create_draft_screening,
    open_admission,
    read_admission,
    read_facility,
    read_screening,
    register_patient,
    review_screening,
    setup_facility_with_staff,
    setup_frozen_facility,
    submit_screening,
    validate_error,
    validate_paginated,
    validate_success,
)

PATIENT_B = {"mrn": "MRN-B", "full_name": "Bo Whitaker"}


def test_editing_a_changes_requested_screening_returns_it_to_draft():
    """The edit rewinds the review and counts the revision.

    PRD §3.2: "Editing a screening in `CHANGES_REQUESTED` returns it to
    `DRAFT`, increases `revision_count` by 1, and clears both
    `reviewed_by_clinician_id` and `reviewed_at` back to null — the revision
    loop `DRAFT` → `SUBMITTED` → `CHANGES_REQUESTED` → `DRAFT` may repeat as
    often as the window allows."

    Design: Difficulty/non_linear_state_machine/screening_revision_cycle_returns_to_draft_and_reconcurs
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    patient = register_patient(env)
    screening = create_draft_screening(env, patient["id"])
    submit_screening(env, screening["id"])
    review_screening(env, screening["id"], "REQUEST_CHANGES",
                     reviewer_note="Document prior functional level in detail")

    response = api_client.patch_screening(
        screening["id"],
        {"expected_admission_at": "2026-08-05T09:00:00Z"},
        env["nurse_headers"],
    )

    revised = validate_success(response, expected_status=200)
    assert revised["status"] == "DRAFT"
    assert revised["revision_count"] == 1
    assert revised["reviewed_by_clinician_id"] is None
    assert revised["reviewed_at"] is None
    assert revised["expected_admission_at"].startswith("2026-08-05T09:00:00")


def test_revised_screening_can_be_resubmitted_and_concurred():
    """The second pass through the loop concurs without resetting the counter.

    PRD §3.2: "A `decision` of `CONCUR` advances the screening from `SUBMITTED`
    to `PHYSICIAN_CONCURRED`, storing `reviewed_by_clinician_id` as the acting
    user and `reviewed_at` as the current logical clock."

    Design: Difficulty/non_linear_state_machine/screening_revision_cycle_returns_to_draft_and_reconcurs
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    patient = register_patient(env)
    screening = create_draft_screening(env, patient["id"])
    submit_screening(env, screening["id"])
    review_screening(env, screening["id"], "REQUEST_CHANGES",
                     reviewer_note="Document prior functional level in detail")

    validate_success(api_client.patch_screening(
        screening["id"],
        {"expected_admission_at": "2026-08-05T09:00:00Z"},
        env["nurse_headers"],
    ))
    submit_screening(env, screening["id"])
    concurred = review_screening(env, screening["id"], "CONCUR")

    assert concurred["status"] == "PHYSICIAN_CONCURRED"
    assert concurred["revision_count"] == 1
    assert concurred["reviewed_by_clinician_id"] == env["physician"]["id"]
    assert concurred["reviewed_at"].startswith("2026-08-03T08:00:00")
    assert concurred["conducted_at"].startswith("2026-08-03T08:00:00")


def test_admission_opening_reports_the_patient_mismatch_before_the_screening_state():
    """A foreign screening that is also unconcurred reports the mismatch.

    PRD §2.5: "Implementations must evaluate checks in the following fixed
    order, so that an early failure masks every later one; a request that
    violates three rules reports only the highest-ranked violation."

    Design: Difficulty/priority_pair_validation_conflict/admission_create_screening_patient_mismatch_beats_unconcurred_screening
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    patient_a = register_patient(env)
    patient_b = register_patient(env, **PATIENT_B)
    screening_b = create_draft_screening(env, patient_b["id"])
    submit_screening(env, screening_b["id"])

    response = api_client.create_admission(
        create_admission_payload(patient_a["id"], screening_b["id"]),
        env["nurse_headers"],
    )

    validate_error(response, ApiErrorId.ERR_SCREENING_PATIENT_MISMATCH)


def test_mismatched_admission_attempt_leaves_the_screening_and_cohort_alone():
    """No admission row appears and the foreign screening stays SUBMITTED.

    PRD §3.3: "The screening must belong to the same patient as the admission,
    and it must already be `PHYSICIAN_CONCURRED` with a `reviewed_at` no later
    than the eventual admission instant — a screening in any other state is
    `ERR_SCREENING_NOT_CONCURRED`."

    Design: Difficulty/priority_pair_validation_conflict/admission_create_screening_patient_mismatch_beats_unconcurred_screening
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    patient_a = register_patient(env)
    patient_b = register_patient(env, **PATIENT_B)
    screening_b = create_draft_screening(env, patient_b["id"])
    submit_screening(env, screening_b["id"])

    api_client.create_admission(
        create_admission_payload(patient_a["id"], screening_b["id"]),
        env["nurse_headers"],
    )

    assert read_screening(screening_b["id"])["status"] == "SUBMITTED"
    _, meta = validate_paginated(api_client.list_admissions(
        OFFICER_HEADERS, {"patient_id": patient_a["id"]}
    ))
    assert meta["total_count"] == 0


def test_admit_is_refused_while_the_facility_posture_is_frozen():
    """A frozen facility blocks the admission gate even for a concurred patient.

    PRD §2.5: "**Admission gate** — admitting requires the facility's `posture`
    to be `OPEN` or `THRESHOLD_WATCH`, else `ERR_FACILITY_ADMISSION_FROZEN`
    (403)."

    Design: Difficulty/cross_entity_state_dependency/admit_cannot_proceed_while_facility_posture_frozen
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    patient_c = register_patient(env, mrn="MRN-C", full_name="Cleo Barnes",
                                 impairment_group_code="0110",
                                 comorbidity_tier="TIER_3")
    screening_c = create_concurred_screening(
        env, patient_c["id"], expected_admission_at="2026-08-04T18:00:00Z"
    )
    admission_c = open_admission(env, patient_c["id"], screening_c["id"])
    setup_frozen_facility(env)

    response = api_client.admit_admission(
        admission_c["id"], admit_admission_payload("2026-08-04T18:00:00Z"),
        env["nurse_headers"],
    )

    validate_error(response, ApiErrorId.ERR_FACILITY_ADMISSION_FROZEN)
    assert read_facility(env["facility_id"])["posture"] == "ADMISSION_FREEZE"


def test_blocked_admit_leaves_the_stay_pending_and_the_screening_concurred():
    """The refused admit stamps nothing on the admission or its screening.

    PRD §3.3: "A successful admit moves `stay_status` from `PENDING` to
    `ADMITTED`, stores `admitted_at` — which is null for as long as the stay is
    `PENDING` — and derives three things."

    Design: Difficulty/cross_entity_state_dependency/admit_cannot_proceed_while_facility_posture_frozen
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    patient_c = register_patient(env, mrn="MRN-C", full_name="Cleo Barnes",
                                 impairment_group_code="0110",
                                 comorbidity_tier="TIER_3")
    screening_c = create_concurred_screening(
        env, patient_c["id"], expected_admission_at="2026-08-04T18:00:00Z"
    )
    admission_c = open_admission(env, patient_c["id"], screening_c["id"])
    setup_frozen_facility(env)

    api_client.admit_admission(
        admission_c["id"], admit_admission_payload("2026-08-04T18:00:00Z"),
        env["nurse_headers"],
    )

    blocked = read_admission(admission_c["id"])
    assert blocked["stay_status"] == "PENDING"
    assert blocked["admitted_at"] is None
    assert blocked["screening_compliant"] is False
    assert read_screening(screening_c["id"])["status"] == "PHYSICIAN_CONCURRED"
