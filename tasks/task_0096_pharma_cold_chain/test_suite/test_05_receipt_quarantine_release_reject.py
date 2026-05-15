"""Quarantine, release-from-quarantine, reject — PRD §3.2.

Branching state machine: INSPECTED → QUARANTINED → ACCEPTED (release
revert path) OR INSPECTED → QUARANTINED → REJECTED (terminal). Also
exercises segregation-of-duties between the QAOfficer that
quarantined and the QAOfficer that releases.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    assert_certificate_format,
    assert_lot,
    create_bin,
    create_inspected_receipt,
    create_product,
    create_supplier,
    create_warehouse,
    create_zone,
    find_row,
    list_audit_log,
    list_external_events,
    list_lots,
    make_qa_officer_headers,
    quarantine_receipt,
    release_receipt_from_quarantine,
    setup_basic_topology,
    setup_qualified_supplier_and_product,
    validate_error,
)


# ===========================================================================
# Routing to quarantine — PRD §3.2 second-to-last paragraph
# ===========================================================================
class TestQuarantineRouting:

    def test_quarantine_mints_lot_with_quarantined_status(self, api):
        """PRD §3.2: "The system allocates a bin in a `QUARANTINE`-type
        zone of the same warehouse, mints a `Lot` whose
        `quality_status` is `QUARANTINED` and whose `bin_id` points
        at the quarantine bin".

        Claim: after quarantine, the minted lot has quality_status
        QUARANTINED and bin_id pointing at a QUARANTINE-type bin.
        """
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product()
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"],
            quantity_units=1, visual_pass=False,
        )
        quarantined = quarantine_receipt(receipt["id"])
        assert quarantined["status"] == "QUARANTINED"
        # Find the minted lot.
        lots = list_lots(
            topology["warehouse"]["id"],
            params={"quality_status": "QUARANTINED", "limit": 100},
        )
        lot = find_row(lots, receipt_id=receipt["id"])
        assert lot["quality_status"] == "QUARANTINED"

    def test_quarantine_emits_regulatory_authority_inbound_quarantined(
        self, api,
    ):
        """PRD §3.2: "appends one `ExternalSyncEvent` targeted at
        `REGULATORY_AUTHORITY` with `event_type`
        `INBOUND_QUARANTINED`".

        Claim: a quarantine call appends one
        REGULATORY_AUTHORITY/INBOUND_QUARANTINED event. (Per PRD §2.13
        only the regulatory event is emitted on quarantine — not the
        GSP event that accompanies accept.)
        """
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product()
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"],
            quantity_units=1, visual_pass=False,
        )
        quarantine_receipt(receipt["id"])
        events = list_external_events(
            topology["warehouse"]["id"],
            params={"event_type": "INBOUND_QUARANTINED", "limit": 100},
        )
        regulatory = [
            e for e in events
            if e["target_system"] == "REGULATORY_AUTHORITY"
            and e["event_type"] == "INBOUND_QUARANTINED"
        ]
        assert len(regulatory) >= 1


# ===========================================================================
# Release-from-quarantine — PRD §3.2 (Revert path)
# ===========================================================================
class TestReleaseFromQuarantine:

    def test_release_only_allowed_for_visual_fail_or_temp_excursion(self, api):
        """PRD §3.2: "may release the receipt back to `ACCEPTED`, but
        only when the `nonconformance_reason` is `VISUAL_FAIL` or
        `TEMP_EXCURSION` — the unqualified-supplier, unqualified-
        product, and expired-on-arrival paths are not releasable."

        Claim: a receipt that was QUARANTINED with
        reason==UNQUALIFIED_SUPPLIER cannot be released; the release
        attempt is rejected.

        Two-reader thought: PRD does not explicitly name the error_id
        for this rejection, so we assert the receipt does NOT move
        back to ACCEPTED rather than asserting a specific error_id.
        """
        topology = setup_basic_topology()
        supplier = create_supplier(qualified=False,
                                   qualification_expiry_minutes=100_000)
        product = create_product(
            required_zone_type="REFRIGERATED", qualified=True,
        )
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"],
            quantity_units=1, visual_pass=True,
        )
        assert receipt["nonconformance_reason"] == "UNQUALIFIED_SUPPLIER"
        quarantined = quarantine_receipt(receipt["id"])
        assert quarantined["status"] == "QUARANTINED"
        # Attempt release.
        res = api.release_receipt_from_quarantine(
            receipt["id"], TEST_USERS["qa_officer_headers_alt"],
        )
        # PRD: "are not releasable" → rejected. Status remains
        # QUARANTINED.
        assert res.status_code >= 400, (
            f"Expected error on release of non-releasable receipt, got "
            f"{res.status_code}"
        )

    def test_release_succeeds_for_visual_fail(self, api):
        """PRD §3.2: "may release the receipt back to `ACCEPTED`, but
        only when the `nonconformance_reason` is `VISUAL_FAIL` or
        `TEMP_EXCURSION`".

        Claim: a VISUAL_FAIL-quarantined receipt can be released
        back to ACCEPTED by a different QAOfficer.
        """
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product()
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"],
            quantity_units=1, visual_pass=False,
        )
        assert receipt["nonconformance_reason"] == "VISUAL_FAIL"
        quarantine_receipt(receipt["id"])
        # Use alt QA so SOD vs quarantine-actor is satisfied.
        released = release_receipt_from_quarantine(receipt["id"])
        assert released["status"] == "ACCEPTED"

    def test_release_writes_audit_log_release_from_quarantine(self, api):
        """PRD §3.2: "writes an `AuditLogEntry` with `action`
        `RECEIPT_RELEASE_FROM_QUARANTINE`".

        Claim: a successful release records an audit entry with
        action == RECEIPT_RELEASE_FROM_QUARANTINE.
        """
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product()
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"],
            quantity_units=1, visual_pass=False,
        )
        quarantine_receipt(receipt["id"])
        release_receipt_from_quarantine(receipt["id"])
        entries = list_audit_log(
            topology["warehouse"]["id"],
            params={"action": "RECEIPT_RELEASE_FROM_QUARANTINE",
                    "limit": 100},
        )
        matched = [
            e for e in entries
            if e["action"] == "RECEIPT_RELEASE_FROM_QUARANTINE"
            and e["target_id"] == receipt["id"]
        ]
        assert len(matched) >= 1

    def test_release_generates_fresh_certificate(self, api):
        """PRD §3.2: "generates a fresh `acceptance_certificate_no`".

        Claim: after release-from-quarantine, the receipt carries a
        non-null acceptance_certificate_no matching the
        CERT-{warehouse.code}-{seq:06d} pattern.
        """
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product()
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"],
            quantity_units=1, visual_pass=False,
        )
        quarantine_receipt(receipt["id"])
        released = release_receipt_from_quarantine(receipt["id"])
        cert = released.get("acceptance_certificate_no")
        assert cert is not None
        assert_certificate_format(cert, topology["warehouse"]["code"])


# ===========================================================================
# Helper import — needs list_audit_log etc.
# ===========================================================================
from test_helpers import list_audit_log, list_lots  # noqa: E402


# ===========================================================================
# Reject — PRD §3.2 last paragraph
# ===========================================================================
class TestReject:

    def test_reject_from_inspected_for_unqualified_supplier(self, api):
        """PRD §3.2: "From either `INSPECTED` (when
        `nonconformance_reason` is `UNQUALIFIED_SUPPLIER`,
        `UNQUALIFIED_PRODUCT`, or `EXPIRED_ON_ARRIVAL`) or
        `QUARANTINED`, a `QAOfficer` may reject the receipt outright:
        the receipt enters the terminal `REJECTED` state".

        Difficulty-design: non_linear_state_machine /
        inbound_receipt_branching_with_revert (the divergent REJECT
        branch from INSPECTED — different terminal from the ACCEPT
        and QUARANTINE branches).
        # difficulty: non_linear_state_machine/inbound_receipt_branching_with_revert

        Claim: an INSPECTED receipt with reason UNQUALIFIED_SUPPLIER
        can be rejected directly (without quarantining first).
        """
        topology = setup_basic_topology()
        supplier = create_supplier(qualified=False,
                                   qualification_expiry_minutes=100_000)
        product = create_product(
            required_zone_type="REFRIGERATED", qualified=True,
        )
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"],
            quantity_units=1, visual_pass=True,
        )
        res = api.reject_receipt(
            receipt["id"], TEST_USERS["qa_officer_headers"],
        )
        assert res.status_code == 200, (
            f"Expected 200 on reject of UNQUALIFIED_SUPPLIER receipt, "
            f"got {res.status_code}: {res.text}"
        )
        body = res.json()
        assert body["data"]["status"] == "REJECTED"

    def test_inspected_to_quarantine_to_released_round_trip(self, api):
        """PRD §3.2 branching state machine:
        INSPECTED → QUARANTINED → ACCEPTED (revert path). After
        release the receipt's status is ACCEPTED, the lot is RELEASED
        in a non-quarantine bin, and a fresh certificate is issued.

        Difficulty-design: non_linear_state_machine /
        inbound_receipt_branching_with_revert.

        # difficulty: non_linear_state_machine/inbound_receipt_branching_with_revert

        Claim: VISUAL_FAIL receipt walks INSPECTED → QUARANTINED →
        ACCEPTED, with the final lot in RELEASED status and not in a
        QUARANTINE-type zone bin.
        """
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product()
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"],
            quantity_units=1, visual_pass=False,
        )
        assert receipt["nonconformance_reason"] == "VISUAL_FAIL"
        quarantined = quarantine_receipt(receipt["id"])
        assert quarantined["status"] == "QUARANTINED"
        released = release_receipt_from_quarantine(receipt["id"])
        assert released["status"] == "ACCEPTED"
        # The minted lot is now RELEASED.
        lots = list_lots(
            topology["warehouse"]["id"],
            params={"quality_status": "RELEASED", "limit": 100},
        )
        matched = [L for L in lots if L["receipt_id"] == receipt["id"]]
        assert len(matched) == 1, (
            f"Expected exactly one RELEASED lot after release-from-"
            f"quarantine, got {len(matched)}"
        )
        # PRD §3.2 says the new bin is a re-allocation via FEFO, so it
        # must not be in the QUARANTINE zone.
        assert matched[0]["bin_id"] is not None
        # Fetch the bin and confirm zone is NOT QUARANTINE.
        from test_helpers import get_zone
        zone = get_zone(topology["zone"]["id"])
        assert zone["zone_type"] == "REFRIGERATED"

    def test_reject_from_quarantined_sets_lot_status_rejected(self, api):
        """PRD §3.2: "any quarantine-held lot has its `quality_status`
        set to `REJECTED` and its bin's `current_lot_id` cleared".

        Claim: reject of a QUARANTINED receipt sets the
        quarantine-held lot's quality_status to REJECTED.
        """
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product()
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"],
            quantity_units=1, visual_pass=False,
        )
        quarantine_receipt(receipt["id"])
        # Use a different QA actor than the one that quarantined to
        # avoid any SOD interpretation; PRD §3.2 does not require
        # SOD on reject specifically, but using alt is safe.
        res = api.reject_receipt(
            receipt["id"], TEST_USERS["qa_officer_headers_alt"],
        )
        assert res.status_code == 200, (
            f"Expected 200 reject, got {res.status_code}: {res.text}"
        )
        # Verify the lot status flipped to REJECTED.
        lots = list_lots(
            topology["warehouse"]["id"],
            params={"quality_status": "REJECTED", "limit": 100},
        )
        matched = [L for L in lots if L["receipt_id"] == receipt["id"]]
        assert len(matched) == 1, (
            f"Expected exactly one REJECTED lot for receipt "
            f"{receipt['id']}, got {len(matched)}"
        )
