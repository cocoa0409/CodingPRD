"""Role-based access control and wholesale-client ownership scoping."""
from test_helpers import (
    validate_error, ApiErrorId, make_account, make_wholesale_client_headers, TEST_USERS,
)

CASHIER = TEST_USERS["cashier_headers"]


class TestRoleDenial:
    def test_cashier_cannot_create_product(self, api):
        """PRD 2.1: "When the headers are well-formed but the role is not permitted to
        perform the requested operation, the request is rejected with ERR_UNAUTHORIZED."
        (POST /products is authorized for Manager only.)

        Design: Corner/rbac/cashier_cannot_create_product_returns_unauthorized
        """
        validate_error(api.create_product({
            "sku": "C-18", "name": "P18", "category": "BREAD",
            "base_price_cents": 400, "shelf_life_hours": 12}, CASHIER),
            ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_wholesale_client_cannot_read_another_account(self, api):
        """PRD 2.1: "a WholesaleClient may read and act only on its own account, its own
        statement, its own standing orders, and its own delivery orders and payments — an
        attempt to touch another account's resources is rejected with ERR_UNAUTHORIZED."

        Design: Corner/rbac/wholesale_client_cannot_read_other_account
        """
        own = make_account(api, name="OwnA")
        other = make_account(api, name="OtherB")
        headers = make_wholesale_client_headers(own["id"])   # X-User-ID == own account id
        validate_error(api.get_wholesale_account(other["id"], headers),
                       ApiErrorId.ERR_UNAUTHORIZED.value)
