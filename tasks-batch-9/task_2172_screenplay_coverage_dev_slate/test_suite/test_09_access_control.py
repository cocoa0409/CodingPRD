"""Authentication, role authorisation, resource ownership and the not-found family."""

import pytest

from test_helpers import (
    ADMIN,
    EDITOR_ASSIGN,
    ApiErrorId,
    board_entries_for_property,
    create_reader,
    fetch_reader,
    fetch_report,
    fetch_submission,
    fill_report,
    make_reader_headers,
    set_clock,
    setup_assigned_coverage,
    setup_submitted_coverage,
    validate_error,
    validate_paginated,
    validate_success,
)

NOT_FOUND_SWEEP = [
    ("submissions", "00000000-0000-4000-8000-000000000001",
     ApiErrorId.ERR_SUBMISSION_NOT_FOUND),
    ("release-forms", "00000000-0000-4000-8000-000000000002",
     ApiErrorId.ERR_RELEASE_FORM_NOT_FOUND),
    ("rights-chain-documents", "00000000-0000-4000-8000-000000000003",
     ApiErrorId.ERR_DOCUMENT_NOT_FOUND),
    ("readers", "00000000-0000-4000-8000-000000000004",
     ApiErrorId.ERR_READER_NOT_FOUND),
    ("coverage-assignments", "00000000-0000-4000-8000-000000000005",
     ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
    ("coverage-reports", "00000000-0000-4000-8000-000000000006",
     ApiErrorId.ERR_REPORT_NOT_FOUND),
    ("tracking-board-entries", "00000000-0000-4000-8000-000000000007",
     ApiErrorId.ERR_BOARD_ENTRY_NOT_FOUND),
    ("option-agreements", "00000000-0000-4000-8000-000000000008",
     ApiErrorId.ERR_OPTION_NOT_FOUND),
    ("development-projects", "00000000-0000-4000-8000-000000000009",
     ApiErrorId.ERR_PROJECT_NOT_FOUND),
    ("writers", "00000000-0000-4000-8000-00000000000a",
     ApiErrorId.ERR_WRITER_NOT_FOUND),
    ("writer-engagements", "00000000-0000-4000-8000-00000000000b",
     ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND),
    ("milestone-payments", "00000000-0000-4000-8000-00000000000c",
     ApiErrorId.ERR_MILESTONE_NOT_FOUND),
    ("greenlight-reviews", "00000000-0000-4000-8000-00000000000d",
     ApiErrorId.ERR_REVIEW_NOT_FOUND),
    ("committee-members", "00000000-0000-4000-8000-00000000000e",
     ApiErrorId.ERR_MEMBER_NOT_FOUND),
]


@pytest.mark.parametrize(
    "collection,resource_id,expected_error",
    NOT_FOUND_SWEEP,
    ids=[row[0] for row in NOT_FOUND_SWEEP],
)
def test_each_resource_family_returns_its_own_not_found_code(
    api, collection, resource_id, expected_error
):
    """PRD 2.6: "Every resource id embedded in the URL is resolved left to right, and
    the first unresolvable segment decides the error: `ERR_PROPERTY_NOT_FOUND`,
    `ERR_SUBMISSION_NOT_FOUND`, `ERR_RELEASE_FORM_NOT_FOUND`, `ERR_READER_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_BOARD_ENTRY_NOT_FOUND`,
    `ERR_OPTION_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_WRITER_NOT_FOUND`,
    `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`,
    `ERR_MEMBER_NOT_FOUND` or `ERR_DOCUMENT_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/not_found_family_sweep_across_every_single_resource_read
    """
    resp = api._request("GET", f"/{collection}/{resource_id}", headers=ADMIN)
    validate_error(resp, expected_error, 404)
    assert resp.json()["response_type"] == "error"


def test_missing_auth_headers_return_unauthenticated(api):
    """PRD 2.1: "Every request to the service must carry two headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, naming the capacity in which
    that principal is acting. If either header is absent, is present but empty, or if
    `X-User-Role` does not name one of the eight roles below, the request is rejected
    with `ERR_UNAUTHENTICATED` and HTTP 401."

    Design: Corner/errors/missing_x_user_headers_returns_unauthenticated
    """
    resp = api._request(
        "POST",
        "/literary-properties",
        {
            "title": "Anonymous",
            "material_type": "SPEC_SCRIPT",
            "source_author_name": "Nobody",
            "genre": "DRAMA",
        },
        headers={},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    _, meta = validate_paginated(api.list_literary_properties(ADMIN))
    assert meta["total_count"] == 0, "an unauthenticated write persists nothing"


def test_slate_admin_cannot_approve_coverage(api):
    """PRD 2.1: "If both headers are well-formed but the named role is not among the
    roles authorised for the endpoint being called (see the Authorized Role(s) column
    in Section 4), the request is rejected with `ERR_FORBIDDEN_ROLE` and HTTP 403."

    Design: Corner/rbac/slate_admin_cannot_approve_coverage_forbidden_role
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_submitted_coverage(
        genre="DRAMA",
        title="Wrong Desk",
        scores=(8, 7, 9, 6, 8),
        recommendation="RECOMMEND",
        synopsis_word_count=400,
    )

    resp = api.approve_coverage_report(ctx["report"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    stored = fetch_report(ctx["report"]["id"])
    assert stored["status"] == "SUBMITTED"
    assert stored["approved_by_user_id"] is None
    assert fetch_submission(ctx["submission"]["id"])["status"] == "COVERAGE_IN_REVIEW"
    assert fetch_reader(ctx["reader"]["id"])["active_assignment_count"] == 1


def test_reader_cannot_submit_another_readers_report(api):
    """PRD 2.1: "An entity-backed role that acts on a resource belonging to a
    different principal — a reader starting, editing or submitting coverage for
    another reader's assignment, a writer delivering against another writer's
    engagement, or a committee member attempting to vote in someone else's name — is
    rejected with `ERR_NOT_RESOURCE_OWNER` and HTTP 403."
    PRD 2.1: "This ownership check guards exactly five operations: starting a coverage
    assignment, patching a coverage report body, submitting a coverage report,
    delivering against a writer engagement, and casting a ballot on a greenlight
    review."

    Design: Corner/rbac/reader_cannot_submit_another_readers_report_not_resource_owner
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_assigned_coverage(genre="DRAMA", title="Not Your Script")
    intruder = create_reader(
        display_name="R2 Intruder", specialty_genre="DRAMA", weekly_capacity=2
    )
    fill_report(
        ctx["report"]["id"], ctx["reader"]["id"],
        logline_score=8, structure_score=7, character_score=9,
        dialogue_score=6, marketability_score=8,
        recommendation="RECOMMEND", synopsis_word_count=400,
    )

    resp = api.submit_coverage_report(
        ctx["report"]["id"], make_reader_headers(intruder["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

    stored = fetch_report(ctx["report"]["id"])
    assert stored["status"] == "DRAFT"
    assert stored["composite_score"] is None
    assert validate_success(
        api.get_coverage_assignment(ctx["assignment"]["id"], EDITOR_ASSIGN)
    )["status"] == "ASSIGNED"
    assert fetch_reader(intruder["id"])["active_assignment_count"] == 0


def test_coverage_approver_cannot_be_the_assigning_editor(api):
    """PRD 2.9: "The approving story editor's `X-User-ID` must differ from the
    `assigned_by_user_id` recorded on the coverage assignment the report answers."
    PRD 3.3: "On success the system creates a coverage assignment in `ASSIGNED` status
    carrying the `submission_id`, the resolved `reader_id`, the two window bounds, and
    `assigned_by_user_id` set to the acting editor's `X-User-ID`."

    Design: Corner/rbac/coverage_approver_cannot_be_the_assigning_editor
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_submitted_coverage(
        genre="DRAMA",
        title="Four Eyes",
        scores=(8, 7, 9, 6, 8),
        recommendation="RECOMMEND",
        synopsis_word_count=400,
    )

    resp = api.approve_coverage_report(ctx["report"]["id"], EDITOR_ASSIGN)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    assert validate_success(
        api.get_coverage_assignment(ctx["assignment"]["id"], EDITOR_ASSIGN)
    )["assigned_by_user_id"] == "editor-assign-1"
    assert fetch_report(ctx["report"]["id"])["status"] == "SUBMITTED"
    assert fetch_submission(ctx["submission"]["id"])["status"] == "COVERAGE_IN_REVIEW"
    assert board_entries_for_property(ctx["property"]["id"]) == []

    from test_helpers import EDITOR_APPROVE

    second = validate_success(
        api.approve_coverage_report(ctx["report"]["id"], EDITOR_APPROVE), 200
    )
    assert second["status"] == "APPROVED", (
        "a different story editor may approve the same report"
    )
