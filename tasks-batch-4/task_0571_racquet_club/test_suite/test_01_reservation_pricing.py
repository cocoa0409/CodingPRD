"""Reservation pricing, credit settlement, and the BOOKED fork.

Covers the reservation_charge dual/combinatorial calculations and the
book-then-undo compensation invariants.
"""
from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_booking_scenario, make_reservation, make_basic_plan, set_clock,
    TEST_USERS,
)

FD = TEST_USERS["frontdesk_headers"]


# ─── dual_variant_calc / dv_reservation_provisional_vs_final_charge ────
def test_reservation_provisional_and_final_fee_diverge_by_one_guest():
    """PRD §3.3: "On top of the court portion, a guest charge equal to the effective
    guest count multiplied by the plan's guest_fee_cents is added — the effective
    guest count is guest_count for the provisional charge and actual_guest_count for
    the final charge."
    PRD §3.3: "When credits settle the reservation, credits_used is set to the billed
    whole-hour duration and the court portion of the charge is zero."

    Design: Difficulty/dual_variant_calc/dv_reservation_provisional_vs_final_charge
    """
    s = setup_booking_scenario(court_overrides={"has_ball_machine": True,
                                                "ball_machine_fee_cents": 1000})
    res = make_reservation(s["court"]["id"], s["member"]["id"],
                           "2026-05-05T10:00:00Z", "2026-05-05T11:00:00Z",
                           guest_count=1, uses_ball_machine=True)
    assert res["provisional_fee_cents"] == 2500
    assert res["credits_used"] == 1

    set_clock("2026-05-05T10:00:00Z")
    get_success_data(api_client.checkin_reservation(res["id"], {"actual_guest_count": 2}, FD))
    completed = get_success_data(api_client.complete_reservation(res["id"], FD))
    assert completed["final_fee_cents"] == 4000


def test_reservation_completion_posts_only_the_delta_to_ledger():
    """PRD §3.3: "At completion the final charge is recomputed using
    actual_guest_count, stored in final_fee_cents, and only the delta — the final fee
    minus the already-posted provisional_fee_cents — is posted to the member's
    account_balance_cents."

    Design: Difficulty/dual_variant_calc/dv_reservation_provisional_vs_final_charge
    """
    s = setup_booking_scenario(court_overrides={"has_ball_machine": True,
                                                "ball_machine_fee_cents": 1000})
    res = make_reservation(s["court"]["id"], s["member"]["id"],
                           "2026-05-05T10:00:00Z", "2026-05-05T11:00:00Z",
                           guest_count=1, uses_ball_machine=True)
    set_clock("2026-05-05T10:00:00Z")
    get_success_data(api_client.checkin_reservation(res["id"], {"actual_guest_count": 2}, FD))
    get_success_data(api_client.complete_reservation(res["id"], FD))

    member = validate_success(api_client.get_member(s["member"]["id"], FD), 200)
    assert member["account_balance_cents"] == 4000


# ─── combinatorial_formula / combo_reservation_charge_peak_nonlinear ──
def test_peak_cash_booking_applies_ceil_surcharge_on_base():
    """PRD §3.3: "For a peak booking, a surcharge of 25 percent of that base court
    charge is computed on the pre-surcharge base, rounded up to the next whole cent,
    and added to the base."
    PRD §3.3: "The total fee is the sum of the court charge, the guest charge, and the
    ball-machine charge."

    Design: Difficulty/combinatorial_formula/combo_reservation_charge_peak_nonlinear
    """
    plan = make_basic_plan()
    s = setup_booking_scenario(plan=plan,
                               court_overrides={"has_ball_machine": True,
                                                "ball_machine_fee_cents": 1000})
    res = make_reservation(s["court"]["id"], s["member"]["id"],
                           "2026-05-05T18:00:00Z", "2026-05-05T20:00:00Z",
                           guest_count=0, uses_ball_machine=True)
    # 2h * 4000 = 8000 base; +ceil(0.25*8000)=2000 peak; cash court=10000; +1000 machine
    assert res["provisional_fee_cents"] == 11000


def test_peak_booking_with_zero_credits_settles_as_cash():
    """PRD §3.3: "The reservation is a peak booking, recorded in is_peak, when the UTC
    hour of its start_time is at or after 17:00 and before 21:00."
    PRD §3.3: "The reservation is settled with credits when the member has a
    non-CANCELLED subscription, that subscription is ACTIVE, its
    court_credits_remaining is at least the billed whole-hour duration, and either the
    booking is not a peak booking or the plan grants peak_access."

    Design: Difficulty/combinatorial_formula/combo_reservation_charge_peak_nonlinear
    """
    plan = make_basic_plan()  # 0 monthly_court_credits
    s = setup_booking_scenario(plan=plan,
                               court_overrides={"has_ball_machine": True,
                                                "ball_machine_fee_cents": 1000})
    res = make_reservation(s["court"]["id"], s["member"]["id"],
                           "2026-05-05T18:00:00Z", "2026-05-05T20:00:00Z",
                           guest_count=0, uses_ball_machine=True)
    assert res["is_peak"] is True
    assert res["credits_used"] == 0


# ─── compensating_invariant / court credits conserved ─────────────────
def test_book_then_cancel_restores_court_credits():
    """PRD §3.2: "The value in court_credits_remaining is always reconcilable as the
    plan's monthly_court_credits minus the sum of credits_used across the member's
    reservations that are in BOOKED, CHECKED_IN, COMPLETED, or NO_SHOW status".
    PRD §3.2: "Cancelling a BOOKED reservation restores its credits_used, whereas a
    reservation marked as a no-show retains its deduction."

    Design: Difficulty/compensating_invariant/invariant_court_credits_conserved_on_book_then_cancel
    """
    s = setup_booking_scenario()
    res = make_reservation(s["court"]["id"], s["member"]["id"],
                           "2026-05-12T10:00:00Z", "2026-05-12T11:00:00Z")
    get_success_data(api_client.cancel_reservation(res["id"], FD))
    sub = validate_success(api_client.get_subscription(s["sub"]["id"], FD), 200)
    assert sub["court_credits_remaining"] == 8


def test_cancelled_reservation_records_credits_used_and_terminal_state():
    """PRD §3.3: "which restores its `credits_used` to `court_credits_remaining` and
    reverses its `provisional_fee_cents` from the member's `account_balance_cents`."

    Design: Difficulty/compensating_invariant/invariant_court_credits_conserved_on_book_then_cancel
    """
    s = setup_booking_scenario()
    res = make_reservation(s["court"]["id"], s["member"]["id"],
                           "2026-05-12T10:00:00Z", "2026-05-12T11:00:00Z")
    assert res["credits_used"] == 1
    cancelled = get_success_data(api_client.cancel_reservation(res["id"], FD))
    assert cancelled["status"] == "CANCELLED"


# ─── compensating_invariant / member balance conserved ────────────────
def test_book_then_cancel_reverses_provisional_charge():
    """PRD §3.3: "which restores its `credits_used` to `court_credits_remaining` and
    reverses its `provisional_fee_cents` from the member's `account_balance_cents`."

    Design: Difficulty/compensating_invariant/invariant_member_balance_conserved_on_book_then_cancel
    """
    s = setup_booking_scenario(court_overrides={"has_ball_machine": True,
                                                "ball_machine_fee_cents": 1000})
    res = make_reservation(s["court"]["id"], s["member"]["id"],
                           "2026-05-13T10:00:00Z", "2026-05-13T11:00:00Z",
                           guest_count=1, uses_ball_machine=True)
    get_success_data(api_client.cancel_reservation(res["id"], FD))
    member = validate_success(api_client.get_member(s["member"]["id"], FD), 200)
    assert member["account_balance_cents"] == 0


def test_provisional_charge_posted_at_booking_before_reversal():
    """PRD §3.3: "At booking, this provisional total is stored in provisional_fee_cents,
    posted to the member's account_balance_cents, and any credits_used are deducted
    from the subscription."

    Design: Difficulty/compensating_invariant/invariant_member_balance_conserved_on_book_then_cancel
    """
    s = setup_booking_scenario(court_overrides={"has_ball_machine": True,
                                                "ball_machine_fee_cents": 1000})
    res = make_reservation(s["court"]["id"], s["member"]["id"],
                           "2026-05-13T10:00:00Z", "2026-05-13T11:00:00Z",
                           guest_count=1, uses_ball_machine=True)
    assert res["provisional_fee_cents"] == 2500
    member = validate_success(api_client.get_member(s["member"]["id"], FD), 200)
    assert member["account_balance_cents"] == 2500


# ─── non_linear_state_machine / reservation BOOKED fork ───────────────
def test_reservation_cancel_and_noshow_reach_divergent_terminals():
    """PRD §3.4: "This is permitted only while the reservation is BOOKED and only once
    the current clock has reached start_time plus a 15-minute grace period; an attempt
    before that instant is rejected with ERR_NO_SHOW_TOO_EARLY."

    Design: Difficulty/non_linear_state_machine/nlsm_reservation_booked_fork_cancel_vs_noshow
    """
    s = setup_booking_scenario()
    r1 = make_reservation(s["court"]["id"], s["member"]["id"],
                          "2026-05-05T10:00:00Z", "2026-05-05T11:00:00Z")
    r2 = make_reservation(s["court"]["id"], s["member"]["id"],
                          "2026-05-05T12:00:00Z", "2026-05-05T13:00:00Z")
    cancelled = get_success_data(api_client.cancel_reservation(r1["id"], FD))
    set_clock("2026-05-05T12:16:00Z")
    no_show = get_success_data(api_client.mark_no_show(r2["id"], FD))
    assert cancelled["status"] == "CANCELLED"
    assert no_show["status"] == "NO_SHOW"


def test_noshow_adds_strike_and_retains_credit_while_cancel_does_not():
    """PRD §3.4: "A no-show is a penalty state: the provisional_fee_cents already
    posted is retained with no refund, and credits_used is not restored to the
    subscription. Marking the no-show increments the member's no_show_strikes by one."

    Design: Difficulty/non_linear_state_machine/nlsm_reservation_booked_fork_cancel_vs_noshow
    """
    s = setup_booking_scenario()
    r1 = make_reservation(s["court"]["id"], s["member"]["id"],
                          "2026-05-05T10:00:00Z", "2026-05-05T11:00:00Z")
    r2 = make_reservation(s["court"]["id"], s["member"]["id"],
                          "2026-05-05T12:00:00Z", "2026-05-05T13:00:00Z")
    get_success_data(api_client.cancel_reservation(r1["id"], FD))
    set_clock("2026-05-05T12:16:00Z")
    get_success_data(api_client.mark_no_show(r2["id"], FD))

    member = validate_success(api_client.get_member(s["member"]["id"], FD), 200)
    sub = validate_success(api_client.get_subscription(s["sub"]["id"], FD), 200)
    assert member["no_show_strikes"] == 1
    assert sub["court_credits_remaining"] == 7


# ─── Corner: reservation_default_guest_count_is_zero ──────────────────
def test_booking_without_guest_count_defaults_to_zero():
    """PRD §3.3: "Two optional inputs shape the charge: guest_count, the number of
    guests declared at booking (default 0, zero or greater), and uses_ball_machine,
    declaring whether the court's ball machine will be used (default false)."

    Design: Corner/entities/reservation_default_guest_count_is_zero
    """
    s = setup_booking_scenario()
    res = make_reservation(s["court"]["id"], s["member"]["id"],
                           "2026-05-05T10:00:00Z", "2026-05-05T11:00:00Z")
    assert res["guest_count"] == 0
    assert res["provisional_fee_cents"] == 0
    assert res["credits_used"] == 1


# ─── Corner: reservation_offpeak_hour_is_peak_false ───────────────────
def test_offpeak_booking_has_no_surcharge():
    """PRD §3.3: "The reservation is a peak booking, recorded in is_peak, when the UTC
    hour of its start_time is at or after 17:00 and before 21:00."
    PRD §3.3: "The base court charge is the court's hourly_rate_cents multiplied by the
    billed whole-hour duration."

    Design: Corner/calculations/reservation_offpeak_hour_is_peak_false
    """
    plan = make_basic_plan()  # 0 credits -> cash booking
    s = setup_booking_scenario(plan=plan)
    res = make_reservation(s["court"]["id"], s["member"]["id"],
                           "2026-05-05T16:00:00Z", "2026-05-05T17:00:00Z")
    assert res["is_peak"] is False
    assert res["provisional_fee_cents"] == 4000
