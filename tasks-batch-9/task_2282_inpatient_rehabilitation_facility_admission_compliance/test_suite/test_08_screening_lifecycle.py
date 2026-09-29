"""Preadmission screening creation, revision, review, expiry and acting identity."""

from test_helpers import (
    OFFICER_HEADERS,
    ApiErrorId,
    api_client,
    assert_clock_state,
    assert_screening,
    create_concurred_screening,
    create_draft_screening,
    create_screening_payload,
    deactivate_clinician,
    make_nurse_headers,
    read_screening,
    register_patient,
    review_screening_payload,
    set_clock,
    setup_facility_with_staff,
    submit_screening,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_screening_creation_stamps_its_system_fields_from_the_clock():
    """A new screening opens in DRAFT with its conducted_at read off the clock.

    PRD §3.2: "On creation the record enters `DRAFT`, its `revision_count` is 0,
    and `conducted_at` is stamped from the logical clock."

    Design: Corner/entities/screening_system_fields_stamped_at_creation
    """
    env = setup_facility_with_staff(staff=("nurse",))
    patient = register_patient(env)

    response = api_client.create_screening(
        create_screening_payload(patient["id"], env["nurse"]["id"]),
        env["nurse_headers"],
    )

    screening = validate_success(response, expected_status=201)
    assert_screening(screening)
    assert screening["conducted_at"].startswith("2026-08-03T08:00:00")
    assert screening["status"] == "DRAFT"
    assert screening["revision_count"] == 0
    assert screening["reviewed_at"] is None
    assert screening["reviewed_by_clinician_id"] is None
    assert screening["version"] == 1


def test_submitting_a_draft_screening_moves_it_to_submitted():
    """Submission hands the screening to the physician without reviewing it.

    PRD §3.2: "Submitting the screening for physician review moves it from
    `DRAFT` to `SUBMITTED`."

    Design: Corner/state_machines/screening_submit_moves_draft_to_submitted
    """
    env = setup_facility_with_staff(staff=("nurse",))
    patient = register_patient(env)
    screening = create_draft_screening(env, patient["id"])

    response = api_client.submit_screening(screening["id"], env["nurse_headers"])

    submitted = validate_success(response, expected_status=200)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["revision_count"] == 0
    assert submitted["reviewed_at"] is None


def test_submission_with_a_false_documentation_attestation_is_refused():
    """One unattested documentation flag blocks the whole submission.

    PRD §3.2: "Submission requires all four documentation attestations to be
    true — if any one of them is false the submission is refused with
    `ERR_SCREENING_DOCUMENTATION_INCOMPLETE`"

    Design: Corner/state_machines/screening_submit_with_missing_documentation_flag_rejected
    """
    env = setup_facility_with_staff(staff=("nurse",))
    patient = register_patient(env)
    screening = create_draft_screening(env, patient["id"],
                                       medical_supervision_documented=False)

    response = api_client.submit_screening(screening["id"], env["nurse_headers"])

    validate_error(response, ApiErrorId.ERR_SCREENING_DOCUMENTATION_INCOMPLETE)
    assert read_screening(screening["id"])["status"] == "DRAFT"


def test_submitting_an_already_submitted_screening_is_refused():
    """The submit transition is not declared from SUBMITTED, so it is a conflict.

    PRD §2.5: "the target resource must currently be in a state from which the
    requested transition is declared, else `ERR_INVALID_STATE` (409), on every
    transition endpoint"

    Design: Corner/state_machines/screening_submit_twice_rejected
    """
    env = setup_facility_with_staff(staff=("nurse",))
    patient = register_patient(env)
    screening = create_draft_screening(env, patient["id"])
    submit_screening(env, screening["id"])

    response = api_client.submit_screening(screening["id"], env["nurse_headers"])

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    unchanged = read_screening(screening["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["version"] == 2


def test_screener_may_not_record_the_review_decision_on_their_own_screening():
    """A physician who screened the patient cannot also concur with the screening.

    PRD §2.9: "The rehabilitation physician recording a review decision on a
    screening must not be the clinician named as `conducted_by_clinician_id` on
    that screening."

    Design: Corner/state_machines/screening_review_by_its_own_screener_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    patient = register_patient(env)
    screening = create_draft_screening(env, patient["id"],
                                       screener_key="physician")
    submit_screening(env, screening["id"])

    response = api_client.review_screening(screening["id"],
                                           review_screening_payload("CONCUR"),
                                           env["physician_headers"])

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    untouched = read_screening(screening["id"])
    assert untouched["status"] == "SUBMITTED"
    assert untouched["reviewed_by_clinician_id"] is None


def test_reviewing_a_concurred_screening_a_second_time_is_refused():
    """Concurrence is terminal, so a follow-up change request cannot land.

    PRD §3.2: "`PHYSICIAN_CONCURRED` and `EXPIRED` are the terminal states of a
    screening; nothing moves out of either."

    Design: Corner/state_machines/screening_review_after_concurrence_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    patient = register_patient(env)
    screening = create_concurred_screening(env, patient["id"])

    response = api_client.review_screening(
        screening["id"],
        review_screening_payload("REQUEST_CHANGES", reviewer_note="Second look"),
        env["physician_headers"],
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    terminal = read_screening(screening["id"])
    assert terminal["status"] == "PHYSICIAN_CONCURRED"
    assert terminal["revision_count"] == 0


def test_screening_expires_when_the_clock_reaches_forty_eight_hours():
    """Exactly 48 hours after conducted_at the sweep carries the screening away.

    PRD §3.2: "whenever the logical clock is advanced, every screening in
    `DRAFT`, `SUBMITTED`, `CHANGES_REQUESTED`, or `ON_HOLD` whose `conducted_at`
    plus 48 hours is at or before the new clock value becomes `EXPIRED`, and the
    count of screenings swept this way is reported as `expired_screening_count`"

    Design: Corner/state_machines/screening_expires_when_clock_reaches_forty_eight_hours
    """
    env = setup_facility_with_staff(staff=("nurse",))
    patient = register_patient(env)
    screening = create_draft_screening(env, patient["id"])
    submit_screening(env, screening["id"])

    clock = set_clock("2026-08-05T08:00:00Z")

    assert_clock_state(clock)
    assert clock["current_utc"].startswith("2026-08-05T08:00:00")
    assert clock["expired_screening_count"] == 1
    assert clock["missed_assessment_count"] == 0
    assert read_screening(screening["id"])["status"] == "EXPIRED"


def test_clock_response_counts_every_screening_it_swept():
    """Both submitted screenings age out together and both are counted once.

    PRD §2.4: "the response reports the resulting `current_utc` together with
    `expired_screening_count` and `missed_assessment_count`, the number of
    records swept into a terminal state by that movement"

    Design: Corner/endpoints/clock_endpoint_reports_sweep_counters_in_its_response
    """
    env = setup_facility_with_staff(staff=("nurse",))
    patient_a = register_patient(env, mrn="MRN-A")
    patient_b = register_patient(env, mrn="MRN-B", full_name="Bo Whitaker")
    screening_a = create_draft_screening(env, patient_a["id"])
    screening_b = create_draft_screening(env, patient_b["id"])
    submit_screening(env, screening_a["id"])
    submit_screening(env, screening_b["id"])

    clock = set_clock("2026-08-05T08:00:00Z")

    assert_clock_state(clock)
    assert clock["current_utc"].startswith("2026-08-05T08:00:00")
    assert clock["expired_screening_count"] == 2
    assert clock["missed_assessment_count"] == 0
    assert read_screening(screening_a["id"])["status"] == "EXPIRED"
    assert read_screening(screening_b["id"])["status"] == "EXPIRED"


def test_revising_a_draft_screening_touches_only_the_supplied_flag():
    """A partial revision leaves the untouched attestations and plan alone.

    PRD §3.2: "Editing a screening that sits in `DRAFT` changes the fields
    without changing state."

    Design: Corner/endpoints/screening_patch_updates_only_the_supplied_flag
    """
    env = setup_facility_with_staff(staff=("nurse",))
    patient = register_patient(env)
    screening = create_draft_screening(env, patient["id"],
                                       medical_supervision_documented=False)

    response = api_client.patch_screening(
        screening["id"], {"medical_supervision_documented": True},
        env["nurse_headers"],
    )

    revised = validate_success(response, expected_status=200)
    assert revised["medical_supervision_documented"] is True
    assert revised["intensive_therapy_documented"] is True
    assert revised["expected_admission_at"].startswith("2026-08-04T12:00:00")
    assert revised["status"] == "DRAFT"
    assert revised["version"] == 2


def test_screening_conducted_by_a_therapist_is_refused():
    """Only a nurse or a rehabilitation physician may be named as the screener.

    PRD §3.2: "The screener must hold either the `NURSE` or the
    `REHAB_PHYSICIAN` credential; any other credential is
    `ERR_SCREENER_CREDENTIAL_INVALID`."

    Design: Corner/validations/screening_conducted_by_therapist_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "pt"))
    patient = register_patient(env)

    response = api_client.create_screening(
        create_screening_payload(patient["id"], env["pt"]["id"]),
        env["nurse_headers"],
    )

    validate_error(response, ApiErrorId.ERR_SCREENER_CREDENTIAL_INVALID)
    _, meta = validate_paginated(api_client.list_screenings(
        OFFICER_HEADERS, params={"patient_id": patient["id"]}
    ))
    assert meta["total_count"] == 0


def test_nurse_role_asserted_with_a_physician_identity_is_refused():
    """The acting clinician's credential must match the role in the header.

    PRD §2.1: "`RehabPhysician` requires credential `REHAB_PHYSICIAN`,
    `NurseCaseManager` requires `NURSE`, `TherapyLead` requires any of
    `THERAPIST_PT`, `THERAPIST_OT` or `THERAPIST_SLP`, and `HimCoder` requires
    `CODER`; a mismatch is `ERR_ROLE_CREDENTIAL_MISMATCH`."

    Design: Corner/validations/screening_create_under_nurse_role_with_physician_user_id_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    patient = register_patient(env)

    response = api_client.create_screening(
        create_screening_payload(patient["id"], env["nurse"]["id"]),
        make_nurse_headers(env["physician"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_ROLE_CREDENTIAL_MISMATCH)
    _, meta = validate_paginated(api_client.list_screenings(
        OFFICER_HEADERS, params={"patient_id": patient["id"]}
    ))
    assert meta["total_count"] == 0


def test_deactivated_nurse_may_no_longer_open_a_screening():
    """A retired clinician cannot act, whatever the rest of the request says.

    PRD §2.1: "Second, that clinician's `status` must be `ACTIVE`; an acting
    clinician whose status is `INACTIVE` is refused with
    `ERR_ACTING_CLINICIAN_INACTIVE`."

    Design: Corner/validations/screening_create_by_deactivated_nurse_rejected
    """
    env = setup_facility_with_staff(staff=("nurse",))
    patient = register_patient(env)
    deactivate_clinician(env["nurse"]["id"])

    response = api_client.create_screening(
        create_screening_payload(patient["id"], env["nurse"]["id"]),
        env["nurse_headers"],
    )

    validate_error(response, ApiErrorId.ERR_ACTING_CLINICIAN_INACTIVE)
    retired = validate_success(
        api_client.get_clinician(env["nurse"]["id"], OFFICER_HEADERS)
    )
    assert retired["status"] == "INACTIVE"
    _, meta = validate_paginated(api_client.list_screenings(
        OFFICER_HEADERS, params={"patient_id": patient["id"]}
    ))
    assert meta["total_count"] == 0


def test_nurse_may_not_record_the_physician_review_decision():
    """Review is a rehabilitation physician action and no other role may take it.

    PRD §2.1: "If the headers are well formed but the declared role is not
    authorised for the endpoint being called, the rejection is
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/nurse_cannot_review_screening
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    patient = register_patient(env)
    screening = create_draft_screening(env, patient["id"])
    submit_screening(env, screening["id"])

    response = api_client.review_screening(screening["id"],
                                           review_screening_payload("CONCUR"),
                                           env["nurse_headers"])

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)
    untouched = read_screening(screening["id"])
    assert untouched["status"] == "SUBMITTED"
    assert untouched["reviewed_by_clinician_id"] is None
