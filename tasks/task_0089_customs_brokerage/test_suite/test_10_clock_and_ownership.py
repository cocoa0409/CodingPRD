"""Clock-driven auto-transitions and ClientUser entity-backed ownership
(PRD §2.1, §2.12, §3.2, §3.6)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    action_with_version_payload,
    activate_agreement,
    advance_clock_to,
    api_client,
    attach_core_docs,
    create_agreement,
    create_client,
    locate_settlement_for_declaration,
    make_client_user_headers,
    reset_clock_to_epoch,
    setup_active_agreement,
    setup_declaration_in_queried,
    setup_declaration_released_via_emit,
    sign_agreement_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# §2.12 — clock-advance triggers auto-rejection of queried declarations
# ===========================================================================
class TestAutoRejectQueriedAfterDeadline:

    def test_clock_past_query_due_at_auto_rejects(self, api, broker_ops_headers):
        """PRD §3.6: "If the clock advances past query_due_at without a
        query response, the system automatically transitions the
        declaration from QUERIED to REJECTED, sets rejection_reason_code
        to OTHER, and creates a RejectionRecord exactly as it would for
        an explicit REJECT response."

        Claim: clock advanced past query_due_at → declaration auto-moves
        to REJECTED with rejection_reason_code=OTHER.
        """
        reset_clock_to_epoch()
        ctx = setup_declaration_in_queried()
        filing = ctx["filing"]
        dec = ctx["declaration"]
        due_dt = datetime.fromisoformat(filing["query_due_at"].replace("Z", "+00:00"))
        advance_clock_to(due_dt + timedelta(seconds=1))
        # Refresh declaration.
        refreshed = validate_success(api.get_declaration(
            dec["id"], broker_ops_headers,
        ))
        assert refreshed["status"] == "REJECTED"
        assert refreshed["rejection_reason_code"] == "OTHER"


# ===========================================================================
# §2.1 — ClientUser entity-backed ownership: cross-tenant denied
# ===========================================================================
class TestClientUserOwnership:

    def test_client_user_can_read_own_client(self, api):
        """PRD §2.1: "A ClientUser may read only their own ClientCompany,
        list only declarations belonging to their own agreements, and
        read only settlements belonging to those declarations."

        Claim: GET /customs/clients/{own_id} with
        X-User-ID=own_client.id and X-User-Role=ClientUser → 200 OK.
        """
        client = create_client()
        resp = api.get_client(
            client["id"], make_client_user_headers(client["id"]),
        )
        validate_success(resp)

    def test_client_user_cannot_read_other_client(self, api):
        """PRD §2.1: "Cross-tenant access by a ClientUser is rejected
        with ERR_FORBIDDEN."

        Claim: GET /customs/clients/{other_id} with
        X-User-ID=our_client.id and X-User-Role=ClientUser →
        ERR_FORBIDDEN.
        """
        ours = create_client()
        theirs = create_client()
        resp = api.get_client(
            theirs["id"], make_client_user_headers(ours["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_client_user_cannot_sign_other_clients_agreement(self, api,
                                                              broker_ops_headers):
        """PRD §2.1: "Cross-tenant access by a ClientUser is rejected
        with ERR_FORBIDDEN."
        PRD §4: POST /customs/agreements/{id}/sign is restricted to ClientUser.

        Claim: another client's user attempting to sign → ERR_FORBIDDEN.
        """
        # Owner of the agreement.
        owner = create_client()
        agreement = create_agreement(owner["id"])
        # Request signature.
        request_resp = api.request_signature(
            agreement["id"],
            action_with_version_payload(version=agreement["version"]),
            broker_ops_headers,
        )
        agreement = validate_success(request_resp)
        # Other client tries to sign.
        other = create_client()
        resp = api.sign_agreement(
            agreement["id"],
            sign_agreement_payload(
                signature_token=agreement["signature_token"],
                version=agreement["version"],
            ),
            make_client_user_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# §3.6 — Filing.is_amendment flag
# ===========================================================================
class TestIsAmendmentFlag:

    def test_first_file_has_is_amendment_false(self, api):
        """PRD §3.6: "and the is_amendment flag set to true exactly when
        the declaration's amendment_count is greater than zero."

        Claim: the first filing (amendment_count=0) has is_amendment=false.
        """
        from test_helpers import setup_declaration_in_filed
        ctx = setup_declaration_in_filed(match_manifest=False)
        filing = ctx["filing"]
        assert filing["is_amendment"] is False


# ===========================================================================
# §3.3 — PATCH on a non-mutable state
# ===========================================================================
class TestDeclarationPatchStateGate:

    def test_patch_in_filed_state_rejected(self, api, declaration_officer_headers):
        """PRD §3.3: "A patch action on the declaration is restricted to
        the DeclarationOfficer role and is accepted only while the
        declaration is in DRAFT, DOCS_PENDING, or AMENDING."

        Claim: PATCH on a FILED declaration → ERR_INVALID_STATE.
        """
        from test_helpers import setup_declaration_in_filed
        ctx = setup_declaration_in_filed(match_manifest=False)
        dec = ctx["declaration"]
        from test_helpers import update_declaration_payload
        resp = api.update_declaration(
            dec["id"],
            update_declaration_payload(
                version=dec["version"], declared_value_amount=2000.00,
            ),
            declaration_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
