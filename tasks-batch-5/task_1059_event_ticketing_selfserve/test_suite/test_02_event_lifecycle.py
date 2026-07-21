"""The event lifecycle: publishing, pausing, closing sales and completing."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    setup_draft_event, setup_onsale_event, setup_reserved_onsale_event,
    setup_marketplace, create_event, create_organizer, create_ticket_type, create_buyer,
    create_held_order, set_clock, close_sales, read_event, read_seat_block,
    read_ticket_type, read_order, make_organizer_headers, make_buyer_headers,
)


def test_publish_without_a_ticket_tier_is_an_invalid_transition():
    """PRD §3.2: "Publishing carries the event from `DRAFT` to `ONSALE`. It is
    permitted only while the event is in `DRAFT`, only when at least one ticket tier
    already exists on the event, and only while `starts_at` remains strictly in the
    future; a publish attempted from any other status, or with no tier declared, is
    rejected with `ERR_INVALID_EVENT_TRANSITION`, while a start instant that has
    already passed yields `ERR_EVENT_START_IN_PAST`."

    Design: Corner/state_machines/corner_publish_without_ticket_type_returns_invalid_event_transition
    """
    ctx = setup_draft_event(
        event_overrides={"title": "NoTier Night", "starts_at": "2026-09-20T18:00:00Z",
                         "ends_at": "2026-09-20T22:00:00Z"},
        with_tier=False)

    resp = api_client.publish_event(ctx["event_id"], ctx["org_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_EVENT_TRANSITION.value, 409)

    event = read_event(ctx["event_id"])
    assert event["status"] == "DRAFT", f"Expected DRAFT, got {event['status']}"
    assert event["version"] == 1, \
        f"A rejected publish must not advance version, got {event['version']}"


def test_pause_from_draft_is_an_invalid_transition():
    """PRD §3.2: "Pausing takes an event from `ONSALE` to `PAUSED` and requires the
    event to be `ONSALE`; resuming takes it from `PAUSED` back to `ONSALE`, requires
    the event to be `PAUSED`, and re-checks that `starts_at` is still strictly in the
    future, rejecting with `ERR_EVENT_START_IN_PAST` if the show has since begun."
    PRD §3.2: "`COMPLETED` and `CANCELLED` are terminal: no transition leaves either,
    and any attempt reports `ERR_INVALID_EVENT_TRANSITION`."

    Design: Corner/state_machines/corner_pause_from_draft_is_an_invalid_transition
    """
    ctx = setup_draft_event(
        event_overrides={"title": "Pause Night", "starts_at": "2026-09-21T18:00:00Z",
                         "ends_at": "2026-09-21T22:00:00Z"})

    resp = api_client.pause_event(ctx["event_id"], ctx["org_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_EVENT_TRANSITION.value, 409)
    assert read_event(ctx["event_id"])["status"] == "DRAFT"


def test_completed_event_rejects_a_later_cancellation():
    """PRD §3.2: "`COMPLETED` and `CANCELLED` are terminal: no transition leaves
    either, and any attempt reports `ERR_INVALID_EVENT_TRANSITION`."

    Design: Corner/state_machines/corner_completed_event_rejects_further_transitions
    """
    ctx = setup_onsale_event(
        event_overrides={"title": "Terminal Night", "starts_at": "2026-08-01T18:00:00Z",
                         "ends_at": "2026-08-01T22:00:00Z"})
    close_sales(ctx)
    set_clock("2026-08-02T00:00:00Z")
    validate_success(api_client.complete_event(ctx["event_id"], ctx["org_headers"]), 200)

    resp = api_client.cancel_event(ctx["event_id"], ctx["org_headers"],
                                   {"reason": "too late"})
    validate_error(resp, ApiErrorId.ERR_INVALID_EVENT_TRANSITION.value, 409)
    assert read_event(ctx["event_id"])["status"] == "COMPLETED"


def test_complete_before_the_show_has_ended_is_rejected():
    """PRD §3.2: "Completion requires the event to be in `SALES_CLOSED` — otherwise
    `ERR_INVALID_EVENT_TRANSITION` — and requires that `ends_at` is at or before the
    current time, so an attempt to complete a show that has not yet finished is
    rejected with `ERR_EVENT_NOT_ENDED`."

    Design: Corner/errors/corner_complete_before_event_end_returns_event_not_ended
    """
    ctx = setup_onsale_event(
        event_overrides={"title": "Notend Night", "starts_at": "2026-10-18T18:00:00Z",
                         "ends_at": "2026-10-18T22:00:00Z"})
    close_sales(ctx)

    resp = api_client.complete_event(ctx["event_id"], ctx["org_headers"])
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_ENDED.value, 409)
    assert read_event(ctx["event_id"])["status"] == "SALES_CLOSED"


def test_closing_sales_expires_live_holds_and_gives_the_seats_back():
    """PRD §3.2: "It also sweeps the floor: every order on the event still in `HELD`
    fulfilment is moved to `EXPIRED` fulfilment and its held seats are given back,
    decrementing the affected seat blocks' occupied-seat counts by the number of
    seats released and recomputing each affected tier's held quantity."

    Design: Corner/state_machines/corner_close_sales_expires_live_holds_and_frees_seats
    """
    ctx = setup_reserved_onsale_event(
        event_overrides={"title": "Sweep Night", "starts_at": "2026-09-23T18:00:00Z",
                         "ends_at": "2026-09-23T22:00:00Z"})
    buyer = create_buyer()
    order = create_held_order(ctx, buyer, quantity=2, seat_numbers=[1, 2])
    assert read_seat_block(ctx["sb_id"])["seats_taken"] == 2, \
        "The live hold should occupy both seats before sales close"

    validate_success(api_client.close_event_sales(ctx["event_id"], ctx["org_headers"]), 200)

    assert read_event(ctx["event_id"])["status"] == "SALES_CLOSED"
    swept = read_order(order["id"], buyer)
    assert swept["fulfillment_status"] == "EXPIRED", \
        f"Expected EXPIRED fulfilment, got {swept['fulfillment_status']}"
    assert swept["payment_status"] == "PENDING", \
        f"Closing sales touches fulfilment only, got {swept['payment_status']}"
    assert read_seat_block(ctx["sb_id"])["seats_taken"] == 0, \
        "Released seats must be given back to the block"
    assert read_ticket_type(ctx["tt_id"])["held_count"] == 0, \
        "The tier's held quantity must be recomputed after the sweep"


def test_buyer_cannot_publish_an_event():
    """PRD §2.8: "2. **Role authorisation** — the acting role appears in the
    endpoint's permitted list, else `ERR_UNAUTHORIZED`."
    PRD §2.1: "Once authenticated, if the acting role is not among the roles the
    target endpoint permits, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/corner_buyer_cannot_publish_an_event
    """
    ctx = setup_draft_event(
        event_overrides={"title": "Rbac Night", "starts_at": "2026-10-19T18:00:00Z",
                         "ends_at": "2026-10-19T22:00:00Z"})
    buyer = create_buyer(email="ida@example.com", display_name="Ida")

    resp = api_client.publish_event(ctx["event_id"], make_buyer_headers(buyer["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert read_event(ctx["event_id"])["status"] == "DRAFT"


def test_organizer_cannot_cancel_another_organizers_event():
    """PRD §2.1: "When `X-User-Role` is `Organizer`, `X-User-ID` is the `id` of the
    acting `Organizer` record; ownership checks on any resource that references an
    `Organizer` compare the resource's foreign-key field to `X-User-ID`."
    PRD §2.1: "An ownership failure on any organiser-scoped or buyer-scoped mutating
    endpoint is also reported as `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/corner_organizer_cannot_cancel_another_organizers_event
    """
    ctx = setup_marketplace(organizer_overrides={"display_name": "Owner One",
                                                 "contact_email": "one@own.example"},
                            venue_overrides={"name": "Own Hall", "city": "Lincoln",
                                             "seated_capacity": 60})
    intruder = create_organizer(display_name="Owner Two", contact_email="two@own.example")
    event = create_event(ctx["organizer"], ctx["venue"], title="Own Night",
                         starts_at="2026-10-21T18:00:00Z",
                         ends_at="2026-10-21T22:00:00Z")

    resp = api_client.cancel_event(event["id"], make_organizer_headers(intruder["id"]),
                                   {"reason": "not mine"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert read_event(event["id"])["status"] == "DRAFT"
