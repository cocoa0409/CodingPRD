"""Customer accounts: documented defaults, OCC on commercial terms, the
credit pre-check at submit, and the customer-ACTIVE gate on submission."""
from test_helpers import (
    ApiErrorId,
    assert_customer,
    get_line_reservations,
    get_order,
    get_order_lines,
    get_success_data,
    make_customer,
    make_customer_headers,
    setup_ambient_order,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

OPS = TEST_USERS["ops_admin_headers"]
ACCOUNTS = TEST_USERS["account_manager_headers"]


class TestCustomerDefaults:
    def test_customer_create_applies_documented_defaults(self, api):
        """PRD §3.3: "An `AccountManager` opens each laboratory account with a `name`, a positive `credit_limit_cents`, and optional commercial terms: a `volume_discount_pct` — a fractional per-line discount between 0 and 0.5 that defaults to 0 — a `hazmat_endorsement` defaulting to `NONE`, and a `cold_chain_certified` flag defaulting to false. New accounts begin `ACTIVE` with `outstanding_balance_cents` at 0."

        Design: Corner/entities/customer_create_applies_documented_defaults
        """
        resp = api.create_customer(
            {"name": "Lab Plain", "credit_limit_cents": 500000}, ACCOUNTS
        )
        data = validate_success(resp, 201)
        assert_customer(data)
        assert data["hazmat_endorsement"] == "NONE"
        assert data["volume_discount_pct"] == 0
        assert data["cold_chain_certified"] is False
        assert data["outstanding_balance_cents"] == 0
        assert data["status"] == "ACTIVE"


class TestCustomerOcc:
    def test_occ_customer_patch_stale_version_rejected(self, api):
        """PRD §2.7: "`PATCH /lab/customers/{customerId}` requires `expected_customer_version`. When it no longer matches the account's current `version` — because an invoice, payment, suspension, or an earlier update already advanced it — the update is rejected with `ERR_STALE_CUSTOMER_VERSION` (HTTP 412), so commercial terms are never overwritten from a stale view."

        Design: Corner/cross_cutting_layers/occ_customer_patch_stale_version_rejected
        """
        customer = make_customer(api, name="Lab Mu", credit_limit_cents=100000)
        observed_version = customer["version"]

        first = api.patch_customer(
            customer["id"],
            {"credit_limit_cents": 200000, "expected_customer_version": observed_version},
            ACCOUNTS,
        )
        patched = validate_success(first, 200)
        assert patched["credit_limit_cents"] == 200000
        assert patched["version"] == observed_version + 1

        second = api.patch_customer(
            customer["id"],
            {"credit_limit_cents": 300000, "expected_customer_version": observed_version},
            ACCOUNTS,
        )
        validate_error(second, ApiErrorId.ERR_STALE_CUSTOMER_VERSION)

        after = validate_success(api.get_customer(customer["id"], ACCOUNTS), 200)
        assert after["credit_limit_cents"] == 200000, (
            "the rejected stale PATCH must change nothing"
        )


class TestCreditPreCheck:
    def test_credit_check_exactly_at_limit_passes(self, api):
        """PRD §3.3: "At order submission, a pre-check requires that the current `outstanding_balance_cents`, plus the projected `product_total_cents` of the order being submitted, plus a projected freight estimate — defined as the base rate of the order's own `shipping_service` computed at zero weight with coolant `NONE`, with no hazmat surcharge, with the freight floor applied, and with the free-freight threshold evaluated against the projected product total — together remain at or below `credit_limit_cents`; otherwise the submit is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

        Design: Corner/calculations/credit_check_exactly_at_limit_passes
        """
        # outstanding 0 + product_total 1000 + STANDARD base 800 == limit 1800: passes.
        ctx = setup_ambient_order(
            api,
            quantity=1,
            lot_quantity=10,
            unit_price_cents=1000,
            customer_overrides={"name": "Lab Edge", "credit_limit_cents": 1800},
            submit=False,
        )
        resp = api.submit_order(
            ctx["order"]["id"], make_customer_headers(ctx["customer"]["id"])
        )
        data = validate_success(resp, 200)
        assert data["status"] == "ALLOCATED", (
            f"equality must pass the at-or-below credit check: {data}"
        )

    def test_credit_limit_exceeded_returns_402(self, api):
        """PRD §3.3: "At order submission, a pre-check requires that the current `outstanding_balance_cents`, plus the projected `product_total_cents` of the order being submitted, plus a projected freight estimate — defined as the base rate of the order's own `shipping_service` computed at zero weight with coolant `NONE`, with no hazmat surcharge, with the freight floor applied, and with the free-freight threshold evaluated against the projected product total — together remain at or below `credit_limit_cents`; otherwise the submit is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

        Design: Corner/validations/credit_limit_exceeded_returns_402
        """
        # projected 1000 + 800 = 1800 > limit 100.
        ctx = setup_ambient_order(
            api,
            quantity=1,
            lot_quantity=10,
            unit_price_cents=1000,
            customer_overrides={"name": "Lab Tiny", "credit_limit_cents": 100},
            submit=False,
        )
        resp = api.submit_order(
            ctx["order"]["id"], make_customer_headers(ctx["customer"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)

        order = get_order(api, ctx["order"]["id"])
        assert order["status"] == "DRAFT", "a credit-rejected submit leaves the order DRAFT"
        lines = get_order_lines(api, ctx["order"]["id"])
        for line in lines:
            assert get_line_reservations(api, line["id"]) == [], (
                "a credit-rejected submit must create no reservations"
            )


class TestSubmitRequiresActiveCustomer:
    def test_order_submit_requires_customer_active_error(self, api):
        """PRD §3.4: "Submission is the pivotal act, and its checks run in a fixed order after the generic chain of §2.6 — the order must be `DRAFT` (`ERR_ORDER_NOT_SUBMITTABLE`), the customer must be `ACTIVE` (`ERR_CUSTOMER_NOT_ACTIVE`), and at least one line must exist (`ERR_ORDER_HAS_NO_LINES`)"

        Design: Difficulty/cross_entity_state_dependency/order_submit_requires_customer_active
        """
        ctx = setup_ambient_order(api, quantity=1, lot_quantity=10, submit=False)
        get_success_data(api.suspend_customer(ctx["customer"]["id"], ACCOUNTS))

        resp = api.submit_order(
            ctx["order"]["id"], make_customer_headers(ctx["customer"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_ACTIVE)

    def test_order_submit_requires_customer_active_no_side_effects(self, api):
        """PRD §3.4: "the order must be `DRAFT` (`ERR_ORDER_NOT_SUBMITTABLE`), the customer must be `ACTIVE` (`ERR_CUSTOMER_NOT_ACTIVE`), and at least one line must exist (`ERR_ORDER_HAS_NO_LINES`)"
        PRD §3.4: "Each successful take creates a reservation in `HELD` status recording its `order_line_id`, `lot_id`, and reserved `quantity`, and moves that quantity from the lot's `quantity_on_hand` into its `quantity_reserved`"

        Design: Difficulty/cross_entity_state_dependency/order_submit_requires_customer_active
        """
        ctx = setup_ambient_order(api, quantity=1, lot_quantity=10, submit=False)
        get_success_data(api.suspend_customer(ctx["customer"]["id"], ACCOUNTS))

        resp = api.submit_order(
            ctx["order"]["id"], make_customer_headers(ctx["customer"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_ACTIVE)

        order = get_order(api, ctx["order"]["id"])
        assert order["status"] == "DRAFT", "the rejected submit must not move the order"
        lines = get_order_lines(api, ctx["order"]["id"])
        assert lines, "the order's materialized lines must still exist"
        for line in lines:
            assert get_line_reservations(api, line["id"]) == [], (
                "the rejected submit must have created no LotReservation rows"
            )
        lot = validate_success(api.get_lot(ctx["lot"]["id"], OPS), 200)
        assert lot["quantity_on_hand"] == 10 and lot["quantity_reserved"] == 0
