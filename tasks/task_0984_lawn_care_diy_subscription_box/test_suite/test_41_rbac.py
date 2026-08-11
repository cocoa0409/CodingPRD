"""Role-based access control: exclusive operations reject other roles
(PRD 2.1, 2.8, 4)."""
import test_helpers as th

MISSING = "11111111-1111-1111-1111-111111111111"


def test_customer_cannot_post_lab_result(api):
    """PRD 2.1: "If the presented role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 2.8: "So a missing header surfaces before any role check, a role failure before ownership, ownership before existence, existence before state, state before the weather gate, the weather gate before temporal windows, temporal windows before constraint checks, and constraint checks before cross-entity referential checks."

    Design: Corner/rbac/customer_cannot_post_lab_result
    """
    # Lab results are Agronomist-exclusive; the role check precedes existence,
    # so a random id still surfaces ERR_FORBIDDEN_ROLE (not a 404).
    th.validate_error(
        api.post_lab_result(
            MISSING,
            th.lab_result_analyzed_payload(),
            th.make_customer_headers(MISSING),
        ),
        th.ApiErrorId.ERR_FORBIDDEN_ROLE,
    )


def test_agronomist_cannot_advance_fulfillment(api):
    """PRD 2.1: "If the presented role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 2.1: "**FulfillmentOps** — the warehouse operator who creates shipment boxes and advances them through fulfillment."

    Design: Corner/rbac/agronomist_cannot_advance_fulfillment
    """
    th.validate_error(
        api.advance_fulfillment(
            MISSING, {"to_status": "PICKING"},
            th.TEST_USERS["agronomist_headers"],
        ),
        th.ApiErrorId.ERR_FORBIDDEN_ROLE,
    )


def test_fulfillmentops_cannot_record_payment(api):
    """PRD 2.1: "If the presented role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 2.1: "**PlatformAdmin** — the operator with override power over the catalog, weather advisories, the logical clock, customer status, payment recording, referral revocation, and manual ledger adjustments."

    Design: Corner/rbac/fulfillmentops_cannot_record_payment
    """
    th.validate_error(
        api.record_payment(
            MISSING, {"outcome": "SUCCEEDED"},
            th.TEST_USERS["fulfillment_ops_headers"],
        ),
        th.ApiErrorId.ERR_FORBIDDEN_ROLE,
    )


def test_anonymous_cannot_read_customers(api):
    """PRD 2.1: "**Anonymous** — the unauthenticated caller, permitted only to register a new customer account."
    PRD 2.1: "If the presented role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/anonymous_cannot_read_customers
    """
    # Anonymous holds no read permission: role failure (403), not a 404.
    th.validate_error(
        api.get_customer(MISSING, th.TEST_USERS["anonymous_headers"]),
        th.ApiErrorId.ERR_FORBIDDEN_ROLE,
    )
