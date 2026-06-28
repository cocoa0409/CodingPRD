"""Second-pass tests for the depth (difficulty) queue. Each difficulty instance is covered
by two tests; this file holds the complementary angle (the other boundary side, the positive
branch, an alternate input, or a different conserved-quantity hop) for every instance.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_quoted_event,
    setup_contracted_event,
    setup_deposit_paid_event,
    setup_scheduled_event,
    setup_balance_due_event,
    sign_contract,
    schedule_assignment,
    apply_addon,
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


# ─── dual_variant_calc ────────────────────────────────
def test_contract_excludes_pending_face_quote_includes_it(api):
    """PRD §3.4: "It differs from the estimate in two ways: it counts only `CONFIRMED` faces
    (pending faces are excluded), and it prices them at the lead artist's *pinned* rates
    rather than the cheapest-lead selector."
    PRD §3.4: "It counts every face the client might bring — those in `PENDING` *or*
    `CONFIRMED` status".

    Design: Difficulty/dual_variant_calc/quote_vs_contract_total_diverge
    """
    setup = setup_quoted_event(
        client_id="client-1",
        artist_overrides=dict(
            hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
            travel_rate_per_km_cents=0, max_faces_per_hour=4,
        ),
        event_overrides=dict(venue_distance_km=0),
        faces=[
            {"person_label": "BRIDE", "service_type": "HAIR", "is_bride": False, "confirm": True},
            {"person_label": "BM_PENDING", "service_type": "HAIR", "confirm": False},
        ],
    )
    # Quote counts both HAIR faces: 20000 + 20000 = 40000.
    assert setup["event"]["estimated_total_cents"] == 40000
    contract = sign_contract(setup["event_id"], setup["lead_artist_id"], setup["quote_version"], "client-1")
    # Contract counts only the CONFIRMED face: 20000.
    assert contract["contracted_total_cents"] == 20000, (
        f"Expected 20000 (CONFIRMED only), got {contract['contracted_total_cents']}"
    )
    assert contract["contracted_total_cents"] != setup["event"]["estimated_total_cents"]


def test_cancellation_relief_writes_off_full_outstanding_balance(api):
    """PRD §3.16: "Whenever an outstanding balance exists at cancellation, the `balance_status`
    advances from `DUE` to `WRITTEN_OFF`, with `balance_relief_cents` equal to that outstanding
    balance and `balance_amount_cents` driven to zero."
    PRD §3.16: "Under `FULL_FORFEIT`, `deposit_refund_cents` is zero and `balance_relief_cents`
    is the whole outstanding balance written off, with the deposit kept and any unpaid balance
    forfeited to the platform as liquidated damages."

    Design: Difficulty/dual_variant_calc/balance_addon_vs_cancellation_relief_diverge
    """
    setup = setup_balance_due_event(
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
        window_start_utc="2026-07-15T01:00:00Z", window_end_utc="2026-07-15T03:00:00Z",
        start_clock="2026-07-15T01:00:00Z",
    )
    # balance DUE 27000 (total 36000 - deposit 9000). Cancel 12h before -> FULL_FORFEIT.
    assert setup["invoice_after"]["balance_amount_cents"] == 27000
    set_clock("2026-07-15T08:00:00Z")
    record = validate_success(
        api.cancel_event(setup["event_id"], {"reason": "CLIENT_CHOICE"}, make_client_headers("client-1")), 200
    )
    assert record["balance_relief_cents"] == 27000, (
        f"Expected balance_relief 27000, got {record['balance_relief_cents']}"
    )
    invoice = validate_success(api.get_invoice(setup["invoice_id"], make_client_headers("client-1")), 200)
    assert invoice["balance_status"] == "WRITTEN_OFF"
    assert invoice["balance_amount_cents"] == 0


# ─── combinatorial_formula ────────────────────────────
def test_single_bride_line_rounds_half_up(api):
    """PRD §3.4: "A bride face's base is multiplied by the same 1.5 surcharge multiplier and
    rounded half-up to a whole cent on that line."

    Design: Difficulty/combinatorial_formula/per_line_bride_rounding_before_sum
    """
    setup = setup_quoted_event(
        client_id="client-5",
        artist_overrides=dict(
            hair_rate_per_face_cents=10001, makeup_rate_per_face_cents=10000,
            travel_rate_per_km_cents=0, max_faces_per_hour=4,
        ),
        event_overrides=dict(venue_distance_km=0),
        faces=[{"person_label": "BRIDE", "service_type": "BOTH", "is_bride": True, "confirm": True}],
    )
    contract = sign_contract(setup["event_id"], setup["lead_artist_id"], setup["quote_version"], "client-5")
    # base 20001, *1.5 = 30001.5 -> rounds half-up to 30002.
    assert contract["contracted_total_cents"] == 30002, (
        f"Expected 30002 (round-half-up), got {contract['contracted_total_cents']}"
    )


def test_deposit_tier_high_band_at_40_percent(api):
    """PRD §3.7: "If it is 200,000 cents or more, the percentage is 40 percent."

    Design: Difficulty/combinatorial_formula/deposit_tier_selection_three_inputs
    """
    setup = setup_quoted_event(
        client_id="client-6",
        artist_overrides=dict(
            hair_rate_per_face_cents=100000, makeup_rate_per_face_cents=100000,
            travel_rate_per_km_cents=0, max_faces_per_hour=4,
        ),
        event_overrides=dict(venue_distance_km=0),
        faces=[{"person_label": "GUEST", "service_type": "BOTH", "is_bride": False, "confirm": True}],
    )
    contract = sign_contract(setup["event_id"], setup["lead_artist_id"], setup["quote_version"], "client-6")
    # total 200000 -> HIGH band 0.40 -> 80000.
    assert contract["contracted_total_cents"] == 200000
    assert contract["deposit_due_cents"] == 80000, (
        f"Expected deposit 80000 in HIGH band, got {contract['deposit_due_cents']}"
    )


# ─── non_linear_state_machine ─────────────────────────
def test_request_revision_clears_estimated_total(api):
    """PRD §3.3: "A `Client` who is unhappy with a quote may request a revision, moving the
    event from `QUOTED` to `REVISION_REQUESTED`. This is permitted only when the acting client
    owns the event and no signed contract yet exists for it; the side effect is to clear
    `estimated_total_cents` back to 0."

    Design: Difficulty/non_linear_state_machine/event_quote_revision_cycle
    """
    setup = setup_quoted_event(
        client_id="client-1",
        artist_overrides=dict(
            hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
            travel_rate_per_km_cents=600, max_faces_per_hour=2,
        ),
        event_overrides=dict(venue_distance_km=10),
        faces=[{"person_label": "BRIDE", "service_type": "BOTH", "is_bride": True, "confirm": True}],
    )
    assert setup["event"]["estimated_total_cents"] > 0
    revised = validate_success(api.request_revision(setup["event_id"], make_client_headers("client-1")), 200)
    assert revised["status"] == "REVISION_REQUESTED"
    assert revised["estimated_total_cents"] == 0, (
        f"Expected estimated_total cleared to 0, got {revised['estimated_total_cents']}"
    )


def test_deposit_paid_leaves_balance_axis_not_due(api):
    """PRD §3.9: "A successful, exact deposit payment advances `deposit_status` from `DUE` to
    `PAID`, increments `amount_paid_cents`, and recomputes `balance_amount_cents`."
    PRD §3.9: "The balance axis only becomes collectible — `balance_status` moving from
    `NOT_DUE` to `DUE` — as a system side effect when a service assignment reaches `COMPLETED`
    while the deposit is already `PAID`."

    Design: Difficulty/non_linear_state_machine/invoice_parallel_deposit_and_balance_axes
    """
    setup = setup_deposit_paid_event(
        client_id="client-1",
        artist_overrides=dict(
            hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
            travel_rate_per_km_cents=600, max_faces_per_hour=2,
        ),
        event_overrides=dict(venue_distance_km=10),
        faces=[{"person_label": "BRIDE", "service_type": "HAIR", "is_bride": True, "confirm": True}],
    )
    # Deposit just paid; no assignment completed yet -> deposit PAID, balance still NOT_DUE.
    invoice = validate_success(api.get_invoice(setup["invoice_id"], make_client_headers("client-1")), 200)
    assert invoice["deposit_status"] == "PAID"
    assert invoice["balance_status"] == "NOT_DUE", (
        f"Expected balance_status NOT_DUE before assignment completes, got {invoice['balance_status']}"
    )


# ─── transitive_cascade ───────────────────────────────
def test_event_cancel_voids_contract_in_cascade(api):
    """PRD §3.16: "In both cases the signed contract is voided as a system consequence — a
    `SIGNED` contract whose owning event transitions to `CANCELLED` moves to `VOIDED` and is no
    longer billable".

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
        faces=[{"person_label": "BRIDE", "service_type": "HAIR", "is_bride": True, "confirm": True}],
    )
    set_clock("2026-07-14T08:00:00Z")
    validate_success(api.cancel_event(setup["event_id"], {"reason": "CLIENT_CHOICE"}, make_client_headers("client-1")), 200)
    contract = validate_success(api.get_contract(setup["contract_id"], make_client_headers("client-1")), 200)
    assert contract["status"] == "VOIDED", f"Expected contract VOIDED, got {contract['status']}"


def test_assignment_cancel_reverses_extended_stay_addon(api):
    """PRD §3.14: "reverses every `APPLIED` add-on on that assignment to `REVERSED`, and
    re-runs the balance reconciliation so the invoice's `balance_amount_cents` drops by the
    reversed add-on charges."

    Design: Difficulty/transitive_cascade/assignment_cancel_reverse_addon_balance_cascade
    """
    setup = setup_scheduled_event(
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
    )
    # contract total 36000, deposit 9000 -> balance 27000. EXTENDED_STAY qty 1 -> +8000 = 35000.
    addon = apply_addon(setup["assignment_id"], "EXTENDED_STAY", 1)
    inv_mid = validate_success(api.get_invoice(setup["invoice_id"], make_client_headers("client-1")), 200)
    assert inv_mid["balance_amount_cents"] == 35000
    validate_success(api.cancel_assignment(setup["assignment_id"], COORD), 200)
    addons = validate_success(api.list_addons(setup["assignment_id"], COORD), 200)
    assert next(a for a in addons if a["id"] == addon["id"])["status"] == "REVERSED"
    inv = validate_success(api.get_invoice(setup["invoice_id"], make_client_headers("client-1")), 200)
    assert inv["balance_amount_cents"] == 27000, (
        f"Expected balance back to 27000, got {inv['balance_amount_cents']}"
    )


# ─── priority_pair_validation_conflict ────────────────
def test_artist_not_active_fires_when_trial_satisfied(api):
    """PRD §3.6: "The nominated lead artist must have `status` `ACTIVE`; a non-active lead is
    rejected with `ERR_ARTIST_NOT_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/trial_referential_beats_artist_constraint
    """
    set_clock("2026-06-01T00:00:00Z")
    artist = create_artist(
        hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
        travel_rate_per_km_cents=600, max_faces_per_hour=2,
    )
    # trial_required FALSE so the trial check passes; only the artist-active check can fail.
    event = create_event(client_id="client-1", venue_distance_km=10, trial_required=False)
    face = add_face(event["id"], "client-1", "BRIDE", "HAIR", is_bride=True)
    confirm_face(face["id"], "client-1")
    quoted = quote_event(event["id"])
    validate_success(
        api.patch_artist(artist["id"], {"status": "SUSPENDED", "expected_artist_version": artist["version"]}, COORD), 200
    )
    resp = api.create_contract(
        {"event_id": event["id"], "lead_artist_id": artist["id"], "expected_event_version": quoted["version"]},
        make_client_headers("client-1"),
    )
    validate_error(resp, ApiErrorId.ERR_ARTIST_NOT_ACTIVE)


def test_balance_payment_succeeds_once_due_and_deposit_paid(api):
    """PRD §3.9: "A balance payment that clears the balance (so the post-payment
    `balance_amount_cents` is zero) is permitted only when `deposit_status` is `PAID`, advances
    `balance_status` from `DUE` to `PAID`, increments `amount_paid_cents`, and sets
    `balance_amount_cents` to zero."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_balance_payment
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
    # balance DUE 27000, deposit PAID -> exact balance payment clears it.
    assert setup["invoice_after"]["balance_amount_cents"] == 27000
    validate_success(
        api.record_payment(setup["invoice_id"], {"applies_to": "BALANCE", "amount_cents": 27000},
                           make_client_headers("client-1")),
        201,
    )
    invoice = validate_success(api.get_invoice(setup["invoice_id"], make_client_headers("client-1")), 200)
    assert invoice["balance_status"] == "PAID"
    assert invoice["balance_amount_cents"] == 0


# ─── boundary_precision_check ─────────────────────────
def test_deposit_tier_boundary_just_below_50000(api):
    """PRD §3.7: "If it is below 50,000 cents, the deposit percentage is 25 percent."

    Design: Difficulty/boundary_precision_check/deposit_tier_boundary_at_50000
    """
    setup = setup_quoted_event(
        client_id="client-4",
        artist_overrides=dict(
            hair_rate_per_face_cents=24999, makeup_rate_per_face_cents=25000,
            travel_rate_per_km_cents=0, max_faces_per_hour=4,
        ),
        event_overrides=dict(venue_distance_km=0),
        faces=[{"person_label": "GUEST", "service_type": "BOTH", "is_bride": False, "confirm": True}],
    )
    contract = sign_contract(setup["event_id"], setup["lead_artist_id"], setup["quote_version"], "client-4")
    # total 49999 -> LOW band 0.25 -> round(12499.75) = 12500.
    assert contract["contracted_total_cents"] == 49999
    assert contract["deposit_due_cents"] == 12500, (
        f"Expected deposit 12500 just below the boundary, got {contract['deposit_due_cents']}"
    )


def test_throughput_one_face_short_rejected(api):
    """PRD §3.12: "if the capacity equals the confirmed count exactly, the window passes, but
    if it falls even one face short the schedule is rejected with `ERR_INSUFFICIENT_THROUGHPUT`."

    Design: Difficulty/boundary_precision_check/throughput_capacity_exactly_meets_faces
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
    # 3 confirmed, cap 2/hr, 1h window -> floor(2)=2 == confirmed-1 -> FAILS.
    resp = api.create_assignment(
        {"event_id": setup["event_id"], "artist_id": setup["lead_artist_id"],
         "window_start_utc": "2026-07-15T08:00:00Z", "window_end_utc": "2026-07-15T09:00:00Z",
         "expected_event_version": setup["post_deposit_version"]},
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_THROUGHPUT)


# ─── cross_entity_state_dependency ────────────────────
def test_contract_rejected_when_required_trial_not_completed(api):
    """PRD §3.6: "If the event's `trial_required` flag is set, a trial session for this event
    must already be in `COMPLETED` status — otherwise the sign is rejected with
    `ERR_TRIAL_NOT_COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/contract_requires_trial_completed
    """
    set_clock("2026-06-01T00:00:00Z")
    artist = create_artist(
        hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
        travel_rate_per_km_cents=600, max_faces_per_hour=2,
    )
    event = create_event(client_id="client-1", venue_distance_km=10, trial_required=True)
    face = add_face(event["id"], "client-1", "BRIDE", "HAIR", is_bride=True)
    confirm_face(face["id"], "client-1")
    quoted = quote_event(event["id"])
    # A trial is booked but NOT completed.
    book_trial(event["id"], artist["id"], "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z")
    resp = api.create_contract(
        {"event_id": event["id"], "lead_artist_id": artist["id"], "expected_event_version": quoted["version"]},
        make_client_headers("client-1"),
    )
    validate_error(resp, ApiErrorId.ERR_TRIAL_NOT_COMPLETED)


def test_event_completes_and_services_faces_when_gates_pass(api):
    """PRD §3.15: "A `Coordinator` completes an event, advancing it from `SCHEDULED` to
    `COMPLETED`, only when every service assignment on the event is in `COMPLETED` status and
    the invoice's `balance_status` is `PAID`."
    PRD §3.15: "Completing the event transitions every `CONFIRMED` booking face to `SERVICED`."

    Design: Difficulty/cross_entity_state_dependency/event_complete_requires_assignments_and_balance
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
    bride_face_id = setup["faces"][0]["id"]
    # Pay the balance so balance_status -> PAID; both gates now satisfied.
    validate_success(
        api.record_payment(setup["invoice_id"], {"applies_to": "BALANCE", "amount_cents": 27000},
                           make_client_headers("client-1")),
        201,
    )
    completed = validate_success(api.complete_event(setup["event_id"], COORD), 200)
    assert completed["status"] == "COMPLETED"
    faces = validate_success(api.list_faces(setup["event_id"], COORD), 200)
    assert next(f for f in faces if f["id"] == bride_face_id)["status"] == "SERVICED"


# ─── resource_temporal_overlap ────────────────────────
def test_trial_adjacency_at_end_utc_allowed(api):
    """PRD §3.5: "two windows that merely touch end-to-start are allowed, but any genuine
    overlap is rejected with `ERR_TRIAL_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/trial_overlap_closed_open_no_buffer
    """
    set_clock("2026-06-01T00:00:00Z")
    artist = create_artist(
        hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
        travel_rate_per_km_cents=600, max_faces_per_hour=2,
    )
    event = create_event(client_id="client-1", venue_distance_km=10, trial_required=True)
    book_trial(event["id"], artist["id"], "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z")
    # Second trial starting exactly at the first's end_utc (10:00) is adjacency -> allowed.
    resp = api.create_trial(
        {"event_id": event["id"], "artist_id": artist["id"],
         "start_utc": "2026-06-10T10:00:00Z", "end_utc": "2026-06-10T11:00:00Z", "trial_fee_cents": 5000},
        COORD,
    )
    trial2 = validate_success(resp, 201)
    assert trial2["status"] == "BOOKED"


def test_assignment_adjacency_at_60_min_gap_allowed(api):
    """PRD §3.11: "Two windows separated by exactly the 60-minute gap are adjacent and allowed;
    anything closer is rejected with `ERR_ASSIGNMENT_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/assignment_overlap_with_travel_buffer
    """
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
    # Second window for the SAME lead [10:00, 11:00): starts exactly 60 min after A ends -> allowed.
    eventB = _second_event_for_lead(api, lead_id, "client-9")
    resp = api.create_assignment(
        {"event_id": eventB["event_id"], "artist_id": lead_id,
         "window_start_utc": "2026-07-15T10:00:00Z", "window_end_utc": "2026-07-15T11:00:00Z",
         "expected_event_version": eventB["post_deposit_version"]},
        COORD,
    )
    assignment = validate_success(resp, 201)
    assert assignment["status"] == "SCHEDULED"


def _second_event_for_lead(api, lead_artist_id, client_id):
    event = create_event(
        client_id=client_id, event_date_utc="2026-07-15T20:00:00Z",
        ready_by_utc="2026-07-15T20:00:00Z", venue_distance_km=5,
    )
    face = add_face(event["id"], client_id, "BRIDE", "HAIR", is_bride=True)
    confirm_face(face["id"], client_id)
    quoted = quote_event(event["id"])
    contract = sign_contract(event["id"], lead_artist_id, quoted["version"], client_id)
    from test_helpers import validate_paginated
    items, _ = validate_paginated(api.list_invoices(make_client_headers(client_id), params={"event_id": event["id"]}))
    pay_deposit(items[0]["id"], contract["deposit_due_cents"], client_id)
    ev = validate_success(api.get_event(event["id"], COORD), 200)
    return {"event_id": event["id"], "post_deposit_version": ev["version"]}


# ─── compensating_invariant ───────────────────────────
def test_single_touch_up_apply_then_reverse_restores_balance(api):
    """PRD §3.14: "re-runs the balance reconciliation so the invoice's `balance_amount_cents`
    drops by the reversed add-on charges."
    PRD §3.8: "Once at least one add-on has been applied, the reconciled balance includes those
    add-on amounts and therefore diverges from the bare contracted baseline."

    Design: Difficulty/compensating_invariant/addon_apply_reverse_conserves_balance
    """
    setup = setup_scheduled_event(
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
    )
    # baseline balance = 36000 - 9000 = 27000. TOUCH_UP qty 1 -> +round(25000*0.5)=12500 -> 39500.
    addon = apply_addon(setup["assignment_id"], "TOUCH_UP", 1)
    mid = validate_success(api.get_invoice(setup["invoice_id"], make_client_headers("client-1")), 200)
    assert mid["balance_amount_cents"] == 39500
    validate_success(api.cancel_assignment(setup["assignment_id"], COORD), 200)
    addons = validate_success(api.list_addons(setup["assignment_id"], COORD), 200)
    assert next(a for a in addons if a["id"] == addon["id"])["status"] == "REVERSED"
    inv = validate_success(api.get_invoice(setup["invoice_id"], make_client_headers("client-1")), 200)
    assert inv["balance_amount_cents"] == 27000, (
        f"Expected balance restored to 27000, got {inv['balance_amount_cents']}"
    )


def test_cancelled_window_no_longer_blocks_overlapping_slot(api):
    """PRD §3.11: "rejects the schedule if that expanded interval intersects any of that
    artist's existing non-cancelled assignment windows (any assignment whose `status` is not
    `CANCELLED`)."
    PRD §3.14: "Cancelling releases the artist's window (so it no longer blocks future bookings
    via the travel buffer)".

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
        faces=[{"person_label": "BRIDE", "service_type": "HAIR", "is_bride": True, "confirm": True}],
    )
    lead_id = setup["lead_artist_id"]
    a1 = schedule_assignment(
        setup["event_id"], lead_id, setup["post_deposit_version"],
        window_start_utc="2026-07-15T08:00:00Z", window_end_utc="2026-07-15T09:00:00Z",
    )
    validate_success(api.cancel_assignment(a1["id"], COORD), 200)
    # On a fresh event for the SAME lead, a window [08:30, 09:30) that directly OVERLAPS a1's
    # window would be blocked by a live window — but the cancelled one no longer blocks.
    other = _second_event_for_lead(api, lead_id, "client-9")
    a2 = schedule_assignment(
        other["event_id"], lead_id, other["post_deposit_version"],
        window_start_utc="2026-07-15T08:30:00Z", window_end_utc="2026-07-15T09:30:00Z",
    )
    assert a2["status"] == "SCHEDULED"
    a1_after = validate_success(api.get_assignment(a1["id"], COORD), 200)
    assert a1_after["status"] == "CANCELLED"
