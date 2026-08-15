"""Authentication, role authorization, and Customer ownership (PRD §2.1, §3.6,
§4)."""
from test_helpers import (
    TEST_USERS,
    accept_quote,
    create_config,
    create_customer,
    create_quote,
    create_variety,
    factories,
    get_order,
    make_customer_headers,
    mini_chain,
    validate_error,
)
from test_helpers.api_errors import ApiErrorId

FARM = TEST_USERS["farm_manager_headers"]
SALES = TEST_USERS["sales_rep_headers"]
HARVEST = TEST_USERS["harvest_supervisor_headers"]
FLEET = TEST_USERS["fleet_manager_headers"]


# ---------------------------------------------------------------------------
# Corner: errors / missing_auth_headers_returns_unauthenticated
# ---------------------------------------------------------------------------

def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, naming their operational capacity. The declared roles are `FarmManager`, `SalesRep`, `HarvestSupervisor`, `FleetManager`, and `Customer`. A request missing either header, or presenting a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/errors/missing_auth_headers_returns_unauthenticated
    """
    resp = api.list_fields(headers=None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


# ---------------------------------------------------------------------------
# Corner: rbac / customer_cannot_create_quotes
# ---------------------------------------------------------------------------

def test_customer_cannot_create_quotes(api):
    """PRD §2.1: "A request whose role is not authorized for the targeted operation is rejected with `ERR_UNAUTHORIZED_ROLE` (403)."
    PRD §2.1: "A `SalesRep` owns the order book: customer registration, quotes and their acceptance, order confirmation, cancellation, and closure, delivery checks, payments, and crew referral and scheduling."

    Design: Corner/rbac/customer_cannot_create_quotes
    """
    create_config(api)
    v = create_variety(api)
    c = create_customer(api)
    payload = factories.create_quote_payload(
        c["id"], [factories.quote_line(v["id"], "PREMIUM", 2)], 1, 1, 0
    )
    resp = api.create_quote(payload, make_customer_headers(c["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)


# ---------------------------------------------------------------------------
# Corner: rbac / harvest_supervisor_cannot_confirm_order
# ---------------------------------------------------------------------------

def test_harvest_supervisor_cannot_confirm_order(api):
    """PRD §2.1: "A request whose role is not authorized for the targeted operation is rejected with `ERR_UNAUTHORIZED_ROLE` (403)."
    PRD §2.1: "A `HarvestSupervisor` schedules, completes, and cancels harvest batches."

    Design: Corner/rbac/harvest_supervisor_cannot_confirm_order
    """
    create_config(api)
    v = create_variety(api)
    c = create_customer(api)
    q = create_quote(api, c["id"],
                     [factories.quote_line(v["id"], "PREMIUM", 2)], 1, 1, 0)
    o = accept_quote(api, q["id"])
    resp = api.confirm_order(o["id"], factories.confirm_order_payload(), HARVEST)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)


# ---------------------------------------------------------------------------
# Corner: rbac / fleet_manager_cannot_evaluate_warranty_claim
# ---------------------------------------------------------------------------

def test_fleet_manager_cannot_evaluate_warranty_claim(api):
    """PRD §2.1: "A request whose role is not authorized for the targeted operation is rejected with `ERR_UNAUTHORIZED_ROLE` (403)."
    PRD §2.1: "A `FarmManager` owns rate cards, variety definitions, fields and their quality data, maturity scans, archiving, re-seeding plans, crew registration and deactivation, warranty evaluation, and the logical clock."

    Design: Corner/rbac/fleet_manager_cannot_evaluate_warranty_claim
    """
    bundle = mini_chain(api, stage="claim")
    resp = api.evaluate_warranty_claim(bundle["w"]["id"], FLEET)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)


# ---------------------------------------------------------------------------
# Corner: rbac / sales_rep_cannot_create_fields
# ---------------------------------------------------------------------------

def test_sales_rep_cannot_create_fields(api):
    """PRD §2.1: "A request whose role is not authorized for the targeted operation is rejected with `ERR_UNAUTHORIZED_ROLE` (403)."
    PRD §2.1: "A `FarmManager` owns rate cards, variety definitions, fields and their quality data, maturity scans, archiving, re-seeding plans, crew registration and deactivation, warranty evaluation, and the logical clock."

    Design: Corner/rbac/sales_rep_cannot_create_fields
    """
    v = create_variety(api)
    payload = factories.create_field_payload(name="North 40")
    payload["variety_id"] = v["id"]
    resp = api.create_field(payload, SALES)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)


# ---------------------------------------------------------------------------
# Corner: rbac / customer_cannot_install_other_customers_order
# ---------------------------------------------------------------------------

def test_customer_cannot_install_other_customers_order(api):
    """PRD §3.6: "On the installation path, the owning `Customer` — and only that customer, with `X-User-ID` equal to the order's `customer_id`, otherwise `ERR_UNAUTHORIZED_ROLE` — marks installation started, moving `DELIVERED` to `INSTALLING` and stamping `install_started_at`, then marks installation complete, moving `INSTALLING` to `INSTALLED` and stamping `installed_at`."
    PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a customer compare the resource's `customer_id` field to `X-User-ID`."

    Design: Corner/rbac/customer_cannot_install_other_customers_order
    """
    bundle = mini_chain(api, stage="delivered")
    bo = create_customer(api, full_name="Bo Lin", email="bo@example.com",
                         phone="555-0102", freight_zone=2, address="4 Pine Ave")

    resp = api.install_start(
        bundle["o"]["id"], make_customer_headers(bo["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)
    assert get_order(api, bundle["o"]["id"])["status"] == "DELIVERED", (
        "a rejected ownership check changes nothing"
    )
