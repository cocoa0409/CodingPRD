"""The version counters themselves: each accepted write consumes the version the client
presented and hands back exactly one more, a refused write consumes nothing, and replaying
the body with the fresh number succeeds unchanged."""

from test_helpers import (
    CLOCK_SETUP,
    COUNTY_PRIMARY,
    TEST_USERS,
    add_lot,
    add_lot_payload,
    api_client,
    create_event,
    create_listing,
    create_seller,
    file_disclosures,
    read_event,
    read_listing,
    read_lot,
    reserve_price_payload,
    set_clock,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["auction_ops_headers"]

EVENT_START = "2026-09-15T17:00:00Z"
EVENT_END = "2026-09-15T19:00:00Z"
FIRST_WINDOW_START = "2026-09-15T17:00:00Z"
FIRST_WINDOW_END = "2026-09-15T18:00:00Z"
SECOND_WINDOW_START = "2026-09-15T18:00:00Z"
SECOND_WINDOW_END = "2026-09-15T19:00:00Z"


def test_a_roster_builder_that_read_the_event_once_is_refused_on_the_second_lot():
    """Every accepted lot addition consumes the event version, so the second add carrying the
    version the client read before the first one is refused; the refusal creates nothing, and
    the identical body replayed with the fresh version is accepted.

    PRD: "Adding a lot to an auction event requires `expected_auction_event_version` in the
    request body, carrying the `version` of the `AuctionEvent` as the client last read it. If
    that value does not equal the event's current `version`, the request is rejected with
    `ERR_STALE_EVENT_VERSION` (HTTP 412)."
    PRD: "The parent event's `lot_count` is recomputed to the number of lots now bound to it,
    and the event's `version` advances by 1 — which is exactly why the next lot addition must
    present a fresh `expected_auction_event_version`."
    PRD: "Creating the lot pulls its asset onto the marketplace: `listing_status` advances
    `DISCLOSURE_READY → LISTED`, and the step is idempotent for an asset already `LISTED`
    through another lot."

    Design: Corner/cross_cutting_complexity_layers/stale_event_version_rejects_the_second_lot_add
    """
    set_clock(CLOCK_SETUP)
    seller = create_seller(
        org_name="OCC Event Bank",
        seller_type="BANK",
        contact_email="o@occevent.example",
        settlement_account_ref="ACH-OCCE",
    )
    first_listing = create_listing(
        seller, street_address="1 Occevent Rd", city="Oakland", estimated_value_cents=26000000
    )
    file_disclosures(seller, first_listing, "VACANT", "CLEAR")
    second_listing = create_listing(
        seller, street_address="2 Occevent Rd", city="Oakland", estimated_value_cents=26000000
    )
    file_disclosures(seller, second_listing, "VACANT", "CLEAR")

    event = create_event(
        title="OCC Event",
        county_code=COUNTY_PRIMARY,
        starts_at=EVENT_START,
        ends_at=EVENT_END,
    )
    first_version = event["version"]
    assert first_version == 1

    add_lot(
        event["id"],
        first_listing["id"],
        lot_number=1,
        lot_window_start_at=FIRST_WINDOW_START,
        lot_window_end_at=FIRST_WINDOW_END,
        opening_bid_cents=20000000,
        reserve_price_cents=20000000,
        expected_auction_event_version=first_version,
    )
    after_first = read_event(event["id"], OPS)
    assert after_first["version"] == 2
    assert after_first["lot_count"] == 1

    second_body = add_lot_payload(
        second_listing["id"],
        first_version,
        lot_number=2,
        lot_window_start_at=SECOND_WINDOW_START,
        lot_window_end_at=SECOND_WINDOW_END,
        opening_bid_cents=20000000,
        reserve_price_cents=20000000,
    )
    validate_error(
        api_client.add_lot(event["id"], second_body, OPS), "ERR_STALE_EVENT_VERSION", 412
    )

    after_refusal = read_event(event["id"], OPS)
    assert after_refusal["version"] == 2
    assert after_refusal["lot_count"] == 1
    assert read_listing(second_listing["id"])["listing_status"] == "DISCLOSURE_READY"

    second_body["expected_auction_event_version"] = after_first["version"]
    validate_success(api_client.add_lot(event["id"], second_body, OPS), 201)

    after_replay = read_event(event["id"], OPS)
    assert after_replay["version"] == 3
    assert after_replay["lot_count"] == 2
    assert read_listing(second_listing["id"])["listing_status"] == "LISTED"


def test_each_accepted_reserve_write_advances_the_lot_version_by_exactly_one():
    """Two reserve revisions each presenting the version returned by the previous response are
    both accepted and take the lot 1 to 2 to 3; only the version already consumed is refused,
    and the deposit fixed at admission never moves with the reserve.

    PRD: "Revising a lot's reserve price requires `expected_auction_lot_version` in the request
    body, carrying the `version` of the `AuctionLot` as the client last read it. A mismatch
    against the lot's current `version` is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412)."
    PRD: "A successful revision advances the lot's `version` by 1."
    PRD: "**The deposit a bidder must post is fixed once, at lot creation, and never
    retro-adjusted.**"
    PRD: "A later disclosure filing or title finding that changes the asset does not reprice a
    lot that already exists."

    Design: Corner/cross_cutting_complexity_layers/lot_version_advances_by_one_per_accepted_reserve_write
    """
    set_clock(CLOCK_SETUP)
    seller = create_seller(
        org_name="OCC Lot Bank",
        seller_type="BANK",
        contact_email="o@occlot.example",
        settlement_account_ref="ACH-OCCL",
    )
    listing = create_listing(
        seller, street_address="1 Occlot Rd", city="Oakland", estimated_value_cents=26000000
    )
    file_disclosures(seller, listing, "VACANT", "CLEAR")

    event = create_event(
        title="OCC Lot Event",
        county_code=COUNTY_PRIMARY,
        starts_at=EVENT_START,
        ends_at=EVENT_END,
    )
    lot = add_lot(
        event["id"],
        listing["id"],
        lot_number=1,
        lot_window_start_at=FIRST_WINDOW_START,
        lot_window_end_at=FIRST_WINDOW_END,
        opening_bid_cents=20000000,
        reserve_price_cents=20000000,
        expected_auction_event_version=event["version"],
    )
    assert lot["version"] == 1
    assert lot["required_deposit_cents"] == 1000000

    second = validate_success(
        api_client.update_reserve_price(
            lot["id"], reserve_price_payload(22000000, lot["version"]), OPS
        )
    )
    assert second["version"] == 2
    assert second["reserve_price_cents"] == 22000000
    assert second["required_deposit_cents"] == 1000000

    third = validate_success(
        api_client.update_reserve_price(
            lot["id"], reserve_price_payload(24000000, second["version"]), OPS
        )
    )
    assert third["version"] == 3
    assert third["reserve_price_cents"] == 24000000

    validate_error(
        api_client.update_reserve_price(
            lot["id"], reserve_price_payload(25000000, second["version"]), OPS
        ),
        "ERR_STALE_LOT_VERSION",
        412,
    )

    final = read_lot(lot["id"], OPS)
    assert final["version"] == 3
    assert final["reserve_price_cents"] == 24000000
