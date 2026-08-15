"""Consignment counts, charges, and stock adjustments."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_charges_for_case,
    get_success_data,
    make_supply_item,
    make_surgeon,
    setup_completed_case,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
MATERIALS = TEST_USERS["materials_headers"]
ANY = TEST_USERS["any_headers"]


def _rod(on_hand=8):
    return make_supply_item(sku="ROD-TI", name="Titanium rod",
                            unit_cost_cents=5000, substitute_group="ROD",
                            consignment_flag=True, initial_on_hand=on_hand)


class TestConsignmentCounts:
    def test_count_variance_adjusts_stock_on_verify(self):
        """PRD §3.8: "At creation the count snapshots the item's
        `on_hand_quantity` as `system_qty_at_count`, computes `variance_qty` as
        `counted_qty` minus `system_qty_at_count`, and values the discrepancy
        as `variance_value_cents`, the variance multiplied by the item's
        `unit_cost_cents`"
        PRD §3.8: "When the variance is non-zero, verification syncs the ledger
        by adding `variance_qty` to the item's `on_hand_quantity`"

        Design: Corner/calculations/consignment_count_variance_adjusts_stock_on_verify
        """
        rod = _rod(on_hand=8)
        created = validate_success(api_client.create_consignment_count(
            {"supply_item_id": rod["id"], "counted_qty": 7}, MATERIALS
        ), expected_status=201)
        assert created["system_qty_at_count"] == 8
        assert created["variance_qty"] == -1

        verified = validate_success(
            api_client.verify_consignment_count(created["id"], MATERIALS)
        )
        assert verified["status"] == "VERIFIED"
        assert verified["variance_value_cents"] == -5000
        item_after = get_success_data(api_client.get_supply_item(rod["id"], ANY))
        assert item_after["on_hand_quantity"] == 7

    def test_count_zero_variance_leaves_stock_unchanged(self):
        """PRD §3.8: "When the variance is non-zero, verification syncs the
        ledger by adding `variance_qty` to the item's `on_hand_quantity`; a
        zero variance leaves stock untouched."

        Design: Corner/calculations/consignment_count_zero_variance_leaves_stock_unchanged
        """
        rod = _rod(on_hand=8)
        created = validate_success(api_client.create_consignment_count(
            {"supply_item_id": rod["id"], "counted_qty": 8}, MATERIALS
        ), expected_status=201)
        get_success_data(api_client.verify_consignment_count(created["id"], MATERIALS))
        item_after = get_success_data(api_client.get_supply_item(rod["id"], ANY))
        assert item_after["on_hand_quantity"] == 8

    def test_verify_verified_count_rejected(self):
        """PRD §3.8: "Verifying is permitted only from `RECORDED`
        (`ERR_COUNT_NOT_RECORDED` otherwise) and moves the count to the
        terminal `VERIFIED` state"

        Design: Corner/errors/verify_verified_count_rejected
        """
        rod = _rod(on_hand=8)
        created = validate_success(api_client.create_consignment_count(
            {"supply_item_id": rod["id"], "counted_qty": 7}, MATERIALS
        ), expected_status=201)
        get_success_data(api_client.verify_consignment_count(created["id"], MATERIALS))
        resp = api_client.verify_consignment_count(created["id"], MATERIALS)
        validate_error(resp, ApiErrorId.ERR_COUNT_NOT_RECORDED)
        item_after = get_success_data(api_client.get_supply_item(rod["id"], ANY))
        assert item_after["on_hand_quantity"] == 7

    def test_count_on_stock_item_rejected(self):
        """PRD §3.8: "Only consignment items may be counted — an item whose
        `consignment_flag` is false is rejected with
        `ERR_NOT_CONSIGNMENT_ITEM`."

        Design: Corner/validations/consignment_count_on_stock_item_rejected
        """
        glove = make_supply_item(sku="GLOVE-PR", name="Gloves pair",
                                 unit_cost_cents=250, substitute_group="GLOVES",
                                 initial_on_hand=100)
        resp = api_client.create_consignment_count(
            {"supply_item_id": glove["id"], "counted_qty": 100}, MATERIALS
        )
        validate_error(resp, ApiErrorId.ERR_NOT_CONSIGNMENT_ITEM)


class TestStockAdjustments:
    def test_negative_result_rejected_and_zero_floor_ok(self):
        """PRD §3.1: "The adjustment is added to `on_hand_quantity`; any
        adjustment whose result would drop the balance below zero is rejected
        with `ERR_INVALID_QUANTITY`."

        Design: Corner/calculations/stock_adjustment_negative_result_rejected
        """
        item = make_supply_item(sku="SCALPEL-11", name="Scalpel 11",
                                unit_cost_cents=150, substitute_group="BLADE",
                                initial_on_hand=5)
        resp = api_client.create_stock_adjustment(
            item["id"], {"delta_qty": -6, "reason": "cycle count"}, MATERIALS
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_QUANTITY)

        ok = api_client.create_stock_adjustment(
            item["id"], {"delta_qty": -5, "reason": "cycle count"}, MATERIALS
        )
        data = validate_success(ok)
        assert data["on_hand_quantity"] == 0


class TestConsignmentCharges:
    def _completed_consignment_case(self, surgeon_name, start, room, qty=2,
                                    used=2):
        surgeon = make_surgeon(full_name=surgeon_name)
        rod = _rod(on_hand=10)
        return setup_completed_case(
            surgeon, [rod],
            [{"item_index": 0, "quantity": qty, "designation": "OPEN"}],
            usage_by_index={0: used},
            procedure_name="SPINE",
            scheduled_start=start,
            expected_duration_min=120,
            room=room,
        )

    def test_capture_captured_charge_rejected(self):
        """PRD §3.8: "A `MaterialsManager` captures a `PENDING` charge, moving
        it `PENDING → CAPTURED` to bill it; capturing from any other state is
        rejected with `ERR_CHARGE_INVALID_STATE`."

        Design: Corner/errors/capture_captured_charge_rejected
        """
        ctx = self._completed_consignment_case("Dr. Cap",
                                               "2026-09-05T08:00:00Z", "OR-6",
                                               qty=1, used=1)
        chg = get_charges_for_case(ctx["case"]["id"])[0]
        get_success_data(api_client.capture_consignment_charge(chg["id"], MATERIALS))
        resp = api_client.capture_consignment_charge(chg["id"], MATERIALS)
        validate_error(resp, ApiErrorId.ERR_CHARGE_INVALID_STATE)
        after = get_success_data(api_client.get_consignment_charge(chg["id"], ANY))
        assert after["status"] == "CAPTURED"

    def test_capture_then_void_conserves_billed_total(self):
        """PRD §3.8: "Voiding compensates a charge from either `PENDING` or
        `CAPTURED`, moving it to the terminal `VOIDED` state — voiding a
        `CAPTURED` charge reduces the running total of captured `amount_cents`
        by that charge's amount"
        PRD §3.5: "`qty_billed` equals the usage record's `qty_opened`, and
        `amount_cents` is `qty_billed` times the record's `unit_cost_cents`."
        PRD §3.8: "Charges may be listed with `case_id`, `supply_item_id`,
        `usage_record_id`, and `status` filters."

        Design: Difficulty/compensating_invariant/capture_then_void_conserves_billed_total
        """
        ctx = self._completed_consignment_case("Dr. Bill",
                                               "2026-09-01T08:00:00Z", "OR-6",
                                               qty=2, used=2)
        chg = get_charges_for_case(ctx["case"]["id"])[0]
        # Consignment bills on open: qty_billed 2 x 5000 = 10000.
        assert chg["amount_cents"] == 10000

        get_success_data(api_client.capture_consignment_charge(chg["id"], MATERIALS))
        voided = validate_success(
            api_client.void_consignment_charge(chg["id"], MATERIALS)
        )
        assert voided["status"] == "VOIDED"

        _, meta = validate_paginated(
            api_client.list_consignment_charges(
                ANY, params={"case_id": ctx["case"]["id"], "status": "CAPTURED"}
            )
        )
        assert meta["total_count"] == 0

    def test_charge_amount_on_open(self):
        """PRD §3.5: "Consignment bills on open, not on use, so `qty_billed`
        equals the usage record's `qty_opened`, and `amount_cents` is
        `qty_billed` times the record's `unit_cost_cents`."

        Design: Difficulty/compensating_invariant/capture_then_void_conserves_billed_total
        """
        ctx = self._completed_consignment_case("Dr. BillAmt",
                                               "2026-09-02T08:00:00Z", "OR-6",
                                               qty=2, used=2)
        chg = get_charges_for_case(ctx["case"]["id"])[0]
        assert chg["qty_billed"] == 2
        assert chg["amount_cents"] == 10000
        assert chg["status"] == "PENDING"
