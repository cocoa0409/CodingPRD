"""RBAC denials, ownership enforcement, and not-found errors."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_seller, create_customer, create_bin, create_lot, create_pending_offer,
    create_buy_offer_payload, accept_buy_offer_payload, create_listing_payload,
    place_order, advance_order_to_delivered,
    setup_listed_broker_owned_scenario,
    make_seller_headers, make_customer_headers,
    api_client,
    TEST_USERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
)

BROKER = TEST_USERS["broker_ops_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
FINANCE = TEST_USERS["finance_admin_headers"]


class TestRoleDenials:
    def test_inspector_cannot_accept_offer(self, api):
        """PRD section 2.1: "Every operation names the roles permitted to
        invoke it; a caller whose role is not in that list is rejected with
        `ERR_FORBIDDEN_ROLE` (403)."
        PRD section 3.2: "Adjudication belongs to `BrokerOps`. Accepting the
        offer records the broker-agreed `agreed_unit_price_cents` per unit and
        the `acquisition_mode`"

        Design: Corner/roles/inspector_cannot_accept_offer
        """
        seller = create_seller(name="Rb Rob")
        offer = create_pending_offer(
            seller, mpn="LM358", quantity=5, ask_price_per_unit_cents=3000,
            provenance_doc_url=None,
        )
        res = api.accept_buy_offer(
            offer["id"],
            accept_buy_offer_payload(
                agreed_unit_price_cents=3000, acquisition_mode="BROKER_OWNED"
            ),
            INSPECTOR,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    def test_brokerops_cannot_settle_segregation_of_duties(self, api):
        """PRD section 2.1: "`FinanceAdmin` is deliberately separated from
        operations and alone may settle delivered orders and issue approved
        refunds — the staff who move the goods never release the money."

        Design: Corner/roles/brokerops_cannot_settle_segregation_of_duties
        """
        sc = setup_listed_broker_owned_scenario(
            mpn="BC547", quantity=3, agreed_unit_price_cents=4000,
            asking_price_per_unit_cents=5000,
            credit_limit_cents=100000, urgency_tier="STANDARD", bin_capacity=20,
        )
        order = place_order(sc["customer"], sc["listing"], quantity=1)
        delivered = advance_order_to_delivered(sc["customer"], order)

        res = api.settle_sales_order(delivered["id"], BROKER)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

        reread = validate_success(api.get_sales_order(delivered["id"], BROKER), 200)
        assert reread["status"] == "DELIVERED", (
            "a role-denied settle must leave the order DELIVERED"
        )

    def test_seller_cannot_cancel_other_sellers_offer(self, api):
        """PRD section 2.1: "An entity-backed caller acting on a resource it
        does not own is rejected with `ERR_FORBIDDEN_OWNERSHIP` (403)."
        PRD section 3.2: "The seller may instead withdraw a still-pending offer
        themselves, moving it to `CANCELLED`; cancel is restricted to the
        offering seller."

        Design: Corner/roles/seller_cannot_cancel_other_sellers_offer
        """
        seller_a = create_seller(name="Ow Owen")
        seller_b = create_seller(name="Ow Olaf")
        offer = create_pending_offer(
            seller_a, mpn="LM317T", quantity=3, ask_price_per_unit_cents=4000,
            provenance_doc_url=None,
        )
        res = api.cancel_buy_offer(offer["id"], make_seller_headers(seller_b["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, expected_status=403)

        reread = validate_success(api.get_buy_offer(offer["id"], BROKER), 200)
        assert reread["status"] == "PENDING_REVIEW"

    def test_customer_cannot_create_listing(self, api):
        """PRD section 2.1: "Every operation names the roles permitted to
        invoke it; a caller whose role is not in that list is rejected with
        `ERR_FORBIDDEN_ROLE` (403)."
        PRD section 3.5: "`BrokerOps` creates it in `DRAFT` against a `lot_id`"

        Design: Corner/roles/customer_cannot_create_listing
        """
        seller = create_seller(name="Cl Carl")
        customer = create_customer(
            name="Cl Cora", credit_limit_cents=10000, urgency_tier="STANDARD"
        )
        storage_bin = create_bin(capacity_units=20, bin_code="BIN-CL1")
        lot, _ = create_lot(
            seller, storage_bin, mpn="NE555", quantity=3,
            ask_price_per_unit_cents=4000, agreed_unit_price_cents=4000,
        )
        res = api.create_listing(
            create_listing_payload(lot["id"], asking_price_per_unit_cents=6000),
            make_customer_headers(customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


class TestNotFound:
    def test_get_listing_not_found(self, api):
        """PRD section 2.10: "Fourth, existence: every identifier in the path
        and every foreign key referenced in the request body must resolve to a
        real resource, with path identifiers checked left to right and the
        first unresolved identifier producing its specific 404 —
        `ERR_SELLER_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
        `ERR_STORAGE_BIN_NOT_FOUND`, `ERR_BUY_OFFER_NOT_FOUND`,
        `ERR_LOT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
        `ERR_SALES_ORDER_NOT_FOUND`, `ERR_CONSIGNMENT_AGREEMENT_NOT_FOUND`, or
        `ERR_RETURN_CASE_NOT_FOUND`, according to the resource type."

        Design: Corner/entities/get_listing_not_found_returns_404
        """
        res = api.get_listing(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", BROKER
        )
        validate_error(res, ApiErrorId.ERR_LISTING_NOT_FOUND, expected_status=404)

    def test_get_sales_order_not_found(self, api):
        """PRD section 2.10: "Fourth, existence: every identifier in the path
        and every foreign key referenced in the request body must resolve to a
        real resource, with path identifiers checked left to right and the
        first unresolved identifier producing its specific 404 —
        `ERR_SELLER_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
        `ERR_STORAGE_BIN_NOT_FOUND`, `ERR_BUY_OFFER_NOT_FOUND`,
        `ERR_LOT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
        `ERR_SALES_ORDER_NOT_FOUND`, `ERR_CONSIGNMENT_AGREEMENT_NOT_FOUND`, or
        `ERR_RETURN_CASE_NOT_FOUND`, according to the resource type."

        Design: Corner/errors/error_sales_order_not_found
        """
        res = api.get_sales_order(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", BROKER
        )
        validate_error(res, ApiErrorId.ERR_SALES_ORDER_NOT_FOUND, expected_status=404)


class TestOrderOnInactiveListing:
    def test_order_against_draft_listing_rejected(self, api):
        """PRD section 3.6: "Admission runs the precedence ladder of §2.10: the
        listing must be `ACTIVE`, failing with `ERR_LISTING_NOT_ACTIVE`; the
        underlying lot must not be counterfeit-suspect, failing with
        `ERR_COUNTERFEIT_SUSPECTED`; the `quantity` must not exceed the lot's
        `qty_available`, failing with `ERR_QUANTITY_EXCEEDS_AVAILABLE`; and the
        customer's credit must absorb the new exposure, as defined below."

        Design: Corner/errors/error_listing_not_active_on_draft_order
        """
        seller = create_seller(name="Dl Dana")
        customer = create_customer(
            name="Dl Dan", credit_limit_cents=100000, urgency_tier="STANDARD"
        )
        storage_bin = create_bin(capacity_units=20, bin_code="BIN-DL1")
        lot, _ = create_lot(
            seller, storage_bin, mpn="NE555", quantity=5,
            ask_price_per_unit_cents=4000, agreed_unit_price_cents=4000,
        )
        listing = validate_success(
            api.create_listing(
                create_listing_payload(lot["id"], asking_price_per_unit_cents=5000),
                BROKER,
            ),
            201,
        )
        res = api.create_sales_order(
            {"customer_id": customer["id"], "listing_id": listing["id"],
             "quantity": 1},
            make_customer_headers(customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_LISTING_NOT_ACTIVE, expected_status=409)
