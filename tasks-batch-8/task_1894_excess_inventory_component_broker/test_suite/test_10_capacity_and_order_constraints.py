"""Aggregate capacity ceilings, order quantity guard, validation precedence."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_seller, create_customer, create_bin, create_lot, create_active_listing,
    create_inspection_passed_offer, convert_to_lot_payload,
    create_listing_payload, place_order,
    setup_listed_broker_owned_scenario,
    make_customer_headers, make_seller_headers,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

BROKER = TEST_USERS["broker_ops_headers"]


class TestBinCapacityCeiling:
    def _three_passed_offers(self, api):
        """Bin capacity 100 with a 60-unit lot already inside; two more
        passed offers of qty 40 and qty 1 awaiting conversion."""
        seller = create_seller(name="Papa Parts")
        storage_bin = create_bin(capacity_units=100, bin_code="BIN-P1")
        lot_p, _ = create_lot(
            seller, storage_bin, mpn="ULN2003", quantity=60,
            ask_price_per_unit_cents=3000, agreed_unit_price_cents=3000,
            provenance_doc_url="https://docs.x.com/p16a.pdf",
        )
        offer_q = create_inspection_passed_offer(
            seller, mpn="ULN2003", quantity=40, ask_price_per_unit_cents=3000,
            agreed_unit_price_cents=3000, acquisition_mode="BROKER_OWNED",
            provenance_doc_url="https://docs.x.com/p16b.pdf",
        )
        offer_r = create_inspection_passed_offer(
            seller, mpn="ULN2003", quantity=1, ask_price_per_unit_cents=3000,
            agreed_unit_price_cents=3000, acquisition_mode="BROKER_OWNED",
            provenance_doc_url="https://docs.x.com/p16c.pdf",
        )
        return seller, storage_bin, lot_p, offer_q, offer_r

    def test_exact_fit_admitted(self, api):
        """PRD section 3.3: "Conversion is an admission decision against bin
        capacity: the offer's `quantity` must fit within the bin's
        `available_units`. An exact fit is admitted; one unit over is rejected
        with `ERR_BIN_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/storage_bin_aggregate_capacity_exact_fit
        """
        _, storage_bin, _, offer_q, _ = self._three_passed_offers(api)
        # 60 occupied; available 40; converting the qty-40 offer is an exact fit.
        lot_q = validate_success(
            api.convert_buy_offer_to_lot(
                offer_q["id"], convert_to_lot_payload(storage_bin["id"]), BROKER
            ),
            201,
        )
        assert lot_q["qty_available"] == 40

        bin_after = validate_success(api.get_storage_bin(storage_bin["id"], BROKER), 200)
        assert bin_after["occupied_units"] == 100
        assert bin_after["available_units"] == 0

    def test_one_unit_over_ceiling_rejected(self, api):
        """PRD section 3.3: "Conversion is an admission decision against bin
        capacity: the offer's `quantity` must fit within the bin's
        `available_units`. An exact fit is admitted; one unit over is rejected
        with `ERR_BIN_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/storage_bin_aggregate_capacity_exact_fit
        """
        _, storage_bin, _, offer_q, offer_r = self._three_passed_offers(api)
        validate_success(
            api.convert_buy_offer_to_lot(
                offer_q["id"], convert_to_lot_payload(storage_bin["id"]), BROKER
            ),
            201,
        )
        # Bin now full (100/100); one more unit must be rejected.
        res = api.convert_buy_offer_to_lot(
            offer_r["id"], convert_to_lot_payload(storage_bin["id"]), BROKER
        )
        validate_error(res, ApiErrorId.ERR_BIN_CAPACITY_EXCEEDED, expected_status=422)

        bin_after = validate_success(api.get_storage_bin(storage_bin["id"], BROKER), 200)
        assert bin_after["occupied_units"] == 100
        assert bin_after["available_units"] == 0


class TestOrderQuantityGuard:
    def _scenario(self, api):
        return setup_listed_broker_owned_scenario(
            mpn="ULN2003", quantity=10, agreed_unit_price_cents=3000,
            asking_price_per_unit_cents=5000,
            credit_limit_cents=1_000_000, urgency_tier="STANDARD", bin_capacity=50,
        )

    def test_quantity_over_available_rejected(self, api):
        """PRD section 3.6: "the `quantity` must not exceed the lot's
        `qty_available`, failing with `ERR_QUANTITY_EXCEEDS_AVAILABLE`"

        Design: Corner/validations/order_quantity_exceeds_available_rejected
        """
        sc = self._scenario(api)
        res = api.create_sales_order(
            {"customer_id": sc["customer"]["id"],
             "listing_id": sc["listing"]["id"], "quantity": 11},
            make_customer_headers(sc["customer"]["id"]),
        )
        validate_error(
            res, ApiErrorId.ERR_QUANTITY_EXCEEDS_AVAILABLE, expected_status=422
        )

    def test_exact_available_quantity_drains_lot_to_fully_reserved(self, api):
        """PRD section 3.6: "Creation moves physical units immediately: the
        lot's `qty_available` decreases and its `qty_reserved` increases by the
        ordered quantity, and the posture recomputes — an order that drains the
        last available unit pushes the lot to `FULLY_RESERVED`."

        Design: Corner/validations/order_quantity_exceeds_available_rejected
        """
        sc = self._scenario(api)
        order = place_order(sc["customer"], sc["listing"], quantity=10)
        assert order["quantity"] == 10

        lot = validate_success(api.get_lot(sc["lot"]["id"], BROKER), 200)
        assert lot["qty_available"] == 0
        assert lot["qty_reserved"] == 10
        assert lot["status"] == "FULLY_RESERVED"


class TestValidationPrecedence:
    def test_state_error_beats_fiscal_error_on_order_create(self, api):
        """PRD section 2.10: "Requests are validated against a fixed precedence
        ladder, so a request violating several rules always surfaces the
        earliest failure rather than an arbitrary one."
        PRD section 2.10: "Sixth, state eligibility: the target resource must
        sit in a valid source state for the requested transition, failing with
        `ERR_INVALID_STATE` or with one of the specific state guards introduced
        in §3. Seventh, counterfeit and provenance safety
        (`ERR_COUNTERFEIT_SUSPECTED`, `ERR_PROVENANCE_DOCUMENT_REQUIRED`).
        Eighth, consignment window rules. Ninth, structural constraints: bin
        capacity, available quantity, the asking-price floor, escrow
        overpayment, consignment seller matching, fee range, and bin-code
        uniqueness. Tenth and last, fiscal guards: customer credit sufficiency
        and the strict positivity of monetary and quantity inputs."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_order_create
        """
        sc = setup_listed_broker_owned_scenario(
            mpn="LM317T", quantity=10, agreed_unit_price_cents=8000,
            asking_price_per_unit_cents=10000,
            credit_limit_cents=1000, urgency_tier="CRITICAL", bin_capacity=100,
        )
        # Pause the listing: listing not ACTIVE (state, priority 6).
        validate_success(api.pause_listing(sc["listing"]["id"], BROKER), 200)
        # qty 10 at CRITICAL -> required 125000 > credit 1000 (fiscal, priority 10).
        res = api.create_sales_order(
            {"customer_id": sc["customer"]["id"],
             "listing_id": sc["listing"]["id"], "quantity": 10},
            make_customer_headers(sc["customer"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_LISTING_NOT_ACTIVE, expected_status=409)

    def test_state_error_returned_not_fiscal_when_both_violated(self, api):
        """PRD section 2.10: "Sixth, state eligibility: the target resource
        must sit in a valid source state for the requested transition, failing
        with `ERR_INVALID_STATE` or with one of the specific state guards
        introduced in §3."
        PRD section 3.6: "Admission requires the existing exposure plus the new
        order's `required_escrow_cents` to be no more than
        `credit_limit_cents` — exact equality is admitted, and one cent over is
        rejected with `ERR_INSUFFICIENT_CUSTOMER_CREDIT` (402)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_order_create
        """
        sc = setup_listed_broker_owned_scenario(
            mpn="LM317T", quantity=10, agreed_unit_price_cents=8000,
            asking_price_per_unit_cents=10000,
            credit_limit_cents=1000, urgency_tier="CRITICAL", bin_capacity=100,
        )
        validate_success(api.pause_listing(sc["listing"]["id"], BROKER), 200)
        res = api.create_sales_order(
            {"customer_id": sc["customer"]["id"],
             "listing_id": sc["listing"]["id"], "quantity": 10},
            make_customer_headers(sc["customer"]["id"]),
        )
        body = res.json()
        assert body["data"]["error_id"] == "ERR_LISTING_NOT_ACTIVE"
        assert body["data"]["error_id"] != "ERR_INSUFFICIENT_CUSTOMER_CREDIT", (
            "the earlier state failure must surface, not the later fiscal one"
        )
