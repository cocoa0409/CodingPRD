"""Cascades, threshold triggers, and conservation invariants: pack depletion
pausing the engagement, no-show strikes suspending privilege, free-cancel seat
restoration, end-of-engagement wallet conservation, and the end cascade's
plan/program transitions.

Depth (queue A): transitive_cascade, compensating_invariant.
Breadth (queue B): state_machines side-effect instances.
"""
from test_helpers import (
    validate_success,
    api_client,
    set_clock,
    setup_pack_engagement, setup_subscription_engagement,
    setup_provisional_macro_plan,
    create_pack, get_pack, book_pack_session, book_subscription_session,
    create_published_program,
    make_trainer_headers, make_client_headers,
)


# ─── transitive_cascade / booking_depletes_pack_pauses_engagement ────────────

def test_final_booking_depletes_pack_and_pauses_engagement(api):
    """PRD §3.3: "When a committing booking drives `sessions_remaining` to zero,
    the pack moves from `ACTIVE` to `DEPLETED`, and that depletion bubbles up to
    pause the parent engagement: the engagement moves `ACTIVE` → `PAUSED` with
    `pause_reason` set to `PACK_DEPLETED`."

    A pack of 1 seat: the single booking drives sessions_remaining to 0, depletes
    the pack, and bubbles up to pause the engagement (PACK_DEPLETED).

    Design: Difficulty/transitive_cascade/booking_depletes_pack_pauses_engagement
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-01T00:00:00Z",
                                total_sessions=1, price_cents=10000)
    t_id, e_id, pack = ctx["trainer"]["id"], ctx["engagement"]["id"], ctx["pack"]
    book_pack_session(t_id, e_id, pack["id"], pack["version"],
                      "2026-06-05T10:00:00Z", "2026-06-05T11:00:00Z")

    refreshed_pack = get_pack(t_id, pack["id"])
    assert refreshed_pack["sessions_remaining"] == 0
    assert refreshed_pack["status"] == "DEPLETED"
    eng = validate_success(api.get_engagement(e_id, make_trainer_headers(t_id)))
    assert eng["status"] == "PAUSED"
    assert eng["pause_reason"] == "PACK_DEPLETED"


def test_pack_depletion_sets_pack_depleted_status(api):
    """PRD §3.3: "A pack's lifecycle status reacts to seat movement. When a
    committing booking drives `sessions_remaining` to zero, the pack moves from
    `ACTIVE` to `DEPLETED`"

    The first cascade link: a single-seat pack reaches DEPLETED on the committing
    booking.

    Design: Difficulty/transitive_cascade/booking_depletes_pack_pauses_engagement
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-01T00:00:00Z",
                                total_sessions=1, price_cents=10000)
    t_id, e_id, pack = ctx["trainer"]["id"], ctx["engagement"]["id"], ctx["pack"]
    book_pack_session(t_id, e_id, pack["id"], pack["version"],
                      "2026-06-05T10:00:00Z", "2026-06-05T11:00:00Z")
    refreshed = get_pack(t_id, pack["id"])
    assert refreshed["status"] == "DEPLETED"
    assert refreshed["sessions_remaining"] == 0


# ─── transitive_cascade / no_show_strike_suspends_privilege ──────────────────

def test_third_no_show_suspends_booking_privilege(api):
    """PRD §3.4: "A client's `no_show_strikes` is the count of that client's
    bookings, across all of their engagements, that ended in either `NO_SHOW` or
    `LATE_CANCELLED`. Whenever a booking enters one of those two states, the count
    is recomputed; the moment it reaches three or more, the client's
    `booking_privilege` flips to `SUSPENDED` (it is `ALLOWED` while the count stays
    below three)."

    Two prior NO_SHOW bookings (strikes=2, still ALLOWED); the third no-show
    recomputes strikes to 3 and flips booking_privilege to SUSPENDED.

    Design: Difficulty/transitive_cascade/no_show_strike_suspends_privilege
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-01T00:00:00Z",
                                total_sessions=5, price_cents=50000)
    t_id, c_id, e_id, pack = (ctx["trainer"]["id"], ctx["client"]["id"],
                              ctx["engagement"]["id"], ctx["pack"])
    th = make_trainer_headers(t_id)
    # Three future bookings.
    b1 = book_pack_session(t_id, e_id, pack["id"], pack["version"],
                           "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z")
    pv1 = get_pack(t_id, pack["id"])["version"]
    b2 = book_pack_session(t_id, e_id, pack["id"], pv1,
                           "2026-06-03T10:00:00Z", "2026-06-03T11:00:00Z")
    pv2 = get_pack(t_id, pack["id"])["version"]
    b3 = book_pack_session(t_id, e_id, pack["id"], pv2,
                           "2026-06-04T10:00:00Z", "2026-06-04T11:00:00Z")
    set_clock("2026-06-04T12:00:00Z")
    validate_success(api.mark_no_show(b1["id"], th))
    validate_success(api.mark_no_show(b2["id"], th))
    # still ALLOWED at 2 strikes.
    mid = validate_success(api.get_client(c_id, th))
    assert mid["no_show_strikes"] == 2
    assert mid["booking_privilege"] == "ALLOWED"

    b3_final = validate_success(api.mark_no_show(b3["id"], th))
    assert b3_final["status"] == "NO_SHOW"
    client = validate_success(api.get_client(c_id, th))
    assert client["no_show_strikes"] == 3
    assert client["booking_privilege"] == "SUSPENDED"


def test_no_show_recomputes_strike_count(api):
    """PRD §3.5: "A no-show also counts as a strike, recomputing `no_show_strikes`
    and suspending the client's `booking_privilege` if it reaches three or more."

    The third no-show recomputes the strike total to 3.

    Design: Difficulty/transitive_cascade/no_show_strike_suspends_privilege
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-01T00:00:00Z",
                                total_sessions=5, price_cents=50000)
    t_id, c_id, e_id, pack = (ctx["trainer"]["id"], ctx["client"]["id"],
                              ctx["engagement"]["id"], ctx["pack"])
    th = make_trainer_headers(t_id)
    b1 = book_pack_session(t_id, e_id, pack["id"], pack["version"],
                           "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z")
    pv1 = get_pack(t_id, pack["id"])["version"]
    b2 = book_pack_session(t_id, e_id, pack["id"], pv1,
                           "2026-06-03T10:00:00Z", "2026-06-03T11:00:00Z")
    pv2 = get_pack(t_id, pack["id"])["version"]
    b3 = book_pack_session(t_id, e_id, pack["id"], pv2,
                           "2026-06-04T10:00:00Z", "2026-06-04T11:00:00Z")
    set_clock("2026-06-04T12:00:00Z")
    validate_success(api.mark_no_show(b1["id"], th))
    validate_success(api.mark_no_show(b2["id"], th))
    validate_success(api.mark_no_show(b3["id"], th))
    client = validate_success(api.get_client(c_id, th))
    assert client["no_show_strikes"] == 3, f"got {client['no_show_strikes']}"


# ─── compensating_invariant / cancel_restores_pack_seat_conservation ─────────

def test_free_cancel_restores_pack_seat(api):
    """PRD §3.5: "for a `SESSION_PACK` booking its seat is released (the committed
    count drops by one), a `DEPLETED` pack returns to `ACTIVE`, and
    `fee_charged_cents` stays 0."
    PRD §3.3: "The available count, `sessions_remaining`, is `total_sessions`
    minus `sessions_committed`"

    A far-future booking on a pack of 5 commits one seat; a free (>=24h) cancel
    releases it, returning sessions_remaining to its pre-booking value 5 with no
    fee.

    Design: Difficulty/compensating_invariant/cancel_restores_pack_seat_conservation
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-01T00:00:00Z",
                                total_sessions=5, price_cents=50000)
    t_id, c_id, e_id, pack = (ctx["trainer"]["id"], ctx["client"]["id"],
                              ctx["engagement"]["id"], ctx["pack"])
    b = book_pack_session(t_id, e_id, pack["id"], pack["version"],
                          "2026-06-20T10:00:00Z", "2026-06-20T11:00:00Z")
    committed = get_pack(t_id, pack["id"])
    assert committed["sessions_remaining"] == 4

    cancelled = validate_success(api.cancel_booking(b["id"], make_client_headers(c_id)))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["fee_charged_cents"] == 0
    refreshed = get_pack(t_id, pack["id"])
    assert refreshed["sessions_remaining"] == 5, f"got {refreshed['sessions_remaining']}"


def test_free_cancel_charges_no_fee(api):
    """PRD §3.5: "If the cancellation arrives at least twenty-four hours before the
    session starts — that is, the gap from the logical clock to `start_utc` is at
    least 86,400 seconds — the booking moves to `CANCELLED` free of charge"

    A cancel of a far-future booking keeps fee_charged_cents at 0 (no money
    created or destroyed on the wallet ledger).

    Design: Difficulty/compensating_invariant/cancel_restores_pack_seat_conservation
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-01T00:00:00Z",
                                total_sessions=5, price_cents=50000)
    t_id, c_id, e_id, pack = (ctx["trainer"]["id"], ctx["client"]["id"],
                              ctx["engagement"]["id"], ctx["pack"])
    b = book_pack_session(t_id, e_id, pack["id"], pack["version"],
                          "2026-06-20T10:00:00Z", "2026-06-20T11:00:00Z")
    cancelled = validate_success(api.cancel_booking(b["id"], make_client_headers(c_id)))
    assert cancelled["fee_charged_cents"] == 0


# ─── compensating_invariant / engagement_end_refund_wallet_conservation ──────

def test_engagement_end_refunds_full_unused_pack_value(api):
    """PRD §3.3: "The refund added to `wallet_credit_cents` is the number of unused
    seats (the pack's `total_sessions` minus the count of truly consumed seats)
    multiplied by `per_session_value_cents`."
    PRD §3.2: "each `ACTIVE` session pack that still has seats remaining refunds
    the value of those remaining seats into the engagement's `wallet_credit_cents`
    and is then marked `REFUNDED`"

    With 5 paid seats and none consumed, ending refunds 5*10000 == 50000 == the
    price paid; no value created or lost.

    Design: Difficulty/compensating_invariant/engagement_end_refund_wallet_conservation
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-01T00:00:00Z",
                                total_sessions=5, price_cents=50000)
    t_id, e_id, pack = ctx["trainer"]["id"], ctx["engagement"]["id"], ctx["pack"]
    eng = validate_success(api.end_engagement(e_id, make_trainer_headers(t_id)))
    assert eng["wallet_credit_cents"] == 50000, f"got {eng['wallet_credit_cents']}"
    assert eng["status"] == "ENDED"
    refreshed = get_pack(t_id, pack["id"])
    assert refreshed["status"] == "REFUNDED"


def test_engagement_end_marks_unused_pack_refunded(api):
    """PRD §3.2: "for a `SESSION_PACK` engagement, each `ACTIVE` session pack that
    still has seats remaining refunds the value of those remaining seats into the
    engagement's `wallet_credit_cents` and is then marked `REFUNDED`"

    The pack with all seats unused transitions to REFUNDED on engagement end.

    Design: Difficulty/compensating_invariant/engagement_end_refund_wallet_conservation
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-01T00:00:00Z",
                                total_sessions=5, price_cents=50000)
    t_id, e_id, pack = ctx["trainer"]["id"], ctx["engagement"]["id"], ctx["pack"]
    validate_success(api.end_engagement(e_id, make_trainer_headers(t_id)))
    refreshed = get_pack(t_id, pack["id"])
    assert refreshed["status"] == "REFUNDED"


# ─── Corner: state_machines / end_engagement_archives_programs_cascade ───────

def test_end_engagement_archives_program_and_locks_macro_plan(api):
    """PRD §3.2: "any `MacroPlan` still in `PROVISIONAL` is moved to `LOCKED`,
    freezing its numbers. Fifth, any `ProgramAssignment` in `DRAFT` or `PUBLISHED`
    is moved to `ARCHIVED`."

    Ending an engagement cascades a PUBLISHED program to ARCHIVED and a PROVISIONAL
    macro plan to LOCKED.

    Design: Corner/state_machines/end_engagement_archives_programs_cascade
    """
    ctx = setup_provisional_macro_plan(clock_utc="2026-06-01T00:00:00Z",
                                       weight_kg=80,
                                       client_overrides={"sex": "MALE",
                                                         "birth_year": 1996,
                                                         "height_cm": 180})
    t_id, e_id, mp = ctx["trainer"]["id"], ctx["engagement"]["id"], ctx["macro_plan"]
    prog = create_published_program(t_id, e_id)
    validate_success(api.end_engagement(e_id, make_trainer_headers(t_id)))

    prog_final = validate_success(api.get_program_assignment(prog["id"], make_trainer_headers(t_id)))
    assert prog_final["status"] == "ARCHIVED"
    mp_final = validate_success(api.get_macro_plan(mp["id"], make_trainer_headers(t_id)))
    assert mp_final["status"] == "LOCKED"


# ─── Corner: state_machines / subscription_late_cancel_charges_zero_fee ──────

def test_subscription_late_cancel_zero_fee(api):
    """PRD §3.5: "If instead the cancellation arrives within that twenty-four-hour
    window — the gap is strictly less than 86,400 seconds — the booking is routed
    to `LATE_CANCELLED` instead"
    PRD §3.5: "for an `ONLINE_SUBSCRIPTION` engagement the fee is 0."

    An ONLINE_SUBSCRIPTION booking late-cancelled (12h ahead) becomes
    LATE_CANCELLED with fee_charged_cents == 0.

    Design: Corner/state_machines/subscription_late_cancel_charges_zero_fee
    """
    ctx = setup_subscription_engagement(clock_utc="2026-06-05T00:00:00Z",
                                        cycle_start_utc="2026-06-05T00:00:00Z")
    t_id, c_id, e_id = ctx["trainer"]["id"], ctx["client"]["id"], ctx["engagement"]["id"]
    b = book_subscription_session(t_id, e_id, "2026-06-05T12:00:00Z",
                                  "2026-06-05T13:00:00Z", as_client_id=c_id)
    cancelled = validate_success(api.cancel_booking(b["id"], make_client_headers(c_id)))
    assert cancelled["status"] == "LATE_CANCELLED"
    assert cancelled["fee_charged_cents"] == 0


# ─── Corner: state_machines / pack_late_cancel_charges_half_fee ──────────────

def test_pack_late_cancel_charges_half_per_session_value(api):
    """PRD §3.5: "For a `SESSION_PACK` engagement the `fee_charged_cents` is the
    pack's `per_session_value_cents` multiplied by the no-show fee rate of 50
    percent (0.50), rounded half-up to a whole cent"
    PRD §3.5: "the seat stays committed (the session is treated as consumed)"

    A SESSION_PACK booking late-cancelled (12h ahead) becomes LATE_CANCELLED with
    fee = round_half_up(10000*0.50) = 5000 and the seat consumed (remaining 4).

    Design: Corner/state_machines/pack_late_cancel_charges_half_fee
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-05T00:00:00Z",
                                total_sessions=5, price_cents=50000)
    t_id, c_id, e_id, pack = (ctx["trainer"]["id"], ctx["client"]["id"],
                              ctx["engagement"]["id"], ctx["pack"])
    b = book_pack_session(t_id, e_id, pack["id"], pack["version"],
                          "2026-06-05T12:00:00Z", "2026-06-05T13:00:00Z")
    cancelled = validate_success(api.cancel_booking(b["id"], make_client_headers(c_id)))
    assert cancelled["status"] == "LATE_CANCELLED"
    assert cancelled["fee_charged_cents"] == 5000, f"got {cancelled['fee_charged_cents']}"
    refreshed = get_pack(t_id, pack["id"])
    assert refreshed["sessions_remaining"] == 4


# ─── Corner: state_machines / reschedule_creates_successor_with_backref ──────

def test_reschedule_creates_successor_with_backref(api):
    """PRD §3.5: "A successful reschedule creates a new booking in `BOOKED` whose
    `rescheduled_from_booking_id` points back to the original booking's `id`,
    reusing the very same pack seat so there is no net change to the pack's
    committed count, while the original booking moves to the terminal `RESCHEDULED`
    state, having handed its seat to the successor."

    Design: Corner/state_machines/reschedule_creates_successor_with_backref
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-01T00:00:00Z",
                                total_sessions=5, price_cents=50000)
    t_id, e_id, pack = ctx["trainer"]["id"], ctx["engagement"]["id"], ctx["pack"]
    b = book_pack_session(t_id, e_id, pack["id"], pack["version"],
                          "2026-06-20T10:00:00Z", "2026-06-20T11:00:00Z")
    resp = api.reschedule_booking(b["id"],
                                  {"start_utc": "2026-06-21T10:00:00Z",
                                   "end_utc": "2026-06-21T11:00:00Z"},
                                  make_trainer_headers(t_id))
    successor = validate_success(resp, 201)
    assert successor["rescheduled_from_booking_id"] == b["id"]
    original = validate_success(api.get_booking(b["id"], make_trainer_headers(t_id)))
    assert original["status"] == "RESCHEDULED"
    refreshed = get_pack(t_id, pack["id"])
    assert refreshed["sessions_remaining"] == 4
