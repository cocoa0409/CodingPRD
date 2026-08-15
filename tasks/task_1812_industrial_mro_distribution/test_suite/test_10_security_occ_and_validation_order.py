"""Auth headers, RBAC, entity-backed scoping, OCC, and existence ordering."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    create_branch,
    create_cart,
    create_customer,
    create_customer_payload,
    create_item,
    create_return,
    get_order_lines,
    make_buyer_headers,
    place_order,
    restock,
    setup_fulfilled_order,
    validate_error,
    validate_success,
    walk_return_to_received,
)

ADMIN = TEST_USERS["admin_headers"]
BRANCH_MANAGER = TEST_USERS["branch_manager_headers"]
VENDOR_REP = TEST_USERS["vendor_rep_headers"]


class TestAuthAndExistence:
    def test_request_missing_auth_headers_returns_error(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity in
        which they act. A request missing either header, or presenting a role the
        system does not declare, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/request_missing_auth_headers_returns_error
        """
        res = api.create_customer(
            {
                "account_number": "NA-1",
                "display_name": "NoAuth Co",
                "credit_limit_cents": 1000,
                "primary_ship_to_state": "OH",
            },
            {},
        )
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_existence_checked_left_to_right(self, api, admin_headers):
        """PRD §2.8: "A request aimed at a rebate agreement beneath a customer
        validates the customer before the agreement: a missing customer yields
        `ERR_CUSTOMER_NOT_FOUND` before the agreement is ever examined"

        Design: Corner/validations/existence_checked_left_to_right
        """
        res = api.create_rebate_agreement(
            NON_EXISTENT_UUID,
            {
                "period_start": "2026-01-01",
                "period_end": "2026-03-31",
                "tiers": [{"threshold_cents": 0, "rebate_bps": 100}],
            },
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_CUSTOMER_NOT_FOUND)


class TestRoleExclusivity:
    def test_buyer_cannot_create_item_returns_forbidden(self, api, admin_headers):
        """PRD §2.1: "Each endpoint admits a specific set of roles (§4); a caller
        whose role is not permitted on the targeted endpoint is rejected with
        `ERR_FORBIDDEN_ROLE`."
        PRD §4: "POST `/mro/items` | Create a catalog item | DistributionAdmin"

        Design: Corner/roles/buyer_cannot_create_item_returns_forbidden
        """
        customer = create_customer(account_number="RB-1", credit_limit_cents=100000)
        res = api.create_item(
            {"sku": "RB-1", "description": "Forbidden", "item_class": "STOCKED",
             "list_price_cents": 100},
            make_buyer_headers(customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    def test_branch_manager_cannot_confirm_order_returns_forbidden(
        self, api, admin_headers
    ):
        """PRD §2.1: "a caller whose role is not permitted on the targeted
        endpoint is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: "POST `/mro/orders/{id}/confirm` | Confirm a SUBMITTED order:
        hazmat and credit gates, the allocation waterfall, promise date, and
        provisional drop-ship margins | DistributionAdmin"

        Design: Corner/roles/branch_manager_cannot_confirm_order_returns_forbidden
        """
        customer = create_customer(account_number="RB-3", credit_limit_cents=100000)
        item = create_item(sku="RB-3", list_price_cents=100)
        branch = create_branch(location_code="BR-RB")
        restock(branch["id"], item["id"], 1)
        order = place_order(
            customer["id"], branch["id"], [{"item_id": item["id"], "qty": 1}]
        )
        res = api.confirm_order(order["id"], BRANCH_MANAGER)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    def test_vendor_rep_cannot_credit_return_returns_forbidden(
        self, api, admin_headers
    ):
        """PRD §2.1: "a caller whose role is not permitted on the targeted
        endpoint is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: "POST `/mro/returns/{id}/credit` | Credit a received return;
        computes the per-line-rounded credit and decrements spend accruals |
        DistributionAdmin"

        Design: Corner/roles/vendor_rep_cannot_credit_return_returns_forbidden
        """
        scenario = setup_fulfilled_order(
            [{"qty": 1, "sku": "RB-4", "list_price_cents": 100}],
            customer_overrides={"account_number": "RB-4",
                                "credit_limit_cents": 100000},
            branch_overrides={"location_code": "BR-VR"},
            restock_qtys=[1],
        )
        line_id = get_order_lines(scenario["order"]["id"])[0]["id"]
        ret = create_return(
            scenario["order"]["id"],
            [{"order_line_id": line_id, "qty": 1, "condition": "DAMAGED"}],
        )
        walk_return_to_received(ret["id"])

        res = api.credit_return(ret["id"], VENDOR_REP)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


class TestCustomerScopeContainment:
    def test_buyer_cannot_read_other_account_cart_returns_scope_error(
        self, api, admin_headers
    ):
        """PRD §2.1: "A buyer or approver who touches a cart, order, return, or
        customer record owned by a different account is rejected with
        `ERR_CUSTOMER_SCOPE_MISMATCH`; their reads are likewise confined to their
        own account's resources."

        Design: Corner/roles/buyer_cannot_read_other_account_cart_returns_scope_error
        """
        customer_a = create_customer(account_number="SC-A", credit_limit_cents=100000)
        customer_b = create_customer(account_number="SC-B", credit_limit_cents=100000)
        item = create_item(sku="SC-1", list_price_cents=100)
        cart = create_cart(customer_a["id"], [{"item_id": item["id"], "qty": 1}])

        res = api.get_cart(cart["id"], make_buyer_headers(customer_b["id"]))
        validate_error(res, ApiErrorId.ERR_CUSTOMER_SCOPE_MISMATCH,
                       expected_status=403)

        fetched = validate_success(api.get_cart(cart["id"], admin_headers), 200)
        assert fetched["id"] == cart["id"]


class TestOptimisticConcurrency:
    def test_occ_customer_stale_version_returns_412(self, api, admin_headers):
        """PRD §2.7: "If the supplied value does not match the account's current
        `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
        Every successful update advances the account's `version` by one, so a
        client holding a previously observed version is writing from a stale view
        even when a sequential update would otherwise be legitimate."

        Design: Corner/cross_cutting_layers/occ_customer_stale_version_returns_412
        """
        customer = create_customer(account_number="OCC-1", credit_limit_cents=100000)
        v1 = customer["version"]
        updated = validate_success(
            api.update_customer(
                customer["id"],
                {"price_tier": "GOLD", "expected_customer_version": v1},
                admin_headers,
            ),
            200,
        )
        assert updated["version"] == 2

        stale = api.update_customer(
            customer["id"],
            {"price_tier": "PLATINUM", "expected_customer_version": v1},
            admin_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        current = validate_success(
            api.update_customer(
                customer["id"],
                {"price_tier": "PLATINUM", "expected_customer_version": 2},
                admin_headers,
            ),
            200,
        )
        assert current["price_tier"] == "PLATINUM"
        assert current["version"] == 3
