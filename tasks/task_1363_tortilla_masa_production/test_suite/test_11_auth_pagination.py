"""Cross-cutting: authentication, role exclusivity, and list pagination."""
from test_helpers import (
    ApiErrorId,
    create_batch,
    create_conditioned_lot,
    create_customer,
    create_pack_order,
    pack_order_pass_weight_check,
    set_clock,
    setup_in_progress_run,
    start_cook,
    start_steep,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
MILLER = TEST_USERS["miller_operator_headers"]
QI = TEST_USERS["quality_inspector_headers"]
PACK = TEST_USERS["packaging_lead_headers"]
DISP = TEST_USERS["route_dispatcher_headers"]


class TestAuthentication:
    def test_missing_auth_headers_rejected_401(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside the seven declared below, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."
        A list call with no authentication headers fails before any role check.

        Design: Corner/validations/val_products_list_missing_auth_headers
        """
        validate_error(api.list_products(headers={}), ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleExclusivity:
    def test_miller_cannot_create_product(self, api):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized
        list is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4 assigns
        "POST | /plant/products | Create a SKU configuration | PlantManager".

        Design: Corner/rbac/rbac_miller_cannot_create_product
        """
        validate_error(
            api.create_product(
                {
                    "sku_code": "RBAC-1", "diameter_in": "D6", "count_per_pack": 12,
                    "packs_per_case": 10, "unit_weight_g": 30, "channel": "RETAIL",
                    "preservative_system": "PROPIONATE", "allergen_class": "CORN_ONLY",
                },
                MILLER,
            ),
            ApiErrorId.ERR_FORBIDDEN,
        )
        _, meta = validate_paginated(api.list_products(PM))
        assert meta["total_count"] == 0, "no product persisted by the forbidden call"

    def test_packaging_lead_cannot_evaluate_batch(self, api):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized
        list is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4 assigns
        "POST | /plant/nixtamal-batches/{id}/evaluate | ... | QualityInspector".
        A PackagingLead is rejected even with a valid decision payload, and the
        batch stays STEEPING.

        Design: Corner/rbac/rbac_packaging_lead_cannot_evaluate_batch
        """
        lot = create_conditioned_lot(lot_code="LOT-RB2")
        batch = create_batch(lot["id"], corn_kg=500)
        start_cook(batch["id"])
        set_clock("2026-08-01T02:00:00Z")
        start_steep(batch["id"])
        set_clock("2026-08-01T12:00:00Z")
        validate_error(
            api.evaluate_batch(batch["id"], "PASS", PACK), ApiErrorId.ERR_FORBIDDEN
        )
        after = validate_success(api.get_nixtamal_batch(batch["id"], QI))
        assert after["batch_status"] == "STEEPING"

    def test_dispatcher_cannot_seal_pack_order(self, api):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized
        list is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4 assigns
        "POST | /plant/pack-orders/{id}/seal | Seal passed cases (blocked while
        run QC is `ON_HOLD`) | PackagingLead".
        A RouteDispatcher is rejected; the pack order stays PASSED.

        Design: Corner/rbac/rbac_dispatcher_cannot_seal_pack_order
        """
        ctx = setup_in_progress_run(
            planned_cases=50, allocated_kg=194.4,
            product_overrides={"sku_code": "C-RB3"},
            line_overrides={"line_code": "L-RB3"},
        )
        pack_order = create_pack_order(ctx["run"]["id"], cases_planned=10)
        pack_order_pass_weight_check(pack_order["id"], 10)
        validate_error(
            api.seal_pack_order(pack_order["id"], DISP), ApiErrorId.ERR_FORBIDDEN
        )
        after = validate_success(api.get_pack_order(pack_order["id"], PACK))
        assert after["pack_status"] == "PASSED"


class TestPagination:
    def test_defaults_and_windowing(self, api):
        """PRD §2.3: "List endpoints accept `limit` and `offset` query parameters.
        `limit` defaults to 10, has a minimum of 1, and a maximum of 100. `offset`
        defaults to 0. List responses sort by `created_at` ascending. The `meta`
        block of a list response includes the four pagination fields `limit`,
        `offset`, `total_count`, and `has_more`."
        With 12 customers: the default page returns 10 with has_more true;
        limit=2&offset=10 returns the last 2 with has_more false.

        Design: Corner/entities/entities_pagination_defaults_and_windowing
        """
        for i in range(12):
            create_customer(
                account_name=f"C{i + 1:02d}", region="R1", base_weekly_cases=1,
                min_shelf_life_pct=10,
            )
        page1, meta1 = validate_paginated(api.list_customers(PM))
        assert len(page1) == 10
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_customers(PM, params={"limit": 2, "offset": 10})
        )
        assert len(page2) == 2
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False
