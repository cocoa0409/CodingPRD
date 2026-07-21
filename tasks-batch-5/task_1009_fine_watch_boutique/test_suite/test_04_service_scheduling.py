"""Bench-buffer and loaner-interval scheduling gates, back-dated appointments,
and the cross-entity authentication precondition for opening a ticket."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    set_clock, new_customer, new_model, new_watch, new_authenticated_watch,
    new_watchmaker, authenticate, service_context, get_success_data, TEST_USERS,
)
from test_helpers.factories import create_service_ticket_payload

ASSOC = TEST_USERS["associate_headers"]


def _bench_setup():
    """Watchmaker with an existing 10:00-12:00 ticket on 2026-07-03 (watch W1),
    plus a second authenticated watch W2 for the probe."""
    set_clock("2026-07-02T00:00:00Z")
    customer = new_customer()
    model = new_model()
    w1 = new_authenticated_watch(model["id"])
    w2 = new_authenticated_watch(model["id"])
    wm = new_watchmaker()
    get_success_data(
        api_client.create_service_ticket(
            create_service_ticket_payload(
                w1["id"], customer["id"], wm["id"], service_type="MOVEMENT_OVERHAUL",
                appt_start="2026-07-03T10:00:00Z", appt_end="2026-07-03T12:00:00Z"),
            ASSOC)
    )
    return customer, wm, w2


def test_bench_gap_below_buffer_rejected(api):
    """PRD §3.6: "a new booking conflicts with an existing one unless the new start
    is at or after the existing end plus thirty minutes, or the existing start is at
    or after the new end plus thirty minutes — so a gap of exactly thirty minutes is
    allowed, and any tighter spacing is rejected with ERR_WATCHMAKER_UNAVAILABLE
    (409)."

    Design: Difficulty/resource_temporal_overlap/watchmaker_bench_buffer_overlap
    """
    customer, wm, w2 = _bench_setup()
    # Start 12:15 — only 15 minutes after the 12:00 end, tighter than the 30 buffer.
    validate_error(
        api.create_service_ticket(
            create_service_ticket_payload(
                w2["id"], customer["id"], wm["id"], service_type="BATTERY",
                appt_start="2026-07-03T12:15:00Z", appt_end="2026-07-03T13:00:00Z"),
            ASSOC),
        ApiErrorId.ERR_WATCHMAKER_UNAVAILABLE,
    )


def test_bench_gap_exactly_buffer_allowed(api):
    """PRD §3.6: "a new booking conflicts with an existing one unless the new start
    is at or after the existing end plus thirty minutes, or the existing start is at
    or after the new end plus thirty minutes — so a gap of exactly thirty minutes is
    allowed, and any tighter spacing is rejected with ERR_WATCHMAKER_UNAVAILABLE
    (409)."

    Design: Difficulty/resource_temporal_overlap/watchmaker_bench_buffer_overlap
    """
    customer, wm, w2 = _bench_setup()
    # Start 12:30 — exactly the 30-minute buffer after the 12:00 end.
    data = validate_success(
        api.create_service_ticket(
            create_service_ticket_payload(
                w2["id"], customer["id"], wm["id"], service_type="BATTERY",
                appt_start="2026-07-03T12:30:00Z", appt_end="2026-07-03T13:30:00Z"),
            ASSOC),
        expected_status=201,
    )
    assert data["status"] == "RECEIVED"


def _loaner_setup():
    """A loaner L reserved over [07-03, 07-09] on ticket1, plus authenticated
    watches W2/W3 for the probes on the same watchmaker."""
    set_clock("2026-07-02T00:00:00Z")
    customer = new_customer()
    model = new_model()
    loaner = authenticate(new_watch(model["id"], is_loaner=True)["id"])
    w1 = new_authenticated_watch(model["id"])
    w2 = new_authenticated_watch(model["id"])
    w3 = new_authenticated_watch(model["id"])
    wm = new_watchmaker()
    get_success_data(
        api_client.create_service_ticket(
            create_service_ticket_payload(
                w1["id"], customer["id"], wm["id"], service_type="BATTERY",
                appt_start="2026-07-03T09:00:00Z", appt_end="2026-07-03T10:00:00Z",
                loaner_watch_id=loaner["id"], loan_start="2026-07-03T00:00:00Z",
                loan_end="2026-07-09T00:00:00Z"),
            ASSOC)
    )
    return customer, wm, loaner, w2, w3


def test_loaner_touching_interval_allowed(api):
    """PRD §3.6: "a new loan conflicts with an existing one when the new start falls
    before the existing end and the existing start falls before the new end — so two
    loans that merely touch at an endpoint (one ending exactly when the next begins)
    do not conflict, while any true overlap is rejected with ERR_LOANER_UNAVAILABLE
    (409)."

    Design: Difficulty/resource_temporal_overlap/loaner_watch_adjacent_vs_overlap
    """
    customer, wm, loaner, w2, _w3 = _loaner_setup()
    # New loan [07-09, 07-12] begins exactly when the prior loan ends (07-09).
    data = validate_success(
        api.create_service_ticket(
            create_service_ticket_payload(
                w2["id"], customer["id"], wm["id"], service_type="BATTERY",
                appt_start="2026-07-03T11:00:00Z", appt_end="2026-07-03T12:00:00Z",
                loaner_watch_id=loaner["id"], loan_start="2026-07-09T00:00:00Z",
                loan_end="2026-07-12T00:00:00Z"),
            ASSOC),
        expected_status=201,
    )
    assert data["status"] == "RECEIVED"


def test_loaner_overlapping_interval_rejected(api):
    """PRD §3.6: "a new loan conflicts with an existing one when the new start falls
    before the existing end and the existing start falls before the new end ... while
    any true overlap is rejected with ERR_LOANER_UNAVAILABLE (409)."

    Design: Difficulty/resource_temporal_overlap/loaner_watch_adjacent_vs_overlap
    """
    customer, wm, loaner, _w2, w3 = _loaner_setup()
    # New loan [07-08, 07-10] overlaps the existing [07-03, 07-09] by a positive span.
    validate_error(
        api.create_service_ticket(
            create_service_ticket_payload(
                w3["id"], customer["id"], wm["id"], service_type="BATTERY",
                appt_start="2026-07-03T13:00:00Z", appt_end="2026-07-03T14:00:00Z",
                loaner_watch_id=loaner["id"], loan_start="2026-07-08T00:00:00Z",
                loan_end="2026-07-10T00:00:00Z"),
            ASSOC),
        ApiErrorId.ERR_LOANER_UNAVAILABLE,
    )


def test_backdated_appointment_rejected(api):
    """PRD §3.6: "The appointment must not be back-dated: appt_start must be at or
    after the current clock, otherwise ERR_APPOINTMENT_IN_PAST (HTTP 422)."

    Design: Corner/validations/appointment_in_past_rejected
    """
    ctx = service_context(clock="2026-07-05T00:00:00Z")
    validate_error(
        api.create_service_ticket(
            create_service_ticket_payload(
                ctx["watch"]["id"], ctx["customer"]["id"], ctx["watchmaker"]["id"],
                service_type="BATTERY",
                appt_start="2026-07-03T09:00:00Z", appt_end="2026-07-03T09:30:00Z"),
            ASSOC),
        ApiErrorId.ERR_APPOINTMENT_IN_PAST,
    )


def test_service_on_unverified_watch_rejected(api):
    """PRD §3.6: "Opening a ticket requires the serviced watch to be AUTHENTICATED
    (else ERR_WATCH_NOT_AUTHENTICATED, 409); on success the watch moves IN_STOCK →
    IN_SERVICE, the ticket is born with workflow status RECEIVED and payment_status
    UNPAID, its quoted_cents still null, and its amount_paid_cents at 0."

    Design: Difficulty/cross_entity_state_dependency/service_create_requires_watch_authenticated
    """
    ctx = service_context(authenticate_watch=False)
    validate_error(
        api.create_service_ticket(
            create_service_ticket_payload(
                ctx["watch"]["id"], ctx["customer"]["id"], ctx["watchmaker"]["id"],
                service_type="BATTERY",
                appt_start="2026-07-03T09:00:00Z", appt_end="2026-07-03T09:30:00Z"),
            ASSOC),
        ApiErrorId.ERR_WATCH_NOT_AUTHENTICATED,
    )


def test_service_after_authenticate_succeeds(api):
    """PRD §3.6: "Opening a ticket requires the serviced watch to be AUTHENTICATED
    (else ERR_WATCH_NOT_AUTHENTICATED, 409); on success the watch moves IN_STOCK →
    IN_SERVICE, the ticket is born with workflow status RECEIVED and payment_status
    UNPAID, its quoted_cents still null, and its amount_paid_cents at 0."

    Design: Difficulty/cross_entity_state_dependency/service_create_requires_watch_authenticated
    """
    ctx = service_context(authenticate_watch=False)
    authenticate(ctx["watch"]["id"])
    ticket = validate_success(
        api.create_service_ticket(
            create_service_ticket_payload(
                ctx["watch"]["id"], ctx["customer"]["id"], ctx["watchmaker"]["id"],
                service_type="BATTERY",
                appt_start="2026-07-03T09:00:00Z", appt_end="2026-07-03T09:30:00Z"),
            ASSOC),
        expected_status=201,
    )
    assert ticket["status"] == "RECEIVED"
    watch = validate_success(api.get_watch(ctx["watch"]["id"], ASSOC))
    assert watch["status"] == "IN_SERVICE"
