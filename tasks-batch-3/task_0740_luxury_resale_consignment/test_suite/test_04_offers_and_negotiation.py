"""The closet: cyclic offer negotiation, the offer floor, lazy expiry, and the
optimistic-concurrency check on offer creation.
"""
from test_helpers import (
    validate_success, validate_error,
    create_offer_payload, create_counter_payload,
    make_seller_headers, make_buyer_headers,
    # fixtures
    setup_published_listing, create_buyer, make_offer, get_offer, get_listing,
    set_clock,
)


# --- non_linear_state_machine: cyclic PENDING <-> COUNTERED negotiation ------
def test_seller_counter_moves_offer_to_countered(api):
    """PRD §3.5: "A `Seller` counters a `PENDING` offer, moving it to `COUNTERED` and
    setting `counter_amount_cents` to their counter (supplied as the `counter_amount_cents`
    input)."

    Design: Difficulty/non_linear_state_machine/offer_cyclic_negotiation_rounds
    """
    ctx = setup_published_listing(list_price_cents=200000, category="HANDBAGS")
    buyer = create_buyer()
    offer = make_offer(ctx["listing_id"], buyer["id"], 150000, ctx["listing_version"])
    validate_success(api.counter_offer(offer["id"], create_counter_payload(175000),
                                       make_seller_headers(ctx["seller_id"])), 200)
    updated = get_offer(offer["id"])
    assert updated["status"] == "COUNTERED", updated["status"]
    assert updated["counter_amount_cents"] == 175000, updated["counter_amount_cents"]


def test_buyer_counter_back_returns_to_pending_and_increments_round(api):
    """PRD §3.5: "A `Buyer` may counter back a `COUNTERED` offer, moving it to `PENDING`:
    this sets the offer's `amount_cents` to the buyer's new figure, clears
    `counter_amount_cents`, and increments `round_number` by one."

    Design: Difficulty/non_linear_state_machine/offer_cyclic_negotiation_rounds
    """
    ctx = setup_published_listing(list_price_cents=200000, category="HANDBAGS")
    buyer = create_buyer()
    offer = make_offer(ctx["listing_id"], buyer["id"], 150000, ctx["listing_version"])
    validate_success(api.counter_offer(offer["id"], create_counter_payload(175000),
                                       make_seller_headers(ctx["seller_id"])), 200)
    validate_success(api.counter_offer(offer["id"], create_counter_payload(160000),
                                       make_buyer_headers(buyer["id"])), 200)
    updated = get_offer(offer["id"])
    assert updated["status"] == "PENDING", updated["status"]
    assert updated["round_number"] == 2, updated["round_number"]
    assert updated["amount_cents"] == 160000, updated["amount_cents"]


# --- Corner: offer below the min_offer floor ---------------------------------
def test_offer_below_floor_rejected(api):
    """PRD §3.4: "It pins `min_offer_cents` as `list_price_cents` multiplied by the
    category's `min_offer_pct`, rounded half up to whole cents."
    PRD §3.5: "the `amount_cents` must be at least the listing's `min_offer_cents` floor,
    or the offer is rejected with `ERR_OFFER_BELOW_FLOOR` (HTTP 422)."

    Design: Corner/validations/offer_below_floor_returns_error
    """
    ctx = setup_published_listing(list_price_cents=200000, category="HANDBAGS")
    buyer = create_buyer()
    # min_offer = round(200000*0.70) = 140000; an offer of 100000 is below the floor.
    res = api.create_offer(
        create_offer_payload(ctx["listing_id"], buyer["id"], 100000, ctx["listing_version"]),
        make_buyer_headers(buyer["id"]))
    validate_error(res, "ERR_OFFER_BELOW_FLOOR", expected_status=422)


# --- Corner: lazy offer expiry on counter ------------------------------------
def test_counter_expired_offer_rejected(api):
    """PRD §3.5: "A new offer starts in `PENDING` with `round_number` at 1 and an
    `expires_at` set to its creation instant plus seventy-two hours;"
    PRD §3.5: "an offer whose `expires_at` has passed on the logical clock is treated as
    `EXPIRED` the moment it is next read, countered, or accepted; acting on such an offer
    therefore fails the state precondition with `ERR_OFFER_INVALID_STATE`."

    Design: Corner/state_machines/counter_expired_offer_returns_invalid_state
    """
    set_clock("2026-03-01T00:00:00Z")
    ctx = setup_published_listing(list_price_cents=200000, category="HANDBAGS")
    buyer = create_buyer()
    offer = make_offer(ctx["listing_id"], buyer["id"], 150000, ctx["listing_version"])
    # expires_at = 2026-03-01 + 72h = 2026-03-04T00:00:00Z; advance past it.
    set_clock("2026-03-05T00:00:00Z")
    res = api.counter_offer(offer["id"], create_counter_payload(175000),
                            make_seller_headers(ctx["seller_id"]))
    validate_error(res, "ERR_OFFER_INVALID_STATE", expected_status=409)


# --- Corner: OCC stale listing version on offer create -----------------------
def test_stale_listing_version_on_offer_rejected(api):
    """PRD §3.5: "creating it increments the listing's `version` by one."
    PRD §2.6: "If the listing's version has advanced since the buyer read it — because
    another offer was created, the seller published or relisted it, or the listing was
    marked sold — the buyer's observed version is stale, and the create is rejected with
    `ERR_STALE_LISTING_VERSION` (HTTP 412), preventing the buyer from posting against a
    listing state that no longer exists."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_listing_version_returns_412
    """
    ctx = setup_published_listing(list_price_cents=200000, category="HANDBAGS")
    stale_version = ctx["listing_version"]
    buyer_a = create_buyer(display_name="BA", email="ba@x.com")
    buyer_b = create_buyer(display_name="BB", email="bb@x.com")
    # buyer_a's offer advances Listing.version, so stale_version is now stale.
    make_offer(ctx["listing_id"], buyer_a["id"], 160000, stale_version)
    assert get_listing(ctx["listing_id"])["version"] != stale_version
    res = api.create_offer(
        create_offer_payload(ctx["listing_id"], buyer_b["id"], 170000, stale_version),
        make_buyer_headers(buyer_b["id"]))
    validate_error(res, "ERR_STALE_LISTING_VERSION", expected_status=412)
