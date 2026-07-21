"""When one request breaks several rules at once, which failure is reported."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_scan_payload, order_item_payload,
    setup_marketplace, setup_onsale_event, setup_paid_order,
    create_event, create_ticket_type, create_venue, create_buyer, publish_event,
    place_order, set_clock, void_attendee, read_attendee,
)

GATE = TEST_USERS["gate_staff_headers"]


def _paused_event_with_a_single_seat():
    """A PAUSED event whose only tier has one seat left, so a two-ticket request
    breaks the state gate and the capacity gate at the same time."""
    ctx = setup_onsale_event(
        event_overrides={"title": "Priority Night", "starts_at": "2026-08-15T18:00:00Z",
                         "ends_at": "2026-08-15T22:00:00Z"},
        tier_overrides={"quantity_total": 1})
    ctx["paused"] = validate_success(
        api_client.pause_event(ctx["event_id"], ctx["org_headers"]), 200)
    return ctx


def test_paused_event_outranks_the_capacity_shortfall():
    """PRD §2.8: "When a single request could fail several checks at once, the checks
    run in a fixed order and the first failure is the one reported."
    PRD §3.4: "When several of these guards could fire on one checkout, they resolve
    in the precedence of §2.8: the event-state gate first, then referential parentage,
    then seat occupancy and seat-range shape, then the per-buyer ticket limit, then
    the uniqueness family, then capacity — sold-out before insufficient-capacity —
    then the promotional gates in the order eligibility floor, redemption budget, and
    finally the expected-event-version guard last of all."

    Design: Difficulty/priority_pair_validation_conflict/paused_event_outranks_insufficient_capacity_on_order_create
    """
    ctx = _paused_event_with_a_single_seat()
    buyer = create_buyer(email="jan@example.com", display_name="Jan")

    # One seat remains but two are requested, so the capacity gate would fire too.
    resp = place_order(ctx, buyer, [order_item_payload(ctx["tt_id"], 2)],
                       expected_event_version=ctx["paused"]["version"])

    error = validate_error(resp, ApiErrorId.ERR_EVENT_NOT_ONSALE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_INSUFFICIENT_CAPACITY.value, \
        "The state gate is evaluated before the fiscal capacity gate"


def test_order_rejected_on_a_paused_event_persists_nothing():
    """PRD §3.4: "Selling is only open while the event is `ONSALE`; an order attempted
    against an event in any other status is rejected with `ERR_EVENT_NOT_ONSALE`."
    PRD §2.8: "When a single request could fail several checks at once, the checks run
    in a fixed order and the first failure is the one reported."

    Design: Difficulty/priority_pair_validation_conflict/paused_event_outranks_insufficient_capacity_on_order_create
    """
    ctx = _paused_event_with_a_single_seat()
    buyer = create_buyer(email="jan2@example.com", display_name="Jan Two")

    validate_error(
        place_order(ctx, buyer, [order_item_payload(ctx["tt_id"], 2)],
                    expected_event_version=ctx["paused"]["version"]),
        ApiErrorId.ERR_EVENT_NOT_ONSALE.value, 409)

    rows, meta = validate_paginated(api_client.list_orders(
        ctx["org_headers"], params={"event_id": ctx["event_id"]}))
    assert meta["total_count"] == 0, \
        f"A rejected checkout leaves no order behind, got total_count {meta['total_count']}"


def _voided_admission_scanned_at_the_wrong_gate():
    """One organiser runs two shows at two venues; a voided admission for the first
    show is presented at the second show's gate, inside that show's check-in window."""
    ctx = setup_marketplace(organizer_overrides={"display_name": "Twin Gate Co",
                                                 "contact_email": "ops@twingate.example"},
                            venue_overrides={"name": "Gate A Hall", "city": "Phoenix",
                                             "seated_capacity": 100})
    venue_b = create_venue(name="Gate B Hall", city="Phoenix", seated_capacity=100)
    set_clock("2026-07-05T10:00:00Z")

    event_a = create_event(ctx["organizer"], ctx["venue"], title="Gate A Night",
                           starts_at="2026-08-12T18:00:00Z", ends_at="2026-08-12T22:00:00Z")
    event_b = create_event(ctx["organizer"], venue_b, title="Gate B Night",
                           starts_at="2026-08-20T18:00:00Z", ends_at="2026-08-20T22:00:00Z")
    tier_a = create_ticket_type(ctx["organizer"], event_a)
    create_ticket_type(ctx["organizer"], event_b)
    publish_event(ctx["organizer"], event_a)
    publish_event(ctx["organizer"], event_b)

    ctx["event_id"] = event_a["id"]
    ctx["tt_id"] = tier_a["id"]
    ctx["sb_id"] = None
    paid = setup_paid_order(ctx, buyer=create_buyer(email="kim@example.com",
                                                    display_name="Kim"), quantity=1)
    admission_id = paid["attendees"][0]["id"]
    void_attendee(ctx, admission_id, reason="duplicate purchase")

    # Inside the second show's check-in window, which opens at 16:00.
    set_clock("2026-08-20T17:00:00Z")
    ctx["event_b_id"] = event_b["id"]
    ctx["admission_id"] = admission_id
    return ctx


def test_wrong_gate_event_outranks_the_voided_ticket_guard():
    """PRD §2.8: "8. **Referential** — cross-entity parentage matches."
    PRD §2.8: "9. **Safety** — void, already-checked-in and segregation-of-duties
    guards."
    PRD §3.5: "a mismatch between the admission's event and the gate's event is
    rejected with `ERR_ATTENDEE_EVENT_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/attendee_event_mismatch_outranks_voided_ticket_on_scan
    """
    ctx = _voided_admission_scanned_at_the_wrong_gate()
    assert read_attendee(ctx["admission_id"])["status"] == "VOIDED"

    resp = api_client.create_scan(
        create_scan_payload(ctx["admission_id"], ctx["event_b_id"], "GATE-B1"), GATE)

    error = validate_error(resp, ApiErrorId.ERR_ATTENDEE_EVENT_MISMATCH.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_TICKET_VOIDED.value, \
        "The referential check is evaluated before the safety guard"


def test_scan_rejected_for_event_mismatch_writes_no_record():
    """PRD §3.5: "An accepted scan moves the admission from `ISSUED` — or from
    `TRANSFERRED` — to `CHECKED_IN`, stamps its `checked_in_at` with the current time,
    and writes an immutable scan record capturing `attendee_id`, `event_id`,
    `gate_code`, the `scanned_at` instant, and the `scanned_by_user_id` of the
    operator who performed it."
    PRD §2.8: "When a single request could fail several checks at once, the checks run
    in a fixed order and the first failure is the one reported."

    Design: Difficulty/priority_pair_validation_conflict/attendee_event_mismatch_outranks_voided_ticket_on_scan
    """
    ctx = _voided_admission_scanned_at_the_wrong_gate()

    validate_error(api_client.create_scan(
        create_scan_payload(ctx["admission_id"], ctx["event_b_id"], "GATE-B1"), GATE),
        ApiErrorId.ERR_ATTENDEE_EVENT_MISMATCH.value, 422)

    rows, meta = validate_paginated(api_client.list_scans(
        GATE, params={"attendee_id": ctx["admission_id"]}))
    assert meta["total_count"] == 0, \
        f"A rejected scan writes no audit record, got total_count {meta['total_count']}"
