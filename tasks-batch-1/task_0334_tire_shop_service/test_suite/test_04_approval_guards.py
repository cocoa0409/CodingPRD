"""Approval guards (fitment, stock, version), mileage-claim eligibility boundaries, and
related validation rejections (PRD §3.2, §3.9, §2.10).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    create_customer, create_vehicle, create_tire_model, create_fitment_rule,
    create_work_order, add_tire_line, approve_order,
    setup_customer_vehicle_tire, setup_approved_order_with_tire_line,
    setup_submitted_mileage_claim,
)
import test_helpers.factories as F

ADVISOR = TEST_USERS["service_advisor_headers"]
INV = TEST_USERS["inventory_manager_headers"]


# ---------------------------------------------------------------------------
# Rule 5 — fitment (referential) precedence over stock (constraint)
# ---------------------------------------------------------------------------
class TestFitmentBeatsStock:
    def _draft_no_fitment_no_stock(self, api):
        customer = create_customer()
        vehicle = create_vehicle(customer["id"], make="VW", model="GOLF")
        tire = create_tire_model(unit_price_cents=11000, mileage_warranty_miles=45000,
                                 original_tread_32nds=9, stock_qty=0)
        create_fitment_rule(vehicle["id"], tire["id"], grade="NOT_RECOMMENDED")
        wo = create_work_order(customer["id"], vehicle["id"])
        add_tire_line(wo, tire["id"], quantity=4)
        return wo

    def test_fitment_error_wins_over_stock_error(self, api):
        """PRD §3.2: "every `TIRE` line's tire model must have a `FitmentRule` for the order's
        vehicle whose `fitment_grade` is `OE_EXACT` or `APPROVED_PLUS`; any tire whose only
        fitment record is `NOT_RECOMMENDED`, or which has no fitment record for the vehicle at
        all, blocks approval with `ERR_FITMENT_NOT_APPROVED`. Then every `TIRE` line must be
        coverable ... a line that can be neither stocked nor sourced blocks approval with
        `ERR_INSUFFICIENT_STOCK`."

        Both guards fail; the fitment guard is checked first ("Then ..."), so
        ERR_FITMENT_NOT_APPROVED is returned.

        Design: Difficulty/priority_pair_validation_conflict/fitment_referential_beats_stock_constraint_on_approve
        """
        wo = self._draft_no_fitment_no_stock(api)
        validate_error(api.approve_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, ADVISOR),
            ApiErrorId.ERR_FITMENT_NOT_APPROVED)

    def test_fitment_error_is_422(self, api):
        """PRD §3.2: "any tire whose only fitment record is `NOT_RECOMMENDED`, or which has no
        fitment record for the vehicle at all, blocks approval with
        `ERR_FITMENT_NOT_APPROVED`."
        PRD §2.10: "Only the first two grades represent an approved fit; a `NOT_RECOMMENDED`
        grade, or the absence of any fitment record for the pairing, means the tire is not
        approved for that vehicle and blocks order approval".

        Design: Difficulty/priority_pair_validation_conflict/fitment_referential_beats_stock_constraint_on_approve
        """
        wo = self._draft_no_fitment_no_stock(api)
        resp = api.approve_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, ADVISOR)
        validate_error(resp, ApiErrorId.ERR_FITMENT_NOT_APPROVED, expected_status=422)


# ---------------------------------------------------------------------------
# Rule 6 — boundary precision
# ---------------------------------------------------------------------------
class TestMileageBoundary:
    def test_miles_exactly_at_warranty_limit_excluded(self, api):
        """PRD §3.9: "the model's `mileage_warranty_miles` must be greater than zero and the
        claim's `miles_driven` must be strictly less than that mileage rating; a tire whose
        driven mileage has reached or passed its rating is rejected with
        `ERR_MILEAGE_EXCEEDED`."

        miles 60000 == warranty 60000 -> not strictly less -> ERR_MILEAGE_EXCEEDED.

        Design: Difficulty/boundary_precision_check/mileage_exactly_at_warranty_limit_is_excluded
        """
        customer, vehicle, tire, wo, line, claim = setup_submitted_mileage_claim(
            measured_tread_32nds=2, miles_driven=60000, payout_method="REFUND",
            claim_quantity=4,
            tire_overrides={"unit_price_cents": 12000, "mileage_warranty_miles": 60000,
                            "original_tread_32nds": 11, "stock_qty": 8})
        validate_error(api.approve_mileage_claim(claim["id"], ADVISOR),
                       ApiErrorId.ERR_MILEAGE_EXCEEDED)

    def test_miles_one_below_limit_approves(self, api):
        """PRD §3.9: "the claim's `miles_driven` must be strictly less than that mileage
        rating".
        PRD §3.9: "On approval the system computes the payout into `prorated_credit_cents` and
        moves the claim's `status` from `SUBMITTED` to `APPROVED`".

        miles 59999 < warranty 60000 -> eligible -> APPROVED (X-1 side of the boundary).

        Design: Difficulty/boundary_precision_check/mileage_exactly_at_warranty_limit_is_excluded
        """
        customer, vehicle, tire, wo, line, claim = setup_submitted_mileage_claim(
            measured_tread_32nds=2, miles_driven=59999, payout_method="REFUND",
            claim_quantity=4,
            tire_overrides={"unit_price_cents": 12000, "mileage_warranty_miles": 60000,
                            "original_tread_32nds": 11, "stock_qty": 8})
        data = validate_success(api.approve_mileage_claim(claim["id"], ADVISOR))
        assert data["status"] == "APPROVED"


class TestZeroLineApproval:
    def test_approve_order_with_no_lines_rejected(self, api):
        """PRD §3.2: "Approval requires the order to be in `DRAFT`, to have at least one line,
        and to carry `expected_work_order_version` matching the order's current `version`".
        PRD §3.2: "an attempt to add a line to an order in any other state is rejected with
        `ERR_INVALID_STATE`." (ERR_INVALID_STATE is the state-violation error.)

        DRAFT order with zero lines -> approval rejected with ERR_INVALID_STATE.

        Design: Difficulty/boundary_precision_check/zero_line_order_approval_empty_set_rejected
        """
        customer = create_customer()
        vehicle = create_vehicle(customer["id"], make="NISSAN", model="ROGUE", tpms_type="INDIRECT")
        wo = create_work_order(customer["id"], vehicle["id"])
        validate_error(api.approve_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, ADVISOR),
            ApiErrorId.ERR_INVALID_STATE)

    def test_approve_order_with_one_line_succeeds(self, api):
        """PRD §3.2: "Approval is the pivotal event, performed by a `ServiceAdvisor`, that
        moves `fulfillment_status` from `DRAFT` to `APPROVED` and finalizes the order's
        economics."
        PRD §3.2: "Approval requires the order to be in `DRAFT`, to have at least one line".

        One line clears the >=1-line precondition -> APPROVED (the X+1 boundary case).

        Design: Difficulty/boundary_precision_check/zero_line_order_approval_empty_set_rejected
        """
        customer, vehicle, tire, wo, line, approved = setup_approved_order_with_tire_line(
            quantity=4, tire_overrides={"unit_price_cents": 10000, "stock_qty": 8})
        assert approved["fulfillment_status"] == "APPROVED"


# ---------------------------------------------------------------------------
# Corner — claim eligibility & stock validations
# ---------------------------------------------------------------------------
class TestClaimEligibilityRejections:
    def test_not_worn_to_bar_rejected(self, api):
        """PRD §3.9: "the `measured_tread_32nds` must be at or below the wear bar of 2
        thirty-seconds of an inch, and the model must carry a mileage warranty at all ...; a
        tire whose tread is still above the wear bar, or whose model offers no mileage
        warranty, is rejected with `ERR_NOT_WORN_TO_BAR`."

        measured_tread 6 > wear bar 2 -> ERR_NOT_WORN_TO_BAR.

        Design: Corner/validations/not_worn_to_bar_claim_rejected
        """
        customer, vehicle, tire, wo, line, claim = setup_submitted_mileage_claim(
            measured_tread_32nds=6, miles_driven=20000, payout_method="REFUND",
            claim_quantity=4,
            tire_overrides={"unit_price_cents": 14000, "mileage_warranty_miles": 60000,
                            "original_tread_32nds": 10, "stock_qty": 8})
        validate_error(api.approve_mileage_claim(claim["id"], ADVISOR),
                       ApiErrorId.ERR_NOT_WORN_TO_BAR)


class TestStockGuards:
    def test_insufficient_stock_blocks_approve(self, api):
        """PRD §3.2: "every `TIRE` line must be coverable: either the tire model's `stock_qty`
        is sufficient for the line's `quantity`, or a special order that is still open or
        already received exists to cover the shortfall; a line that can be neither stocked nor
        sourced blocks approval with `ERR_INSUFFICIENT_STOCK`."

        qty 4 line, stock 2, no special order, fitment approved -> ERR_INSUFFICIENT_STOCK.

        Design: Corner/validations/insufficient_stock_without_special_order_blocks_approve
        """
        customer, vehicle, tire = setup_customer_vehicle_tire(
            tire_overrides={"unit_price_cents": 14000, "mileage_warranty_miles": 60000,
                            "original_tread_32nds": 10, "stock_qty": 2})
        wo = create_work_order(customer["id"], vehicle["id"])
        add_tire_line(wo, tire["id"], quantity=4)
        validate_error(api.approve_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, ADVISOR),
            ApiErrorId.ERR_INSUFFICIENT_STOCK)

    def test_restock_below_zero_rejected(self, api):
        """PRD §2.10: "A restock whose `delta_qty` would drive `stock_qty` below zero is
        rejected with `ERR_NEGATIVE_STOCK`, and `stock_qty` is never permitted to fall below
        zero through any path."

        stock 3, delta -5 -> would be -2 -> ERR_NEGATIVE_STOCK.

        Design: Corner/validations/restock_below_zero_rejected
        """
        tire = create_tire_model(unit_price_cents=10000, original_tread_32nds=10, stock_qty=3)
        validate_error(api.restock_tire_model(tire["id"], {"delta_qty": -5}, INV),
                       ApiErrorId.ERR_NEGATIVE_STOCK)
