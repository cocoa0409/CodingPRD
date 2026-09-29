"""The error catalogue: authentication before everything, one distinct not-found id per entity,
ownership on the entity-backed roles, and the state and shape rejections."""
from test_helpers import (
    BILLING_SPECIALIST,
    PATHOLOGIST,
    PATIENT_NAVIGATOR,
    PRACTICE_ADMIN,
    QUALITY_OFFICER,
    REFERRAL_COORDINATOR,
    api_client,
    apply_block_action,
    book_slot,
    cancel_booking_payload,
    cancel_slot,
    check_in,
    confirm_prep,
    create_block,
    create_procedure_booking_payload,
    list_noninvasive_tests,
    list_patients,
    list_quality_periods,
    lock_quality_period,
    make_patient_headers,
    move_clock,
    open_episode,
    open_quality_period,
    prep_attestation_payload,
    read_block,
    read_booking,
    read_episode,
    read_referral,
    read_quality_period,
    register_endoscopist,
    register_patient,
    register_plan,
    session_status_action_payload,
    submit_referral,
    triage,
    triage_action_payload,
    validate_error,
    validate_success,
)

UNKNOWN = "00000000-0000-4000-8000-0000000000"


def test_authentication_is_settled_before_the_role_and_before_the_body():
    """Every request to every endpoint must carry two headers: `X-User-ID`, identifying the
    acting user, and `X-User-Role`, naming the role they are acting under. If either header is
    absent, or if `X-User-Role` is not one of the eight role names below, the request is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well formed but the named role is
    not authorized for the endpoint being called, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403).

    Design: Corner/errors/missing_x_user_headers_return_unauthenticated
    """
    headerless = {"Content-Type": "application/json"}
    validate_error(
        api_client.create_patient(
            {"mrn": "MRN-9999", "birth_date": "1975-04-10",
             "insurance_plan_id": UNKNOWN + "01"},
            headerless),
        "ERR_UNAUTHENTICATED")

    undeclared_role = {"X-User-ID": "op-tech-1", "X-User-Role": "EndoscopyTech",
                       "Content-Type": "application/json"}
    refused = api_client.list_patients(undeclared_role)
    validate_error(refused, "ERR_UNAUTHENTICATED")
    body = refused.json()
    assert body["response_type"] == "error"
    assert set(body["data"].keys()) >= {"error_id", "message"}

    rows, meta = list_patients()
    assert meta["total_count"] == 0
    assert rows == []


def test_each_entity_read_path_carries_its_own_not_found_identifier():
    """4. Path-parameter resolution, evaluated left to right along the URL — the not-found error
    naming the segment that failed to resolve.

    Every one of the thirteen resource types in this system — payer plans, patients, clinicians,
    room blocks, anesthesia coverage rows, referrals, screening episodes, non-invasive tests,
    procedure bookings, pathology reports, surveillance recommendations, billing claims, and
    quality measurement windows — additionally carries an `updated_at` timestamp in the same
    format and an integer `version`.

    Design: Corner/errors/every_declared_not_found_id_is_reachable
    """
    validate_error(api_client.get_insurance_plan(UNKNOWN + "01", PRACTICE_ADMIN),
                   "ERR_PLAN_NOT_FOUND")
    validate_error(api_client.get_patient(UNKNOWN + "02", PRACTICE_ADMIN),
                   "ERR_PATIENT_NOT_FOUND")
    validate_error(api_client.get_clinician(UNKNOWN + "03", QUALITY_OFFICER),
                   "ERR_CLINICIAN_NOT_FOUND")
    validate_error(api_client.get_endoscopy_session(UNKNOWN + "04", PRACTICE_ADMIN),
                   "ERR_SESSION_NOT_FOUND")
    validate_error(api_client.get_anesthesia_coverage(UNKNOWN + "05", PRACTICE_ADMIN),
                   "ERR_COVERAGE_NOT_FOUND")
    validate_error(api_client.get_referral(UNKNOWN + "06", REFERRAL_COORDINATOR),
                   "ERR_REFERRAL_NOT_FOUND")
    validate_error(api_client.get_screening_episode(UNKNOWN + "07", PATIENT_NAVIGATOR),
                   "ERR_EPISODE_NOT_FOUND")
    validate_error(api_client.get_noninvasive_test(UNKNOWN + "08", PATHOLOGIST),
                   "ERR_TEST_NOT_FOUND")
    validate_error(api_client.get_procedure_booking(UNKNOWN + "09", BILLING_SPECIALIST),
                   "ERR_BOOKING_NOT_FOUND")
    validate_error(api_client.get_pathology_report(UNKNOWN + "0a", PATHOLOGIST),
                   "ERR_PATHOLOGY_NOT_FOUND")
    validate_error(
        api_client.get_surveillance_recommendation(UNKNOWN + "0b", PATIENT_NAVIGATOR),
        "ERR_RECOMMENDATION_NOT_FOUND")
    validate_error(api_client.get_billing_claim(UNKNOWN + "0c", BILLING_SPECIALIST),
                   "ERR_CLAIM_NOT_FOUND")
    validate_error(api_client.get_quality_period(UNKNOWN + "0d", QUALITY_OFFICER),
                   "ERR_QUALITY_PERIOD_NOT_FOUND")


def test_the_addressed_identifier_decides_for_the_patient_role():
    """When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`;
    ownership checks compare `Patient.id` itself, or a `ScreeningEpisode`'s `patient_id`, to
    `X-User-ID`. A violation of either ownership rule is rejected with `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403). A `Patient` may read only their own patient row and only episodes whose
    `patient_id` equals their `X-User-ID`; an `Endoscopist` may start, complete, or abort only
    bookings whose `performing_endoscopist_id` equals their `X-User-ID`.

    Design: Corner/errors/patient_role_cannot_reach_another_patients_rows
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    owner = register_patient(plan["id"], mrn="MRN-0001")
    stranger = register_patient(plan["id"], mrn="MRN-0002", birth_date="1970-02-02")
    episode = open_episode(owner["id"], "SCREENING_AVERAGE_RISK")
    intruder = make_patient_headers(stranger["id"])

    validate_error(api_client.get_screening_episode(episode["id"], intruder),
                   "ERR_NOT_RESOURCE_OWNER")
    validate_error(api_client.get_patient(owner["id"], intruder), "ERR_NOT_RESOURCE_OWNER")
    validate_error(
        api_client.submit_prep_attestation(
            episode["id"], prep_attestation_payload(True), intruder),
        "ERR_NOT_RESOURCE_OWNER")

    own = validate_success(
        api_client.get_screening_episode(episode["id"], make_patient_headers(owner["id"])))
    assert own["id"] == episode["id"]
    assert own["prep_attestation"] == "NONE"
    assert own["navigation_status"] == "NOT_STARTED"
    assert own["prep_adherence_score"] == 0.0


def test_one_accept_payload_yields_three_outcomes_driven_only_by_the_status():
    """The referral's `status` moves through `SUBMITTED`, `UNDER_TRIAGE`, and `INFO_REQUESTED`
    before settling into one of the three terminal states `ACCEPTED_OPEN_ACCESS`,
    `ACCEPTED_OFFICE_VISIT`, or `DECLINED`. Requesting an action that is not declared from the
    referral's current state is rejected with `ERR_INVALID_REFERRAL_STATE`.

    Design: Corner/errors/triage_action_rejected_outside_under_triage
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    patient = register_patient(plan["id"])
    referral = submit_referral(patient["id"], referring_provider_npi="3000000001",
                               reason="FAMILY_HISTORY", asa_class_reported=2)
    assert referral["status"] == "SUBMITTED"
    assert referral["info_request_rounds"] == 0

    validate_error(
        api_client.referral_triage_action(
            referral["id"], triage_action_payload("ACCEPT_OPEN_ACCESS"), REFERRAL_COORDINATOR),
        "ERR_INVALID_REFERRAL_STATE")

    assert triage(referral["id"], "BEGIN_TRIAGE")["status"] == "UNDER_TRIAGE"
    assert triage(referral["id"], "ACCEPT_OPEN_ACCESS")["status"] == "ACCEPTED_OPEN_ACCESS"

    validate_error(
        api_client.referral_triage_action(
            referral["id"], triage_action_payload("DECLINE"), REFERRAL_COORDINATOR),
        "ERR_INVALID_REFERRAL_STATE")

    settled = read_referral(referral["id"])
    assert settled["status"] == "ACCEPTED_OPEN_ACCESS"
    assert settled["info_request_rounds"] == 0


def test_the_release_only_ever_happens_on_the_booked_to_cancelled_edge():
    """Any action requested from a state that does not declare it is rejected with
    `ERR_INVALID_BOOKING_STATE`. A `ReferralCoordinator` or `PracticeAdmin` cancels a booking that
    is still in `BOOKED`, supplying a `cancellation_reason`; the booking moves
    `BOOKED → CANCELLED`, `released_minutes` is set to that booking's `duration_minutes` plus the
    block's `turnover_minutes` — exactly the quantity the booking had consumed, and zero for
    every booking in any other status — and the block's ledger is recomputed so that booked and
    remaining minutes again sum to capacity.

    Design: Corner/errors/cancel_after_check_in_returns_invalid_booking_state
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endoscopist = register_endoscopist()
    patient = register_patient(plan["id"])
    block = create_block(endoscopist["id"])
    apply_block_action(block["id"], "PUBLISH")
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    booking = book_slot(block["id"], episode["id"], endoscopist["id"])
    confirm_prep(episode["id"], patient["id"])
    assert check_in(booking["id"])["status"] == "CHECKED_IN"

    validate_error(
        api_client.cancel_booking(
            booking["id"], cancel_booking_payload("PATIENT_RESCHEDULED"),
            REFERRAL_COORDINATOR),
        "ERR_INVALID_BOOKING_STATE")

    ledger = read_block(block["id"])
    assert ledger["booked_minutes"] == 60
    assert ledger["remaining_minutes"] == 420

    still = read_booking(booking["id"])
    assert still["status"] == "CHECKED_IN"
    assert still["cancellation_reason"] is None
    assert read_episode(episode["id"])["clinical_status"] == "PROCEDURE_SCHEDULED"


def test_a_block_can_run_out_of_rows_while_it_still_has_minutes():
    """Third, the headcount ceiling: when the number of bookings on the block whose `status` is
    anything other than `CANCELLED` already equals `max_procedures`, the request is rejected with
    `ERR_SESSION_CAPACITY_EXCEEDED` (HTTP 409).

    Design: Corner/errors/headcount_ceiling_returns_session_capacity_exceeded
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endoscopist = register_endoscopist()
    patient_a = register_patient(plan["id"], mrn="MRN-0001")
    patient_b = register_patient(plan["id"], mrn="MRN-0002", birth_date="1970-02-02")
    episode_a = open_episode(patient_a["id"], "SCREENING_AVERAGE_RISK")
    episode_b = open_episode(patient_b["id"], "SCREENING_AVERAGE_RISK")

    block = create_block(endoscopist["id"], max_procedures=1)
    assert block["max_procedures"] == 1
    apply_block_action(block["id"], "PUBLISH")
    first = book_slot(block["id"], episode_a["id"], endoscopist["id"],
                      slot_start_utc="2026-09-15T13:00:00Z", duration_minutes=45)

    full = read_block(block["id"])
    assert full["remaining_minutes"] == 420

    validate_error(
        api_client.create_procedure_booking(
            block["id"],
            create_procedure_booking_payload(
                episode_b["id"], endoscopist["id"], full["version"],
                "2026-09-15T15:00:00Z", 30),
            REFERRAL_COORDINATOR),
        "ERR_SESSION_CAPACITY_EXCEEDED")

    assert cancel_slot(first["id"], "PATIENT_RESCHEDULED")["status"] == "CANCELLED"
    freed = read_block(block["id"])
    assert freed["remaining_minutes"] == 480
    assert freed["version"] == full["version"] + 1

    second = book_slot(block["id"], episode_b["id"], endoscopist["id"],
                       expected_session_version=freed["version"],
                       slot_start_utc="2026-09-15T15:00:00Z", duration_minutes=30)
    assert second["status"] == "BOOKED"
    assert read_block(block["id"])["booked_minutes"] == 45


def test_a_window_cannot_be_measured_before_its_last_calendar_day_has_passed():
    """Locking a window moves `OPEN → LOCKED` and is the computation event. It is refused with
    `ERR_QUALITY_PERIOD_NOT_ENDED` (HTTP 422) unless the calendar date of the logical clock is on
    or after the window's `period_end_date` — a window cannot be measured before it has finished.

    Design: Corner/errors/quality_period_lock_before_the_end_date_is_rejected
    """
    move_clock("2026-09-15T00:00:00Z")
    endoscopist = register_endoscopist()
    period = open_quality_period(endoscopist["id"], "2026-09-01", "2026-09-30")
    assert period["status"] == "OPEN"
    assert period["attribution_basis"] == "PROCEDURE_DATE"

    validate_error(api_client.lock_quality_period(period["id"], QUALITY_OFFICER),
                   "ERR_QUALITY_PERIOD_NOT_ENDED")
    assert read_quality_period(period["id"])["status"] == "OPEN"

    move_clock("2026-10-01T00:00:00Z")
    locked = lock_quality_period(period["id"])
    assert locked["status"] == "LOCKED"
    assert locked["updated_at"] == "2026-10-01T00:00:00.000Z"
    assert locked["attribution_basis"] == "PROCEDURE_DATE"


def test_four_action_endpoints_all_report_the_same_shape_error_for_a_missing_field():
    """3. Request-shape validation — `ERR_INVALID_REQUEST`. This covers missing required fields,
    unknown enum members, integers outside their declared bounds, calendar dates that are not in
    `YYYY-MM-DD` form, instants that are not ISO 8601 UTC, a `limit` outside 1 through 100, and a
    negative `offset`.

    `SUSPEND` moves either `PUBLISHED → SUSPENDED` or `COVERAGE_CONFIRMED → SUSPENDED`, requires
    a `reason` — omitting it is `ERR_INVALID_REQUEST` — records it in `suspension_reason`, and
    stops the block accepting new bookings.

    Design: Corner/errors/missing_required_action_fields_return_invalid_request
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endoscopist = register_endoscopist()
    patient = register_patient(plan["id"])
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    block = create_block(endoscopist["id"])
    published = apply_block_action(block["id"], "PUBLISH")

    validate_error(
        api_client.session_status_action(
            block["id"], session_status_action_payload("SUSPEND"), PRACTICE_ADMIN),
        "ERR_INVALID_REQUEST")
    validate_error(
        api_client.close_screening_episode(episode["id"], {}, PATIENT_NAVIGATOR),
        "ERR_INVALID_REQUEST")
    validate_error(
        api_client.create_noninvasive_test(
            episode["id"], {"test_type": "FIT"}, REFERRAL_COORDINATOR),
        "ERR_INVALID_REQUEST")
    validate_error(
        api_client.create_quality_period(
            {"endoscopist_id": endoscopist["id"], "period_start_date": "2026-09-01"},
            QUALITY_OFFICER),
        "ERR_INVALID_REQUEST")

    intact = read_block(block["id"])
    assert intact["status"] == "PUBLISHED"
    assert intact["version"] == published["version"]
    assert intact["suspension_reason"] is None

    open_still = read_episode(episode["id"])
    assert open_still["clinical_status"] == "OPEN"
    assert open_still["closure_reason"] is None
    assert list_noninvasive_tests()[1]["total_count"] == 0
    assert list_quality_periods()[1]["total_count"] == 0
