"""Cascade and settlement tests: event-cancel multi-hop settlement, assignment-cancel
add-on reversal, compensating apply/reverse invariants, window release, the cancellation
refund tiers (weather override, deposit-forfeit), and the extended-stay add-on.

Difficulty queue: transitive_cascade, compensating_invariant.
Corner queue: calculations (weather override, deposit forfeit, extended stay).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_deposit_paid_event,
    setup_scheduled_event,
    apply_addon,
    schedule_assignment,
    sign_contract,
    create_event,
    add_face,
    confirm_face,
    quote_event,
    pay_deposit,
    set_clock,
    same_instant,
    make_client_headers,
    make_coordinator_headers,
)

COORD = make_coordinator_headers()


def _cancel(api, event_id, reason, client_id):
    return api.cancel_event(event_id, {"reason": reason}, make_client_headers(client_id))


def _deposit_paid_event_for_lead(api, lead_artist_id, client_id, distance_km=5):
    """Build a fresh deposit-paid CONTRACTED event whose lead is the GIVEN artist, so a new
    assignment's window is checked against that artist's prior (possibly cancelled) windows."""
    from test_helpers import validate_paginated
    event = create_event(
        client_id=client_id, event_date_utc="2026-07-15T20:00:00Z",
        ready_by_utc="2026-07-15T20:00:00Z", venue_distance_km=distance_km,
    )
    face = add_face(event["id"], client_id, "BRIDE", "HAIR", is_bride=True)
    confirm_face(face["id"], client_id)
    quoted = quote_event(event["id"])
    contract = sign_contract(event["id"], lead_artist_id, quoted["version"], client_id)
    items, _ = validate_paginated(
        api.list_invoices(make_client_headers(client_id), params={"event_id": event["id"]})
    )
    pay_deposit(items[0]["id"], contract["deposit_due_cents"], client_id)
    ev = validate_success(api.get_event(event["id"], COORD), 200)
    return {"event_id": event["id"], "post_deposit_version": ev["version"]}


# ─── Rule: transitive_cascade ─────────────────────────
def test_event_cancel_full_forfeit_cascade_settles_invoice_and_removes_faces(api):
    """PRD §3.16: "if fewer than 72 hours remain, the tier is `FULL_FORFEIT`."
    PRD §3.16: "When the tier is `DEPOSIT_FORFEIT` or `FULL_FORFEIT` and the deposit was
    `PAID`, the `deposit_status` advances from `PAID` to `FORFEITED` with `deposit_refund_cents`
    of zero."
    PRD §3.16: "Cancelling a `CONTRACTED` event, after settling the invoice, transitions every
    `CONFIRMED` and `PENDING` booking face to `REMOVED`."

    Design: Difficulty/transitive_cascade/event_cancel_settlement_invoice_face_cascade
    """
    setup = setup_deposit_paid_event(
        client_id="client-1",
        artist_overrides=dict(
            hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
            travel_rate_per_km_cents=600, max_faces_per_hour=2,
        ),
        event_overrides=dict(
            event_date_utc="2026-07-15T20:00:00Z", ready_by_utc="2026-07-15T12:00:00Z",
            venue_distance_km=10,
        ),
        faces=[
            {"person_label": "BRIDE", "service_type": "BOTH", "is_bride": True, "confirm": True},
            {"person_label": "BRIDESMAID_1", "service_type": "HAIR", "confirm": True},
        ],
    )
    bride_face_id = setup["faces"][0]["id"]
    # ~36h before event_date (< 72h) -> FULL_FORFEIT tier.
    set_clock("2026-07-14T08:00:00Z")
    record = validate_success(_cancel(api, setup["event_id"], "CLIENT_CHOICE", "client-1"), 200)
    assert record["refund_tier"] == "FULL_FORFEIT", (
        f"Expected FULL_FORFEIT, got {record['refund_tier']}"
    )

    invoice = validate_success(api.get_invoice(setup["invoice_id"], make_client_headers("client-1")), 200)
    assert invoice["deposit_status"] == "FORFEITED", (
        f"Expected deposit FORFEITED, got {invoice['deposit_status']}"
    )
    face = validate_success(api.list_faces(setup["event_id"], COORD), 200)
    bride = next(f for f in face if f["id"] == bride_face_id)
    assert bride["status"] == "REMOVED", f"Expected face REMOVED, got {bride['status']}"


def test_assignment_cancel_reverses_addon_and_recomputes_balance(api):
    """PRD §3.14: "Cancelling releases the artist's window ..., reverses every `APPLIED`
    add-on on that assignment to `REVERSED`, and re-runs the balance reconciliation so the
    invoice's `balance_amount_cents` drops by the reversed add-on charges."

    Design: Difficulty/transitive_cascade/assignment_cancel_reverse_addon_balance_cascade
    """
    setup = setup_scheduled_event(
        client_id="client-1",
        artist_overrides=dict(
            hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
            travel_rate_per_km_cents=600, max_faces_per_hour=2,
        ),
        event_overrides=dict(venue_distance_km=10),
        faces=[
            {"person_label": "BRIDE", "service_type": "BOTH", "is_bride": True, "confirm": True},
            {"person_label": "BRIDESMAID_1", "service_type": "HAIR", "confirm": True},
        ],
        window_start_utc="2026-07-15T08:00:00Z", window_end_utc="2026-07-15T10:00:00Z",
    )
    addon = apply_addon(setup["assignment_id"], "TOUCH_UP", 2)  # +25000 -> balance 90450

    cancelled = validate_success(api.cancel_assignment(setup["assignment_id"], COORD), 200)
    assert cancelled["status"] == "CANCELLED"

    addons = validate_success(api.list_addons(setup["assignment_id"], COORD), 200)
    reversed_addon = next(a for a in addons if a["id"] == addon["id"])
    assert reversed_addon["status"] == "REVERSED"

    invoice = validate_success(api.get_invoice(setup["invoice_id"], make_client_headers("client-1")), 200)
    # balance drops back to contract 93500 - deposit 28050 = 65450.
    assert invoice["balance_amount_cents"] == 65450, (
        f"Expected balance 65450 after reversal, got {invoice['balance_amount_cents']}"
    )


# ─── Rule: compensating_invariant ─────────────────────
def test_addon_apply_then_reverse_conserves_balance(api):
    """PRD §3.14: "re-runs the balance reconciliation so the invoice's `balance_amount_cents`
    drops by the reversed add-on charges."
    PRD §3.8: "the gross amount due is the contract's `contracted_total_cents` plus the
    applied add-ons; the `balance_amount_cents` is the gross due minus the paid total minus
    any cancellation relief that has been written off, floored at zero so the balance is
    never negative".

    Design: Difficulty/compensating_invariant/addon_apply_reverse_conserves_balance
    """
    setup = setup_scheduled_event(
        client_id="client-1",
        artist_overrides=dict(
            hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
            travel_rate_per_km_cents=600, max_faces_per_hour=2,
        ),
        event_overrides=dict(venue_distance_km=10),
        faces=[
            {"person_label": "BRIDE", "service_type": "BOTH", "is_bride": True, "confirm": True},
            {"person_label": "BRIDESMAID_1", "service_type": "HAIR", "confirm": True},
        ],
        window_start_utc="2026-07-15T08:00:00Z", window_end_utc="2026-07-15T10:00:00Z",
    )
    addon = apply_addon(setup["assignment_id"], "TOUCH_UP", 2)  # balance 90450
    # Cancel the assignment, reversing the add-on -> balance must return to 65450.
    validate_success(api.cancel_assignment(setup["assignment_id"], COORD), 200)

    addons = validate_success(api.list_addons(setup["assignment_id"], COORD), 200)
    assert next(a for a in addons if a["id"] == addon["id"])["status"] == "REVERSED"

    invoice = validate_success(api.get_invoice(setup["invoice_id"], make_client_headers("client-1")), 200)
    assert invoice["balance_amount_cents"] == 65450, (
        f"Expected balance restored to 65450, got {invoice['balance_amount_cents']}"
    )


def test_scheduled_then_cancelled_window_can_be_rescheduled(api):
    """PRD §3.14: "Cancelling releases the artist's window (so it no longer blocks future
    bookings via the travel buffer)".
    PRD §3.11: "the system takes the new window's interval, expands it by 60 minutes on each
    side, and rejects the schedule if that expanded interval intersects any of that artist's
    existing non-cancelled assignment windows (any assignment whose `status` is not
    `CANCELLED`)."

    Design: Difficulty/compensating_invariant/assignment_schedule_cancel_releases_window
    """
    setup = setup_deposit_paid_event(
        client_id="client-1",
        artist_overrides=dict(
            hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
            travel_rate_per_km_cents=600, max_faces_per_hour=4,
        ),
        event_overrides=dict(
            event_date_utc="2026-07-15T20:00:00Z", ready_by_utc="2026-07-15T20:00:00Z",
            venue_distance_km=10,
        ),
        faces=[
            {"person_label": "BRIDE", "service_type": "HAIR", "is_bride": True, "confirm": True},
        ],
    )
    lead_id = setup["lead_artist_id"]
    a1 = schedule_assignment(
        setup["event_id"], lead_id, setup["post_deposit_version"],
        window_start_utc="2026-07-15T08:00:00Z", window_end_utc="2026-07-15T09:00:00Z",
    )
    validate_success(api.cancel_assignment(a1["id"], COORD), 200)

    # A fresh event for the SAME lead artist: the same [08:00, 09:00) slot must now be
    # schedulable (the cancelled window no longer blocks via the travel buffer).
    other = _deposit_paid_event_for_lead(api, lead_id, "client-9")
    a2 = schedule_assignment(
        other["event_id"], lead_id, other["post_deposit_version"],
        window_start_utc="2026-07-15T08:00:00Z", window_end_utc="2026-07-15T09:00:00Z",
    )
    assert a2["status"] == "SCHEDULED"
    a1_after = validate_success(api.get_assignment(a1["id"], COORD), 200)
    assert a1_after["status"] == "CANCELLED"
    a1_after = validate_success(api.get_assignment(a1["id"], COORD), 200)
    assert a1_after["status"] == "CANCELLED"


# ─── Corner: calculations ─────────────────────────────
def test_extended_stay_addon_bills_flat_and_extends_window(api):
    """PRD §3.13: "For an `EXTENDED_STAY`, each extra 30-minute block is billed at a flat
    overtime rate of 8,000 cents, so `amount_cents` is 8,000 multiplied by the quantity; in
    addition, the assignment's `extended_until_utc` is set to its `window_end_utc` pushed out
    by the quantity times 30 minutes."

    Design: Corner/calculations/extended_stay_addon_extends_window_and_bills_flat
    """
    setup = setup_scheduled_event(
        client_id="client-1",
        artist_overrides=dict(
            hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
            travel_rate_per_km_cents=600, max_faces_per_hour=2,
        ),
        event_overrides=dict(
            event_date_utc="2026-07-15T20:00:00Z", ready_by_utc="2026-07-15T12:00:00Z",
            venue_distance_km=10,
        ),
        faces=[{"person_label": "BRIDE", "service_type": "HAIR", "is_bride": True, "confirm": True}],
        window_start_utc="2026-07-15T08:00:00Z", window_end_utc="2026-07-15T10:00:00Z",
    )
    addon = apply_addon(setup["assignment_id"], "EXTENDED_STAY", 1)
    assert addon["amount_cents"] == 8000, f"Expected flat 8000, got {addon['amount_cents']}"

    assignment = validate_success(api.get_assignment(setup["assignment_id"], COORD), 200)
    assert same_instant(assignment["extended_until_utc"], "2026-07-15T10:30:00Z"), (
        f"Expected extended_until 10:30, got {assignment['extended_until_utc']}"
    )


def test_extended_stay_past_ready_by_deadline_rejected(api):
    """PRD §3.13: "An `EXTENDED_STAY` add-on may not push `extended_until_utc` past the event's
    `ready_by_utc`; a request that would extend beyond the deadline is rejected with
    `ERR_EXTENSION_PAST_DEADLINE`."

    Design: Corner/calculations/extended_stay_past_deadline_rejected
    """
    setup = setup_scheduled_event(
        client_id="client-1",
        artist_overrides=dict(
            hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
            travel_rate_per_km_cents=600, max_faces_per_hour=2,
        ),
        event_overrides=dict(
            event_date_utc="2026-07-15T20:00:00Z", ready_by_utc="2026-07-15T09:00:00Z",
            venue_distance_km=10,
        ),
        faces=[{"person_label": "BRIDE", "service_type": "HAIR", "is_bride": True, "confirm": True}],
        window_start_utc="2026-07-15T08:00:00Z", window_end_utc="2026-07-15T09:00:00Z",
    )
    # window ends at ready_by 09:00; +30min -> 09:30 > ready_by -> rejected.
    resp = api.add_addon(setup["assignment_id"], {"addon_type": "EXTENDED_STAY", "quantity": 1}, COORD)
    validate_error(resp, ApiErrorId.ERR_EXTENSION_PAST_DEADLINE)


def test_weather_cancellation_overrides_to_full_refund(api):
    """PRD §3.16: "If the `reason` is `WEATHER`, the tier is always `FULL_REFUND` regardless of
    how many hours remain — weather is always fully forgiven, which is what makes a weather
    cancellation diverge from a `CLIENT_CHOICE` cancellation at identical hours."
    PRD §3.16: "Under `FULL_REFUND`, `deposit_refund_cents` equals the invoice's
    `deposit_amount_cents` when the deposit was `PAID` (and zero otherwise)".

    Design: Corner/calculations/weather_cancellation_overrides_to_full_refund
    """
    setup = setup_deposit_paid_event(
        client_id="client-1",
        artist_overrides=dict(
            hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
            travel_rate_per_km_cents=600, max_faces_per_hour=2,
        ),
        event_overrides=dict(
            event_date_utc="2026-07-15T20:00:00Z", ready_by_utc="2026-07-15T12:00:00Z",
            venue_distance_km=10,
        ),
        faces=[{"person_label": "BRIDE", "service_type": "HAIR", "is_bride": True, "confirm": True}],
    )
    # hair-only bride: base 20000*1.5=30000; total 30000 + travel 6000 = 36000 -> LOW tier
    # 0.25 -> 9000.
    assert setup["deposit_due_cents"] == 9000
    set_clock("2026-07-14T08:00:00Z")  # ~36h before -> would be FULL_FORFEIT for CLIENT_CHOICE
    record = validate_success(_cancel(api, setup["event_id"], "WEATHER", "client-1"), 200)
    assert record["refund_tier"] == "FULL_REFUND"
    assert record["deposit_refund_cents"] == 9000, (
        f"Expected deposit refund 9000, got {record['deposit_refund_cents']}"
    )
    invoice = validate_success(api.get_invoice(setup["invoice_id"], make_client_headers("client-1")), 200)
    assert invoice["deposit_status"] == "REFUNDED"


def test_deposit_forfeit_tier_at_120_hours(api):
    """PRD §3.16: "if the hours remaining are at least 72 but less than 720 (between three and
    thirty days out), the tier is `DEPOSIT_FORFEIT`".
    PRD §3.16: "Under `DEPOSIT_FORFEIT`, `deposit_refund_cents` is zero (the platform keeps the
    deposit)".

    Design: Corner/calculations/deposit_forfeit_tier_at_120_hours
    """
    setup = setup_deposit_paid_event(
        client_id="client-1",
        artist_overrides=dict(
            hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
            travel_rate_per_km_cents=600, max_faces_per_hour=2,
        ),
        event_overrides=dict(
            event_date_utc="2026-07-15T20:00:00Z", ready_by_utc="2026-07-15T12:00:00Z",
            venue_distance_km=10,
        ),
        faces=[{"person_label": "BRIDE", "service_type": "HAIR", "is_bride": True, "confirm": True}],
    )
    set_clock("2026-07-10T20:00:00Z")  # exactly 120h before event_date -> DEPOSIT_FORFEIT
    record = validate_success(_cancel(api, setup["event_id"], "CLIENT_CHOICE", "client-1"), 200)
    assert record["refund_tier"] == "DEPOSIT_FORFEIT"
    assert record["deposit_refund_cents"] == 0
    invoice = validate_success(api.get_invoice(setup["invoice_id"], make_client_headers("client-1")), 200)
    assert invoice["deposit_status"] == "FORFEITED"
