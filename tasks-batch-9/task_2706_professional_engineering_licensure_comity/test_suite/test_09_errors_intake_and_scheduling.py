"""Error-catalogue probes over roster intake, the logical clock, firm registration,
reference submission and examination scheduling.

Each test drives the public API to the state the rule guards and then checks the
single error identifier the PRD names for that rule, together with the stored
state the rejection must leave untouched.
"""

from test_helpers import (
    BOARD_INVESTIGATOR_HEADERS,
    BOARD_LICENSING_OFFICER_HEADERS,
    BOARD_REVIEWER_HEADERS,
    BOARD_SECRETARY_HEADERS,
    NON_EXISTENT_UUID,
    assert_seat_ledger,
    build_user_headers,
    factories,
    fixtures,
    make_applicant_headers,
    make_supervising_engineer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# An examination file needs a referee who already holds a licence; the referee's
# licence is issued as a full instant so its biennium is unambiguous.
REFEREE = {"license_overrides": {"issued_on": "2026-01-15T00:00:00Z"}}
# The referee endorses the claimed responsibility level with a boolean.
ENDORSED = {"responsibility_confirmed": True}


def test_absent_uuid_reports_each_entity_own_not_found_code(api):
    """PRD §2.7: "Path identifier existence — the matching per-entity not-found code at HTTP 404, resolved strictly left to right along the URL."

    Design: Corner/errors/unknown_path_id_returns_entity_specific_not_found
    """
    missing = NON_EXISTENT_UUID

    validate_error(
        api.get_engineer(missing, BOARD_SECRETARY_HEADERS), "ERR_ENGINEER_NOT_FOUND"
    )
    validate_error(
        api.get_experience_record(missing, BOARD_REVIEWER_HEADERS),
        "ERR_EXPERIENCE_RECORD_NOT_FOUND",
    )
    validate_error(
        api.get_reference(missing, BOARD_REVIEWER_HEADERS), "ERR_REFERENCE_NOT_FOUND"
    )
    validate_error(
        api.get_test_center(missing, BOARD_SECRETARY_HEADERS),
        "ERR_TEST_CENTER_NOT_FOUND",
    )
    validate_error(
        api.get_exam_authorization(missing, BOARD_SECRETARY_HEADERS),
        "ERR_EXAM_AUTHORIZATION_NOT_FOUND",
    )
    validate_error(
        api.get_exam_appointment(missing, BOARD_SECRETARY_HEADERS),
        "ERR_EXAM_APPOINTMENT_NOT_FOUND",
    )
    validate_error(
        api.get_plan_submission(missing, BOARD_INVESTIGATOR_HEADERS),
        "ERR_PLAN_SUBMISSION_NOT_FOUND",
    )
    validate_error(
        api.get_cpc_report(missing, BOARD_REVIEWER_HEADERS), "ERR_CPC_REPORT_NOT_FOUND"
    )
    validate_error(
        api.get_pdh_record(missing, BOARD_REVIEWER_HEADERS), "ERR_PDH_RECORD_NOT_FOUND"
    )
    validate_error(
        api.get_cpc_audit(missing, BOARD_SECRETARY_HEADERS), "ERR_CPC_AUDIT_NOT_FOUND"
    )
    validate_error(
        api.get_case(missing, BOARD_INVESTIGATOR_HEADERS), "ERR_CASE_NOT_FOUND"
    )
    validate_error(
        api.get_consent_order(missing, BOARD_INVESTIGATOR_HEADERS),
        "ERR_CONSENT_ORDER_NOT_FOUND",
    )


def test_missing_role_header_is_unauthenticated_and_writes_nothing(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the nine role names enumerated below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/err_unauthenticated_when_x_user_role_header_missing_or_unknown
    """
    payload = factories.engineer_payload(
        full_name="Ghost Applicant", email="ghost@pe.test", home_jurisdiction="OR"
    )
    headers_without_role = {"X-User-ID": "SEC-1", "Content-Type": "application/json"}

    validate_error(
        api.create_engineer(payload, headers_without_role), "ERR_UNAUTHENTICATED"
    )

    items, meta = validate_paginated(api.list_engineers(BOARD_SECRETARY_HEADERS))
    assert meta["total_count"] == 0
    assert items == []


def test_undeclared_role_name_is_unauthenticated_and_writes_nothing(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the nine role names enumerated below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/err_unauthenticated_when_x_user_role_header_missing_or_unknown
    """
    payload = factories.engineer_payload(
        full_name="Ghost Applicant", email="ghost@pe.test", home_jurisdiction="OR"
    )

    validate_error(
        api.create_engineer(payload, build_user_headers("SEC-1", "Notary")),
        "ERR_UNAUTHENTICATED",
    )

    items, meta = validate_paginated(api.list_engineers(BOARD_SECRETARY_HEADERS))
    assert meta["total_count"] == 0
    assert items == []


def test_repeated_email_under_a_different_name_is_refused(api):
    """PRD §3.1: "must be unique across the roster (a repeat address is refused with `ERR_DUPLICATE_EMAIL`, HTTP 409)"

    Design: Corner/errors/err_duplicate_email_rejected_on_engineer_create
    """
    first = fixtures.create_engineer(
        api,
        full_name="Tor Halden",
        email="tor.halden@pe.test",
        home_jurisdiction="OR",
    )

    validate_error(
        api.create_engineer(
            factories.engineer_payload(
                full_name="Torvald Halden",
                email="tor.halden@pe.test",
                home_jurisdiction="WA",
            ),
            BOARD_SECRETARY_HEADERS,
        ),
        "ERR_DUPLICATE_EMAIL",
    )

    items, meta = validate_paginated(api.list_engineers(BOARD_SECRETARY_HEADERS))
    assert meta["total_count"] == 1
    assert len(items) == 1
    stored = validate_success(api.get_engineer(first["id"], BOARD_SECRETARY_HEADERS))
    assert stored["home_jurisdiction"] == "OR"
    assert stored["full_name"] == "Tor Halden"
    assert stored["version"] == 1


def test_second_license_for_an_engineer_already_active_is_refused(api):
    """PRD §3.1: "An engineer may hold only one live registration: if any licence with the same `engineer_id` already stands in `ACTIVE`, issuance is refused with `ERR_DUPLICATE_ACTIVE_LICENSE` (HTTP 409)."

    Design: Corner/errors/err_duplicate_active_license_rejected_for_same_engineer
    """
    engineer = fixtures.create_engineer(
        api, full_name="Ines Volk", email="ines.volk@pe.test", home_jurisdiction="OR"
    )
    held = fixtures.issue_license(
        api, engineer["id"], license_type="STANDARD", issued_on="2026-01-15T00:00:00Z"
    )
    assert held["status"] == "ACTIVE"

    validate_error(
        api.create_license(
            factories.license_payload(
                engineer["id"], license_type="COMITY", issued_on="2026-03-01T00:00:00Z"
            ),
            BOARD_LICENSING_OFFICER_HEADERS,
        ),
        "ERR_DUPLICATE_ACTIVE_LICENSE",
    )

    items, meta = validate_paginated(
        api.list_licenses(
            BOARD_LICENSING_OFFICER_HEADERS, params={"engineer_id": engineer["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in items] == [held["id"]]
    stored = validate_success(
        api.get_license(held["id"], BOARD_LICENSING_OFFICER_HEADERS)
    )
    assert stored["status"] == "ACTIVE"
    assert stored["license_type"] == "STANDARD"
    assert stored["version"] == 1


def test_naming_oneself_as_referee_is_refused(api):
    """PRD §3.3: "An applicant may not vouch for themselves: a `referee_engineer_id` equal to the file's own `engineer_id` is refused with `ERR_SELF_REFERENCE_FORBIDDEN` (HTTP 422)."

    Design: Corner/errors/err_self_reference_forbidden_when_referee_is_the_applicant
    """
    engineer = fixtures.create_engineer(
        api, full_name="Sol Marek", email="sol.marek@pe.test", home_jurisdiction="OR"
    )
    application = fixtures.create_application(api, engineer["id"])
    record = fixtures.add_experience_record(
        api,
        application["id"],
        engineer["id"],
        employer_name="Marek Structural",
        period_start_month="2019-01",
        period_end_month="2022-12",
    )

    validate_error(
        api.create_reference(
            record["id"],
            factories.reference_payload(engineer["id"]),
            make_applicant_headers(engineer["id"]),
        ),
        "ERR_SELF_REFERENCE_FORBIDDEN",
    )

    items, meta = validate_paginated(
        api.list_references(
            make_applicant_headers(engineer["id"]),
            params={"experience_record_id": record["id"]},
        )
    )
    assert meta["total_count"] == 0
    assert items == []
    stored = validate_success(
        api.get_experience_record(record["id"], make_applicant_headers(engineer["id"]))
    )
    assert stored["verification_status"] == "UNVERIFIED"


def test_rewinding_the_logical_clock_is_refused(api):
    """PRD §2.5: "The clock may only move forward or stand still: a requested value earlier than the current logical clock is rejected with `ERR_CLOCK_REWIND_FORBIDDEN` (HTTP 409)."

    Design: Corner/errors/err_clock_rewind_forbidden_but_idempotent_reset_allowed
    """
    advanced = fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    assert advanced["current_utc"] == "2026-09-01T00:00:00.000Z"

    validate_error(
        api.set_current_utc(
            factories.clock_payload("2026-08-15T00:00:00Z"), BOARD_SECRETARY_HEADERS
        ),
        "ERR_CLOCK_REWIND_FORBIDDEN",
    )

    unchanged = fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    assert unchanged["current_utc"] == "2026-09-01T00:00:00.000Z"


def test_setting_the_clock_to_the_identical_instant_stands_still(api):
    """PRD §2.5: "The clock may only move forward or stand still: a requested value earlier than the current logical clock is rejected with `ERR_CLOCK_REWIND_FORBIDDEN` (HTTP 409)."

    Design: Corner/errors/err_clock_rewind_forbidden_but_idempotent_reset_allowed
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")

    summary = validate_success(
        api.set_current_utc(
            factories.clock_payload("2026-09-01T00:00:00Z"), BOARD_SECRETARY_HEADERS
        )
    )

    assert summary["current_utc"] == "2026-09-01T00:00:00.000Z"
    assert summary["expired_authorization_count"] == 0
    assert summary["expired_license_count"] == 0
    assert summary["expired_firm_count"] == 0
    assert summary["cancelled_appointment_count"] == 0
    assert summary["lapsed_firm_count"] == 0


def test_repeated_firm_name_behind_a_different_licence_is_refused(api):
    """PRD §3.8: "a non-empty business name of at most 160 characters that must be unique across the register — a repeat is refused with `ERR_DUPLICATE_FIRM_NAME` (HTTP 409)"

    Design: Corner/errors/firm_registration_rejects_duplicate_firm_name
    """
    _, first_license = fixtures.create_licensed_engineer(
        api,
        license_overrides={"issued_on": "2026-01-15T00:00:00Z"},
        full_name="Alma Halvard",
        email="alma.halvard@pe.test",
    )
    _, second_license = fixtures.create_licensed_engineer(
        api,
        license_overrides={"issued_on": "2026-02-15T00:00:00Z"},
        full_name="Bo Halvard",
        email="bo.halvard@pe.test",
    )
    firm = fixtures.create_firm(
        api, first_license["id"], firm_name="Halvard Engineering PC", state_code="OR"
    )

    validate_error(
        api.create_firm_registration(
            factories.firm_registration_payload(
                second_license["id"],
                firm_name="Halvard Engineering PC",
                state_code="WA",
            ),
            BOARD_LICENSING_OFFICER_HEADERS,
        ),
        "ERR_DUPLICATE_FIRM_NAME",
    )

    items, meta = validate_paginated(
        api.list_firm_registrations(BOARD_LICENSING_OFFICER_HEADERS)
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in items] == [firm["id"]]
    stored = validate_success(
        api.get_firm_registration(firm["id"], BOARD_LICENSING_OFFICER_HEADERS)
    )
    assert stored["responsible_charge_license_id"] == first_license["id"]
    assert stored["state_code"] == "OR"
    assert stored["status"] == "ACTIVE"


def test_firm_registration_behind_a_swept_expired_licence_is_refused(api):
    """PRD §3.8: "That licence must stand in `ACTIVE`; anything else is refused with `ERR_RESPONSIBLE_CHARGE_LICENSE_INACTIVE` (HTTP 422)."

    Design: Corner/errors/err_responsible_charge_license_inactive_after_expiry_sweep
    """
    _, license_ = fixtures.create_licensed_engineer(
        api,
        license_overrides={"issued_on": "2026-01-15T00:00:00Z"},
        full_name="Ulf Nord",
        email="ulf.nord@pe.test",
    )

    summary = fixtures.set_clock(api, "2028-02-01T00:00:00Z")
    assert summary["expired_license_count"] == 1

    swept = validate_success(
        api.get_license(license_["id"], BOARD_LICENSING_OFFICER_HEADERS)
    )
    assert swept["status"] == "EXPIRED"

    validate_error(
        api.create_firm_registration(
            factories.firm_registration_payload(
                license_["id"], firm_name="Nord Structural PC", state_code="OR"
            ),
            BOARD_LICENSING_OFFICER_HEADERS,
        ),
        "ERR_RESPONSIBLE_CHARGE_LICENSE_INACTIVE",
    )

    items, meta = validate_paginated(
        api.list_firm_registrations(BOARD_LICENSING_OFFICER_HEADERS)
    )
    assert meta["total_count"] == 0
    assert items == []


def test_reference_submitted_against_an_unverified_block_is_a_state_conflict(api):
    """PRD §3.3: "And the block being attested must stand in `PENDING_VERIFICATION`, meaning the file has been submitted; answering against a block still in `UNVERIFIED` or already resolved is refused with `ERR_REFERENCE_STATE_INVALID` (HTTP 409)."

    Design: Corner/errors/err_reference_state_invalid_when_parent_record_still_unverified
    """
    applicant = fixtures.create_engineer(
        api, full_name="Nia Frost", email="nia.frost@pe.test", home_jurisdiction="OR"
    )
    referee = fixtures.create_engineer(
        api, full_name="Gus Frost", email="gus.frost@pe.test", home_jurisdiction="OR"
    )
    application = fixtures.create_application(api, applicant["id"])
    record = fixtures.add_experience_record(
        api,
        application["id"],
        applicant["id"],
        employer_name="Frost Bridges",
        period_start_month="2019-01",
        period_end_month="2022-12",
    )
    reference = fixtures.request_reference(
        api, record["id"], applicant["id"], referee["id"]
    )
    assert reference["status"] == "REQUESTED"

    validate_error(
        api.submit_reference(
            reference["id"],
            factories.reference_submission_payload(
                evaluation_score=5, months_confirmed=48, responsibility_confirmed=True
            ),
            make_supervising_engineer_headers(referee["id"]),
        ),
        "ERR_REFERENCE_STATE_INVALID",
    )

    stored = validate_success(
        api.get_reference(reference["id"], BOARD_REVIEWER_HEADERS)
    )
    assert stored["status"] == "REQUESTED"
    assert stored["submitted_at"] is None
    assert stored["evaluation_score"] is None
    assert stored["version"] == 1
    block = validate_success(
        api.get_experience_record(record["id"], BOARD_REVIEWER_HEADERS)
    )
    assert block["verification_status"] == "UNVERIFIED"


def test_booking_against_an_unknown_test_centre_is_not_found(api):
    """PRD §3.1: "A `test_center_id` naming no centre answers `ERR_TEST_CENTER_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/exam_scheduling_guards_center_seat_and_window_length
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="exam_approved",
        submission_overrides=ENDORSED,
        referee_overrides=REFEREE,
    )
    center = fixtures.create_test_center(
        api, name="Eugene Testing Hall", state_code="OR", seat_labels=["S1", "S2"]
    )

    validate_error(
        api.create_exam_appointment(
            factories.exam_appointment_payload(
                track["authorization"]["id"],
                NON_EXISTENT_UUID,
                seat_label="S1",
                window_start="2026-09-10T09:00:00Z",
                window_end="2026-09-10T17:00:00Z",
            ),
            make_applicant_headers(track["engineer"]["id"]),
        ),
        "ERR_TEST_CENTER_NOT_FOUND",
    )

    untouched = validate_success(
        api.get_test_center(center["id"], BOARD_SECRETARY_HEADERS)
    )
    assert_seat_ledger(untouched, seat_count=2, committed=0, available=2)
    authorization = validate_success(
        api.get_exam_authorization(
            track["authorization"]["id"],
            make_applicant_headers(track["engineer"]["id"]),
        )
    )
    assert authorization["status"] == "APPROVED_TO_SIT"


def test_booking_a_seat_label_the_centre_does_not_offer_is_not_found(api):
    """PRD §3.5: "The `seat_label` must be one of the centre's declared `seat_labels`; a label the centre does not offer answers `ERR_SEAT_LABEL_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/exam_scheduling_guards_center_seat_and_window_length
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="exam_approved",
        submission_overrides=ENDORSED,
        referee_overrides=REFEREE,
    )
    center = fixtures.create_test_center(
        api, name="Eugene Testing Hall", state_code="OR", seat_labels=["S1", "S2"]
    )

    validate_error(
        api.create_exam_appointment(
            factories.exam_appointment_payload(
                track["authorization"]["id"],
                center["id"],
                seat_label="S9",
                window_start="2026-09-10T09:00:00Z",
                window_end="2026-09-10T17:00:00Z",
            ),
            make_applicant_headers(track["engineer"]["id"]),
        ),
        "ERR_SEAT_LABEL_NOT_FOUND",
    )

    untouched = validate_success(
        api.get_test_center(center["id"], BOARD_SECRETARY_HEADERS)
    )
    assert_seat_ledger(untouched, seat_count=2, committed=0, available=2)
    assert untouched["seat_labels"] == ["S1", "S2"]
    items, meta = validate_paginated(
        api.list_exam_appointments(
            make_applicant_headers(track["engineer"]["id"]),
            params={"test_center_id": center["id"]},
        )
    )
    assert meta["total_count"] == 0
    assert items == []


def test_booking_a_470_minute_window_is_refused_on_window_length(api):
    """PRD §3.5: "The window length is checked first: `window_end` must be exactly 480 minutes — eight hours — after `window_start`, and any other span is refused with `ERR_EXAM_WINDOW_LENGTH_INVALID` (HTTP 422)."

    Design: Corner/errors/exam_scheduling_guards_center_seat_and_window_length
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="exam_approved",
        submission_overrides=ENDORSED,
        referee_overrides=REFEREE,
    )
    center = fixtures.create_test_center(
        api, name="Eugene Testing Hall", state_code="OR", seat_labels=["S1", "S2"]
    )

    validate_error(
        api.create_exam_appointment(
            factories.exam_appointment_payload(
                track["authorization"]["id"],
                center["id"],
                seat_label="S1",
                window_start="2026-09-10T09:00:00Z",
                window_end="2026-09-10T16:50:00Z",
            ),
            make_applicant_headers(track["engineer"]["id"]),
        ),
        "ERR_EXAM_WINDOW_LENGTH_INVALID",
    )

    untouched = validate_success(
        api.get_test_center(center["id"], BOARD_SECRETARY_HEADERS)
    )
    assert_seat_ledger(untouched, seat_count=2, committed=0, available=2)
    authorization = validate_success(
        api.get_exam_authorization(
            track["authorization"]["id"],
            make_applicant_headers(track["engineer"]["id"]),
        )
    )
    assert authorization["status"] == "APPROVED_TO_SIT"


def test_booking_an_exact_480_minute_window_commits_one_seat(api):
    """PRD §3.5: "On success, the owning centre's `seats_committed` rises by 1 and its `seats_available` falls by 1, and both the authorization's and the centre's `version` are incremented."

    Design: Corner/errors/exam_scheduling_guards_center_seat_and_window_length
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="exam_approved",
        submission_overrides=ENDORSED,
        referee_overrides=REFEREE,
    )
    center = fixtures.create_test_center(
        api, name="Eugene Testing Hall", state_code="OR", seat_labels=["S1", "S2"]
    )
    authorization_version = track["authorization"]["version"]
    center_version = center["version"]

    appointment = validate_success(
        api.create_exam_appointment(
            factories.exam_appointment_payload(
                track["authorization"]["id"],
                center["id"],
                seat_label="S1",
                window_start="2026-09-10T09:00:00Z",
                window_end="2026-09-10T17:00:00Z",
            ),
            make_applicant_headers(track["engineer"]["id"]),
        ),
        201,
    )

    assert appointment["status"] == "SCHEDULED"
    assert appointment["seat_label"] == "S1"
    booked_center = validate_success(
        api.get_test_center(center["id"], BOARD_SECRETARY_HEADERS)
    )
    assert_seat_ledger(booked_center, seat_count=2, committed=1, available=1)
    assert booked_center["version"] == center_version + 1
    authorization = validate_success(
        api.get_exam_authorization(
            track["authorization"]["id"],
            make_applicant_headers(track["engineer"]["id"]),
        )
    )
    assert authorization["status"] == "SCHEDULED"
    assert authorization["version"] == authorization_version + 1


def test_retake_at_the_failure_instant_is_refused_on_the_waiting_period(api):
    """PRD §3.5: "the logical clock must have reached `retake_eligible_at`, an early attempt being refused with `ERR_RETAKE_WAITING_PERIOD` (HTTP 409)"

    Design: Corner/errors/exam_retake_waiting_period_then_attempt_limit_reached
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="exam_approved",
        submission_overrides=ENDORSED,
        referee_overrides=REFEREE,
    )
    center = fixtures.create_test_center(
        api, name="Bend Testing Hall", state_code="OR", seat_labels=["S1", "S2"]
    )
    authorization_id = track["authorization"]["id"]
    applicant_headers = make_applicant_headers(track["engineer"]["id"])

    fixtures.book_appointment(
        api,
        authorization_id,
        center["id"],
        track["engineer"]["id"],
        seat_label="S1",
        window_start="2026-09-10T09:00:00Z",
        window_end="2026-09-10T17:00:00Z",
    )
    fixtures.set_clock(api, "2026-09-10T17:00:00Z")
    failed = fixtures.score_exam(
        api,
        authorization_id,
        raw_score=65,
        administered_at="2026-09-10T17:00:00Z",
        ncees_transmission_id="TX-YARA-1",
    )
    assert failed["status"] == "FAILED"
    assert failed["result"] == "FAIL"
    assert failed["retake_eligible_at"] == "2026-12-09T17:00:00.000Z"

    validate_error(
        api.retake_exam(authorization_id, applicant_headers),
        "ERR_RETAKE_WAITING_PERIOD",
    )

    stored = validate_success(
        api.get_exam_authorization(authorization_id, applicant_headers)
    )
    assert stored["status"] == "FAILED"
    assert stored["attempt_number"] == 1
    assert stored["raw_score"] == 65


def test_retake_exactly_at_retake_eligible_at_rearms_the_authorization(api):
    """PRD §3.5: "Retaking moves it `FAILED → APPROVED_TO_SIT`, increments `attempt_number` by 1, resets `raw_score` to `null`, `result` to `PENDING` and `retake_eligible_at` to `null`."

    Design: Corner/errors/exam_retake_waiting_period_then_attempt_limit_reached
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="exam_approved",
        submission_overrides=ENDORSED,
        referee_overrides=REFEREE,
    )
    center = fixtures.create_test_center(
        api, name="Bend Testing Hall", state_code="OR", seat_labels=["S1", "S2"]
    )
    authorization_id = track["authorization"]["id"]
    applicant_headers = make_applicant_headers(track["engineer"]["id"])

    fixtures.book_appointment(
        api,
        authorization_id,
        center["id"],
        track["engineer"]["id"],
        seat_label="S1",
        window_start="2026-09-10T09:00:00Z",
        window_end="2026-09-10T17:00:00Z",
    )
    fixtures.set_clock(api, "2026-09-10T17:00:00Z")
    fixtures.score_exam(
        api,
        authorization_id,
        raw_score=65,
        administered_at="2026-09-10T17:00:00Z",
        ncees_transmission_id="TX-YARA-1",
    )
    fixtures.set_clock(api, "2026-12-09T17:00:00Z")

    rearmed = validate_success(api.retake_exam(authorization_id, applicant_headers))

    assert rearmed["status"] == "APPROVED_TO_SIT"
    assert rearmed["attempt_number"] == 2
    assert rearmed["raw_score"] is None
    assert rearmed["result"] == "PENDING"
    assert rearmed["retake_eligible_at"] is None
    assert rearmed["authorization_expires_at"] == "2027-08-01T00:00:00.000Z"
    released = validate_success(
        api.get_test_center(center["id"], BOARD_SECRETARY_HEADERS)
    )
    assert_seat_ledger(released, seat_count=2, committed=0, available=2)


def test_fourth_sitting_after_three_failures_is_refused_on_the_attempt_limit(api):
    """PRD §3.5: "`attempt_number` must be below 3, a fourth sitting being refused with `ERR_ATTEMPT_LIMIT_REACHED` (HTTP 409)"

    Design: Corner/errors/exam_retake_waiting_period_then_attempt_limit_reached
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="exam_approved",
        submission_overrides=ENDORSED,
        referee_overrides=REFEREE,
    )
    center = fixtures.create_test_center(
        api, name="Bend Testing Hall", state_code="OR", seat_labels=["S1", "S2"]
    )
    authorization_id = track["authorization"]["id"]
    engineer_id = track["engineer"]["id"]
    applicant_headers = make_applicant_headers(engineer_id)

    sittings = (
        (None, "2026-09-10T09:00:00Z", "2026-09-10T17:00:00Z", 65, "2026-12-09T17:00:00.000Z"),
        (
            "2026-12-09T17:00:00Z",
            "2026-12-15T09:00:00Z",
            "2026-12-15T17:00:00Z",
            60,
            "2027-03-15T17:00:00.000Z",
        ),
        (
            "2027-03-15T17:00:00Z",
            "2027-03-20T09:00:00Z",
            "2027-03-20T17:00:00Z",
            55,
            "2027-06-18T17:00:00.000Z",
        ),
    )
    for index, sitting in enumerate(sittings):
        retake_at, window_start, window_end, raw_score, eligible_at = sitting
        if retake_at is not None:
            fixtures.set_clock(api, retake_at)
            rearmed = fixtures.retake_exam(api, authorization_id, engineer_id)
            assert rearmed["attempt_number"] == index + 1
            assert rearmed["status"] == "APPROVED_TO_SIT"
            assert rearmed["retake_eligible_at"] is None
        fixtures.book_appointment(
            api,
            authorization_id,
            center["id"],
            engineer_id,
            seat_label="S1",
            window_start=window_start,
            window_end=window_end,
        )
        fixtures.set_clock(api, window_end)
        failed = fixtures.score_exam(
            api,
            authorization_id,
            raw_score=raw_score,
            administered_at=window_end,
            ncees_transmission_id=f"TX-YARA-{index + 1}",
        )
        assert failed["status"] == "FAILED"
        assert failed["attempt_number"] == index + 1
        assert failed["retake_eligible_at"] == eligible_at

    summary = fixtures.set_clock(api, "2027-06-18T17:00:00Z")
    assert summary["expired_authorization_count"] == 0

    validate_error(
        api.retake_exam(authorization_id, applicant_headers),
        "ERR_ATTEMPT_LIMIT_REACHED",
    )

    stored = validate_success(
        api.get_exam_authorization(authorization_id, applicant_headers)
    )
    assert stored["status"] == "FAILED"
    assert stored["attempt_number"] == 3
    assert stored["raw_score"] == 55
    assert stored["authorization_expires_at"] == "2027-08-01T00:00:00.000Z"
    ledger = validate_success(api.get_test_center(center["id"], BOARD_SECRETARY_HEADERS))
    assert_seat_ledger(ledger, seat_count=2, committed=0, available=2)


def test_booking_at_the_authorization_expiry_instant_is_refused(api):
    """PRD §3.5: "Finally, the logical clock must be strictly before the authorization's `authorization_expires_at`; a lapsed envelope is refused with `ERR_AUTHORIZATION_EXPIRED` (HTTP 409)."

    Design: Corner/errors/exam_appointment_at_authorization_expiry_instant_rejected
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="exam_approved",
        submission_overrides=ENDORSED,
        referee_overrides=REFEREE,
    )
    center = fixtures.create_test_center(
        api, name="Medford Testing Hall", state_code="OR", seat_labels=["S1", "S2"]
    )
    authorization_id = track["authorization"]["id"]
    applicant_headers = make_applicant_headers(track["engineer"]["id"])
    assert track["authorization"]["authorization_expires_at"] == "2027-08-01T00:00:00.000Z"

    summary = validate_success(
        api.set_current_utc(
            factories.clock_payload("2027-08-01T00:00:00Z"), BOARD_SECRETARY_HEADERS
        )
    )
    assert summary["current_utc"] == "2027-08-01T00:00:00.000Z"
    assert summary["expired_authorization_count"] == 0
    assert summary["cancelled_appointment_count"] == 0

    validate_error(
        api.create_exam_appointment(
            factories.exam_appointment_payload(
                authorization_id,
                center["id"],
                seat_label="S1",
                window_start="2027-08-05T09:00:00Z",
                window_end="2027-08-05T17:00:00Z",
            ),
            applicant_headers,
        ),
        "ERR_AUTHORIZATION_EXPIRED",
    )

    stored = validate_success(
        api.get_exam_authorization(authorization_id, applicant_headers)
    )
    assert stored["status"] == "APPROVED_TO_SIT"
    assert stored["authorization_expires_at"] == "2027-08-01T00:00:00.000Z"
    ledger = validate_success(api.get_test_center(center["id"], BOARD_SECRETARY_HEADERS))
    assert_seat_ledger(ledger, seat_count=2, committed=0, available=2)
    items, meta = validate_paginated(
        api.list_exam_appointments(
            applicant_headers, params={"exam_authorization_id": authorization_id}
        )
    )
    assert meta["total_count"] == 0
    assert items == []
