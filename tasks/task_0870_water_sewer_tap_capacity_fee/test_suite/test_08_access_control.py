"""Authentication, RBAC authorization, and separation-of-duties (PRD §2.1, §2.9)."""
import pytest
from test_helpers import (
    validate_error, ApiErrorId,
    application_under_review, application_with_availability,
    create_meter_size_schedule_payload,
    make_applicant_headers, make_reviewer_headers,
)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying
    the acting user, and `X-User-Role`, declaring the capacity in which they act. If either
    header is missing, or if `X-User-Role` is not one of the recognized roles, the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/missing_auth_headers_rejected
    """
    res = api.list_applications(headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_applicant_cannot_approve(api):
    """PRD §2.1: "If the headers are well-formed but the acting role is not permitted to invoke
    the requested operation under the access matrix, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/applicant_cannot_approve
    """
    app = application_under_review(parcel_id="APN-AU", meter_size="ONE")
    res = api.approve_application(app["id"], make_applicant_headers("appl-1"))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


def test_same_reviewer_cannot_approve(api):
    """PRD §2.9: "The reviewer who recorded the availability determination for an application —
    captured as `availability_reviewer_id` — may not be the same reviewer who approves that
    application. If the approving reviewer's `X-User-ID` equals the stored
    `availability_reviewer_id`, the approval is rejected with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403)."

    Design: Corner/rbac/sod_same_reviewer_cannot_approve
    """
    app, _ = application_with_availability(distance_to_main_ft=120,
                                           availability_reviewer_id="rev-1",
                                           parcel_id="APN-SD", service_type="WATER",
                                           meter_size="ONE")
    res = api.approve_application(app["id"], make_reviewer_headers("rev-1"))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=403)


def test_reviewer_cannot_create_meter_schedule(api):
    """PRD §3.1: "All of these configuration collections are readable by the operational roles,
    while creation of schedules, rate cards, inspectors, and crews is reserved to the
    `UtilityAdmin`."

    Design: Corner/rbac/reviewer_cannot_create_meter_schedule
    """
    res = api.create_meter_size_schedule(
        create_meter_size_schedule_payload(meter_size="TWO", eru_factor=8.0,
                                            tap_install_fee_cents=700000),
        make_reviewer_headers("rev-1"))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)
