"""Terminal states and the routes back from them.

This module covers the end of a lot's life and the recovery paths the plant still
allows: a shipped carton and its lot refusing every further verb, an operator
quality hold that moves the disposition dimension while the process dimension
stands still, a revoked certificate of conformance recalling the carton printed
with it while its pieces stay accounted for as packed, and the revoke-reissue-issue
cycle that carries one certificate row back to ``ISSUED`` (PRD §2.8, §3.4, §3.8,
§3.9).
"""

from typing import Any, Dict

import pytest

from test_helpers import (
    ApiErrorId,
    assert_lot_piece_ledger,
    assert_wire_mass_ledger,
    fixtures,
    make_clerk_headers,
    make_engineer_headers,
    make_inspector_headers,
    make_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# The unplated reference route used throughout this module.
#
# An unplated CLASS_10_9 part (``plating_spec`` of ``NONE``) needs no relief bake,
# so the lot is tested straight out of the furnace: 5000 planned pieces reserve
# 105.000 kg of the 500.000 kg wire lot, heading reports 4900 good and 60 spoiled,
# the thread roll hands back 4850, the destructive sample consumes 70 and one
# hundred-piece carton takes the available count to 4680.
# ---------------------------------------------------------------------------
REFERENCE_SPEC_OVERRIDES: Dict[str, Any] = {
    "part_number": "NP-M8-088",
    "thread_designation": "M8x1.25",
    "strength_class": "CLASS_10_9",
    "qualification_program": "AUTOMOTIVE_PPAP",
    "allowed_steel_grades": ["SAE_10B21"],
    "blank_mass_g": 20.0,
    "station_count_required": 4,
    "thread_timing": "BEFORE_HEAT_TREAT",
    "required_secondary_ops": ["THREAD_ROLL"],
    "min_core_hardness_hv": 304,
    "max_core_hardness_hv": 361,
    "max_decarb_depth_mm": 0.100,
    "plating_spec": "NONE",
    "packaging_mode": "BY_COUNT",
    "nominal_pack_count": 100,
    "pieces_per_kg": 62.5,
    "proof_load_kn": 34.7,
}

EXPECTED_PACKED_COUNT = 100
EXPECTED_AVAILABLE_COUNT = 4680
EXPECTED_WIRE_RESERVED_KG = 105.000
EXPECTED_WIRE_AVAILABLE_KG = 395.000

CLERK = make_clerk_headers("ship-1")
ENGINEER = make_engineer_headers("eng-1")
INSPECTOR = make_inspector_headers("insp-1")
MANAGER = make_manager_headers("qm-1")
MANAGER_ALT = make_manager_headers("qm-2")


def _lot_in_setup() -> Dict[str, Any]:
    """Master data plus one lot in ``SETUP`` / ``IN_PROCESS`` holding a 105.000 kg reservation."""
    return fixtures.setup_lot_in_setup(
        planned_pieces=5000,
        unplated=True,
        spec_overrides=dict(REFERENCE_SPEC_OVERRIDES),
    )


def _sealed_pack_env() -> Dict[str, Any]:
    """The unplated route driven to a ``SEALED`` carton behind an ``ISSUED`` certificate."""
    return fixtures.setup_sealed_pack(
        unplated=True,
        spec_overrides=dict(REFERENCE_SPEC_OVERRIDES),
        min_measured_core_hardness_hv=322.0,
        cert_serial="CERT-0001",
        label_serial="PK-0001",
    )


def _list_certificates_for_lot(api, production_lot_id: str):
    """Certificates of one lot, with the paginated envelope's meta block."""
    return validate_paginated(
        api.list_certification_documents(
            MANAGER, params={"production_lot_id": production_lot_id}
        )
    )


def _shipped_pack_env() -> Dict[str, Any]:
    """The same route driven one step further, to a ``SHIPPED`` carton and a ``SHIPPED`` lot."""
    return fixtures.setup_shipped_pack(
        unplated=True,
        spec_overrides=dict(REFERENCE_SPEC_OVERRIDES),
        min_measured_core_hardness_hv=322.0,
        cert_serial="CERT-0001",
        label_serial="PK-0001",
    )


class TestShippedIsTerminalOnBothEntities:
    """A carton that has left the dock, and the lot behind it, accept nothing further."""

    def test_reshipping_a_shipped_pack_unit_is_refused(self, api):
        """Shipping an already-shipped carton a second time is refused and changes nothing.

        PRD: "A pack unit must be `OPEN` to seal and `SEALED` to reopen or ship, with `RECALLED` terminal — otherwise `ERR_INVALID_PACK_UNIT_STATE` (409)."

        PRD: "On success the pack moves `SEALED → SHIPPED` and `shipped_at` is stamped from the logical clock; the lot moves `PACKED → SHIPPED` only once every pack unit of the lot is in `status` `SHIPPED` and at least one such pack exists."

        Design: Corner/state_machines/shipped_lot_and_pack_cannot_transition_again
        """
        env = _shipped_pack_env()
        pack_before = env["pack"]
        assert pack_before["status"] == "SHIPPED", (
            f"Expected SHIPPED, got {pack_before['status']} after the first shipment"
        )

        resp = api.ship_pack_unit(pack_before["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_PACK_UNIT_STATE.value)

        pack_after = validate_success(api.get_pack_unit(pack_before["id"], CLERK))
        assert pack_after["status"] == "SHIPPED", (
            f"Expected the carton to stay SHIPPED, got {pack_after['status']}"
        )
        assert pack_after["version"] == pack_before["version"], (
            f"Expected version {pack_before['version']}, got {pack_after['version']} "
            "after a refused re-shipment"
        )

        lot = validate_success(api.get_production_lot(env["lot"]["id"], CLERK))
        assert lot["packed_count"] == EXPECTED_PACKED_COUNT, (
            f"Expected packed_count {EXPECTED_PACKED_COUNT}, got {lot['packed_count']} "
            "after a refused re-shipment"
        )
        assert lot["available_count"] == EXPECTED_AVAILABLE_COUNT, (
            f"Expected available_count {EXPECTED_AVAILABLE_COUNT}, got "
            f"{lot['available_count']} after a refused re-shipment"
        )
        assert_lot_piece_ledger(lot)

    def test_shipped_lot_refuses_a_new_secondary_operation(self, api):
        """A lot whose process dimension reads SHIPPED will not queue more floor work.

        PRD: "Queueing requires the lot's `disposition` to be `IN_PROCESS` and its `process_state` to be `HEADED`, `HEAT_TREATED` or `SECONDARY_IN_PROGRESS`; anything else is refused with `ERR_INVALID_LOT_STATE`."

        PRD: "`SHIPPED` is terminal on the lot's process dimension."

        Design: Corner/state_machines/shipped_lot_and_pack_cannot_transition_again
        """
        env = _shipped_pack_env()
        lot_before = validate_success(
            api.get_production_lot(env["lot"]["id"], ENGINEER)
        )
        assert lot_before["process_state"] == "SHIPPED", (
            f"Expected SHIPPED, got {lot_before['process_state']} once the only "
            "carton of the lot had shipped"
        )

        resp = api.queue_secondary_operation(
            lot_before["id"],
            {"op_type": "POINT", "sequence_no": 2, "machine_code": "PT-1"},
            ENGINEER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_LOT_STATE.value)

        lot_after = validate_success(api.get_production_lot(lot_before["id"], ENGINEER))
        assert lot_after["process_state"] == "SHIPPED", (
            f"Expected the lot to stay SHIPPED, got {lot_after['process_state']}"
        )
        assert lot_after["version"] == lot_before["version"], (
            f"Expected version {lot_before['version']}, got {lot_after['version']} "
            "after a refused secondary-operation queue"
        )
        assert lot_after["packed_count"] == EXPECTED_PACKED_COUNT, (
            f"Expected packed_count {EXPECTED_PACKED_COUNT}, got "
            f"{lot_after['packed_count']} after a refused queue"
        )
        assert lot_after["available_count"] == EXPECTED_AVAILABLE_COUNT, (
            f"Expected available_count {EXPECTED_AVAILABLE_COUNT}, got "
            f"{lot_after['available_count']} after a refused queue"
        )


class TestHoldMovesOnlyTheDispositionDimension:
    """The quality freeze and thaw of a lot still in setup, and what they leave alone."""

    def test_operator_hold_moves_only_the_disposition_dimension(self, api):
        """An inspector's hold sets HOLD / QUALITY while process_state and the wire ledger stand still.

        PRD: "A `QualityInspector` or `QualityManager` may place a hold with a `reason` on any lot whose `disposition` is `IN_PROCESS`, taking it `IN_PROCESS → HOLD` with `hold_source` of `QUALITY` and incrementing its `version` by 1."

        PRD: "The `disposition` dimension is deliberately independent of `process_state`: a lot can be frozen and thawed without moving one step along its process route."

        Design: Corner/state_machines/operator_hold_and_release_hold_move_only_the_disposition_dimension
        """
        env = _lot_in_setup()
        lot_before = env["lot"]
        assert lot_before["process_state"] == "SETUP", (
            f"Expected SETUP, got {lot_before['process_state']} at lot opening"
        )

        held = validate_success(
            api.hold_production_lot(
                lot_before["id"],
                {"reason": "customer stop-ship pending drawing review"},
                INSPECTOR,
            )
        )

        assert held["disposition"] == "HOLD", (
            f"Expected disposition HOLD, got {held['disposition']} after the hold"
        )
        assert held["hold_source"] == "QUALITY", (
            f"Expected hold_source QUALITY, got {held['hold_source']} for an operator hold"
        )
        assert held["process_state"] == "SETUP", (
            f"Expected process_state to stay SETUP, got {held['process_state']} "
            "after a hold"
        )
        assert held["version"] == lot_before["version"] + 1, (
            f"Expected version {lot_before['version'] + 1}, got {held['version']} "
            "after one hold write"
        )

        wire = validate_success(api.get_wire_lot(env["wire"]["id"], INSPECTOR))
        assert wire["reserved_mass_kg"] == pytest.approx(
            EXPECTED_WIRE_RESERVED_KG, abs=0.001
        ), (
            f"Expected reserved_mass_kg {EXPECTED_WIRE_RESERVED_KG}, got "
            f"{wire['reserved_mass_kg']} after a hold that touched no material"
        )
        assert wire["available_mass_kg"] == pytest.approx(
            EXPECTED_WIRE_AVAILABLE_KG, abs=0.001
        ), (
            f"Expected available_mass_kg {EXPECTED_WIRE_AVAILABLE_KG}, got "
            f"{wire['available_mass_kg']} after a hold that touched no material"
        )
        assert_wire_mass_ledger(wire)

    def test_release_hold_returns_the_disposition_to_in_process(self, api):
        """The manager's release clears the tag, leaves process_state in SETUP and is one write.

        PRD: "A successful release takes the lot `HOLD → IN_PROCESS`, resets `hold_source` to `NONE`, and increments the `version` by 1."

        PRD: "On success, that amount is subtracted from `available_mass_kg`, added to `reserved_mass_kg`, and stored on the lot as `wire_reserved_kg`; the wire lot's `version` increments by 1."

        Design: Corner/state_machines/operator_hold_and_release_hold_move_only_the_disposition_dimension
        """
        env = _lot_in_setup()
        held = validate_success(
            api.hold_production_lot(
                env["lot"]["id"],
                {"reason": "customer stop-ship pending drawing review"},
                INSPECTOR,
            )
        )

        released = validate_success(
            api.release_hold(
                env["lot"]["id"], {"note": "drawing review closed"}, MANAGER
            )
        )

        assert released["disposition"] == "IN_PROCESS", (
            f"Expected disposition IN_PROCESS, got {released['disposition']} "
            "after the release"
        )
        assert released["hold_source"] == "NONE", (
            f"Expected hold_source NONE, got {released['hold_source']} after the release"
        )
        assert released["process_state"] == "SETUP", (
            f"Expected process_state to stay SETUP, got {released['process_state']} "
            "after the release"
        )
        assert released["version"] == held["version"] + 1, (
            f"Expected version {held['version'] + 1}, got {released['version']} — "
            "each transition on the disposition dimension is exactly one write"
        )
        assert released["wire_reserved_kg"] == pytest.approx(
            EXPECTED_WIRE_RESERVED_KG, abs=0.001
        ), (
            f"Expected wire_reserved_kg {EXPECTED_WIRE_RESERVED_KG}, got "
            f"{released['wire_reserved_kg']} across the hold and the release"
        )

        wire = validate_success(api.get_wire_lot(env["wire"]["id"], MANAGER))
        assert wire["reserved_mass_kg"] == pytest.approx(
            EXPECTED_WIRE_RESERVED_KG, abs=0.001
        ), (
            f"Expected reserved_mass_kg {EXPECTED_WIRE_RESERVED_KG}, got "
            f"{wire['reserved_mass_kg']} after the release"
        )
        assert wire["available_mass_kg"] == pytest.approx(
            EXPECTED_WIRE_AVAILABLE_KG, abs=0.001
        ), (
            f"Expected available_mass_kg {EXPECTED_WIRE_AVAILABLE_KG}, got "
            f"{wire['available_mass_kg']} after the release"
        )
        assert_wire_mass_ledger(wire)


class TestRevokeRecallsTheSealedPack:
    """One revoke request fans out to the carton and to the lot's disposition."""

    def test_revoking_the_certificate_recalls_the_sealed_pack(self, api):
        """The revoke records its reason and copies it onto the recalled carton.

        PRD: "Revoking a certificate in `status` `DRAFT`, `ISSUED` or `REISSUE_PENDING` with a supplied `reason` moves it to `REVOKED` and records that reason as `revoked_reason`."

        PRD: "The revocation cascades: every pack unit printed with that certificate whose `status` is `SEALED` or `SHIPPED` becomes `RECALLED`, in ascending `created_at` order, with its `recall_reason` copied from the certificate's `revoked_reason`."

        PRD: "The certificate's `version`, the lot's `version` and the `version` of every recalled pack unit each increment by 1."

        Design: Corner/state_machines/cert_revoke_recalls_the_sealed_pack_and_holds_the_lot
        """
        env = _sealed_pack_env()
        pack_before = env["pack"]
        assert pack_before["status"] == "SEALED", (
            f"Expected SEALED, got {pack_before['status']} before the revoke"
        )
        reason = "customer complaint on thread gauge"

        cert = validate_success(
            api.revoke_certification_document(
                env["certificate"]["id"], {"reason": reason}, MANAGER
            )
        )

        assert cert["status"] == "REVOKED", (
            f"Expected REVOKED, got {cert['status']} after the operator revoke"
        )
        assert cert["revoked_reason"] == reason, (
            f"Expected revoked_reason {reason!r}, got {cert['revoked_reason']!r}"
        )

        pack_after = validate_success(api.get_pack_unit(pack_before["id"], MANAGER))
        assert pack_after["status"] == "RECALLED", (
            f"Expected RECALLED, got {pack_after['status']} for the carton printed "
            "with the revoked certificate"
        )
        assert pack_after["recall_reason"] == reason, (
            f"Expected recall_reason {reason!r} copied from the revocation, got "
            f"{pack_after['recall_reason']!r}"
        )
        assert pack_after["version"] == pack_before["version"] + 1, (
            f"Expected version {pack_before['version'] + 1}, got "
            f"{pack_after['version']} on the recalled carton"
        )

    def test_revoking_the_certificate_holds_the_lot_without_returning_packed_pieces(
        self, api
    ):
        """The lot picks up HOLD / QUALITY, stays PACKED, and keeps its packed pieces.

        PRD: "When the revocation came from the operator endpoint and the lot's `disposition` was `IN_PROCESS`, the lot additionally moves to `disposition` `HOLD` with `hold_source` of `QUALITY`."

        PRD: "Recalled pieces do not come back into inventory: the lot's `packed_count` is left exactly as it was, because those pieces have left the lot for good."

        Design: Corner/state_machines/cert_revoke_recalls_the_sealed_pack_and_holds_the_lot
        """
        env = _sealed_pack_env()
        lot_before = env["lot"]
        assert lot_before["process_state"] == "PACKED", (
            f"Expected PACKED, got {lot_before['process_state']} after the seal"
        )
        assert lot_before["disposition"] == "IN_PROCESS", (
            f"Expected IN_PROCESS, got {lot_before['disposition']} before the revoke"
        )

        validate_success(
            api.revoke_certification_document(
                env["certificate"]["id"],
                {"reason": "customer complaint on thread gauge"},
                MANAGER,
            )
        )

        lot_after = validate_success(api.get_production_lot(lot_before["id"], MANAGER))
        assert lot_after["disposition"] == "HOLD", (
            f"Expected disposition HOLD, got {lot_after['disposition']} after the revoke"
        )
        assert lot_after["hold_source"] == "QUALITY", (
            f"Expected hold_source QUALITY, got {lot_after['hold_source']} after an "
            "operator revoke"
        )
        assert lot_after["process_state"] == "PACKED", (
            f"Expected process_state to stay PACKED, got {lot_after['process_state']} — "
            "the revoke touches the disposition dimension only"
        )
        assert lot_after["packed_count"] == EXPECTED_PACKED_COUNT, (
            f"Expected packed_count {EXPECTED_PACKED_COUNT}, got "
            f"{lot_after['packed_count']} — recalled pieces stay accounted as packed"
        )
        assert lot_after["available_count"] == EXPECTED_AVAILABLE_COUNT, (
            f"Expected available_count {EXPECTED_AVAILABLE_COUNT}, got "
            f"{lot_after['available_count']} — recalled pieces are not returned to stock"
        )
        assert_lot_piece_ledger(lot_after)


class TestReissueCycleReturnsTheDocumentToIssued:
    """ISSUED to REVOKED to REISSUE_PENDING to ISSUED, closing on the same row."""

    @staticmethod
    def _revoked_and_released(api) -> Dict[str, Any]:
        """A sealed carton's certificate revoked, then the resulting quality hold released."""
        env = _sealed_pack_env()
        env["certificate"] = validate_success(
            api.revoke_certification_document(
                env["certificate"]["id"],
                {"reason": "customer complaint on thread gauge"},
                MANAGER,
            )
        )
        env["lot"] = validate_success(
            api.release_hold(
                env["lot"]["id"],
                {"note": "complaint closed as gauge error at the customer"},
                MANAGER,
            )
        )
        return env

    def test_reissue_bumps_the_revision_and_clears_the_signature(self, api):
        """Reissuing swaps the serial, advances the revision to 2 and drops the signature.

        PRD: "A `QualityManager` reissues it by supplying a new, plant-unique `cert_serial`; the certificate must be in `status` `REVOKED` and the lot's `disposition` must be `IN_PROCESS`, so a lot still on hold reports `ERR_LOT_ON_HOLD` and a quarantined lot reports `ERR_LOT_QUARANTINED`."

        PRD: "On success the new serial replaces the old one, `revision` increments by 1, the `status` moves `REVOKED → REISSUE_PENDING`, `signed_by_user_id` is cleared, the `traceability_chain` is re-projected from the lot's current provenance, and the certificate's `version` increments by 1 — closing the cycle `ISSUED → REVOKED → REISSUE_PENDING → ISSUED`."

        Design: Corner/state_machines/cert_reissue_cycle_returns_the_document_to_issued
        """
        env = self._revoked_and_released(api)
        cert_before = env["certificate"]
        assert cert_before["revision"] == 1, (
            f"Expected revision 1 on the first issue, got {cert_before['revision']}"
        )

        cert = validate_success(
            api.reissue_certification_document(
                cert_before["id"], {"cert_serial": "CERT-0002"}, MANAGER
            )
        )

        assert cert["status"] == "REISSUE_PENDING", (
            f"Expected REISSUE_PENDING, got {cert['status']} after the reissue"
        )
        assert cert["revision"] == 2, (
            f"Expected revision 2, got {cert['revision']} after the reissue"
        )
        assert cert["cert_serial"] == "CERT-0002", (
            f"Expected cert_serial CERT-0002, got {cert['cert_serial']!r} after the reissue"
        )
        assert cert["signed_by_user_id"] in (None, ""), (
            "Expected signed_by_user_id to be cleared by the reissue, got "
            f"{cert['signed_by_user_id']!r}"
        )
        assert cert["version"] == cert_before["version"] + 1, (
            f"Expected version {cert_before['version'] + 1}, got {cert['version']} "
            "after one reissue write"
        )
        assert cert["id"] == cert_before["id"], (
            "The reissue must mutate the same certificate row, got "
            f"{cert['id']} instead of {cert_before['id']}"
        )

    def test_second_issue_closes_the_reissue_cycle_on_the_same_row(self, api):
        """Signing the reissue-pending document re-stamps the signer without creating a second row.

        PRD: "Signing a certificate in `status` `REISSUE_PENDING` requires only that its `pinned_part_spec_version` still match the specification's `version`; the certificate moves `REISSUE_PENDING → ISSUED`, `issued_at` is stamped, `signed_by_user_id` takes the acting `X-User-ID`, and the certificate's `version` increments by 1."

        Design: Corner/state_machines/cert_reissue_cycle_returns_the_document_to_issued
        """
        env = self._revoked_and_released(api)
        pending = validate_success(
            api.reissue_certification_document(
                env["certificate"]["id"], {"cert_serial": "CERT-0002"}, MANAGER
            )
        )

        issued = validate_success(
            api.issue_certification_document(pending["id"], MANAGER_ALT)
        )

        assert issued["status"] == "ISSUED", (
            f"Expected ISSUED, got {issued['status']} after signing the reissue"
        )
        assert issued["signed_by_user_id"] == "qm-2", (
            f"Expected signed_by_user_id qm-2, got {issued['signed_by_user_id']!r} "
            "after the second issue"
        )
        assert issued["version"] == pending["version"] + 1, (
            f"Expected version {pending['version'] + 1}, got {issued['version']} "
            "after one issue write"
        )

        items, meta = _list_certificates_for_lot(api, env["lot"]["id"])
        assert meta["total_count"] == 1, (
            f"Expected total_count 1 for the lot, got {meta['total_count']} — the "
            "revoke-reissue-issue cycle mutates one certificate row"
        )
        assert [row["id"] for row in items] == [pending["id"]], (
            f"Expected only certificate {pending['id']} on the lot, got "
            f"{[row['id'] for row in items]}"
        )

    def test_reissue_does_not_undo_the_recall_or_the_lot_state(self, api):
        """The recalled carton stays recalled and the lot stays PACKED / IN_PROCESS.

        PRD: "`RECALLED` is terminal."

        PRD: "Recalled pieces do not come back into inventory: the lot's `packed_count` is left exactly as it was, because those pieces have left the lot for good."

        Design: Corner/state_machines/cert_reissue_cycle_returns_the_document_to_issued
        """
        env = self._revoked_and_released(api)
        pending = validate_success(
            api.reissue_certification_document(
                env["certificate"]["id"], {"cert_serial": "CERT-0002"}, MANAGER
            )
        )
        validate_success(api.issue_certification_document(pending["id"], MANAGER_ALT))

        pack = validate_success(api.get_pack_unit(env["pack"]["id"], MANAGER))
        assert pack["status"] == "RECALLED", (
            f"Expected the carton to stay RECALLED, got {pack['status']} after the "
            "reissue cycle"
        )

        lot = validate_success(api.get_production_lot(env["lot"]["id"], MANAGER))
        assert lot["disposition"] == "IN_PROCESS", (
            f"Expected disposition IN_PROCESS after the release, got {lot['disposition']}"
        )
        assert lot["process_state"] == "PACKED", (
            f"Expected process_state PACKED, got {lot['process_state']} — the "
            "certificate cycle never moves the process dimension"
        )
        assert lot["packed_count"] == EXPECTED_PACKED_COUNT, (
            f"Expected packed_count {EXPECTED_PACKED_COUNT}, got {lot['packed_count']} "
            "after the reissue cycle"
        )
        assert lot["available_count"] == EXPECTED_AVAILABLE_COUNT, (
            f"Expected available_count {EXPECTED_AVAILABLE_COUNT}, got "
            f"{lot['available_count']} after the reissue cycle"
        )
        assert_lot_piece_ledger(lot)
