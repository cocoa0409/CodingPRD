"""Recycle batch assembly: add/remove compensation, data gate, category and
routing gates, and the state-beats-safety error ordering (PRD §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_to_batch,
    new_active_policy,
    new_batch,
    new_recycler,
    remove_from_batch,
    scan_and_triage,
    setup_received_manifest,
    setup_triaged_item,
    ship_batch,
    validate_error,
    validate_success,
)


class TestBatchAddRemoveCompensation:
    def _setup(self):
        recycler = new_recycler(accepted_categories=["SERVER"],
                                daily_intake_capacity_kg=1000)
        ctx = setup_triaged_item(disposition="RECYCLE", category="SERVER",
                                 weight_kg=12.5, declared_grade="C",
                                 serial_number="SN-W1")
        batch = new_batch(recycler_id=recycler["id"])
        return recycler, ctx, batch

    def test_batch_add_then_remove_restores_totals(self, api, logistics_coordinator_headers):
        """PRD §3.7: "A new batch is `STAGING` with `gross_weight_kg` and `item_count` both zero; both are computed fields maintained automatically as items come and go."
        PRD §3.7: "Removal is the compensating mirror — allowed only while `STAGING` under the same `ERR_BATCH_NOT_STAGING` gate — returning the item `BATCHED` → `FOR_RECYCLE`, nulling its `recycle_batch_id`, recomputing totals, and incrementing the batch version; removal returns no content."

        Design: Difficulty/compensating_invariant/batch_item_add_then_remove_restores_weight
        """
        _recycler, ctx, batch = self._setup()
        assert batch["gross_weight_kg"] == pytest.approx(0.0)
        assert batch["item_count"] == 0

        batch = add_to_batch(batch["id"], ctx["item"]["id"])
        assert batch["gross_weight_kg"] == pytest.approx(12.5)
        assert batch["item_count"] == 1

        remove_from_batch(batch["id"], ctx["item"]["id"])
        batch = validate_success(api.get_recycle_batch(batch["id"],
                                                       logistics_coordinator_headers))
        assert batch["gross_weight_kg"] == pytest.approx(0.0)
        assert batch["item_count"] == 0

    def test_batch_remove_restores_item_routing_fields(self, api, logistics_coordinator_headers):
        """PRD §3.7: "Removal is the compensating mirror — allowed only while `STAGING` under the same `ERR_BATCH_NOT_STAGING` gate — returning the item `BATCHED` → `FOR_RECYCLE`, nulling its `recycle_batch_id`, recomputing totals, and incrementing the batch version; removal returns no content."
        PRD §3.4: "While triaged for recycling, an item carries a `recycle_batch_id` only once it has been placed into a batch; the field is null outside the `BATCHED` and `DOWNSTREAM` states."

        Design: Difficulty/compensating_invariant/batch_item_add_then_remove_restores_weight
        """
        _recycler, ctx, batch = self._setup()
        add_to_batch(batch["id"], ctx["item"]["id"])
        item = validate_success(api.get_item(ctx["item"]["id"], logistics_coordinator_headers))
        assert item["processing_status"] == "BATCHED"
        assert item["recycle_batch_id"] == batch["id"]

        remove_from_batch(batch["id"], ctx["item"]["id"])
        item = validate_success(api.get_item(ctx["item"]["id"], logistics_coordinator_headers))
        assert item["processing_status"] == "FOR_RECYCLE"
        assert item["recycle_batch_id"] is None


class TestBatchAddDataGate:
    def test_batch_add_unverified_data_item_rejected(self, api, logistics_coordinator_headers):
        """PRD §3.7: "Next the data gate: a data-bearing item must be `VERIFIED` — `ERR_DATA_SANITIZATION_UNVERIFIED` otherwise — while non-data-bearing items pass."

        Design: Corner/state_machines/data_gate_on_batch_add_unverified
        """
        new_active_policy(sanitization_methods_allowed=["NIST_CLEAR"])
        recycler = new_recycler(accepted_categories=["LAPTOP"], daily_intake_capacity_kg=1000)
        # Data-bearing item, never sanitized: data_status PENDING.
        ctx = setup_triaged_item(disposition="RECYCLE", data_bearing=True, declared_grade="B",
                                 serial_number="SN-DG1")
        batch = new_batch(recycler_id=recycler["id"])

        resp = api.add_batch_item(batch["id"], {"item_id": ctx["item"]["id"]},
                                  logistics_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_DATA_SANITIZATION_UNVERIFIED)
        assert resp.status_code == 422


class TestBatchAddCategoryAndRouting:
    def test_batch_add_unsupported_category_rejected(self, api, logistics_coordinator_headers):
        """PRD §3.7: "Then the recycler must actually accept the item's `category` in its `accepted_categories` (`ERR_RECYCLER_CATEGORY_UNSUPPORTED`), and finally the item itself must be recycle-routed, meaning `disposition` `RECYCLE` and `processing_status` `FOR_RECYCLE` (`ERR_ITEM_NOT_RECYCLE_ROUTED`)."

        Design: Corner/validations/recycler_category_unsupported_rejected
        """
        recycler = new_recycler(accepted_categories=["LAPTOP"], daily_intake_capacity_kg=1000)
        ctx = setup_triaged_item(disposition="RECYCLE", category="OTHER", weight_kg=1.0,
                                 declared_grade="D", serial_number="SN-CT1")
        batch = new_batch(recycler_id=recycler["id"])

        resp = api.add_batch_item(batch["id"], {"item_id": ctx["item"]["id"]},
                                  logistics_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_RECYCLER_CATEGORY_UNSUPPORTED)
        assert resp.status_code == 422

    def test_batch_add_non_recycle_item_rejected(self, api, logistics_coordinator_headers):
        """PRD §3.7: "Then the recycler must actually accept the item's `category` in its `accepted_categories` (`ERR_RECYCLER_CATEGORY_UNSUPPORTED`), and finally the item itself must be recycle-routed, meaning `disposition` `RECYCLE` and `processing_status` `FOR_RECYCLE` (`ERR_ITEM_NOT_RECYCLE_ROUTED`)."

        Design: Corner/errors/batch_add_non_recycle_item_rejected
        """
        recycler = new_recycler(accepted_categories=["LAPTOP"], daily_intake_capacity_kg=1000)
        # Category accepted and non-data-bearing: only the routing gate can fail.
        ctx = setup_triaged_item(disposition="RESALE", category="LAPTOP", declared_grade="A",
                                 serial_number="SN-NR1")
        batch = new_batch(recycler_id=recycler["id"])

        resp = api.add_batch_item(batch["id"], {"item_id": ctx["item"]["id"]},
                                  logistics_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_RECYCLE_ROUTED)
        assert resp.status_code == 422

        item = validate_success(api.get_item(ctx["item"]["id"], logistics_coordinator_headers))
        assert item["processing_status"] == "FOR_RESALE"
        batch = validate_success(api.get_recycle_batch(batch["id"], logistics_coordinator_headers))
        assert batch["item_count"] == 0


class TestBatchAddErrorOrdering:
    def _setup_shipped_batch_and_unverified_item(self, api):
        """Batch already IN_TRANSIT (state gate fails) plus a data-bearing,
        never-sanitized recycle-routed item (safety gate also fails)."""
        new_active_policy()
        recycler = new_recycler(accepted_categories=["OTHER", "LAPTOP"],
                                daily_intake_capacity_kg=1000)
        account, manifest = setup_received_manifest(declared_item_count=2)
        item_one = scan_and_triage(manifest["id"], "RECYCLE", serial_number="SN-P1",
                                   category="OTHER", weight_kg=1.0, declared_grade="C")
        item_two = scan_and_triage(manifest["id"], "RECYCLE", serial_number="SN-P2",
                                   category="LAPTOP", weight_kg=2.0, data_bearing=True,
                                   declared_grade="B")
        batch = new_batch(recycler_id=recycler["id"])
        batch = add_to_batch(batch["id"], item_one["id"])
        ship_batch(batch["id"])
        return {"account": account, "manifest": manifest, "recycler": recycler,
                "batch": batch, "item_two": item_two}

    def test_state_error_beats_safety_error_on_batch_add(self, api,
                                                         logistics_coordinator_headers):
        """PRD §3.7: "The batch must still be `STAGING`, or the add fails with `ERR_BATCH_NOT_STAGING`. Next the data gate: a data-bearing item must be `VERIFIED` — `ERR_DATA_SANITIZATION_UNVERIFIED` otherwise — while non-data-bearing items pass."
        PRD §2.6: "8.–11. Specialized state gates, in this order: `ERR_BATCH_NOT_STAGING`, then `ERR_MANIFEST_NOT_RECEIVED`, then `ERR_LISTING_NOT_ACTIVE`, then `ERR_SETTLEMENT_NOT_FINALIZED`."

        Design: Difficulty/priority_pair_validation_conflict/batch_add_item_state_error_beats_safety_error
        """
        ctx = self._setup_shipped_batch_and_unverified_item(api)
        resp = api.add_batch_item(ctx["batch"]["id"], {"item_id": ctx["item_two"]["id"]},
                                  logistics_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_STAGING)
        assert resp.status_code == 409

    def test_rejected_batch_add_leaves_item_for_recycle(self, api,
                                                        logistics_coordinator_headers):
        """PRD §3.7: "The batch must still be `STAGING`, or the add fails with `ERR_BATCH_NOT_STAGING`. Next the data gate: a data-bearing item must be `VERIFIED` — `ERR_DATA_SANITIZATION_UNVERIFIED` otherwise — while non-data-bearing items pass."

        Design: Difficulty/priority_pair_validation_conflict/batch_add_item_state_error_beats_safety_error
        """
        ctx = self._setup_shipped_batch_and_unverified_item(api)
        validate_error(api.add_batch_item(ctx["batch"]["id"],
                                          {"item_id": ctx["item_two"]["id"]},
                                          logistics_coordinator_headers),
                       ApiErrorId.ERR_BATCH_NOT_STAGING)

        item = validate_success(api.get_item(ctx["item_two"]["id"],
                                             logistics_coordinator_headers))
        assert item["processing_status"] == "FOR_RECYCLE"
        batch = validate_success(api.get_recycle_batch(ctx["batch"]["id"],
                                                       logistics_coordinator_headers))
        assert batch["item_count"] == 1
