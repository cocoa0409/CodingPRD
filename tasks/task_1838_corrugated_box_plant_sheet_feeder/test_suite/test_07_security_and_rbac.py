"""Authentication, role authorization, and customer ownership enforcement."""
import pytest

from test_helpers import (
    ANONYMOUS_HEADERS,
    UNKNOWN_UUID,
    ApiErrorId,
    create_box_order_payload,
    create_customer,
    create_grade,
    create_release,
    create_stocked_program,
    make_customer_headers,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

SALES = TEST_USERS["sales_rep_headers"]
ADMIN = TEST_USERS["plant_admin_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
ADJUDICATOR = TEST_USERS["claims_adjuster_headers"]


def test_missing_auth_headers_unauthenticated(api):
    """PRD 2.1: "Every request to the API must carry two headers: `X-User-ID`,
    identifying the acting operator, and `X-User-Role`, naming one of the six
    declared roles. A request missing either header, or carrying a role string
    that is not one of the declared roles, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    res = api.create_customer_account(
        {
            "account_name": "Acme Foods",
            "ship_to_city": "Fresno",
            "distance_miles_from_plant": 120.0,
            "credit_limit_dollars": 50000.00,
        },
        ANONYMOUS_HEADERS,
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_production_planner_cannot_create_box_order(api, production_planner_headers):
    """PRD 2.1: "A request whose role is authenticated but not listed among the
    roles authorized for that endpoint is rejected with `ERR_FORBIDDEN` (HTTP
    403)."
    PRD 2.1: "`SalesRep` owns the commercial pipeline: customer accounts, box
    orders, quotes, quote acceptance, invoicing, and inventory-program
    creation."

    Design: Corner/rbac/planner_cannot_create_box_order_forbidden
    """
    res = api.create_box_order(
        create_box_order_payload(UNKNOWN_UUID, UNKNOWN_UUID, quantity=100),
        production_planner_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_sales_rep_cannot_approve_release(api, sales_rep_headers):
    """PRD 2.1: "A request whose role is authenticated but not listed among the
    roles authorized for that endpoint is rejected with `ERR_FORBIDDEN` (HTTP
    403)."
    PRD 2.1: "`PlantAdmin` governs master data and program governance:
    board-grade registration and discontinuation, inventory-program suspension
    and reactivation, release-order approval, and the logical clock."

    Design: Corner/rbac/salesrep_cannot_approve_release_forbidden
    """
    customer = create_customer()
    grade = create_grade()
    program = create_stocked_program(
        customer["id"], grade["id"], 100, reorder_point=10, replenishment_qty=500
    )
    release = create_release(program["id"], 10, customer["id"])

    res = api.approve_release_order(release["id"], sales_rep_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    releases, _ = validate_paginated(
        api.list_release_orders(program["id"], PLANNER)
    )
    assert releases[0]["status"] == "PENDING"


def test_claims_adjuster_cannot_file_claim(api, claims_adjuster_headers):
    """PRD 2.1: "A request whose role is authenticated but not listed among the
    roles authorized for that endpoint is rejected with `ERR_FORBIDDEN` (HTTP
    403)."
    PRD 2.1: "`CustomerService` files quality claims. `ClaimsAdjuster` reviews
    and resolves those claims."

    Design: Corner/rbac/adjuster_cannot_file_claim_forbidden
    """
    res = api.create_quality_claim(
        {
            "box_order_id": UNKNOWN_UUID,
            "claim_type": "TRANSIT_DAMAGE",
            "defective_qty_claimed": 10,
        },
        claims_adjuster_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_customer_cannot_release_foreign_program(api):
    """PRD 2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of
    the acting `CustomerAccount`. Ownership checks on any resource that
    references a `CustomerAccount` — the customer-facing writes on inventory
    programs and release orders — compare the resource's `customer_id` (reached
    through the parent program when necessary) to `X-User-ID`, and a mismatch
    is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."
    PRD 3.7: "A `Customer` creates a release order against its own program —
    the ownership check of §2.1 applies, and a customer acting on another's
    program is rejected with `ERR_OWNERSHIP_MISMATCH`."

    Design: Corner/rbac/customer_cannot_release_other_customers_program
    """
    customer_a = create_customer(name="Acme Foods", city="Fresno", miles=120.0)
    customer_b = create_customer(
        name="Beacon Retail", city="Reno", miles=500.0, credit_limit=100000.00
    )
    grade = create_grade()
    program = create_stocked_program(
        customer_a["id"], grade["id"], 100, reorder_point=10, replenishment_qty=500
    )

    foreign = api.create_release_order(
        program["id"],
        {"qty": 10, "requested_ship_date": "2026-08-12"},
        make_customer_headers(customer_b["id"]),
    )
    validate_error(foreign, ApiErrorId.ERR_OWNERSHIP_MISMATCH, expected_status=403)

    own = api.create_release_order(
        program["id"],
        {"qty": 10, "requested_ship_date": "2026-08-12"},
        make_customer_headers(customer_a["id"]),
    )
    release = validate_success(own, 201)
    assert release["status"] == "PENDING"
