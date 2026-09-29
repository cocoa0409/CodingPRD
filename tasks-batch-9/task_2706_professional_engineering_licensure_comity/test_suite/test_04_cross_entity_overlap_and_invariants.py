"""Cross-entity guard states, temporal overlap arithmetic and the conserved ledgers.

Covers the guards that read state on a different row from the one being written
(plan sealing against the firm posture, reference submission against the
referee's licence, consent-order proposal against the investigative axis), the
two overlap domains (buffered half-open seat windows and closed inclusive
experience months) and the two conservation laws (a test centre's seat ledger
and an application's experience-credit ledger).
"""

import pytest

from test_helpers import (
    BOARD_INVESTIGATOR_HEADERS,
    BOARD_LICENSING_OFFICER_HEADERS,
    BOARD_REVIEWER_HEADERS,
    TESTING_SERVICE_HEADERS,
    assert_iso_timestamp,
    assert_seat_ledger,
    factories,
    fixtures,
    make_applicant_headers,
    make_licensee_headers,
    make_supervising_engineer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_seal_refused_while_firm_lapsed_by_responsible_charge_suspension(api):
    """PRD §3.8: "First the firm must stand in `ACTIVE`, otherwise `ERR_FIRM_STATE_INVALID` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/seal_gated_on_firm_registration_state
    """
    engineer, license_ = fixtures.create_licensed_engineer(api)
    firm = fixtures.create_firm(api, license_["id"])

    case = fixtures.create_case(
        api, allegation_type="NEGLIGENCE", respondent_license_id=license_["id"]
    )
    fixtures.open_investigation(api, case["id"])
    case = fixtures.record_finding(
        api,
        case["id"],
        finding="PROBABLE_CAUSE",
        aggravating_factor_count=1,
        mitigating_factor_count=0,
        violation_count=1,
    )
    assert case["assessed_penalty_cents"] == 247500
    order = fixtures.propose_consent_order(
        api,
        case["id"],
        case["version"],
        sanction_type="SUSPENSION",
        suspension_months=6,
        penalty_paid_cents=247500,
    )
    fixtures.execute_consent_order(
        api, order["id"], executed_on="2026-08-01T00:00:00Z"
    )

    suspended = validate_success(
        api.get_license(license_["id"], BOARD_LICENSING_OFFICER_HEADERS), 200
    )
    assert suspended["status"] == "SUSPENDED"
    assert str(suspended["suspension_ends_at"]).startswith("2027-02-01")
    lapsed_firm = validate_success(
        api.get_firm_registration(firm["id"], BOARD_LICENSING_OFFICER_HEADERS), 200
    )
    assert lapsed_firm["status"] == "LAPSED_NO_RESPONSIBLE_CHARGE"

    plan = fixtures.create_plan_submission(api, firm["id"], sheet_count=3)
    assert plan["status"] == "DRAFT"

    response = api.seal_plan_submission(
        plan["id"],
        factories.seal_payload(license_["id"]),
        make_licensee_headers(engineer["id"]),
    )
    validate_error(response, "ERR_FIRM_STATE_INVALID")

    untouched = validate_success(
        api.get_plan_submission(plan["id"], BOARD_LICENSING_OFFICER_HEADERS), 200
    )
    assert untouched["status"] == "DRAFT"
    assert untouched["sealing_license_id"] is None
    assert untouched["seal_affixed_at"] is None
    assert untouched["responsible_charge_attested"] is False
    assert untouched["version"] == plan["version"]


def test_seal_succeeds_on_active_firm_holding_the_sealing_license(api):
    """PRD §3.8: "On success the set moves `DRAFT → SEALED`, both supplied fields are written, and `seal_affixed_at` is stamped from the logical clock."

    Design: Difficulty/cross_entity_state_dependency/seal_gated_on_firm_registration_state
    """
    engineer, license_ = fixtures.create_licensed_engineer(api)
    firm = fixtures.create_firm(api, license_["id"])
    assert firm["status"] == "ACTIVE"
    plan = fixtures.create_plan_submission(api, firm["id"], sheet_count=3)

    sealed = validate_success(
        api.seal_plan_submission(
            plan["id"],
            factories.seal_payload(license_["id"]),
            make_licensee_headers(engineer["id"]),
        ),
        200,
    )
    assert sealed["status"] == "SEALED"
    assert sealed["sealing_license_id"] == license_["id"]
    assert sealed["responsible_charge_attested"] is True
    assert_iso_timestamp(sealed["seal_affixed_at"])
    assert str(sealed["seal_affixed_at"]).startswith("2026-08-01")
    assert sealed["version"] == plan["version"] + 1

    still_active = validate_success(
        api.get_firm_registration(firm["id"], BOARD_LICENSING_OFFICER_HEADERS), 200
    )
    assert still_active["status"] == "ACTIVE"


def test_reference_submit_refused_when_referee_holds_no_license_then_allowed_once_issued(api):
    """PRD §3.3: "The referee must hold a licence in `ACTIVE` at the moment of answering — an expired, suspended or revoked supervisor cannot attest, and the attempt is refused with `ERR_REFEREE_LICENSE_INACTIVE` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/reference_submit_gated_on_referee_active_license
    """
    applicant = fixtures.create_engineer(api)
    referee = fixtures.create_engineer(api)
    application = fixtures.create_application(api, applicant["id"])
    fixtures.evaluate_education(api, application["id"])
    record = fixtures.add_experience_record(
        api,
        application["id"],
        applicant["id"],
        period_start_month="2019-01",
        period_end_month="2022-12",
        responsibility_level="RESPONSIBLE_CHARGE",
        post_degree=True,
    )
    reference = fixtures.request_reference(
        api, record["id"], applicant["id"], referee["id"], relationship="DIRECT_SUPERVISOR"
    )
    fixtures.pay_assessed_fee(api, application["id"], applicant["id"])
    fixtures.submit_application(api, application["id"], applicant["id"])

    pending = validate_success(
        api.get_experience_record(record["id"], BOARD_REVIEWER_HEADERS), 200
    )
    assert pending["verification_status"] == "PENDING_VERIFICATION"

    blocked = api.submit_reference(
        reference["id"],
        factories.reference_submission_payload(
            evaluation_score=5, months_confirmed=48, responsibility_confirmed=True
        ),
        make_supervising_engineer_headers(referee["id"]),
    )
    validate_error(blocked, "ERR_REFEREE_LICENSE_INACTIVE")

    unchanged = validate_success(
        api.get_reference(reference["id"], BOARD_REVIEWER_HEADERS), 200
    )
    assert unchanged["status"] == "REQUESTED"
    assert unchanged["submitted_at"] is None
    assert unchanged["evaluation_score"] is None
    assert unchanged["version"] == reference["version"]

    referee_license = fixtures.issue_license(api, referee["id"])
    assert referee_license["status"] == "ACTIVE"

    submitted = validate_success(
        api.submit_reference(
            reference["id"],
            factories.reference_submission_payload(
                evaluation_score=5, months_confirmed=48, responsibility_confirmed=True
            ),
            make_supervising_engineer_headers(referee["id"]),
        ),
        200,
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["months_confirmed"] == 48
    assert submitted["evaluation_score"] == 5
    assert submitted["responsibility_confirmed"] is True
    assert_iso_timestamp(submitted["submitted_at"])

    still_pending = validate_success(
        api.get_experience_record(record["id"], BOARD_REVIEWER_HEADERS), 200
    )
    assert still_pending["verification_status"] == "PENDING_VERIFICATION"


def test_reference_submit_refused_for_suspended_referee_but_allowed_for_licensed_referee(api):
    """PRD §3.3: "The referee must hold a licence in `ACTIVE` at the moment of answering — an expired, suspended or revoked supervisor cannot attest, and the attempt is refused with `ERR_REFEREE_LICENSE_INACTIVE` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/reference_submit_gated_on_referee_active_license
    """
    track = fixtures.setup_exam_track(api, stop_after="submitted")
    referee = track["referee"]
    referee_license = track["referee_license"]

    case = fixtures.create_case(
        api, allegation_type="NEGLIGENCE", respondent_license_id=referee_license["id"]
    )
    fixtures.open_investigation(api, case["id"])
    case = fixtures.record_finding(
        api,
        case["id"],
        finding="PROBABLE_CAUSE",
        aggravating_factor_count=1,
        mitigating_factor_count=0,
        violation_count=1,
    )
    order = fixtures.propose_consent_order(
        api,
        case["id"],
        case["version"],
        sanction_type="SUSPENSION",
        suspension_months=6,
        penalty_paid_cents=247500,
    )
    fixtures.execute_consent_order(
        api, order["id"], executed_on="2026-08-01T00:00:00Z"
    )
    suspended = validate_success(
        api.get_license(referee_license["id"], BOARD_LICENSING_OFFICER_HEADERS), 200
    )
    assert suspended["status"] == "SUSPENDED"

    blocked = api.submit_reference(
        track["reference"]["id"],
        factories.reference_submission_payload(
            evaluation_score=5, months_confirmed=48, responsibility_confirmed=True
        ),
        make_supervising_engineer_headers(referee["id"]),
    )
    validate_error(blocked, "ERR_REFEREE_LICENSE_INACTIVE")
    frozen = validate_success(
        api.get_reference(track["reference"]["id"], BOARD_REVIEWER_HEADERS), 200
    )
    assert frozen["status"] == "REQUESTED"

    second_referee, second_license = fixtures.create_licensed_engineer(api)
    assert second_license["status"] == "ACTIVE"
    second_reference = fixtures.request_reference(
        api,
        track["experience_record"]["id"],
        track["engineer"]["id"],
        second_referee["id"],
        relationship="DIRECT_SUPERVISOR",
    )
    accepted_shape = validate_success(
        api.submit_reference(
            second_reference["id"],
            factories.reference_submission_payload(
                evaluation_score=4, months_confirmed=36, responsibility_confirmed=True
            ),
            make_supervising_engineer_headers(second_referee["id"]),
        ),
        200,
    )
    assert accepted_shape["status"] == "SUBMITTED"
    assert accepted_shape["months_confirmed"] == 36
    assert accepted_shape["evaluation_score"] == 4

    unaffected = validate_success(
        api.get_reference(track["reference"]["id"], BOARD_REVIEWER_HEADERS), 200
    )
    assert unaffected["status"] == "REQUESTED"


def test_consent_order_refused_while_case_still_investigating_then_allowed_at_probable_cause(api):
    """PRD §3.9: "The case's `investigation_status` must be `PROBABLE_CAUSE`; proposing against a case still under investigation, or one found to have no cause, is refused with `ERR_PROBABLE_CAUSE_REQUIRED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/consent_order_gated_on_case_probable_cause
    """
    engineer, license_ = fixtures.create_licensed_engineer(api)
    case = fixtures.create_case(
        api,
        allegation_type="CPC_FRAUD",
        complainant_name="Board CPC Unit",
        respondent_license_id=license_["id"],
    )
    case = fixtures.open_investigation(api, case["id"])
    assert case["investigation_status"] == "INVESTIGATING"
    assert case["sanction_status"] == "NONE"
    assert case["assessed_penalty_cents"] == 0
    fresh_version = case["version"]

    too_early = api.create_consent_order(
        factories.consent_order_payload(
            case["id"], fresh_version, sanction_type="REPRIMAND", penalty_paid_cents=0
        ),
        BOARD_INVESTIGATOR_HEADERS,
    )
    validate_error(too_early, "ERR_PROBABLE_CAUSE_REQUIRED")

    unmoved = validate_success(api.get_case(case["id"], BOARD_INVESTIGATOR_HEADERS), 200)
    assert unmoved["sanction_status"] == "NONE"
    assert unmoved["investigation_status"] == "INVESTIGATING"
    assert unmoved["version"] == fresh_version

    found = validate_success(
        api.record_finding(
            case["id"],
            factories.finding_payload(
                finding="PROBABLE_CAUSE",
                aggravating_factor_count=2,
                mitigating_factor_count=1,
                violation_count=1,
            ),
            BOARD_INVESTIGATOR_HEADERS,
        ),
        200,
    )
    assert found["investigation_status"] == "PROBABLE_CAUSE"
    assert found["penalty_factor"] == pytest.approx(1.35)
    assert found["assessed_penalty_cents"] == 199800

    order = validate_success(
        api.create_consent_order(
            factories.consent_order_payload(
                case["id"],
                found["version"],
                sanction_type="REPRIMAND",
                penalty_paid_cents=199800,
            ),
            BOARD_INVESTIGATOR_HEADERS,
        ),
        201,
    )
    assert order["status"] == "PROPOSED"
    assert order["penalty_cents"] == 199800
    assert order["penalty_paid_cents"] == 199800
    assert order["executed_on"] is None
    assert order["executed_by_user_id"] is None

    settled = validate_success(api.get_case(case["id"], BOARD_INVESTIGATOR_HEADERS), 200)
    assert settled["sanction_status"] == "PROPOSED"
    assert settled["investigation_status"] == "PROBABLE_CAUSE"
    assert settled["version"] == found["version"] + 1

    respondent = validate_success(
        api.get_license(license_["id"], BOARD_LICENSING_OFFICER_HEADERS), 200
    )
    assert respondent["status"] == "ACTIVE"


def test_consent_order_refused_on_a_case_found_to_have_no_cause(api):
    """PRD §3.9: "The case's `investigation_status` must be `PROBABLE_CAUSE`; proposing against a case still under investigation, or one found to have no cause, is refused with `ERR_PROBABLE_CAUSE_REQUIRED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/consent_order_gated_on_case_probable_cause
    """
    engineer, license_ = fixtures.create_licensed_engineer(api)
    case = fixtures.create_case(
        api,
        allegation_type="CPC_FRAUD",
        complainant_name="Board CPC Unit",
        respondent_license_id=license_["id"],
    )
    fixtures.open_investigation(api, case["id"])
    cleared = fixtures.record_finding(
        api,
        case["id"],
        finding="NO_CAUSE",
        aggravating_factor_count=2,
        mitigating_factor_count=1,
        violation_count=0,
    )
    assert cleared["investigation_status"] == "NO_CAUSE"
    assert cleared["penalty_factor"] == pytest.approx(0.0)
    assert cleared["assessed_penalty_cents"] == 0
    assert cleared["sanction_status"] == "NONE"

    refused = api.create_consent_order(
        factories.consent_order_payload(
            case["id"],
            cleared["version"],
            sanction_type="REPRIMAND",
            penalty_paid_cents=0,
        ),
        BOARD_INVESTIGATOR_HEADERS,
    )
    validate_error(refused, "ERR_PROBABLE_CAUSE_REQUIRED")

    unmoved = validate_success(api.get_case(case["id"], BOARD_INVESTIGATOR_HEADERS), 200)
    assert unmoved["sanction_status"] == "NONE"
    assert unmoved["version"] == cleared["version"]

    orders, meta = validate_paginated(
        api.list_consent_orders(BOARD_INVESTIGATOR_HEADERS, {"case_id": case["id"]})
    )
    assert meta["total_count"] == 0
    assert orders == []


def test_seat_window_conflict_on_the_same_seat_label_for_a_partial_straddle(api):
    """PRD §3.5: "Each existing appointment on the same centre and the same `seat_label` that still stands in `SCHEDULED` is inflated by appending 45 minutes to its `window_end`; the new booking collides with it when the new `window_start` falls strictly before that inflated end **and** the new booking's own inflated end falls strictly after the existing `window_start`."

    Design: Difficulty/resource_temporal_overlap/exam_seat_overlap_scoped_to_seat_label
    """
    incumbent = fixtures.setup_scheduled_appointment(
        api,
        center_overrides={"seat_labels": ["S1", "S2"], "status": "OPEN"},
        appointment_overrides={
            "seat_label": "S1",
            "window_start": "2026-09-10T08:00:00Z",
            "window_end": "2026-09-10T16:00:00Z",
        },
        submission_overrides={"responsibility_confirmed": True},
    )
    center = incumbent["test_center"]
    rival = fixtures.setup_exam_track(
        api,
        stop_after="exam_approved",
        submission_overrides={"responsibility_confirmed": True},
    )

    collision = api.create_exam_appointment(
        factories.exam_appointment_payload(
            rival["authorization"]["id"],
            center["id"],
            seat_label="S1",
            window_start="2026-09-10T12:00:00Z",
            window_end="2026-09-10T20:00:00Z",
        ),
        make_applicant_headers(rival["engineer"]["id"]),
    )
    validate_error(collision, "ERR_SEAT_WINDOW_CONFLICT")

    held = validate_success(
        api.get_exam_appointment(
            incumbent["appointment"]["id"], BOARD_LICENSING_OFFICER_HEADERS
        ),
        200,
    )
    assert held["status"] == "SCHEDULED"
    assert held["seat_label"] == "S1"

    rival_auth = validate_success(
        api.get_exam_authorization(
            rival["authorization"]["id"], BOARD_LICENSING_OFFICER_HEADERS
        ),
        200,
    )
    assert rival_auth["status"] == "APPROVED_TO_SIT"

    ledger = validate_success(
        api.get_test_center(center["id"], BOARD_LICENSING_OFFICER_HEADERS), 200
    )
    assert_seat_ledger(ledger, seat_count=2, committed=1, available=1)


def test_identical_window_is_accepted_on_the_sibling_seat_label(api):
    """PRD §3.5: "Appointments on different `seat_labels` of the same centre never collide with one another; they compete only through the capacity dimension below."

    Design: Difficulty/resource_temporal_overlap/exam_seat_overlap_scoped_to_seat_label
    """
    incumbent = fixtures.setup_scheduled_appointment(
        api,
        center_overrides={"seat_labels": ["S1", "S2"], "status": "OPEN"},
        appointment_overrides={
            "seat_label": "S1",
            "window_start": "2026-09-10T08:00:00Z",
            "window_end": "2026-09-10T16:00:00Z",
        },
        submission_overrides={"responsibility_confirmed": True},
    )
    center = incumbent["test_center"]
    rival = fixtures.setup_exam_track(
        api,
        stop_after="exam_approved",
        submission_overrides={"responsibility_confirmed": True},
    )

    booked = validate_success(
        api.create_exam_appointment(
            factories.exam_appointment_payload(
                rival["authorization"]["id"],
                center["id"],
                seat_label="S2",
                window_start="2026-09-10T12:00:00Z",
                window_end="2026-09-10T20:00:00Z",
            ),
            make_applicant_headers(rival["engineer"]["id"]),
        ),
        201,
    )
    assert booked["seat_label"] == "S2"
    assert booked["status"] == "SCHEDULED"
    assert booked["test_center_id"] == center["id"]

    rival_auth = validate_success(
        api.get_exam_authorization(
            rival["authorization"]["id"], BOARD_LICENSING_OFFICER_HEADERS
        ),
        200,
    )
    assert rival_auth["status"] == "SCHEDULED"

    held = validate_success(
        api.get_exam_appointment(
            incumbent["appointment"]["id"], BOARD_LICENSING_OFFICER_HEADERS
        ),
        200,
    )
    assert held["status"] == "SCHEDULED"

    ledger = validate_success(
        api.get_test_center(center["id"], BOARD_LICENSING_OFFICER_HEADERS), 200
    )
    assert_seat_ledger(ledger, seat_count=2, committed=2, available=0)


def test_turnover_buffer_refuses_forty_four_minutes_and_admits_forty_five(api):
    """PRD §3.5: "Because both comparisons are strict, a booking starting exactly 45 minutes after an existing window's end does not collide, while one starting 44 minutes after it does."

    Design: Difficulty/resource_temporal_overlap/exam_seat_overlap_scoped_to_seat_label
    """
    incumbent = fixtures.setup_scheduled_appointment(
        api,
        center_overrides={"seat_labels": ["S1", "S2"], "status": "OPEN"},
        appointment_overrides={
            "seat_label": "S1",
            "window_start": "2026-09-10T08:00:00Z",
            "window_end": "2026-09-10T16:00:00Z",
        },
        submission_overrides={"responsibility_confirmed": True},
    )
    center = incumbent["test_center"]
    rival = fixtures.setup_exam_track(
        api,
        stop_after="exam_approved",
        submission_overrides={"responsibility_confirmed": True},
    )

    inside_buffer = api.create_exam_appointment(
        factories.exam_appointment_payload(
            rival["authorization"]["id"],
            center["id"],
            seat_label="S1",
            window_start="2026-09-10T16:44:00Z",
            window_end="2026-09-11T00:44:00Z",
        ),
        make_applicant_headers(rival["engineer"]["id"]),
    )
    validate_error(inside_buffer, "ERR_SEAT_WINDOW_CONFLICT")

    ledger = validate_success(
        api.get_test_center(center["id"], BOARD_LICENSING_OFFICER_HEADERS), 200
    )
    assert_seat_ledger(ledger, seat_count=2, committed=1, available=1)

    on_the_boundary = validate_success(
        api.create_exam_appointment(
            factories.exam_appointment_payload(
                rival["authorization"]["id"],
                center["id"],
                seat_label="S1",
                window_start="2026-09-10T16:45:00Z",
                window_end="2026-09-11T00:45:00Z",
            ),
            make_applicant_headers(rival["engineer"]["id"]),
        ),
        201,
    )
    assert on_the_boundary["seat_label"] == "S1"
    assert on_the_boundary["status"] == "SCHEDULED"

    ledger = validate_success(
        api.get_test_center(center["id"], BOARD_LICENSING_OFFICER_HEADERS), 200
    )
    assert_seat_ledger(ledger, seat_count=2, committed=2, available=0)

    rival_auth = validate_success(
        api.get_exam_authorization(
            rival["authorization"]["id"], BOARD_LICENSING_OFFICER_HEADERS
        ),
        200,
    )
    assert rival_auth["status"] == "SCHEDULED"


def test_experience_block_sharing_one_boundary_month_is_refused(api):
    """PRD §3.3: "Two blocks running January through June and July through December of the same year are merely adjacent and both stand; a block running January through June and a second running June through November share the month of June, and the second is refused."

    Design: Difficulty/resource_temporal_overlap/experience_period_shared_boundary_month_versus_adjacent_month
    """
    engineer = fixtures.create_engineer(api)
    application = fixtures.create_application(api, engineer["id"])
    fixtures.evaluate_education(api, application["id"])
    first = fixtures.add_experience_record(
        api,
        application["id"],
        engineer["id"],
        employer_name="Iyer Coastal",
        position_title="Design Engineer",
        period_start_month="2024-01",
        period_end_month="2024-06",
        responsibility_level="PROGRESSIVE",
        post_degree=True,
    )
    assert first["raw_months"] == 6

    overlapping = api.create_experience_record(
        application["id"],
        factories.experience_record_payload(
            employer_name="Iyer Coastal",
            position_title="Design Engineer",
            period_start_month="2024-06",
            period_end_month="2024-11",
            responsibility_level="PROGRESSIVE",
            post_degree=True,
        ),
        make_applicant_headers(engineer["id"]),
    )
    validate_error(overlapping, "ERR_EXPERIENCE_PERIOD_OVERLAP")

    records, meta = validate_paginated(
        api.list_experience_records(
            BOARD_REVIEWER_HEADERS, {"application_id": application["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in records] == [first["id"]]

    unbilled = validate_success(
        api.get_application(application["id"], BOARD_REVIEWER_HEADERS), 200
    )
    assert unbilled["fee_assessment_cents"] == 27500
    assert unbilled["provisional_experience_months"] == 4


def test_experience_block_starting_the_month_after_the_incumbent_is_accepted(api):
    """PRD §3.3: "Two blocks running January through June and July through December of the same year are merely adjacent and both stand; a block running January through June and a second running June through November share the month of June, and the second is refused."

    Design: Difficulty/resource_temporal_overlap/experience_period_shared_boundary_month_versus_adjacent_month
    """
    engineer = fixtures.create_engineer(api)
    application = fixtures.create_application(api, engineer["id"])
    fixtures.evaluate_education(api, application["id"])
    first = fixtures.add_experience_record(
        api,
        application["id"],
        engineer["id"],
        employer_name="Iyer Coastal",
        position_title="Design Engineer",
        period_start_month="2024-01",
        period_end_month="2024-06",
        responsibility_level="PROGRESSIVE",
        post_degree=True,
    )

    adjacent = validate_success(
        api.create_experience_record(
            application["id"],
            factories.experience_record_payload(
                employer_name="Iyer Coastal",
                position_title="Design Engineer",
                period_start_month="2024-07",
                period_end_month="2024-12",
                responsibility_level="PROGRESSIVE",
                post_degree=True,
            ),
            make_applicant_headers(engineer["id"]),
        ),
        201,
    )
    assert adjacent["raw_months"] == 6
    assert adjacent["credit_multiplier"] == pytest.approx(0.75)
    assert adjacent["credited_months"] == 0
    assert adjacent["verification_status"] == "UNVERIFIED"

    incumbent = validate_success(
        api.get_experience_record(first["id"], BOARD_REVIEWER_HEADERS), 200
    )
    assert incumbent["raw_months"] == 6
    assert incumbent["credited_months"] == 0

    application = validate_success(
        api.get_application(application["id"], BOARD_REVIEWER_HEADERS), 200
    )
    assert application["provisional_experience_months"] == 8
    assert application["verified_experience_months"] == 0
    assert application["fee_assessment_cents"] == 30000

    records, meta = validate_paginated(
        api.list_experience_records(
            BOARD_REVIEWER_HEADERS, {"application_id": application["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in records} == {first["id"], adjacent["id"]}


def test_candidate_cancellation_restores_the_seat_ledger_and_cycles_the_authorization(api):
    """PRD §3.5: "The authorization returns `SCHEDULED → APPROVED_TO_SIT`, which is the cyclic edge that lets the candidate re-book, and the seat is released: `seats_committed` falls by 1 and `seats_available` rises by 1, restoring both counters to exactly their pre-booking values."

    Design: Difficulty/compensating_invariant/seat_capacity_conservation_survives_cancel
    """
    track = fixtures.setup_scheduled_appointment(
        api,
        center_overrides={"seat_labels": ["S1", "S2"], "status": "OPEN"},
        appointment_overrides={
            "seat_label": "S1",
            "window_start": "2026-09-10T08:00:00Z",
            "window_end": "2026-09-10T16:00:00Z",
        },
        submission_overrides={"responsibility_confirmed": True},
    )
    center = validate_success(
        api.get_test_center(track["test_center"]["id"], BOARD_LICENSING_OFFICER_HEADERS),
        200,
    )
    assert_seat_ledger(center, seat_count=2, committed=1, available=1)

    cancelled = validate_success(
        api.cancel_exam_appointment(
            track["appointment"]["id"],
            make_applicant_headers(track["engineer"]["id"]),
            {"reason": "Travel conflict"},
        ),
        200,
    )
    assert cancelled["status"] == "CANCELLED_BY_CANDIDATE"

    authorization = validate_success(
        api.get_exam_authorization(
            track["authorization"]["id"], BOARD_LICENSING_OFFICER_HEADERS
        ),
        200,
    )
    assert authorization["status"] == "APPROVED_TO_SIT"
    assert authorization["attempt_number"] == 1
    assert authorization["result"] == "PENDING"
    assert authorization["raw_score"] is None
    assert authorization["retake_eligible_at"] is None

    released = validate_success(
        api.get_test_center(track["test_center"]["id"], BOARD_LICENSING_OFFICER_HEADERS),
        200,
    )
    assert_seat_ledger(released, seat_count=2, committed=0, available=2)

    application = validate_success(
        api.get_application(track["application"]["id"], BOARD_REVIEWER_HEADERS), 200
    )
    assert application["status"] == "EXAM_APPROVED"


def test_released_seat_is_bookable_again_at_the_same_window(api):
    """PRD §2.9: "Booking a seat and then cancelling that booking must restore both `seats_committed` and `seats_available` to their exact pre-booking values"

    Design: Difficulty/compensating_invariant/seat_capacity_conservation_survives_cancel
    """
    track = fixtures.setup_scheduled_appointment(
        api,
        center_overrides={"seat_labels": ["S1"], "status": "OPEN"},
        appointment_overrides={
            "seat_label": "S1",
            "window_start": "2026-09-10T08:00:00Z",
            "window_end": "2026-09-10T16:00:00Z",
        },
        submission_overrides={"responsibility_confirmed": True},
    )
    first_booking = track["appointment"]
    fixtures.cancel_appointment(
        api, first_booking["id"], track["engineer"]["id"], reason="Travel conflict"
    )
    emptied = validate_success(
        api.get_test_center(track["test_center"]["id"], BOARD_LICENSING_OFFICER_HEADERS),
        200,
    )
    assert_seat_ledger(emptied, seat_count=1, committed=0, available=1)

    rebooked = validate_success(
        api.create_exam_appointment(
            factories.exam_appointment_payload(
                track["authorization"]["id"],
                track["test_center"]["id"],
                seat_label="S1",
                window_start="2026-09-10T08:00:00Z",
                window_end="2026-09-10T16:00:00Z",
            ),
            make_applicant_headers(track["engineer"]["id"]),
        ),
        201,
    )
    assert rebooked["status"] == "SCHEDULED"
    assert rebooked["seat_label"] == "S1"
    assert rebooked["id"] != first_booking["id"]

    refilled = validate_success(
        api.get_test_center(track["test_center"]["id"], BOARD_LICENSING_OFFICER_HEADERS),
        200,
    )
    assert_seat_ledger(refilled, seat_count=1, committed=1, available=0)

    authorization = validate_success(
        api.get_exam_authorization(
            track["authorization"]["id"], BOARD_LICENSING_OFFICER_HEADERS
        ),
        200,
    )
    assert authorization["status"] == "SCHEDULED"
    assert authorization["attempt_number"] == 1

    stale = validate_success(
        api.get_exam_appointment(first_booking["id"], BOARD_LICENSING_OFFICER_HEADERS),
        200,
    )
    assert stale["status"] == "CANCELLED_BY_CANDIDATE"


def test_score_reporting_releases_the_seat_exactly_as_cancellation_does(api):
    """PRD §3.5: "Both outcomes store `raw_score` and `ncees_transmission_id`, move the linked appointment `SCHEDULED → COMPLETED`, and release its seat by decrementing `seats_committed` and incrementing `seats_available` — the scoring path and the cancellation path must release a seat identically, with no drift."

    Design: Difficulty/compensating_invariant/seat_capacity_conservation_survives_cancel
    """
    track = fixtures.setup_scheduled_appointment(
        api,
        center_overrides={"seat_labels": ["S1", "S2"], "status": "OPEN"},
        appointment_overrides={
            "seat_label": "S1",
            "window_start": "2026-09-10T08:00:00Z",
            "window_end": "2026-09-10T16:00:00Z",
        },
        submission_overrides={"responsibility_confirmed": True},
    )
    committed = validate_success(
        api.get_test_center(track["test_center"]["id"], BOARD_LICENSING_OFFICER_HEADERS),
        200,
    )
    assert_seat_ledger(committed, seat_count=2, committed=1, available=1)

    fixtures.set_clock(api, "2026-09-10T16:00:00Z")

    scored = validate_success(
        api.score_exam(
            track["authorization"]["id"],
            factories.score_payload(
                raw_score=82, administered_at="2026-09-10T16:00:00Z"
            ),
            TESTING_SERVICE_HEADERS,
        ),
        200,
    )
    assert scored["status"] == "PASSED"
    assert scored["result"] == "PASS"
    assert scored["raw_score"] == 82
    assert scored["ncees_transmission_id"] is not None

    finished = validate_success(
        api.get_exam_appointment(
            track["appointment"]["id"], BOARD_LICENSING_OFFICER_HEADERS
        ),
        200,
    )
    assert finished["status"] == "COMPLETED"

    released = validate_success(
        api.get_test_center(track["test_center"]["id"], BOARD_LICENSING_OFFICER_HEADERS),
        200,
    )
    assert_seat_ledger(released, seat_count=2, committed=0, available=2)


def test_recant_returns_verified_experience_months_to_its_pre_acceptance_value(api):
    """PRD §3.3: "Afterwards, the withdrawn block's `credited_months` must read 0 and the file's `verified_experience_months` must read exactly what it read before the acceptance being undone."

    Design: Difficulty/compensating_invariant/experience_credit_ledger_conservation_survives_recant
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="credit_determined",
        credit_headers=BOARD_REVIEWER_HEADERS,
        submission_overrides={"responsibility_confirmed": True},
    )
    reference_before = validate_success(
        api.get_reference(track["reference"]["id"], BOARD_REVIEWER_HEADERS), 200
    )
    assert reference_before["status"] == "ACCEPTED"
    record_before = validate_success(
        api.get_experience_record(track["experience_record"]["id"], BOARD_REVIEWER_HEADERS),
        200,
    )
    assert record_before["verification_status"] == "VERIFIED"
    assert record_before["credited_months"] == 48
    application_before = validate_success(
        api.get_application(track["application"]["id"], BOARD_REVIEWER_HEADERS), 200
    )
    assert application_before["verified_experience_months"] == 48
    assert application_before["provisional_experience_months"] == 48
    assert application_before["credit_determined_by_user_id"] == "REV-1"

    recanted = validate_success(
        api.recant_reference(
            track["reference"]["id"],
            {"recant_reason": "Records show the candidate was not in responsible charge"},
            make_supervising_engineer_headers(track["referee"]["id"]),
        ),
        200,
    )
    assert recanted["status"] == "RECANTED"
    assert (
        recanted["recant_reason"]
        == "Records show the candidate was not in responsible charge"
    )
    assert recanted["version"] == reference_before["version"] + 1

    record_after = validate_success(
        api.get_experience_record(track["experience_record"]["id"], BOARD_REVIEWER_HEADERS),
        200,
    )
    assert record_after["verification_status"] == "RECANTED"
    assert record_after["credited_months"] == 0
    assert record_after["raw_months"] == 48
    assert record_after["version"] > record_before["version"]

    application_after = validate_success(
        api.get_application(track["application"]["id"], BOARD_REVIEWER_HEADERS), 200
    )
    assert application_after["verified_experience_months"] == 0
    assert application_after["provisional_experience_months"] == 48
    assert application_after["status"] == "UNDER_REVIEW"
    assert application_after["credit_determined_by_user_id"] == "REV-1"
    assert application_after["version"] > application_before["version"]

    authorizations, meta = validate_paginated(
        api.list_exam_authorizations(
            BOARD_LICENSING_OFFICER_HEADERS, {"application_id": track["application"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert authorizations == []


def test_recant_of_one_block_rederives_the_ledger_from_the_surviving_verified_block(api):
    """PRD §2.9: "The second is the experience-credit ledger: an application's `verified_experience_months` must always equal the smaller of 96 and the sum of `credited_months` across that application's experience records whose `verification_status` is `VERIFIED`."

    Design: Difficulty/compensating_invariant/experience_credit_ledger_conservation_survives_recant
    """
    referee, referee_license = fixtures.create_licensed_engineer(api)
    applicant = fixtures.create_engineer(api)
    application = fixtures.create_application(api, applicant["id"])
    fixtures.evaluate_education(api, application["id"])

    kept = fixtures.add_experience_record(
        api,
        application["id"],
        applicant["id"],
        employer_name="Marchetti Civil",
        position_title="Engineer in Responsible Charge",
        period_start_month="2019-01",
        period_end_month="2022-12",
        responsibility_level="RESPONSIBLE_CHARGE",
        post_degree=True,
    )
    withdrawn = fixtures.add_experience_record(
        api,
        application["id"],
        applicant["id"],
        employer_name="Marchetti Civil",
        position_title="Design Engineer",
        period_start_month="2023-01",
        period_end_month="2024-12",
        responsibility_level="PROGRESSIVE",
        post_degree=True,
    )
    assert kept["raw_months"] == 48
    assert withdrawn["raw_months"] == 24

    kept_reference = fixtures.request_reference(
        api, kept["id"], applicant["id"], referee["id"], relationship="DIRECT_SUPERVISOR"
    )
    withdrawn_reference = fixtures.request_reference(
        api,
        withdrawn["id"],
        applicant["id"],
        referee["id"],
        relationship="DIRECT_SUPERVISOR",
    )
    fixtures.pay_assessed_fee(api, application["id"], applicant["id"])
    fixtures.submit_application(api, application["id"], applicant["id"])
    fixtures.submit_reference(
        api,
        kept_reference["id"],
        referee["id"],
        evaluation_score=5,
        months_confirmed=48,
        responsibility_confirmed=True,
    )
    fixtures.submit_reference(
        api,
        withdrawn_reference["id"],
        referee["id"],
        evaluation_score=5,
        months_confirmed=24,
        responsibility_confirmed=True,
    )
    fixtures.start_review(api, application["id"])
    fixtures.evaluate_reference(api, kept_reference["id"], "ACCEPT")
    fixtures.evaluate_reference(api, withdrawn_reference["id"], "ACCEPT")
    determined = fixtures.determine_credit(
        api, application["id"], BOARD_REVIEWER_HEADERS
    )
    assert determined["verified_experience_months"] == 66

    validate_success(
        api.recant_reference(
            withdrawn_reference["id"],
            {"recant_reason": "Supervision was indirect"},
            make_supervising_engineer_headers(referee["id"]),
        ),
        200,
    )

    kept_after = validate_success(
        api.get_experience_record(kept["id"], BOARD_REVIEWER_HEADERS), 200
    )
    assert kept_after["verification_status"] == "VERIFIED"
    assert kept_after["credited_months"] == 48
    withdrawn_after = validate_success(
        api.get_experience_record(withdrawn["id"], BOARD_REVIEWER_HEADERS), 200
    )
    assert withdrawn_after["verification_status"] == "RECANTED"
    assert withdrawn_after["credited_months"] == 0
    assert withdrawn_after["raw_months"] == 24

    application_after = validate_success(
        api.get_application(application["id"], BOARD_REVIEWER_HEADERS), 200
    )
    assert application_after["verified_experience_months"] == 48
    assert application_after["status"] == "UNDER_REVIEW"

    records, meta = validate_paginated(
        api.list_experience_records(
            BOARD_REVIEWER_HEADERS, {"application_id": application["id"]}
        )
    )
    assert meta["total_count"] == 2
    verified_sum = sum(
        row["credited_months"]
        for row in records
        if row["verification_status"] == "VERIFIED"
    )
    assert verified_sum == application_after["verified_experience_months"]
