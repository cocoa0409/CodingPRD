"""Travel-nurse credential packets: materialized checklist, evidence flow, waiver
rules, readiness score, approval path, and the item-invalidation cascade
(PRD §3.4, §3.7)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_credential_packet_payload,
    create_nurse,
    create_packet,
    create_requirement,
    create_unit,
    fill_packet_items,
    get_nurse,
    get_packet,
    get_packet_item,
    make_nurse_headers,
    packet_items_by_type,
    set_clock,
    setup_approved_packet,
    setup_credentialed_nurse,
    setup_submitted_packet,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client, TEST_USERS

SPEC1 = TEST_USERS["specialist_1"]
SPEC2 = TEST_USERS["specialist_2"]
CO1 = TEST_USERS["compliance_1"]


class TestReadinessScoreCriticalCap:
    """Difficulty instance: packet_readiness_score_critical_cap — the weighted score
    with status-dependent credits and the 0.49 critical cap keyed on item state."""

    def _setup_tessa_capped_packet(self):
        set_clock()
        req = create_requirement(code="ANNUAL_SKILLS", name="Annual Skills",
                                 validity_months=12, window_mode="ROLLING",
                                 mandatory=True,
                                 applies_to=["STAFF", "TRAVEL", "PER_DIEM"])
        unit = create_unit(name="ICU", required_cert_types=["ACLS"])
        ctx = setup_credentialed_nurse(
            full_name="Tessa Cap", email="tessa.cap@x.com",
            employment_type="TRAVEL", requirement=req,
        )
        nurse = ctx["nurse"]
        packet = create_packet(nurse["id"], unit["id"])
        items = fill_packet_items(
            packet["id"], nurse["id"],
            verify_types=["LICENSE_VERIFICATION", "BLS", "COMPETENCY_ANNUAL"],
            waive_types=["ATTESTATION"],
            skip_types=["ACLS"],
        )
        return nurse, packet, items

    def test_critical_missing_item_clamps_score(self):
        """PRD §3.7: "The raw score is the sum of each item's weight times its credit,
        divided by the sum of the weights, rounded half up to 4 decimals. A critical
        cap then applies: while any critical item stands `MISSING` or `INVALIDATED`,
        the score is the smaller of the raw value and 0.49."

        Design: Difficulty/combinatorial_formula/packet_readiness_score_critical_cap
        """
        _nurse, packet, _items = self._setup_tessa_capped_packet()
        data = get_packet(packet["id"])
        # raw = (40*1 + 20*1 + 20*0 + 15*1 + 5*0.5) / 100 = 0.775; cap -> 0.49
        assert data["readiness_score"] == pytest.approx(0.49, abs=0.0001), (
            f"critical ACLS MISSING clamps 0.775 to 0.49; got {data['readiness_score']}"
        )

    def test_critical_cap_keyed_on_item_state(self):
        """PRD §3.7: "A `VERIFIED` item earns full credit, `WAIVED` earns half credit,
        `SUBMITTED` earns a quarter credit, and `MISSING` or `INVALIDATED` earns
        nothing."
        PRD §3.7: "...each carries a `critical` flag — true for license verification,
        BLS, the unit-required ACLS, and the annual competency item, false for
        attestation — and a scoring `weight`: 40 for license verification, 20 each for
        BLS and ACLS, 15 for the annual competency item, and 5 for attestation."

        Design: Difficulty/combinatorial_formula/packet_readiness_score_critical_cap
        """
        _nurse, packet, items = self._setup_tessa_capped_packet()
        acls = get_packet_item(items["ACLS"]["id"])
        assert acls["status"] == "MISSING"
        assert acls["critical"] is True
        assert acls["weight"] == 20
        att = get_packet_item(items["ATTESTATION"]["id"])
        assert att["status"] == "WAIVED" and att["critical"] is False
        lv = get_packet_item(items["LICENSE_VERIFICATION"]["id"])
        assert lv["status"] == "VERIFIED" and lv["weight"] == 40

        data = get_packet(packet["id"])
        assert data["readiness_score"] == pytest.approx(0.49, abs=0.0001)


class TestPacketStateRules:
    def test_packet_approve_from_draft_rejected(self):
        """PRD §3.7: "From `UNDER_REVIEW`, approval requires strict completeness —
        every item `VERIFIED` or `WAIVED`, else `ERR_PACKET_ITEMS_INCOMPLETE` — plus a
        nurse who is `ACTIVE` (`ERR_INVALID_NURSE_STATE`) and `CLEAR`
        (`ERR_NURSE_NOT_CLEAR`); approval stamps `reviewed_by_user_id`."
        PRD §2.9: "7. **State validity** — the target entity must stand in a valid
        from-state for the requested transition, reported per entity as ...,
        `ERR_INVALID_PACKET_STATE`, ... (all 409)."

        Design: Corner/state_machines/packet_approve_from_draft_rejected
        """
        set_clock()
        unit = create_unit(name="MED", required_cert_types=[])
        nurse = create_nurse(full_name="Pack Draft", email="pack.draft@x.com",
                             employment_type="TRAVEL")
        packet = create_packet(nurse["id"], unit["id"])

        resp = api_client.approve_packet(packet["id"], SPEC2)
        validate_error(resp, ApiErrorId.ERR_INVALID_PACKET_STATE)
        assert get_packet(packet["id"])["status"] == "DRAFT"

    def test_packet_submit_with_missing_items_rejected(self):
        """PRD §3.7: "Once the checklist is complete in the loose sense — every item
        `SUBMITTED`, `VERIFIED`, or `WAIVED`, else `ERR_PACKET_ITEMS_INCOMPLETE` — the
        owning nurse submits the packet, moving it from `DRAFT` to `SUBMITTED`; ..."

        Design: Corner/validations/packet_submit_with_missing_items_rejected
        """
        set_clock()
        unit = create_unit(name="MED", required_cert_types=[])
        nurse = create_nurse(full_name="In Complete", email="in.complete@x.com",
                             employment_type="TRAVEL")
        packet = create_packet(nurse["id"], unit["id"])

        resp = api_client.submit_packet(packet["id"], make_nurse_headers(nurse["id"]))
        validate_error(resp, ApiErrorId.ERR_PACKET_ITEMS_INCOMPLETE)
        assert get_packet(packet["id"])["status"] == "DRAFT"

    def test_packet_second_active_rejected(self):
        """PRD §3.7: "At most one packet per nurse may stand in `DRAFT`, `SUBMITTED`,
        or `UNDER_REVIEW` at a time — a second creation is `ERR_ACTIVE_PACKET_EXISTS`."

        Design: Corner/validations/packet_second_active_rejected
        """
        set_clock()
        unit = create_unit(name="MED", required_cert_types=[])
        nurse = create_nurse(full_name="Two Packets", email="two.packets@x.com",
                             employment_type="TRAVEL")
        packet = create_packet(nurse["id"], unit["id"])

        resp = api_client.create_credential_packet(
            create_credential_packet_payload(nurse["id"], unit["id"]), SPEC2
        )
        validate_error(resp, ApiErrorId.ERR_ACTIVE_PACKET_EXISTS)
        data, meta = validate_paginated(
            api_client.list_credential_packets(SPEC1, params={"nurse_id": nurse["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == packet["id"] and data[0]["status"] == "DRAFT"

    def test_packet_create_unit_not_found_returns_404(self):
        """PRD §2.9: "5. **Body referential integrity** — foreign keys in the payload
        must resolve: `nurse_id` (`ERR_NURSE_NOT_FOUND`), `license_id`
        (`ERR_LICENSE_NOT_FOUND`), `unit_id` or `target_unit_id`
        (`ERR_UNIT_NOT_FOUND`), and `requirement_id` (`ERR_REQUIREMENT_NOT_FOUND`),
        all 404."

        Design: Corner/validations/packet_create_unit_not_found_returns_404
        """
        set_clock()
        nurse = create_nurse(full_name="Unit Miss", email="unit.miss@x.com",
                             employment_type="TRAVEL")
        resp = api_client.create_credential_packet(
            create_credential_packet_payload(nurse["id"], NON_EXISTENT_UUID), SPEC1
        )
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_FOUND)
        _data, meta = validate_paginated(
            api_client.list_credential_packets(SPEC1, params={"nurse_id": nurse["id"]})
        )
        assert meta["total_count"] == 0


class TestPacketItemRules:
    def test_item_waive_critical_rejected(self):
        """PRD §3.7: "A specialist may instead waive an item standing `MISSING` or
        `SUBMITTED`, recording a `waive_reason`, but only when the item is not critical
        — waiving a critical item is `ERR_ITEM_NOT_WAIVABLE`. Waiving lands the item in
        terminal `WAIVED` and recomputes the score."
        PRD §3.7: "The raw score is the sum of each item's weight times its credit,
        divided by the sum of the weights, rounded half up to 4 decimals. A critical
        cap then applies: while any critical item stands `MISSING` or `INVALIDATED`,
        the score is the smaller of the raw value and 0.49."

        Design: Corner/validations/item_waive_critical_rejected
        """
        set_clock()
        unit = create_unit(name="ICU", required_cert_types=["ACLS"])
        nurse = create_nurse(full_name="Wai Ver", email="wai.ver@x.com",
                             employment_type="TRAVEL")
        packet = create_packet(nurse["id"], unit["id"])
        items = packet_items_by_type(packet["id"])

        resp = api_client.waive_packet_item(
            items["ACLS"]["id"], {"waive_reason": "not needed"}, SPEC1
        )
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_WAIVABLE)
        assert get_packet_item(items["ACLS"]["id"])["status"] == "MISSING"

        waived = validate_success(
            api_client.waive_packet_item(
                items["ATTESTATION"]["id"], {"waive_reason": "on file"}, SPEC1
            ),
            200,
        )
        assert waived["status"] == "WAIVED"
        # raw = (5 * 0.5) / 100 = 0.025; critical items MISSING -> min(0.025, 0.49).
        assert get_packet(packet["id"])["readiness_score"] == pytest.approx(
            0.025, abs=0.0001
        )

    def test_item_verify_without_evidence_rejected(self):
        """PRD §3.7: "The server checks that the underlying evidence actually holds,
        else `ERR_ITEM_EVIDENCE_INVALID`: a license-verification item requires an
        `ACTIVE` state license for the nurse; BLS and ACLS items each require an
        `ACTIVE` certification of that `cert_type`; the annual-competency item requires
        a `CURRENT` completion for a mandatory applicable requirement; and an
        attestation item requires only its `evidence_ref`."

        Design: Corner/validations/item_verify_without_evidence_rejected
        """
        set_clock()
        unit = create_unit(name="MED", required_cert_types=[])
        nurse = create_nurse(full_name="No Cert", email="no.cert@x.com",
                             employment_type="TRAVEL")
        packet = create_packet(nurse["id"], unit["id"])
        items = packet_items_by_type(packet["id"])
        submitted = validate_success(
            api_client.submit_item_evidence(
                items["BLS"]["id"], {"evidence_ref": "bls-claim"},
                make_nurse_headers(nurse["id"]),
            ),
            200,
        )
        assert submitted["status"] == "SUBMITTED"

        resp = api_client.verify_packet_item(items["BLS"]["id"], SPEC1)
        validate_error(resp, ApiErrorId.ERR_ITEM_EVIDENCE_INVALID)
        assert get_packet_item(items["BLS"]["id"])["status"] == "SUBMITTED", (
            "no ACTIVE BLS certification exists for the nurse"
        )

    def test_item_verify_from_missing_rejected(self):
        """PRD §3.7: "Verification belongs to a `CredentialingSpecialist` and is
        allowed only from `SUBMITTED`, else `ERR_INVALID_ITEM_STATE`."

        Design: Corner/validations/item_verify_from_missing_rejected
        """
        set_clock()
        unit = create_unit(name="MED", required_cert_types=[])
        nurse = create_nurse(full_name="Miss Verify", email="miss.verify@x.com",
                             employment_type="TRAVEL")
        packet = create_packet(nurse["id"], unit["id"])
        items = packet_items_by_type(packet["id"])

        resp = api_client.verify_packet_item(items["BLS"]["id"], SPEC1)
        validate_error(resp, ApiErrorId.ERR_INVALID_ITEM_STATE)
        assert get_packet_item(items["BLS"]["id"])["status"] == "MISSING"


class TestPacketApprovalAndCascade:
    def test_packet_full_approval_readiness_one(self):
        """PRD §3.7: "The raw score is the sum of each item's weight times its credit,
        divided by the sum of the weights, rounded half up to 4 decimals."
        PRD §3.7: "From `UNDER_REVIEW`, approval requires strict completeness — every
        item `VERIFIED` or `WAIVED`, else `ERR_PACKET_ITEMS_INCOMPLETE` — plus a nurse
        who is `ACTIVE` (`ERR_INVALID_NURSE_STATE`) and `CLEAR` (`ERR_NURSE_NOT_CLEAR`);
        approval stamps `reviewed_by_user_id`."
        PRD §3.7: "...an attestation item requires only its `evidence_ref`."

        Design: Corner/calculations/packet_full_approval_readiness_one
        """
        set_clock()
        ctx = setup_credentialed_nurse(
            full_name="Happy Path", email="happy.path@x.com", employment_type="TRAVEL",
        )
        nurse = ctx["nurse"]
        unit = create_unit(name="MED", required_cert_types=[])
        approved_ctx = setup_approved_packet(nurse["id"], unit["id"],
                                             attestation="verify")
        packet = approved_ctx["packet"]
        # (40 + 20 + 15 + 5) / 80 == 1.0 with all credits 1.0
        assert packet["readiness_score"] == pytest.approx(1.0, abs=0.0001)
        assert packet["status"] == "APPROVED"
        assert packet["reviewed_by_user_id"] == "spec-2"

    def test_certification_revoke_invalidates_packet_item(self):
        """PRD §3.4: "Revoking an `ACTIVE` certification fires the same
        item-invalidation cascade as expiry; both the revoke and the expire paths
        recompute the nurse's posture."
        PRD §3.7: "Invalidation is itself a cascade: when the credential row named by
        an item's `source_credential_id` lapses — a license going `EXPIRED`,
        `ENCUMBERED`, or `SURRENDERED`; a certification going `EXPIRED` or `REVOKED`; a
        completion going `LAPSED` or `SUPERSEDED` — a `VERIFIED` item becomes
        `INVALIDATED`, the readiness score recomputes, and an `APPROVED` parent packet
        is voided."
        PRD §3.5: "Every certification type in the requirement set must be backed by an
        `ACTIVE` certification, and every competency requirement in the set by a
        `CURRENT` completion; any deficit means `SCHEDULING_SUSPENDED`."

        Design: Corner/state_machines/certification_revoke_invalidates_packet_item
        """
        set_clock()
        ctx = setup_credentialed_nurse(
            full_name="Rev Oke", email="rev.oke@x.com", employment_type="TRAVEL",
        )
        nurse, bls = ctx["nurse"], ctx["bls"]
        unit = create_unit(name="MED", required_cert_types=[])
        approved_ctx = setup_approved_packet(nurse["id"], unit["id"])
        packet, items = approved_ctx["packet"], approved_ctx["items"]
        assert get_packet_item(items["BLS"]["id"])["source_credential_id"] == bls["id"]

        revoked = validate_success(api_client.revoke_certification(bls["id"], CO1), 200)
        assert revoked["status"] == "REVOKED"

        bls_item = get_packet_item(items["BLS"]["id"])
        assert bls_item["status"] == "INVALIDATED"
        assert get_packet_item(items["LICENSE_VERIFICATION"]["id"])["status"] == "VERIFIED"
        assert get_packet_item(items["ATTESTATION"]["id"])["status"] == "WAIVED"
        assert get_packet(packet["id"])["status"] == "VOIDED"
        assert get_nurse(nurse["id"])["credential_posture"] == "SCHEDULING_SUSPENDED", (
            "the BLS deficit survives the revocation"
        )


class TestCertificationRenewState:
    def test_cert_renew_from_active_rejected(self):
        """PRD §3.4: "Renewal moves a certification from `EXPIRED` back to `ACTIVE` —
        renewal from any other state is `ERR_INVALID_CERTIFICATION_STATE` — with a
        `new_expires_on` strictly after the current date, else
        `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/cert_renew_from_active_rejected
        """
        set_clock()
        nurse = create_nurse(full_name="Cert Renew", email="cert.renew@x.com")
        cert = validate_success(
            api_client.create_certification(
                {"nurse_id": nurse["id"], "cert_type": "BLS", "issuing_body": "AHA",
                 "obtained_on": "2026-05-01", "expires_on": "2027-03-31"},
                SPEC1,
            ),
            201,
        )
        resp = api_client.renew_certification(
            cert["id"], {"new_expires_on": "2028-03-31"}, SPEC1
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_CERTIFICATION_STATE)
        after = validate_success(api_client.get_certification(cert["id"], SPEC1), 200)
        assert after["status"] == "ACTIVE"
        assert after["expires_on"] == "2027-03-31"
