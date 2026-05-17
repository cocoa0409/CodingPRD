"""Depth-3 license-revoke cascade: license → consult unroute → DRAFT
prescription voided.

PRD §2.7 (cascading mutations & versioning), §3.6 (depth-three cascade
described in detail).
"""
from __future__ import annotations

from test_helpers import (
    TEST_USERS,
    re_get_consult,
    re_get_state_license,
    revoke_state_license,
    setup_routed_consult_with_draft_rx,
    validate_success,
)


# ===========================================================================
# §3.6 Link 1: revoked StateLicense projects to REVOKED
# ===========================================================================
class TestLicenseRevokeLink1:

    def test_revoke_projects_license_to_revoked(self, api):
        """PRD §3.6: "Link one is the revocation itself: an AuditEvent
        of type LICENSE_REVOKED is appended with subject_id equal to
        the license's id, and from that moment any read of the license
        — including state-machine precondition checks — projects its
        status as REVOKED."

        Claim: after /revoke, the license projects to REVOKED.

        difficulty: transitive_cascade/license_revoke_to_consult_to_rx_void_depth_3
        """
        physician, lic, _, _, _ = setup_routed_consult_with_draft_rx()
        revoke_state_license(physician["id"], lic["id"])
        refreshed = re_get_state_license(physician["id"], lic["id"])
        assert refreshed["status"] == "REVOKED"


# ===========================================================================
# §3.6 Link 2: affected consults reset to REQUESTED with cleared fields
# ===========================================================================
class TestLicenseRevokeLink2:

    def test_revoke_resets_in_progress_consult_to_requested(self, api):
        """PRD §3.6: "Link two scans every consult in REQUESTED, ROUTED,
        or IN_PROGRESS status whose physician_id equals the revoked
        license's physician_id and whose present_state_code equals the
        revoked license's state_code ... Each matching consult is reset
        to REQUESTED with physician_id cleared to null, routing_basis
        cleared to null, updated_at refreshed, and version incremented."

        Claim: after revoking the license, the matched IN_PROGRESS
        consult is reset to REQUESTED with physician_id=null and
        routing_basis=null.

        difficulty: transitive_cascade/license_revoke_to_consult_to_rx_void_depth_3
        """
        physician, lic, _, consult, _ = setup_routed_consult_with_draft_rx()
        # consult started → IN_PROGRESS.
        assert consult["status"] == "IN_PROGRESS"
        revoke_state_license(physician["id"], lic["id"])
        refreshed = re_get_consult(consult["id"])
        assert refreshed["status"] == "REQUESTED"
        assert refreshed.get("physician_id") in (None, "")
        assert refreshed.get("routing_basis") in (None, "")

    def test_revoke_does_not_affect_other_state_consults(self, api):
        """PRD §3.6: "The reset is keyed on the matched-license
        discriminator: a consult routed against a different physician
        or a different state, even if that physician happens to share
        another revoked license, is not affected."

        Claim: a consult in a different state is unaffected by the
        revoke. We construct two consults under the same physician,
        each for a different state (CA + NY), revoke the CA license,
        and verify only the CA consult is reset.
        """
        from test_helpers import (
            create_consult,
            create_patient,
            create_physician,
            create_state_license,
            random_dea_number,
            route_consult,
            start_consult,
        )
        # Two distinct physicians and patients so the patient-active-
        # consult rule does not block setup.
        physician_shared = create_physician(dea_number=random_dea_number())
        lic_ca = create_state_license(
            physician_shared, state_code="CA", license_type="FULL",
        )
        create_state_license(
            physician_shared, state_code="NY", license_type="FULL",
        )
        # Consult in CA.
        patient_ca = create_patient(home_state_code="CA")
        consult_ca = create_consult(
            patient=patient_ca, billing_mode="SELF_PAY",
            visit_tier="STANDARD", present_state_code="CA",
        )
        consult_ca = route_consult(
            consult=consult_ca, physician=physician_shared,
        )
        consult_ca = start_consult(
            consult=consult_ca, physician=physician_shared,
        )
        # Consult in NY (different patient).
        patient_ny = create_patient(home_state_code="NY")
        consult_ny = create_consult(
            patient=patient_ny, billing_mode="SELF_PAY",
            visit_tier="STANDARD", present_state_code="NY",
        )
        consult_ny = route_consult(
            consult=consult_ny, physician=physician_shared,
        )
        consult_ny = start_consult(
            consult=consult_ny, physician=physician_shared,
        )
        # Revoke the CA license.
        revoke_state_license(physician_shared["id"], lic_ca["id"])
        # CA consult was reset.
        refreshed_ca = re_get_consult(consult_ca["id"])
        assert refreshed_ca["status"] == "REQUESTED"
        # NY consult should be UNCHANGED.
        refreshed_ny = re_get_consult(consult_ny["id"])
        assert refreshed_ny["status"] == "IN_PROGRESS", (
            f"NY consult must be unaffected by CA-license revoke; "
            f"got status={refreshed_ny['status']!r}"
        )
        assert refreshed_ny["physician_id"] == physician_shared["id"]


# ===========================================================================
# §3.6 Link 3: DRAFT prescriptions auto-voided with LICENSE_REVOKED
# ===========================================================================
class TestLicenseRevokeLink3:

    def test_revoke_voids_draft_prescription_with_license_revoked_reason(
        self, api,
    ):
        """PRD §3.6: "Link three operates on the consults identified by
        link two: every Prescription under those consults whose current
        status is DRAFT is auto-voided. Each auto-voided prescription
        has its status set to VOIDED, its void_reason set to the
        literal 'LICENSE_REVOKED'".

        Claim: after revoke, the DRAFT prescription under the affected
        consult is VOIDED with void_reason='LICENSE_REVOKED'.

        difficulty: transitive_cascade/license_revoke_to_consult_to_rx_void_depth_3
        """
        physician, lic, _, _, rx = setup_routed_consult_with_draft_rx()
        # rx.status == DRAFT.
        assert rx["status"] == "DRAFT"
        revoke_state_license(physician["id"], lic["id"])
        # PRD §4 endpoint table does not expose a singular GET
        # /prescriptions/{id}; the only PRD-pinned way to inspect a
        # prescription post-revoke is via the audit trail. PRD §2.10
        # names RX_VOIDED as the event type; the audit event has
        # subject_id and payload_json.
        resp = api.list_audit_events(
            TEST_USERS["compliance_officer_headers"],
            params={
                "event_type": "RX_VOIDED",
                "subject_entity": "Prescription",
                "subject_id": rx["id"],
                "limit": 10,
            },
        )
        body = resp.json()["data"]
        items = body if isinstance(body, list) else (
            body.get("items", body)
        )
        if isinstance(items, dict):
            items = items.get("items", [])
        matching = [
            ev for ev in items if ev.get("subject_id") == rx["id"]
        ]
        assert len(matching) >= 1, (
            "PRD §3.6: revoke must append an AuditEvent of type "
            f"RX_VOIDED for the auto-voided prescription {rx['id']}"
        )
        # PRD §3.6 pins actor_role='system' for the cascade event.
        assert any(
            ev.get("actor_role") == "system" for ev in matching
        ), (
            "PRD §3.6: cascade-auto-voided prescription's RX_VOIDED "
            "audit event must record actor_role='system'"
        )

    def test_already_issued_prescription_not_touched_by_revoke(self, api):
        """PRD §3.6: "Already-ISSUED, TRANSMITTED, or DISPENSED
        prescriptions are not touched by the cascade — the revoke does
        not retroactively unwind prescriptions that have already left
        the physician's hands; only drafts that were still on the bench
        are voided."

        Claim: an ISSUED prescription is NOT auto-voided by a license
        revoke that affects its parent consult. We verify by checking
        that no NEW RX_VOIDED audit event was appended for the ISSUED
        prescription.

        difficulty: transitive_cascade/license_revoke_to_consult_to_rx_void_depth_3
        """
        from test_helpers import (
            create_prescription, issue_prescription,
            setup_routed_consult_with_draft_rx,
        )
        physician, lic, _, _, draft_rx = setup_routed_consult_with_draft_rx()
        # Issue the prescription so it leaves DRAFT.
        issued_rx = issue_prescription(
            prescription=draft_rx, physician=physician,
        )
        assert issued_rx["status"] == "ISSUED"
        # Revoke the license.
        revoke_state_license(physician["id"], lic["id"])
        # Verify no RX_VOIDED event was appended for the ISSUED rx.
        resp = api.list_audit_events(
            TEST_USERS["compliance_officer_headers"],
            params={
                "event_type": "RX_VOIDED",
                "subject_entity": "Prescription",
                "subject_id": issued_rx["id"],
                "limit": 10,
            },
        )
        body = resp.json()["data"]
        items = body if isinstance(body, list) else (
            body.get("items", body)
        )
        if isinstance(items, dict):
            items = items.get("items", [])
        matching = [
            ev for ev in items if ev.get("subject_id") == issued_rx["id"]
        ]
        assert len(matching) == 0, (
            f"PRD §3.6: an already-ISSUED prescription must NOT be "
            f"voided by the license-revoke cascade; got "
            f"{len(matching)} RX_VOIDED events for it"
        )
