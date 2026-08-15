"""Catalog rules (bundles, sized products) and the online store lifecycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_online_order,
    cancel_online_order,
    create_active_tour,
    create_online_order_payload,
    create_product,
    create_product_payload,
    create_tour,
    fulfill_online_order,
    get_product,
    get_success_data,
    get_tour,
    patch_royalty_config,
    place_online_order,
    royalty_config_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

TM1 = TEST_USERS["tour_manager_headers"]


def test_bundle_with_sized_component_rejected(api):
    """PRD §3.1: "Every component must be a `REGULAR`, non-sized product
    belonging to the same tour as the bundle, and the list may not reference the
    bundle itself or another bundle — any violation is rejected with
    `ERR_BUNDLE_COMPONENT_INVALID`, and a component from another tour also
    offends the cross-tour coherence rule of §3.2."

    Design: Corner/validations/bundle_with_sized_component_rejected
    """
    tour = create_tour(name="VA8 Tour")
    hoodie = create_product(tour["id"], sku="VA8-HOODIE", name="Hoodie",
                            sized=True, base_price_cents=8000,
                            initial_stock_by_size={"M": 50})
    sticker = create_product(tour["id"], sku="VA8-STICKER", name="Sticker",
                             sized=False, base_price_cents=500,
                             initial_stock_by_size={"OS": 500})

    resp = api.create_product(
        create_product_payload(
            tour["id"], sku="VA8-BUNDLE", name="Bad Bundle",
            product_type="BUNDLE", sized=False, base_price_cents=9000,
            bundle_components=[
                {"component_product_id": hoodie["id"], "qty_per_bundle": 1},
                {"component_product_id": sticker["id"], "qty_per_bundle": 2},
            ]),
        TM1)
    validate_error(resp, ApiErrorId.ERR_BUNDLE_COMPONENT_INVALID)

    _rows, meta = validate_paginated(
        api.list_products(TM1, params={"tour_id": tour["id"]}))
    assert meta["total_count"] == 2, "no bundle row may be created"


def test_online_order_for_sized_product_requires_size(api):
    """PRD §3.7: "Placing an order takes the `tour_id` — the tour must be
    `ACTIVE`, otherwise `ERR_TOUR_NOT_ACTIVE` — a `product_id` that may be
    `REGULAR` or `BUNDLE`, a positive `quantity`, and a `size` that is required
    (one of S, M, L, XL) exactly when the product is sized and must be null for
    non-sized products and for bundles."
    PRD §2.7: "Request and configuration shape — `ERR_INVALID_SIZE_CURVE`,
    `ERR_INVALID_COMMISSION_CONFIG`, `ERR_BUNDLE_COMPONENT_INVALID` (all
    HTTP 400), `ERR_PRODUCT_NOT_SELLABLE_AT_SHOW` (HTTP 422), or the catch-all
    `ERR_VALIDATION` (HTTP 400) for missing required fields, wrong types,
    non-positive quantities or prices, invalid enum values, and malformed size
    maps."
    PRD §3.7: "The order's `unit_price_cents` is pinned from the product's
    `base_price_cents` at creation, `gross_cents` is `quantity` times that
    pinned price, and the order starts `PLACED`."

    Design: Corner/entities/online_order_for_sized_product_requires_size
    """
    tour = create_active_tour(name="CD6 Tour")
    product = create_product(tour["id"], sku="CD6-HOODIE", name="Hoodie",
                             sized=True, base_price_cents=8000,
                             initial_stock_by_size={"M": 50})

    resp = api.create_online_order(
        create_online_order_payload(tour["id"], product["id"], 1), TM1)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)

    order = validate_success(
        api.create_online_order(
            create_online_order_payload(tour["id"], product["id"], 1, size="M"),
            TM1),
        201)
    assert_online_order(order)
    assert order["status"] == "PLACED"
    assert order["size"] == "M"
    assert order["unit_price_cents"] == 8000, "unit price pinned from base price"
    assert order["gross_cents"] == 8000


def test_online_order_fulfill_after_cancel_rejected(api):
    """PRD §3.7: "Cancelling a `PLACED` order moves it to `CANCELLED` with no
    stock or royalty effects; both final fields simply stay null, and a cancel
    or fulfill against a non-`PLACED` order fails with `ERR_ORDER_NOT_PLACED`."

    Design: Corner/state_machines/online_order_fulfill_after_cancel_rejected
    """
    tour = create_active_tour(name="SM6 Tour")
    product = create_product(tour["id"], sku="SM6-POSTER", name="Poster",
                             base_price_cents=5000,
                             initial_stock_by_size={"OS": 100})
    order = place_online_order(tour["id"], product["id"], 2)
    cancelled = cancel_online_order(order["id"])
    assert cancelled["status"] == "CANCELLED"

    resp = api.fulfill_online_order(order["id"], TM1)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_PLACED)

    reloaded = get_success_data(api.get_online_order(order["id"], TM1))
    assert reloaded["status"] == "CANCELLED"
    assert reloaded["artist_royalty_final_cents"] is None
    assert reloaded["licensing_final_cents"] is None
    assert get_product(product["id"])["warehouse_stock_by_size"]["OS"] == 100, (
        "stock is untouched by a cancelled order")


class TestOnlineRoyaltyDualVariant:
    def test_provisional_royalty_snapshots_creation_config(self, api):
        """PRD §3.7: "Two provisional royalty figures are snapshotted at
        creation from the tour configuration in effect at that moment.
        `artist_royalty_provisional_cents` is the order's `gross_cents`
        multiplied by the tour's `standard_rate_bps` and divided by 10000,
        rounded half up, regardless of treatment."
        PRD §3.7: "`licensing_provisional_cents` is zero for a `STANDARD`
        product; for a `LICENSED` product it is the greater of
        `licensed_flat_per_unit_cents` multiplied by `quantity` and the order's
        `gross_cents` multiplied by `licensed_rate_bps`, divided by 10000, and
        rounded half up."

        Design: Difficulty/dual_variant_calc/online_royalty_provisional_vs_final_after_config_change
        """
        tour = create_active_tour(name="DV2 Tour")
        product = create_product(tour["id"], sku="DV2-POSTER", name="Poster",
                                 base_price_cents=5000,
                                 initial_stock_by_size={"OS": 100})

        order = place_online_order(tour["id"], product["id"], 20)
        assert_online_order(order)
        assert order["gross_cents"] == 100000
        assert order["artist_royalty_provisional_cents"] == 10000, (
            "snapshot at creation: 100000 gross x 1000 bps = 10000")
        assert order["licensing_provisional_cents"] == 0, "STANDARD product"
        assert order["artist_royalty_final_cents"] is None
        assert order["licensing_final_cents"] is None

    def test_final_royalty_recomputed_after_config_patch(self, api):
        """PRD §3.7: "Fulfillment decrements warehouse stock accordingly (a
        bundle decrements each component's OS stock), moves the order to
        `FULFILLED`, and recomputes the royalty arms with the tour configuration
        in effect at that instant: `artist_royalty_final_cents` and
        `licensing_final_cents` follow the same formulas as their provisional
        counterparts but read the live config, so a royalty-config patch between
        placement and fulfillment makes the final figures diverge from the
        provisional ones."

        Design: Difficulty/dual_variant_calc/online_royalty_provisional_vs_final_after_config_change
        """
        tour = create_active_tour(name="DV2 Tour")
        product = create_product(tour["id"], sku="DV2-POSTER", name="Poster",
                                 base_price_cents=5000,
                                 initial_stock_by_size={"OS": 100})
        order = place_online_order(tour["id"], product["id"], 20)

        patch_royalty_config(tour["id"], tour["version"], standard_rate_bps=2000)

        fulfilled = fulfill_online_order(order["id"])
        assert fulfilled["status"] == "FULFILLED"
        assert fulfilled["gross_cents"] == 100000
        assert fulfilled["artist_royalty_provisional_cents"] == 10000, (
            "provisional snapshot is never rewritten")
        assert fulfilled["artist_royalty_final_cents"] == 20000, (
            "recomputed at fulfill: 100000 gross x 2000 bps = 20000")
        assert fulfilled["licensing_provisional_cents"] == 0
        assert fulfilled["licensing_final_cents"] == 0
        assert get_product(product["id"])["warehouse_stock_by_size"]["OS"] == 80


def test_occ_stale_tour_version_rejected(api):
    """PRD §2.9: "Updating a tour's royalty configuration requires the request
    to carry `expected_tour_version` equal to the tour's current `version`;
    repricing a show product requires `expected_show_product_version` equal to
    the show product's current `version`. If another accepted write — a config
    patch, an activation, a close, a prior reprice — has advanced the entity's
    `version` since the caller last observed it, the write is rejected with
    `ERR_STALE_VERSION` (HTTP 412), because the caller would otherwise overwrite
    terms it has never seen."

    Design: Corner/complexity_layers/occ_stale_tour_version_rejected
    """
    tour = create_active_tour(name="CC1 Tour")
    observed_version = tour["version"]

    first = validate_success(api.patch_royalty_config(
        tour["id"],
        royalty_config_payload(standard_rate_bps=1500, tier_threshold_cents=500000,
                               tier_bonus_bps=500, licensed_flat_per_unit_cents=500,
                               licensed_rate_bps=2000,
                               expected_tour_version=observed_version),
        TM1))
    assert first["standard_rate_bps"] == 1500
    assert first["version"] == observed_version + 1, (
        "an accepted config patch increments the tour version by exactly one")

    resp = api.patch_royalty_config(
        tour["id"],
        royalty_config_payload(standard_rate_bps=2500, tier_threshold_cents=500000,
                               tier_bonus_bps=500, licensed_flat_per_unit_cents=500,
                               licensed_rate_bps=2000,
                               expected_tour_version=observed_version),
        TM1)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    assert get_tour(tour["id"])["standard_rate_bps"] == 1500, (
        "the losing write is fully rejected")


def test_bundle_fulfill_decrements_component_stock(api):
    """PRD §3.7: "The order must be `PLACED` (otherwise
    `ERR_ORDER_NOT_PLACED`), and warehouse stock must cover it: for a sized
    `REGULAR` product the `warehouse_stock_by_size` entry for the ordered size
    must be at least `quantity`; for a non-sized product the OS entry must be;
    for a `BUNDLE` every component's OS entry must be at least `qty_per_bundle`
    times `quantity` — any shortfall fails with `ERR_INSUFFICIENT_STOCK`.
    Fulfillment decrements warehouse stock accordingly (a bundle decrements each
    component's OS stock), moves the order to `FULFILLED`, and recomputes the
    royalty arms with the tour configuration in effect at that instant:
    `artist_royalty_final_cents` and `licensing_final_cents` follow the same
    formulas as their provisional counterparts but read the live config, so a
    royalty-config patch between placement and fulfillment makes the final
    figures diverge from the provisional ones."

    Design: Corner/complexity_layers/bundle_fulfill_decrements_component_stock
    """
    tour = create_active_tour(name="CC5 Tour")
    poster = create_product(tour["id"], sku="CC5-POSTER", name="Poster",
                            base_price_cents=2000,
                            initial_stock_by_size={"OS": 100})
    sticker = create_product(tour["id"], sku="CC5-STICKER", name="Sticker",
                             base_price_cents=500,
                             initial_stock_by_size={"OS": 200})
    bundle = create_product(
        tour["id"], sku="CC5-PACK", name="Fan Pack", product_type="BUNDLE",
        base_price_cents=6000,
        bundle_components=[
            {"component_product_id": poster["id"], "qty_per_bundle": 1},
            {"component_product_id": sticker["id"], "qty_per_bundle": 2},
        ],
        initial_stock_by_size={})

    order = place_online_order(tour["id"], bundle["id"], 10)
    assert order["gross_cents"] == 60000

    fulfilled = fulfill_online_order(order["id"])
    assert fulfilled["status"] == "FULFILLED"
    assert fulfilled["artist_royalty_final_cents"] == 6000, (
        "60000 gross x 1000 bps from the live config")
    assert get_product(poster["id"])["warehouse_stock_by_size"]["OS"] == 90, (
        "100 - 10 x 1 poster per bundle")
    assert get_product(sticker["id"])["warehouse_stock_by_size"]["OS"] == 180, (
        "200 - 10 x 2 stickers per bundle")
