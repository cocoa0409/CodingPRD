"""Utility material stewardship: stock ledger conservation, issuance boundaries,
returns, two-path reconciliation, and cross-contract referential integrity."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_material_issue,
    assert_stock_item,
    create_draft_contract,
    get_success_data,
    issue_material,
    receive_stock,
    setup_field_scenario,
    setup_stock_item,
    validate_error,
    validate_success,
)

PM = TEST_USERS["contractor_pm_headers"]
FOREMAN = TEST_USERS["foreman_headers"]
DISPATCHER = TEST_USERS["utility_dispatcher_headers"]


def _stock_scenario(api, contract_number="C-1000", initial_on_hand=0,
                    material_code="WIRE-1/0", description="1/0 ACSR wire",
                    uom="LF"):
    """Field setup (IN_PROGRESS) plus a stock item. Returns (scenario, stock)."""
    scenario = setup_field_scenario(
        activate=False,
        contract_overrides={"contract_number": contract_number},
        bid_item_overrides={"item_code": "OH-WIRE-1/0", "description": "1/0 ACSR",
                            "unit": "LF", "unit_price": 6.00,
                            "estimated_quantity": 500},
        wp_overrides={"name": "Reconductor R-5", "location": "Feeder F-6"},
        crew_overrides={"crew_code": "CR-S1"},
        equipment_overrides={"equipment_code": "EQ-S1", "kind": "REEL_TRAILER",
                             "daily_rate": 90.00})
    stock = setup_stock_item(scenario["contract"]["id"],
                             initial_on_hand=initial_on_hand,
                             material_code=material_code,
                             description=description, uom=uom)
    return scenario, stock


class TestIssueBoundary:
    def test_issue_exact_on_hand_empties_shelf(self, api):
        """PRD §3.4: "the draw may not exceed the stock on hand —
        `quantity_issued` at most `on_hand`, with equality permitted so the shelf
        may be drawn to exactly zero, and any excess rejected as
        `ERR_INSUFFICIENT_STOCK` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/material_issue_exact_on_hand_boundary
        """
        scenario, stock = _stock_scenario(api, contract_number="C-700",
                                          material_code="XFR-50KVA",
                                          description="50kVA pole transformer",
                                          uom="EACH")
        receive_stock(stock["id"], 25)

        issue = validate_success(api.create_material_issue(
            scenario["work_package"]["id"],
            {"stock_item_id": stock["id"], "quantity_issued": 25},
            FOREMAN), 201)
        assert_material_issue(issue)
        assert issue["status"] == "OPEN"
        assert issue["quantity_returned"] == 0
        assert issue["quantity_installed"] is None

        stock_after = validate_success(api.get_stock_item(stock["id"], PM))
        assert stock_after["on_hand"] == 0, (
            "Issuing exactly the available on_hand draws the shelf to zero")

    def test_issue_beyond_empty_stock_rejected(self, api):
        """PRD §3.4: "the draw may not exceed the stock on hand —
        `quantity_issued` at most `on_hand`, with equality permitted so the shelf
        may be drawn to exactly zero, and any excess rejected as
        `ERR_INSUFFICIENT_STOCK` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/material_issue_exact_on_hand_boundary
        """
        scenario, stock = _stock_scenario(api, contract_number="C-700",
                                          material_code="XFR-50KVA",
                                          description="50kVA pole transformer",
                                          uom="EACH")
        receive_stock(stock["id"], 25)
        issue_material(scenario["work_package"]["id"], stock["id"], 25)

        resp = api.create_material_issue(
            scenario["work_package"]["id"],
            {"stock_item_id": stock["id"], "quantity_issued": 0.5},
            FOREMAN)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK)
        stock_after = validate_success(api.get_stock_item(stock["id"], PM))
        assert stock_after["on_hand"] == 0, (
            "The rejected issue leaves the empty shelf untouched")


class TestStockConservation:
    def test_stock_conserved_across_issue(self, api):
        """PRD §2.8: "A stock item's `on_hand` is derived, never stored as an
        independent fact: it equals the item's `initial_on_hand`, plus the
        quantity of every receipt recorded against the item, minus the
        `quantity_issued` of every material issue drawn from it, plus the
        `quantity_returned` of those issues."
        0 + 100 receipt = 100; 100 - 30 issued = 70.

        Design: Difficulty/compensating_invariant/stock_issue_return_conservation
        """
        scenario, stock = _stock_scenario(api)
        received = receive_stock(stock["id"], 100)
        assert received["on_hand"] == 100

        issue_material(scenario["work_package"]["id"], stock["id"], 30)
        stock_after = validate_success(api.get_stock_item(stock["id"], PM))
        assert stock_after["on_hand"] == 70, (
            "on_hand drops by the issued quantity")

    def test_stock_restored_exactly_after_full_return(self, api):
        """PRD §2.8: "Issuing a quantity and later returning the same quantity
        restores `on_hand` to its pre-issue value exactly."
        PRD §3.4: "A return names a `quantity`, which is added both to the
        issue's `quantity_returned` and to the stock item's `on_hand`."

        Design: Difficulty/compensating_invariant/stock_issue_return_conservation
        """
        scenario, stock = _stock_scenario(api)
        receive_stock(stock["id"], 100)
        issue = issue_material(scenario["work_package"]["id"], stock["id"], 30)

        returned = get_success_data(api.return_material_issue(
            issue["id"], {"quantity": 30}, FOREMAN))
        assert returned["quantity_returned"] == 30
        stock_after = validate_success(api.get_stock_item(stock["id"], PM))
        assert stock_after["on_hand"] == 100, (
            "The issue/return pair conserves stock units exactly")


class TestReturnsAndReconciliation:
    def test_return_exceeds_issued_rejected(self, api):
        """PRD §3.4: "A return that would push the cumulative `quantity_returned`
        above the original `quantity_issued` is rejected with
        `ERR_RETURN_EXCEEDS_ISSUED`."
        Issued 10, returned 7; a further 4 would push returns to 11 > 10.

        Design: Corner/validations/return_exceeds_issued_rejected
        """
        scenario, stock = _stock_scenario(api, contract_number="CV-3",
                                          initial_on_hand=10,
                                          material_code="MAT-1",
                                          description="Connectors", uom="EACH")
        issue = issue_material(scenario["work_package"]["id"], stock["id"], 10)
        get_success_data(api.return_material_issue(issue["id"], {"quantity": 7},
                                                   FOREMAN))

        resp = api.return_material_issue(issue["id"], {"quantity": 4}, FOREMAN)
        validate_error(resp, ApiErrorId.ERR_RETURN_EXCEEDS_ISSUED)
        issue_after = validate_success(api.get_material_issue(issue["id"], PM))
        assert issue_after["quantity_returned"] == 7, (
            "The rejected return leaves quantity_returned at 7")

    def test_variance_reconcile_requires_pm_and_note(self, api):
        """PRD §3.4: "When the quantities do not balance, only a `CONTRACTOR_PM`
        may reconcile, and only with a non-empty `variance_note` explaining the
        difference; the issue then moves to `VARIANCE_RECONCILED` with `variance`
        recorded as the issued quantity minus the installed quantity minus the
        returned quantity, and the counter likewise drops by one. A foreman
        attempting the variance path, or a variance reconciliation submitted
        without a note, is rejected with `ERR_MATERIAL_VARIANCE_UNRESOLVED`."
        Issued 10, returned 2, installed 5: variance = 10 - 5 - 2 = 3.

        Design: Corner/validations/variance_reconcile_requires_pm_and_note
        """
        scenario, stock = _stock_scenario(api, contract_number="CV-4",
                                          initial_on_hand=10,
                                          material_code="MAT-2",
                                          description="Splices", uom="EACH")
        wp_id = scenario["work_package"]["id"]
        issue = issue_material(wp_id, stock["id"], 10)
        get_success_data(api.return_material_issue(issue["id"], {"quantity": 2},
                                                   FOREMAN))

        foreman_resp = api.reconcile_material_issue(
            issue["id"], {"quantity_installed": 5}, FOREMAN)
        validate_error(foreman_resp, ApiErrorId.ERR_MATERIAL_VARIANCE_UNRESOLVED)

        reconciled = validate_success(api.reconcile_material_issue(
            issue["id"],
            {"quantity_installed": 5,
             "variance_note": "3 units damaged on truck, incident report IR-77"},
            PM))
        assert reconciled["status"] == "VARIANCE_RECONCILED"
        assert reconciled["quantity_installed"] == 5
        assert reconciled["variance"] == 3, (
            "variance = issued 10 - installed 5 - returned 2")

        wp_after = validate_success(api.get_work_package(wp_id, PM))
        assert wp_after["open_material_issue_count"] == 0, (
            "The variance reconciliation drops the open-issue counter to zero")


class TestCrossContractIntegrity:
    def test_cross_contract_stock_reference_rejected(self, api):
        """PRD §3.4: "the stock item must belong to the same contract as the work
        package, otherwise `ERR_CROSS_CONTRACT_REFERENCE`"

        Design: Corner/validations/cross_contract_stock_reference_rejected
        """
        scenario = setup_field_scenario(
            activate=False,
            contract_overrides={"contract_number": "CV-5A"},
            wp_overrides={"name": "WP A", "location": "L12"},
            crew_overrides={"crew_code": "CR-XC"},
            equipment_overrides={"equipment_code": "EQ-XC"})
        contract_b = create_draft_contract(contract_number="CV-5B")
        stock_b = setup_stock_item(contract_b["id"], initial_on_hand=10,
                                   material_code="MAT-B",
                                   description="B-owned stock")

        resp = api.create_material_issue(
            scenario["work_package"]["id"],
            {"stock_item_id": stock_b["id"], "quantity_issued": 1},
            FOREMAN)
        validate_error(resp, ApiErrorId.ERR_CROSS_CONTRACT_REFERENCE)
        stock_b_after = validate_success(api.get_stock_item(stock_b["id"], PM))
        assert stock_b_after["on_hand"] == 10, (
            "The rejected cross-contract issue leaves the other contract's "
            "stock untouched")


class TestReceiptVisibility:
    def test_receipt_response_reflects_on_hand_immediately(self, api):
        """PRD §3.4: "Additional stock arrives through receipts: each receipt
        carries a `quantity` that is added to `on_hand` and increments the stock
        item's `version` by one."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/receipt_response_reflects_on_hand_immediately
        """
        contract = create_draft_contract(contract_number="CM-1")
        stock = setup_stock_item(contract["id"], initial_on_hand=0,
                                 material_code="MAT-C",
                                 description="Cons stock")
        assert_stock_item(stock)
        created_version = stock["version"]

        resp = api.create_stock_receipt(stock["id"], {"quantity": 100}, DISPATCHER)
        updated = validate_success(resp, 200)
        assert updated["on_hand"] == 100, (
            "The receipt response itself shows on_hand 0 + 100 = 100")
        assert updated["version"] == created_version + 1, (
            "Recording a stock receipt increments the stock item's version by one")
