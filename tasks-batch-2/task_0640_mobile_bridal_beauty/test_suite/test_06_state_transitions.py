"""State-machine corner tests: invalid transitions, terminal-state lockdown, idempotency,
initial state, and the no-lead-artist precondition.

Corner queue: state_machines.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_quoted_event,
    setup_contracted_event,
    setup_balance_due_event,
    create_artist,
    create_event,
    add_face,
    confirm_face,
    quote_event,
    book_trial,
    complete_trial,
    pay_deposit,
    set_clock,
    make_client_headers,
    make_coordinator_headers,
)

COORD = make_coordinator_headers()


def test_quote_from_contracted_returns_invalid_state(api):
    """PRD §3.3: "Once at least one face exists, a `Coordinator` issues a quote, advancing the
    event from `DRAFT` to `QUOTED`."
    PRD §2.9: "then whether the target resource is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/quote_from_contracted_returns_invalid_state
    """
    setup = setup_contracted_event(
        client_id="client-1",
        artist_overrides=dict(
            hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
            travel_rate_per_km_cents=600, max_faces_per_hour=2,
        ),
        event_overrides=dict(venue_distance_km=10),
        faces=[{"person_label": "BRIDE", "service_type": "HAIR", "is_bride": True, "confirm": True}],
    )
    # Event is CONTRACTED; quoting has no defined transition from CONTRACTED.
    validate_error(api.quote_event(setup["event_id"], COORD), ApiErrorId.ERR_INVALID_STATE)


def test_request_revision_from_draft_returns_invalid_state(api):
    """PRD §3.3: "A `Client` who is unhappy with a quote may request a revision, moving the
    event from `QUOTED` to `REVISION_REQUESTED`."

    Design: Corner/state_machines/request_revision_from_draft_returns_invalid_state
    """
    event = create_event(client_id="client-1", venue_distance_km=10)
    # Event is in DRAFT (never quoted); request-revision is only defined from QUOTED.
    resp = api.request_revision(event["id"], make_client_headers("client-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_cancel_from_completed_terminal_returns_invalid_state(api):
    """PRD §3.15: "`COMPLETED` is a terminal event state."
    PRD §3.16: "A `Client` may cancel an event from `DRAFT`, `QUOTED`, `CONTRACTED`, or
    `SCHEDULED`".

    Design: Corner/state_machines/cancel_from_completed_terminal_returns_invalid_state
    """
    # Build a fully completed event: deposit+balance paid, assignment completed, event done.
    setup = setup_balance_due_event(
        client_id="client-1",
        artist_overrides=dict(
            hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
            travel_rate_per_km_cents=600, max_faces_per_hour=2,
        ),
        event_overrides=dict(
            event_date_utc="2026-07-15T20:00:00Z", ready_by_utc="2026-07-15T20:00:00Z",
            venue_distance_km=10,
        ),
        faces=[{"person_label": "BRIDE", "service_type": "HAIR", "is_bride": True, "confirm": True}],
        window_start_utc="2026-07-15T08:00:00Z", window_end_utc="2026-07-15T10:00:00Z",
        start_clock="2026-07-15T08:00:00Z",
    )
    # Pay the balance (27000) so balance_status -> PAID, then complete the event.
    assert setup["invoice_after"]["balance_amount_cents"] == 27000
    validate_success(
        api.record_payment(setup["invoice_id"], {"applies_to": "BALANCE", "amount_cents": 27000},
                           make_client_headers("client-1")),
        201,
    )
    completed = validate_success(api.complete_event(setup["event_id"], COORD), 200)
    assert completed["status"] == "COMPLETED"
    # Cancelling from the terminal COMPLETED state has no defined transition.
    resp = api.cancel_event(setup["event_id"], {"reason": "CLIENT_CHOICE"}, make_client_headers("client-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_trial_complete_twice_returns_invalid_state(api):
    """PRD §3.5: "The conducting `Artist` marks a trial completed, advancing `BOOKED` to
    `COMPLETED`, but only when the acting artist is the trial's own artist and the current
    time has reached the trial's `start_utc`."

    Design: Corner/state_machines/trial_complete_twice_idempotency_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    artist = create_artist(
        hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
        travel_rate_per_km_cents=600, max_faces_per_hour=2,
    )
    event = create_event(client_id="client-1", venue_distance_km=10, trial_required=True)
    trial = book_trial(event["id"], artist["id"], "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z")
    set_clock("2026-06-10T09:30:00Z")
    complete_trial(trial["id"], artist["id"])
    # Second complete on an already-COMPLETED trial -> invalid state.
    from test_helpers import make_artist_headers
    resp = api.complete_trial(trial["id"], make_artist_headers(artist["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_new_event_starts_in_draft(api):
    """PRD §3.2: "The event is created in `DRAFT` status with `estimated_total_cents` at 0,
    `quote_revision` at 0, and `party_size` at 0."

    Design: Corner/state_machines/new_event_starts_in_draft
    """
    event = create_event(client_id="client-1", venue_distance_km=10)
    assert event["status"] == "DRAFT"
    assert event["quote_revision"] == 0
    assert event["estimated_total_cents"] == 0


def test_quote_with_no_active_lead_artist_returns_no_lead(api):
    """PRD §3.4: "If no `ACTIVE` `LEAD` artist exists on the roster, the quote is rejected with
    `ERR_NO_LEAD_ARTIST`."

    Design: Corner/state_machines/quote_with_no_lead_artist_returns_no_lead
    """
    # Only a SENIOR artist on the roster; no LEAD.
    create_artist(
        display_name="S", skill_tier="SENIOR", hair_rate_per_face_cents=10000,
        makeup_rate_per_face_cents=12000, travel_rate_per_km_cents=500, max_faces_per_hour=3,
    )
    event = create_event(client_id="client-1", venue_distance_km=10)
    face = add_face(event["id"], "client-1", "BRIDE", "HAIR", is_bride=True)
    confirm_face(face["id"], "client-1")
    validate_error(api.quote_event(event["id"], COORD), ApiErrorId.ERR_NO_LEAD_ARTIST)
