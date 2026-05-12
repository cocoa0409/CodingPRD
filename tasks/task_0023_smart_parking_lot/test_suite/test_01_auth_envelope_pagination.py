"""Auth, RBAC, envelope, pagination, and existence checks (PRD §2.1–§2.7)."""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    build_user_headers,
    create_lot_payload,
    create_vehicle_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# §2.1 — Auth header presence
# ===========================================================================
class TestAuthHeaders:
    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: 'Missing or empty values yield ERR_MISSING_AUTH.'"""
        bad_headers = {"X-User-Role": "Operator"}
        res = api.create_lot(create_lot_payload(), bad_headers)
        validate_error(res, "ERR_MISSING_AUTH")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: 'Missing or empty values yield ERR_MISSING_AUTH.'"""
        bad_headers = {"X-User-ID": "operator-001"}
        res = api.create_lot(create_lot_payload(), bad_headers)
        validate_error(res, "ERR_MISSING_AUTH")

    def test_empty_user_id_value_rejected(self, api):
        """PRD §2.1: 'Missing or empty values yield ERR_MISSING_AUTH.'"""
        bad_headers = {"X-User-ID": "", "X-User-Role": "Operator"}
        res = api.create_lot(create_lot_payload(), bad_headers)
        validate_error(res, "ERR_MISSING_AUTH")

    def test_both_headers_missing_rejected(self, api):
        """PRD §2.1: 'Missing or empty values yield ERR_MISSING_AUTH.'"""
        res = api.create_lot(create_lot_payload(), {})
        validate_error(res, "ERR_MISSING_AUTH")


# ===========================================================================
# §2.1 — RBAC mismatch
# ===========================================================================
class TestRBAC:
    @pytest.mark.parametrize(
        "role",
        ["Driver", "GateSystem", "EnforcementOfficer",
         "ParkingPartner", "Auditor"],
    )
    def test_create_lot_requires_operator(self, api, role):
        """PRD §2.1: 'a mismatch yields ERR_FORBIDDEN.'
        PRD §4: 'POST /lots ... Authorized Role(s): Operator'."""
        headers = build_user_headers(f"some-{role}", role)
        res = api.create_lot(create_lot_payload(), headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_create_zone_requires_operator(self, api, gate_headers):
        """PRD §4: 'POST /lots/{lot_id}/zones ... Authorized Role(s): Operator'."""
        from test_helpers import create_zone_payload
        res = api.create_zone(NON_EXISTENT_UUID, create_zone_payload(), gate_headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_issue_violation_requires_enforcement_officer(self, api, gate_headers):
        """PRD §4: 'POST /violations ... Authorized Role(s): EnforcementOfficer'."""
        from test_helpers import create_violation_payload
        bad_payload = create_violation_payload(
            lot_id=NON_EXISTENT_UUID,
            vehicle_id=NON_EXISTENT_UUID,
            violation_type="OVERSTAY",
            space_id=NON_EXISTENT_UUID,
            detected_at="2026-01-01T10:00:00.000Z",
        )
        res = api.create_violation(bad_payload, gate_headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_audit_logs_requires_auditor_or_operator(self, api):
        """PRD §4: 'GET /audit-logs ... Authorized Role(s): Auditor, Operator'."""
        headers = build_user_headers("driver-1", "Driver")
        res = api.list_audit_logs(headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_settlement_run_requires_operator(self, api, partner_headers):
        """PRD §4: 'POST /lots/{lot_id}/settlement/run ... Authorized Role(s): Operator'."""
        res = api.run_settlement(NON_EXISTENT_UUID, {}, partner_headers)
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.6 — Path existence (left-to-right resolution)
# ===========================================================================
class TestPathExistence:
    def test_get_unknown_lot_returns_not_found(self, api, operator_headers):
        """PRD §2.6: 'The first identifier that fails to resolve causes the
        request to fail with ERR_NOT_FOUND before any downstream validation runs.'"""
        res = api.get_lot(NON_EXISTENT_UUID, operator_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_zone_under_unknown_lot_returns_not_found(self, api, operator_headers):
        """PRD §2.6: 'The first identifier that fails to resolve causes the
        request to fail with ERR_NOT_FOUND before any downstream validation runs.'"""
        res = api.get_space(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            operator_headers,
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_unknown_vehicle_returns_not_found(self, api, operator_headers):
        """PRD §2.6: unresolved path identifier yields ERR_NOT_FOUND."""
        res = api.get_vehicle(NON_EXISTENT_UUID, operator_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_unknown_card_returns_not_found(self, api, operator_headers):
        """PRD §2.6: unresolved path identifier yields ERR_NOT_FOUND."""
        res = api.get_card(NON_EXISTENT_UUID, operator_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_unknown_session_returns_not_found(self, api, operator_headers):
        """PRD §2.6: unresolved path identifier yields ERR_NOT_FOUND."""
        res = api.get_session(NON_EXISTENT_UUID, operator_headers)
        validate_error(res, "ERR_NOT_FOUND")


# ===========================================================================
# §2.6 — Body foreign key existence
# ===========================================================================
class TestBodyForeignKeyExistence:
    def test_bind_with_unknown_vehicle_id_in_body(self, api, operator_headers):
        """PRD §2.6: 'Foreign-key identifiers carried inside the request body
        ... are likewise resolved after path validation; an unresolvable body
        reference yields ERR_NOT_FOUND as well.'"""
        from test_helpers import create_card, bind_card_payload
        card = create_card()
        res = api.bind_card(
            card["id"],
            bind_card_payload(vehicle_id=NON_EXISTENT_UUID),
            operator_headers,
        )
        validate_error(res, "ERR_NOT_FOUND")


# ===========================================================================
# §2.2 — Response envelope shape
# ===========================================================================
class TestResponseEnvelope:
    def test_success_envelope_has_required_meta(self, api, operator_headers):
        """PRD §2.2: 'The api_request_id is a server-generated unique identifier
        for the request that starts with req_.'"""
        res = api.create_lot(create_lot_payload(), operator_headers)
        body = res.json()
        assert body["response_type"] in ("object", "array")
        meta = body["meta"]
        assert isinstance(meta["api_request_id"], str)
        assert meta["api_request_id"].startswith("req_"), (
            "PRD §2.2: api_request_id must start with 'req_'"
        )
        assert isinstance(meta["api_request_timestamp"], str)

    def test_error_envelope_carries_error_id_and_message(self, api):
        """PRD §2.2: 'The error_id is a unique, machine-readable string
        that identifies the specific error.'"""
        res = api.create_lot(create_lot_payload(), {})  # missing auth
        body = res.json()
        assert body["response_type"] == "error"
        data = body["data"]
        assert isinstance(data["error_id"], str) and len(data["error_id"]) > 0
        assert isinstance(data["message"], str) and len(data["message"]) > 0


# ===========================================================================
# §2.3 — Pagination bounds
# ===========================================================================
class TestPaginationBounds:
    def test_limit_above_max_rejected(self, api, auditor_headers):
        """PRD §2.3: 'permitted values are integers from 1 to 100 inclusive.
        Any value outside these bounds is rejected with ERR_BAD_REQUEST.'"""
        res = api.list_audit_logs(auditor_headers, params={"limit": 101})
        validate_error(res, "ERR_BAD_REQUEST")

    def test_limit_below_min_rejected(self, api, auditor_headers):
        """PRD §2.3: 'permitted values are integers from 1 to 100 inclusive.
        Any value outside these bounds is rejected with ERR_BAD_REQUEST.'"""
        res = api.list_audit_logs(auditor_headers, params={"limit": 0})
        validate_error(res, "ERR_BAD_REQUEST")

    def test_negative_offset_rejected(self, api, auditor_headers):
        """PRD §2.3: 'The offset parameter defaults to 0 and must be a
        non-negative integer. Any value outside these bounds is rejected
        with ERR_BAD_REQUEST.'"""
        res = api.list_audit_logs(auditor_headers, params={"offset": -1})
        validate_error(res, "ERR_BAD_REQUEST")
