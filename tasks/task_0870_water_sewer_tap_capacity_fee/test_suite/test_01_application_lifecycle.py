"""Connection-application intake, defaults, invalid transitions, revision loop, listing."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId, assert_application,
    create_application_payload,
    create_application, application_under_review, ensure_meter_schedule,
    submit_application, start_review, record_availability, approve_now,
    make_reviewer_headers, make_applicant_headers,
)


def test_create_application_minimal_returns_draft(api, applicant_headers):
    """PRD §3.2: "An `Applicant` opens the process by creating a **connection application**,
    which begins in `DRAFT`." PRD §3.2: "The server stamps `applicant_user_id` from the
    caller's `X-User-ID`; the applicant does not supply it."

    Design: Corner/entities/create_application_minimal_returns_201
    """
    res = api.create_application(
        create_application_payload(parcel_id="APN-1", service_type="WATER",
                                   meter_size="ONE", use_type="RESIDENTIAL"),
        applicant_headers)
    app = validate_success(res, 201)
    assert_application(app)
    assert app["status"] == "DRAFT"
    assert app["applicant_user_id"] == "appl-1"
    assert app["version"] == 1


def test_create_application_missing_service_type_rejected(api, applicant_headers):
    """PRD §2.10: "A generic body-shape check (`ERR_VALIDATION`, HTTP 400), which confirms
    that required fields are present and that enum and numeric values are well-formed, is
    the lowest-precedence guard and is applied last."

    Design: Corner/entities/create_application_missing_service_type_rejected
    """
    payload = create_application_payload(parcel_id="APN-1", meter_size="ONE",
                                         use_type="RESIDENTIAL")
    del payload["service_type"]
    res = api.create_application(payload, applicant_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION.value, expected_status=400)


def test_get_application_not_found(api, reviewer_headers):
    """PRD §2.8: "a path id that does not resolve to an existing resource yields
    `ERR_NOT_FOUND` (HTTP 404), evaluated left to right so that the first unresolved
    identifier in the path is the one reported."

    Design: Corner/entities/get_application_not_found
    """
    res = api.get_application(NON_EXISTENT_UUID, reviewer_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_application_defaults_applied(api, applicant_headers):
    """PRD §3.2: "Two optional flags shape the eventual fee: `requires_pavement_cut`
    (defaulting to false) records whether the tap will cut pavement, and the pair
    `prior_credit_eru` (defaulting to 0, and at least zero) and `assessment_basis`
    (defaulting to `NEW`, otherwise `REDEVELOPMENT`) control the redevelopment credit
    described in §3.4."

    Design: Corner/entities/application_defaults_applied
    """
    res = api.create_application(
        create_application_payload(parcel_id="APN-2", service_type="WATER",
                                   meter_size="ONE", use_type="RESIDENTIAL"),
        applicant_headers)
    app = validate_success(res, 201)
    assert app["requires_pavement_cut"] is False
    assert app["assessment_basis"] == "NEW"
    assert app["prior_credit_eru"] == 0


def test_invalid_enum_service_type_rejected(api, applicant_headers):
    """PRD §2.10: "A generic body-shape check (`ERR_VALIDATION`, HTTP 400), which confirms
    that required fields are present and that enum and numeric values are well-formed, is
    the lowest-precedence guard and is applied last."

    Design: Corner/entities/invalid_enum_service_type_rejected
    """
    res = api.create_application(
        create_application_payload(parcel_id="APN-3", service_type="GAS",
                                   meter_size="ONE", use_type="RESIDENTIAL"),
        applicant_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION.value, expected_status=400)


def test_approve_from_draft_invalid_state(api, applicant_headers):
    """PRD §3.4: "The application must be `UNDER_REVIEW`, or the transition is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/approve_from_draft_invalid_state
    """
    ensure_meter_schedule()
    app = create_application(parcel_id="APN-D1")
    res = api.approve_application(app["id"], make_reviewer_headers("rev-2"))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_withdraw_from_denied_is_invalid_state(api):
    """PRD §3.2: "they may deny it, transitioning `UNDER_REVIEW → DENIED` (again optionally
    with a `reason`), a terminal outcome". PRD §3.2: "the withdraw action is allowed from
    `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED`, or `APPROVED`, and drives the
    application to the terminal `WITHDRAWN` state."

    Design: Corner/state_machines/withdraw_from_denied_terminal_invalid
    """
    ensure_meter_schedule()
    app = create_application(parcel_id="APN-DN")
    submit_application(app["id"])
    start_review(app["id"], "rev-1")
    api.deny_application(app["id"], make_reviewer_headers("rev-1"), {"reason": "out of area"})
    res = api.withdraw_application(app["id"], make_applicant_headers("appl-1"))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_list_applications_pagination_envelope(api, applicant_headers, reviewer_headers):
    """PRD §2.3: "Every list response echoes `limit`, `offset`, `total_count`, and `has_more`
    inside the `meta` object."

    Design: Corner/endpoints/list_applications_pagination_envelope
    """
    api.create_application(create_application_payload(parcel_id="APN-L1"), applicant_headers)
    api.create_application(create_application_payload(parcel_id="APN-L2"), applicant_headers)
    data, meta = validate_paginated(api.list_applications(reviewer_headers,
                                                          params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


class TestApplicationRevisionCycle:
    """The connection application is cyclic: UNDER_REVIEW -> REVISION_REQUESTED -> SUBMITTED
    -> UNDER_REVIEW returns to a previously-visited state."""

    def test_request_revision_then_resubmit(self, api):
        """PRD §3.2: "They may send it back, transitioning `UNDER_REVIEW → REVISION_REQUESTED`
        (optionally attaching a `reason`)". PRD §3.2: "an application sitting in
        `REVISION_REQUESTED` returns to `SUBMITTED` through the same transition, so an
        applicant may cycle through corrections as many times as review demands."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle
        """
        app = application_under_review(parcel_id="APN-R", meter_size="ONE")
        revised = validate_success(
            api.request_revision(app["id"], make_reviewer_headers("rev-1"),
                                 {"reason": "need site plan"}), 200)
        assert revised["status"] == "REVISION_REQUESTED"
        resubmitted = validate_success(
            api.submit_application(app["id"], make_applicant_headers("appl-1")), 200)
        assert resubmitted["status"] == "SUBMITTED"

    def test_second_start_review_revisits_under_review(self, api):
        """PRD §3.2: "A `UtilityReviewer` picks up a `SUBMITTED` application and begins review,
        moving it to `UNDER_REVIEW`." PRD §3.2: "an application sitting in `REVISION_REQUESTED`
        returns to `SUBMITTED` through the same transition, so an applicant may cycle through
        corrections as many times as review demands."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle
        """
        app = application_under_review(parcel_id="APN-R2", meter_size="ONE")
        api.request_revision(app["id"], make_reviewer_headers("rev-1"))
        api.submit_application(app["id"], make_applicant_headers("appl-1"))
        reviewed = validate_success(
            api.start_review(app["id"], make_reviewer_headers("rev-1")), 200)
        assert reviewed["status"] == "UNDER_REVIEW"
