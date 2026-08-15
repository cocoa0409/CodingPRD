"""Order freight thresholds and the confirm-time credit gate."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_branch,
    create_customer,
    create_item,
    get_customer,
    place_order,
    restock,
    validate_error,
    validate_success,
)


def _freight_scenario(api, admin_headers):
    """Customer credit 10,000,000; item A list 25,000 hazmat NONE; item B list
    25,000 hazmat GROUND_ONLY; branch stocked 1 of each."""
    customer = create_customer(
        account_number="FR-1", credit_limit_cents=10000000,
        primary_ship_to_state="OH",
    )
    item_a = create_item(sku="FR-25K", list_price_cents=25000)
    item_b = create_item(
        sku="HZ-25K", hazmat_restriction="GROUND_ONLY", list_price_cents=25000
    )
    branch = create_branch(location_code="BR-5")
    restock(branch["id"], item_a["id"], 1)
    restock(branch["id"], item_b["id"], 1)
    return customer, item_a, item_b, branch


class TestFreightThresholdOnPreFreightSubtotal:
    def test_subtotal_at_threshold_waives_base_freight(self, api, admin_headers):
        """PRD §3.5: "Freight follows a pinned order: `WILL_CALL` orders never
        carry base freight; for delivery methods, a `subtotal_cents` reaching
        25,000 cents waives the base freight entirely; otherwise `SAME_DAY`
        carries 1,500 cents and `STANDARD` 795 cents."
        PRD §3.5: "the free-freight test always reads the pre-freight subtotal,
        never the total."

        Design: Difficulty/combinatorial_formula/freight_threshold_on_pre_freight_subtotal
        """
        customer, item_a, _item_b, branch = _freight_scenario(api, admin_headers)
        order = place_order(
            customer["id"], branch["id"],
            [{"item_id": item_a["id"], "qty": 1}],
            fulfillment_method="STANDARD",
        )
        assert order["subtotal_cents"] == 25000
        assert order["freight_cents"] == 0
        assert order["total_cents"] == 25000

    def test_hazmat_handling_added_even_when_base_freight_waived(
        self, api, admin_headers
    ):
        """PRD §3.5: "Independently of any waiver, when any line's item has a
        `hazmat_restriction` other than `NONE` and the order is not will-call, a
        2,500-cent hazmat handling charge is added — even when the base freight
        was waived."

        Design: Difficulty/combinatorial_formula/freight_threshold_on_pre_freight_subtotal
        """
        customer, _item_a, item_b, branch = _freight_scenario(api, admin_headers)
        order = place_order(
            customer["id"], branch["id"],
            [{"item_id": item_b["id"], "qty": 1}],
            fulfillment_method="STANDARD",
        )
        assert order["subtotal_cents"] == 25000
        assert order["freight_cents"] == 2500
        assert order["total_cents"] == 27500


class TestFreeFreightBoundary:
    def test_free_freight_one_cent_below_threshold(self, api, admin_headers):
        """PRD §3.5: "for delivery methods, a `subtotal_cents` reaching 25,000
        cents waives the base freight entirely; otherwise `SAME_DAY` carries
        1,500 cents and `STANDARD` 795 cents."

        Design: Corner/calculations/free_freight_one_cent_below_threshold
        """
        customer = create_customer(
            account_number="FF-1", credit_limit_cents=100000,
            primary_ship_to_state="OH",
        )
        item = create_item(sku="FF-1", list_price_cents=24999)
        branch = create_branch(location_code="BR-FF")
        restock(branch["id"], item["id"], 1)
        order = place_order(
            customer["id"], branch["id"],
            [{"item_id": item["id"], "qty": 1}],
            fulfillment_method="STANDARD",
        )
        assert order["subtotal_cents"] == 24999
        assert order["freight_cents"] == 795
        assert order["total_cents"] == 25794


class TestCreditGate:
    def test_credit_limit_exact_equality_allowed(self, api, admin_headers):
        """PRD §3.6: "if the account's `open_credit_exposure_cents` plus the
        order's `total_cents` would exceed `credit_limit_cents`, confirmation is
        rejected with `ERR_CREDIT_LIMIT_EXCEEDED`; exact equality with the limit
        is allowed."
        PRD §3.6: "Confirmation then stamps `confirmed_at` from the logical clock
        and debits the account's `open_credit_exposure_cents` by the order's
        `total_cents`."

        Design: Corner/validations/credit_limit_exact_equality_allowed
        """
        customer = create_customer(
            account_number="CE-1", credit_limit_cents=5000,
            primary_ship_to_state="OH",
        )
        item = create_item(sku="CE-1", list_price_cents=5000)
        branch = create_branch(location_code="BR-CE")
        restock(branch["id"], item["id"], 1)
        order = place_order(
            customer["id"], branch["id"], [{"item_id": item["id"], "qty": 1}]
        )
        assert order["total_cents"] == 5000  # WILL_CALL: no freight

        confirmed = validate_success(api.confirm_order(order["id"], admin_headers))
        assert confirmed["status"] == "CONFIRMED"

        account = get_customer(customer["id"])
        assert account["open_credit_exposure_cents"] == 5000

    def test_credit_limit_exceeded_pure_fiscal(self, api, admin_headers):
        """PRD §3.6: "Fourth and last, the fiscal gate: if the account's
        `open_credit_exposure_cents` plus the order's `total_cents` would exceed
        `credit_limit_cents`, confirmation is rejected with
        `ERR_CREDIT_LIMIT_EXCEEDED`; exact equality with the limit is allowed."

        Design: Corner/errors/credit_limit_exceeded_pure_fiscal
        """
        customer = create_customer(
            account_number="CL-1", credit_limit_cents=1000,
            primary_ship_to_state="OH",
        )
        item = create_item(sku="CL-1", list_price_cents=5000)
        branch = create_branch(location_code="BR-CL")
        restock(branch["id"], item["id"], 1)
        order = place_order(
            customer["id"], branch["id"], [{"item_id": item["id"], "qty": 1}]
        )
        res = api.confirm_order(order["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
