"""Processing batches: provisional vs final yield variants, per-lot
round-then-sum order, mass-balance reconciliation, OCC on complete, batch
input consumption gates, and compensating mass conservation."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_lot,
    add_input,
    assert_lot_mass_balance,
    complete_batch,
    create_accepted_lot,
    create_approved_supplier,
    create_batch,
    create_completed_batch,
    create_lot,
    create_processing_batch_payload,
    create_released_entry,
    get_success_data,
    record_histamine_pass,
    validate_error,
    validate_paginated,
    validate_success,
    verify_species,
)

CM = TEST_USERS["compliance_manager_headers"]
PS = TEST_USERS["processing_supervisor_headers"]
RI = TEST_USERS["receiving_inspector_headers"]
QA = TEST_USERS["qa_tech_headers"]


def _two_tuna_lots(api, frn="FRN-1001", entry_number="E-1001",
                   country="US", qty_a=100, grade_a="A", qty_b=50,
                   grade_b="B", goods=1000000, freight=50000,
                   duty_rate=0.03, total_weight=200):
    """Approved supplier + RELEASED entry + two ACCEPTED TUNA lots."""
    supplier = create_approved_supplier(name="Pacific Harvest Ltd",
                                        country=country, frn=frn)
    entry = create_released_entry(
        supplier["id"], entry_number=entry_number, species="TUNA",
        transport_mode="VESSEL", goods_value_cents=goods,
        freight_cost_cents=freight, duty_rate_pct=duty_rate,
        total_weight_kg=total_weight)
    lot_a = create_lot(entry["id"], species="TUNA", grade=grade_a,
                       quantity_received_kg=qty_a, vessel_name="FV Pacific",
                       catch_area_code="FAO77", receiving_temp_c=2.0)
    verify_species(lot_a["id"], "TUNA", test_method="DNA_BARCODING")
    record_histamine_pass(lot_a["id"])
    accept_lot(lot_a["id"])
    lot_b = create_lot(entry["id"], species="TUNA", grade=grade_b,
                       quantity_received_kg=qty_b, vessel_name="FV Pacific",
                       catch_area_code="FAO77", receiving_temp_c=2.0)
    verify_species(lot_b["id"], "TUNA", test_method="SENSORY")
    record_histamine_pass(lot_b["id"])
    accept_lot(lot_b["id"])
    return supplier, entry, lot_a, lot_b


def _cod_batch_with_input(api, frn="FRN-8002", entry_number="E-8002",
                          quantity_received_kg=100, consume_kg=100,
                          actual=42.0, trim=50.0, other=8.0,
                          product_form="FILLET",
                          complete_headers=None):
    """Full chain to a COMPLETED batch consuming one COD lot."""
    supplier = create_approved_supplier(name="Harbor Fresh", country="US",
                                        frn=frn)
    entry = create_released_entry(supplier["id"], entry_number=entry_number,
                                  species="COD", transport_mode="ROAD")
    lot = create_accepted_lot(entry["id"], species="COD",
                              quantity_received_kg=quantity_received_kg)
    batch = create_batch(target_species="COD", product_form=product_form)
    add_input(batch["id"], lot["id"], consume_kg)
    completed = complete_batch(batch["id"], actual, trim, other,
                               headers=complete_headers)
    return supplier, entry, lot, batch, completed


class TestProvisionalVsFinalYield:
    def test_batch_yield_provisional_vs_final_diverge(self, api):
        """PRD: "the per-lot provisional contribution `provisional_yield_kg`
        is computed as: the input `quantity_kg` multiplied by the base yield
        factor for the batch's `product_form` (0.42 for `FILLET` ...),
        multiplied by the grade factor for the lot's `grade` (1.00 for `A`,
        0.95 for `B` ...), with each per-lot contribution rounded half-up to 3
        decimal places **first**. The batch's `provisional_output_kg` is then
        the sum of these individually rounded `provisional_yield_kg` values."
        PRD: "`yield_pct_final` as 100 times `actual_output_kg` divided by
        `input_total_kg`, rounded half-up to 2 decimal places, and
        `yield_variance_pct` as the final percentage minus the provisional
        percentage, rounded half-up to 2 decimal places."

        Design: Difficulty/dual_variant_calc/batch_yield_provisional_vs_final_diverge
        """
        supplier, entry, lot_a, lot_b = _two_tuna_lots(api)
        batch = create_batch(target_species="TUNA", product_form="FILLET")
        add_input(batch["id"], lot_a["id"], 100)
        add_input(batch["id"], lot_b["id"], 50)

        completed = complete_batch(batch["id"], actual_output_kg=55.0,
                                   trim_waste_kg=80.0, other_waste_kg=15.0)
        # per-lot: round(100*0.42*1.00,3)=42.000; round(50*0.42*0.95,3)=19.950
        assert completed["input_total_kg"] == pytest.approx(150.000, abs=1e-6)
        assert completed["provisional_output_kg"] == pytest.approx(61.950,
                                                                   abs=1e-6)
        # 100 * 61.950 / 150 = 41.30
        assert completed["yield_pct_provisional"] == pytest.approx(41.30,
                                                                   abs=0.005)
        # 100 * 55.0 / 150 = 36.67 (round half up)
        assert completed["yield_pct_final"] == pytest.approx(36.67, abs=0.005)
        # 36.67 - 41.30 = -4.63
        assert completed["yield_variance_pct"] == pytest.approx(-4.63,
                                                                abs=0.005)
        assert completed["yield_pct_provisional"] != \
            completed["yield_pct_final"]

    def test_provisional_computed_before_completion(self, api):
        """PRD: "The provisional yield estimation runs on every input addition
        and removal." The batch exposes provisional outputs while still
        IN_PROCESS, before any measured output exists.

        Design: Difficulty/dual_variant_calc/batch_yield_provisional_vs_final_diverge
        """
        supplier, entry, lot_a, lot_b = _two_tuna_lots(api)
        batch = create_batch(target_species="TUNA", product_form="FILLET")
        add_input(batch["id"], lot_a["id"], 100)
        add_input(batch["id"], lot_b["id"], 50)
        in_process = validate_success(api.get_processing_batch(batch["id"], PS))
        assert in_process["status"] == "IN_PROCESS"
        assert in_process["input_total_kg"] == pytest.approx(150.000, abs=1e-6)
        assert in_process["provisional_output_kg"] == pytest.approx(61.950,
                                                                    abs=1e-6)
        assert in_process["yield_pct_provisional"] == pytest.approx(41.30,
                                                                    abs=0.005)


class TestPerLotRoundThenSum:
    def test_per_lot_round_then_sum_yield(self, api):
        """PRD: "with each per-lot contribution rounded half-up to 3 decimal
        places **first**. The batch's `provisional_output_kg` is then the sum
        of these individually rounded `provisional_yield_kg` values. Summing
        first and then rounding is forbidden — it produces different results."

        Design: Difficulty/combinatorial_formula/per_lot_round_then_sum_yield
        """
        supplier, entry, lot_a, lot_b = _two_tuna_lots(
            api, frn="FRN-3002", entry_number="E-3002", country="PA",
            qty_a=10.001, grade_a="A", qty_b=10.001, grade_b="A",
            goods=300000, freight=10000, duty_rate=0.0, total_weight=25)
        batch = create_batch(target_species="TUNA", product_form="LOIN")
        in_a = add_input(batch["id"], lot_a["id"], 10.001)
        in_b = add_input(batch["id"], lot_b["id"], 10.001)

        # round(10.001 * 0.55 * 1.00, 3) = round(5.50055, 3) = 5.501 per lot.
        assert in_a["provisional_yield_kg"] == pytest.approx(5.501, abs=1e-6)
        assert in_b["provisional_yield_kg"] == pytest.approx(5.501, abs=1e-6)

        batch_after = validate_success(api.get_processing_batch(batch["id"],
                                                                PS))
        # Round-then-sum: 5.501 + 5.501 = 11.002 (sum-then-round: 11.001).
        assert batch_after["provisional_output_kg"] == pytest.approx(11.002,
                                                                     abs=1e-6)
        assert batch_after["input_total_kg"] == pytest.approx(20.002, abs=1e-6)
        # 100 * 11.002 / 20.002 = 55.005 -> 55.00 round half up at 2dp? No:
        # 55.00499... -> 55.00.
        assert batch_after["yield_pct_provisional"] == pytest.approx(55.00,
                                                                     abs=0.005)

    def test_provisional_yield_uses_grade_factor(self, api):
        """PRD: "multiplied by the grade factor for the lot's `grade` (1.00
        for `A`, 0.95 for `B`, 0.88 for `C`)". A grade-B lot contributes less
        than a grade-A lot of the same weight in the same form.

        Design: Difficulty/combinatorial_formula/per_lot_round_then_sum_yield
        """
        supplier, entry, lot_a, lot_b = _two_tuna_lots(
            api, frn="FRN-3002B", entry_number="E-3002B", country="PA",
            qty_a=100, grade_a="A", qty_b=100, grade_b="C",
            goods=300000, freight=10000, duty_rate=0.0, total_weight=200)
        batch = create_batch(target_species="TUNA", product_form="PORTION")
        in_a = add_input(batch["id"], lot_a["id"], 100)
        in_b = add_input(batch["id"], lot_b["id"], 100)
        # A: round(100 * 0.48 * 1.00, 3) = 48.000
        assert in_a["provisional_yield_kg"] == pytest.approx(48.000, abs=1e-6)
        # C: round(100 * 0.48 * 0.88, 3) = 42.240
        assert in_b["provisional_yield_kg"] == pytest.approx(42.240, abs=1e-6)


class TestInputConsumptionGates:
    def test_insufficient_remaining_rejected(self, api):
        """PRD: "The quantity must not exceed the lot's `remaining_kg`;
        exceeding it yields `ERR_INSUFFICIENT_LOT_REMAINING` (HTTP 422)."

        Design: Corner/validations/insufficient_remaining_rejected
        """
        supplier = create_approved_supplier(name="Harbor Fresh", country="US",
                                            frn="FRN-V10")
        entry = create_released_entry(supplier["id"], entry_number="E-V10",
                                      species="COD")
        lot = create_accepted_lot(entry["id"], species="COD",
                                  quantity_received_kg=50)
        batch = create_batch(target_species="COD", product_form="FILLET")
        resp = api.add_batch_input(batch["id"],
                                   {"receipt_lot_id": lot["id"],
                                    "quantity_kg": 50.001}, PS)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LOT_REMAINING)
        lot_after = validate_success(api.get_receipt_lot(lot["id"], PS))
        assert lot_after["remaining_kg"] == pytest.approx(50.000, abs=1e-6)

    def test_species_mismatch_on_input_rejected(self, api):
        """PRD: "The species gate checks that the lot's effective species —
        `species_verified` if set, otherwise `species_declared` — equals the
        batch's `target_species`. A mismatch yields `ERR_SPECIES_MISMATCH`
        (HTTP 422)."

        Design: Corner/validations/insufficient_remaining_rejected
        """
        supplier = create_approved_supplier(name="Harbor Fresh", country="US",
                                            frn="FRN-V10B")
        entry = create_released_entry(supplier["id"], entry_number="E-V10B",
                                      species="COD")
        lot = create_accepted_lot(entry["id"], species="COD",
                                  quantity_received_kg=50)
        batch = create_batch(target_species="SALMON", product_form="FILLET")
        resp = api.add_batch_input(batch["id"],
                                   {"receipt_lot_id": lot["id"],
                                    "quantity_kg": 10}, PS)
        validate_error(resp, ApiErrorId.ERR_SPECIES_MISMATCH)

    def test_last_kg_consumption_auto_consumed(self, api):
        """PRD: "When a lot's `remaining_kg` reaches exactly 0 after a batch
        input addition, the system auto-transitions the lot from `ACCEPTED` to
        `CONSUMED` (terminal), incrementing the lot version."
        PRD: "The referenced lot must be in `ACCEPTED` status — otherwise
        `ERR_LOT_NOT_ACCEPTED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/last_kg_consumption_auto_consumed
        """
        supplier = create_approved_supplier(name="Harbor Fresh", country="US",
                                            frn="FRN-7002")
        entry = create_released_entry(supplier["id"], entry_number="E-7002",
                                      species="COD", goods_value_cents=50000,
                                      freight_cost_cents=2000,
                                      total_weight_kg=10)
        lot = create_accepted_lot(entry["id"], species="COD",
                                  quantity_received_kg=10)
        batch = create_batch(target_species="COD", product_form="PORTION")

        add_input(batch["id"], lot["id"], 10.000)
        after = validate_success(api.get_receipt_lot(lot["id"], PS))
        assert after["remaining_kg"] == pytest.approx(0, abs=1e-9)
        assert after["status"] == "CONSUMED"

        # A further 0.001 kg input hits the not-ACCEPTED gate.
        resp = api.add_batch_input(batch["id"],
                                   {"receipt_lot_id": lot["id"],
                                    "quantity_kg": 0.001}, PS)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_ACCEPTED)

    def test_consumed_lot_mass_balance_at_zero_remaining(self, api):
        """PRD: "On addition, the lot's `consumed_kg` increases by the input
        quantity and `remaining_kg` is recomputed as `quantity_accepted_kg`
        minus `consumed_kg`. If `remaining_kg` reaches exactly 0, the lot
        auto-transitions from `ACCEPTED` to `CONSUMED`."
        At the zero boundary the mass-balance identity
        consumed + remaining == quantity_accepted holds exactly.

        Design: Difficulty/boundary_precision_check/last_kg_consumption_auto_consumed
        """
        supplier = create_approved_supplier(name="Harbor Fresh", country="US",
                                            frn="FRN-7002B")
        entry = create_released_entry(supplier["id"], entry_number="E-7002B",
                                      species="COD", goods_value_cents=50000,
                                      freight_cost_cents=2000,
                                      total_weight_kg=10)
        lot = create_accepted_lot(entry["id"], species="COD",
                                  quantity_received_kg=10)
        batch = create_batch(target_species="COD", product_form="PORTION")
        add_input(batch["id"], lot["id"], 10.000)
        after = validate_success(api.get_receipt_lot(lot["id"], PS))
        assert after["consumed_kg"] == pytest.approx(10.000, abs=1e-9)
        assert after["remaining_kg"] == pytest.approx(0.000, abs=1e-9)
        assert_lot_mass_balance(after)
        assert after["status"] == "CONSUMED"

    def test_fk_reverse_filtered_list_batch_inputs(self, api):
        """PRD: "| GET | `/seafood/batch-input-lots` | List batch input rows;
        filter by `processing_batch_id` and/or `receipt_lot_id`; paginated |"
        Filtering by receipt_lot_id returns exactly the input rows consuming
        that lot.

        Design: Corner/endpoints/fk_reverse_filtered_list_batch_inputs
        """
        supplier = create_approved_supplier(name="Harbor Fresh", country="US",
                                            frn="FRN-P01")
        entry = create_released_entry(supplier["id"], entry_number="E-P01",
                                      species="COD")
        lot = create_accepted_lot(entry["id"], species="COD",
                                  quantity_received_kg=80)
        batch = create_batch(target_species="COD", product_form="FILLET")
        in_row = add_input(batch["id"], lot["id"], 30.000)

        rows, meta = validate_paginated(api.list_batch_inputs(
            PS, params={"receipt_lot_id": lot["id"]}))
        assert meta["total_count"] == 1
        row = rows[0]
        assert row["id"] == in_row["id"]
        assert row["processing_batch_id"] == batch["id"]
        assert row["quantity_kg"] == pytest.approx(30.000, abs=1e-6)
        # round(30 * 0.42 * 1.00, 3) = 12.600
        assert row["provisional_yield_kg"] == pytest.approx(12.600, abs=1e-6)


class TestMassConservation:
    def test_batch_input_add_remove_conserves_mass(self, api):
        """PRD: "On addition, the lot's `consumed_kg` increases by the input
        quantity and `remaining_kg` is recomputed as `quantity_accepted_kg`
        minus `consumed_kg`."
        PRD: "Removing a batch input (a compensating action) is allowed while
        the batch is `IN_PROCESS`. The lot's `consumed_kg` decreases by the
        removed quantity."

        Design: Difficulty/compensating_invariant/batch_input_add_remove_conserves_mass
        """
        supplier = create_approved_supplier(name="Harbor Fresh", country="US",
                                            frn="FRN-1001B")
        entry = create_released_entry(supplier["id"], entry_number="E-1001B",
                                      species="COD")
        lot = create_accepted_lot(entry["id"], species="COD",
                                  quantity_received_kg=80)
        batch = create_batch(target_species="COD", product_form="FILLET")

        in_row = add_input(batch["id"], lot["id"], 30.000)
        mid = validate_success(api.get_receipt_lot(lot["id"], PS))
        assert mid["consumed_kg"] == pytest.approx(30.000, abs=1e-6)
        assert mid["remaining_kg"] == pytest.approx(50.000, abs=1e-6)
        assert_lot_mass_balance(mid)

        validate_success(api.delete_batch_input(in_row["id"], PS))
        restored = validate_success(api.get_receipt_lot(lot["id"], PS))
        assert restored["consumed_kg"] == pytest.approx(0, abs=1e-9)
        assert restored["remaining_kg"] == pytest.approx(80.000, abs=1e-9)
        assert_lot_mass_balance(restored)

    def test_consumed_lot_returns_to_accepted_on_delete(self, api):
        """PRD: "If the lot had been auto-consumed (`CONSUMED`) and its
        `remaining_kg` is now greater than 0, it transitions back to
        `ACCEPTED`."

        Design: Difficulty/compensating_invariant/batch_input_add_remove_conserves_mass
        """
        supplier = create_approved_supplier(name="Harbor Fresh", country="US",
                                            frn="FRN-1001C")
        entry = create_released_entry(supplier["id"], entry_number="E-1001C",
                                      species="COD")
        lot = create_accepted_lot(entry["id"], species="COD",
                                  quantity_received_kg=10)
        batch = create_batch(target_species="COD", product_form="FILLET")
        in_row = add_input(batch["id"], lot["id"], 10.000)
        consumed = validate_success(api.get_receipt_lot(lot["id"], PS))
        assert consumed["status"] == "CONSUMED"

        validate_success(api.delete_batch_input(in_row["id"], PS))
        restored = validate_success(api.get_receipt_lot(lot["id"], PS))
        assert restored["status"] == "ACCEPTED"
        assert restored["remaining_kg"] == pytest.approx(10.000, abs=1e-9)


class TestBatchCompletion:
    def test_complete_empty_batch_rejected(self, api):
        """PRD: "The batch must be `IN_PROCESS` and must have at least 1 input
        row — zero inputs yields `ERR_BATCH_HAS_NO_INPUTS` (HTTP 422)."

        Design: Corner/errors/complete_empty_batch_rejected
        """
        batch = create_batch(target_species="COD", product_form="FILLET")
        resp = api.complete_batch(
            batch["id"],
            {"expected_batch_version": batch["version"],
             "actual_output_kg": 0, "trim_waste_kg": 0, "other_waste_kg": 0},
            PS)
        validate_error(resp, ApiErrorId.ERR_BATCH_HAS_NO_INPUTS)
        after = validate_success(api.get_processing_batch(batch["id"], PS))
        assert after["status"] == "IN_PROCESS"

    def test_occ_stale_version_on_complete(self, api):
        """PRD: "**Completing a ProcessingBatch** requires
        `expected_batch_version` in the request payload, carrying the client's
        last observed `version` of the batch. If the batch's current `version`
        does not match, the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_complete
        """
        supplier, entry, lot, batch, completed = _cod_batch_with_input(
            api, frn="FRN-X01", entry_number="E-X01")
        assert completed["status"] == "COMPLETED"
        stale_version = completed["version"]

        # Reopen (bumps version), then replay the stale version on complete.
        get_success_data(api.reopen_batch(batch["id"], PS))
        resp = api.complete_batch(
            batch["id"],
            {"expected_batch_version": stale_version,
             "actual_output_kg": 42.0, "trim_waste_kg": 50.0,
             "other_waste_kg": 8.0},
            PS)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_complete_with_fresh_version_after_reopen(self, api):
        """PRD: "A `COMPLETED` batch may be reopened by a `ProcessingSupervisor`
        only if no FinishedProductLot of this batch has status `RELEASED` or
        `RECALLED`. Reopening transitions the batch back to `IN_PROCESS`."
        After reopen, completion with the then-current version succeeds.

        Design: Corner/cross_cutting_layers/occ_stale_version_on_complete
        """
        supplier, entry, lot, batch, completed = _cod_batch_with_input(
            api, frn="FRN-X01", entry_number="E-X01")
        get_success_data(api.reopen_batch(batch["id"], PS))
        recompleted = complete_batch(batch["id"], 42.0, 50.0, 8.0)
        assert recompleted["status"] == "COMPLETED"
        assert recompleted["version"] > completed["version"]


class TestReconciliation:
    def test_reconcile_mass_imbalance_rejected(self, api):
        """PRD: "The mass-balance invariant requires `input_total_kg` to
        exactly equal the sum of `actual_output_kg`, `trim_waste_kg`, and
        `other_waste_kg` — exact equality at 3 decimal places. Violation yields
        `ERR_MASS_IMBALANCE` (HTTP 422)."

        Design: Corner/validations/reconcile_mass_imbalance_rejected
        """
        supplier = create_approved_supplier(name="Pacific Harvest Ltd",
                                            country="JP", frn="FRN-V05")
        entry = create_released_entry(
            supplier["id"], entry_number="E-V05", species="TUNA",
            transport_mode="VESSEL", goods_value_cents=1000000,
            freight_cost_cents=50000, duty_rate_pct=0.03, total_weight_kg=100)
        lot = create_lot(entry["id"], species="TUNA", quantity_received_kg=100,
                         ice_deduction_pct=2.5, vessel_name="FV Pacific",
                         catch_area_code="FAO77", receiving_temp_c=2.0)
        verify_species(lot["id"], "TUNA", test_method="DNA_BARCODING")
        record_histamine_pass(lot["id"])
        accept_lot(lot["id"])

        batch = create_batch(target_species="TUNA", product_form="FILLET")
        add_input(batch["id"], lot["id"], 97.5)
        complete_batch(batch["id"], actual_output_kg=40.0, trim_waste_kg=45.0,
                       other_waste_kg=12.4)
        # 97.500 != 40.0 + 45.0 + 12.4 == 97.400
        resp = api.reconcile_batch(batch["id"], PS)
        validate_error(resp, ApiErrorId.ERR_MASS_IMBALANCE)
        after = validate_success(api.get_processing_batch(batch["id"], PS))
        assert after["status"] == "COMPLETED"

    def test_reconcile_succeeds_at_exact_mass_balance(self, api):
        """PRD: "The mass-balance invariant requires `input_total_kg` to
        exactly equal the sum of `actual_output_kg`, `trim_waste_kg`, and
        `other_waste_kg` — exact equality at 3 decimal places."
        PRD: "On reconciliation, the batch transitions to `RECONCILED`
        (terminal)."

        Design: Corner/validations/reconcile_mass_imbalance_rejected
        """
        supplier, entry, lot, batch, completed = _cod_batch_with_input(
            api, frn="FRN-V05B", entry_number="E-V05B",
            actual=42.0, trim=50.0, other=8.0)
        # 100.000 == 42.0 + 50.0 + 8.0 exactly.
        reconciled = validate_success(api.reconcile_batch(batch["id"], PS))
        assert reconciled["status"] == "RECONCILED"


class TestYieldVarianceGate:
    def test_yield_variance_exceeded_rejected(self, api):
        """PRD: "If the absolute value of `yield_variance_pct` exceeds 5.0, a
        CorrectiveAction is auto-created with `source_type` `YIELD_VARIANCE`,
        `processing_batch_id` set to the batch, `supplier_id` null, and
        `opened_by` set to the requesting `X-User-ID`."
        PRD: "If the absolute value of `yield_variance_pct` exceeds 5.0, a
        CorrectiveAction with `source_type` `YIELD_VARIANCE` for this batch
        with status `RESOLVED` must exist; otherwise
        `ERR_YIELD_VARIANCE_EXCEEDED` (HTTP 422)."

        Design: Corner/errors/yield_variance_exceeded_rejected
        """
        from test_helpers import make_processing_supervisor_headers
        supplier = create_approved_supplier(name="Pacific Harvest Ltd",
                                            country="JP", frn="FRN-E02")
        entry = create_released_entry(
            supplier["id"], entry_number="E-E02", species="TUNA",
            transport_mode="VESSEL", goods_value_cents=1000000,
            freight_cost_cents=50000, duty_rate_pct=0.03, total_weight_kg=100)
        lot = create_lot(entry["id"], species="TUNA", quantity_received_kg=100,
                         ice_deduction_pct=2.5, vessel_name="FV Pacific",
                         catch_area_code="FAO77", receiving_temp_c=2.0)
        verify_species(lot["id"], "TUNA", test_method="DNA_BARCODING")
        record_histamine_pass(lot["id"])
        accept_lot(lot["id"])

        batch = create_batch(target_species="TUNA", product_form="FILLET")
        add_input(batch["id"], lot["id"], 97.5)
        ps01 = make_processing_supervisor_headers("ps-01")
        completed = complete_batch(batch["id"], actual_output_kg=30.0,
                                   trim_waste_kg=55.0, other_waste_kg=12.5,
                                   headers=ps01)
        # provisional: round(97.5*0.42,3)=40.950 -> 100*40.950/97.5 = 42.00
        # final: 100*30/97.5 = 30.77 -> variance -11.23
        assert completed["yield_pct_final"] == pytest.approx(30.77, abs=0.005)
        assert completed["yield_variance_pct"] == pytest.approx(-11.23,
                                                                abs=0.005)

        cas, meta = validate_paginated(api.list_corrective_actions(
            CM, params={"processing_batch_id": batch["id"]}))
        assert meta["total_count"] == 1
        assert cas[0]["source_type"] == "YIELD_VARIANCE"
        assert cas[0]["status"] == "OPEN"
        assert cas[0]["opened_by"] == "ps-01"

        # Mass is balanced (97.5 == 30+55+12.5) but the CA is unresolved.
        resp = api.reconcile_batch(batch["id"], PS)
        validate_error(resp, ApiErrorId.ERR_YIELD_VARIANCE_EXCEEDED)

    def test_yield_variance_reconcile_succeeds_after_ca_resolved(self, api):
        """PRD: "If the absolute value of `yield_variance_pct` exceeds 5.0, a
        CorrectiveAction with `source_type` `YIELD_VARIANCE` for this batch
        with status `RESOLVED` must exist; otherwise
        `ERR_YIELD_VARIANCE_EXCEEDED` (HTTP 422)."

        Design: Corner/errors/yield_variance_exceeded_rejected
        """
        from test_helpers import (
            make_compliance_manager_headers,
            make_processing_supervisor_headers,
        )
        supplier, entry, lot, batch, completed = _cod_batch_with_input(
            api, frn="FRN-E02B", entry_number="E-E02B",
            actual=30.0, trim=55.0, other=15.0,
            complete_headers=make_processing_supervisor_headers("ps-01"))
        # provisional 42.000 -> 42.00; final 30.00; variance -12.00 > 5.
        assert abs(completed["yield_variance_pct"]) > 5.0

        cas, _ = validate_paginated(api.list_corrective_actions(
            CM, params={"processing_batch_id": batch["id"]}))
        ca_id = cas[0]["id"]
        cm01 = make_compliance_manager_headers("cm-01")
        get_success_data(api.investigate_corrective_action(ca_id, cm01))
        get_success_data(api.resolve_corrective_action(
            ca_id, "reworked trim loss", cm01))

        reconciled = validate_success(api.reconcile_batch(batch["id"], PS))
        assert reconciled["status"] == "RECONCILED"
