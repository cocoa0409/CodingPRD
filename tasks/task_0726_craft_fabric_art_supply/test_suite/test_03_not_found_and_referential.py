"""Path-resource not-found and body foreign-key referential integrity."""
from test_helpers import (
    validate_error, ApiErrorId, NON_EXISTENT_UUID,
    create_customer, create_order,
    make_customer_headers, create_order_line_payload,
    TEST_USERS,
)


def test_get_missing_order_not_found(api):
    """PRD §2.7: "The parent resource is resolved first; if it does not exist, the
    corresponding not-found error is returned before any child identifier is
    examined. The not-found errors are role-specific to the resource:
    ERR_CUSTOMER_NOT_FOUND, ERR_PRODUCT_NOT_FOUND, ERR_ORDER_NOT_FOUND"

    Design: Corner/validations/get_missing_order_not_found
    """
    resp = api.get_order(NON_EXISTENT_UUID, TEST_USERS["store_manager_headers"])
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)


def test_add_line_unknown_product_referenced_not_found(api):
    """PRD §2.7: "When a request body carries a foreign-key reference (for example
    a product_id, session_id, or order_id on a create operation) that does not
    resolve to an existing record, the response is ERR_REFERENCED_ENTITY_NOT_FOUND
    (HTTP 404)."

    Design: Corner/validations/add_line_unknown_product_referenced_not_found
    """
    customer = create_customer()
    order = create_order(customer["id"])
    resp = api.add_order_line(
        order["id"],
        create_order_line_payload(NON_EXISTENT_UUID, requested_yards=1),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND)
