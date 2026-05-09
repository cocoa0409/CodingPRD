"""Application creation, submission, and the per-program-per-applicant uniqueness rule.

Covers PRD §2.1 (Applicant ownership identity), §3.2 (intake, family_size,
requires_accessibility, submit), and §2.9 (duplicate active application).
"""

import pytest

from test_helpers import (
    api_client as api,
    assert_application,
    create_application_in_draft,
    create_application_payload,
    create_program,
    fresh_applicant_id,
    make_applicant_headers,
    make_household_member,
    validate_error,
    validate_success,
)


def test_create_application_records_applicant_user_id_from_header():
    """PRD §2.1: "ownership is recorded by writing X-User-ID into applicant_user_id at
    application creation"."""
    program = create_program()
    applicant_id = fresh_applicant_id()
    headers = make_applicant_headers(applicant_id)
    payload = create_application_payload()
    res = api.create_application(program["id"], payload, headers)
    application = validate_success(res, expected_status=201)
    assert_application(application)
    assert application["applicant_user_id"] == applicant_id
    assert application["status"] == "DRAFT"


def test_create_application_computes_family_size_and_accessibility():
    """PRD §3.2: "computes family_size as the length of household_members, computes
    requires_accessibility as true if and only if at least one member has has_disability
    true".
    """
    program = create_program()
    members = [
        make_household_member(relation="SELF", has_disability=False),
        make_household_member(relation="SPOUSE", has_disability=True),
        make_household_member(relation="CHILD", has_disability=False),
    ]
    application, _ = create_application_in_draft(program["id"], household_members=members)
    assert application["family_size"] == 3
    assert application["requires_accessibility"] is True


def test_requires_accessibility_false_when_no_member_has_disability():
    """PRD §3.2: "computes requires_accessibility as true if and only if at least one
    member has has_disability true"."""
    program = create_program()
    members = [
        make_household_member(has_disability=False),
        make_household_member(has_disability=False),
    ]
    application, _ = create_application_in_draft(program["id"], household_members=members)
    assert application["requires_accessibility"] is False


def test_create_application_initial_queue_score_is_null():
    """PRD §3.3: "While the application is in DRAFT or UNDER_REVIEW, queue_score is null"."""
    program = create_program()
    application, _ = create_application_in_draft(program["id"])
    assert application.get("queue_score") in (None, 0) or application["queue_score"] is None
    # PRD says null specifically for DRAFT and UNDER_REVIEW.
    assert application["queue_score"] is None


def test_only_applicant_role_can_create_application():
    """PRD §4: "POST /housing-programs/{programId}/applications" is Applicant-only.
    PRD §2.1: "A request whose role is recognized but is not authorized for the requested
    operation is rejected with ERR_INSUFFICIENT_PERMISSIONS at HTTP 403".
    """
    program = create_program()
    res = api.create_application(
        program["id"],
        create_application_payload(),
        {"X-User-ID": "officer-x", "X-User-Role": "HousingOfficer"},
    )
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


def test_submit_transitions_draft_to_under_review():
    """PRD §3.2: "The applicant submits the draft, transitioning the application from
    DRAFT to UNDER_REVIEW".
    """
    program = create_program()
    application, applicant_id = create_application_in_draft(program["id"])
    res = api.submit_application(program["id"], application["id"], make_applicant_headers(applicant_id))
    updated = validate_success(res)
    assert updated["status"] == "UNDER_REVIEW"


def test_submit_application_not_in_draft_rejected():
    """PRD §3.2: "if the application is not in DRAFT the submit is rejected with
    ERR_APPLICATION_NOT_IN_DRAFT".
    """
    program = create_program()
    application, applicant_id = create_application_in_draft(program["id"])
    headers = make_applicant_headers(applicant_id)
    validate_success(api.submit_application(program["id"], application["id"], headers))
    res = api.submit_application(program["id"], application["id"], headers)
    validate_error(res, "ERR_APPLICATION_NOT_IN_DRAFT")


def test_submit_with_empty_household_members_invalid_request():
    """PRD §3.2: "if household_members is empty the submit is rejected with
    ERR_INVALID_REQUEST".
    """
    program = create_program()
    applicant_id = fresh_applicant_id()
    payload = create_application_payload(household_members=[])
    res = api.create_application(program["id"], payload, make_applicant_headers(applicant_id))
    # The check might fire at creation or at submit; PRD requires ERR_INVALID_REQUEST at
    # submit specifically. If creation rejects with the same code that's also valid;
    # however PRD prose names submit as the failing point.
    if res.status_code >= 400:
        validate_error(res, "ERR_INVALID_REQUEST")
    else:
        application = validate_success(res, expected_status=201)
        sres = api.submit_application(
            program["id"], application["id"], make_applicant_headers(applicant_id)
        )
        validate_error(sres, "ERR_INVALID_REQUEST")


def test_duplicate_active_application_per_applicant_rejected():
    """PRD §2.1: "A given X-User-ID acting as Applicant may own at most one Application
    per program in any non-terminal status — the second such submission is rejected with
    ERR_DUPLICATE_ACTIVE_APPLICATION".
    """
    program = create_program()
    applicant_id = fresh_applicant_id()
    headers = make_applicant_headers(applicant_id)
    validate_success(
        api.create_application(program["id"], create_application_payload(), headers),
        expected_status=201,
    )
    res = api.create_application(program["id"], create_application_payload(), headers)
    validate_error(res, "ERR_DUPLICATE_ACTIVE_APPLICATION")


def test_get_nonexistent_application_returns_application_not_found():
    """PRD §2.8: "ERR_APPLICATION_NOT_FOUND ... returned for the first missing segment"."""
    program = create_program()
    res = api.get_application(
        program["id"],
        "00000000-0000-0000-0000-000000000000",
        {"X-User-ID": "officer-x", "X-User-Role": "HousingOfficer"},
    )
    validate_error(res, "ERR_APPLICATION_NOT_FOUND")
