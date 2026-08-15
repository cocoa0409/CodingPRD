"""Staff roster basics, authentication, role authorization, and identifier
resolution errors."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_staff_member,
    create_analytics_report_payload,
    create_staff_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_assignment_editor_headers,
    make_managing_editor_headers,
    make_reporter_headers,
    make_staff,
    validate_error,
    validate_success,
)

ND = TEST_USERS["news_director_headers"]


class TestStaffCreation:
    def test_staff_create_defaults_and_system_fields(self, api):
        """PRD §3.1: "An optional `max_concurrent_assignments` caps how many
        accepted assignments the person may hold at once; it defaults to 3 when
        omitted and must be at least 1."
        PRD §3.1: "New staff start with `employment_status` set to `ACTIVE` and
        an `active_assignment_count` of zero."
        PRD §2.5: "`version` (integer): starts at 1 and increments by exactly
        one on every mutation of the resource, including mutations driven by
        system side effects; it is the basis of optimistic concurrency control."
        PRD §2.5: "`id` (string): a server-minted UUID with no type prefix."

        Design: Corner/entities/staff_create_defaults_and_system_fields
        """
        resp = api.create_staff(
            create_staff_payload(full_name="Base Staff",
                                 role_capability="REPORTER",
                                 home_desk="METRO", hourly_rate_cents=6000),
            ND,
        )
        staff = validate_success(resp, 201)
        assert_staff_member(staff)
        assert staff["max_concurrent_assignments"] == 3, \
            "omitted cap defaults to 3"
        assert staff["employment_status"] == "ACTIVE"
        assert staff["active_assignment_count"] == 0
        assert staff["version"] == 1, "a new resource is born at version 1"
        assert is_valid_uuid(staff["id"]), "id is a bare UUID"
        assert is_iso8601_timestamp(staff["created_at"])

    def test_staff_create_missing_required_field_returns_400(self, api):
        """PRD §3.1: "A `NewsDirector` onboards a staff member by supplying
        their `full_name`, editorial `role_capability`, `home_desk`, and
        `hourly_rate_cents` — a non-negative integer cost rate in cents per
        hour that feeds both provisional assignment costing and weekly
        payroll."
        PRD §2.7: "3. Request-body schema — required fields present, types
        correct, and enum values inside their declared domains (`urgency`,
        `story_type`, `severity`, `review_type`, `verdict`, `variant`,
        `channel`, `role_capability`, `home_desk`, `employment_status`,
        `assignment_role`); failures yield `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/staff_create_missing_required_field_returns_400
        """
        payload = create_staff_payload(full_name="No Rate",
                                       role_capability="REPORTER",
                                       home_desk="METRO")
        del payload["hourly_rate_cents"]
        resp = api.create_staff(payload, ND)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_story_get_not_found_returns_404(self, api):
        """PRD §2.6: "Each parameterized segment — `staffId`, `pitchId`,
        `storyId`, `assignmentId`, `slotId`, `correctionId`, `eventId`, or
        `callInId` — must resolve to an existing resource, and the request is
        rejected with the 404 error matching the first segment that does not
        resolve: `ERR_STAFF_NOT_FOUND`, `ERR_PITCH_NOT_FOUND`,
        `ERR_STORY_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
        `ERR_SLOT_NOT_FOUND`, `ERR_CORRECTION_NOT_FOUND`,
        `ERR_EVENT_NOT_FOUND`, or `ERR_CALL_IN_NOT_FOUND` respectively."

        Design: Corner/entities/story_get_not_found_returns_404
        """
        resp = api.get_story(NON_EXISTENT_UUID, ND)
        validate_error(resp, ApiErrorId.ERR_STORY_NOT_FOUND)


class TestAuthentication:
    def test_request_without_auth_headers_returns_401(self, api):
        """PRD §2.1: "A request whose headers are missing, whose role is not
        one of these nine values, or — for any entity-backed role — whose
        `X-User-ID` does not resolve to an existing staff member is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/request_without_auth_headers_returns_401
        """
        resp = api.list_staff({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleAuthorization:
    def test_role_denial_matrix_sample(self, api):
        """PRD §2.1: "A request whose role is not listed among an endpoint's
        permitted roles is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.7: "2. Role authorization — the acting role appears in the
        endpoint's permitted roles; failures yield `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/role_denial_matrix_sample
        """
        desk = make_staff("Desk RD", "DESK_EDITOR")
        rep = make_staff("Rep RD", "REPORTER")
        me = make_staff("ME RD", "MANAGING_EDITOR", hourly_rate_cents=8000)
        desk_h = make_assignment_editor_headers(desk["id"])
        rep_h = make_reporter_headers(rep["id"])
        me_h = make_managing_editor_headers(me["id"])

        # Staff administration is NewsDirector-only.
        e1 = api.create_staff(
            create_staff_payload(full_name="Intruder", hourly_rate_cents=1),
            desk_h)
        validate_error(e1, ApiErrorId.ERR_FORBIDDEN)

        # Analytics ingestion is AnalyticsProducer-only; the role check fires
        # even though the story id does not resolve.
        e2 = api.create_story_analytics_report(
            NON_EXISTENT_UUID, create_analytics_report_payload(), rep_h)
        validate_error(e2, ApiErrorId.ERR_FORBIDDEN)

        # Event activation is NewsDirector-only.
        e3 = api.activate_breaking_event(NON_EXISTENT_UUID, me_h)
        validate_error(e3, ApiErrorId.ERR_FORBIDDEN)

        # Correction issuance is ManagingEditor-only.
        e4 = api.issue_correction(NON_EXISTENT_UUID, desk_h)
        validate_error(e4, ApiErrorId.ERR_FORBIDDEN)


class TestNotFoundVariants:
    def test_every_path_segment_family_resolves_to_its_own_404(self, api):
        """PRD §2.6: "Requests that target a resource by path are validated
        left to right. Each parameterized segment — `staffId`, `pitchId`,
        `storyId`, `assignmentId`, `slotId`, `correctionId`, `eventId`, or
        `callInId` — must resolve to an existing resource, and the request is
        rejected with the 404 error matching the first segment that does not
        resolve: `ERR_STAFF_NOT_FOUND`, `ERR_PITCH_NOT_FOUND`,
        `ERR_STORY_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
        `ERR_SLOT_NOT_FOUND`, `ERR_CORRECTION_NOT_FOUND`,
        `ERR_EVENT_NOT_FOUND`, or `ERR_CALL_IN_NOT_FOUND` respectively."

        Design: Corner/errors/not_found_variants
        """
        rep = make_staff("Rep NF", "REPORTER")
        me = make_staff("ME NF", "MANAGING_EDITOR", hourly_rate_cents=8000)
        rep_h = make_reporter_headers(rep["id"])
        me_h = make_managing_editor_headers(me["id"])

        cases = [
            (api.get_staff(NON_EXISTENT_UUID, ND),
             ApiErrorId.ERR_STAFF_NOT_FOUND),
            (api.get_pitch(NON_EXISTENT_UUID, ND),
             ApiErrorId.ERR_PITCH_NOT_FOUND),
            (api.accept_assignment(NON_EXISTENT_UUID, rep_h),
             ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
            (api.get_slot(NON_EXISTENT_UUID, ND),
             ApiErrorId.ERR_SLOT_NOT_FOUND),
            (api.approve_correction(NON_EXISTENT_UUID, me_h),
             ApiErrorId.ERR_CORRECTION_NOT_FOUND),
            (api.activate_breaking_event(NON_EXISTENT_UUID, ND),
             ApiErrorId.ERR_EVENT_NOT_FOUND),
            (api.confirm_call_in(NON_EXISTENT_UUID, rep_h),
             ApiErrorId.ERR_CALL_IN_NOT_FOUND),
        ]
        for resp, expected in cases:
            validate_error(resp, expected)
