"""The computed yield read, the two-parent allocation link, the per-family
not-found codes, and the core-stock sufficiency ceiling."""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    allocate_receipt_payload,
    create_flooring_lot_payload,
    finalize_lot_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    BROKER,
    CLERK,
    INSPECTOR,
    OPERATOR,
    SCHEDULER,
    SUPERVISOR,
    ADJUDICATOR,
    create_accepted_receipt,
    create_core_stock,
    create_product_line,
    refetch_charge,
    refetch_core_stock,
    refetch_receipt,
    set_logical_clock,
    setup_finalized_grade_run,
    setup_released_charge,
    setup_scheduled_charge,
)

# A second syntactically valid identifier so both parents of the allocation link
# can be made unresolvable independently.
UNKNOWN_CHARGE_ID = "00000000-0000-0000-0000-00000000beef"

# The engineered line and the thin substrate holding that governs the core-stock
# sufficiency ceiling.
ENGINEERED_LINE = {
    "line_code": "ENG-RO-500",
    "construction_type": "ENGINEERED",
    "nominal_width_in": 5.000,
    "nominal_thickness_in": 0.500,
    "material_value_cents_per_sf": 720,
    "warranty_funded_total_cents": 400000,
}


class TestYieldSummaryComputedRead:
    """One read carries the mass balance and both yield variants, and it reports
    the final variant rather than computing it."""

    def test_the_summary_gains_a_final_yield_and_a_delta_only_once_the_lot_closes(
        self, api
    ):
        """PRD 3.7: "A computed read exposes both variants side by side for a lot,
        returning its `flooring_lot_id`, the `input_dry_bf` drawn, the
        `net_flooring_bf` milled, the `residue_bf` and `waste_bf` from the mass
        balance, the `provisional_yield_pct` and `final_yield_pct` variants, a
        `yield_delta_pp` giving the final yield less the provisional yield in
        percentage points rounded half up to two decimal places, and the
        `yield_floor_pct` of 55.00 in force."

        PRD 3.7: "`yield_delta_pp` is null while `final_yield_pct` is still null."

        PRD 3.7: "A lot that milled 6000 board feet into 4680 net had a
        `provisional_yield_pct` of 78.00; credited at 3970.2625 board feet its
        `final_yield_pct` is 66.17 and it grades out, while a character-heavy run
        crediting only 2200.0000 board feet gives 36.67 and quarantines it."

        Design: Corner/endpoints/yield_summary_computed_read_matches_both_yield_variants
        """
        ctx = setup_finalized_grade_run(api)
        lot_id = ctx["lot"]["id"]

        before = validate_success(
            api.get_yield_summary(lot_id, SUPERVISOR), expected_status=200
        )
        assert before["flooring_lot_id"] == lot_id
        assert before["input_dry_bf"] == pytest.approx(6000, abs=0.01)
        assert before["net_flooring_bf"] == pytest.approx(4680, abs=0.01)
        assert before["residue_bf"] == pytest.approx(570.00, abs=0.01)
        assert before["waste_bf"] == pytest.approx(570.00, abs=0.01)
        assert before["provisional_yield_pct"] == pytest.approx(78.00, abs=0.01)
        assert before["final_yield_pct"] is None
        assert before["yield_delta_pp"] is None
        assert before["yield_floor_pct"] == pytest.approx(55.00, abs=0.01)

        graded = validate_success(
            api.finalize_flooring_lot(
                lot_id, finalize_lot_payload(ctx["grade_run"]["id"]), SUPERVISOR
            ),
            expected_status=200,
        )
        assert graded["status"] == "GRADED"
        assert graded["final_yield_pct"] == pytest.approx(66.17, abs=0.01)

        after = validate_success(
            api.get_yield_summary(lot_id, SUPERVISOR), expected_status=200
        )
        assert after["flooring_lot_id"] == lot_id
        assert after["provisional_yield_pct"] == pytest.approx(78.00, abs=0.01)
        assert after["final_yield_pct"] == pytest.approx(66.17, abs=0.01)
        assert after["yield_delta_pp"] == pytest.approx(-11.83, abs=0.01)
        assert after["net_flooring_bf"] == pytest.approx(4680, abs=0.01)
        assert after["residue_bf"] == pytest.approx(570.00, abs=0.01)
        assert after["waste_bf"] == pytest.approx(570.00, abs=0.01)


class TestAllocationLinkResolvesBothParents:
    """The allocation body names one parent and the path names the other; each
    unresolved parent has its own code, and the body is checked first."""

    def test_each_missing_parent_gets_its_own_code_and_the_receipt_check_runs_first(
        self, api
    ):
        """PRD 2.7: "5. Green receipt existence — `ERR_RECEIPT_NOT_FOUND` (404), on
        green receipt paths and on the `green_receipt_id` carried in an allocation or
        deallocation body."

        PRD 2.7: "6. Kiln charge existence — `ERR_CHARGE_NOT_FOUND` (404), on kiln
        charge paths and on flooring lot creation."

        PRD 3.4: "A `KilnOperator` or `MillAdmin` names a `green_receipt_id` in the
        payload, and the receipt moves from `ACCEPTED` to `ALLOCATED` with its
        `kiln_charge_id` set to the target charge."

        Design: Corner/endpoints/allocate_receipt_link_requires_both_parents_and_receipt_not_found
        """
        ctx = setup_scheduled_charge(api)
        charge_id = ctx["charge"]["id"]
        receipt = create_accepted_receipt(api, ctx["species"])

        validate_error(
            api.allocate_receipt(
                charge_id, allocate_receipt_payload(NON_EXISTENT_UUID), OPERATOR
            ),
            "ERR_RECEIPT_NOT_FOUND",
            expected_status=404,
        )
        validate_error(
            api.allocate_receipt(
                UNKNOWN_CHARGE_ID, allocate_receipt_payload(receipt["id"]), OPERATOR
            ),
            "ERR_CHARGE_NOT_FOUND",
            expected_status=404,
        )
        validate_error(
            api.allocate_receipt(
                UNKNOWN_CHARGE_ID, allocate_receipt_payload(NON_EXISTENT_UUID), OPERATOR
            ),
            "ERR_RECEIPT_NOT_FOUND",
            expected_status=404,
        )

        untouched = refetch_receipt(api, receipt["id"])
        assert untouched["status"] == "ACCEPTED"
        assert untouched["kiln_charge_id"] is None

        charge = validate_success(
            api.allocate_receipt(
                charge_id, allocate_receipt_payload(receipt["id"]), OPERATOR
            ),
            expected_status=200,
        )
        assert charge["charged_green_bf"] == pytest.approx(5800, abs=0.01)

        rows, meta = validate_paginated(
            api.list_green_receipts(CLERK, params={"kiln_charge_id": charge_id})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == receipt["id"]
        assert rows[0]["status"] == "ALLOCATED"


class TestNotFoundCodesArePerEntityFamily:
    """Five reads against an otherwise empty mill return five distinct codes."""

    def test_each_family_reports_its_own_not_found_code(self, api):
        """PRD 2.7: "7. Flooring lot existence — `ERR_LOT_NOT_FOUND` (404), on flooring
        lot paths and on grade run creation, prefinish run creation and warranty claim
        creation."

        PRD 2.7: "8. Grade run existence — `ERR_GRADE_RUN_NOT_FOUND` (404), on grade
        run paths, bundle creation, lot finalization and the replacement reference of a
        supersede."

        PRD 2.7: "9. Prefinish run existence — `ERR_PREFINISH_RUN_NOT_FOUND` (404), on
        prefinish run paths."

        PRD 2.7: "10. Byproduct batch existence — `ERR_BATCH_NOT_FOUND` (404), on
        byproduct batch paths and on byproduct sale creation."

        PRD 2.7: "11. Warranty claim existence — `ERR_CLAIM_NOT_FOUND` (404), on
        warranty claim paths."

        Design: Corner/errors/unknown_ids_across_entity_families_return_not_found_codes
        """
        set_logical_clock(api)

        validate_error(
            api.get_flooring_lot(NON_EXISTENT_UUID, SUPERVISOR),
            "ERR_LOT_NOT_FOUND",
            expected_status=404,
        )
        validate_error(
            api.get_grade_run(NON_EXISTENT_UUID, INSPECTOR),
            "ERR_GRADE_RUN_NOT_FOUND",
            expected_status=404,
        )
        validate_error(
            api.get_prefinish_run(NON_EXISTENT_UUID, SCHEDULER),
            "ERR_PREFINISH_RUN_NOT_FOUND",
            expected_status=404,
        )
        validate_error(
            api.get_byproduct_batch(NON_EXISTENT_UUID, BROKER),
            "ERR_BATCH_NOT_FOUND",
            expected_status=404,
        )
        validate_error(
            api.get_warranty_claim(NON_EXISTENT_UUID, ADJUDICATOR),
            "ERR_CLAIM_NOT_FOUND",
            expected_status=404,
        )


class TestCoreStockSufficiencyCeiling:
    """The ceiling is on the reserved square footage, not the board feet, and it
    is applied to the running reserved total."""

    def test_the_ceiling_counts_the_reservation_and_accumulates_across_lots(self, api):
        """PRD 3.6: "For an engineered lot the server computes `reserved_core_sf` as
        the drawn `input_dry_bf` multiplied by 1.10 square feet of core per board foot,
        rounded half up to two decimal places — a draw of 2900 board feet reserves
        3190.00 square feet — and adds it to the core stock's `reserved_square_feet`,
        which is at all times the total `reserved_core_sf` of the non-voided lots on
        that stock."

        PRD 3.6: "The reservation is refused with `ERR_CORE_STOCK_INSUFFICIENT` when
        the stock's `reserved_square_feet` including this new reservation would exceed
        its `available_square_feet`."

        PRD 3.5: "A charge holding 9700 green board feet of a `DENSE` species yields
        8972.50 kiln-dry board feet."

        Design: Corner/errors/core_stock_reservation_above_available_square_feet_rejected
        """
        ctx = setup_released_charge(api)
        charge_id = ctx["charge"]["id"]
        line = create_product_line(api, ctx["species"], **ENGINEERED_LINE)
        core = create_core_stock(api, line, available_square_feet=1000.00)

        validate_error(
            api.create_flooring_lot(
                create_flooring_lot_payload(
                    line["id"], charge_id, 1000, core_stock_id=core["id"]
                ),
                SUPERVISOR,
            ),
            "ERR_CORE_STOCK_INSUFFICIENT",
            expected_status=422,
        )
        assert refetch_core_stock(api, core["id"])[
            "reserved_square_feet"
        ] == pytest.approx(0.00, abs=0.01)
        assert refetch_charge(api, charge_id)["remaining_dry_bf"] == pytest.approx(
            8972.50, abs=0.01
        )

        lot = validate_success(
            api.create_flooring_lot(
                create_flooring_lot_payload(
                    line["id"], charge_id, 900, core_stock_id=core["id"]
                ),
                SUPERVISOR,
            ),
            expected_status=201,
        )
        assert lot["reserved_core_sf"] == pytest.approx(990.00, abs=0.01)
        assert refetch_core_stock(api, core["id"])[
            "reserved_square_feet"
        ] == pytest.approx(990.00, abs=0.01)

        validate_error(
            api.create_flooring_lot(
                create_flooring_lot_payload(
                    line["id"], charge_id, 10, core_stock_id=core["id"]
                ),
                SUPERVISOR,
            ),
            "ERR_CORE_STOCK_INSUFFICIENT",
            expected_status=422,
        )
        assert refetch_core_stock(api, core["id"])[
            "reserved_square_feet"
        ] == pytest.approx(990.00, abs=0.01)
