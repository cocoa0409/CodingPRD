"""Member intake, response envelope, clock default, and baseline access control."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_member,
    assert_npdb_report,
    create_member_payload,
    create_npdb_report_payload,
    is_valid_uuid,
    parse_ts,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
PRACTITIONER = TEST_USERS["practitioner_headers"]


class TestMemberCreation:
    def test_member_creation_applies_defaults_and_system_fields(self, api):
        """PRD §3.1: "The record is born with `membership_status` `APPLICANT`,
        `privilege_posture` `NONE`, an `active_privilege_line_count` of zero, a
        `credential_expiry_risk_score` of zero, and empty `sod_exclusion_tags`."
        PRD §2.5: "Before any clock-setting call has been made, the logical clock
        reads exactly `2026-08-01T00:00:00Z` — a fixed startup default that never
        falls back to wall-clock time."

        Design: Corner/entities/member_creation_applies_defaults_and_system_fields
        """
        resp = api.create_member(
            create_member_payload("Dr. New", "NPDB-NEW", "CARD"), COORD)
        data = validate_success(resp, 201)
        assert_member(data)
        assert data["membership_status"] == "APPLICANT"
        assert data["privilege_posture"] == "NONE"
        assert data["active_privilege_line_count"] == 0
        assert data["credential_expiry_risk_score"] == 0
        assert data["sod_exclusion_tags"] == []
        assert is_valid_uuid(data["id"])
        assert parse_ts(data["created_at"]) == parse_ts("2026-08-01T00:00:00Z"), (
            "created_at must reflect the fixed startup logical clock")

        fetched = validate_success(api.get_member(data["id"], COORD))
        assert_member(fetched)
        assert fetched["membership_status"] == "APPLICANT"
        assert fetched["privilege_posture"] == "NONE"

    def test_member_creation_missing_required_field_returns_400(self, api):
        """PRD §2.9: "Required fields present, enum values valid, minimum string
        lengths met, and start-before-end datetime ordering respected —
        `ERR_INVALID_REQUEST` (400), applying to every endpoint."
        PRD §3.1: "a coordinator creates their **MedicalStaffMember** record from
        a `full_name`, an `npdb_subject_id` (the identifier later used on NPDB
        queries and reports), and a `primary_specialty_code`".

        Design: Corner/entities/member_creation_missing_required_field_returns_400
        """
        resp = api.create_member(
            {"full_name": "Dr. NoSubj", "primary_specialty_code": "CARD"}, COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

        _data, meta = validate_paginated(api.list_members(COORD))
        assert meta["total_count"] == 0, "Rejected creation must not persist a row"

    def test_application_kind_invalid_enum_rejected(self, api):
        """PRD §2.9: "Required fields present, enum values valid, minimum string
        lengths met, and start-before-end datetime ordering respected —
        `ERR_INVALID_REQUEST` (400), applying to every endpoint."
        PRD §3.1: "an `application_kind` of `INITIAL` or `REAPPOINTMENT`".

        Design: Corner/entities/application_kind_invalid_enum_rejected
        """
        member = validate_success(
            api.create_member(
                create_member_payload("Dr. Enum", "NPDB-ENUM", "CARD"), COORD),
            201)
        resp = api.create_application(
            {"member_id": member["id"], "application_kind": "LOCUMS",
             "expected_member_version": member["version"]},
            COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_get_member_with_unknown_id_returns_404(self, api):
        """PRD §2.9: "Every referenced resource exists: path identifiers are
        validated left to right, then foreign keys carried in the body —
        `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/get_member_with_unknown_id_returns_404
        """
        resp = api.get_member(NON_EXISTENT_UUID, COORD)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestListEnvelope:
    def test_list_members_pagination_fields_present(self, api):
        """PRD §2.3: "Paginated list responses carry four pagination fields in
        the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/list_members_pagination_fields_present
        """
        validate_success(
            api.create_member(create_member_payload("Dr. P1", "NPDB-PG1", "CARD"),
                              COORD), 201)
        validate_success(
            api.create_member(create_member_payload("Dr. P2", "NPDB-PG2", "CARD"),
                              COORD), 201)

        resp = api.list_members(COORD, params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        assert len(data) == 1, f"limit=1 must return one row, got {len(data)}"
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0


class TestNpdbReportImmutability:
    def test_npdb_report_is_immutable_event_entity(self, api):
        """PRD §2.4: "An NPDB report is an immutable filing record and carries
        only `id` and `created_at`; both `updated_at` and `version` are absent
        from it."

        Design: Corner/entities/npdb_report_is_immutable_event_entity
        """
        member = validate_success(
            api.create_member(create_member_payload("Dr. Imm", "NPDB-IMM", "CARD"),
                              COORD), 201)
        report = validate_success(
            api.create_npdb_report(
                create_npdb_report_payload(member["id"], "QUERY_INITIAL"), COORD),
            201)

        fetched = validate_success(api.get_npdb_report(report["id"], COORD))
        assert_npdb_report(fetched)
        assert "version" not in fetched, "NpdbReport must not expose version"
        assert "updated_at" not in fetched, "NpdbReport must not expose updated_at"
        assert fetched["report_status"] == "SUBMITTED"
        assert parse_ts(fetched["submitted_at"]) == parse_ts(
            "2026-08-01T00:00:00Z"), (
            "submitted_at is stamped from the logical clock's startup default")


class TestAuthContext:
    def test_missing_auth_headers_returns_400(self, api):
        """PRD §2.1: "A request that omits either header, or carries a role value
        outside this list, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        resp = api.list_members(headers={})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)

    def test_rbac_practitioner_cannot_create_members(self, api):
        """PRD §2.1: "A request whose declared role is not authorized for the
        target operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: POST /mso/members is authorized for MedicalStaffCoordinator only.

        Design: Corner/roles/rbac_practitioner_cannot_create_members
        """
        resp = api.create_member(
            create_member_payload("Dr. RBAC", "NPDB-RB", "CARD"), PRACTITIONER)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


class TestLogicalClockDefault:
    def test_clock_startup_default_is_fixed(self, api):
        """PRD §2.5: "Before any clock-setting call has been made, the logical
        clock reads exactly `2026-08-01T00:00:00Z` — a fixed startup default that
        never falls back to wall-clock time."

        Design: Corner/endpoints/clock_startup_default_is_fixed
        """
        # No clock-setting call is made in this test at all.
        member = validate_success(
            api.create_member(
                create_member_payload("Dr. Clock", "NPDB-CLK", "CARD"), COORD),
            201)
        assert parse_ts(member["created_at"]) == parse_ts(
            "2026-08-01T00:00:00Z"), (
            "created_at must equal the fixed startup default, not wall-clock")
