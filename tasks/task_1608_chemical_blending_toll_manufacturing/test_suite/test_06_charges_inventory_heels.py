"""Batch charges, consignment inventory reconciliation, cancel compensation,
and heel-disposal manifest compliance (PRD §3.4, §3.6, §3.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_batch_charge,
    assert_lot,
    assert_lot_balances,
    create_and_post_heel_disposal,
    get_lot,
    post_batch_charge,
    recipe_component,
    setup_batch_context,
    setup_batch_in_hold_qa,
    setup_released_batch,
    validate_error,
    validate_paginated,
    validate_success,
)

SCHED = TEST_USERS["batch_scheduler_headers"]
OPERATOR = TEST_USERS["tank_operator_headers"]
QM = TEST_USERS["quality_manager_headers"]


class TestChargeCompleteness:
    def test_start_charging_with_incomplete_charges_rejected(self, api):
        """PRD §3.6: "Starting charging moves the batch from `RELEASED` to
        `CHARGING` and requires the charge book to be complete: exactly one
        charge per recipe component, each drawn from a lot whose
        `material_code` matches that component's and owned by the batch's
        customer (otherwise `ERR_INCOMPLETE_CHARGES`, HTTP 409)."

        Design: Corner/errors/incomplete_charges_returns_err
        """
        ctx = setup_released_batch(
            materials=[
                {"material_code": "A", "ghs_class": "NON_HAZ",
                 "quantity_kg_received": 500},
                {"material_code": "B", "ghs_class": "NON_HAZ",
                 "quantity_kg_received": 500},
            ],
            components=[recipe_component("A", 60.0, 1),
                        recipe_component("B", 40.0, 2)])
        # Charge only component A; component B is never charged.
        post_batch_charge(ctx["customer"]["id"], ctx["batch"]["id"],
                          ctx["lots"]["A"]["id"], charge_order=1,
                          charged_qty_kg=60)
        resp = api.start_charging(ctx["customer"]["id"], ctx["batch"]["id"],
                                  OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INCOMPLETE_CHARGES)


class TestChargeCommitCascade:
    def _setup_capped_lot(self):
        return setup_released_batch(lot_quantity_kg=300, batch_size_l=100)

    def test_overcommit_beyond_available_rejected(self, api):
        """PRD §3.6: "the promised mass may not exceed the lot's
        `quantity_kg_available` (else `ERR_INSUFFICIENT_LOT_QUANTITY`)".

        Design: Difficulty/transitive_cascade/charge_commit_cascades_lot_recompute_and_capacity_validation
        """
        ctx = self._setup_capped_lot()
        lot = ctx["lots"]["M-A"]
        post_batch_charge(ctx["customer"]["id"], ctx["batch"]["id"],
                          lot["id"], charge_order=1, charged_qty_kg=250)
        # Only 50 kg remains available; committing another 100 must fail.
        resp = api.create_batch_charge(
            ctx["customer"]["id"], ctx["batch"]["id"],
            {"raw_material_lot_id": lot["id"], "charge_order": 1,
             "charged_qty_kg": 100},
            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LOT_QUANTITY)

    def test_failed_charge_leaves_lot_balances_unchanged(self, api):
        """PRD §3.4: "The spendable balance `quantity_kg_available` is then
        `quantity_kg_on_hand` minus `quantity_kg_committed`." PRD §3.6: "Each
        committed charge is created in `COMMITTED` status, raises the lot's
        `quantity_kg_committed` by the promised mass with a lot `version`
        increment" — a rejected charge commits nothing.

        Design: Difficulty/transitive_cascade/charge_commit_cascades_lot_recompute_and_capacity_validation
        """
        ctx = self._setup_capped_lot()
        customer_id, lot_id = ctx["customer"]["id"], ctx["lots"]["M-A"]["id"]
        post_batch_charge(customer_id, ctx["batch"]["id"], lot_id,
                          charge_order=1, charged_qty_kg=250)
        resp = api.create_batch_charge(
            customer_id, ctx["batch"]["id"],
            {"raw_material_lot_id": lot_id, "charge_order": 1,
             "charged_qty_kg": 100},
            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LOT_QUANTITY)

        lot = get_lot(customer_id, lot_id)
        assert_lot_balances(lot, on_hand=300, committed=250, available=50)


class TestConsignmentReconciliation:
    def _setup_two_lots(self, api):
        ctx = setup_released_batch(
            materials=[
                {"material_code": "SOLV", "ghs_class": "NON_HAZ",
                 "quantity_kg_received": 1000},
                {"material_code": "SOLV2", "ghs_class": "NON_HAZ",
                 "quantity_kg_received": 500},
            ],
            components=[recipe_component("SOLV", 100.0, 1)],
            batch_size_l=300)
        return ctx

    def test_lot_balances_after_first_commits(self, api):
        """PRD §3.4: "The committed balance `quantity_kg_committed` is the sum
        of `charged_qty_kg` across the lot's charge rows whose own status is
        `COMMITTED` — exactly the draws promised to batches still in flight."
        and "The spendable balance `quantity_kg_available` is then
        `quantity_kg_on_hand` minus `quantity_kg_committed`."

        Design: Difficulty/dual_variant_calc/lot_available_kg_consignment_reconciliation
        """
        ctx = self._setup_two_lots(api)
        customer_id = ctx["customer"]["id"]
        lot_a, lot_b = ctx["lots"]["SOLV"], ctx["lots"]["SOLV2"]
        post_batch_charge(customer_id, ctx["batch"]["id"], lot_a["id"],
                          charge_order=1, charged_qty_kg=200)
        post_batch_charge(customer_id, ctx["batch"]["id"], lot_b["id"],
                          charge_order=1, charged_qty_kg=100)

        after_a = get_lot(customer_id, lot_a["id"])
        assert_lot(after_a)
        assert_lot_balances(after_a, on_hand=1000, committed=200, available=800)
        after_b = get_lot(customer_id, lot_b["id"])
        assert_lot_balances(after_b, on_hand=500, committed=100, available=400)

    def test_lot_balances_after_additional_commit(self, api):
        """PRD §3.4: "The committed balance `quantity_kg_committed` is the sum
        of `charged_qty_kg` across the lot's charge rows whose own status is
        `COMMITTED`" and "The on-hand balance `quantity_kg_on_hand` is
        `quantity_kg_received` minus the mass consumed (the sum of
        `charged_qty_kg` over the lot's `CONSUMED` charge rows) minus the mass
        sent to waste (the sum of `heel_disposed_kg` over the lot's `POSTED`
        heel disposal records)."

        Design: Difficulty/dual_variant_calc/lot_available_kg_consignment_reconciliation
        """
        ctx = self._setup_two_lots(api)
        customer_id = ctx["customer"]["id"]
        lot_a, lot_b = ctx["lots"]["SOLV"], ctx["lots"]["SOLV2"]
        post_batch_charge(customer_id, ctx["batch"]["id"], lot_a["id"],
                          charge_order=1, charged_qty_kg=200)
        post_batch_charge(customer_id, ctx["batch"]["id"], lot_b["id"],
                          charge_order=1, charged_qty_kg=100)
        post_batch_charge(customer_id, ctx["batch"]["id"], lot_a["id"],
                          charge_order=1, charged_qty_kg=50)

        after_a = get_lot(customer_id, lot_a["id"])
        assert_lot_balances(after_a, on_hand=1000, committed=250, available=750)
        after_b = get_lot(customer_id, lot_b["id"])
        assert_lot_balances(after_b, on_hand=500, committed=100, available=400)

    def test_lot_available_immediately_reflects_commit(self, api):
        """PRD §1: "The design favors immediate consistency: every derived
        quantity described here is reconciled at the moment the underlying
        event occurs". PRD §3.4: "The spendable balance
        `quantity_kg_available` is then `quantity_kg_on_hand` minus
        `quantity_kg_committed`."

        Design: Corner/consistency_model/lot_available_immediately_reflects_commit
        """
        ctx = setup_released_batch(lot_quantity_kg=100, batch_size_l=50)
        customer_id, lot_id = ctx["customer"]["id"], ctx["lots"]["M-A"]["id"]
        post_batch_charge(customer_id, ctx["batch"]["id"], lot_id,
                          charge_order=1, charged_qty_kg=30)
        lot = get_lot(customer_id, lot_id)
        assert lot["quantity_kg_available"] == 70, (
            f"Availability must reflect the commit immediately, got "
            f"{lot['quantity_kg_available']}")


class TestCancelCompensation:
    def test_cancel_restores_lot_available_balance(self, api):
        """PRD §3.6: "from `RELEASED` the tank cascades from `RESERVED` back to
        `AVAILABLE` with `occupied_by_batch_id` cleared but `cleaning_state`
        and `last_product_ghs` untouched, since no material was ever drawn,
        and any `COMMITTED` charges flip to `RELEASED` with lot quantities
        reconciled."

        Design: Difficulty/compensating_invariant/charge_commit_then_cancel_restores_lot_available_invariant
        """
        ctx = setup_released_batch(lot_quantity_kg=400, batch_size_l=100)
        customer_id, lot_id = ctx["customer"]["id"], ctx["lots"]["M-A"]["id"]
        before = get_lot(customer_id, lot_id)
        assert_lot_balances(before, on_hand=400, committed=0, available=400)

        post_batch_charge(customer_id, ctx["batch"]["id"], lot_id,
                          charge_order=1, charged_qty_kg=150)
        cancelled = validate_success(api.cancel_batch_job(
            customer_id, ctx["batch"]["id"], SCHED))
        assert cancelled["status"] == "CANCELLED"

        after = get_lot(customer_id, lot_id)
        assert_lot_balances(after, on_hand=400, committed=0, available=400)

    def test_cancel_marks_charge_released_and_frees_tank(self, api):
        """PRD §3.6: "any `COMMITTED` charges flip to `RELEASED` with lot
        quantities reconciled" and "from `RELEASED` the tank cascades from
        `RESERVED` back to `AVAILABLE` with `occupied_by_batch_id` cleared".

        Design: Difficulty/compensating_invariant/charge_commit_then_cancel_restores_lot_available_invariant
        """
        ctx = setup_released_batch(lot_quantity_kg=400, batch_size_l=100)
        customer_id, lot_id = ctx["customer"]["id"], ctx["lots"]["M-A"]["id"]
        charge = post_batch_charge(customer_id, ctx["batch"]["id"], lot_id,
                                   charge_order=1, charged_qty_kg=150)
        assert charge["status"] == "COMMITTED"

        validate_success(api.cancel_batch_job(customer_id, ctx["batch"]["id"],
                                              SCHED))
        charge_after = validate_success(api.get_batch_charge(
            customer_id, ctx["batch"]["id"], charge["id"], QM))
        assert_batch_charge(charge_after)
        assert charge_after["status"] == "RELEASED"

        tank_after = validate_success(api.get_tank(ctx["tank"]["id"], QM))
        assert tank_after["operational_state"] == "AVAILABLE"
        assert tank_after["occupied_by_batch_id"] is None

    def test_cancel_from_released_reverts_tank_without_contamination(
            self, api):
        """PRD §3.6: "from `RELEASED` the tank cascades from `RESERVED` back to
        `AVAILABLE` with `occupied_by_batch_id` cleared but `cleaning_state`
        and `last_product_ghs` untouched, since no material was ever drawn".

        Design: Difficulty/non_linear_state_machine/batch_job_reject_qa_and_cancel_revert_paths
        """
        ctx = setup_released_batch(batch_size_l=200)
        tank_reserved = validate_success(api.get_tank(ctx["tank"]["id"], QM))
        assert tank_reserved["operational_state"] == "RESERVED"

        cancelled = validate_success(api.cancel_batch_job(
            ctx["customer"]["id"], ctx["batch"]["id"], SCHED))
        assert cancelled["status"] == "CANCELLED"

        tank_after = validate_success(api.get_tank(ctx["tank"]["id"], QM))
        assert tank_after["operational_state"] == "AVAILABLE"
        assert tank_after["occupied_by_batch_id"] is None
        # No material was drawn, so no contamination was recorded.
        assert tank_after["last_product_ghs"] is None
        assert tank_after["cleaning_state"] == "CLEAN_VALIDATED"

    def test_cancel_from_charging_rejected(self, api):
        """PRD §3.6: "Cancellation by a `BatchScheduler` is permitted only from
        `INTAKE` or `RELEASED`"; any other source state fails the §2.9
        "source-state validity for the requested transition
        (`ERR_INVALID_STATE`)" check.

        Design: Corner/state_machines/cancel_from_charging_returns_invalid_state
        """
        ctx = setup_released_batch(lot_quantity_kg=500, batch_size_l=100)
        post_batch_charge(ctx["customer"]["id"], ctx["batch"]["id"],
                          ctx["lots"]["M-A"]["id"], charge_order=1,
                          charged_qty_kg=100)
        started = validate_success(api.start_charging(
            ctx["customer"]["id"], ctx["batch"]["id"], OPERATOR))
        assert started["status"] == "CHARGING"

        resp = api.cancel_batch_job(ctx["customer"]["id"], ctx["batch"]["id"],
                                    SCHED)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestHeelManifestCompliance:
    def test_post_heel_disposal_without_manifest_rejected(self, api):
        """PRD §3.9: "when `heel_disposed_kg` is positive, `disposal_method`
        must be present and `waste_manifest_number` non-empty (else
        `ERR_WASTE_MANIFEST_REQUIRED`, HTTP 422)."

        Design: Corner/errors/heel_disposal_without_manifest_returns_err
        """
        ctx = setup_batch_in_hold_qa(lot_quantity_kg=500, batch_size_l=100,
                                     charge_qty_kg=100)
        customer_id = ctx["customer"]["id"]
        lot_id = ctx["lots"]["M-A"]["id"]
        record = validate_success(api.create_heel_disposal(
            customer_id, ctx["batch"]["id"],
            {"raw_material_lot_id": lot_id, "heel_returned_kg": 0,
             "heel_disposed_kg": 5, "disposed_at": "2026-09-01T11:00:00Z"},
            OPERATOR), 201)
        resp = api.post_heel_disposal(customer_id, ctx["batch"]["id"],
                                      record["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_WASTE_MANIFEST_REQUIRED)
