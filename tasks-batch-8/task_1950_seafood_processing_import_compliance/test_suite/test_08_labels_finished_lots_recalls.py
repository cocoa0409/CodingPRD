"""Finished product lots, product labels (allergen/COOL/version pinning),
release gates, reopen guards, and recall cascade."""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_lot,
    add_input,
    complete_batch,
    create_approved_label,
    create_approved_supplier,
    create_batch,
    create_finished_lot,
    create_lot,
    create_product_label_payload,
    create_released_entry,
    get_success_data,
    is_iso8601_timestamp,
    make_compliance_manager_headers,
    make_processing_supervisor_headers,
    make_receiving_inspector_headers,
    validate_error,
    validate_paginated,
    validate_success,
    verify_species,
)

CM = TEST_USERS["compliance_manager_headers"]
PS = TEST_USERS["processing_supervisor_headers"]
QA = TEST_USERS["qa_tech_headers"]
RI = TEST_USERS["receiving_inspector_headers"]


def _parse_instant(ts):
    """Parse an ISO 8601 UTC timestamp to an aware datetime for
    instant-equality comparisons."""
    return datetime.fromisoformat(
        ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def _reconciled_cod_batch(api, frn="FRN-V04", entry_number="E-V04",
                          actual=42.0, trim=50.0, other=8.0):
    """Full chain: approved supplier, RELEASED entry, ACCEPTED COD lot,
    batch completed with zero variance and RECONCILED."""
    supplier = create_approved_supplier(name="Harbor Fresh", country="US",
                                        frn=frn)
    entry = create_released_entry(supplier["id"], entry_number=entry_number,
                                  species="COD", transport_mode="ROAD")
    lot = create_lot(entry["id"], species="COD",
                     quantity_received_kg=actual + trim + other)
    verify_species(lot["id"], "COD")
    accept_lot(lot["id"])
    batch = create_batch(target_species="COD", product_form="FILLET")
    add_input(batch["id"], lot["id"], actual + trim + other)
    completed = complete_batch(batch["id"], actual, trim, other)
    reconciled = get_success_data(api.reconcile_batch(batch["id"], PS))
    return supplier, entry, lot, batch, reconciled


def _completed_cod_batch(api, frn="FRN-E04", entry_number="E-E04",
                         actual=42.0, trim=50.0, other=8.0,
                         complete_headers=None):
    """Same as above but stops at COMPLETED (no reconcile)."""
    supplier = create_approved_supplier(name="Harbor Fresh", country="US",
                                        frn=frn)
    entry = create_released_entry(supplier["id"], entry_number=entry_number,
                                  species="COD", transport_mode="ROAD")
    lot = create_lot(entry["id"], species="COD",
                     quantity_received_kg=actual + trim + other)
    verify_species(lot["id"], "COD")
    accept_lot(lot["id"])
    batch = create_batch(target_species="COD", product_form="FILLET")
    add_input(batch["id"], lot["id"], actual + trim + other)
    completed = complete_batch(batch["id"], actual, trim, other,
                               headers=complete_headers)
    return supplier, entry, lot, batch, completed


class TestLabelCreation:
    def test_label_allergen_statement_computed(self, api):
        """PRD: "The `allergen_statement` is computed by the system as
        \"Contains: Fish (\" followed by the `market_name` followed by \")\"
        — any input for this field is ignored. The label starts in `DRAFT`
        status with `approved_at` null."

        Design: Corner/entities/label_allergen_statement_computed
        """
        label = validate_success(api.create_product_label(
            create_product_label_payload(
                market_name="Pacific Cod",
                scientific_name="Gadus macrocephalus", species="COD",
                production_method="WILD", country_of_origin="US",
                keep_frozen_statement=True),
            CM), 201)
        assert label["allergen_statement"] == "Contains: Fish (Pacific Cod)"
        assert label["status"] == "DRAFT"
        assert label["approved_at"] is None
        assert label["version"] == 1


class TestFinishedLotWeightGate:
    def test_finished_weight_equality_allowed_then_exceeded(self, api):
        """PRD: "The sum of `net_weight_kg` across all of the batch's finished
        lots must not exceed the batch's `actual_output_kg` — equality is
        allowed. Exceeding it yields `ERR_FINISHED_WEIGHT_EXCEEDS_OUTPUT`
        (HTTP 422)."

        Design: Corner/validations/finished_weight_equality_allowed_then_exceeded
        """
        supplier, entry, lot, batch, completed = _completed_cod_batch(
            api, frn="FRN-V06", entry_number="E-V06")
        # 25.0 + 17.0 == 42.0 == actual_output_kg: equality allowed.
        fl1 = validate_success(api.create_finished_lot(
            {"processing_batch_id": batch["id"], "net_weight_kg": 25.0},
            PS), 201)
        fl2 = validate_success(api.create_finished_lot(
            {"processing_batch_id": batch["id"], "net_weight_kg": 17.0},
            PS), 201)
        # One more 0.001 kg exceeds the output.
        resp = api.create_finished_lot(
            {"processing_batch_id": batch["id"], "net_weight_kg": 0.001}, PS)
        validate_error(resp, ApiErrorId.ERR_FINISHED_WEIGHT_EXCEEDS_OUTPUT)


class TestApplyLabel:
    def test_apply_draft_label_rejected(self, api):
        """PRD: "The label must be `APPROVED` (`ERR_LABEL_NOT_APPROVED`, HTTP
        409) and its `species` must equal the batch's `target_species`."

        Design: Corner/errors/apply_draft_label_rejected
        """
        supplier, entry, lot, batch, completed = _completed_cod_batch(
            api, frn="FRN-E04", entry_number="E-E04")
        fin = create_finished_lot(batch["id"], 42.0)
        draft = validate_success(api.create_product_label(
            create_product_label_payload(species="COD"), CM), 201)
        resp = api.apply_label(fin["id"], draft["id"], PS)
        validate_error(resp, ApiErrorId.ERR_LABEL_NOT_APPROVED)
        after = validate_success(api.get_finished_lot(fin["id"], PS))
        assert after["status"] == "UNLABELED"

    def test_release_requires_batch_reconciled(self, api):
        """PRD: "the batch must be `RECONCILED` (a batch not yet reconciled
        yields `ERR_INVALID_STATE`, HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/finished_release_requires_batch_reconciled
        """
        supplier, entry, lot, batch, completed = _completed_cod_batch(
            api, frn="FRN-8002", entry_number="E-8002")
        fin = create_finished_lot(batch["id"], 42.0)
        label = create_approved_label(species="COD", market_name="Pacific Cod",
                                      country_of_origin="US",
                                      keep_frozen_statement=True)
        get_success_data(api.apply_label(fin["id"], label["id"], PS))

        resp = api.release_finished_lot(fin["id"], CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_finished_lot(fin["id"], CM))
        assert after["status"] == "LABELED"

    def test_release_succeeds_once_batch_reconciled(self, api):
        """PRD: "The lot must be `LABELED`, the batch must be `RECONCILED`...,
        `label_stale` must be `false`..., the pinned label must currently be
        `APPROVED`, and no CorrectiveAction linked to the batch may be `OPEN`
        or `INVESTIGATING`... On release, `released_at` is set and the lot
        transitions to `RELEASED`."

        Design: Difficulty/cross_entity_state_dependency/finished_release_requires_batch_reconciled
        """
        supplier, entry, lot, batch, reconciled = _reconciled_cod_batch(
            api, frn="FRN-8002B", entry_number="E-8002B")
        fin = create_finished_lot(batch["id"], 42.0)
        label = create_approved_label(species="COD", market_name="Pacific Cod",
                                      country_of_origin="US")
        get_success_data(api.apply_label(fin["id"], label["id"], PS))
        released = validate_success(api.release_finished_lot(fin["id"], CM))
        assert released["status"] == "RELEASED"
        assert released["released_at"] is not None


class TestLabelVersionPinning:
    def test_release_blocked_by_stale_label_then_relabeled(self, api):
        """PRD: "If superseding, the referenced label transitions to
        `SUPERSEDED` (terminal) and its version increments. Every
        FinishedProductLot pinned to the superseded label has its `label_stale`
        set to `true` and its version incremented."
        PRD: "`label_stale` must be `false` (a stale label yields
        `ERR_LABEL_STALE`, HTTP 409)".
        PRD: "Re-application re-pins `product_label_id` and
        `label_version_pinned` to the new label's version, clears `label_stale`
        to `false`, and refreshes `allergen_statement` and
        `country_of_origin`."

        Design: Corner/validations/release_blocked_by_stale_label_then_relabeled
        """
        supplier, entry, lot, batch, reconciled = _reconciled_cod_batch(api)
        fin = create_finished_lot(batch["id"], 42.0)
        label1 = create_approved_label(species="COD",
                                       market_name="Pacific Cod",
                                       country_of_origin="US")
        applied = get_success_data(api.apply_label(fin["id"], label1["id"],
                                                   PS))
        # L1 was created at version 1 and its approve bumped it to 2; the pin
        # captures the label's current version at apply time.
        assert applied["label_version_pinned"] == label1["version"]
        assert applied["label_stale"] is False

        # L2 supersedes L1; approving L2 flips the lot's label_stale.
        label2 = create_approved_label(species="COD",
                                       market_name="Pacific Cod",
                                       country_of_origin="US",
                                       supersedes_label_id=label1["id"])
        stale_lot = validate_success(api.get_finished_lot(fin["id"], PS))
        assert stale_lot["label_stale"] is True
        superseded = validate_success(api.get_product_label(label1["id"], CM))
        assert superseded["status"] == "SUPERSEDED"

        resp = api.release_finished_lot(fin["id"], CM)
        validate_error(resp, ApiErrorId.ERR_LABEL_STALE)

        reapplied = get_success_data(api.apply_label(fin["id"], label2["id"],
                                                     PS))
        assert reapplied["label_version_pinned"] == label2["version"]
        assert reapplied["label_stale"] is False

        released = validate_success(api.release_finished_lot(fin["id"], CM))
        assert released["status"] == "RELEASED"


class TestReopenGuard:
    def test_reopen_blocked_after_finished_lot_recalled(self, api):
        """PRD: "A `COMPLETED` batch may be reopened by a
        `ProcessingSupervisor` only if no FinishedProductLot of this batch has
        status `RELEASED` or `RECALLED`."
        PRD: "Recall creation (via CA escalation, see §3.11) transitions every
        in-scope finished lot — regardless of whether it was `UNLABELED`,
        `LABELED`, or `RELEASED` — to `RECALLED` (terminal)."

        Design: Corner/state_machines/reopen_blocked_after_finished_lot_recalled
        """
        supplier, entry, lot, batch, completed = _completed_cod_batch(
            api, frn="FRN-S04", entry_number="E-S04")
        fin = create_finished_lot(batch["id"], 42.0)

        cm01 = make_compliance_manager_headers("cm-01")
        ca = validate_success(api.create_corrective_action(
            {"source_type": "MANUAL", "processing_batch_id": batch["id"],
             "reason": "in-plant audit hold"}, cm01), 201)
        get_success_data(api.escalate_corrective_action(
            ca["id"], "in-plant recall", [fin["id"]], cm01))

        fin_after = validate_success(api.get_finished_lot(fin["id"], PS))
        assert fin_after["status"] == "RECALLED"

        resp = api.reopen_batch(batch["id"], PS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        batch_after = validate_success(api.get_processing_batch(batch["id"],
                                                                PS))
        assert batch_after["status"] == "COMPLETED"


class TestEscalateRecallCascade:
    def _full_released_lot_and_open_ca(self, api):
        """Builds: RELEASED finished lot (batch reconciled after resolving the
        yield-variance CA) plus a fresh OPEN species-mismatch CA."""
        ps01 = make_processing_supervisor_headers("ps-01")
        supplier = create_approved_supplier(name="Nordic Fish Co", country="NO",
                                            frn="FRN-5002")
        entry = create_released_entry(
            supplier["id"], entry_number="E-5002", species="COD",
            transport_mode="VESSEL", goods_value_cents=700000,
            freight_cost_cents=30000, duty_rate_pct=0.0, total_weight_kg=200)
        lot = create_lot(entry["id"], species="COD", quantity_received_kg=100,
                         harvest_country_code="NO", catch_area_code="FAO27",
                         vessel_name="FV Nord")
        verify_species(lot["id"], "COD")
        accept_lot(lot["id"])
        batch = create_batch(target_species="COD", product_form="FILLET")
        add_input(batch["id"], lot["id"], 100)
        # 100 = 30 + 55 + 15; provisional 42.00, final 30.00, variance -12.00
        completed = complete_batch(batch["id"], 30.0, 55.0, 15.0,
                                   headers=ps01)
        cas, _ = validate_paginated(api.list_corrective_actions(
            CM, params={"processing_batch_id": batch["id"]}))
        yield_ca = cas[0]["id"]
        cm01 = make_compliance_manager_headers("cm-01")
        get_success_data(api.investigate_corrective_action(yield_ca, cm01))
        get_success_data(api.resolve_corrective_action(
            yield_ca, "reworked trim loss", cm01))
        get_success_data(api.reconcile_batch(batch["id"], PS))

        fin = create_finished_lot(batch["id"], 30.0)
        label = create_approved_label(species="COD",
                                      market_name="Pacific Cod",
                                      country_of_origin="NO",
                                      keep_frozen_statement=True)
        get_success_data(api.apply_label(fin["id"], label["id"], PS))
        get_success_data(api.release_finished_lot(fin["id"], CM))

        # Second lot on the same entry -> species mismatch -> fresh OPEN CA.
        lot2 = create_lot(entry["id"], species="COD", grade="B",
                          quantity_received_kg=50, harvest_country_code="NO",
                          catch_area_code="FAO27", vessel_name="FV Nord",
                          harvest_date="2026-07-21T00:00:00Z")
        ri01 = make_receiving_inspector_headers("ri-01")
        validate_success(api.create_species_verification(
            {"receipt_lot_id": lot2["id"], "test_method": "DNA_BARCODING",
             "sample_size": 4, "verified_species": "POLLOCK"}, ri01), 201)
        cas2, _ = validate_paginated(api.list_corrective_actions(
            CM, params={"receipt_lot_id": lot2["id"]}))
        return supplier, fin, cas2[0]["id"], cm01

    def test_escalate_recall_lot_cascade(self, api):
        """PRD: "Escalation creates a Recall with `corrective_action_id` set to
        the CA, the provided `reason` and scope, and status `INITIATED`. The
        CA's `recall_id` is set to the new recall's id. Every in-scope
        FinishedProductLot with status not already `RECALLED` transitions to
        `RECALLED`, each incrementing its version."

        Design: Difficulty/transitive_cascade/escalate_recall_lot_cascade_depth2
        """
        supplier, fin, ca_id, cm01 = self._full_released_lot_and_open_ca(api)
        escalated = validate_success(api.escalate_corrective_action(
            ca_id, "mislabeled species entered commerce", [fin["id"]], cm01))
        assert escalated["status"] == "ESCALATED"
        recall_id = escalated["recall_id"]
        assert recall_id

        recall = validate_success(api.get_recall(recall_id, CM))
        assert recall["status"] == "INITIATED"
        assert recall["corrective_action_id"] == ca_id

        fin_after = validate_success(api.get_finished_lot(fin["id"], CM))
        assert fin_after["status"] == "RECALLED"

    def test_escalate_decrements_supplier_open_ca_count(self, api):
        """PRD: "For supplier-linked CAs, `open_corrective_action_count`
        decrements by 1 (ESCALATED is no longer open) and risk recomputes."
        PRD risk formula: "The `risk_score` is 40% of the evaluation component
        plus 30% of the open penalty plus 30% of the history penalty, rounded
        half-up to 2 decimal places."

        Design: Difficulty/transitive_cascade/escalate_recall_lot_cascade_depth2
        """
        supplier, fin, ca_id, cm01 = self._full_released_lot_and_open_ca(api)
        validate_success(api.escalate_corrective_action(
            ca_id, "mislabeled species entered commerce", [fin["id"]], cm01))
        after = validate_success(api.get_supplier(supplier["id"], CM))
        assert after["open_corrective_action_count"] == 0
        # eval component 10 (overall 90); history 25 (one lifetime mismatch):
        # 0.4*10 + 0.3*0 + 0.3*25 = 11.50
        assert after["risk_score"] == pytest.approx(11.50, abs=0.005)


class TestRecallLifecycle:
    def test_recall_notify_then_terminal_lockdown(self, api):
        """PRD: "A `ComplianceManager` marks a recall as notified via the
        notify action, transitioning from `INITIATED` to `NOTIFIED` (terminal)
        and setting `notified_at`."
        A second notify targets no valid from-state: ERR_INVALID_STATE (409).

        Design: Corner/state_machines/recall_notify_then_terminal_lockdown
        """
        supplier, entry, lot, batch, reconciled = _reconciled_cod_batch(
            api, frn="FRN-S05", entry_number="E-S05")
        fin = create_finished_lot(batch["id"], 42.0)
        label = create_approved_label(species="COD",
                                      market_name="Pacific Cod",
                                      country_of_origin="US",
                                      keep_frozen_statement=True)
        get_success_data(api.apply_label(fin["id"], label["id"], PS))
        get_success_data(api.release_finished_lot(fin["id"], CM))

        cm01 = make_compliance_manager_headers("cm-01")
        ca = validate_success(api.create_corrective_action(
            {"source_type": "MANUAL", "processing_batch_id": batch["id"],
             "reason": "post-release audit finding"}, cm01), 201)
        escalated = get_success_data(api.escalate_corrective_action(
            ca["id"], "audit finding confirmed", [fin["id"]], cm01))
        recall_id = escalated["recall_id"]

        notified = validate_success(api.notify_recall(recall_id, CM))
        assert notified["status"] == "NOTIFIED"
        # notified_at is the current logical time (default clock:
        # 2026-08-01T00:00:00Z). Compare instants — PRD fixes the instant,
        # not the fractional-digit rendering of this field.
        assert is_iso8601_timestamp(notified["notified_at"])
        assert _parse_instant(notified["notified_at"]) == _parse_instant(
            "2026-08-01T00:00:00Z")

        resp = api.notify_recall(recall_id, CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
