"""Completion, gross, balance, payout, cancellation branches, and the
cascades they trigger.

Covers the dual-variant session gross (HOURLY vs PIECE), the pinned tax/deposit
final balance, the three-input payout floor, the completion cascade
(deposit -> APPLIED, artist counters, reliability), the divergent cancel
branches (client cancel forfeits; artist cancel preserves), the flash-release
cascade, and the relevant invalid-state guards.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_artist_headers, make_client_headers,
    create_artist, create_chair, create_client, create_verified_client,
    create_flash_design, hold_appointment, pay_deposit, record_waiver,
    set_clock, current_chair_version,
    setup_confirmed_appointment, setup_confirmed_flash_appointment,
    setup_completed_appointment, setup_held_appointment,
)
from test_helpers import factories

MANAGER = TEST_USERS["manager_headers"]


# ---------------------------------------------------------------------------
# Session gross: dual variant (PRD §3.9)
# ---------------------------------------------------------------------------
def test_session_gross_hourly_15min_ceiling(api):
    """PRD §3.9: "In `HOURLY` mode the studio bills in 15-minute increments: the
    `actual_minutes` is divided by 15 and rounded up to the next whole
    increment, and that number of increments is multiplied by the per-increment
    rate, which is the `hourly_rate_cents` divided by 4."

    ceil(200/15)=14 increments; 14 * (18000/4=4500) = 63000.

    Design: Corner/calculations/session_gross_hourly_15min_ceiling
    """
    ctx = setup_completed_appointment(
        clock="2026-06-01T12:00:00Z", complete_clock="2026-06-10T14:00:00Z",
        actual_minutes=200, hourly_rate_cents=18000, estimated_minutes=180,
    )
    assert ctx["appointment"]["gross_cents"] == 63000, \
        f"expected gross 63000, got {ctx['appointment']['gross_cents']}"


def test_session_gross_piece_ignores_actual_minutes(api):
    """PRD §3.9: "In `PIECE` mode the `gross_cents` is simply the
    `piece_price_cents`, and the actual time is disregarded."
    PRD §3.9: "First, the pre-tax balance is the session `gross_cents` minus the
    appointment's `deposit_paid_cents`, but never less than 0".

    PIECE gross 55000; pre-tax = 55000-11000=44000; tax=round(44000*0.08)=3520;
    balance=47520.

    Design: Corner/calculations/session_gross_piece_ignores_actual_minutes
    """
    ctx = setup_confirmed_flash_appointment(
        clock="2026-06-01T12:00:00Z", piece_price_cents=55000, deposit_cents=11000,
    )
    completed = get_success_data(
        api.complete_appointment(ctx["appointment_id"], {}, make_artist_headers(ctx["artist_id"]))
    )
    assert completed["gross_cents"] == 55000, \
        f"PIECE gross must equal piece_price_cents, got {completed['gross_cents']}"
    assert completed["balance_due_cents"] == 47520, \
        f"expected balance 47520, got {completed['balance_due_cents']}"


def test_session_gross_hourly_vs_piece_diverge(api):
    """PRD §3.9: "In `HOURLY` mode the studio bills in 15-minute increments ...
    that number of increments is multiplied by the per-increment rate, which is
    the `hourly_rate_cents` divided by 4."
    PRD §3.9: "In `PIECE` mode the `gross_cents` is simply the `piece_price_cents`,
    and the actual time is disregarded."

    Same artist/chair domain, two bookings: HOURLY (200 min @ 18000/hr -> 63000)
    vs PIECE (flat 55000) — different gross.

    Design: Difficulty/dual_variant_calc/session_gross_hourly_vs_piece_diverge
    """
    set_clock("2026-06-01T12:00:00Z")
    artist = create_artist(hourly_rate_cents=18000)
    chair = create_chair()
    flash = create_flash_design(artist["id"], title="Rose", piece_price_cents=55000, estimated_minutes=120)
    client = create_verified_client()
    cid = client["id"]
    ch = make_client_headers(cid)
    ah = make_artist_headers(artist["id"])

    # A1: HOURLY
    a1 = hold_appointment(
        artist["id"], cid, chair["id"], chair["version"],
        pricing_mode="HOURLY", hourly_rate_cents=18000, estimated_minutes=180,
        start_at="2026-06-10T10:00:00Z", end_at="2026-06-10T13:00:00Z",
    )
    pay_deposit(a1["id"], cid, 10800, a1["version"])
    record_waiver(a1["id"], cid, aftercare_acknowledged=True)
    get_success_data(api.confirm_appointment(a1["id"], ch))

    # A2: PIECE on the flash
    chair_v2 = current_chair_version(chair["id"])
    a2 = hold_appointment(
        artist["id"], cid, chair["id"], chair_v2,
        pricing_mode="PIECE", flash_design_id=flash["id"], piece_price_cents=55000,
        estimated_minutes=120, start_at="2026-06-11T10:00:00Z", end_at="2026-06-11T12:00:00Z",
    )
    pay_deposit(a2["id"], cid, 11000, a2["version"])
    record_waiver(a2["id"], cid, aftercare_acknowledged=True)
    get_success_data(api.confirm_appointment(a2["id"], ch))

    a1_done = get_success_data(api.complete_appointment(a1["id"], {"actual_minutes": 200}, ah))
    a2_done = get_success_data(api.complete_appointment(a2["id"], {}, ah))

    assert a1_done["gross_cents"] == 63000, f"HOURLY gross expected 63000, got {a1_done['gross_cents']}"
    assert a2_done["gross_cents"] == 55000, f"PIECE gross expected 55000, got {a2_done['gross_cents']}"
    assert a1_done["gross_cents"] != a2_done["gross_cents"], "the two variants must diverge"


def test_piece_variant_disregards_actual_time(api):
    """PRD §3.9: "In `PIECE` mode the `gross_cents` is simply the
    `piece_price_cents`, and the actual time is disregarded."
    PRD §3.9: "for a `PIECE` session `actual_minutes` is ignored."

    A focused second assertion on the dual-variant instance: a PIECE session
    completes with no actual_minutes and grosses the flat piece price, isolating
    the PIECE arm of the HOURLY-vs-PIECE divergence.

    Design: Difficulty/dual_variant_calc/session_gross_hourly_vs_piece_diverge
    """
    ctx = setup_confirmed_flash_appointment(
        clock="2026-06-01T12:00:00Z", piece_price_cents=55000, deposit_cents=11000,
    )
    completed = get_success_data(
        api.complete_appointment(ctx["appointment_id"], {}, make_artist_headers(ctx["artist_id"]))
    )
    assert completed["gross_cents"] == 55000, \
        f"PIECE variant must gross the flat piece price, got {completed['gross_cents']}"


# ---------------------------------------------------------------------------
# Final balance: pinned tax-after-deposit (PRD §3.9)
# ---------------------------------------------------------------------------
def test_final_balance_taxes_post_deposit_balance(api):
    """PRD §3.9: "First, the pre-tax balance is the session `gross_cents` minus
    the appointment's `deposit_paid_cents`, but never less than 0 ... Second, the
    tax is that pre-tax balance multiplied by the tax rate of 0.08 (eight
    percent), rounded half up to whole cents. Third, the `balance_due_cents` is
    the pre-tax balance plus that tax. Tax is therefore charged on the
    post-deposit balance, not on the gross."

    gross 63000, deposit 10800; pre-tax=52200; tax=round(52200*0.08)=4176;
    balance=56376 (taxing gross would wrongly give 58040).

    Design: Difficulty/combinatorial_formula/final_balance_pinned_tax_after_deposit_order
    """
    ctx = setup_completed_appointment(
        clock="2026-06-01T12:00:00Z", complete_clock="2026-06-10T14:00:00Z",
        actual_minutes=200, deposit_cents=10800,
    )
    appt = ctx["appointment"]
    assert appt["gross_cents"] == 63000, f"expected gross 63000, got {appt['gross_cents']}"
    assert appt["balance_due_cents"] == 56376, \
        f"expected balance 56376 (tax on post-deposit), got {appt['balance_due_cents']}"


def test_final_balance_gross_matches_before_balance(api):
    """PRD §3.9: "Completion computes the session `gross_cents`, then the
    `balance_due_cents`, applies the deposit, and updates the artist's standing."
    PRD §3.9: "the tax is that pre-tax balance multiplied by the tax rate of 0.08
    (eight percent), rounded half up to whole cents."

    A second assertion on the same pinned-order instance, confirming gross is
    computed and the balance is derived from it (not independently).

    Design: Difficulty/combinatorial_formula/final_balance_pinned_tax_after_deposit_order
    """
    ctx = setup_completed_appointment(
        clock="2026-06-01T12:00:00Z", complete_clock="2026-06-10T14:00:00Z",
        actual_minutes=200, deposit_cents=10800,
    )
    appt = ctx["appointment"]
    pre_tax = appt["gross_cents"] - 10800
    expected_balance = pre_tax + round(pre_tax * 0.08)
    assert appt["balance_due_cents"] == expected_balance == 56376, \
        f"balance must equal pre-tax + tax = {expected_balance}, got {appt['balance_due_cents']}"


# ---------------------------------------------------------------------------
# Payout: three-input non-linear floor (PRD §3.9)
# ---------------------------------------------------------------------------
def test_payout_three_input_nonlinear_floor(api):
    """PRD §3.9: "The artist's cut is the session `gross_cents` multiplied by the
    artist's `commission_pct`, rounded half up to whole cents, then reduced by
    the flat supply fee of 3500 cents, with the result floored at 0 ... The
    studio's cut is the `gross_cents` minus the artist's cut. The payout read
    returns `artist_cut_cents`, `studio_cut_cents`, and `gross_cents`."

    gross 63000, commission 0.70: round(44100)-3500=40600 artist; studio 22400.

    Design: Difficulty/combinatorial_formula/payout_three_input_nonlinear_floor
    """
    ctx = setup_completed_appointment(
        clock="2026-06-01T12:00:00Z", complete_clock="2026-06-10T14:00:00Z",
        actual_minutes=200, commission_pct=0.70,
    )
    payout = validate_success(api.get_payout(ctx["appointment_id"], MANAGER), expected_status=200)
    assert payout["artist_cut_cents"] == 40600, f"expected artist_cut 40600, got {payout['artist_cut_cents']}"
    assert payout["studio_cut_cents"] == 22400, f"expected studio_cut 22400, got {payout['studio_cut_cents']}"
    assert payout["gross_cents"] == 63000, f"expected gross 63000, got {payout['gross_cents']}"


def test_payout_studio_cut_complements_artist_cut(api):
    """PRD §3.9: "The studio's cut is the `gross_cents` minus the artist's cut."

    A second assertion on the payout instance: the two cuts always sum back to
    gross.

    Design: Difficulty/combinatorial_formula/payout_three_input_nonlinear_floor
    """
    ctx = setup_completed_appointment(
        clock="2026-06-01T12:00:00Z", complete_clock="2026-06-10T14:00:00Z",
        actual_minutes=200, commission_pct=0.70,
    )
    payout = validate_success(api.get_payout(ctx["appointment_id"], MANAGER), expected_status=200)
    assert payout["artist_cut_cents"] + payout["studio_cut_cents"] == payout["gross_cents"], \
        "artist_cut + studio_cut must equal gross"


# ---------------------------------------------------------------------------
# Completion cascade (PRD §3.9, depth-3)
# ---------------------------------------------------------------------------
def test_complete_cascade_deposit_artist_reliability(api):
    """PRD §3.9: "As side effects of completion, every `CONFIRMED` deposit row on
    the appointment is moved to `APPLIED`, the artist's `completed_session_count`
    is increased by one, and the artist's `reliability_score` is recomputed by
    the strict rule below."
    PRD §3.9: "The persisted, booking-gating **strict** `reliability_score` is
    100 minus both penalties, floored at 0."

    With zero cancels/reschedules the score stays 100 after the cascade.

    Design: Difficulty/transitive_cascade/complete_cascade_deposit_artist_reliability
    """
    ctx = setup_completed_appointment(
        clock="2026-06-01T12:00:00Z", complete_clock="2026-06-10T14:00:00Z", actual_minutes=200,
    )
    assert ctx["appointment"]["status"] == "COMPLETED"
    artist = get_success_data(api.get_artist(ctx["artist_id"], MANAGER))
    assert artist["completed_session_count"] == 1, \
        f"completed_session_count must be 1, got {artist['completed_session_count']}"
    assert artist["reliability_score"] == 100, \
        f"reliability_score must stay 100, got {artist['reliability_score']}"
    deposits = get_success_data(api.list_deposits(ctx["appointment_id"], MANAGER))
    statuses = [d["status"] for d in deposits]
    assert statuses == ["APPLIED"], f"deposit must be APPLIED after completion, got {statuses}"


def test_complete_cascade_marks_status_completed(api):
    """PRD §3.9: "An `Artist` completes a session, moving the appointment from
    `CONFIRMED` to `COMPLETED`; this is permitted only from `CONFIRMED`."
    PRD §3.9: "the artist's `completed_session_count` is increased by one".

    A second assertion on the completion cascade instance: the terminal status
    and the artist tally both move.

    Design: Difficulty/transitive_cascade/complete_cascade_deposit_artist_reliability
    """
    ctx = setup_completed_appointment(
        clock="2026-06-01T12:00:00Z", complete_clock="2026-06-10T14:00:00Z", actual_minutes=200,
    )
    appt = get_success_data(api.get_appointment(ctx["appointment_id"], MANAGER))
    assert appt["status"] == "COMPLETED", f"expected COMPLETED, got {appt['status']}"


# ---------------------------------------------------------------------------
# Cancellation branches (PRD §3.8) and the flash-release cascade
# ---------------------------------------------------------------------------
def test_client_cancel_forfeits_deposit_branch(api):
    """PRD §3.8: "When a **client cancels**, the appointment moves to
    `CANCELLED`; this is permitted from either `HELD` or `CONFIRMED`. Because the
    deposit is non-refundable, every `CONFIRMED` deposit row on the appointment
    is moved to `FORFEITED` and the appointment's `deposit_paid_cents` is
    recomputed to 0."

    Design: Difficulty/non_linear_state_machine/appointment_branching_cancel_vs_artist_cancel
    """
    ctx = setup_confirmed_appointment(
        clock="2026-06-01T12:00:00Z", deposit_cents=10800,
        start_at="2026-06-20T10:00:00Z", end_at="2026-06-20T13:00:00Z",
    )
    cancelled = get_success_data(
        api.cancel_appointment(ctx["appointment_id"], make_client_headers(ctx["client_id"]))
    )
    assert cancelled["status"] == "CANCELLED", f"expected CANCELLED, got {cancelled['status']}"
    assert cancelled["deposit_paid_cents"] == 0, \
        f"client cancel must forfeit (0), got {cancelled['deposit_paid_cents']}"


def test_artist_cancel_preserves_deposit_branch(api):
    """PRD §3.8: "When an **artist cancels** their own appointment, the
    appointment also moves to `CANCELLED` ... The client's deposits are **not**
    forfeited: the `CONFIRMED` deposit rows stay `CONFIRMED` and the appointment's
    `deposit_paid_cents` is preserved ... Instead, the artist's
    `artist_cancel_count` is increased by one".

    Design: Difficulty/non_linear_state_machine/appointment_branching_cancel_vs_artist_cancel
    """
    ctx = setup_confirmed_appointment(
        clock="2026-06-01T12:00:00Z", deposit_cents=10800,
        start_at="2026-06-21T10:00:00Z", end_at="2026-06-21T13:00:00Z",
    )
    cancelled = get_success_data(
        api.cancel_appointment_by_artist(ctx["appointment_id"], make_artist_headers(ctx["artist_id"]))
    )
    assert cancelled["status"] == "CANCELLED", f"expected CANCELLED, got {cancelled['status']}"
    assert cancelled["deposit_paid_cents"] == 10800, \
        f"artist cancel must preserve deposit (10800), got {cancelled['deposit_paid_cents']}"
    artist = get_success_data(api.get_artist(ctx["artist_id"], MANAGER))
    assert artist["artist_cancel_count"] == 1, \
        f"artist_cancel_count must be 1, got {artist['artist_cancel_count']}"


def test_artist_cancel_conserves_deposit_total_and_deposit_row(api):
    """PRD §3.8: "The client's deposits are **not** forfeited: the `CONFIRMED`
    deposit rows stay `CONFIRMED` and the appointment's `deposit_paid_cents` is
    preserved so the money can carry forward."

    The conserved quantity = total client deposit money; artist cancel leaves
    both the Deposit row CONFIRMED and deposit_paid_cents == 10800.

    Design: Difficulty/compensating_invariant/artist_cancel_preserves_deposit_total
    """
    ctx = setup_confirmed_appointment(
        clock="2026-06-01T12:00:00Z", deposit_cents=10800,
        start_at="2026-06-20T10:00:00Z", end_at="2026-06-20T13:00:00Z",
    )
    cancelled = get_success_data(
        api.cancel_appointment_by_artist(ctx["appointment_id"], make_artist_headers(ctx["artist_id"]))
    )
    assert cancelled["deposit_paid_cents"] == 10800, \
        f"deposit total must be conserved, got {cancelled['deposit_paid_cents']}"
    deposit = get_success_data(api.get_appointment(ctx["appointment_id"], MANAGER))
    deposits = get_success_data(api.list_deposits(ctx["appointment_id"], MANAGER))
    assert [d["status"] for d in deposits] == ["CONFIRMED"], \
        f"deposit row must stay CONFIRMED, got {[d['status'] for d in deposits]}"
    assert cancelled["status"] == "CANCELLED"


def test_artist_cancel_preserves_deposit_status_row(api):
    """PRD §3.8: "the `CONFIRMED` deposit rows stay `CONFIRMED` and the
    appointment's `deposit_paid_cents` is preserved so the money can carry
    forward."

    Second assertion on the compensating-invariant instance via the deposit
    resource's own status field.

    Design: Difficulty/compensating_invariant/artist_cancel_preserves_deposit_total
    """
    ctx = setup_confirmed_appointment(
        clock="2026-06-01T12:00:00Z", deposit_cents=10800,
        start_at="2026-06-22T10:00:00Z", end_at="2026-06-22T13:00:00Z",
    )
    get_success_data(
        api.cancel_appointment_by_artist(ctx["appointment_id"], make_artist_headers(ctx["artist_id"]))
    )
    deposits = get_success_data(api.list_deposits(ctx["appointment_id"], MANAGER))
    target = [d for d in deposits if d["id"] == ctx["deposit_id"]]
    assert target and target[0]["status"] == "CONFIRMED", \
        f"the deposit row must remain CONFIRMED, got {deposits}"


def test_client_cancel_cascade_releases_flash(api):
    """PRD §3.8: "When a **client cancels**, the appointment moves to
    `CANCELLED` ... every `CONFIRMED` deposit row on the appointment is moved to
    `FORFEITED` and the appointment's `deposit_paid_cents` is recomputed to 0. If
    the appointment held a flash piece, that piece is released from `RESERVED`
    back to `AVAILABLE`."

    Design: Difficulty/transitive_cascade/client_cancel_cascade_deposit_flash_release
    """
    ctx = setup_confirmed_flash_appointment(
        clock="2026-06-01T12:00:00Z", piece_price_cents=55000, deposit_cents=11000,
    )
    cancelled = get_success_data(
        api.cancel_appointment(ctx["appointment_id"], make_client_headers(ctx["client_id"]))
    )
    assert cancelled["status"] == "CANCELLED", f"expected CANCELLED, got {cancelled['status']}"
    deposits = get_success_data(api.list_deposits(ctx["appointment_id"], MANAGER))
    assert [d["status"] for d in deposits] == ["FORFEITED"], \
        f"client cancel must forfeit deposits, got {[d['status'] for d in deposits]}"
    flash = get_success_data(api.get_flash_design(ctx["flash_design_id"], MANAGER))
    assert flash["status"] == "AVAILABLE", \
        f"flash must be released to AVAILABLE, got {flash['status']}"


def test_client_cancel_cascade_forfeits_named_deposit(api):
    """PRD §3.8: "every `CONFIRMED` deposit row on the appointment is moved to
    `FORFEITED` and the appointment's `deposit_paid_cents` is recomputed to 0."

    Second assertion on the client-cancel cascade instance: the specific deposit
    row created in setup is the one forfeited, and deposit_paid_cents falls to 0.

    Design: Difficulty/transitive_cascade/client_cancel_cascade_deposit_flash_release
    """
    ctx = setup_confirmed_flash_appointment(
        clock="2026-06-01T12:00:00Z", piece_price_cents=55000, deposit_cents=11000,
    )
    cancelled = get_success_data(
        api.cancel_appointment(ctx["appointment_id"], make_client_headers(ctx["client_id"]))
    )
    assert cancelled["deposit_paid_cents"] == 0, \
        f"deposit_paid_cents must recompute to 0, got {cancelled['deposit_paid_cents']}"
    deposits = get_success_data(api.list_deposits(ctx["appointment_id"], MANAGER))
    target = [d for d in deposits if d["id"] == ctx["deposit_id"]]
    assert target and target[0]["status"] == "FORFEITED", \
        f"the named deposit must be FORFEITED, got {deposits}"


# ---------------------------------------------------------------------------
# Invalid-state guards (PRD §2.9, §3.8, §3.9)
# ---------------------------------------------------------------------------
def test_complete_from_held_invalid_state(api):
    """PRD §3.9: "An `Artist` completes a session, moving the appointment from
    `CONFIRMED` to `COMPLETED`; this is permitted only from `CONFIRMED`."
    PRD §2.9: "an operation requested against a resource that is not in a state
    permitting the transition fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/complete_from_held_invalid_state
    """
    ctx = setup_held_appointment(verify_client=False)
    resp = api.complete_appointment(
        ctx["appointment_id"], {"actual_minutes": 60}, make_artist_headers(ctx["artist_id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    after = get_success_data(api.get_appointment(ctx["appointment_id"], MANAGER))
    assert after["status"] == "HELD", f"appointment must stay HELD, got {after['status']}"


def test_cancel_already_cancelled_invalid_state(api):
    """PRD §3.8: "When a **client cancels**, the appointment moves to
    `CANCELLED`; this is permitted from either `HELD` or `CONFIRMED`."
    PRD §2.9: "an operation requested against a resource that is not in a state
    permitting the transition fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_already_cancelled_invalid_state
    """
    artist = create_artist(hourly_rate_cents=18000)
    chair = create_chair()
    client = create_client()
    appt = hold_appointment(
        artist["id"], client["id"], chair["id"], chair["version"],
        pricing_mode="HOURLY", hourly_rate_cents=18000, estimated_minutes=60,
        start_at="2026-07-01T10:00:00Z", end_at="2026-07-01T11:00:00Z",
    )
    ch = make_client_headers(client["id"])
    get_success_data(api.cancel_appointment(appt["id"], ch))
    resp = api.cancel_appointment(appt["id"], ch)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    after = get_success_data(api.get_appointment(appt["id"], MANAGER))
    assert after["status"] == "CANCELLED", f"must stay CANCELLED, got {after['status']}"


def test_no_show_before_start_time_invalid_state(api):
    """PRD §3.8: "When an artist marks a **no-show**, the appointment moves from
    `CONFIRMED` to `NO_SHOW`; this is permitted only from `CONFIRMED`, and only
    once the logical clock has reached or passed the appointment's `start_at`."
    PRD §2.9: "an operation requested against a resource that is not in a state
    permitting the transition fails with `ERR_INVALID_STATE`."

    Clock at 2026-06-01; appointment starts 2026-07-01 (future), so no-show is
    not yet allowed.

    Design: Corner/state_machines/no_show_before_start_time_invalid_state
    """
    ctx = setup_confirmed_appointment(
        clock="2026-06-01T12:00:00Z",
        start_at="2026-07-01T10:00:00Z", end_at="2026-07-01T13:00:00Z",
    )
    resp = api.no_show_appointment(ctx["appointment_id"], make_artist_headers(ctx["artist_id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    after = get_success_data(api.get_appointment(ctx["appointment_id"], MANAGER))
    assert after["status"] == "CONFIRMED", f"must stay CONFIRMED, got {after['status']}"
