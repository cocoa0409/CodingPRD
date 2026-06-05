"""Corner section: rbac — the role-denial surface."""
from test_helpers import (
    validate_error,
    setup_actors,
    setup_active_agreement,
    create_wire,
    callback_verify_wire,
    create_title_search_payload,
    api_client,
)


class TestComplianceOfficerCannotCreateTitleSearch:
    def test_compliance_officer_calling_title_search_create_returns_403(self, api):
        """PRD §2.1: "A request whose role is recognised but not permitted on the called endpoint is rejected with ``ERR_FORBIDDEN`` (HTTP 403)."
        PRD §4: lists POST /title-searches as restricted to TitleAgent.

        Design: Corner/rbac/rbac_compliance_officer_cannot_create_title_search
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        base = setup_active_agreement(actors=actors)
        res = api.create_title_search(
            create_title_search_payload(base["agreement"]["id"]),
            actors["co"],  # ComplianceOfficer — not the title agent.
        )
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)


class TestEscrowOfficerCannotLockWire:
    def test_escrow_officer_locking_wire_returns_403(self, api):
        """PRD §2.1: "A request whose role is recognised but not permitted on the called endpoint is rejected with ``ERR_FORBIDDEN`` (HTTP 403)."
        PRD §4: lists POST /wire-instructions/{id}/lock as restricted to ComplianceOfficer.
        PRD §2.6: "The lock that follows must be performed by a different officer. A ``ComplianceOfficer`` locking the wire compares their ``X-User-ID`` to the stored ``callback_verifier_id``"

        Design: Corner/rbac/rbac_escrow_officer_cannot_lock_wire_segregation
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        base = setup_active_agreement(actors=actors)
        wire = create_wire(
            actors, base["agreement"]["id"], party="BUYER",
            beneficiary_account_last4="1111",
        )
        # Verify the wire so it's in VERIFIED state (callback-verify is
        # EscrowOfficer's job per PRD §4).
        callback_verify_wire(
            actors, wire["id"],
            verifier_id=actors["eo_id"],
            voice_callback_reference="VC-RB2",
            as_user="eo",
        )
        # Now attempt the lock as EscrowOfficer (forbidden — CO-only per §4).
        res = api.lock_wire_instruction(wire["id"], actors["eo"])
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)
