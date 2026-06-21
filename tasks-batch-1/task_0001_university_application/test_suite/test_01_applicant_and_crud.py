"""Applicant creation, CRUD, listing, profile lock.

Covers Corner-design entities + state_machines (initial state / lockdown) +
validations (profile lock).
"""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_applicant,
    create_applicant_payload,
    make_applicant_headers,
    set_clock,
    setup_submitted_application,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_create_applicant_with_all_required_fields_returns_201(api):
    """PRD §3.1: "On creation the new Applicant is in profile_status DRAFT and
    the submitted_application_count is 0."
    PRD §2.4: "version is an integer that starts at 1 at creation".

    Design: Corner/entities/applicant_create_with_all_required_fields_returns_201
    """
    payload = create_applicant_payload(
        email="creation@u.edu", full_name="Cre Ation",
        gpa_unweighted=3.50, sat_total=1300, residency="IN_STATE",
    )
    res = api.create_applicant(payload)
    data = validate_success(res, expected_status=201)
    assert_applicant(data)
    assert data["profile_status"] == "DRAFT"
    assert data["submitted_application_count"] == 0
    assert data["version"] == 1
    assert data["email"] == "creation@u.edu"


def test_create_applicant_missing_required_email_returns_400(api):
    """PRD §2.6: "generic input validation (ERR_INVALID_REQUEST) for missing
    required fields, type mismatches, and out-of-bounds numerics."

    Design: Corner/entities/applicant_create_missing_required_email_returns_400
    """
    payload = {
        "full_name": "No Email",
        "gpa_unweighted": 3.50,
        "residency": "IN_STATE",
    }
    res = api.create_applicant(payload)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_applicant_invalid_gpa_above_max_returns_400(api):
    """PRD §3.1: "an unweighted GPA on the 4.00 scale carried in gpa_unweighted
    (two decimals, between 0.00 and 4.00 inclusive)".
    PRD §2.6: "generic input validation (ERR_INVALID_REQUEST) for missing
    required fields, type mismatches, and out-of-bounds numerics."

    Design: Corner/entities/applicant_create_invalid_gpa_above_max_returns_400
    """
    payload = create_applicant_payload(
        email="bad_gpa@u.edu", full_name="Bad GPA",
        gpa_unweighted=4.50, sat_total=None, residency="IN_STATE",
    )
    payload.pop("sat_total", None)
    res = api.create_applicant(payload)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_applicant_invalid_sat_below_min_returns_400(api):
    """PRD §3.1: "an optional sat_total (an integer between 400 and 1600
    inclusive, or null when the student is applying test-optional)".
    PRD §2.6: "generic input validation (ERR_INVALID_REQUEST) for missing
    required fields, type mismatches, and out-of-bounds numerics."

    Design: Corner/entities/applicant_create_invalid_sat_below_min_returns_400
    """
    payload = create_applicant_payload(
        email="bad_sat@u.edu", full_name="Bad SAT",
        gpa_unweighted=3.0, sat_total=300, residency="IN_STATE",
    )
    res = api.create_applicant(payload)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_get_applicant_non_existent_returns_404(api, platform_admin_headers):
    """PRD §2.5: "Whenever a path contains an {id} segment, the server first
    verifies that the referenced row exists; if not, the request is rejected
    with ERR_NOT_FOUND before any body validation runs."

    Design: Corner/entities/get_applicant_non_existent_returns_404
    """
    res = api.get_applicant(NON_EXISTENT_UUID, platform_admin_headers)
    validate_error(res, "ERR_NOT_FOUND")


def test_applicant_listing_returns_pagination_envelope(api, platform_admin_headers):
    """PRD §2.3: "Every list endpoint accepts two optional query parameters:
    limit and offset. limit defaults to 10, has a minimum of 1, and a maximum
    of 100; values outside that range are rejected as malformed input."
    PRD §2.3: "The response meta block for list endpoints carries limit,
    offset, total_count, and has_more so the client can drive pagination
    without state."

    Design: Corner/entities/applicant_listing_returns_pagination_envelope
    """
    api.create_applicant(create_applicant_payload(
        email="p1@u.edu", full_name="P 1", gpa_unweighted=3.0, residency="IN_STATE",
    ))
    api.create_applicant(create_applicant_payload(
        email="p2@u.edu", full_name="P 2", gpa_unweighted=3.1, residency="IN_STATE",
    ))
    api.create_applicant(create_applicant_payload(
        email="p3@u.edu", full_name="P 3", gpa_unweighted=3.2, residency="OUT_OF_STATE",
    ))
    res = api.list_applicants(platform_admin_headers, params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert len(data) == 2


def test_applicant_id_and_timestamps_are_server_generated(api):
    """PRD §2.4: "The id is a server-minted UUID with no type prefix; clients
    never construct ids. created_at is set when the row is inserted and never
    changes; updated_at is refreshed on every mutation."
    PRD §2.4: "version is an integer that starts at 1 at creation".

    Design: Corner/entities/applicant_id_and_timestamps_are_server_generated
    """
    payload = create_applicant_payload(
        email="sys@u.edu", full_name="Sys Fields",
        gpa_unweighted=3.0, sat_total=None, residency="IN_STATE",
    )
    payload.pop("sat_total", None)
    data = validate_success(api.create_applicant(payload), expected_status=201)
    # assert_applicant validates UUID + ISO8601 created_at + version >= 1
    assert_applicant(data)
    assert data["version"] == 1


# ─── State machine: initial state + locked profile + terminal lockdown ───

def test_application_create_initial_state_is_draft(api):
    """PRD §3.3: "the server creates the row with status set to DRAFT, a fresh
    UUID id, version of 1, and submitted_at, decision_at, enrollment_decision_at,
    composite_score, and admission_track_snapshot all unset."

    Design: Corner/state_machines/application_create_initial_state_is_draft
    """
    school = validate_success(
        api.create_school(
            {
                "name": "U Init", "state_code": "WI", "admission_track": "REGULAR",
                "deadline_iso": "2026-12-01T00:00:00Z",
                "decision_release_iso": "2027-03-15T00:00:00Z",
                "target_class_size": 100, "assumed_yield_rate": 0.50,
                "in_state_tuition_cents": 5000000,
                "out_of_state_tuition_cents": 9000000,
                "international_tuition_cents": 12000000,
            },
            TEST_USERS["platform_admin_headers"],
        ),
        expected_status=201,
    )
    applicant = validate_success(
        api.create_applicant(create_applicant_payload(
            email="init@u.edu", full_name="Init A",
            gpa_unweighted=3.50, residency="IN_STATE",
        )),
        expected_status=201,
    )
    app = validate_success(
        api.create_application(
            {"applicant_id": applicant["id"], "school_id": school["id"]},
            make_applicant_headers(applicant["id"]),
        ),
        expected_status=201,
    )
    assert app["status"] == "DRAFT"
    assert app["version"] == 1
    assert app.get("submitted_at") is None


def test_application_submit_from_already_submitted_returns_invalid_state(api):
    """PRD §2.6: "then state-machine eligibility (ERR_INVALID_STATE)".
    PRD §3.5: "When the bundle is ready, the applicant submits — driving the
    application from DRAFT to SUBMITTED."

    Design: Corner/state_machines/application_submit_from_already_submitted_returns_invalid_state
    """
    set_clock("2026-09-01T00:00:00Z")
    applicant, school, submitted = setup_submitted_application(
        submit_clock_iso="2026-09-15T00:00:00Z",
        email_suffix="inv_sm",
    )
    res = api.submit_application(
        submitted["id"], make_applicant_headers(applicant["id"])
    )
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(
        api.get_application(submitted["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert after["status"] == "SUBMITTED"


def test_application_admit_from_draft_returns_invalid_state(api):
    """PRD §3.6: "An application sitting in SUBMITTED enters the admissions
    office's queue. An AdmissionsOfficer whose school assignment matches the
    application's school_id begins review, transitioning the application from
    SUBMITTED to UNDER_REVIEW."
    PRD §3.6: "From UNDER_REVIEW an officer drives one of three decisions:
    admit, waitlist, or deny."

    Design: Corner/state_machines/application_admit_from_draft_returns_invalid_state
    """
    school = validate_success(
        api.create_school(
            {
                "name": "U Admit D", "state_code": "TN", "admission_track": "REGULAR",
                "deadline_iso": "2026-12-01T00:00:00Z",
                "decision_release_iso": "2027-03-15T00:00:00Z",
                "target_class_size": 100, "assumed_yield_rate": 0.50,
                "in_state_tuition_cents": 5000000,
                "out_of_state_tuition_cents": 9000000,
                "international_tuition_cents": 12000000,
            },
            TEST_USERS["platform_admin_headers"],
        ),
        expected_status=201,
    )
    applicant = validate_success(
        api.create_applicant(create_applicant_payload(
            email="ad@u.edu", full_name="Ad D",
            gpa_unweighted=3.50, residency="IN_STATE",
        )),
        expected_status=201,
    )
    draft = validate_success(
        api.create_application(
            {"applicant_id": applicant["id"], "school_id": school["id"]},
            make_applicant_headers(applicant["id"]),
        ),
        expected_status=201,
    )
    res = api.admit_application(
        draft["id"], draft["version"], TEST_USERS["admissions_headers"],
    )
    validate_error(res, "ERR_INVALID_STATE")


def test_application_terminal_state_denied_lockdown(api):
    """PRD §3.9: "Withdrawing is the applicant's escape hatch before any
    decision has been issued. It is allowed only from DRAFT or SUBMITTED
    (not from UNDER_REVIEW or later — once the officer has begun review, the
    only paths out are admit, waitlist, or deny)."
    PRD §2.6: "then state-machine eligibility (ERR_INVALID_STATE)".

    Design: Corner/state_machines/application_terminal_state_denied_lockdown
    """
    set_clock("2026-09-01T00:00:00Z")
    # Drive Application to DENIED
    from test_helpers import setup_under_review_application

    applicant, school, ur = setup_under_review_application(
        email_suffix="term",
    )
    denied = validate_success(
        api.deny_application(ur["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert denied["status"] == "DENIED"
    # Now any further trigger is rejected
    res = api.withdraw_application(
        denied["id"], make_applicant_headers(applicant["id"])
    )
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(
        api.get_application(denied["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert after["status"] == "DENIED"


def test_profile_locked_after_first_submit_blocks_gpa_update(api):
    """PRD §3.1: "The moment they submit their first application, however, the
    profile is auto-promoted to LOCKED — and from that point forward, attempts
    to mutate gpa_unweighted, sat_total, or residency are rejected with
    ERR_PROFILE_LOCKED."

    Design: Corner/validations/profile_locked_after_first_submit_blocks_gpa_update
    """
    set_clock("2026-09-01T00:00:00Z")
    applicant, _, submitted = setup_submitted_application(email_suffix="lk")
    res = api.update_applicant(
        applicant["id"],
        {"gpa_unweighted": 4.00},
        make_applicant_headers(applicant["id"]),
    )
    validate_error(res, "ERR_PROFILE_LOCKED")
    after = validate_success(
        api.get_applicant(applicant["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert after["profile_status"] == "LOCKED"
    assert float(after["gpa_unweighted"]) == pytest.approx(3.50, abs=0.001)
