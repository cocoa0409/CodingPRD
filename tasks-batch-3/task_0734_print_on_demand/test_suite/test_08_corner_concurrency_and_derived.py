"""Corner tests — OCC stale-version, markup-cascade derived field
reconciliation, and happy-path endpoint smoke."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    get_success_data,
    make_platform_admin_headers,
    make_anonymous_headers,
    make_creator_headers,
    set_clock,
    create_verified_creator,
    create_product_and_variant,
    create_storefront,
    upload_and_approve_design,
    create_and_publish_listing,
    listing_payload,
    storefront_payload,
    storefront_update_payload,
    link_channel_payload,
    ingest_channel_order_payload,
    design_payload,
)


# =============================================================================
# Corner: cross-cutting complexity — OCC on link-channel
# =============================================================================

def test_link_channel_with_stale_expected_version_returns_stale_version(api):
    """PRD §2.5: "Linking a `Storefront` to an external channel — Etsy or
    Shopify — is the single write in this system that carries a mandatory
    optimistic-concurrency guard. The link-channel request must include a
    non-optional `expected_storefront_version` field carrying the client's last
    observed `version` of the target storefront. When the server processes the
    request, it compares `expected_storefront_version` to the storefront's
    current `version`. If the two do not match — because another writer has
    already linked, suspended, resumed, or updated the storefront since the
    client last read it — the request is rejected with
    `ERR_STALE_STOREFRONT_VERSION` and HTTP 412."

    A PUT that bumps the storefront's version invalidates the earlier version;
    a subsequent link-channel with that stale version -> ERR_STALE_STOREFRONT_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_storefront_version_on_link_channel
    """
    set_clock("2026-06-01T00:00:00Z")
    creator = create_verified_creator(email="occ@example.com", display_name="OCC")
    sf = get_success_data(api.create_storefront(
        storefront_payload(
            creator["id"], slug="occ-sf", integration_channel="SHOPIFY", markup_bps=5000,
        ),
        make_creator_headers(creator["id"]),
    ))
    v_initial = sf["version"]
    # Bump version via unrelated write (PUT markup).
    get_success_data(api.update_storefront(
        sf["id"], storefront_update_payload(markup_bps=6000),
        make_creator_headers(creator["id"]),
    ))
    # Now try to link with the stale version.
    resp = api.link_channel(
        sf["id"], link_channel_payload(expected_storefront_version=v_initial),
        make_creator_headers(creator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_STOREFRONT_VERSION)


# =============================================================================
# Corner: derived-field reconciliation — markup update cascades listing prices
# =============================================================================

def test_storefront_markup_update_cascades_listing_price_recompute(api):
    """PRD §3.2: "Updating the markup is the pricing-engine's cascade trigger.
    When a creator revises `markup_bps` on their storefront, every dependent
    `Listing` under that storefront has its `listed_price_cents` recomputed from
    the new markup, its `updated_at` refreshed, and its `version` incremented."
    PRD §3.6: "The listed price is the sum of the per-unit base, the ceiled
    platform fee, and the ceiled creator markup — the two rate-based components
    are each ceiled individually before being added."
    PRD §3.6: "The platform fee in basis-points is chosen by product category:
    `APPAREL` carries 1500 basis-points, `DRINKWARE` 1200, `ACCESSORY` 1000, and `PRINT` 800."

    For base=2000, APPAREL fee=1500 bps:
      markup 5000: 2000 + ceil(2000*1500/10000) + ceil(2000*5000/10000)
                 = 2000 + 300 + 1000 = 3300
      markup 10000: 2000 + 300 + ceil(2000*10000/10000) = 2000 + 300 + 2000 = 4300

    Design: Corner/cross_cutting_complexity_layers/markup_update_cascades_to_all_listings_prices
    """
    set_clock("2026-06-01T00:00:00Z")
    product, variant = create_product_and_variant(sku="T-MK", category="APPAREL", base_cost_cents=2000)
    creator = create_verified_creator(email="mk@example.com", display_name="MK")
    sf = create_storefront(creator["id"], slug="mk-sf", markup_bps=5000)
    design = upload_and_approve_design(creator["id"], file_hash="hash_mk")
    listing = get_success_data(api.create_listing(
        listing_payload(sf["id"], design["id"], variant["id"], title="MK Tee"),
        make_creator_headers(creator["id"]),
    ))
    assert listing["listed_price_cents"] == 3300, \
        f"Setup: expected pre-cascade price=3300, got {listing['listed_price_cents']}"

    api.update_storefront(
        sf["id"], storefront_update_payload(markup_bps=10000),
        make_creator_headers(creator["id"]),
    )
    listing_after = get_success_data(
        api.get_listing(listing["id"], make_platform_admin_headers()),
    )
    assert listing_after["listed_price_cents"] == 4300, \
        f"Expected post-cascade price=4300, got {listing_after['listed_price_cents']}"


# =============================================================================
# Corner: endpoints — happy paths
# =============================================================================

def test_publish_listing_transitions_draft_to_published(api):
    """PRD §3.6: "Publication moves a listing from `DRAFT` to `PUBLISHED`,
    exposing it on the storefront."

    Design: Corner/endpoints/publish_listing_from_draft_transitions_to_published
    """
    set_clock("2026-06-01T00:00:00Z")
    product, variant = create_product_and_variant(sku="T-PL")
    creator = create_verified_creator(email="pl@example.com", display_name="PL")
    sf = create_storefront(creator["id"], slug="pl-sf", markup_bps=5000)
    design = upload_and_approve_design(creator["id"], file_hash="hash_pl")
    listing = get_success_data(api.create_listing(
        listing_payload(sf["id"], design["id"], variant["id"], title="PL Tee"),
        make_creator_headers(creator["id"]),
    ))
    assert listing["status"] == "DRAFT"
    resp = api.publish_listing(listing["id"], make_creator_headers(creator["id"]))
    data = validate_success(resp)
    assert data["status"] == "PUBLISHED", \
        f"Expected status=PUBLISHED after publish, got {data['status']}"


def test_ingest_channel_order_creates_order_and_emits_sync_event(api):
    """PRD §3.3: "External channels may also push orders into the platform.
    When Etsy or Shopify posts an ingested order to the storefront's ingest
    endpoint, the server creates a native `Order` shell — with `payment_status`
    set to `DRAFT` and `fulfillment_status` set to `PENDING` — and emits a
    `ChannelSyncEvent` with `event_type` set to `ORDER_INGEST` capturing the
    external channel's `external_ref` for reconciliation."

    Design: Corner/endpoints/ingest_channel_order_creates_order_and_sync_event
    """
    set_clock("2026-06-01T00:00:00Z")
    product, variant = create_product_and_variant(sku="T-IC")
    creator = create_verified_creator(email="ic@example.com", display_name="IC")
    sf = get_success_data(api.create_storefront(
        storefront_payload(
            creator["id"], slug="ic-sf", integration_channel="SHOPIFY", markup_bps=5000,
        ),
        make_creator_headers(creator["id"]),
    ))
    # Link the channel so the storefront is LINKED to SHOPIFY.
    get_success_data(api.link_channel(
        sf["id"], link_channel_payload(expected_storefront_version=sf["version"]),
        make_creator_headers(creator["id"]),
    ))
    design = upload_and_approve_design(creator["id"], file_hash="hash_ic")
    listing = create_and_publish_listing(
        sf["id"], design["id"], variant["id"], creator["id"], title="IC Tee",
    )

    ing_resp = api.ingest_channel_order(
        sf["id"],
        ingest_channel_order_payload(
            channel="SHOPIFY", external_ref="shop_ext_1", listing_id=listing["id"],
        ),
        make_platform_admin_headers(),
    )
    new_order = validate_success(ing_resp, expected_status=201)
    assert new_order["payment_status"] == "DRAFT", \
        f"Expected new order payment_status=DRAFT, got {new_order['payment_status']}"
    assert new_order["fulfillment_status"] == "PENDING", \
        f"Expected new order fulfillment_status=PENDING, got {new_order['fulfillment_status']}"

    events_resp = api.list_channel_sync_events(sf["id"], make_platform_admin_headers())
    events_data = get_success_data(events_resp)
    if isinstance(events_data, dict) and "data" in events_data:
        events_list = events_data["data"]
    elif isinstance(events_data, list):
        events_list = events_data
    else:
        events_list = events_data
    # ChannelSyncEvent for LISTING_MIRROR was emitted at link-channel; the ORDER_INGEST
    # must also exist after the ingest call.
    ingested_events = [e for e in events_list if e.get("event_type") == "ORDER_INGEST"]
    assert len(ingested_events) >= 1, \
        f"Expected at least one ORDER_INGEST event; events={events_list}"
