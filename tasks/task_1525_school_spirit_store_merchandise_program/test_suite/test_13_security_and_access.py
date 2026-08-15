"""Auth context, role enforcement, existence checks, and the program gate."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_active_program,
    create_design_payload,
    create_program,
    NON_EXISTENT_UUID,
    TEST_USERS,
    validate_error,
    validate_success,
)

DIRECTOR = TEST_USERS["director_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
TREASURER = TEST_USERS["treasurer_headers"]
CASHIER = TEST_USERS["cashier_headers"]


class TestAuthContext:
    def test_missing_auth_header_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        value the system does not recognize, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_rejected
        """
        program = create_program()
        res = api.get_program(program["id"], {})
        validate_error(
            res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400
        )


class TestRoleEnforcement:
    def test_student_cashier_cannot_create_vendor(self, api):
        """PRD §2.1: "A `StoreManager` runs the catalog — vendors, designs as
        their creator, variants, drops, purchase orders, campaigns, event
        scheduling, and fulfillment"
        PRD §2.1: "When the role is recognized but not permitted for the
        requested endpoint, the request is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/student_cashier_cannot_create_vendor
        """
        program = create_program()
        res = api.create_vendor(
            {
                "program_id": program["id"],
                "name": "PrintCo",
                "contact_email": "p@co.com",
            },
            CASHIER,
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)


class TestExistenceChecks:
    def test_variant_create_with_unknown_design_returns_not_found(self, api):
        """PRD §2.8: "Foreign keys carried in the request body — `design_id`,
        `variant_id`, `vendor_id`, `campaign_id`, `event_id`, `order_id`,
        `original_variant_id`, `new_variant_id` — must exist and must belong
        to the same program as the request's scope; failures draw from the
        same not-found family as step 3."

        Design: Corner/validations/variant_create_with_unknown_design_returns_not_found
        """
        program = create_active_program()
        res = api.create_product_variant(
            {
                "program_id": program["id"],
                "design_id": NON_EXISTENT_UUID,
                "size": "M",
                "unit_price_cents": 2500,
            },
            MANAGER,
        )
        validate_error(res, ApiErrorId.ERR_DESIGN_NOT_FOUND, 404)

    def test_not_found_sweep_all_resources(self, api):
        """PRD §2.8: "Path identifiers are validated left to right — the
        program first, then the resource within it — and the first missing
        identifier yields its own 404: `ERR_PROGRAM_NOT_FOUND`,
        `ERR_VENDOR_NOT_FOUND`, `ERR_DESIGN_NOT_FOUND`, `ERR_VARIANT_NOT_FOUND`,
        `ERR_DROP_NOT_FOUND`, `ERR_PO_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`,
        `ERR_PREORDER_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
        `ERR_EXCHANGE_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, or
        `ERR_ALLOCATION_RUN_NOT_FOUND`."

        Design: Corner/errors/not_found_sweep_all_resources
        """
        create_program()
        checks = [
            (api.get_vendor, ApiErrorId.ERR_VENDOR_NOT_FOUND),
            (api.get_product_variant, ApiErrorId.ERR_VARIANT_NOT_FOUND),
            (api.get_seasonal_drop, ApiErrorId.ERR_DROP_NOT_FOUND),
            (api.get_purchase_order, ApiErrorId.ERR_PO_NOT_FOUND),
            (api.get_preorder_campaign, ApiErrorId.ERR_CAMPAIGN_NOT_FOUND),
            (api.get_preorder, ApiErrorId.ERR_PREORDER_NOT_FOUND),
            (api.get_event_sale, ApiErrorId.ERR_EVENT_NOT_FOUND),
            (api.get_order, ApiErrorId.ERR_ORDER_NOT_FOUND),
            (api.get_exchange, ApiErrorId.ERR_EXCHANGE_NOT_FOUND),
            (api.get_activity_account, ApiErrorId.ERR_ACCOUNT_NOT_FOUND),
            (api.get_allocation_run, ApiErrorId.ERR_ALLOCATION_RUN_NOT_FOUND),
        ]
        for getter, error_id in checks:
            validate_error(getter(NON_EXISTENT_UUID, TREASURER), error_id, 404)


class TestProgramGate:
    def test_catalog_write_before_activation_rejected(self, api):
        """PRD §2.8: "Catalog, campaign, event, order, preorder, and exchange
        writes require the program's `status` to be `ACTIVE`, else
        `ERR_PROGRAM_NOT_ACTIVE`; posting an allocation run requires it to be
        `CLOSED`, else `ERR_PROGRAM_NOT_CLOSED`."

        Design: Corner/validations/catalog_write_before_activation_rejected
        """
        program = create_program()
        res = api.create_design(
            create_design_payload(program["id"]),
            MANAGER,
        )
        validate_error(res, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE, 409)
