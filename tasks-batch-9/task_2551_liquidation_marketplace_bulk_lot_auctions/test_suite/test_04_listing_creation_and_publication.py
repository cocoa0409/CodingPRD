"""Listing creation shape rules and the ordered publication gate."""

from test_helpers import (
    ADMIN,
    AUCTION_OPENING_BID_CENTS,
    api_client,
    assert_listing,
    auction_listing_payload,
    bootstrap_marketplace,
    create_brand_policy,
    create_listing,
    publish_listing,
    read_listing,
    read_lot,
    read_seller,
    setup_approved_lot,
    setup_decided_claim,
    total_count,
    validate_error,
    validate_success,
)

TWO_HUNDRED_UNIT_LINES = [
    {
        "sku": "APP-RET-0200",
        "unit_count": 200,
        "unit_retail_cents": 10_000,
        "declared_condition": "USED_GOOD",
    },
]

FIFTY_UNIT_LINES = [
    {
        "sku": "APP-RET-0050",
        "unit_count": 50,
        "unit_retail_cents": 20_000,
        "declared_condition": "USED_GOOD",
    },
]

EMBARGO_START = "2026-08-01T00:00:00Z"
EMBARGO_END = "2026-08-10T00:00:00Z"


def test_listing_creation_refuses_an_inverted_window_and_an_unknown_channel():
    """Both an end instant that precedes the start and a resale channel outside
    the closed set are refused as request-shape violations, leaving the lot
    without any listing.

    PRD 2.5: "All required input fields present; every enum-valued field inside
    its declared value set; every integer inside its declared range (`unit_count`
    at least 1, `unit_retail_cents` at least 1, `dock_door_count` at least 1,
    `daily_pickup_capacity` at least 1, `bid_increment_cents` at least 1);
    `window_end_at` strictly later than `window_start_at`; and the
    format-conditional price field present for the chosen sale mechanism
    (`opening_bid_cents` for an auction, `ask_price_cents` for a fixed price,
    `min_offer_cents` for negotiated terms)."
    PRD 2.10: "A resale channel — whether it appears as a member of
    `permitted_channels` or as a listing's `resale_channel` — is one of
    `MARKETPLACE_RESALE`, `EXPORT_ONLY`, `DISCOUNT_RETAIL` or `SCRAP_ONLY`."

    Design: Corner/entities/listing_creation_rejects_window_end_before_window_start
    """
    env = bootstrap_marketplace()
    built = setup_approved_lot(env, TWO_HUNDRED_UNIT_LINES)
    lot_id = built["lot"]["id"]

    inverted = api_client.create_listing(
        lot_id,
        auction_listing_payload(
            window_start_at="2026-08-12T00:00:00Z",
            window_end_at="2026-08-05T00:00:00Z",
        ),
        env["seller_headers"],
    )
    validate_error(inverted, "ERR_INVALID_REQUEST", 400)

    bad_channel = api_client.create_listing(
        lot_id,
        auction_listing_payload(resale_channel="WHOLESALE_CLUB"),
        env["seller_headers"],
    )
    validate_error(bad_channel, "ERR_INVALID_REQUEST", 400)

    assert total_count(api_client.list_lot_listings(lot_id, env["seller_headers"])) == 0
    assert read_lot(env, lot_id)["lot_status"] == "MANIFEST_APPROVED"


def test_auction_reserve_below_the_opening_bid_is_refused_at_creation():
    """A reserve one cent under the opening bid is refused, while a reserve
    exactly equal to it creates a DRAFT listing whose reserve is not yet met.

    PRD 3.3: "One fiscal check runs at creation: when both `reserve_price_cents`
    and `opening_bid_cents` are supplied on an auction listing, the reserve must
    be at least the opening bid, since a reserve below the opening bid could never
    bind."
    PRD 3.3: "A reserve below the opening bid is `ERR_RESERVE_BELOW_OPENING`."
    PRD 3.3: "A freshly created listing has `listing_status` `DRAFT`,
    `effective_close_at` seeded to `window_end_at`, `extension_count` at zero,
    `bid_count` at zero, `current_high_bid_cents` and `current_high_bidder_id`
    both null, and `reserve_met` set by the reserve rule: it is true when
    `reserve_price_cents` is null, and otherwise false while there is no high
    bid."

    Design: Corner/errors/auction_reserve_below_opening_is_refused_at_listing_creation
    """
    env = bootstrap_marketplace()
    built = setup_approved_lot(env, TWO_HUNDRED_UNIT_LINES)
    lot_id = built["lot"]["id"]

    refused = api_client.create_listing(
        lot_id,
        auction_listing_payload(reserve_price_cents=999_999),
        env["seller_headers"],
    )
    validate_error(refused, "ERR_RESERVE_BELOW_OPENING", 422)
    assert read_lot(env, lot_id)["lot_status"] == "MANIFEST_APPROVED"

    accepted = validate_success(
        api_client.create_listing(
            lot_id,
            auction_listing_payload(reserve_price_cents=AUCTION_OPENING_BID_CENTS),
            env["seller_headers"],
        ),
        201,
    )
    assert_listing(accepted)
    assert accepted["listing_status"] == "DRAFT"
    assert accepted["reserve_price_cents"] == AUCTION_OPENING_BID_CENTS
    assert accepted["reserve_met"] is False
    assert accepted["bid_count"] == 0
    assert accepted["extension_count"] == 0
    assert accepted["current_high_bid_cents"] is None
    assert accepted["current_high_bidder_id"] is None
    assert total_count(api_client.list_lot_listings(lot_id, env["seller_headers"])) == 1


def test_debranding_attestation_is_demanded_only_by_the_lot_that_mirrors_it():
    """The attestation gate follows the lot's mirrored flag: the unattested
    listing on the de-branding lot is refused while the unattested listing on the
    permissive lot publishes.

    PRD 3.1: "One value is copied rather than computed: the lot's
    `de_branding_required` mirrors the linked brand policy's own
    `de_branding_required` at the instant of creation, and it is false when no
    `brand_policy_id` was supplied."
    PRD 3.3: "Next, at band 11, the brand-protection pair: when the lot names a
    brand policy, the listing's `resale_channel` must appear in that policy's
    `permitted_channels` allow-list, and a channel absent from the list is
    `ERR_CHANNEL_NOT_PERMITTED`; and whenever the lot's `de_branding_required` is
    true, the listing's `de_branding_attested` must be true, or the publication is
    refused with `ERR_DEBRANDING_ATTESTATION_REQUIRED`."

    Design: Corner/validations/debranding_attestation_required_only_when_the_brand_policy_demands_it
    """
    env = bootstrap_marketplace()
    strict_policy = create_brand_policy(
        "ARCLIGHT",
        ["MARKETPLACE_RESALE"],
        de_branding_required=True,
        debranding_fee_cents_per_unit=25,
    )
    permissive_policy = create_brand_policy("PLAINCO", ["MARKETPLACE_RESALE"])
    branded = setup_approved_lot(
        env, TWO_HUNDRED_UNIT_LINES,
        brand_policy_id=strict_policy["id"], title="Arclight branded returns",
    )
    plain = setup_approved_lot(
        env, TWO_HUNDRED_UNIT_LINES,
        brand_policy_id=permissive_policy["id"], title="Plainco returns",
    )
    assert branded["lot"]["de_branding_required"] is True
    assert plain["lot"]["de_branding_required"] is False

    unattested = create_listing(env, branded["lot"]["id"], auction_listing_payload())
    attested = create_listing(
        env, branded["lot"]["id"], auction_listing_payload(de_branding_attested=True)
    )
    plain_listing = create_listing(env, plain["lot"]["id"], auction_listing_payload())

    refused = api_client.publish_listing(unattested["id"], {}, env["seller_headers"])
    validate_error(refused, "ERR_DEBRANDING_ATTESTATION_REQUIRED", 422)
    reread = read_listing(env, unattested["id"])
    assert reread["listing_status"] == "DRAFT"
    assert reread["de_branding_attested"] is False

    published_plain = validate_success(
        api_client.publish_listing(plain_listing["id"], {}, env["seller_headers"])
    )
    assert published_plain["listing_status"] == "OPEN"

    published_attested = validate_success(
        api_client.publish_listing(attested["id"], {}, env["seller_headers"])
    )
    assert published_attested["listing_status"] == "OPEN"
    assert published_attested["de_branding_attested"] is True

    assert read_lot(env, branded["lot"]["id"])["lot_status"] == "LISTED"
    assert read_lot(env, plain["lot"]["id"])["lot_status"] == "LISTED"


def test_publication_is_refused_when_the_channel_is_outside_the_allow_list():
    """The allow-list is enforced at publication rather than at creation, so the
    off-list listing is created happily and only fails when it is opened.

    PRD 3.3: "Next, at band 11, the brand-protection pair: when the lot names a
    brand policy, the listing's `resale_channel` must appear in that policy's
    `permitted_channels` allow-list, and a channel absent from the list is
    `ERR_CHANNEL_NOT_PERMITTED`; and whenever the lot's `de_branding_required` is
    true, the listing's `de_branding_attested` must be true, or the publication is
    refused with `ERR_DEBRANDING_ATTESTATION_REQUIRED`."
    PRD 3.3: "A publication that clears the whole gate advances the listing
    `DRAFT → OPEN`, sets `effective_close_at` to `window_end_at` and
    `extension_count` to zero, and advances the listing's `version` by one."

    Design: Corner/validations/publication_rejected_when_resale_channel_is_outside_permitted_channels
    """
    env = bootstrap_marketplace()
    export_policy = create_brand_policy("EXPORTLINE", ["EXPORT_ONLY"])
    built = setup_approved_lot(
        env, TWO_HUNDRED_UNIT_LINES,
        brand_policy_id=export_policy["id"], title="Exportline overstock",
    )

    off_list = validate_success(
        api_client.create_listing(
            built["lot"]["id"],
            auction_listing_payload(resale_channel="MARKETPLACE_RESALE"),
            env["seller_headers"],
        ),
        201,
    )
    on_list = create_listing(
        env, built["lot"]["id"], auction_listing_payload(resale_channel="EXPORT_ONLY")
    )

    refused = api_client.publish_listing(off_list["id"], {}, env["seller_headers"])
    validate_error(refused, "ERR_CHANNEL_NOT_PERMITTED", 422)
    assert read_listing(env, off_list["id"])["listing_status"] == "DRAFT"

    published = validate_success(
        api_client.publish_listing(on_list["id"], {}, env["seller_headers"])
    )
    assert published["listing_status"] == "OPEN"
    assert published["resale_channel"] == "EXPORT_ONLY"
    assert read_lot(env, built["lot"]["id"])["lot_status"] == "LISTED"


def test_brand_embargo_bites_on_its_inclusive_end_instant():
    """A window that starts exactly at `embargo_end_at` still intersects the
    embargo, while a window starting one second later publishes.

    PRD 3.3: "Then, at band 12, the embargo test: the offering interval running
    from `window_start_at` to `window_end_at` must not intersect the brand
    policy's embargo interval running from `embargo_start_at` to `embargo_end_at`,
    with both intervals treated as inclusive at both ends, so an offering window
    that merely touches an embargo endpoint is still an intersection and is
    rejected with `ERR_BRAND_EMBARGO_ACTIVE`."

    Design: Corner/validations/brand_embargo_blocks_publication_on_the_inclusive_end_instant
    """
    env = bootstrap_marketplace()
    policy = create_brand_policy(
        "MERIDIAN",
        ["MARKETPLACE_RESALE"],
        embargo_start_at=EMBARGO_START,
        embargo_end_at=EMBARGO_END,
    )
    built = setup_approved_lot(
        env, TWO_HUNDRED_UNIT_LINES,
        brand_policy_id=policy["id"], title="Meridian salvage",
    )

    touching = create_listing(
        env,
        built["lot"]["id"],
        auction_listing_payload(
            window_start_at=EMBARGO_END, window_end_at="2026-08-17T00:00:00Z"
        ),
    )
    clear = create_listing(
        env,
        built["lot"]["id"],
        auction_listing_payload(
            window_start_at="2026-08-10T00:00:01Z", window_end_at="2026-08-17T00:00:00Z"
        ),
    )

    refused = api_client.publish_listing(touching["id"], {}, env["seller_headers"])
    validate_error(refused, "ERR_BRAND_EMBARGO_ACTIVE", 422)
    assert read_listing(env, touching["id"])["listing_status"] == "DRAFT"
    assert read_lot(env, built["lot"]["id"])["lot_status"] == "MANIFEST_APPROVED"

    published = validate_success(
        api_client.publish_listing(clear["id"], {}, env["seller_headers"])
    )
    assert published["listing_status"] == "OPEN"
    assert read_lot(env, built["lot"]["id"])["lot_status"] == "LISTED"


def test_second_publication_on_one_lot_is_caught_by_the_lot_state_gate():
    """Publishing the first listing moves the lot out of MANIFEST_APPROVED, so the
    sibling publication is refused by the band 10 lot-state guard rather than by
    the band 15 concurrent-offering rule.

    PRD 3.3: "Then, at band 10, two cross-entity conditions: the backing lot's
    `lot_status` must be `MANIFEST_APPROVED` or `RELIST_PENDING`, and a lot still
    in `DRAFT`, `MANIFEST_IN_REVIEW` or `MANIFEST_REJECTED` cannot back an open
    offering — `ERR_LOT_MANIFEST_NOT_APPROVED`; and the owning seller's
    `account_status` must be `ACTIVE`, so a seller sitting on
    `MANIFEST_PROBATION` is barred from publishing anything at all —
    `ERR_SELLER_NOT_ACTIVE`."
    PRD 3.3: "Finally, at band 15, at most one live offering per lot: if another
    listing on the same lot already has `listing_status` equal to `OPEN`, the
    publication is refused with `ERR_LISTING_ALREADY_OPEN`."
    PRD 3.3: "The lot moves with it: `MANIFEST_APPROVED → LISTED` on a first
    offering, or `RELIST_PENDING → LISTED` when the lot is being offered again
    after a failed auction or an abandoned pickup."

    Design: Corner/errors/second_open_listing_on_one_lot_is_refused_by_the_lot_state_rule
    """
    env = bootstrap_marketplace()
    built = setup_approved_lot(env, TWO_HUNDRED_UNIT_LINES)
    lot_id = built["lot"]["id"]
    first = create_listing(env, lot_id, auction_listing_payload())
    second = create_listing(env, lot_id, auction_listing_payload())

    opened = publish_listing(env, first["id"])
    assert opened["listing_status"] == "OPEN"
    assert read_lot(env, lot_id)["lot_status"] == "LISTED"

    refused = api_client.publish_listing(second["id"], {}, env["seller_headers"])
    validate_error(refused, "ERR_LOT_MANIFEST_NOT_APPROVED", 409)

    assert read_listing(env, second["id"])["listing_status"] == "DRAFT"
    open_listings = total_count(
        api_client.list_lot_listings(lot_id, env["seller_headers"], {"listing_status": "OPEN"})
    )
    assert open_listings == 1


def test_publication_is_barred_by_probation_earned_on_a_different_lot():
    """A listing that satisfies every rule belonging to itself and to its own lot
    is still refused because a claim on an unrelated lot pushed the owning seller
    onto probation.

    PRD 3.3: "Then, at band 10, two cross-entity conditions: the backing lot's
    `lot_status` must be `MANIFEST_APPROVED` or `RELIST_PENDING`, and a lot still
    in `DRAFT`, `MANIFEST_IN_REVIEW` or `MANIFEST_REJECTED` cannot back an open
    offering — `ERR_LOT_MANIFEST_NOT_APPROVED`; and the owning seller's
    `account_status` must be `ACTIVE`, so a seller sitting on
    `MANIFEST_PROBATION` is barred from publishing anything at all —
    `ERR_SELLER_NOT_ACTIVE`."
    PRD 3.9: "When `manifest_accuracy_avg` falls strictly below 0.850, the seller
    advances `ACTIVE → MANIFEST_PROBATION`; an average landing exactly on 0.850
    keeps the seller `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/listing_publication_blocked_by_seller_probation_on_another_lot
    """
    env = bootstrap_marketplace()
    spare = setup_approved_lot(env, FIFTY_UNIT_LINES, title="Second returns lot")
    spare_listing = create_listing(
        env,
        spare["lot"]["id"],
        auction_listing_payload(
            window_start_at="2026-08-25T00:00:00Z", window_end_at="2026-08-31T00:00:00Z"
        ),
    )
    setup_decided_claim(env)

    assert read_lot(env, spare["lot"]["id"])["lot_status"] == "MANIFEST_APPROVED"
    assert read_listing(env, spare_listing["id"])["listing_status"] == "DRAFT"
    seller = read_seller(env)
    assert seller["account_status"] == "MANIFEST_PROBATION"
    assert seller["commission_tier"] == "TIER_PROBATION"

    refused = api_client.publish_listing(spare_listing["id"], {}, env["seller_headers"])
    validate_error(refused, "ERR_SELLER_NOT_ACTIVE", 409)

    assert read_listing(env, spare_listing["id"])["listing_status"] == "DRAFT"
    assert read_lot(env, spare["lot"]["id"])["lot_status"] == "MANIFEST_APPROVED"


def test_a_refused_publication_leaves_the_gross_denominator_and_probation_rate_alone():
    """Because the probation-blocked publication never happened, the spare lot's
    retail value stays out of the gross denominator and the seller keeps the
    probation rate that overrides its recovery-based tier.

    PRD 3.3: "Publication also enters the lot into the seller's gross recovery
    denominator — the seller's `listed_retail_value_cents` is recomputed as the sum
    of `declared_retail_value_cents` over that seller's lots whose `lot_status` is
    `LISTED`, `SOLD` or `RELIST_PENDING`, which recomputes `gross_recovery_rate`,
    which reassigns `commission_tier` and `commission_rate_bps` as §3.9
    specifies."
    PRD 3.9: "Probation has two consequences: `commission_tier` is forced to
    `TIER_PROBATION` with `commission_rate_bps` of 2,500 basis points, overriding
    whatever the recovery-based tier would otherwise have been, and every
    publication attempt on any of that seller's lots is refused with
    `ERR_SELLER_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/listing_publication_blocked_by_seller_probation_on_another_lot
    """
    env = bootstrap_marketplace()
    spare = setup_approved_lot(env, FIFTY_UNIT_LINES, title="Second returns lot")
    spare_listing = create_listing(
        env,
        spare["lot"]["id"],
        auction_listing_payload(
            window_start_at="2026-08-25T00:00:00Z", window_end_at="2026-08-31T00:00:00Z"
        ),
    )
    setup_decided_claim(env)

    refused = api_client.publish_listing(spare_listing["id"], {}, env["seller_headers"])
    validate_error(refused, "ERR_SELLER_NOT_ACTIVE", 409)

    seller = read_seller(env)
    assert seller["listed_retail_value_cents"] == 10_000_000
    assert seller["gross_hammer_cents"] == 2_700_000
    assert seller["gross_recovery_rate"] == 0.27
    assert seller["manifest_accuracy_avg"] == 0.83
    assert seller["account_status"] == "MANIFEST_PROBATION"
    assert seller["commission_tier"] == "TIER_PROBATION"
    assert seller["commission_rate_bps"] == 2500
