"""Component inventory: append-only ledger, receipt validation, component OCC,
and the instantaneous vs forward-looking availability variants.

Covers PRD §2.6 (ledger and availability), §2.8 (component OCC), §3.4
(receipts).
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_component_invariants,
    assert_component_read,
    assert_inventory_event,
    create_client,
    create_revision,
    create_stocked_component,
    get_component,
    import_named_subscribers,
    create_run,
    put_bom,
    approve_revision,
    activate_plan,
    create_plan,
    bom_line,
    receipt_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

WAREHOUSE = TEST_USERS["warehouse_ops_headers"]


class TestInventoryLedger:
    def test_inventory_event_is_append_only_log(self):
        """PRD §3.4: "A successful receipt appends a `RECEIPT` inventory event
        whose `quantity_delta` is the received quantity and whose `run_id` is
        null". PRD §2.4: "A KitBOMLine and an InventoryEvent each carry only
        `id` and `created_at`: both `updated_at` and `version` are absent for
        them, because a BOM line set is replaced wholesale rather than patched
        and an inventory event is an immutable ledger entry."

        Design: Corner/entities/inventory_event_is_append_only_log
        """
        set_clock()
        component = create_stocked_component("CMP-EV", 0)
        validate_success(
            api_client.create_receipt(
                component["id"],
                receipt_payload(7, component["version"], note="initial load"),
                WAREHOUSE))
        resp = api_client.list_component_inventory_events(component["id"], WAREHOUSE)
        events, meta = validate_paginated(resp)
        assert len(events) == 1 and meta["total_count"] == 1, \
            f"one receipt must produce exactly one event, got {len(events)}"
        event = events[0]
        assert_inventory_event(event)
        assert event["event_type"] == "RECEIPT"
        assert event["quantity_delta"] == 7
        assert event["run_id"] is None, "receipts exist outside any run"


class TestReceiptValidation:
    def test_receipt_zero_quantity_rejected(self):
        """PRD §3.4: "The `quantity` must be a positive integer — anything else
        is rejected with `ERR_INVALID_QUANTITY` (HTTP 400)".

        Design: Corner/validations/receipt_zero_quantity_rejected
        """
        set_clock()
        component = create_stocked_component("CMP-V1", 0)
        resp = api_client.create_receipt(
            component["id"], receipt_payload(0, component["version"]), WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_INVALID_QUANTITY)
        after = get_component(component["id"])
        assert after["on_hand_units"] == 0, \
            "rejected receipt must not change on_hand_units"
        assert after["version"] == component["version"], \
            "rejected receipt must not bump the component version (no event appended)"


class TestReceiptOcc:
    def test_occ_receipt_stale_component_version_rejected(self):
        """PRD §2.8: "Recording a stock receipt against a component requires
        the request to carry `expected_component_version` holding the
        component's `version` as the client last observed it. A mismatch with
        the component's current `version` is likewise rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_receipt_stale_component_version_rejected
        """
        set_clock()
        component = create_stocked_component("CMP-X2", 0)
        observed_version = component["version"]
        accepted = validate_success(
            api_client.create_receipt(
                component["id"], receipt_payload(5, observed_version), WAREHOUSE))
        assert accepted["on_hand_units"] == 5

        replay = api_client.create_receipt(
            component["id"], receipt_payload(5, observed_version), WAREHOUSE)
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)

        after = get_component(component["id"])
        assert after["on_hand_units"] == 5, \
            "the stale receipt must append nothing"
        assert after["version"] == accepted["version"], \
            "the stale receipt must not advance the component version"

    def test_occ_receipt_current_version_succeeds(self):
        """PRD §3.4: "A successful receipt appends a `RECEIPT` inventory event
        whose `quantity_delta` is the received quantity and whose `run_id` is
        null, raises `on_hand_units` by that quantity, recomputes the
        component's availability figures and `stock_status`, and increments the
        component's `version` by one."

        Design: Corner/cross_cutting_layers/occ_receipt_current_version_succeeds
        """
        set_clock()
        component = create_stocked_component("CMP-X3", 0)
        before_version = component["version"]
        accepted = validate_success(
            api_client.create_receipt(
                component["id"], receipt_payload(8, before_version), WAREHOUSE))
        assert_component_read(accepted)
        assert accepted["on_hand_units"] == 8
        assert accepted["version"] == before_version + 1, (
            f"receipt must increment version by exactly one: "
            f"{before_version} -> {accepted['version']}"
        )


class TestAvailabilityVariants:
    def _setup_dv2(self, with_draft_run: bool):
        """Component 500 on hand; ACTIVE plan with BOM qty 2; 3 ACTIVE
        subscribers; optionally one DRAFT run for the period."""
        set_clock()
        client = create_client(name="DV2 Client", billing_email="dv2@acme.test")
        component = create_stocked_component("CMP-DV2", 500)
        plan = create_plan(client["id"], "PL-DV2", price_per_box_cents=1000,
                           shipping_weight_grams=500, name="DV2 Box")
        revision = create_revision(plan["id"], client["id"])
        put_bom(revision["id"], client["id"], [bom_line(component["id"], 2)])
        approve_revision(revision["id"], client["id"])
        activate_plan(plan["id"], client["id"])
        import_named_subscribers(plan["id"], client["id"], [
            ("dv2a@x.test", 1), ("dv2b@x.test", 1), ("dv2c@x.test", 1),
        ])
        run = create_run(plan["id"]) if with_draft_run else None
        return client, component, plan, run

    def test_availability_forward_looking_subtracts_draft_run_demand(self):
        """PRD §2.6: "`available_units` is `on_hand_units` minus
        `reserved_units` — the instantaneous view of what can be promised right
        now. `projected_available_units` is a forward-looking planning view:
        start from `available_units` and subtract the not-yet-reserved demand
        of every assembly run still in `DRAFT`." PRD §2.6: "Consequently,
        identical physical inventory shows a lower `projected_available_units`
        whenever a draft run exists, while `available_units` ignores draft-run
        demand entirely."

        Design: Difficulty/dual_variant_calc/availability_instantaneous_vs_forward_looking
        """
        _client, component, _plan, _run = self._setup_dv2(with_draft_run=True)
        data = validate_success(api_client.get_component(component["id"], WAREHOUSE))
        assert_component_read(data)
        assert data["available_units"] == 500, (
            f"instantaneous variant must ignore DRAFT-run demand: "
            f"expected 500, got {data['available_units']}"
        )
        assert data["projected_available_units"] == 494, (
            f"forward-looking variant must subtract 2 x 3 draft demand: "
            f"expected 494, got {data['projected_available_units']}"
        )
        assert data["stock_status"] == "OK"
        assert_component_invariants(data)

    def test_availability_variants_agree_without_draft_run(self):
        """PRD §2.6: "Only `DRAFT` runs feed this deduction: `LOCKED` runs are
        already reflected inside `reserved_units`, `KITTING` and `KITTED` runs
        are committed or in progress, and `CLOSED` or `CANCELLED` runs are
        excluded entirely."

        Design: Difficulty/dual_variant_calc/availability_instantaneous_vs_forward_looking
        """
        _client, component, _plan, _run = self._setup_dv2(with_draft_run=False)
        data = validate_success(api_client.get_component(component["id"], WAREHOUSE))
        assert_component_read(data)
        assert data["available_units"] == 500
        assert data["projected_available_units"] == 500, (
            f"with no DRAFT run the forward-looking variant deducts nothing: "
            f"expected 500, got {data['projected_available_units']}"
        )
        assert data["stock_status"] == "OK"
        assert_component_invariants(data)
