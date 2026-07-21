"""Ticket tiers, reserved-seat geography and promotional codes."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, ANONYMOUS_HEADERS,
    assert_ticket_type, assert_seat_block,
    create_ticket_type_payload, create_seat_block_payload, create_promo_code_payload,
    setup_marketplace, setup_draft_event, setup_onsale_event,
    create_ticket_type, create_promo_code, create_buyer, create_held_order,
    read_ticket_type, order_items_of, read_order,
)


def test_list_ticket_types_paginates_with_the_standard_envelope():
    """PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` — the number of records matching the filters before the window is
    applied — and `has_more`, which is true exactly when records remain beyond the
    current window."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/corner_list_ticket_types_paginates_with_envelope_fields
    """
    ctx = setup_draft_event(
        event_overrides={"title": "Pager Night", "starts_at": "2026-09-12T18:00:00Z",
                         "ends_at": "2026-09-12T22:00:00Z"},
        tier_overrides={"name": "Tier 1", "tier_rank": 1, "price_cents": 1000,
                        "quantity_total": 5})
    create_ticket_type(ctx["organizer"], ctx["event"], name="Tier 2", tier_rank=2,
                       price_cents=2000, quantity_total=5)
    create_ticket_type(ctx["organizer"], ctx["event"], name="Tier 3", tier_rank=3,
                       price_cents=3000, quantity_total=5)

    resp = api_client.list_ticket_types(
        ANONYMOUS_HEADERS, params={"event_id": ctx["event_id"], "limit": 2, "offset": 0})
    rows, meta = validate_paginated(resp)
    body = resp.json()
    assert body["response_type"] == "array", \
        f"A list response is an array, got {body['response_type']}"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    assert meta["total_count"] == 3, f"Expected total_count 3, got {meta['total_count']}"
    assert meta["has_more"] is True, "Records remain beyond a two-row window over three"
    assert len(rows) == 2, f"Expected the window to hold 2 rows, got {len(rows)}"


def test_omitted_optional_declarations_take_their_stated_defaults():
    """PRD §3.3: "An optional `seating_mode` chooses between `GA` — the default when
    omitted — and `RESERVED`."
    PRD §3.2: "`fee_mode` decides who bears the platform fee and takes either
    `PASS_ON` — the default when omitted — or `ABSORB`. `refund_policy` decides the
    default refund variant for the event and takes either `FEE_RETAINED` — the
    default when omitted — or `FEE_INCLUDED`."

    Design: Corner/entities/corner_ticket_type_seating_mode_defaults_to_ga
    """
    ctx = setup_marketplace(venue_overrides={"name": "Default Hall", "city": "Omaha",
                                             "seated_capacity": 60})
    event = validate_success(api_client.create_event(
        {"organizer_id": ctx["org_id"], "venue_id": ctx["venue_id"],
         "title": "Default Night", "starts_at": "2026-09-14T18:00:00Z",
         "ends_at": "2026-09-14T22:00:00Z"}, ctx["org_headers"]), 201)

    tier = validate_success(api_client.create_ticket_type(
        {"event_id": event["id"], "name": "General", "tier_rank": 1,
         "price_cents": 5000, "quantity_total": 10}, ctx["org_headers"]), 201)

    assert_ticket_type(tier)
    assert tier["seating_mode"] == "GA", f"Expected GA by default, got {tier['seating_mode']}"
    assert tier["sold_count"] == 0
    assert tier["held_count"] == 0
    assert event["fee_mode"] == "PASS_ON", \
        f"Expected PASS_ON by default, got {event['fee_mode']}"
    assert event["refund_policy"] == "FEE_RETAINED", \
        f"Expected FEE_RETAINED by default, got {event['refund_policy']}"


def test_seat_block_derives_its_total_from_the_declared_range():
    """PRD §3.3: "The block's `seats_total` is derived as `seat_to` minus `seat_from`
    plus one, and its `seats_taken` opens at zero."

    Design: Corner/entities/corner_seat_block_seats_total_is_computed_from_range
    """
    ctx = setup_draft_event(
        event_overrides={"title": "Seats Night", "starts_at": "2026-09-15T18:00:00Z",
                         "ends_at": "2026-09-15T22:00:00Z"},
        tier_overrides={"name": "Orchestra", "tier_rank": 2, "quantity_total": 8,
                        "seating_mode": "RESERVED"})

    block = validate_success(api_client.create_seat_block(
        create_seat_block_payload(ctx["tt_id"], row_label="A", seat_from=3, seat_to=10),
        ctx["org_headers"]), 201)

    assert_seat_block(block)
    assert block["seats_total"] == 8, f"Expected 8 seats in rows 3..10, got {block['seats_total']}"
    assert block["seats_taken"] == 0, "A fresh block opens with no seats occupied"


def test_promo_code_with_an_undeclared_kind_is_rejected():
    """PRD §3.3: "A code declares its `event_id`, the `code` string buyers will type
    — unique per event, with a collision rejected as `ERR_DUPLICATE_PROMO_CODE` — a
    `kind` of either `PERCENT` or `FIXED`, a `max_uses` of at least 1, and the
    `valid_from` and `valid_until` instants bounding its redemption window."
    PRD §2.8: "3. **Request shape** — required fields present, types correct, enum
    members drawn from the declared sets, integers inside their declared ranges,
    else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/corner_promo_code_invalid_enum_kind_rejected
    """
    ctx = setup_draft_event(
        event_overrides={"title": "Enum Night", "starts_at": "2026-09-16T18:00:00Z",
                         "ends_at": "2026-09-16T22:00:00Z"})

    resp = api_client.create_promo_code(
        create_promo_code_payload(ctx["event_id"], code="BAD", kind="BOGOF",
                                  percent_bp=500, max_uses=1),
        ctx["org_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_ticket_tier_against_an_unknown_event_is_not_created():
    """PRD §3.2: "An event named in a path or body that does not resolve yields
    `ERR_EVENT_NOT_FOUND`."

    Design: Corner/entities/corner_ticket_type_parent_event_missing_returns_not_found
    """
    ctx = setup_marketplace(organizer_overrides={"display_name": "Orphan Co",
                                                 "contact_email": "ops@orphan.example"})

    resp = api_client.create_ticket_type(
        create_ticket_type_payload(NON_EXISTENT_UUID), ctx["org_headers"])
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_FOUND.value, 404)


def test_duplicate_promo_code_on_the_same_event_is_rejected():
    """PRD §3.3: "A code declares its `event_id`, the `code` string buyers will type
    — unique per event, with a collision rejected as `ERR_DUPLICATE_PROMO_CODE` — a
    `kind` of either `PERCENT` or `FIXED`, a `max_uses` of at least 1, and the
    `valid_from` and `valid_until` instants bounding its redemption window."

    Design: Corner/validations/corner_duplicate_promo_code_within_event_rejected
    """
    ctx = setup_draft_event(
        event_overrides={"title": "Dup Night", "starts_at": "2026-10-10T18:00:00Z",
                         "ends_at": "2026-10-10T22:00:00Z"})
    create_promo_code(ctx["organizer"], ctx["event"], code="SAVE10", kind="PERCENT",
                      percent_bp=1000, max_uses=5)

    resp = api_client.create_promo_code(
        create_promo_code_payload(ctx["event_id"], code="SAVE10", kind="FIXED",
                                  percent_bp=0, amount_cents=300, max_uses=2),
        ctx["org_headers"])
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PROMO_CODE.value, 409)

    rows, meta = validate_paginated(api_client.list_promo_codes(
        ctx["org_headers"], params={"event_id": ctx["event_id"]}))
    assert meta["total_count"] == 1, \
        f"The collision must persist nothing, got total_count {meta['total_count']}"


def test_repricing_a_tier_never_reprices_an_existing_order():
    """PRD §3.3: "Crucially, repricing is never retroactive: every order already
    created keeps the unit price it snapshotted at creation, and no existing order's
    money is recomputed by a later tier edit."

    Design: Corner/endpoints/corner_patch_ticket_type_reprice_does_not_reprice_existing_order
    """
    ctx = setup_onsale_event(
        event_overrides={"title": "Reprice Night", "starts_at": "2026-10-15T18:00:00Z",
                         "ends_at": "2026-10-15T22:00:00Z"})
    buyer = create_buyer()
    order = create_held_order(ctx, buyer, quantity=1)
    line = order_items_of(order["id"], buyer)[0]

    repriced = validate_success(api_client.update_ticket_type(
        ctx["tt_id"], {"price_cents": 9000}, ctx["org_headers"]), 200)
    assert repriced["price_cents"] == 9000, \
        f"Expected the tier to move to 9000, got {repriced['price_cents']}"

    kept = validate_success(api_client.get_order_item(
        line["id"], ctx["org_headers"]), 200)
    assert kept["unit_price_cents"] == 5000, \
        f"The snapshotted unit price must survive the reprice, got {kept['unit_price_cents']}"
    assert kept["per_ticket_fee_cents"] == 364, \
        f"The snapshotted fee must survive the reprice, got {kept['per_ticket_fee_cents']}"

    unchanged = read_order(order["id"], buyer)
    assert unchanged["subtotal_cents"] == 5000
    assert unchanged["buyer_total_cents"] == 5364
