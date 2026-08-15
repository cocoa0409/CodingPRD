"""Buy offer pipeline: submission, review, inspection branching, conversion."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_seller, create_bin, create_pending_offer, create_accepted_offer,
    create_received_offer, create_inspection_passed_offer, create_lot,
    create_buy_offer_payload, accept_buy_offer_payload, convert_to_lot_payload,
    make_seller_headers,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

BROKER = TEST_USERS["broker_ops_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


class TestOfferCreation:
    def test_new_offer_starts_pending_review(self, api):
        """PRD section 3.2: "Sourcing begins when a `Seller` submits a buy
        offer for excess inventory, passing a `seller_id` equal to their own
        identity, the manufacturer part number `mpn`, the `quantity` of units
        offered, and the per-unit `ask_price_per_unit_cents`."
        PRD section 3.2: "The new offer enters `PENDING_REVIEW`."

        Design: Corner/state_machines/newly_created_offer_starts_pending_review
        """
        seller = create_seller(name="Init Ingrid")
        res = api.create_buy_offer(
            create_buy_offer_payload(
                seller["id"], mpn="LM317T", quantity=3,
                ask_price_per_unit_cents=4500,
                provenance_doc_url=None,
            ),
            make_seller_headers(seller["id"]),
        )
        offer = validate_success(res, 201)
        assert offer["status"] == "PENDING_REVIEW"
        assert offer["inspection_result"] == "NONE"

    def test_create_offer_missing_quantity_rejected(self, api):
        """PRD section 2.10: "Independently of this ladder, a malformed payload
        — a missing required field, a value of the wrong type, or an unknown
        enum value — is rejected with `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/buy_offer_missing_required_quantity_rejected
        """
        seller = create_seller(name="Req Rachel")
        res = api.create_buy_offer(
            {"seller_id": seller["id"], "mpn": "LM317T",
             "ask_price_per_unit_cents": 5000},
            make_seller_headers(seller["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestAcceptValidation:
    def test_accept_with_unknown_acquisition_mode_rejected(self, api):
        """PRD section 2.10: "Independently of this ladder, a malformed payload
        — a missing required field, a value of the wrong type, or an unknown
        enum value — is rejected with `ERR_INVALID_REQUEST` (400)."
        PRD section 3.2: "the `acquisition_mode` — `BROKER_OWNED` when the
        broker buys the position outright, `CONSIGNMENT` when the parts remain
        the seller's property until sold"

        Design: Corner/entities/buy_offer_invalid_enum_acquisition_mode_rejected
        """
        seller = create_seller(name="Enum Erin")
        offer = create_pending_offer(
            seller, mpn="LM358", quantity=5, ask_price_per_unit_cents=3000,
            provenance_doc_url=None,
        )
        res = api.accept_buy_offer(
            offer["id"],
            {"agreed_unit_price_cents": 3000, "acquisition_mode": "LEASE"},
            BROKER,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        reread = validate_success(api.get_buy_offer(offer["id"], BROKER), 200)
        assert reread["status"] == "PENDING_REVIEW", (
            "a rejected accept must not move the offer out of PENDING_REVIEW"
        )


class TestTerminalStates:
    def test_accept_on_rejected_offer_returns_invalid_state(self, api):
        """PRD section 3.2: "All three of these decisions are available only
        from `PENDING_REVIEW`, and indeed every pipeline action is
        state-guarded — invoking one against an offer in the wrong state is
        rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/buy_offer_rejected_is_terminal
        """
        seller = create_seller(name="Term Tina")
        offer = create_pending_offer(
            seller, mpn="LM358", quantity=5, ask_price_per_unit_cents=3000,
            provenance_doc_url=None,
        )
        validate_success(api.reject_buy_offer(offer["id"], BROKER), 200)

        res = api.accept_buy_offer(
            offer["id"],
            accept_buy_offer_payload(
                agreed_unit_price_cents=3000, acquisition_mode="BROKER_OWNED"
            ),
            BROKER,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestInspectionProvenance:
    def test_pass_without_provenance_document_rejected(self, api):
        """PRD section 3.2: "A passing outcome demands provenance
        documentation: either the offer's `provenance_doc_url` is already set,
        or the inspection payload itself supplies a `provenance_doc_url`; when
        neither is present the pass is rejected with
        `ERR_PROVENANCE_DOCUMENT_REQUIRED`."

        Design: Corner/validations/inspection_pass_without_provenance_rejected
        """
        seller = create_seller(name="Pv Pete")
        offer = create_received_offer(
            seller, mpn="LM317T", quantity=5, ask_price_per_unit_cents=4000,
            agreed_unit_price_cents=4000, provenance_doc_url=None,
        )
        res = api.inspect_buy_offer(offer["id"], {"outcome": "PASS"}, INSPECTOR)
        validate_error(
            res, ApiErrorId.ERR_PROVENANCE_DOCUMENT_REQUIRED, expected_status=422
        )

    def test_pass_succeeds_when_payload_supplies_provenance(self, api):
        """PRD section 3.2: "A passing outcome demands provenance
        documentation: either the offer's `provenance_doc_url` is already set,
        or the inspection payload itself supplies a `provenance_doc_url`; when
        neither is present the pass is rejected with
        `ERR_PROVENANCE_DOCUMENT_REQUIRED`."
        PRD section 3.2: "A successful pass moves the offer to
        `INSPECTION_PASSED` and records `inspection_result` as `PASS`."

        Design: Corner/validations/inspection_pass_without_provenance_rejected
        """
        seller = create_seller(name="Pv Pete")
        offer = create_received_offer(
            seller, mpn="LM317T", quantity=5, ask_price_per_unit_cents=4000,
            agreed_unit_price_cents=4000, provenance_doc_url=None,
        )
        # First attempt without a document fails.
        validate_error(
            api.inspect_buy_offer(offer["id"], {"outcome": "PASS"}, INSPECTOR),
            ApiErrorId.ERR_PROVENANCE_DOCUMENT_REQUIRED,
        )
        # Retry supplying the document in the inspect payload succeeds.
        res = api.inspect_buy_offer(
            offer["id"],
            {"outcome": "PASS",
             "provenance_doc_url": "https://docs.x.com/late.pdf"},
            INSPECTOR,
        )
        passed = validate_success(res, 200)
        assert passed["status"] == "INSPECTION_PASSED"
        assert passed["inspection_result"] == "PASS"


class TestInspectionBranching:
    def test_pass_branch_creates_lot_and_occupies_bin(self, api):
        """PRD section 3.3: "A successful conversion creates the Lot, answers
        with the new resource, and moves the offer to `CONVERTED`. The lot
        carries `buy_offer_id` pointing back to its originating offer, copies
        the `mpn`, copies the offer's acquisition mode into its own
        `storage_mode`, and records `quantity_received` as the offered
        quantity."
        PRD section 3.3: "`occupied_units` is the sum of `qty_available` plus
        `qty_reserved` across every non-`DEPLETED` lot assigned to the bin, and
        `available_units` is `capacity_units` minus that occupancy"

        Design: Difficulty/non_linear_state_machine/buy_offer_inspection_branching_divergent_effects
        """
        seller = create_seller(name="Foxtrot Surplus")
        storage_bin = create_bin(capacity_units=100, bin_code="BIN-F1")
        passed_offer = create_inspection_passed_offer(
            seller, mpn="LM358", quantity=10, ask_price_per_unit_cents=6000,
            agreed_unit_price_cents=6000, acquisition_mode="BROKER_OWNED",
            provenance_doc_url="https://docs.x.com/p6a.pdf",
        )
        res = api.convert_buy_offer_to_lot(
            passed_offer["id"], convert_to_lot_payload(storage_bin["id"]), BROKER
        )
        lot = validate_success(res, 201)
        assert lot["qty_available"] == 10

        offer_after = validate_success(
            api.get_buy_offer(passed_offer["id"], BROKER), 200
        )
        assert offer_after["status"] == "CONVERTED"

        bin_after = validate_success(api.get_storage_bin(storage_bin["id"], BROKER), 200)
        assert bin_after["occupied_units"] == 10
        assert bin_after["available_units"] == 90

    def test_fail_branch_walks_return_without_touching_bin_or_balance(self, api):
        """PRD section 3.2: "Three failure outcomes exist — `FAIL_COUNTERFEIT`
        for suspected counterfeit material, `FAIL_DAMAGED` for physically
        damaged goods, and `FAIL_DOCUMENTATION` for inadequate paperwork — and
        any of them moves the offer to `INSPECTION_FAILED`, records that
        outcome in `inspection_result`, and preserves the inspector's
        `failure_note`."
        PRD section 3.2: "Because the broker never took ownership of returned
        goods, the seller's `account_balance_cents` is left untouched by the
        entire return flow."

        Design: Difficulty/non_linear_state_machine/buy_offer_inspection_branching_divergent_effects
        """
        seller = create_seller(name="Foxtrot Surplus")
        storage_bin = create_bin(capacity_units=100, bin_code="BIN-F1")
        failed_offer = create_received_offer(
            seller, mpn="LM358", quantity=7, ask_price_per_unit_cents=6000,
            agreed_unit_price_cents=6000, acquisition_mode="BROKER_OWNED",
            provenance_doc_url="https://docs.x.com/p6b.pdf",
        )
        failed = validate_success(
            api.inspect_buy_offer(
                failed_offer["id"],
                {"outcome": "FAIL_DAMAGED", "failure_note": "bent pins"},
                INSPECTOR,
            ),
            200,
        )
        assert failed["status"] == "INSPECTION_FAILED"
        assert failed["inspection_result"] == "FAIL_DAMAGED"

        pending = validate_success(
            api.initiate_buy_offer_return(failed_offer["id"], BROKER), 200
        )
        assert pending["status"] == "RETURN_PENDING"
        returned = validate_success(
            api.mark_buy_offer_returned(failed_offer["id"], BROKER), 200
        )
        assert returned["status"] == "RETURNED"

        # No lot was ever created for the failed offer.
        data, meta = validate_paginated(
            api.list_lots(BROKER, params={"buy_offer_id": failed_offer["id"]})
        )
        assert data == [], "FAIL branch must never create a lot"

        bin_after = validate_success(api.get_storage_bin(storage_bin["id"], BROKER), 200)
        assert bin_after["occupied_units"] == 0

        seller_after = validate_success(api.get_seller(seller["id"], BROKER), 200)
        assert seller_after["account_balance_cents"] == 0
        assert seller_after["total_payouts_cents"] == 0


class TestConvertToLot:
    def test_convert_returns_created_lot_with_agreed_cost_basis(self, api):
        """PRD section 3.3: "It opens with `qty_available` equal to the full
        received quantity and `qty_reserved`, `qty_sold`, and `qty_returned`
        all at zero, sets `cost_basis_per_unit_cents` to the agreed unit price,
        stamps `received_at` from the logical clock, opens with
        `is_counterfeit_suspect` false, and starts in `IN_STOCK`."

        Design: Corner/endpoints/convert_to_lot_action_endpoint_returns_created_lot
        """
        seller = create_seller(name="Cv Cathy")
        storage_bin = create_bin(capacity_units=20, bin_code="BIN-CV1")
        offer = create_inspection_passed_offer(
            seller, mpn="TIP120", quantity=7, ask_price_per_unit_cents=6000,
            agreed_unit_price_cents=6200, acquisition_mode="BROKER_OWNED",
            provenance_doc_url="https://docs.x.com/pcv.pdf",
        )
        res = api.convert_buy_offer_to_lot(
            offer["id"], convert_to_lot_payload(storage_bin["id"]), BROKER
        )
        lot = validate_success(res, 201)
        assert lot["cost_basis_per_unit_cents"] == 6200, (
            "cost basis is the agreed price, not the ask"
        )
        assert lot["qty_available"] == 7
        assert lot["qty_reserved"] == 0
        assert lot["qty_sold"] == 0
        assert lot["qty_returned"] == 0
        assert lot["status"] == "IN_STOCK"
        assert lot["is_counterfeit_suspect"] is False

        offer_after = validate_success(api.get_buy_offer(offer["id"], BROKER), 200)
        assert offer_after["status"] == "CONVERTED"


class TestLotFilters:
    def test_lots_filter_by_buy_offer_and_bin(self, api):
        """PRD section 3.3: "Lots may be browsed in a list, optionally filtered
        by `buy_offer_id` or `storage_bin_id`."

        Design: Corner/entities/lot_fk_reverse_reachable_from_bin_and_offer
        """
        seller = create_seller(name="FK Fred")
        storage_bin = create_bin(capacity_units=20, bin_code="BIN-FK1")
        lot, offer = create_lot(
            seller, storage_bin, mpn="NE555", quantity=5,
            ask_price_per_unit_cents=4000, agreed_unit_price_cents=4000,
        )
        by_offer, _ = validate_paginated(
            api.list_lots(BROKER, params={"buy_offer_id": offer["id"]})
        )
        assert [l["id"] for l in by_offer] == [lot["id"]]

        by_bin, _ = validate_paginated(
            api.list_lots(BROKER, params={"storage_bin_id": storage_bin["id"]})
        )
        assert [l["id"] for l in by_bin] == [lot["id"]]


class TestSellerOfferSubresource:
    def test_seller_offer_history_lists_only_own_offers(self, api):
        """PRD section 3.2: "Sellers can follow their own pipeline through the
        buy-offer read and the per-seller offer history, both restricted to
        their own identity."

        Design: Corner/endpoints/seller_offers_subresource_lists_only_own
        """
        seller_a = create_seller(name="Sub Al")
        seller_b = create_seller(name="Sub Bo")
        offer_a = create_pending_offer(
            seller_a, mpn="LM317T", quantity=3, ask_price_per_unit_cents=4000,
            provenance_doc_url=None,
        )

        data_a, _ = validate_paginated(
            api.list_seller_buy_offers(
                seller_a["id"], make_seller_headers(seller_a["id"])
            )
        )
        assert [o["id"] for o in data_a] == [offer_a["id"]]

        data_b, _ = validate_paginated(
            api.list_seller_buy_offers(
                seller_b["id"], make_seller_headers(seller_b["id"])
            )
        )
        assert data_b == []
