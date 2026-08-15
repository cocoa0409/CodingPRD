"""Entity corner cases (corner-design §entities).

Creation defaults, required-field and enum validation, 404 shape, computed
fields at creation, Payment append-only shape, and nested-parent existence.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    FINANCE,
    OPS,
    TEST_USERS,
    api_client,
    assert_payment,
    get_success_data,
    make_clerk_headers,
    make_officer_headers,
    setup_invoiced_order,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    create_agent,
    create_catalog_item,
    create_stock_lot,
    create_vessel_call,
    pay_invoice,
)

WAREHOUSE = TEST_USERS["warehouse_headers"]


class TestVesselCallCreationDefaults:
    def test_vessel_call_creation_defaults(self, api):
        """PRD §3.1: "A new call starts as `SCHEDULED` with
        `customs_clearance_status` `PENDING`, and `actual_eta` and `actual_etd`
        remain unset until the corresponding events occur." PRD §2.4: "an
        integer `version` that starts at 1 on creation".

        Design: Corner/entities/vessel_call_creation_defaults
        """
        agent = create_agent(name="Agent AA")
        call = create_vessel_call(
            agent["id"], vessel_name="MV Aurora II", imo_number="9074760",
            foreign_going=True,
        )
        assert call["status"] == "SCHEDULED"
        assert call["customs_clearance_status"] == "PENDING"
        assert call["actual_eta"] is None
        assert call["actual_etd"] is None
        assert call["version"] == 1


class TestShipAgentRequiredFields:
    def test_ship_agent_missing_required_field_returns_invalid_request(self, api):
        """PRD §3.1: "a `FinanceController` registers a paying agent, supplying the
        agent company `name`, the `settlement_currency` (one of `USD`, `EUR`,
        `GBP`, or `SGD`), a `credit_limit_cents` ceiling in cents of that
        currency, and `payment_terms_days`". Omitting the required
        settlement_currency is rejected with ERR_INVALID_REQUEST (400).

        Design: Corner/entities/ship_agent_missing_required_field_returns_invalid_request
        """
        resp = api_client.create_ship_agent(
            {"name": "Agent NoCurrency", "credit_limit_cents": 1000,
             "payment_terms_days": 30},
            FINANCE,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestCatalogItemEnumValidation:
    def test_catalog_item_invalid_enum_rejected(self, api):
        """PRD §3.1: "a `category` of `PROVISIONS`, `BONDED`, `DECK`, `ENGINE`, or
        `CABIN`". A category outside that set fails with ERR_INVALID_REQUEST
        before any persistence.

        Design: Corner/entities/catalog_item_invalid_enum_rejected
        """
        resp = api_client.create_catalog_item(
            {"sku": "BAD-01", "name": "Mystery", "category": "FRESH",
             "bonded_eligible": False, "requires_cold_chain": False,
             "base_price_cents": 100},
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestVesselCallNotFound:
    def test_vessel_call_get_not_found_returns_404(self, api):
        """PRD §5: `ERR_VESSEL_CALL_NOT_FOUND` (404). GET on a random UUID yields
        ERR_VESSEL_CALL_NOT_FOUND.

        Design: Corner/entities/vessel_call_get_not_found_returns_404
        """
        resp = api_client.get_vessel_call(NON_EXISTENT_UUID, OPS)
        validate_error(resp, ApiErrorId.ERR_VESSEL_CALL_NOT_FOUND)


class TestStockLotComputedOnHandAtCreation:
    def test_stock_lot_computed_on_hand_at_creation(self, api):
        """PRD §3.2: "On creation the lot's `on_hand_qty` is set equal to
        `received_qty` and `reserved_qty` starts at zero."

        Design: Corner/entities/stock_lot_computed_on_hand_at_creation
        """
        item = create_catalog_item(
            sku="WATER-C1", name="Water 1L", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=False,
            base_price_cents=120, duty_rate_pct=0,
        )
        lot = create_stock_lot(item["id"], lot_code="DS-C1", received_qty=250)
        assert lot["on_hand_qty"] == 250
        assert lot["reserved_qty"] == 0


class TestPaymentImmutableNoVersionField:
    def test_payment_immutable_no_version_field(self, api):
        """PRD §2.4: "The `Payment` entity is the single exception: it is an
        append-only event log entry and carries only `id` and `created_at` —
        neither `updated_at` nor `version` exists on payments, and no payment
        record is ever mutated after creation." A 120,000-cent USD payment
        against a 120,000 USD invoice also shows identity conversion
        (converted_amount_cents == amount_cents; PRD §3.10: "If the payment
        currency equals the invoice's `settlement_currency`, the converted
        amount is the tendered amount").

        Design: Corner/entities/payment_immutable_no_version_field
        """
        ctx = setup_invoiced_order(
            qty=1000, unit_price_cents=120, fx_rate_to_settlement=1.0,
            agent_overrides=dict(name="Agent AB"),
            item_overrides=dict(sku="WATER-C2", name="Water 1L"),
            lot_overrides=dict(lot_code="DS-C2", received_qty=10000),
        )
        payment = pay_invoice(ctx["invoice"]["id"], ctx["agent"]["id"], 120000, currency="USD")
        assert payment["converted_amount_cents"] == 120000, (
            "Same currency: identity conversion"
        )
        assert_payment(payment)  # asserts id + created_at present, version/updated_at absent


class TestRequisitionRequiresExistingVesselCallParent:
    def test_requisition_requires_existing_vessel_call_parent(self, api):
        """PRD §3.3: "Creation is nested under the vessel call". Creating a
        requisition under a non-existent vessel call id yields
        ERR_VESSEL_CALL_NOT_FOUND (existence is validated before any body
        check).

        Design: Corner/entities/requisition_requires_existing_vessel_call_parent
        """
        item = create_catalog_item(
            sku="WATER-C3", name="Water 1L", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=False,
            base_price_cents=120, duty_rate_pct=0,
        )
        resp = api_client.create_requisition(
            NON_EXISTENT_UUID,
            {"title": "orphan", "lines": [{
                "catalog_item_id": item["id"], "requested_qty": 1,
                "allows_substitution": False,
            }]},
            make_officer_headers(NON_EXISTENT_UUID),
        )
        validate_error(resp, ApiErrorId.ERR_VESSEL_CALL_NOT_FOUND)
