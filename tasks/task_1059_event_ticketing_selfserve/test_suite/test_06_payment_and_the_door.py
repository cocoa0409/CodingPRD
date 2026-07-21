"""Capturing payment, minting admissions and working the gate."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, GATE_USER_ID, GATE_USER_ID_2, TEST_USERS,
    assert_scan_record, assert_attendee, assert_three_fractional_digits,
    create_scan_payload,
    setup_onsale_event, setup_reserved_onsale_event, setup_paid_order,
    create_buyer, create_held_order, set_clock, scan_attendee,
    read_event, read_order, read_attendee, read_ticket_type, read_seat_block,
    read_organizer, attendees_of, make_buyer_headers, make_gate_staff_headers,
)

GATE = TEST_USERS["gate_staff_headers"]


def _event_with_two_paid_admissions(title="Axis Night"):
    """ONSALE evening show with one paid two-ticket order and the clock inside
    the check-in window, which opens at 16:00 for an 18:00 start."""
    ctx = setup_onsale_event(
        event_overrides={"title": title, "starts_at": "2026-08-01T18:00:00Z",
                         "ends_at": "2026-08-01T22:00:00Z"})
    ctx["paid"] = setup_paid_order(ctx, quantity=2)
    set_clock("2026-08-01T17:00:00Z")
    return ctx


# ---------------------------------------------------------------------------
# The order's two dimensions advance independently
# ---------------------------------------------------------------------------

def test_scanning_one_admission_moves_fulfilment_but_not_payment():
    """PRD §3.5: "an order moves from `ISSUED` to `CHECKED_IN_PARTIAL` when at least
    one of its admissions is `CHECKED_IN` while at least one remains `ISSUED`, and
    from `CHECKED_IN_PARTIAL` to `CHECKED_IN_FULL` when every one of its non-voided
    admissions is `CHECKED_IN`."
    PRD §3.5: "Paying carries an order's payment dimension from `PENDING` to `PAID`
    and, on the very same call, its fulfilment dimension from `HELD` to `ISSUED`."

    Design: Difficulty/non_linear_state_machine/order_payment_and_fulfillment_dimensions_advance_independently
    """
    ctx = _event_with_two_paid_admissions()
    first_admission = ctx["paid"]["attendees"][0]

    scan_attendee(first_admission["id"], ctx["event_id"])

    order = read_order(ctx["paid"]["order_id"], ctx["paid"]["buyer"])
    assert order["payment_status"] == "PAID", (
        "The payment dimension is untouched by a scan, got "
        f"{order['payment_status']}")
    assert order["fulfillment_status"] == "CHECKED_IN_PARTIAL", (
        "One of two admissions scanned leaves the order partially checked in, got "
        f"{order['fulfillment_status']}")


def test_partial_check_in_stamps_the_admission_and_lifts_the_event_counts():
    """PRD §3.5: "An accepted scan moves the admission from `ISSUED` — or from
    `TRANSFERRED` — to `CHECKED_IN`, stamps its `checked_in_at` with the current time,
    and writes an immutable scan record capturing `attendee_id`, `event_id`,
    `gate_code`, the `scanned_at` instant, and the `scanned_by_user_id` of the
    operator who performed it."
    PRD §3.5: "The event's `checked_in_count` is recomputed."

    Design: Difficulty/non_linear_state_machine/order_payment_and_fulfillment_dimensions_advance_independently
    """
    ctx = _event_with_two_paid_admissions()
    first_admission = ctx["paid"]["attendees"][0]

    scan_attendee(first_admission["id"], ctx["event_id"])

    admission = read_attendee(first_admission["id"])
    assert_attendee(admission)
    assert admission["status"] == "CHECKED_IN"
    assert admission["checked_in_at"].startswith("2026-08-01T17:00:00"), (
        "checked_in_at is stamped with the current logical instant, got "
        f"{admission['checked_in_at']}")
    assert_three_fractional_digits(admission["checked_in_at"], "checked_in_at")

    event = read_event(ctx["event_id"])
    assert event["checked_in_count"] == 1, \
        f"Expected one admission through the door, got {event['checked_in_count']}"
    assert event["issued_count"] == 2, \
        f"Both admissions remain issued for the event, got {event['issued_count']}"


# ---------------------------------------------------------------------------
# Payment preconditions
# ---------------------------------------------------------------------------

def test_second_payment_on_the_same_order_is_rejected():
    """PRD §3.5: "Four preconditions guard it: the order's `payment_status` must be
    `PENDING` and its `fulfillment_status` must be `HELD` — a violation of either is
    `ERR_ORDER_NOT_HELD` — the current time must be strictly before
    `hold_expires_at`, else `ERR_HOLD_EXPIRED`, and the order's event must still be
    `ONSALE`, else `ERR_EVENT_NOT_ONSALE`."

    Design: Corner/state_machines/corner_second_pay_on_same_order_returns_order_not_held
    """
    ctx = setup_onsale_event(
        event_overrides={"title": "Once Night", "starts_at": "2026-09-22T18:00:00Z",
                         "ends_at": "2026-09-22T22:00:00Z"})
    paid = setup_paid_order(ctx, buyer=create_buyer(email="zed@example.com",
                                                    display_name="Zed"), quantity=1)

    resp = api_client.pay_order(paid["order_id"], paid["buyer_headers"])
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_HELD.value, 409)

    rows, meta = validate_paginated(api_client.list_attendees(
        paid["buyer_headers"], params={"order_id": paid["order_id"]}))
    assert meta["total_count"] == 1, \
        f"A refused second payment mints no extra admission, got {meta['total_count']}"
    assert read_ticket_type(ctx["tt_id"])["sold_count"] == 1


def test_payment_after_the_hold_has_lapsed_is_rejected():
    """PRD §3.5: "the current time must be strictly before `hold_expires_at`, else
    `ERR_HOLD_EXPIRED`"
    PRD §3.4: "The `hold_expires_at` deadline is set to fifteen minutes after the
    current time, and the hold is live for as long as the current time is strictly
    before that instant."

    Design: Corner/errors/corner_pay_after_hold_expiry_returns_hold_expired
    """
    ctx = setup_onsale_event(
        clock="2026-07-05T10:00:00Z",
        event_overrides={"title": "Lapse Night", "starts_at": "2026-10-17T18:00:00Z",
                         "ends_at": "2026-10-17T22:00:00Z"})
    buyer = create_buyer(email="gia@example.com", display_name="Gia")
    order = create_held_order(ctx, buyer, quantity=1)

    set_clock("2026-07-05T10:16:00Z")

    resp = api_client.pay_order(order["id"], make_buyer_headers(buyer["id"]))
    validate_error(resp, ApiErrorId.ERR_HOLD_EXPIRED.value, 409)

    assert read_order(order["id"], buyer)["payment_status"] == "PENDING"
    rows, meta = validate_paginated(api_client.list_attendees(
        make_buyer_headers(buyer["id"]), params={"order_id": order["id"]}))
    assert meta["total_count"] == 0, \
        f"A refused payment mints no admissions, got {meta['total_count']}"
    assert read_ticket_type(ctx["tt_id"])["sold_count"] == 0


def test_payment_response_already_reflects_every_side_effect():
    """PRD §3.5: "Paying carries an order's payment dimension from `PENDING` to
    `PAID` and, on the very same call, its fulfilment dimension from `HELD` to
    `ISSUED`."
    PRD §3.5: "The organiser's `lifetime_gross_cents` rises by the order's
    `organizer_gross_cents` and the organiser's `version` rises by 1. The event's
    `gross_cents` and `issued_count` are recomputed."

    Design: Corner/consistency_model/corner_pay_response_reflects_every_side_effect_immediately
    """
    ctx = setup_onsale_event(
        event_overrides={"title": "Immediate Night", "starts_at": "2026-10-25T18:00:00Z",
                         "ends_at": "2026-10-25T22:00:00Z"})
    buyer = create_buyer(email="quill@example.com", display_name="Quill")
    order = create_held_order(ctx, buyer, quantity=2)

    paid = validate_success(
        api_client.pay_order(order["id"], make_buyer_headers(buyer["id"])), 200)
    assert paid["payment_status"] == "PAID", \
        f"The pay response itself shows PAID, got {paid['payment_status']}"
    assert paid["fulfillment_status"] == "ISSUED", \
        f"The pay response itself shows ISSUED, got {paid['fulfillment_status']}"

    tier = read_ticket_type(ctx["tt_id"])
    assert tier["sold_count"] == 2
    assert tier["held_count"] == 0, \
        f"The hold is consumed by the payment, got held_count {tier['held_count']}"

    event = read_event(ctx["event_id"])
    assert event["issued_count"] == 2
    assert event["gross_cents"] == 10000

    assert read_organizer(ctx["org_id"])["lifetime_gross_cents"] == 10000

    rows, meta = validate_paginated(api_client.list_attendees(
        make_buyer_headers(buyer["id"]), params={"order_id": order["id"]}))
    assert meta["total_count"] == 2, \
        f"One admission is minted per ticket, got {meta['total_count']}"


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

def test_accepted_scan_writes_an_append_only_audit_record():
    """PRD §2.4: "The scan record produced by a gate operator is an append-only audit
    fact: it carries `id` and `created_at` only. It has no `updated_at` and no
    `version`, because it is never modified after it is written."
    PRD §3.5: "An accepted scan moves the admission from `ISSUED` — or from
    `TRANSFERRED` — to `CHECKED_IN`, stamps its `checked_in_at` with the current time,
    and writes an immutable scan record capturing `attendee_id`, `event_id`,
    `gate_code`, the `scanned_at` instant, and the `scanned_by_user_id` of the
    operator who performed it."

    Design: Corner/entities/corner_scan_record_is_append_only_event_log
    """
    ctx = setup_onsale_event(
        event_overrides={"title": "Append Night", "starts_at": "2026-08-01T18:00:00Z",
                         "ends_at": "2026-08-01T22:00:00Z"})
    paid = setup_paid_order(ctx, buyer=create_buyer(email="vic@example.com",
                                                    display_name="Vic"), quantity=1)
    set_clock("2026-08-01T17:00:00Z")
    admission_id = paid["attendees"][0]["id"]

    resp = api_client.create_scan(
        create_scan_payload(admission_id, ctx["event_id"], "GATE-A"), GATE)
    record = validate_success(resp, 201)

    assert_scan_record(record)
    assert record["scanned_at"].startswith("2026-08-01T17:00:00"), \
        f"scanned_at records the current logical instant, got {record['scanned_at']}"
    assert record["scanned_by_user_id"] == GATE_USER_ID, (
        "The acting gate operator's identifier is recorded, got "
        f"{record['scanned_by_user_id']}")
    assert record["gate_code"] == "GATE-A"

    rows, meta = validate_paginated(api_client.list_scans(
        GATE, params={"attendee_id": admission_id}))
    assert meta["total_count"] == 1


def test_scan_one_minute_before_the_window_opens_is_rejected():
    """PRD §3.5: "That window opens two hours before the event's `starts_at` and
    closes one hour after its `ends_at`, and both bounds are inclusive, so a scan
    landing exactly on either boundary instant is accepted. A scan outside it is
    rejected with `ERR_CHECKIN_WINDOW_CLOSED`."

    Design: Corner/validations/corner_scan_before_window_opens_returns_checkin_window_closed
    """
    ctx = setup_onsale_event(
        event_overrides={"title": "Early Night", "starts_at": "2026-08-01T18:00:00Z",
                         "ends_at": "2026-08-01T22:00:00Z"})
    paid = setup_paid_order(ctx, buyer=create_buyer(email="sig@example.com",
                                                    display_name="Sig"), quantity=1)
    admission_id = paid["attendees"][0]["id"]

    # The window opens at 16:00; one minute earlier is outside it.
    set_clock("2026-08-01T15:59:00Z")

    resp = api_client.create_scan(
        create_scan_payload(admission_id, ctx["event_id"], "GATE-A"), GATE)
    validate_error(resp, ApiErrorId.ERR_CHECKIN_WINDOW_CLOSED.value, 409)

    assert read_attendee(admission_id)["status"] == "ISSUED"
    rows, meta = validate_paginated(api_client.list_scans(
        GATE, params={"attendee_id": admission_id}))
    assert meta["total_count"] == 0, \
        f"A refused scan writes no record, got {meta['total_count']}"


def test_rescanning_a_checked_in_admission_is_rejected():
    """PRD §3.5: "a second scan of an admission already in `CHECKED_IN` is rejected
    with `ERR_ALREADY_CHECKED_IN`"

    Design: Corner/errors/corner_second_scan_of_same_admission_returns_already_checked_in
    """
    ctx = setup_onsale_event(
        event_overrides={"title": "Rescan Night", "starts_at": "2026-08-01T18:00:00Z",
                         "ends_at": "2026-08-01T22:00:00Z"})
    paid = setup_paid_order(ctx, buyer=create_buyer(email="hux@example.com",
                                                    display_name="Hux"), quantity=1)
    set_clock("2026-08-01T17:00:00Z")
    admission_id = paid["attendees"][0]["id"]
    scan_attendee(admission_id, ctx["event_id"])

    resp = api_client.create_scan(
        create_scan_payload(admission_id, ctx["event_id"], "GATE-B"),
        make_gate_staff_headers(GATE_USER_ID_2))
    validate_error(resp, ApiErrorId.ERR_ALREADY_CHECKED_IN.value, 409)

    rows, meta = validate_paginated(api_client.list_scans(
        GATE, params={"attendee_id": admission_id}))
    assert meta["total_count"] == 1, \
        f"The refused rescan writes no second record, got {meta['total_count']}"
    assert read_event(ctx["event_id"])["checked_in_count"] == 1


def test_undoing_a_check_in_returns_the_admission_to_issued():
    """PRD §3.5: "Undoing a check-in returns an admission from `CHECKED_IN` to
    `ISSUED` and is permitted only from `CHECKED_IN`, else `ERR_ATTENDEE_NOT_ISSUED`.
    It clears `checked_in_at` back to null, recomputes the event's `checked_in_count`,
    and re-derives the owning order's fulfilment in the opposite direction: from
    `CHECKED_IN_FULL` back to `CHECKED_IN_PARTIAL` when, after the undo, at least one
    admission is `ISSUED` and at least one remains `CHECKED_IN`, and from
    `CHECKED_IN_PARTIAL` back to `ISSUED` when, after the undo, no admission of that
    order is `CHECKED_IN` any longer."
    PRD §2.4: "It has no `updated_at` and no `version`, because it is never modified
    after it is written."

    Design: Corner/state_machines/corner_undo_check_in_returns_attendee_to_issued
    """
    ctx = setup_onsale_event(
        event_overrides={"title": "Undo Night", "starts_at": "2026-08-01T18:00:00Z",
                         "ends_at": "2026-08-01T22:00:00Z"})
    paid = setup_paid_order(ctx, buyer=create_buyer(email="ben@example.com",
                                                    display_name="Ben"), quantity=1)
    set_clock("2026-08-01T17:00:00Z")
    admission_id = paid["attendees"][0]["id"]
    scan_attendee(admission_id, ctx["event_id"])

    validate_success(api_client.undo_check_in(admission_id, GATE), 200)

    admission = read_attendee(admission_id)
    assert admission["status"] == "ISSUED"
    assert admission["checked_in_at"] is None, \
        f"The undo clears checked_in_at, got {admission['checked_in_at']}"
    assert read_event(ctx["event_id"])["checked_in_count"] == 0
    assert read_order(paid["order_id"], paid["buyer"])["fulfillment_status"] == "ISSUED"

    rows, meta = validate_paginated(api_client.list_scans(
        GATE, params={"attendee_id": admission_id}))
    assert meta["total_count"] == 1, \
        "The scan history survives the undo because a scan record is never modified"


def test_scanning_the_last_admission_completes_the_order_check_in():
    """PRD §3.5: "an order moves from `ISSUED` to `CHECKED_IN_PARTIAL` when at least
    one of its admissions is `CHECKED_IN` while at least one remains `ISSUED`, and
    from `CHECKED_IN_PARTIAL` to `CHECKED_IN_FULL` when every one of its non-voided
    admissions is `CHECKED_IN`."

    Design: Corner/state_machines/corner_order_reaches_checked_in_full_when_every_attendee_scanned
    """
    ctx = _event_with_two_paid_admissions(title="Bubble Night")
    first, second = ctx["paid"]["attendees"][0], ctx["paid"]["attendees"][1]
    scan_attendee(first["id"], ctx["event_id"])

    scan_attendee(second["id"], ctx["event_id"])

    order = read_order(ctx["paid"]["order_id"], ctx["paid"]["buyer"])
    assert order["fulfillment_status"] == "CHECKED_IN_FULL", \
        f"Every admission is through the door, got {order['fulfillment_status']}"
    assert order["payment_status"] == "PAID"
    assert read_attendee(second["id"])["status"] == "CHECKED_IN"
    assert read_event(ctx["event_id"])["checked_in_count"] == 2

    rows, meta = validate_paginated(api_client.list_scans(
        GATE, params={"event_id": ctx["event_id"]}))
    assert meta["total_count"] == 2


def test_voiding_one_seated_admission_syncs_both_ledgers():
    """PRD §3.5: "Any of the three source states produces identical consequences: the
    tier's `sold_count` falls by 1, and when the admission carried a non-null
    `seat_block_id` the block's `seats_taken` also falls by 1, returning that exact
    seat to the pool; the event's `issued_count` and `checked_in_count` are both
    recomputed."

    Design: Corner/state_machines/corner_attendee_void_syncs_seat_and_sold_ledgers
    """
    ctx = setup_reserved_onsale_event(
        event_overrides={"title": "Sync Night", "starts_at": "2026-09-27T18:00:00Z",
                         "ends_at": "2026-09-27T22:00:00Z"})
    paid = setup_paid_order(ctx, buyer=create_buyer(email="gus@example.com",
                                                    display_name="Gus"),
                            quantity=2, seat_numbers=[7, 8])
    first, second = paid["attendees"][0], paid["attendees"][1]

    validate_success(api_client.void_attendee(
        first["id"], ctx["org_headers"], {"reason": "guest withdrew"}), 200)

    assert read_attendee(first["id"])["status"] == "VOIDED"
    assert read_attendee(second["id"])["status"] == "ISSUED", \
        "The sibling admission is untouched"
    assert read_ticket_type(ctx["tt_id"])["sold_count"] == 1
    assert read_seat_block(ctx["sb_id"])["seats_taken"] == 1
    assert read_event(ctx["event_id"])["issued_count"] == 1


def test_event_report_carries_the_check_in_rate_to_four_decimals():
    """PRD §3.9: "It reports the `event_id`; a `tickets_sold_count` counting the
    event's admissions in `ISSUED`, `CHECKED_IN` or `TRANSFERRED` status; a
    `checked_in_count` counting those in `CHECKED_IN`; a `voided_count` counting those
    in `VOIDED`; the event's `gross_cents` and `refunds_cents` as stored; a
    `net_to_organizer_cents` equal to `gross_cents` minus `refunds_cents`; a
    `check_in_rate` equal to `checked_in_count` divided by `tickets_sold_count`,
    expressed as a number with exactly four decimal places rounded half up, and
    reported as zero when `tickets_sold_count` is zero; and a `waitlist_depth`
    counting the waitlist entries still in `WAITING` across every tier of the event."

    Design: Corner/calculations/corner_event_report_check_in_rate_rounds_to_four_decimals
    """
    ctx = setup_onsale_event(
        event_overrides={"title": "Report Night", "starts_at": "2026-08-01T18:00:00Z",
                         "ends_at": "2026-08-01T22:00:00Z"})
    paid = setup_paid_order(ctx, buyer=create_buyer(email="quy@example.com",
                                                    display_name="Quy"), quantity=3)
    set_clock("2026-08-01T17:00:00Z")
    scan_attendee(paid["attendees"][0]["id"], ctx["event_id"])

    report = validate_success(
        api_client.get_event_report(ctx["event_id"], ctx["org_headers"]), 200)

    assert report["tickets_sold_count"] == 3
    assert report["checked_in_count"] == 1
    assert report["voided_count"] == 0
    assert report["check_in_rate"] == pytest.approx(0.3333, abs=1e-9), (
        "One of three checked in rounds half up at four decimal places to 0.3333, got "
        f"{report['check_in_rate']}")
    assert report["gross_cents"] == 15000
    assert report["refunds_cents"] == 0
    assert report["net_to_organizer_cents"] == 15000
    assert report["waitlist_depth"] == 0
