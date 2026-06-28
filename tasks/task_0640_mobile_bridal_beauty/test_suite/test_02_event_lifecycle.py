"""Event/invoice lifecycle tests: the quote-revision cycle, the invoice's two independent
status axes, the trial-completed gate on signing, and the assignment+balance gate on
completing the event.

Difficulty queue: non_linear_state_machine, cross_entity_state_dependency.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_quoted_event,
    setup_balance_due_event,
    sign_contract,
    book_trial,
    complete_trial,
    set_clock,
    create_artist,
    create_event,
    add_face,
    confirm_face,
    quote_event,
    make_client_headers,
    make_coordinator_headers,
)

COORD = make_coordinator_headers()


# ─── Rule: non_linear_state_machine ───────────────────
def test_quote_revision_cycle_increments_each_round(api):
    """PRD §3.3: "The loop `QUOTED → REVISION_REQUESTED → QUOTED` may cycle any number of
    times, and `quote_revision` counts the rounds."
    PRD §3.3: "Issuing the quote runs the estimate calculation (see §3.4) and writes the
    result into `estimated_total_cents`, increments `quote_revision` by one".

    Design: Difficulty/non_linear_state_machine/event_quote_revision_cycle
    """
    set_clock("2026-06-01T00:00:00Z")
    create_artist(
        hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
        travel_rate_per_km_cents=600, max_faces_per_hour=2,
    )
    event = create_event(client_id="client-1", venue_distance_km=10)
    face = add_face(event["id"], "client-1", "BRIDE", "BOTH", is_bride=True)
    confirm_face(face["id"], "client-1")

    # First quote (round 1).
    quote_event(event["id"])
    # Request a revision, then re-quote (round 2).
    validate_success(api.request_revision(event["id"], make_client_headers("client-1")), 200)
    requoted = validate_success(api.quote_event(event["id"], COORD), 200)

    assert requoted["status"] == "QUOTED"
    assert requoted["quote_revision"] == 2, (
        f"Expected quote_revision 2 after two rounds, got {requoted['quote_revision']}"
    )


def test_invoice_deposit_and_balance_axes_evolve_independently(api):
    """PRD §3.9: "A successful, exact deposit payment advances `deposit_status` from `DUE` to
    `PAID`, increments `amount_paid_cents`, and recomputes `balance_amount_cents`."
    PRD §3.13: "Completing the assignment has a bubble-up side effect on billing: if the
    invoice's `balance_status` is currently `NOT_DUE`, it advances to `DUE`, making the
    balance collectible (this readiness advance is conditioned on the deposit already being
    `PAID`)."

    Design: Difficulty/non_linear_state_machine/invoice_parallel_deposit_and_balance_axes
    """
    setup = setup_balance_due_event(
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
        start_clock="2026-07-15T08:00:00Z",
    )
    invoice = setup["invoice_after"]
    # Deposit axis moved DUE->PAID; balance axis moved NOT_DUE->DUE independently.
    assert invoice["deposit_status"] == "PAID", (
        f"Expected deposit_status PAID, got {invoice['deposit_status']}"
    )
    assert invoice["balance_status"] == "DUE", (
        f"Expected balance_status DUE, got {invoice['balance_status']}"
    )


# ─── Rule: cross_entity_state_dependency ──────────────
def test_contract_signs_only_after_trial_completed(api):
    """PRD §3.6: "If the event's `trial_required` flag is set, a trial session for this event
    must already be in `COMPLETED` status — otherwise the sign is rejected with
    `ERR_TRIAL_NOT_COMPLETED`."
    PRD §3.6: "Signing a contract is the pivot from negotiation to commitment, and it is a
    `Client`-only action that moves the event from `QUOTED` to `CONTRACTED`."

    Design: Difficulty/cross_entity_state_dependency/contract_requires_trial_completed
    """
    set_clock("2026-06-01T00:00:00Z")
    artist = create_artist(
        hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
        travel_rate_per_km_cents=600, max_faces_per_hour=2,
    )
    event = create_event(client_id="client-1", venue_distance_km=10, trial_required=True)
    face = add_face(event["id"], "client-1", "BRIDE", "BOTH", is_bride=True)
    confirm_face(face["id"], "client-1")
    quoted = quote_event(event["id"])

    # Book then complete a trial for this event.
    trial = book_trial(event["id"], artist["id"], "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z")
    set_clock("2026-06-10T09:30:00Z")
    complete_trial(trial["id"], artist["id"])

    contract = sign_contract(event["id"], artist["id"], quoted["version"], "client-1")
    assert contract["status"] == "SIGNED"
    event_after = validate_success(api.get_event(event["id"], COORD), 200)
    assert event_after["status"] == "CONTRACTED"


def test_event_complete_rejected_while_balance_unpaid(api):
    """PRD §3.15: "A `Coordinator` completes an event, advancing it from `SCHEDULED` to
    `COMPLETED`, only when every service assignment on the event is in `COMPLETED` status and
    the invoice's `balance_status` is `PAID`."

    Design: Difficulty/cross_entity_state_dependency/event_complete_requires_assignments_and_balance
    """
    setup = setup_balance_due_event(
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
        start_clock="2026-07-15T08:00:00Z",
    )
    # Assignment is COMPLETED, but balance_status is DUE (unpaid) -> complete is rejected.
    resp = api.complete_event(setup["event_id"], COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    invoice = validate_success(api.get_invoice(setup["invoice_id"], make_client_headers("client-1")), 200)
    assert invoice["balance_status"] == "DUE"
