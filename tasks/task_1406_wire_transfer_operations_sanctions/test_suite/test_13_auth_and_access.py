"""Cross-cutting access rules: header presence, the role-before-existence
order, unknown-id 404s, and exclusive administrative capabilities."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_callback_pending_wire,
    create_wire,
    record_callback,
    setup_wire_room,
    validate_error,
    validate_paginated,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["wire_ops_admin_headers"]
OPERATOR = TEST_USERS["wire_operator_headers"]


class TestHeaderPresence:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "Every request to the API must carry two HTTP headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`, naming
        their operational capacity. A request missing either header, or
        carrying an empty value in either, is rejected with
        `ERR_MISSING_AUTH`."

        A request with no auth headers is rejected and creates nothing.

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        resp = api.create_customer(
            {"legal_name": "No Auth", "risk_rating": "LOW"}, None)
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH)

        listed, _meta = validate_paginated(api.list_customers(ADMIN))
        assert listed == [], f"no customer may be created, got {len(listed)}"


class TestExistenceChecks:
    def test_get_nonexistent_wire_returns_not_found(self, api):
        """PRD §2.8: "(3) existence of every path identifier, validated
        left-to-right, and of every body-supplied foreign reference such as
        `ordering_account_id`, `beneficiary_id`, `wire_id`, or
        `investigation_id` — `ERR_NOT_FOUND`"

        Reading a well-formed but unknown wire id is ERR_NOT_FOUND (404).

        Design: Corner/entities/get_nonexistent_wire_returns_not_found
        """
        resp = api.get_wire(NON_EXISTENT_UUID, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_role_forbidden_precedes_not_found(self, api):
        """PRD §2.8: "The order, from first to last, is: (1) header presence —
        `ERR_MISSING_AUTH`; (2) role authorization, including the
        disposition-tier split on sanctions hits — `ERR_FORBIDDEN_ROLE`; (3)
        existence of every path identifier, validated left-to-right, and of
        every body-supplied foreign reference such as `ordering_account_id`,
        `beneficiary_id`, `wire_id`, or `investigation_id` — `ERR_NOT_FOUND`"

        A WireOperator calling the approver-only endpoint against a wire id
        that does not exist is rejected for the role, proving authorization
        runs before existence.

        Design: Corner/validations/role_forbidden_precedes_not_found
        """
        room = setup_wire_room()
        wire = create_wire(room["account"]["id"], room["beneficiary"]["id"],
                           100000, purpose="priority order probe")

        resp = api.approve_wire(
            NON_EXISTENT_UUID, {"expected_wire_version": wire["version"]},
            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestExclusiveCapabilities:
    def test_clock_set_forbidden_for_operator(self, api):
        """PRD §2.5: "At startup the logical clock reads exactly
        2026-08-01T00:00:00Z. A `WireOpsAdmin` may advance it by supplying a
        target instant via `to_iso8601`; the clock is then pinned at that
        instant and never falls back to wall-clock time. Test-driving the
        clock is an administrator-only capability and returns the current
        logical instant as `current_utc`."

        A WireOperator's attempt to move time is forbidden, and the clock
        provably stayed at the startup default: a callback case opened
        afterwards still records CONFIRMED (had the clock jumped to December,
        its four-hour window would already have lapsed).

        Design: Corner/rbac/clock_set_forbidden_for_operator
        """
        resp = api.set_clock("2026-12-31T00:00:00Z", OPERATOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        room = setup_wire_room(
            account_overrides={"daily_outgoing_limit_cents": 500000000})
        wire, case = create_callback_pending_wire(
            room["account"]["id"], room["beneficiary"]["id"],
            amount_cents=150000000)
        recorded = record_callback(case["id"], outcome="CONFIRMED")
        assert recorded["status"] == "CONFIRMED", (
            "the window is still open, so the rejected clock set never moved "
            "the logical clock off its startup default")

    def test_audit_logs_forbidden_for_operator(self, api):
        """PRD §3.11: "The audit log itself is readable by a `WireOpsAdmin`,
        an `Auditor`, or a `ComplianceOfficer` only."
        PRD §2.1: "A request whose role is not permitted for the target
        endpoint — including disposition-tier mismatches on sanctions hits,
        where the permitted role depends on the hit's current state — is
        rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/audit_logs_forbidden_for_operator
        """
        resp = api.list_audit_logs(OPERATOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
