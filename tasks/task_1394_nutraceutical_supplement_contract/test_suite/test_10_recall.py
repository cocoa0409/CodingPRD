"""Recall initiation, synchronous trace cascade, and recall closure."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_recall_event,
    close_recall_event,
    create_material_lot,
    create_raw_material,
    create_recall_event,
    create_released_lot,
    get_batch,
    get_customer,
    get_material_lot,
    get_order,
    setup_batch_at_stage,
    setup_two_released_batches_same_lot,
    validate_error,
    validate_success,
)

QA = TEST_USERS["qa_manager_headers"]


class TestRecallScopeGates:
    def test_recall_on_quarantine_lot_rejected(self, api):
        """PRD §3.8: "For a `MATERIAL_LOT` scope, the named lot must be `RELEASED`
        (`ERR_LOT_STATE` otherwise)".

        Design: Corner/state_machines/recall_on_quarantine_lot_rejected
        """
        material = create_raw_material("VitC", "NONE")
        lot = create_material_lot(material["id"], qty_received=100000)
        assert lot["status"] == "QUARANTINE"

        resp = api.create_recall(
            {"scope_type": "MATERIAL_LOT", "scope_id": lot["id"], "reason": "test"},
            QA,
        )
        validate_error(resp, ApiErrorId.ERR_LOT_STATE)
        assert resp.status_code == 409

    def test_batch_scope_recall_on_prerelease_batch_rejected(self, api):
        """PRD §3.8: "For a `BATCH` scope, the named batch must itself be `RELEASED`
        — otherwise the initiation is rejected with `ERR_BATCH_STATE`".

        Design: Corner/state_machines/batch_scope_recall_on_prerelease_batch_rejected
        """
        ctx = setup_batch_at_stage("COMPLETED")
        assert ctx["batch"]["quality_status"] == "PENDING_QC"

        resp = api.create_recall(
            {"scope_type": "BATCH", "scope_id": ctx["batch"]["id"],
             "reason": "deviation"},
            QA,
        )
        validate_error(resp, ApiErrorId.ERR_BATCH_STATE)
        assert resp.status_code == 409


class TestRecallLifecycle:
    def test_recall_close_twice_rejected(self, api):
        """PRD §3.8: "closing requires the event to be in `TRACED` status
        (`ERR_RECALL_STATE` otherwise) and moves it to the terminal `CLOSED`
        status."

        Design: Corner/state_machines/recall_close_twice_rejected
        """
        material = create_raw_material("VitC", "NONE")
        lot = create_released_lot(material["id"], qty_received=100000)
        recall = create_recall_event("MATERIAL_LOT", lot["id"])
        assert recall["status"] == "TRACED"

        closed = close_recall_event(recall["id"])
        assert closed["status"] == "CLOSED"

        resp = api.close_recall(recall["id"], {}, QA)
        validate_error(resp, ApiErrorId.ERR_RECALL_STATE)
        assert resp.status_code == 409


class TestLotRecallCascade:
    def test_lot_recall_transitions_consuming_released_batches(self, api):
        """PRD §3.8: "the lot moves to the terminal `RECALLED` status, and every
        batch holding an `ACTIVE` consumption of that lot whose `quality_status` is
        `RELEASED` transitions to `RECALLED`, processed in ascending order of batch
        creation time." and "The event's `affected_batch_count` records how many
        batches the cascade transitioned."
        PRD §3.8: "the RecallEvent is created in `INITIATED` and immediately walks
        to `TRACED` as the cascade runs."

        Design: Difficulty/transitive_cascade/recall_cascade_lot_to_batches_to_orders
        """
        ctx, run1, run2 = setup_two_released_batches_same_lot(
            clock="2026-08-01T00:00:00Z"
        )

        resp = api.create_recall(
            {"scope_type": "MATERIAL_LOT", "scope_id": ctx["lot"]["id"],
             "reason": "supplier contamination"},
            QA,
        )
        recall = validate_success(resp, 201)
        assert_recall_event(recall)
        assert recall["status"] == "TRACED"
        assert recall["affected_batch_count"] == 2

        assert get_batch(run1["batch"]["id"])["quality_status"] == "RECALLED"
        assert get_batch(run2["batch"]["id"])["quality_status"] == "RECALLED"
        assert get_material_lot(ctx["lot"]["id"])["status"] == "RECALLED"

    def test_lot_recall_flags_orders_and_counts_customer(self, api):
        """PRD §3.8: "Each batch so transitioned sets its parent order's
        `recall_flag` to true and refreshes the owning customer's
        `open_recall_count` to the count of that customer's orders now flagged."
        PRD §2.12: "The `open_recall_count` is the count of that customer's orders
        whose `recall_flag` is true."

        Design: Difficulty/transitive_cascade/recall_cascade_lot_to_batches_to_orders
        """
        ctx, run1, run2 = setup_two_released_batches_same_lot(
            clock="2026-08-01T00:00:00Z"
        )

        resp = api.create_recall(
            {"scope_type": "MATERIAL_LOT", "scope_id": ctx["lot"]["id"],
             "reason": "supplier contamination"},
            QA,
        )
        validate_success(resp, 201)

        assert get_order(run1["mo"]["id"])["recall_flag"] is True
        assert get_order(run2["mo"]["id"])["recall_flag"] is True
        customer = get_customer(ctx["customer"]["id"])
        assert customer["open_recall_count"] == 2
