"""Entity-creation and entity-shape corner tests."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_category_payload,
    create_planogram_payload,
    create_product_payload,
    create_retailer_payload,
    create_supplier_payload,
    setup_category_with_listed_product,
    setup_retailer_category_supplier,
    validate_error,
    validate_success,
)


class TestRetailerLifecycle:
    def test_create_retailer_with_defaults(self, api, platform_admin_headers):
        """PRD §3.1: "A new retailer's `status` begins at `ACTIVE`; the field is
        enumerated as `ACTIVE` or `SUSPENDED`."
        PRD §3.1: "optionally, a `compliance_threshold_pct` — the minimum audit
        compliance score the retailer considers acceptable, which defaults to
        85 when omitted."

        Design: Corner/entities/create_retailer_with_defaults
        """
        resp = api.create_retailer(create_retailer_payload(name="R"), platform_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE"
        assert data["compliance_threshold_pct"] == 85
        assert data["version"] == 1

    def test_get_retailer_returns_stored(self, api, platform_admin_headers):
        """PRD §2.5: "every resource type can be fetched by its bare `id` through
        a top-level single-resource path."

        Design: Corner/entities/get_retailer_returns_stored
        """
        created = validate_success(
            api.create_retailer(create_retailer_payload(name="Acme"), platform_admin_headers),
            expected_status=201,
        )
        rid = created["id"]
        got = validate_success(api.get_retailer(rid, platform_admin_headers), expected_status=200)
        assert got["id"] == rid
        assert got["name"] == "Acme"

    def test_get_nonexistent_retailer_returns_404(self, api, platform_admin_headers):
        """PRD §2.5: "The first identifier that does not resolve to an existing
        resource inside its parent's scope terminates the request with
        `ERR_NOT_FOUND`."

        Design: Corner/entities/get_nonexistent_retailer_returns_404
        """
        resp = api.get_retailer(NON_EXISTENT_UUID, platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestCategoryPayloadValidation:
    def test_category_missing_required_field_returns_400(self, api, platform_admin_headers, category_manager_headers):
        """PRD §2.8: "A malformed payload — wrong field types, or a required
        field absent — is rejected with `ERR_INVALID_REQUEST` before any
        business evaluation begins."

        Design: Corner/entities/category_missing_required_field_returns_400
        """
        retailer = validate_success(
            api.create_retailer(create_retailer_payload(name="R"), platform_admin_headers),
            expected_status=201,
        )
        rid = retailer["id"]
        bad_payload = {"role": "ROUTINE", "annual_sales_cents": 100, "total_linear_feet": 5}
        resp = api.create_category(rid, bad_payload, category_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_category_invalid_role_enum_returns_400(self, api, platform_admin_headers, category_manager_headers):
        """PRD §2.8: "A malformed payload — wrong field types, or a required
        field absent — is rejected with `ERR_INVALID_REQUEST` before any
        business evaluation begins."

        Design: Corner/entities/product_invalid_role_enum_returns_400
        """
        retailer = validate_success(
            api.create_retailer(create_retailer_payload(name="R"), platform_admin_headers),
            expected_status=201,
        )
        rid = retailer["id"]
        bad_payload = {
            "code": "X",
            "role": "NOT_A_ROLE",
            "annual_sales_cents": 100,
            "total_linear_feet": 5,
        }
        resp = api.create_category(rid, bad_payload, category_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestSupplierDefaults:
    def test_supplier_default_is_captain_false(self, api, platform_admin_headers, retailer_admin_headers):
        """PRD §3.2: "Creating a supplier takes only a `name`; the record starts
        with `is_captain` set to false and `captain_category_id` empty."

        Design: Corner/entities/supplier_default_is_captain_false
        """
        retailer = validate_success(
            api.create_retailer(create_retailer_payload(name="R"), platform_admin_headers),
            expected_status=201,
        )
        rid = retailer["id"]
        resp = api.create_supplier(rid, create_supplier_payload(name="S"), retailer_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert data["is_captain"] is False


class TestPlanogramSystemFields:
    def test_planogram_id_system_generated_input_ignored(self, api, platform_admin_headers, category_manager_headers):
        """PRD §2.4: "`id` — a server-minted UUID string, with no type prefix
        of any kind."

        Design: Corner/entities/planogram_id_system_generated_input_ignored
        """
        retailer = validate_success(
            api.create_retailer(create_retailer_payload(name="R"), platform_admin_headers),
            expected_status=201,
        )
        rid = retailer["id"]
        cat = validate_success(
            api.create_category(rid, create_category_payload(code="C"), category_manager_headers),
            expected_status=201,
        )
        cid = cat["id"]
        payload = create_planogram_payload(name="PG", variant="BASE")
        payload["id"] = "client-supplied-fake-id"
        resp = api.create_planogram(rid, cid, payload, category_manager_headers)
        data = validate_success(resp, expected_status=201)
        assert data["id"] != "client-supplied-fake-id"


class TestPlanogramLineComputedFields:
    def test_planogram_line_computed_fields_input_ignored(
        self, api, platform_admin_headers, category_manager_headers
    ):
        """PRD §3.4: "Each line's `days_of_supply` answers \"how long does the
        allocated shelf last at current demand?\": the line's `capacity_units`
        is divided by the product's average daily demand, where average daily
        demand is the product's `weekly_demand_units` divided by seven, and
        the quotient is rounded half-up to two decimal places."
        PRD §3.4: "A line lasting strictly less than 3.0 days is flagged
        `UNDERSTOCK`; one lasting strictly more than 21.0 days is flagged
        `OVERSTOCK`; everything between those poles is `OK`."

        Design: Corner/entities/planogram_line_computed_fields_input_ignored
        """
        retailer, category, supplier, product = setup_category_with_listed_product(
            product_overrides={"sku": "P", "width_in": 6, "weekly_demand_units": 70},
            category_overrides={"code": "C", "total_linear_feet": 10},
        )
        rid, cid = retailer["id"], category["id"]
        pg = validate_success(
            api.create_planogram(rid, cid, create_planogram_payload(), category_manager_headers),
            expected_status=201,
        )
        # Client attempts to inject sentinel values; server must ignore them.
        payload = {
            "product_id": product["id"],
            "position_index": 1,
            "facings": 3,
            "capacity_units": 30,
            "days_of_supply": 9999.0,
            "dos_flag": "OVERSTOCK",
        }
        resp = api.create_planogram_line(rid, cid, pg["id"], payload, category_manager_headers)
        data = validate_success(resp, expected_status=201)
        # Server-computed: 30 / (70/7) = 30/10 = 3.0 → OK (boundary is inclusive).
        assert data["days_of_supply"] == 3.0
        assert data["dos_flag"] == "OK"
