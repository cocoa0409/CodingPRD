"""Role-based access denials, the fixed response envelopes, and the 404 vocabulary."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_audit_entry,
    assert_error_envelope,
    create_batch_payload,
    create_data_field_payload,
    create_grant_record,
    create_position_payload,
    create_position_record,
    create_worker_payload,
    get_success_data,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
STEWARD = TEST_USERS["steward_headers"]
APPROVER = TEST_USERS["approver_headers"]
OPERATOR = TEST_USERS["operator_headers"]
SECADMIN = TEST_USERS["security_admin_headers"]


class TestRbac:
    def test_rbac_analyst_cannot_create_data_field(self, api, analyst_headers):
        """PRD §4: "| POST | `/hris/data-fields` | Create a data-dictionary entry
        in `DRAFT` | DataSteward |"
        PRD §2.1: "Each operation is restricted to designated roles; an
        authenticated caller attempting an operation outside their role is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/rbac_analyst_cannot_create_data_field
        """
        create_position_record()  # DB non-empty
        payload = create_data_field_payload(field_key="assignment.pay_grade", display_name="Grade")
        resp = api.create_data_field(payload, analyst_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_rbac_steward_cannot_create_worker(self, api, steward_headers):
        """PRD §4: "| POST | `/hris/workers` | Hire a worker, seeding the initial
        assignment row | HrisAnalyst |"
        PRD §2.1: "Each operation is restricted to designated roles; an
        authenticated caller attempting an operation outside their role is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/rbac_steward_cannot_create_worker
        """
        pos = create_position_record()
        payload = create_worker_payload(
            legal_name="Deny", worker_number="W910", initial_position_id=pos["id"],
        )
        resp = api.create_worker(payload, steward_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_rbac_approver_cannot_apply_change(self, api, approver_headers):
        """PRD §4: "| POST | `/hris/change-requests/{changeRequestId}/apply` |
        Apply an `APPROVED` request | HrisAnalyst |"
        PRD §2.1: "Each operation is restricted to designated roles; an
        authenticated caller attempting an operation outside their role is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/rbac_approver_cannot_apply_change
        """
        create_position_record()  # DB non-empty
        resp = api.apply_change_request(NON_EXISTENT_UUID, approver_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_rbac_operator_cannot_resolve_exception(self, api, operator_headers):
        """PRD §4: "| POST | `/hris/exception-records/{exceptionId}/resolve` |
        Resolve an `OPEN` exception | DataSteward |"
        PRD §2.1: "Each operation is restricted to designated roles; an
        authenticated caller attempting an operation outside their role is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/rbac_operator_cannot_resolve_exception
        """
        create_position_record()  # DB non-empty
        resp = api.resolve_exception_record(
            NON_EXISTENT_UUID, {"resolution_note": "x"}, operator_headers
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_rbac_security_admin_cannot_create_batch(self, api, security_admin_headers):
        """PRD §4: "| POST | `/hris/mass-change-batches` | Create an empty reorg
        batch | HrisAnalyst |"
        PRD §2.1: "Each operation is restricted to designated roles; an
        authenticated caller attempting an operation outside their role is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/rbac_security_admin_cannot_create_batch
        """
        create_position_record()  # DB non-empty
        resp = api.create_batch(create_batch_payload(name="denied"), security_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_rbac_analyst_cannot_set_clock(self, api, analyst_headers):
        """PRD §4: "| POST | `/_clock/set_current_utc` | Set the logical clock and
        sweep time-driven transitions | SecurityAdmin |"
        PRD §2.1: "Each operation is restricted to designated roles; an
        authenticated caller attempting an operation outside their role is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/rbac_analyst_cannot_set_clock
        """
        create_position_record()  # DB non-empty
        resp = api.set_clock({"to_iso8601": "2026-08-02T00:00:00Z"}, analyst_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestErrorCatalogAndEnvelope:
    def test_error_catalog_not_found_and_error_envelope(self, api):
        """PRD §2.9: "The not-found vocabulary is resource-specific:
        `ERR_DATA_FIELD_NOT_FOUND`, `ERR_POSITION_NOT_FOUND`,
        `ERR_WORKER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND` (including
        `target_row_id` references), `ERR_CHANGE_REQUEST_NOT_FOUND`,
        `ERR_BATCH_NOT_FOUND`, `ERR_BATCH_LINE_NOT_FOUND`,
        `ERR_INTEGRATION_EVENT_NOT_FOUND`, `ERR_DQ_RULE_NOT_FOUND`,
        `ERR_EXCEPTION_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, and
        `ERR_AUDIT_ENTRY_NOT_FOUND`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/errors/error_catalog_not_found_and_error_envelope
        """
        create_position_record()  # DB non-empty so 404s are not empty-DB artifacts

        checks = [
            (api.get_position(NON_EXISTENT_UUID, ANALYST), ApiErrorId.ERR_POSITION_NOT_FOUND),
            (api.get_worker(NON_EXISTENT_UUID, ANALYST), ApiErrorId.ERR_WORKER_NOT_FOUND),
            (api.get_data_field(NON_EXISTENT_UUID, STEWARD), ApiErrorId.ERR_DATA_FIELD_NOT_FOUND),
            (api.get_change_request(NON_EXISTENT_UUID, ANALYST), ApiErrorId.ERR_CHANGE_REQUEST_NOT_FOUND),
            (api.get_batch(NON_EXISTENT_UUID, ANALYST), ApiErrorId.ERR_BATCH_NOT_FOUND),
            (api.get_batch_line(NON_EXISTENT_UUID, ANALYST), ApiErrorId.ERR_BATCH_LINE_NOT_FOUND),
            (api.get_integration_event(NON_EXISTENT_UUID, OPERATOR), ApiErrorId.ERR_INTEGRATION_EVENT_NOT_FOUND),
            (api.patch_data_quality_rule(NON_EXISTENT_UUID, {"status": "DISABLED"}, STEWARD), ApiErrorId.ERR_DQ_RULE_NOT_FOUND),
            (api.resolve_exception_record(NON_EXISTENT_UUID, {"resolution_note": "x"}, STEWARD), ApiErrorId.ERR_EXCEPTION_NOT_FOUND),
            (api.approve_security_role_assignment(NON_EXISTENT_UUID, SECADMIN), ApiErrorId.ERR_GRANT_NOT_FOUND),
            (api.get_audit_entry(NON_EXISTENT_UUID, STEWARD), ApiErrorId.ERR_AUDIT_ENTRY_NOT_FOUND),
            (api.terminate_worker(NON_EXISTENT_UUID, {"termination_date": "2026-08-01"}, ANALYST), ApiErrorId.ERR_WORKER_NOT_FOUND),
        ]
        for resp, expected_error in checks:
            validate_error(resp, expected_error)
            assert_error_envelope(resp.json())


class TestEnvelopesAndConsistency:
    def test_list_workers_pagination_envelope(self, api, analyst_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it
        defaults to 10 when omitted, accepts a minimum of 1, and is clamped at a
        maximum of 100. The `offset` parameter skips a number of items from the
        start of the result set and defaults to 0. Unless otherwise specified,
        every list endpoint returns resources sorted by `created_at` in ascending
        order. The `meta` object of a list response carries the pagination fields
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_workers_pagination_envelope
        """
        pos = create_position_record(headcount_budget=9)
        for i, number in enumerate(("W901", "W902", "W903"), start=1):
            payload = create_worker_payload(
                legal_name=f"P{i}", worker_number=number, initial_position_id=pos["id"],
            )
            validate_success(api.create_worker(payload, analyst_headers), expected_status=201)

        page1, meta1 = validate_paginated(
            api.list_workers(analyst_headers, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_workers(analyst_headers, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_get_position_returns_envelope_wrapped_object(self, api, analyst_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC
        timestamp with three fractional digits."
        PRD §2.2: "The `response_type` is either \"object\" for a single resource
        or \"array\" for a list of resources."

        Design: Corner/endpoints/get_position_returns_envelope_wrapped_object
        """
        pos = create_position_record(title="Root", department="HQ", headcount_budget=3)

        resp = api.get_position(pos["id"], analyst_headers)
        body = resp.json()
        assert resp.status_code == 200
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

        data = validate_success(resp)
        assert data["id"] == pos["id"]
        assert data["status"] == "ACTIVE"

    def test_writes_visible_immediately_in_response(self, api, analyst_headers):
        """PRD §2.2: "The `data` field contains the resource object or an array of
        resource objects. For 2xx responses with no data, it contains an empty
        object. Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §2.4: "Every primary resource carries a standard set of system-managed
        properties. The `id` is a server-minted UUID with no type prefix.
        `created_at` is an ISO 8601 UTC timestamp with three fractional digits,
        fixed at creation. `updated_at` follows the same format and is refreshed
        on every mutation. `version` is an integer that increments on every
        mutation of the resource, including mutations driven by cascades and
        system sweeps, and it anchors the optimistic-concurrency rules of §2.7."

        Design: Corner/consistency_model/writes_visible_immediately_in_response
        """
        created = validate_success(
            api.create_position(create_position_payload(title="Root", department="HQ",
                                                        headcount_budget=3),
                                analyst_headers),
            expected_status=201,
        )
        assert created["status"] == "ACTIVE"
        assert created["version"] == 1

        reread = validate_success(api.get_position(created["id"], analyst_headers))
        assert reread["status"] == "ACTIVE"
        assert reread["version"] == 1
        assert reread["id"] == created["id"]


class TestAuditLogShape:
    def test_audit_entry_immutable_no_version_field(self, api):
        """PRD §2.4: "One entity deliberately breaks this pattern: the audit log
        is append-only. An audit entry carries only `id` and `created_at`;
        `updated_at` and `version` are absent, and entries are immutable once
        written."
        PRD §3.8: "A successful approval records `approved_by` as the approver's
        `X-User-ID`, writes an audit entry with action `GRANT_APPROVE`, and —
        when the clock date has already reached `valid_from` — provisions the
        grant immediately rather than leaving it waiting."

        Design: Corner/entities/audit_entry_immutable_no_version_field
        """
        grant = create_grant_record(
            "op-30", "HRIS_ANALYST", valid_from="2026-08-01", valid_until="2027-08-01",
        )
        from test_helpers import approve_grant_record
        approve_grant_record(grant["id"], approver_user_id="secadmin-1")

        resp = api.list_audit_entries(STEWARD)
        audits = get_success_data(resp)
        assert len(audits) == 1
        entry = audits[0]
        assert entry["action"] == "GRANT_APPROVE"
        assert_audit_entry(entry)
