"""RBAC denials, segregation of duties, initial states, system-stamped fields,
audit log retrieval, listing/pagination, priority-conflict pairs."""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_DEFAULT,
    TEST_USERS,
    create_approved_content,
    create_assignment,
    create_content_payload,
    create_instructor_led_setup,
    create_rep,
    create_session_for_content,
    get_success_data,
    make_admin_headers,
    make_officer_headers,
    make_rep_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]


class TestRbacDenials:
    def test_rep_cannot_create_content(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        targeted endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST /contents is authorized for TrainingAdmin only.

        Design: Corner/rbac/c_rep_cannot_create_content_returns_403
        """
        rep = create_rep(crd_number="CRD-C33")
        resp = api.create_content(
            create_content_payload(code="RBAC-1"), make_rep_headers(rep["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_training_admin_cannot_approve(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        targeted endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §3.2: "Approval belongs to a `ComplianceOfficer` and requires the
        content to be in `PENDING_APPROVAL`."

        Design: Corner/rbac/c_training_admin_cannot_approve_returns_403
        """
        author = make_admin_headers("ta-1")
        other_admin = make_admin_headers("ta-9")
        content = get_success_data(
            api.create_content(create_content_payload(code="RBAC-2"), author))
        get_success_data(api.submit_content(content["id"], author))

        resp = api.approve_content(content["id"], other_admin)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        data = validate_success(api.get_content(content["id"], OFFICER))
        assert data["content_status"] == "PENDING_APPROVAL", (
            f"role-denied approval must leave the content PENDING_APPROVAL, "
            f"got {data['content_status']}")

    def test_auditor_cannot_run_sweep(self, api, auditor_headers):
        """PRD §2.1: "When `X-User-Role` is `Auditor`, `X-User-ID` is an opaque
        read-only identifier with no write privileges anywhere in the system."
        PRD §3.9: "The enforcement sweep is a `ComplianceOfficer`-only
        operation."

        Design: Corner/rbac/c_auditor_cannot_run_sweep_returns_403
        """
        get_success_data(
            api.create_content(create_content_payload(code="RBAC-3"), ADMIN))
        # Auditor read path works.
        data, _meta = validate_paginated(api.list_contents(auditor_headers))
        assert len(data) == 1

        resp = api.run_enforcement_sweep(auditor_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestMissingAuthHeaders:
    def test_missing_headers_returns_400(self, api):
        """PRD §2.1: "A request whose headers are missing, or whose
        `X-User-Role` is not one of these four declared roles, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/errors/c_missing_auth_header_returns_400
        """
        from test_helpers import create_representative_payload
        resp = api.create_representative(
            create_representative_payload(crd_number="CRD-NH1"), headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestSegregationOfDuties:
    def test_author_cannot_approve(self, api):
        """PRD §3.2: "The approver's `X-User-ID` must differ from the content's
        `author_user_id`; an author attempting to approve their own course is
        rejected with `ERR_SOD_AUTHOR_CANNOT_APPROVE`."

        Design: Corner/validations/c_sod_author_cannot_approve_returns_403
        """
        author = make_admin_headers("ta-sod")
        content = get_success_data(
            api.create_content(create_content_payload(code="SOD-1"), author))
        get_success_data(api.submit_content(content["id"], author))

        # Approve with an X-User-ID equal to the author (SoD violation).
        resp = api.approve_content(content["id"], make_officer_headers("ta-sod"))
        validate_error(resp, ApiErrorId.ERR_SOD_AUTHOR_CANNOT_APPROVE)

        data = validate_success(api.get_content(content["id"], OFFICER))
        assert data["content_status"] == "PENDING_APPROVAL", (
            f"SoD-denied approval must leave the content PENDING_APPROVAL, "
            f"got {data['content_status']}")


class TestPriorityPairConflicts:
    def test_state_error_beats_sod_on_approve(self, api):
        """PRD §2.6: "Every incoming request is evaluated against an ordered
        validation chain, and the first failing check determines the response;
        later checks are not evaluated once an earlier one has failed."
        PRD §3.2: "Approval belongs to a `ComplianceOfficer` and requires the
        content to be in `PENDING_APPROVAL` — approving or rejecting content in
        any other status is rejected with `ERR_CONTENT_NOT_PENDING_APPROVAL`."

        Design: Difficulty/priority_pair_validation_conflict/approve_conflict_state_beats_sod
        """
        # Content authored by ta-author-1 and never submitted (still DRAFT).
        content = get_success_data(api.create_content(
            create_content_payload(code="CF-9"), make_admin_headers("ta-author-1")))
        # Approving a DRAFT violates the state guard (step 6) AND, because the
        # caller's X-User-ID equals the author, the SoD guard (step 8). The
        # earlier state error wins.
        resp = api.approve_content(
            content["id"], make_officer_headers("ta-author-1"))
        validate_error(resp, ApiErrorId.ERR_CONTENT_NOT_PENDING_APPROVAL)

    def test_state_error_beats_sod_on_approve_draft_by_other(self, api):
        """PRD §3.2: "approving or rejecting content in any other status is
        rejected with `ERR_CONTENT_NOT_PENDING_APPROVAL`."

        Design: Difficulty/priority_pair_validation_conflict/approve_conflict_state_beats_sod
        """
        # Companion scenario: DRAFT approved by a non-author — still the state
        # guard that fires (no SoD violation present).
        content = get_success_data(api.create_content(
            create_content_payload(code="CF-9b"), ADMIN))
        resp = api.approve_content(content["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_CONTENT_NOT_PENDING_APPROVAL)

    def test_duplicate_enrollment_beats_capacity(self, api, admin_headers):
        """PRD §2.6: "Every incoming request is evaluated against an ordered
        validation chain, and the first failing check determines the response;
        later checks are not evaluated once an earlier one has failed."
        PRD §3.4: "the rep must not already hold an active enrollment for the
        same content: a second enrollment for the same `rep_id` and content
        while one exists in `ENROLLED` or `IN_PROGRESS` is rejected with
        `ERR_DUPLICATE_ENROLLMENT`."

        Design: Difficulty/priority_pair_validation_conflict/enroll_conflict_duplicate_beats_capacity
        """
        rep = create_rep(crd_number="CRD-PC2")
        content, session = create_instructor_led_setup(
            capacity=1, room_name="Room-Dup",
            start_at="2026-09-15T09:00:00Z", end_at="2026-09-15T11:00:00Z")
        # First enrollment fills the only seat AND establishes the duplicate.
        from test_helpers import create_enrollment
        create_enrollment(rep["id"], session_id=session["id"])
        # Second enrollment: duplicate (step 9) AND session full (step 12).
        # Uniqueness is evaluated before capacity, so the duplicate error wins.
        resp = api.create_enrollment(
            {"rep_id": rep["id"], "session_id": session["id"]}, admin_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENROLLMENT)

    def test_duplicate_enrollment_rejected_when_session_has_seats(
            self, api, admin_headers):
        """PRD §3.4: "the rep must not already hold an active enrollment for
        the same content: a second enrollment for the same `rep_id` and content
        while one exists in `ENROLLED` or `IN_PROGRESS` is rejected with
        `ERR_DUPLICATE_ENROLLMENT`."

        Design: Difficulty/priority_pair_validation_conflict/enroll_conflict_duplicate_beats_capacity
        """
        # Companion scenario isolating the duplicate rule with seats to spare:
        # confirms ERR_DUPLICATE_ENROLLMENT fires on its own merits.
        rep = create_rep(crd_number="CRD-PC2b")
        content, session = create_instructor_led_setup(
            capacity=5, room_name="Room-Dup2",
            start_at="2026-09-15T09:00:00Z", end_at="2026-09-15T11:00:00Z")
        from test_helpers import create_enrollment
        create_enrollment(rep["id"], session_id=session["id"])
        resp = api.create_enrollment(
            {"rep_id": rep["id"], "session_id": session["id"]}, admin_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENROLLMENT)


class TestInitialStates:
    def test_assignment_created_assigned_with_computed_deadlines(
            self, api, admin_headers):
        """PRD §3.5: "The assignment clock starts at creation — `due_at` is
        exactly 120 days after creation, and `lapse_after` is a further 30 days
        beyond that — and the new assignment begins in `ASSIGNED`."
        PRD §2.4: "Before it has ever been set, the logical clock reads exactly
        `2026-08-01T00:00:00Z`."

        Design: Corner/state_machines/c_initial_states_on_create
        """
        set_clock(CLOCK_DEFAULT)
        rep = create_rep(crd_number="CRD-C07")
        data = validate_success(
            api.create_regulatory_assignment(
                {"rep_id": rep["id"], "cycle_year": 2026}, admin_headers),
            expected_status=201)
        assert data["assignment_status"] == "ASSIGNED"
        # 120 days after 2026-08-01T00:00:00Z. PRD pins the instants (§3.5),
        # not the fractional-digit rendering — compare parsed instants.
        due_at = datetime.fromisoformat(data["due_at"].replace("Z", "+00:00"))
        lapse_after = datetime.fromisoformat(
            data["lapse_after"].replace("Z", "+00:00"))
        assert due_at == datetime(2026, 11, 29, tzinfo=timezone.utc), (
            f"due_at must be created_at + 120 days, got {data['due_at']}")
        assert lapse_after == datetime(2026, 12, 29, tzinfo=timezone.utc), (
            f"lapse_after must be due_at + 30 days, got {data['lapse_after']}")

    def test_plan_created_needs_analysis(self, api, admin_headers):
        """PRD §3.6: "A new plan begins in `NEEDS_ANALYSIS`, with
        `certified_hours` and `projected_hours` starting at zero and
        `required_hours` unset until publish."

        Design: Corner/state_machines/c_initial_states_on_create
        """
        set_clock(CLOCK_DEFAULT)
        rep = create_rep(crd_number="CRD-C07p")
        from test_helpers import create_plan
        plan = create_plan(rep["id"], rep["version"], plan_year=2026)
        assert plan["plan_status"] == "NEEDS_ANALYSIS"

    def test_session_created_scheduled_with_full_seats(self, api, admin_headers):
        """PRD §3.3: "A new session starts in `SCHEDULED` with
        `available_seats` equal to its `capacity`."

        Design: Corner/state_machines/c_initial_states_on_create
        """
        content = create_approved_content(
            code="ILT-INIT", delivery_format="INSTRUCTOR_LED", credit_hours=2.0)
        session = create_session_for_content(
            content["id"], room_name="Room-Init",
            start_at="2026-10-05T09:00:00Z", end_at="2026-10-05T11:00:00Z",
            capacity=7)
        assert session["session_status"] == "SCHEDULED"
        assert session["available_seats"] == 7


class TestSystemStampedFields:
    def test_author_and_approver_stamped(self, api, admin_headers, officer_headers):
        """PRD §3.2: "New content starts in `DRAFT`, and the server records the
        author's `X-User-ID` as `author_user_id` — the segregation-of-duties
        anchor used at approval time."
        PRD §3.2: "A successful approval stamps `approved_by_user_id` with the
        approver's identity and writes a `CONTENT_APPROVED` audit event."

        Design: Corner/entities/c_content_system_fields_server_set
        """
        author = make_admin_headers("ta-777")
        approver = make_officer_headers("co-999")
        content = get_success_data(
            api.create_content(create_content_payload(code="SYS-1"), author))
        assert content["author_user_id"] == "ta-777", (
            f"author_user_id must be stamped from X-User-ID, "
            f"got {content['author_user_id']!r}")
        assert content["version"] == 1
        get_success_data(api.submit_content(content["id"], author))
        approved = get_success_data(api.approve_content(content["id"], approver))
        assert approved["content_status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "co-999", (
            f"approved_by_user_id must be stamped at approval, "
            f"got {approved['approved_by_user_id']!r}")


class TestAuditLog:
    def test_content_approval_is_audited(self, api, auditor_headers):
        """PRD §2.9: "The system maintains an append-only audit evidence log."
        PRD §3.2: "A successful approval stamps `approved_by_user_id` with the
        approver's identity and writes a `CONTENT_APPROVED` audit event."
        PRD §2.9: "The log is queryable through a dedicated list endpoint
        restricted to the `Auditor` and `ComplianceOfficer` roles, filterable
        by `entity_type`, `entity_id`, and `event_type`."

        Design: Corner/entities/c_audit_event_append_only_retrieval
        """
        content = create_approved_content(code="AUD-1")
        data, _meta = validate_paginated(api.list_audit_events(
            auditor_headers,
            params={"entity_type": "TrainingContent", "entity_id": content["id"]}))
        event_types = [e["event_type"] for e in data]
        assert "CONTENT_APPROVED" in event_types, (
            f"approval must be retrievable as a CONTENT_APPROVED event, "
            f"got {event_types}")


class TestPagination:
    def test_pagination_envelope(self, api, auditor_headers):
        """PRD §2.3: "Paginated list responses carry the fields `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object of the
        response envelope, so a client can always determine how many records
        exist in total and whether further pages remain."
        PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return; it defaults to 10 when omitted."

        Design: Corner/endpoints/c_list_pagination_envelope
        """
        for code in ("PG-1", "PG-2", "PG-3"):
            get_success_data(
                api.create_content(create_content_payload(code=code), ADMIN))

        page1, meta1 = validate_paginated(
            api.list_contents(auditor_headers, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_contents(auditor_headers, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestFilteredList:
    def test_enrollments_filtered_by_rep(self, api, admin_headers):
        """PRD §3.4: "The enrollment list can be filtered by `rep_id`,
        `content_id`, `session_id`, and `enrollment_status`."

        Design: Corner/endpoints/c_filtered_list_reverse_reachability
        """
        from test_helpers import create_enrollment
        rep_a = create_rep(crd_number="CRD-C31A")
        rep_b = create_rep(crd_number="CRD-C31B")
        c1 = create_approved_content(code="FLT-1")
        c2 = create_approved_content(code="FLT-2")
        create_enrollment(rep_a["id"], content_id=c1["id"])
        create_enrollment(rep_a["id"], content_id=c2["id"])
        create_enrollment(rep_b["id"], content_id=c1["id"])

        data, _meta = validate_paginated(
            api.list_enrollments(admin_headers, params={"rep_id": rep_a["id"]}))
        assert len(data) == 2, (
            f"rep_id filter must return exactly A's two enrollments, "
            f"got {len(data)}")
        assert all(row["rep_id"] == rep_a["id"] for row in data)
