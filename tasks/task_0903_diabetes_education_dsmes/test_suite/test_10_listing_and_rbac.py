"""Filtered/paginated listing and role-based access denials.

Queue B (Corner): endpoints (session list pagination), rbac (role denials).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId, TEST_USERS,
    setup_active_enrollment, create_referral_payload, make_dietitian_headers,
)
import test_helpers as th

COORD = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_headers"]


def test_sessions_filtered_list_pagination(api):
    """PRD §2.3: "Each paginated response reports `limit`, `offset`, `total_count`
    (the total number of matching records across all pages), and `has_more` (true
    when records remain beyond the current page) inside `meta`."

    Two sessions filtered by enrollment_id with limit=1 report total_count 2 and
    has_more true.

    Design: Corner/endpoints/ep_sessions_filtered_list_pagination
    """
    ctx = setup_active_enrollment(api)
    th.schedule_individual_session_ok(api, ctx, "2026-05-28T09:00:00Z", "2026-05-28T09:30:00Z")
    th.schedule_individual_session_ok(api, ctx, "2026-05-28T10:00:00Z", "2026-05-28T10:30:00Z")
    resp = api.list_sessions(COORD, params={"enrollment_id": ctx["enrollment_id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"total_count must be 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"has_more must be True, got {meta['has_more']}"
    assert len(data) == 1, f"limit=1 must return one row, got {len(data)}"


def test_dietitian_cannot_adjudicate(api):
    """PRD §2.1: "If the headers are present and valid but the role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "A specialist adjudicates submitted DSMT claims and otherwise has
    read access to all resources for reconciliation."

    Adjudication is a BillingSpecialist operation; a Dietitian calling it is
    denied.

    Design: Corner/rbac/rbac_dietitian_cannot_adjudicate
    """
    ctx = setup_active_enrollment(api)
    sess = th.schedule_individual_session_ok(api, ctx, "2026-05-31T09:00:00Z", "2026-05-31T10:00:00Z")
    th.complete(api, ctx, sess["id"], 60)
    resp = api.adjudicate_session(sess["id"], {"billing_decision": "PAID"}, ctx["diet"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_dietitian_cannot_create_referral(api):
    """PRD §2.1: "If the headers are present and valid but the role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "Coordinators create programs, curricula, patients, dietitians,
    referrals, enrollments, group classes, and device enrollments".

    Referral creation is a ProgramCoordinator operation; a Dietitian calling it
    is denied.

    Design: Corner/rbac/rbac_dietitian_cannot_create_referral
    """
    ctx = setup_active_enrollment(api, assess=False, create_enrollment=False)
    resp = api.create_referral(
        create_referral_payload(ctx["program_id"], ctx["patient_id"]),
        make_dietitian_headers(ctx["dietitian_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
