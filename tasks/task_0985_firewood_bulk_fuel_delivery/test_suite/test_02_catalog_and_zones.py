"""Product catalog rules and delivery-area restrictions (PRD §3.2, §2.8)."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    assert_product, create_product_payload, create_area_restriction_payload,
    set_clock, create_customer, create_product, create_route, create_order,
    order_line, create_order_payload, setup_catalog_with_route,
    TEST_USERS, make_customer_headers,
)

CS = TEST_USERS["customer_service_headers"]
OM = TEST_USERS["operations_manager_headers"]
RP = TEST_USERS["route_planner_headers"]


class TestProductCatalog:
    def test_pellet_product_must_use_blend_species(self, api):
        """PRD §3.2: "the two blend species are the only legal choices for
        `PELLET_TON` and `PELLET_BAG`; pairing a pellet kind with a solid-wood
        species, or naming a seasoned grade outside `GREEN`, `SEMI_SEASONED`,
        and `KILN_DRIED`, is rejected with `ERR_INVALID_PRODUCT_SPEC`."

        Design: Corner/entities/pellet_product_must_use_blend_species
        """
        set_clock()
        res = api.create_product(create_product_payload(
            sku="PBAD", product_kind="PELLET_TON", species="OAK",
            seasoned_grade="KILN_DRIED", base_price_cents=25000,
            moisture_ceiling_pct=10.0, available_qty=100), OM)
        validate_error(res, "ERR_INVALID_PRODUCT_SPEC", expected_status=422)

    def test_product_computed_reserved_qty_ignores_input(self, api):
        """PRD §3.2: "`reserved_qty` starts at 0 and tracks stock committed to
        non-terminal orders; `discontinued` defaults to false, and a
        discontinued product cannot be added to any new order or line, a
        rejection surfaced as `ERR_PRODUCT_DISCONTINUED`."

        Design: Corner/entities/product_computed_reserved_qty_ignores_input
        """
        set_clock()
        res = api.create_product(create_product_payload(
            sku="PC", product_kind="CORD", species="OAK",
            seasoned_grade="KILN_DRIED", base_price_cents=40000,
            moisture_ceiling_pct=20.0, available_qty=10), OM)
        product = validate_success(res, 201)
        assert_product(product)
        assert product["reserved_qty"] == 0

    def test_customer_cannot_create_product(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /api/v1/products — Authorized Role(s): OperationsManager.

        Design: Corner/rbac/customer_cannot_create_product
        """
        set_clock()
        customer = create_customer()
        res = api.create_product(create_product_payload(
            sku="PRB", product_kind="CORD", species="OAK",
            seasoned_grade="KILN_DRIED", base_price_cents=40000,
            moisture_ceiling_pct=20.0, available_qty=10),
            make_customer_headers(customer["id"]))
        validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)

    def test_product_discontinued_cannot_be_added(self, api):
        """PRD §3.2: "a discontinued product cannot be added to any new order
        or line, a rejection surfaced as `ERR_PRODUCT_DISCONTINUED`."

        Design: Corner/validations/product_discontinued_cannot_be_added
        """
        set_clock()
        customer, product, route = setup_catalog_with_route()
        get_success_data(api.update_product(product["id"], {"discontinued": True}, OM))
        res = api.create_order(create_order_payload(
            customer["id"], [order_line(product["id"], 1.0)]), CS)
        validate_error(res, "ERR_PRODUCT_DISCONTINUED", expected_status=422)


class TestAreaRestrictionYearWrap:
    """Area restriction with a year-wrapping enforcement window (PRD §3.2)."""

    def _setup_restriction(self, api):
        set_clock("2026-08-01T00:00:00Z")
        customer = create_customer(postal_code="55555")
        get_success_data(api.create_area_restriction(
            create_area_restriction_payload(
                name="WinterBan", postal_codes=["55555"],
                restricted_kinds=["CORD"], restricted_species=[],
                enforcement_window_start="11-01",
                enforcement_window_end="03-31"), OM))
        product = create_product(sku="P17", product_kind="CORD", species="OAK",
                                 seasoned_grade="KILN_DRIED", base_price_cents=40000,
                                 moisture_ceiling_pct=20.0, available_qty=10)
        create_route(prefixes=("5",))
        return customer, product

    def test_area_restriction_wraps_year_end_and_rejects_january(self, api):
        """PRD §3.2: "The window may wrap around the year end — a restriction
        running 11-01 through 03-31 is enforced through winter."
        PRD §3.2: "if any active restriction covers the order's
        `delivery_postal_code` and its enforcement window covers the order's
        `requested_delivery_date`, and it bans the line's kind or species, the
        operation fails with `ERR_AREA_RESTRICTED`."

        Design: Difficulty/resource_temporal_overlap/area_restriction_year_wrapping_enforcement_window
        """
        customer, product = self._setup_restriction(api)
        res = api.create_order(create_order_payload(
            customer["id"], [order_line(product["id"], 1.0)],
            delivery_street_address="17 Willow", delivery_postal_code="55555",
            requested_delivery_date="2027-01-15"), CS)
        validate_error(res, "ERR_AREA_RESTRICTED", expected_status=422)

    def test_area_restriction_wrapped_window_permits_june(self, api):
        """PRD §3.2: "The window may wrap around the year end — a restriction
        running 11-01 through 03-31 is enforced through winter."
        PRD §3.2: "if any active restriction covers the order's
        `delivery_postal_code` and its enforcement window covers the order's
        `requested_delivery_date`, and it bans the line's kind or species, the
        operation fails with `ERR_AREA_RESTRICTED`."
        June 15 falls outside the 11-01..03-31 wrapped window, so the order is
        accepted.

        Design: Difficulty/resource_temporal_overlap/area_restriction_year_wrapping_enforcement_window
        """
        customer, product = self._setup_restriction(api)
        res = api.create_order(create_order_payload(
            customer["id"], [order_line(product["id"], 1.0)],
            delivery_street_address="17 Willow", delivery_postal_code="55555",
            requested_delivery_date="2027-06-15"), CS)
        order = validate_success(res, 201)
        assert order["fulfillment_status"] == "DRAFT"
