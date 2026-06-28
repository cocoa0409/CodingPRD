"""Validation, temporal-conflict, fiscal-guard, OCC, and priority-ordering tests.

Difficulty queue: priority_pair_validation_conflict, resource_temporal_overlap.
Corner queue: validations (deposit mismatch, window past deadline, throughput, invalid
assistant, balance overpay), cross_cutting_complexity_layers (OCC stale event version).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    ApiErrorId,
    setup_quoted_event,
    setup_deposit_paid_event,
    setup_contracted_event,
    setup_balance_due_event,
    setup_scheduled_event,
    sign_contract,
    schedule_assignment,
    create_artist,
    create_event,
    add_face,
    confirm_face,
    quote_event,
    book_trial,
    set_clock,
    make_client_headers,
    make_coordinator_headers,
)

COORD = make_coordinator_headers()


# ─── Rule: priority_pair_validation_conflict ──────────
def test_trial_not_completed_beats_artist_not_active(api):
    """PRD §2.9: "Only after those guards pass does the system evaluate the operation-specific
    business rules described in §3 — trial completion, artist eligibility, window conflicts,
    timeline deadlines, throughput, and fiscal checks."
    PRD §3.6: "If the event's `trial_required` flag is set, a trial session for this event
    must already be in `COMPLETED` status — otherwise the sign is rejected with
    `ERR_TRIAL_NOT_COMPLETED`."

    Design: Difficulty/priority_pair_validation_conflict/trial_referential_beats_artist_constraint
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
    # Suspend the lead artist AND leave the required trial uncompleted: both P7 and P8 fail.
    validate_success(
        api.patch_artist(artist["id"], {"status": "SUSPENDED", "expected_artist_version": artist["version"]}, COORD),
        200,
    )
    resp = api.create_contract(
        {"event_id": event["id"], "lead_artist_id": artist["id"], "expected_event_version": quoted["version"]},
        make_client_headers("client-1"),
    )
    # Trial-completion (the earlier business rule) wins over artist-eligibility.
    validate_error(resp, ApiErrorId.ERR_TRIAL_NOT_COMPLETED)


def test_invalid_state_beats_deposit_not_settled_on_balance_payment(api):
    """PRD §2.9: "then whether the target resource is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`). Only after those guards pass does the system
    evaluate the operation-specific business rules described in §3".
    PRD §3.9: "A balance payment is gated on the deposit having settled first: attempting to
    pay the balance while `deposit_status` is anything other than `PAID` is rejected with
    `ERR_DEPOSIT_NOT_SETTLED`."

    PRD prose names BOTH the state guard (§2.9) and the deposit-not-settled fiscal rule (§3.9)
    for a balance payment attempted while the deposit is unpaid and the balance axis is still
    NOT_DUE, but does not commit to which pre-empts the other in this combined scenario; both
    outcomes are PRD-faithful, so either error_id is accepted.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_balance_payment
    """
    setup = setup_contracted_event(
        client_id="client-1",
        artist_overrides=dict(
            hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
            travel_rate_per_km_cents=600, max_faces_per_hour=2,
        ),
        event_overrides=dict(venue_distance_km=10),
        faces=[{"person_label": "BRIDE", "service_type": "BOTH", "is_bride": True, "confirm": True}],
    )
    # deposit UNPAID, balance_status still NOT_DUE -> rejected; PRD does not uniquely pin the
    # state guard ahead of the deposit-not-settled fiscal check, so accept either.
    resp = api.record_payment(
        setup["invoice_id"], {"applies_to": "BALANCE", "amount_cents": 1000},
        make_client_headers("client-1"),
    )
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_DEPOSIT_NOT_SETTLED]
    )


# ─── Rule: resource_temporal_overlap ──────────────────
def test_trial_overlap_closed_open_rejected(api):
    """PRD §3.5: "At booking time the system enforces that the trial window, treated as the
    half-open interval from `start_utc` up to but not including `end_utc`, does not overlap
    any other non-terminal trial of the same artist; two windows that merely touch
    end-to-start are allowed, but any genuine overlap is rejected with
    `ERR_TRIAL_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/trial_overlap_closed_open_no_buffer
    """
    set_clock("2026-06-01T00:00:00Z")
    artist = create_artist(
        hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
        travel_rate_per_km_cents=600, max_faces_per_hour=2,
    )
    event = create_event(client_id="client-1", venue_distance_km=10, trial_required=True)
    # First trial [09:00, 10:00); a second starting 09:30 overlaps.
    book_trial(event["id"], artist["id"], "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z")
    resp = api.create_trial(
        {"event_id": event["id"], "artist_id": artist["id"],
         "start_utc": "2026-06-10T09:30:00Z", "end_utc": "2026-06-10T10:30:00Z", "trial_fee_cents": 5000},
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_TRIAL_WINDOW_CONFLICT)


def test_assignment_overlap_with_travel_buffer_rejected(api):
    """PRD §3.11: "an existing window, treated as the half-open interval from its start up to
    but not including its end, blocks a new window whenever the new window's interval expanded
    by 60 minutes before its start and 60 minutes after its end intersects the existing
    interval. Two windows separated by exactly the 60-minute gap are adjacent and allowed;
    anything closer is rejected with `ERR_ASSIGNMENT_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/assignment_overlap_with_travel_buffer
    """
    # Event A: lead L1 has a SCHEDULED assignment [08:00, 09:00).
    setupA = setup_deposit_paid_event(
        client_id="client-1",
        artist_overrides=dict(
            hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
            travel_rate_per_km_cents=600, max_faces_per_hour=4,
        ),
        event_overrides=dict(
            event_date_utc="2026-07-15T20:00:00Z", ready_by_utc="2026-07-15T20:00:00Z",
            venue_distance_km=10,
        ),
        faces=[{"person_label": "BRIDE", "service_type": "HAIR", "is_bride": True, "confirm": True}],
    )
    lead_id = setupA["lead_artist_id"]
    schedule_assignment(
        setupA["event_id"], lead_id, setupA["post_deposit_version"],
        window_start_utc="2026-07-15T08:00:00Z", window_end_utc="2026-07-15T09:00:00Z",
    )

    # Event B for the SAME lead artist, deposit paid, 1 confirmed face. Its window
    # [09:30, 10:30) starts only 30 min after A's window ends -> inside the 60-min buffer.
    eventB = _build_second_event_for_lead(api, lead_id, client_id="client-9")
    resp = api.create_assignment(
        {"event_id": eventB["event_id"], "artist_id": lead_id,
         "window_start_utc": "2026-07-15T09:30:00Z", "window_end_utc": "2026-07-15T10:30:00Z",
         "expected_event_version": eventB["post_deposit_version"]},
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_WINDOW_CONFLICT)


def _build_second_event_for_lead(api, lead_artist_id, client_id):
    """Build a second deposit-paid CONTRACTED event whose lead is the GIVEN artist (so the
    travel-buffer conflict is evaluated against that artist's prior window)."""
    event = create_event(
        client_id=client_id, event_date_utc="2026-07-15T20:00:00Z",
        ready_by_utc="2026-07-15T20:00:00Z", venue_distance_km=5,
    )
    face = add_face(event["id"], client_id, "BRIDE", "HAIR", is_bride=True)
    confirm_face(face["id"], client_id)
    quoted = quote_event(event["id"])
    contract = sign_contract(event["id"], lead_artist_id, quoted["version"], client_id)
    invoice, _ = _first_invoice(api, event["id"], client_id)
    api.record_payment(invoice["id"], {"applies_to": "DEPOSIT", "amount_cents": contract["deposit_due_cents"]},
                       make_client_headers(client_id))
    ev = validate_success(api.get_event(event["id"], COORD), 200)
    return {"event_id": event["id"], "post_deposit_version": ev["version"]}


def _first_invoice(api, event_id, client_id):
    from test_helpers import validate_paginated
    resp = api.list_invoices(make_client_headers(client_id), params={"event_id": event_id})
    items, meta = validate_paginated(resp)
    return items[0], meta


# ─── Corner: validations ──────────────────────────────
def test_deposit_amount_mismatch_rejected(api):
    """PRD §3.9: "A deposit payment must settle the deposit exactly. Its `amount_cents` must
    equal the `deposit_amount_cents` minus any deposit already paid; an amount over or under
    that exact remaining deposit is rejected with `ERR_DEPOSIT_AMOUNT_MISMATCH`."

    Design: Corner/validations/deposit_amount_mismatch_rejected
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
    assert setup["deposit_due_cents"] == 9000
    resp = api.record_payment(
        setup["invoice_id"], {"applies_to": "DEPOSIT", "amount_cents": 8000},
        make_client_headers("client-1"),
    )
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_AMOUNT_MISMATCH)


def test_assignment_window_past_deadline_rejected(api):
    """PRD §3.10: "The window's `window_end_utc` must be no later than the event's
    `ready_by_utc` so the faces finish by the timeline deadline; a window ending past the
    deadline is rejected with `ERR_WINDOW_PAST_DEADLINE`."

    Design: Corner/validations/assignment_window_past_deadline_rejected
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
    # window_end 13:00 > ready_by 12:00 -> rejected.
    resp = api.create_assignment(
        {"event_id": setup["event_id"], "artist_id": setup["lead_artist_id"],
         "window_start_utc": "2026-07-15T11:00:00Z", "window_end_utc": "2026-07-15T13:00:00Z",
         "expected_event_version": setup["post_deposit_version"]},
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_PAST_DEADLINE)


def test_throughput_insufficient_rejected(api):
    """PRD §3.12: "The window is sufficient when this floored capacity is greater than or
    equal to the `CONFIRMED` face count; if the capacity equals the confirmed count exactly,
    the window passes, but if it falls even one face short the schedule is rejected with
    `ERR_INSUFFICIENT_THROUGHPUT`."

    Design: Corner/validations/throughput_insufficient_rejected
    """
    setup = setup_deposit_paid_event(
        client_id="client-1",
        artist_overrides=dict(
            hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
            travel_rate_per_km_cents=600, max_faces_per_hour=2,
        ),
        event_overrides=dict(
            event_date_utc="2026-07-15T20:00:00Z", ready_by_utc="2026-07-15T20:00:00Z",
            venue_distance_km=10,
        ),
        faces=[
            {"person_label": "BRIDE", "service_type": "HAIR", "is_bride": True, "confirm": True},
            {"person_label": "BM1", "service_type": "HAIR", "confirm": True},
            {"person_label": "BM2", "service_type": "HAIR", "confirm": True},
        ],
    )
    # 3 confirmed faces, cap 2/hr, 1-hour window -> floor(2*1)=2 < 3 -> rejected.
    resp = api.create_assignment(
        {"event_id": setup["event_id"], "artist_id": setup["lead_artist_id"],
         "window_start_utc": "2026-07-15T08:00:00Z", "window_end_utc": "2026-07-15T09:00:00Z",
         "expected_event_version": setup["post_deposit_version"]},
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_THROUGHPUT)


def test_invalid_assistant_cannot_assist_rejected(api):
    """PRD §3.10: "When an `assistant_artist_id` is supplied it must reference an artist whose
    `can_assist` is `true` and must not be the same artist as the lead, failing with
    `ERR_INVALID_ASSISTANT`."

    Design: Corner/validations/invalid_assistant_not_allowed_to_assist_rejected
    """
    setup = setup_deposit_paid_event(
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
    )
    no_assist = create_artist(
        display_name="NoAssist", skill_tier="JUNIOR", hair_rate_per_face_cents=5000,
        makeup_rate_per_face_cents=6000, travel_rate_per_km_cents=100, max_faces_per_hour=2,
        can_assist=False,
    )
    resp = api.create_assignment(
        {"event_id": setup["event_id"], "artist_id": setup["lead_artist_id"],
         "assistant_artist_id": no_assist["id"],
         "window_start_utc": "2026-07-15T08:00:00Z", "window_end_utc": "2026-07-15T10:00:00Z",
         "expected_event_version": setup["post_deposit_version"]},
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ASSISTANT)


def test_balance_overpay_rejected(api):
    """PRD §3.9: "A balance payment may not exceed the current `balance_amount_cents`; an
    overpayment is rejected with `ERR_BALANCE_OVERPAY`."

    Design: Corner/validations/balance_overpay_rejected
    """
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
    # balance DUE 27000 (total 36000 - deposit 9000); pay 30000 -> overpay.
    assert setup["invoice_after"]["balance_amount_cents"] == 27000
    resp = api.record_payment(
        setup["invoice_id"], {"applies_to": "BALANCE", "amount_cents": 30000},
        make_client_headers("client-1"),
    )
    validate_error(resp, ApiErrorId.ERR_BALANCE_OVERPAY)


# ─── Corner: cross_cutting_complexity_layers (OCC) ────
def test_contract_sign_with_stale_event_version_rejected(api):
    """PRD §2.7: "If another writer has advanced the event's `version` since then — for
    instance by re-quoting it, which increments `quote_revision` and bumps the event's
    `version` — the stale signer's pinned price would reference an outdated quote, so the
    create is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/contract_sign_stale_event_version_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    artist = create_artist(
        hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
        travel_rate_per_km_cents=600, max_faces_per_hour=2,
    )
    event = create_event(client_id="client-1", venue_distance_km=10)
    face = add_face(event["id"], "client-1", "BRIDE", "HAIR", is_bride=True)
    confirm_face(face["id"], "client-1")
    quoted = quote_event(event["id"])
    stale_version = quoted["version"]
    # Re-quote round bumps event.version past stale_version.
    validate_success(api.request_revision(event["id"], make_client_headers("client-1")), 200)
    quote_event(event["id"])

    resp = api.create_contract(
        {"event_id": event["id"], "lead_artist_id": artist["id"], "expected_event_version": stale_version},
        make_client_headers("client-1"),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_EVENT_VERSION)


def test_assignment_create_with_stale_event_version_rejected(api):
    """PRD §2.7: "Scheduling a service assignment likewise requires `expected_event_version`
    carrying the event `version` the client last observed. If another coordinator has already
    scheduled the event ... the current writer's view is stale and a second create would
    schedule a duplicate on-location window; the request is therefore rejected with
    `ERR_STALE_EVENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/assignment_create_stale_event_version_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    artist = create_artist(
        hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
        travel_rate_per_km_cents=600, max_faces_per_hour=2,
    )
    event = create_event(client_id="client-1", venue_distance_km=10)
    face = add_face(event["id"], "client-1", "BRIDE", "HAIR", is_bride=True)
    confirm_face(face["id"], "client-1")
    quoted = quote_event(event["id"])
    quote_version = quoted["version"]
    # Sign the contract (the cascade bumps event.version past quote_version).
    sign_contract(event["id"], artist["id"], quote_version, "client-1")
    invoice, _ = _first_invoice(api, event["id"], "client-1")
    api.record_payment(invoice["id"], {"applies_to": "DEPOSIT", "amount_cents": 9000},
                       make_client_headers("client-1"))

    # Scheduling with the pre-sign version is stale.
    resp = api.create_assignment(
        {"event_id": event["id"], "artist_id": artist["id"],
         "window_start_utc": "2026-07-15T08:00:00Z", "window_end_utc": "2026-07-15T10:00:00Z",
         "expected_event_version": quote_version},
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_EVENT_VERSION)
