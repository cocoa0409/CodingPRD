"""ADC pockets: ledger replay, dispense gates, counts, waste witnessing (PRD §3.6)."""
from test_helpers import (
    assert_pocket_ledger_consistent,
    count_payload,
    create_drug,
    create_patient,
    dispense_payload,
    fixtures,
    get_patient,
    place_order,
    restock_payload,
    setup_station_with_pocket,
    setup_verified_order,
    validate_error,
    validate_paginated,
    validate_success,
)


def _current_pocket(api, pocket_id, headers):
    return validate_success(api.get_adc_pocket(pocket_id, headers), 200)


class TestRestockZeroQuantity:
    def _setup_empty_pocket(self):
        return setup_station_with_pocket(schedule="NON_CONTROLLED")

    def test_zero_units_rejected_invalid_quantity(self, api):
        """PRD §3.6: "Every pocket-mutating call below also increments the pocket's `version` by 1, and all unit quantities must be at least 1 — a zero or negative `units` is rejected with `ERR_INVALID_QUANTITY`."

        Design: Difficulty/boundary_precision_check/restock_zero_quantity_rejected
        """
        ns = self._setup_empty_pocket()
        resp = api.restock_pocket(
            ns.pocket["id"],
            restock_payload(0, ns.pocket["version"]),
            ns.technician_headers,
        )
        validate_error(resp, "ERR_INVALID_QUANTITY", 400)

    def test_rejected_restock_is_side_effect_free(self, api):
        """PRD §3.6: "Restock is a `PharmacyTechnician` action carrying `units` and the mandatory OCC field `expected_pocket_version` (§2.5). Capacity is enforced: the restock may not push `on_hand_units` above `max_units`, otherwise the call is rejected with `ERR_POCKET_CAPACITY_EXCEEDED`. Success appends a `RESTOCK` event and adds `units` to `on_hand_units`."

        Design: Difficulty/boundary_precision_check/restock_zero_quantity_rejected
        """
        ns = self._setup_empty_pocket()
        api.restock_pocket(
            ns.pocket["id"], restock_payload(0, ns.pocket["version"]),
            ns.technician_headers,
        )
        pocket = _current_pocket(api, ns.pocket["id"], ns.technician_headers)
        assert pocket["on_hand_units"] == 0
        assert pocket["version"] == ns.pocket["version"]


class TestPocketCapacityBoundary:
    def test_restock_to_exactly_max_allowed_one_over_rejected(self, api):
        """PRD §3.6: "Capacity is enforced: the restock may not push `on_hand_units` above `max_units`, otherwise the call is rejected with `ERR_POCKET_CAPACITY_EXCEEDED`."

        Design: Corner/validations/pocket_capacity_boundary
        """
        ns = setup_station_with_pocket(max_units=10)
        ns.pocket = fixtures.restock_pocket(ns.pocket, 9, ns.technician)
        current = _current_pocket(api, ns.pocket["id"], ns.technician_headers)
        resp = api.restock_pocket(
            ns.pocket["id"], restock_payload(2, current["version"]),
            ns.technician_headers,
        )
        validate_error(resp, "ERR_POCKET_CAPACITY_EXCEEDED", 422)
        current = _current_pocket(api, ns.pocket["id"], ns.technician_headers)
        assert current["on_hand_units"] == 9
        ok = api.restock_pocket(
            ns.pocket["id"], restock_payload(1, current["version"]),
            ns.technician_headers,
        )
        pocket = validate_success(ok, 200)
        assert pocket["on_hand_units"] == 10


class TestDispenseGates:
    def test_dispense_beyond_on_hand_rejected(self, api, pharmacist_headers):
        """PRD §3.6: "The pocket must hold at least `units` on hand, otherwise `ERR_INSUFFICIENT_STOCK`."

        Design: Corner/validations/insufficient_stock_dispense_rejected
        """
        ns = setup_verified_order(route="PO", ordered_dose_mg=100.0)
        inv = setup_station_with_pocket(drug=ns.drug, restock_units=4)
        nurse, nurse_headers = fixtures.make_nurse()
        resp = api.dispense_pocket(
            inv.pocket["id"], dispense_payload(ns.order["id"], 5), nurse_headers
        )
        validate_error(resp, "ERR_INSUFFICIENT_STOCK", 422)
        pocket = _current_pocket(api, inv.pocket["id"], pharmacist_headers)
        assert pocket["on_hand_units"] == 4
        order = validate_success(
            api.get_medication_order(ns.order["id"], pharmacist_headers), 200
        )
        assert order["fulfillment_status"] == "READY"

    def test_quarantined_pocket_refuses_dispense_then_allows_after_release(self, api, pharmacist_headers):
        """PRD §3.6: "The pocket must be `ACTIVE`; dispensing from a `QUARANTINED` pocket is rejected with `ERR_POCKET_QUARANTINED`."
        PRD §3.6: "Quarantine is the pharmacist's hold on a pocket: quarantining an `ACTIVE` pocket moves it to `QUARANTINED` and releasing returns it to `ACTIVE`, each incrementing the pocket's `version`."

        Design: Corner/validations/quarantined_pocket_blocks_dispense
        """
        ns = setup_verified_order(route="PO", ordered_dose_mg=100.0)
        inv = setup_station_with_pocket(drug=ns.drug, restock_units=4)
        pharmacist, pharmacist_hdrs = fixtures.make_pharmacist()
        nurse, nurse_headers = fixtures.make_nurse()
        validate_success(api.quarantine_pocket(inv.pocket["id"], pharmacist_hdrs), 200)
        resp = api.dispense_pocket(
            inv.pocket["id"], dispense_payload(ns.order["id"], 1), nurse_headers
        )
        validate_error(resp, "ERR_POCKET_QUARANTINED", 409)
        validate_success(
            api.release_pocket_quarantine(inv.pocket["id"], pharmacist_hdrs), 200
        )
        pocket = validate_success(
            api.dispense_pocket(
                inv.pocket["id"], dispense_payload(ns.order["id"], 1), nurse_headers
            ),
            200,
        )
        assert pocket["on_hand_units"] == 3

    def test_dispense_with_wrong_pocket_drug_rejected(self, api, pharmacist_headers):
        """PRD §3.6: "The pocket's drug must equal the order's drug — `drug_product_id` matching `drug_product_id` — otherwise `ERR_DRUG_MISMATCH`."

        Design: Corner/errors/error_drug_mismatch_on_dispense
        """
        ns = setup_verified_order(route="PO", ordered_dose_mg=100.0)
        other_drug = create_drug(name="DrugDMB")
        inv = setup_station_with_pocket(drug=other_drug, restock_units=10)
        nurse, nurse_headers = fixtures.make_nurse()
        resp = api.dispense_pocket(
            inv.pocket["id"], dispense_payload(ns.order["id"], 1), nurse_headers
        )
        validate_error(resp, "ERR_DRUG_MISMATCH", 422)
        pocket = _current_pocket(api, inv.pocket["id"], pharmacist_headers)
        assert pocket["on_hand_units"] == 10
        order = validate_success(
            api.get_medication_order(ns.order["id"], pharmacist_headers), 200
        )
        assert order["fulfillment_status"] == "READY"


class TestDispenseCrossEntityGates:
    def _setup(self, api):
        ns = setup_verified_order(route="IV", ordered_dose_mg=100.0)
        batch_ns = fixtures.setup_batch_qa_review([ns.order["id"]], [10.0])
        inv = setup_station_with_pocket(drug=ns.drug, restock_units=10)
        nurse, nurse_headers = fixtures.make_nurse()
        prescriber, _ = fixtures.make_prescriber()
        patient = create_patient()
        unverified = place_order(patient, ns.drug, prescriber, route="PO",
                                 ordered_dose_mg=100.0)
        return ns, batch_ns, inv, nurse_headers, unverified

    def test_dispense_against_unverified_order_rejected(self, api, pharmacist_headers):
        """PRD §3.6: "The order's `verification_status` must be `VERIFIED`, otherwise `ERR_ORDER_NOT_VERIFIED`."

        Design: Difficulty/cross_entity_state_dependency/pocket_dispense_requires_order_verified_and_preparation_qa
        """
        _, _, inv, nurse_headers, unverified = self._setup(api)
        resp = api.dispense_pocket(
            inv.pocket["id"], dispense_payload(unverified["id"], 1), nurse_headers
        )
        validate_error(resp, "ERR_ORDER_NOT_VERIFIED", 422)
        pocket = _current_pocket(api, inv.pocket["id"], pharmacist_headers)
        assert pocket["on_hand_units"] == 10

    def test_iv_dispense_without_qa_passed_preparation_rejected(self, api, pharmacist_headers):
        """PRD §3.6: "For an `IV` order, two further gates apply: a linked preparation in `QA_PASSED` must exist, otherwise `ERR_PREPARATION_NOT_QA_PASSED`, and the logical clock must be strictly before that preparation's `bud_expiry` — dispensing at or after the expiry is rejected with `ERR_BUD_EXPIRED`, the sweep having already run."

        Design: Difficulty/cross_entity_state_dependency/pocket_dispense_requires_order_verified_and_preparation_qa
        """
        ns, _, inv, nurse_headers, _ = self._setup(api)
        # Batch is in QA_REVIEW: the linked preparation is COMPOUNDED, not QA_PASSED.
        resp = api.dispense_pocket(
            inv.pocket["id"], dispense_payload(ns.order["id"], 1), nurse_headers
        )
        validate_error(resp, "ERR_PREPARATION_NOT_QA_PASSED", 422)
        pocket = _current_pocket(api, inv.pocket["id"], pharmacist_headers)
        assert pocket["on_hand_units"] == 10


class TestInventoryConservation:
    def _setup_stocked_50_with_order(self):
        ns = setup_verified_order(route="PO", ordered_dose_mg=100.0)
        inv = setup_station_with_pocket(drug=ns.drug, restock_units=50)
        nurse, nurse_headers = fixtures.make_nurse()
        return ns, inv, nurse, nurse_headers

    def test_dispense_then_return_restores_on_hand(self, api, pharmacist_headers):
        """PRD §3.6: "The pocket's `on_hand_units` is not an independent counter — it is defined as the chronological replay of the pocket's `InventoryEvent` ledger, and it must equal that replay after every mutation."

        Design: Difficulty/compensating_invariant/adc_pocket_inventory_conservation
        """
        ns, inv, nurse, nurse_headers = self._setup_stocked_50_with_order()
        after_disp = fixtures.dispense_pocket(inv.pocket["id"], ns.order["id"], 3, nurse)
        assert after_disp["on_hand_units"] == 47
        after_ret = fixtures.return_pocket(inv.pocket["id"], 3, nurse,
                                           order_id=ns.order["id"])
        assert after_ret["on_hand_units"] == 50
        count = fixtures.count_pocket(inv.pocket["id"], 50, ns.pharmacist)
        assert count["expected_on_hand_units"] == 50
        assert count["variance_units"] == 0
        assert count["discrepancy_case_id"] is None

    def test_ledger_replay_equals_on_hand_and_event_deltas(self, api, pharmacist_headers):
        """PRD §3.6: "The replay convention is: restock adds its units, dispense subtracts, return adds, waste subtracts, adjustment adds or subtracts its signed amount, and a count contributes zero; events replay in `occurred_at` ascending order with `created_at` ascending as the tie-break, starting from zero."

        Design: Difficulty/compensating_invariant/adc_pocket_inventory_conservation
        """
        ns, inv, nurse, nurse_headers = self._setup_stocked_50_with_order()
        fixtures.dispense_pocket(inv.pocket["id"], ns.order["id"], 3, nurse)
        fixtures.return_pocket(inv.pocket["id"], 3, nurse, order_id=ns.order["id"])
        events, meta = validate_paginated(
            api.list_pocket_events(inv.pocket["id"], pharmacist_headers)
        )
        assert meta["total_count"] == 3
        deltas = [e["units_delta"] for e in events]
        assert deltas == [50, -3, 3]
        pocket = _current_pocket(api, inv.pocket["id"], pharmacist_headers)
        assert_pocket_ledger_consistent(pocket, events)


class TestCountChronologicalReplay:
    def test_known_event_sequence_replays_to_expected_on_hand(self, api):
        """PRD §3.6: "The count call returns the `variance_units`, the `expected_on_hand_units` from the replay, the `discrepancy_case_id` (null when no case opened), and the `event_id` of the appended count event. A count that stays within threshold appends its event and opens nothing."

        Design: Corner/calculations/adc_count_chronological_replay_value
        """
        ns = setup_verified_order(route="PO", ordered_dose_mg=100.0)
        inv = setup_station_with_pocket(drug=ns.drug, restock_units=50)
        nurse, _ = fixtures.make_nurse()
        fixtures.dispense_pocket(inv.pocket["id"], ns.order["id"], 3, nurse)
        fixtures.return_pocket(inv.pocket["id"], 1, nurse)
        fixtures.waste_pocket(inv.pocket["id"], 1, inv.technician,
                              inv.technician_headers)
        fixtures.return_pocket(inv.pocket["id"], 1, nurse)
        count = fixtures.count_pocket(inv.pocket["id"], 48, ns.pharmacist)
        assert count["expected_on_hand_units"] == 48  # 50 - 3 + 1 - 1 + 1
        assert count["variance_units"] == 0
        assert count["discrepancy_case_id"] is None


class TestDiscrepancyThresholdBoundaries:
    def test_threshold_inclusive_per_schedule(self, api):
        """PRD §3.6: "When the absolute variance breaches the schedule-specific threshold — 2 units for a `C_II` drug, 5 units for any other schedule — a `DiscrepancyCase` opens in `OPEN` status, recording the `pocket_id` and the signed `variance_units`."

        Design: Corner/calculations/discrepancy_threshold_inclusive_cii
        """
        pharmacist, _ = fixtures.make_pharmacist()
        c2 = setup_station_with_pocket(schedule="C_II", restock_units=50)
        nc = setup_station_with_pocket(schedule="NON_CONTROLLED", restock_units=50)
        # C_II: variance -1 opens nothing; variance -2 (inclusive) opens a case
        count = fixtures.count_pocket(c2.pocket["id"], 49, pharmacist)
        assert count["discrepancy_case_id"] is None
        count = fixtures.count_pocket(c2.pocket["id"], 48, pharmacist)
        assert count["variance_units"] == -2
        assert count["discrepancy_case_id"] is not None
        # NON_CONTROLLED: -4 opens nothing; -5 (inclusive) opens a case
        count = fixtures.count_pocket(nc.pocket["id"], 46, pharmacist)
        assert count["discrepancy_case_id"] is None
        count = fixtures.count_pocket(nc.pocket["id"], 45, pharmacist)
        assert count["variance_units"] == -5
        assert count["discrepancy_case_id"] is not None


class TestWasteWitnessing:
    def test_cii_waste_requires_witness_non_controlled_does_not(self, api, pharmacist_headers):
        """PRD §3.6: "When the pocket's drug is schedule `C_II`, a `witness_staff_id` must be present — its absence is rejected with `ERR_WITNESS_REQUIRED` — and the witness must differ from the recorder: a `witness_staff_id` equal to the caller's `X-User-ID` is rejected with `ERR_WITNESS_SELF_FORBIDDEN`."

        Design: Corner/validations/waste_witness_required_for_cii
        """
        c2 = setup_station_with_pocket(schedule="C_II", restock_units=10)
        nc = setup_station_with_pocket(schedule="NON_CONTROLLED", restock_units=10)
        resp = api.waste_pocket(c2.pocket["id"], {"units": 1}, c2.technician_headers)
        validate_error(resp, "ERR_WITNESS_REQUIRED", 422)
        pocket = _current_pocket(api, c2.pocket["id"], pharmacist_headers)
        assert pocket["on_hand_units"] == 10
        pocket = fixtures.waste_pocket(nc.pocket["id"], 1, nc.technician,
                                       nc.technician_headers)
        assert pocket["on_hand_units"] == 9

    def test_witness_equal_to_recorder_rejected(self, api, pharmacist_headers):
        """PRD §3.6: "When the pocket's drug is schedule `C_II`, a `witness_staff_id` must be present — its absence is rejected with `ERR_WITNESS_REQUIRED` — and the witness must differ from the recorder: a `witness_staff_id` equal to the caller's `X-User-ID` is rejected with `ERR_WITNESS_SELF_FORBIDDEN`."

        Design: Corner/validations/waste_witness_self_forbidden
        """
        c2 = setup_station_with_pocket(schedule="C_II", restock_units=10)
        resp = api.waste_pocket(
            c2.pocket["id"],
            {"units": 1, "witness_staff_id": c2.technician["id"]},
            c2.technician_headers,
        )
        validate_error(resp, "ERR_WITNESS_SELF_FORBIDDEN", 422)
        pocket = _current_pocket(api, c2.pocket["id"], pharmacist_headers)
        assert pocket["on_hand_units"] == 10


class TestRestockOcc:
    def test_stale_pocket_version_rejected_fresh_accepted(self, api, pharmacist_headers):
        """PRD §2.5: "Restocking an ADC pocket requires the request to carry `expected_pocket_version`, the `version` of the target `ADCPocket` as the client last observed it. Restock is otherwise always legitimate on an `ACTIVE` pocket, so the sole OCC ground for rejection is that another ledger mutation — a restock, dispense, return, waste, or adjustment — advanced the pocket's `version` after the client's physical observation; such a call is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_pocket_restock_stale_version
        """
        ns = setup_verified_order(route="PO", ordered_dose_mg=100.0)
        inv = setup_station_with_pocket(drug=ns.drug, restock_units=10)
        nurse, nurse_headers = fixtures.make_nurse()
        pre_dispense_version = inv.pocket["version"]
        fixtures.dispense_pocket(inv.pocket["id"], ns.order["id"], 1, nurse)
        resp = api.restock_pocket(
            inv.pocket["id"], restock_payload(5, pre_dispense_version),
            inv.technician_headers,
        )
        validate_error(resp, "ERR_STALE_VERSION", 412)
        pocket = _current_pocket(api, inv.pocket["id"], pharmacist_headers)
        assert pocket["on_hand_units"] == 9
        ok = api.restock_pocket(
            inv.pocket["id"], restock_payload(5, pocket["version"]),
            inv.technician_headers,
        )
        pocket = validate_success(ok, 200)
        assert pocket["on_hand_units"] == 14


class TestImmediateConsistency:
    def test_restock_response_carries_post_mutation_state(self, api):
        """PRD §3.6: "Restock is a `PharmacyTechnician` action carrying `units` and the mandatory OCC field `expected_pocket_version` (§2.5). Capacity is enforced: the restock may not push `on_hand_units` above `max_units`, otherwise the call is rejected with `ERR_POCKET_CAPACITY_EXCEEDED`. Success appends a `RESTOCK` event and adds `units` to `on_hand_units`."
        PRD §3.6: "Every pocket-mutating call below also increments the pocket's `version` by 1, and all unit quantities must be at least 1 — a zero or negative `units` is rejected with `ERR_INVALID_QUANTITY`."

        Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_same_response
        """
        ns = setup_station_with_pocket()
        assert ns.pocket["on_hand_units"] == 0
        initial_version = ns.pocket["version"]
        pocket = validate_success(
            api.restock_pocket(
                ns.pocket["id"], restock_payload(7, initial_version),
                ns.technician_headers,
            ),
            200,
        )
        assert pocket["on_hand_units"] == 7
        assert pocket["version"] == initial_version + 1
        fetched = _current_pocket(api, ns.pocket["id"], ns.technician_headers)
        assert fetched["on_hand_units"] == 7
        assert fetched["version"] == initial_version + 1
