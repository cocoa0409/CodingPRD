"""Registry provisioning, access control, and response-envelope claims (PRD §2, §3.1)."""
from test_helpers import (
    ADMIN,
    BOARD,
    NON_EXISTENT_UUID,
    RAM,
    ApiErrorId,
    assert_commitment,
    create_agency,
    create_agency_payload,
    create_commitment_payload,
    create_examination,
    create_examination_payload,
    create_officer,
    is_valid_uuid,
    make_remediation_owner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRegistryProvisioning:
    def test_agency_creation_applies_active_default(self, api):
        """PRD §3.1: "The `active` flag defaults to true; an agency that has been
        deactivated may not be linked to new examinations, though its history
        remains readable."

        Design: Corner/entities/agency_creation_assigns_defaults
        """
        resp = api.create_agency(
            create_agency_payload(agency_code="XST", agency_name="State Reg",
                                  jurisdiction="STATE", escalation_threshold_days=10,
                                  repeat_finding_multiplier_bp=15000),
            ADMIN)
        data = validate_success(resp, 201)
        assert data["active"] is True, "omitted active flag must default to true"

    def test_agency_invalid_jurisdiction_enum_rejected(self, api):
        """PRD §3.1: "together with the agency's full legal `agency_name` and its
        `jurisdiction`, one of `FEDERAL`, `STATE`, or `FOREIGN`."
        PRD §2.9: "All required fields are present, enum values are valid, and
        arrays declared non-empty are non-empty — otherwise `ERR_INVALID_REQUEST`
        (HTTP 400)."

        Design: Corner/entities/agency_invalid_enum_jurisdiction_rejected
        """
        resp = api.create_agency(
            create_agency_payload(agency_code="BAD", jurisdiction="INTERNATIONAL"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_agency_code_uniqueness_enforced(self, api):
        """PRD §3.1: "A duplicate `agency_code` is rejected with
        `ERR_DUPLICATE_KEY`."

        Design: Corner/entities/agency_code_uniqueness_enforced
        """
        create_agency(agency_code="DUP")
        resp = api.create_agency(
            create_agency_payload(agency_code="DUP", agency_name="Second",
                                  jurisdiction="STATE", escalation_threshold_days=60),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY)

    def test_get_nonexistent_examination_returns_not_found(self, api, ram_headers):
        """PRD §2.8: "each path segment must resolve to an existing resource
        before the next is examined, and the first segment that fails to resolve
        yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_nonexistent_entity_returns_not_found
        """
        resp = api.get_examination(NON_EXISTENT_UUID, ram_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_examination_system_fields_present(self, api):
        """PRD §2.4: "Every persisted resource carries an `id` minted by the
        server as a bare UUID — no type prefix, no human-readable slug."
        PRD §2.4: "every resource also carries `created_at` and `updated_at`,
        both ISO 8601 UTC timestamps rendered with three fractional digits, and
        a `version` integer that starts at 1 and increments by exactly one on
        every mutation of that resource"

        Design: Corner/entities/examination_system_fields_present
        """
        agency = create_agency(agency_code="SYS")
        resp = api.create_examination(create_examination_payload(agency["id"]), RAM)
        data = validate_success(resp, 201)
        assert data["version"] == 1, "fresh entity must start at version 1"
        assert is_valid_uuid(data["id"]), "id must be a bare UUID"
        assert "-" in data["id"] and not data["id"].split("-")[0].isalpha(), (
            "id carries no type prefix"
        )

    def test_commitment_log_entry_is_append_only_without_version(self, api):
        """PRD §2.4: "The exception is the commitment log: a `CommitmentLogEntry`
        is an append-only record and carries only `id` and `created_at`. It has
        no `updated_at` and no `version` — once written, a commitment entry is
        never modified in place; its only later change is the `fulfilled_at`
        stamp described in §3.8, which is itself an immutable write-once field."

        Design: Corner/entities/commitment_log_immutable_no_update_endpoint
        """
        agency = create_agency(agency_code="C1")
        exam = create_examination(agency["id"])
        officer = create_officer()
        resp = api.create_commitment(
            exam["id"],
            create_commitment_payload(committed_by_user_id=officer["id"]),
            RAM)
        data = validate_success(resp, 201)
        assert_commitment(data)
        assert data["created_at"], "created_at must be present"


class TestAccessControl:
    def test_missing_auth_headers_return_unauthenticated(self, api):
        """PRD §2.1: "A request whose headers are missing or malformed, or whose
        role string is not one of the five, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        resp = api.list_agencies(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_remediation_owner_cannot_approve_closure(self, api):
        """PRD §2.9: "When several checks could apply to one request, the server
        evaluates them in a single fixed order, and the first failing check
        determines the error response." — authorization (step 2) precedes
        existence (step 3), and §4 reserves closure approval to
        ComplianceReviewer: "| POST | /regulatory-exams/closure-requests/{id}/approve | Approve a PENDING closure request; closes the parent issue (OCC-guarded on the issue) | ComplianceReviewer |"

        Design: Corner/rbac/remediation_owner_cannot_approve_closure
        """
        officer = create_officer()
        owner_headers = make_remediation_owner_headers(officer["id"])
        resp = api.approve_closure_request(
            NON_EXISTENT_UUID, {"expected_issue_version": 1}, owner_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_platform_admin_cannot_file_issue(self, api):
        """PRD §4: "| POST | /regulatory-exams/examinations/{id}/issues | File a formal MRA/MRIA issue (OCC-guarded) | RegulatoryAffairsManager |"
        PRD §2.1: "A well-authenticated caller whose role is not permitted to
        invoke the requested endpoint is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."

        Design: Corner/rbac/platform_admin_cannot_file_issue
        """
        agency = create_agency(agency_code="RA")
        exam = create_examination(agency["id"])
        resp = api.create_issue(
            exam["id"],
            {
                "issue_ref": "X",
                "classification": "MRA",
                "severity": "LOW",
                "due_date": "2026-09-01T00:00:00Z",
                "expected_examination_version": exam["version"],
            },
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_board_reporter_exclusive_generate_and_finalize(self, api):
        """PRD §4: "| POST | /regulatory-exams/board-reports | Generate a board report snapshot for an examination | BoardReporter |"
        PRD §3.9: "A report is born `DRAFT` and finalizing it moves `DRAFT` →
        `FINALIZED`, after which it is immutable; report listings filter by
        `examination_id` and `status`."
        PRD §3.9: "`open_issue_count`, the issues on this examination whose
        status is anything other than `CLOSED`"

        Design: Corner/rbac/board_reporter_exclusive_generate_and_finalize
        """
        agency = create_agency(agency_code="BR")
        exam = create_examination(agency["id"])
        create_resp = api.create_board_report(
            {
                "examination_id": exam["id"],
                "reporting_period_start": "2026-07-01T00:00:00Z",
                "reporting_period_end": "2026-07-31T00:00:00Z",
            },
            BOARD)
        report = validate_success(create_resp, 201)
        assert report["open_issue_count"] == 0, "no issues filed yet"
        fin_resp = api.finalize_board_report(report["id"], BOARD)
        finalized = validate_success(fin_resp, 200)
        assert finalized["status"] == "FINALIZED"

        ram_resp = api.create_board_report(
            {
                "examination_id": exam["id"],
                "reporting_period_start": "2026-07-01T00:00:00Z",
                "reporting_period_end": "2026-07-31T00:00:00Z",
            },
            RAM)
        validate_error(ram_resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestEnvelopeAndClock:
    def test_pagination_defaults_applied_on_list(self, api, ram_headers):
        """PRD §2.3: "`limit` controls the page size: it defaults to 10, and any
        value from 1 up to and including 100 is accepted. `offset` controls how
        many records are skipped and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`, where
        `has_more` reports whether additional records exist beyond the returned
        page."

        Design: Corner/endpoints/pagination_defaults_applied_on_list
        """
        for i in range(15):
            create_officer(full_name=f"O{i + 1}", email=f"o{i + 1}@x.test")
        resp = api.list_officers(ram_headers)
        body = resp.json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        data, meta = validate_paginated(resp)
        assert len(data) == 10, "default page size is 10"
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 15
        assert meta["has_more"] is True

    def test_logical_clock_defaults_to_2026_08_01(self, api):
        """PRD §2.5: "Before any operator intervention the logical clock reads
        exactly `2026-08-01T00:00:00Z`; the server must not fall back to
        wall-clock time under any circumstance."

        Design: Corner/cross_cutting_layers/clock_default_time_is_2026_08_01
        """
        resp = api.create_agency(create_agency_payload(agency_code="CD"), ADMIN)
        data = validate_success(resp, 201)
        assert data["created_at"].startswith("2026-08-01T00:00:00"), (
            f"server-stamped created_at must reflect the default logical clock, "
            f"got {data['created_at']}"
        )
