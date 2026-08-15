"""Intake semantics, confidentiality firewall, envelope shapes, pagination, reporter channel."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_case,
    create_case_payload,
    create_staff,
    make_admin_headers,
    make_officer_headers,
    make_reporter_headers,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)


class TestStaffCreationDefaults:
    def test_employment_status_defaults_active(self, api):
        """PRD §3.1: "`employment_status` may be supplied but defaults to `ACTIVE`".

        Design: Corner/entities/staff_member_creation_applies_defaults
        """
        resp = api.create_staff_member({
            "display_name": "Olivia Officer", "email": "officer@corp.example",
            "department": "Ethics", "capabilities": ["OFFICER"], "max_active_cases": 5,
        }, make_admin_headers())
        data = validate_success(resp, expected_status=201)
        assert data["employment_status"] == "ACTIVE"

    def test_workload_counters_start_at_zero(self, api):
        """PRD §3.1: "Both start at 0 for a newly registered staff member."

        Design: Corner/entities/staff_member_creation_applies_defaults
        """
        resp = api.create_staff_member({
            "display_name": "Olivia Officer", "email": "officer@corp.example",
            "department": "Ethics", "capabilities": ["OFFICER"], "max_active_cases": 5,
        }, make_admin_headers())
        data = validate_success(resp, expected_status=201)
        assert data["active_case_count"] == 0
        assert data["weighted_caseload"] == 0
        assert data["version"] == 1


class TestIntakeSystemFields:
    def test_intake_returns_received_status_and_version_one(self, api):
        """PRD §3.2: "A successful intake creates the case in `RECEIVED` status".

        Design: Corner/entities/case_intake_mints_key_and_received_state
        """
        case, key = create_case()
        assert case["status"] == "RECEIVED"
        assert case["version"] == 1
        assert isinstance(key, str) and key

    def test_received_at_uses_logical_clock_default(self, api):
        """PRD §2.9: "Before any clock-setting call, the logical clock reads exactly
        2026-08-01T00:00:00Z." PRD §3.2: intake "stamps `received_at` from the
        logical clock".

        Design: Corner/entities/case_intake_mints_key_and_received_state
        """
        case, _ = create_case()
        assert case["received_at"] == "2026-08-01T00:00:00Z", (
            f"received_at must come from the logical clock default, got {case['received_at']}"
        )
        assert case["is_anonymous"] is True, "is_anonymous defaults to true"


class TestIntakeValidation:
    def test_missing_description_returns_invalid_request(self, api):
        """PRD §3.2: "a free-text `description` of at least 20 characters" (required);
        §2.11 sixth: "required fields present ... (`ERR_INVALID_REQUEST`)".

        Design: Corner/entities/case_create_missing_required_returns_invalid_request
        """
        resp = api.create_case({
            "channel": "WEB_PORTAL", "category": "FRAUD", "region": "NORTH",
        }, make_reporter_headers("anon-e2"))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_out_of_vocabulary_category_returns_invalid_request(self, api):
        """PRD §3.2: category is "one of `FRAUD`, `HARASSMENT`, `SAFETY`,
        `FINANCIAL_REPORTING`, `DATA_PRIVACY`, `CONFLICT_OF_INTEREST`, or `OTHER`";
        §2.11 sixth: "enum values valid ... (`ERR_INVALID_REQUEST`)".

        Design: Corner/entities/case_create_invalid_enum_returns_invalid_request
        """
        payload = create_case_payload(category="THEFT")
        resp = api.create_case(payload, make_reporter_headers("anon-e3"))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestConfidentialityFirewall:
    def _mk_officer_and_identified_case(self, api):
        s_off = create_staff("Olivia Officer", "officer@corp.example", ["OFFICER"])
        case, _ = create_case(
            channel="EMAIL", category="HARASSMENT",
            description="Allegation of hostile workplace conduct",
            region="EAST", is_anonymous=False, reporter_contact="jane.doe@example.com",
        )
        return s_off, case

    def test_single_case_read_redacts_reporter_fields(self, api):
        """PRD §2.5: "Neither field is ever present in any staff-facing response:
        not in case list payloads, not in single-case reads".

        Design: Corner/entities/identified_report_requires_contact_and_staff_view_redacts
        """
        s_off, case = self._mk_officer_and_identified_case(api)
        resp = api.get_case(case["id"], make_officer_headers(s_off["id"]))
        data = validate_success(resp)
        assert "reporter_contact" not in data
        assert "reporter_access_key" not in data

    def test_case_list_rows_redact_reporter_fields(self, api):
        """PRD §2.5: "Neither field is ever present in any staff-facing response:
        not in case list payloads, not in single-case reads, not in any
        child-resource payload."

        Design: Corner/entities/identified_report_requires_contact_and_staff_view_redacts
        """
        s_off, case = self._mk_officer_and_identified_case(api)
        resp = api.list_cases(make_officer_headers(s_off["id"]))
        rows, _meta = validate_paginated(resp)
        target = [r for r in rows if r["id"] == case["id"]]
        assert target, "created case must appear in list"
        for row in target:
            assert "reporter_contact" not in row
            assert "reporter_access_key" not in row


class TestReporterStatus:
    def test_reporter_status_shape_before_triage(self, api):
        """PRD §3.2: "A reporter self-service view answers with exactly four fields —
        `case_status`, `severity`, `closure_summary`, and `monitoring_active`".

        Design: Corner/entities/reporter_status_returns_redacted_inline_view
        """
        case, key = create_case()
        resp = api.get_reporter_status(case["id"], make_reporter_headers(key))
        data = validate_success(resp)
        assert data["case_status"] == "RECEIVED"
        assert data["monitoring_active"] is False
        assert data["severity"] is None
        assert data["closure_summary"] is None

    def test_reporter_status_wrong_key_denied(self, api):
        """PRD §3.2: "only when `X-User-ID` equals the case's `reporter_access_key`;
        any other key is refused with `ERR_REPORTER_ACCESS_DENIED`".

        Design: Corner/errors/reporter_wrong_key_returns_access_denied
        """
        case, _key = create_case()
        resp = api.get_reporter_status(case["id"], make_reporter_headers("wrong-key-999"))
        validate_error(resp, ApiErrorId.ERR_REPORTER_ACCESS_DENIED)


class TestNotFound:
    def test_get_nonexistent_case_404(self, api):
        """PRD §2.11 fifth: "path resource existence, validated left to right along
        the URL hierarchy (`ERR_NOT_FOUND`)".

        Design: Corner/entities/case_get_nonexistent_returns_not_found
        """
        s_off = create_staff("Olivia Officer", "officer@corp.example", ["OFFICER"])
        resp = api.get_case(NON_EXISTENT_UUID, make_officer_headers(s_off["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestCaseListPagination:
    def _three_cases(self, api):
        s_off = create_staff("Olivia Officer", "officer@corp.example", ["OFFICER"])
        create_case(description="Allegation of expense fraud case one")
        create_case(channel="PHONE", category="SAFETY",
                    description="Allegation of unsafe practice case two", region="SOUTH")
        create_case(channel="EMAIL", category="OTHER",
                    description="Allegation of policy lapse case three", region="EAST")
        return s_off

    def test_first_page_limit_offset(self, api):
        """PRD §2.3: "The `meta` object of every list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/case_list_pagination_envelope
        """
        s_off = self._three_cases(api)
        resp = api.list_cases(make_officer_headers(s_off["id"]), params={"limit": 2, "offset": 0})
        rows, meta = validate_paginated(resp)
        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

    def test_last_page_has_more_false(self, api):
        """PRD §2.3: "The `meta` object of every list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/case_list_pagination_envelope
        """
        s_off = self._three_cases(api)
        resp = api.list_cases(make_officer_headers(s_off["id"]), params={"limit": 2, "offset": 2})
        rows, meta = validate_paginated(resp)
        assert len(rows) == 1
        assert meta["has_more"] is False


class TestEnvelopeShapes:
    def test_error_envelope_on_404(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`" and
        "`response_type`: \"error\"".

        Design: Corner/endpoints/error_envelope_shape_on_404
        """
        s_off = create_staff("Olivia Officer", "officer@corp.example", ["OFFICER"])
        resp = api.get_case("22222222-2222-2222-2222-222222222222", make_officer_headers(s_off["id"]))
        body = resp.json()
        assert resp.status_code == 404
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
        assert "api_request_id" in body["meta"]

    def test_success_envelope_on_create(self, api):
        """PRD §2.2: "The `response_type` is either \"object\" for a single resource"
        and "The `api_request_id` is a server-generated unique identifier for the
        request". PRD §4: "Resource-creating operations return HTTP 201".

        Design: Corner/endpoints/success_envelope_shape_on_create
        """
        resp = api.create_staff_member({
            "display_name": "Olivia Officer", "email": "officer@corp.example",
            "department": "Ethics", "capabilities": ["OFFICER"], "max_active_cases": 5,
        }, make_admin_headers())
        body = resp.json()
        assert resp.status_code == 201
        assert body["response_type"] == "object"
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]
        assert isinstance(body["data"], dict) and body["data"]["id"]


class TestAuthHeaderGate:
    def test_missing_headers_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role outside the
        declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        resp = api.list_cases(headers={"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
