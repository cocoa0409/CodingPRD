"""Standing up a gala, walking the event machine, and the posture gate."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_gala_event,
    create_bid_payload,
    create_paddle_raise_payload,
    create_event_payload,
    make_bidder_headers,
    read_auction_item,
    read_event,
    read_invoice,
    register_bidder,
    setup_awarded_lot_scenario,
    setup_draft_event,
    setup_frozen_event,
    setup_published_event,
    setup_restricted_event,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
    CLOCK_STARTUP_UTC,
    BIDDER_SPECS,
)


def test_create_event_applies_declared_defaults(api):
    """PRD §3.1: "When `match_cap_cents` is omitted it defaults to 0, meaning no
    challenge match is in play; it may never be negative."
    PRD §3.1: "A new event begins with `status` of `DRAFT` and a `posture` of
    `OPEN`, and its four rollup counters — `match_awarded_cents`,
    `gross_collected_cents`, `open_lot_count` and `unpaid_invoice_count` — all
    start at 0."
    PRD §2.4: "The `version` field begins at 1 when the resource is created and
    increases by exactly 1 on every mutation of that resource, whether the
    mutation was requested directly or caused as a downstream side effect of an
    operation on some other resource; `updated_at` is refreshed on the same
    occasions."

    Design: Corner/entities/create_gala_event_applies_defaults_and_system_fields
    """
    set_clock(CLOCK_STARTUP_UTC)

    response = api.create_event(create_event_payload(), TEST_USERS["organizer_headers"])
    event = validate_success(response, 201)

    assert_gala_event(event)
    assert event["status"] == "DRAFT", f"New event must open DRAFT, got {event['status']}"
    assert event["posture"] == "OPEN", f"New event posture must be OPEN, got {event['posture']}"
    assert event["match_cap_cents"] == 0, "Omitted match_cap_cents defaults to 0"
    assert event["version"] == 1, "version begins at 1"
    assert event["match_awarded_cents"] == 0
    assert event["gross_collected_cents"] == 0
    assert event["open_lot_count"] == 0
    assert event["unpaid_invoice_count"] == 0


def test_get_event_with_unknown_id_returns_not_found(api):
    """PRD §2.4: "Each entity type has its own not-found error —
    `ERR_EVENT_NOT_FOUND`, `ERR_TABLE_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`,
    `ERR_TICKET_ORDER_NOT_FOUND`, `ERR_BIDDER_NOT_FOUND`,
    `ERR_SPONSOR_NOT_FOUND`, `ERR_AD_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`,
    `ERR_BID_NOT_FOUND`, `ERR_PADDLE_RAISE_NOT_FOUND`, `ERR_PLEDGE_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND`
    and `ERR_RUN_NOT_FOUND` — each returned with HTTP 404."

    Design: Corner/entities/get_event_with_unknown_id_returns_not_found
    """
    set_clock(CLOCK_STARTUP_UTC)

    response = api.get_event(NON_EXISTENT_UUID, TEST_USERS["organizer_headers"])

    validate_error(response, ApiErrorId.ERR_EVENT_NOT_FOUND.value, 404)


def test_register_bidder_without_paddle_number_is_rejected(api):
    """PRD §3.3: "An `EventOrganizer` registers a `Bidder` against an event by
    supplying `event_id`, the `display_name` printed on the bid sheet, a
    contact `email` for receipts, and a `paddle_number` of at least 1 that must
    be unique among the guests of that event — a collision is refused with
    `ERR_DUPLICATE_PADDLE_NUMBER`."
    PRD §2.5: "Request shape: required fields present, enum members drawn from
    the declared sets, integers respecting their non-negativity constraints,
    `limit` inside 1 through 100, `offset` at least 0, a hold's `hold_end_utc`
    strictly later than its `hold_start_utc`, and a lot's `close_at_utc`
    strictly later than its `open_at_utc`. Any violation is
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_bidder_missing_required_paddle_number_returns_invalid_request
    """
    event = setup_draft_event(clock=CLOCK_STARTUP_UTC)

    response = api.create_bidder(
        {
            "event_id": event["id"],
            "display_name": "Ada Lovelace",
            "email": "ada@example.org",
        },
        TEST_USERS["organizer_headers"],
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_list_bidders_returns_paginated_envelope(api):
    """PRD §2.3: "Lists are returned sorted by `created_at` in ascending order,
    so the oldest record appears first."
    PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` (the number of records matching the filter before the page
    window is applied), and `has_more` (true when records remain beyond the
    current window)."
    PRD §3.3: "The optional `payment_method_on_file` flag defaults to false and
    records whether a card is stored; a guest or an organizer may later flip it
    either way by submitting a new `payment_method_on_file` value, which
    advances the guest's `version`."

    Design: Corner/entities/list_bidders_returns_paginated_envelope
    """
    event = setup_draft_event(clock=CLOCK_STARTUP_UTC)
    guest_a = register_bidder(event["id"], **BIDDER_SPECS[0])
    guest_b = register_bidder(event["id"], **BIDDER_SPECS[1])

    response = api.list_bidders(
        TEST_USERS["organizer_headers"],
        params={"event_id": event["id"], "limit": 1, "offset": 0},
    )
    rows, meta = validate_paginated(response)

    assert meta["total_count"] == 2, f"Two guests registered, meta says {meta['total_count']}"
    assert meta["has_more"] is True, "A one-row window over two rows leaves more"
    assert len(rows) == 1, f"limit=1 must return one row, got {len(rows)}"
    assert rows[0]["id"] == guest_a["id"], "Oldest guest appears first"
    assert guest_b["payment_method_on_file"] is False, (
        "payment_method_on_file defaults to false when omitted"
    )


def test_publish_event_twice_returns_invalid_state(api):
    """PRD §3.1: "Publication, taking the event `DRAFT → PUBLISHED`, requires
    that the event currently sit in `DRAFT` and that at least one ticket table
    already exist for it — a gala with no tables is not sellable."
    PRD §2.5: "The target resource is in a state from which the requested
    transition is declared, else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/publish_event_twice_returns_invalid_state
    """
    env = setup_published_event(clock=CLOCK_STARTUP_UTC, bidder_count=0)

    response = api.publish_event(env["event"]["id"], TEST_USERS["organizer_headers"])

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert read_event(env["event"]["id"])["status"] == "PUBLISHED"


def test_publish_event_without_any_table_is_rejected(api):
    """PRD §3.1: "Publication, taking the event `DRAFT → PUBLISHED`, requires
    that the event currently sit in `DRAFT` and that at least one ticket table
    already exist for it — a gala with no tables is not sellable."
    PRD §2.5: "The target resource is in a state from which the requested
    transition is declared, else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/publish_event_without_any_table_is_rejected
    """
    event = setup_draft_event(clock=CLOCK_STARTUP_UTC)

    response = api.publish_event(event["id"], TEST_USERS["organizer_headers"])

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert read_event(event["id"])["status"] == "DRAFT", (
        "A refused publication leaves the event in DRAFT"
    )


def test_list_events_with_limit_zero_is_rejected(api):
    """PRD §2.3: "The `limit` parameter defaults to 10 when omitted, may be no
    smaller than 1 and no larger than 100; the `offset` parameter defaults to 0
    and may not be negative. A `limit` outside the inclusive range of 1 through
    100, or a negative `offset`, is a malformed request and is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/endpoints/list_events_with_invalid_request_limit_zero_is_rejected
    """
    setup_draft_event(clock=CLOCK_STARTUP_UTC)

    response = api.list_events(TEST_USERS["organizer_headers"], params={"limit": 0})

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_request_without_auth_headers_is_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of
    those five strings, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/request_missing_auth_headers_returns_unauthenticated
    """
    set_clock(CLOCK_STARTUP_UTC)

    response = api.list_events({})

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_auction_manager_cannot_finalize_an_invoice(api):
    """PRD §2.1: "If the headers are well-formed but the acting role is not
    among the roles authorized for the requested endpoint (see the table in
    §4), the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.7: "Finalization is a `FinanceOfficer` action that closes the
    guest's tab."

    Design: Corner/rbac/auction_manager_cannot_finalize_an_invoice
    """
    env = setup_awarded_lot_scenario()

    response = api.finalize_invoice(
        env["invoice_id"], TEST_USERS["auction_manager_headers"]
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    assert read_invoice(env["invoice_id"])["status"] == "OPEN", (
        "A forbidden finalize leaves the invoice OPEN"
    )


def test_paddle_raise_on_frozen_event_is_rejected(api):
    """PRD §2.6: "Otherwise, if the event has at least one reconciliation run
    whose `status` is `FINALIZED`, the posture is `FROZEN` — runs in
    `SUPERSEDED` or `PREPARED` are ignored for this purpose."
    PRD §2.6: "A `FROZEN` posture rejects every mutating operation on a child of
    that event with `ERR_EVENT_FROZEN` (HTTP 409), with two carve-outs: the
    five event lifecycle transitions (publish, unpublish, go-live, start
    settlement, close) remain available, and so do the three
    reconciliation-run operations (preparing a run, finalizing it, and
    reopening it) — otherwise a frozen event could never be reopened."

    Design: Corner/errors/error_event_frozen_after_run_finalized
    """
    env = setup_frozen_event(match_cap_cents=500_000)
    guest = env["bidders"][0]

    response = api.create_paddle_raise(
        create_paddle_raise_payload(env["event"]["id"], guest["id"], 100_000),
        TEST_USERS["auction_manager_headers"],
    )

    validate_error(response, ApiErrorId.ERR_EVENT_FROZEN.value, 409)
    event = read_event(env["event"]["id"])
    assert event["posture"] == "FROZEN", f"Posture must be FROZEN, got {event['posture']}"
    assert event["match_awarded_cents"] == 0, "A refused gift awards no match"


def test_bid_on_settling_event_is_rejected_as_restricted(api):
    """PRD §2.6: "It rejects exactly six creation operations with
    `ERR_EVENT_RESTRICTED` (HTTP 409): placing a table hold, creating a ticket
    order, creating an auction lot, opening an auction lot, placing a bid, and
    recording a paddle-raise gift."
    PRD §3.1: "The transition recomputes posture, which becomes `RESTRICTED`,
    and advances the event's `version`."

    Design: Difficulty/cross_entity_state_dependency/bid_rejected_because_event_posture_is_restricted
    """
    env = setup_restricted_event()
    guest = env["bidders"][0]

    response = api.place_bid(
        env["lot"]["id"],
        create_bid_payload(guest["id"], 20_000),
        make_bidder_headers(guest["id"]),
    )

    validate_error(response, ApiErrorId.ERR_EVENT_RESTRICTED.value, 409)


def test_start_settlement_sets_restricted_posture_after_lots_close(api):
    """PRD §3.1: "Starting settlement takes the event `LIVE → SETTLING`. Beyond
    requiring the event to be in `LIVE`, it requires that no lot remain open:
    `open_lot_count` must be exactly 0, and otherwise the request is refused
    with `ERR_OPEN_LOTS_REMAIN`."
    PRD §3.5: "If instead no bid on the lot is `ACTIVE` at close, the lot goes
    `OPEN → PASSED` and the side-effect set is deliberately different:
    `hammer_price_cents` stays null, `settlement_status` stays `UNSETTLED`, and
    no invoice anywhere is created or modified."

    Design: Difficulty/cross_entity_state_dependency/bid_rejected_because_event_posture_is_restricted
    """
    env = setup_restricted_event()

    event = read_event(env["event"]["id"])
    assert event["status"] == "SETTLING"
    assert event["posture"] == "RESTRICTED", (
        f"A SETTLING event's posture is RESTRICTED, got {event['posture']}"
    )
    assert event["open_lot_count"] == 0

    lot = read_auction_item(env["lot"]["id"])
    assert lot["listing_status"] == "PASSED", (
        "The unbid lot that go-live opened must close as PASSED"
    )
