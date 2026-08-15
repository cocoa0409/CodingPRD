"""Catalog: brands, territory exclusivity windows, product lifecycle, and the
liquidation pricing ladder."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_salon,
    create_product_payload,
    create_territory_exclusive_payload,
    list_order_line_items,
    make_brand,
    make_product,
    make_salon_buyer_headers,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestProductCreation:
    def test_product_create_invalid_hazmat_enum_rejected(self, api):
        """PRD §2.9: "Products have a `lifecycle_status` of `ACTIVE`,
        `DISCONTINUED`, `LIQUIDATION`, or `ARCHIVED`; a `variant_type` of
        `BACKBAR` (professional use, not for resale) or `RETAIL` (for resale
        to consumers); and a `hazmat_class` of `NONE`, `AEROSOL`, or
        `FLAMMABLE_LIQUID`."
        PRD §2.8: "Schema failures yield `ERR_INVALID_REQUEST`;
        window-ordering failures yield `ERR_INVALID_TIME_WINDOW`."

        Design: Corner/entities/product_create_invalid_hazmat_enum_rejected
        """
        brand = make_brand()
        resp = api.create_product(
            create_product_payload(
                brand_id=brand["id"], hazmat_class="EXPLOSIVE",
                base_price_cents=1000),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestTerritoryExclusiveWindows:
    def test_exclusive_window_inverted_returns_400(self, api):
        """PRD §3.2: "Granting exclusivity on a brand creates a window with a
        `territory_code`, an inclusive `effective_from`, and an exclusive
        `effective_to` — a half-open window in which `effective_to` must be
        strictly after `effective_from` (`ERR_INVALID_TIME_WINDOW`
        otherwise)."

        Design: Corner/entities/exclusive_window_inverted_returns_400
        """
        brand = make_brand()
        resp = api.create_territory_exclusive(
            brand["id"],
            create_territory_exclusive_payload(
                territory_code="OR",
                effective_from="2026-06-01T00:00:00Z",
                effective_to="2026-06-01T00:00:00Z"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW)

    def test_overlapping_territory_window_rejected(self, api):
        """PRD §3.2: "Two windows for the same brand and territory pair must
        not overlap: overlap exists precisely when the new window's
        `effective_from` falls before the existing window's `effective_to` and
        the existing window's `effective_from` falls before the new window's
        `effective_to`; mere adjacency — the new window starting exactly where
        the old one ends — is allowed. An overlapping grant is rejected with
        `ERR_TERRITORY_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/territory_exclusive_half_open_overlap
        """
        brand = make_brand()
        validate_success(api.create_territory_exclusive(
            brand["id"],
            create_territory_exclusive_payload(
                territory_code="CA",
                effective_from="2026-01-01T00:00:00Z",
                effective_to="2026-06-01T00:00:00Z"),
            ADMIN), 201)

        resp = api.create_territory_exclusive(
            brand["id"],
            create_territory_exclusive_payload(
                territory_code="CA",
                effective_from="2026-03-01T00:00:00Z",
                effective_to="2026-09-01T00:00:00Z"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_TERRITORY_WINDOW_OVERLAP)

    def test_adjacent_territory_window_allowed(self, api):
        """PRD §3.2: "Two windows for the same brand and territory pair must
        not overlap: overlap exists precisely when the new window's
        `effective_from` falls before the existing window's `effective_to` and
        the existing window's `effective_from` falls before the new window's
        `effective_to`; mere adjacency — the new window starting exactly where
        the old one ends — is allowed. An overlapping grant is rejected with
        `ERR_TERRITORY_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/territory_exclusive_half_open_overlap
        """
        brand = make_brand()
        validate_success(api.create_territory_exclusive(
            brand["id"],
            create_territory_exclusive_payload(
                territory_code="CA",
                effective_from="2026-01-01T00:00:00Z",
                effective_to="2026-06-01T00:00:00Z"),
            ADMIN), 201)

        adjacent = validate_success(api.create_territory_exclusive(
            brand["id"],
            create_territory_exclusive_payload(
                territory_code="CA",
                effective_from="2026-06-01T00:00:00Z",
                effective_to="2027-01-01T00:00:00Z"),
            ADMIN), 201)
        assert adjacent["territory_code"] == "CA"

        windows = validate_success(
            api.list_territory_exclusives(brand["id"], ADMIN), 200)
        ca_windows = [w for w in windows if w["territory_code"] == "CA"]
        assert len(ca_windows) == 2, (
            f"expected exactly 2 CA windows after adjacency, got {len(ca_windows)}")


class TestTerritoryRestrictionAndLifecycleOrdering:
    def test_brand_territory_restricted_at_order_create(self, api):
        """PRD §3.5: "Order creation requires the salon to be `ACTIVE` —
        otherwise `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 409) — and the
        territory-exclusivity rule is evaluated per initial line: for each
        line's brand, if any exclusivity window exists for that brand, the
        salon's `territory_code` must be covered by a window containing the
        logical clock under half-open semantics; failure is
        `ERR_BRAND_TERRITORY_RESTRICTED` (HTTP 422)."

        Design: Corner/validations/brand_territory_restricted_at_order_create
        """
        salon, _ = create_active_salon(territory_code="TX", legal_name="Salon 27")
        brand = make_brand()
        validate_success(api.create_territory_exclusive(
            brand["id"],
            create_territory_exclusive_payload(
                territory_code="CA",
                effective_from="2026-01-01T00:00:00Z",
                effective_to="2027-01-01T00:00:00Z"),
            ADMIN), 201)
        product = make_product(brand["id"], base_price_cents=9000)

        resp = api.create_order(
            {"salon_account_id": salon["id"],
             "items": [{"product_id": product["id"], "quantity": 1}]},
            make_salon_buyer_headers(salon["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BRAND_TERRITORY_RESTRICTED)

    def test_discontinued_product_not_orderable(self, api):
        """PRD §3.4: "Only `ACTIVE` and `LIQUIDATION` products may be added to
        orders; a line referencing a product in any other lifecycle state is
        rejected with `ERR_INVALID_PRODUCT_STATE`."

        Design: Corner/validations/discontinued_product_not_orderable
        """
        salon, _ = create_active_salon(legal_name="Salon 28")
        brand = make_brand()
        product = make_product(brand["id"], base_price_cents=3000)
        validate_success(api.transition_product_lifecycle(
            product["id"], {"target_status": "DISCONTINUED"}, ADMIN), 200)

        resp = api.create_order(
            {"salon_account_id": salon["id"],
             "items": [{"product_id": product["id"], "quantity": 1}]},
            make_salon_buyer_headers(salon["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PRODUCT_STATE)


class TestProductLifecycle:
    def test_product_discontinue_reinstate_cycle(self, api):
        """PRD §3.2: "From `ACTIVE`, a product may move to `DISCONTINUED`,
        stamping `discontinued_at` with the logical clock and pausing every
        `ACTIVE` promotion that references the product as its required, free,
        or sample product. From `DISCONTINUED`, a product may return to
        `ACTIVE` only while its owning brand is still `ACTIVE` —
        `discontinued_at` clears to null — or move to `LIQUIDATION`, which
        stamps `liquidation_started_at` with the logical clock exactly once:
        leaving and re-entering `LIQUIDATION` later does not reset that
        timestamp."

        Design: Corner/state_machines/product_discontinue_reinstate_cycle
        """
        brand = make_brand()
        product = make_product(brand["id"], base_price_cents=7000)

        discontinued = validate_success(api.transition_product_lifecycle(
            product["id"], {"target_status": "DISCONTINUED"}, ADMIN), 200)
        assert discontinued["lifecycle_status"] == "DISCONTINUED"
        assert discontinued["discontinued_at"] is not None

        reinstated = validate_success(api.transition_product_lifecycle(
            product["id"], {"target_status": "ACTIVE"}, ADMIN), 200)
        assert reinstated["lifecycle_status"] == "ACTIVE"
        assert reinstated["discontinued_at"] is None
        assert reinstated["liquidation_started_at"] is None

    def test_liquidation_ladder_week2_boundary(self, api):
        """PRD §3.4: "At least 14 but fewer than 28 days elapsed: 40 percent
        off."
        PRD §3.4: "The steps are left-closed: at exactly 14 days elapsed the
        40 percent step applies."

        Design: Corner/calculations/liquidation_ladder_week2_boundary
        """
        salon, _ = create_active_salon(legal_name="Salon 18")
        brand = make_brand()
        product = make_product(brand["id"], base_price_cents=20000,
                               weight_grams=100)
        # Enter LIQUIDATION at the default logical clock 2026-08-01T00:00:00Z.
        validate_success(api.transition_product_lifecycle(
            product["id"], {"target_status": "DISCONTINUED"}, ADMIN), 200)
        validate_success(api.transition_product_lifecycle(
            product["id"], {"target_status": "LIQUIDATION"}, ADMIN), 200)
        # Advance to exactly liquidation_started_at + 14 days.
        set_clock("2026-08-15T00:00:00Z")

        order = validate_success(api.create_order(
            {"salon_account_id": salon["id"],
             "items": [{"product_id": product["id"], "quantity": 2}]},
            make_salon_buyer_headers(salon["id"])), 201)
        items = list_order_line_items(order["id"])
        assert len(items) == 1
        assert items[0]["unit_price_cents"] == 12000, (
            "round_half_up(20000 * (1 - 0.40)) at the left-closed day-14 step")
        assert items[0]["line_total_cents"] == 24000
