"""Auth headers, RBAC, and path-existence checks (PRD §2.1, §2.5)."""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    validate_error,
    validate_success,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    create_insurer,
    create_insurer_payload,
    build_user_headers,
)


# ---------------------------------------------------------------------------
# Missing or empty user-context headers (PRD §2.1)
# ---------------------------------------------------------------------------

class TestUserContextHeaders:
    def test_missing_user_id_returns_400(self, api):
        """PRD §2.1: "If either header is missing or empty the request is
        rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (HTTP 400)."

        Claim: GET without X-User-ID is rejected with the named error.
        """
        # Build a header dict with only X-User-Role.
        headers = {"X-User-Role": "ClaimsAdmin"}
        resp = api.create_insurer(create_insurer_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_missing_user_role_returns_400(self, api):
        """PRD §2.1: "If either header is missing or empty the request is
        rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (HTTP 400)."

        Claim: POST without X-User-Role is rejected with the named error.
        """
        headers = {"X-User-ID": "anyone"}
        resp = api.create_insurer(create_insurer_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_empty_user_id_returns_400(self, api):
        """PRD §2.1: "If either header is missing or empty the request is
        rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (HTTP 400).

        Claim: empty X-User-ID is treated as missing.
        """
        headers = {"X-User-ID": "", "X-User-Role": "ClaimsAdmin"}
        resp = api.create_insurer(create_insurer_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


# ---------------------------------------------------------------------------
# RBAC — wrong role rejected (PRD §2.1)
# ---------------------------------------------------------------------------

class TestRbacRoleEnforcement:
    def test_create_insurer_requires_claims_admin(self, api):
        """PRD §2.1: "If the role is well-formed but does not have authority
        to invoke the endpoint, the request is rejected with
        ERR_FORBIDDEN_FOR_ROLE (HTTP 403)."

        Claim: POST /insurers by an Auditor is forbidden.
        """
        resp = api.create_insurer(
            create_insurer_payload(),
            TEST_USERS["auditor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)

    def test_suspend_policy_requires_policy_admin(self, api):
        """PRD §2.1: "ERR_FORBIDDEN_FOR_ROLE (HTTP 403)" for unauthorized roles.

        Claim: a PayoutOperator cannot suspend a policy.
        """
        from test_helpers import setup_basic_insurer_with_policy
        insurer, policy = setup_basic_insurer_with_policy()
        resp = api.suspend_policy(
            insurer["id"], policy["id"],
            {"reason": "test"},
            TEST_USERS["payout_operator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)

    def test_advance_clock_requires_claims_admin(self, api):
        """PRD §2.6: "advance only when a ClaimsAdmin calls the test-clock
        advance capability with either delta_ms ... or to_epoch_ms."

        Claim: a PolicyAdmin cannot advance the clock.
        """
        insurer = create_insurer()
        resp = api.advance_clock(
            insurer["id"], {"delta_ms": 100},
            TEST_USERS["policy_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)

    def test_archive_flight_requires_claims_admin(self, api):
        """PRD §3.2: "A finalised flight may be archived by a ClaimsAdmin (or
        by the system sweep, when ...)."

        Claim: PolicyAdmin cannot archive a flight directly.
        """
        from test_helpers import setup_flight_with_delay
        insurer = create_insurer()
        flight = setup_flight_with_delay(insurer["id"])
        resp = api.archive_flight(
            insurer["id"], flight["id"], TEST_USERS["policy_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)

    def test_reverse_claim_requires_claims_admin(self, api):
        """PRD §3.9: "A ClaimsAdmin may reverse a PAID claim by advancing
        payout_status from PAID to REVERSED (with X-User-Role of
        ClaimsAdmin)."

        Claim: a PolicyAdmin cannot invoke /reverse.
        """
        from test_helpers import setup_claim_paid
        insurer, policy, flight, ticket, claim, batch, *_ = setup_claim_paid()
        resp = api.reverse_claim(
            insurer["id"], claim["id"], TEST_USERS["policy_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


# ---------------------------------------------------------------------------
# Path-parameter existence (PRD §2.5)
# ---------------------------------------------------------------------------

class TestPathExistence:
    def test_get_insurer_not_found(self, api):
        """PRD §2.5: "Path parameters are validated strictly left-to-right
        ... The first parameter in the chain that fails to resolve produces
        ERR_NOT_FOUND (HTTP 404)."

        Claim: GET /insurers/{nonexistent_id} returns ERR_NOT_FOUND.
        """
        resp = api.get_insurer(NON_EXISTENT_UUID, TEST_USERS["claims_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_policy_under_unknown_insurer(self, api):
        """PRD §2.5: "the insurer must exist before the policy is checked".

        Claim: GET /insurers/{bogus}/policies/{bogus} returns ERR_NOT_FOUND
        (the insurer-existence check fails first).
        """
        resp = api.get_policy(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            TEST_USERS["claims_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_unknown_policy_in_real_insurer(self, api):
        """PRD §2.5: "The first parameter in the chain that fails to resolve
        produces ERR_NOT_FOUND (HTTP 404)."

        Claim: with insurer existing but policy id missing, returns
        ERR_NOT_FOUND.
        """
        insurer = create_insurer()
        resp = api.get_policy(
            insurer["id"], NON_EXISTENT_UUID,
            TEST_USERS["claims_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_create_ticket_with_unknown_flight(self, api):
        """PRD §3.3: "When a referenced flight does not exist within the
        insurer, the ingest is rejected with ERR_FLIGHT_NOT_FOUND (HTTP
        404)."

        Claim: POST /tickets with bogus flight_id returns ERR_FLIGHT_NOT_FOUND.
        """
        from test_helpers import setup_basic_insurer_with_policy, create_ticket_payload
        insurer, policy = setup_basic_insurer_with_policy()
        resp = api.create_ticket(
            insurer["id"],
            create_ticket_payload(
                flight_id=NON_EXISTENT_UUID,
                passenger_doc_id=policy["policy_holder_doc_id"],
            ),
            TEST_USERS["policy_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FLIGHT_NOT_FOUND.value)

    def test_change_ticket_unknown_flight(self, api):
        """PRD §3.3: "this fails with ERR_FLIGHT_NOT_FOUND if the new flight
        cannot be resolved".

        Claim: change a ticket to a non-existent flight_id → ERR_FLIGHT_NOT_FOUND.
        """
        from test_helpers import setup_ticket_attached
        ctx = setup_ticket_attached()
        resp = api.change_ticket(
            ctx["insurer"]["id"], ctx["ticket"]["id"],
            {"flight_id": NON_EXISTENT_UUID},
            TEST_USERS["policy_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FLIGHT_NOT_FOUND.value)
