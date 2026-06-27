"""No-show marking and its cascade, the strike-count deposit threshold boundary,
the no-show grace boundary, the confirm deposit gate, and the strike-decay vs
loyalty-accrual distinct-domain divergence."""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS,
    make_station, make_menu_item, make_technician, make_client,
    book_appointment, confirm, drive_to_completed,
    inject_client_state, inject_appointment_deposit, set_clock,
)

MANAGER = TEST_USERS["salon_manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


# ---------------------------------------------------------------------------
# Difficulty: no-show cascade depth>=2 (strike bump -> deposit flag -> forfeit)
# ---------------------------------------------------------------------------
def test_no_show_bumps_strike_and_flips_deposit_required(api):
    """PRD §3.13: "It increments the client's `active_no_show_strikes` by one, sets
    the client's `last_no_show_at` to the current clock, and sets the appointment's
    `no_show_strike_charged` to true."
    PRD §3.13: "If the resulting `active_no_show_strikes` is at least the deposit
    threshold of 2, it sets the client's `deposit_required` to true — a cascade hop
    in which a strike bump flips the deposit flag."

    Design: Difficulty/transitive_cascade/no_show_cascade_depth3_strike_depositflag_forfeit
    """
    set_clock("2026-03-25T00:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=3000, duration_minutes=30,
                          requires_sterile_station=False)
    tech = make_technician(station["id"])
    client = make_client()
    inject_client_state(client["id"], active_no_show_strikes=1,
                        last_no_show_at="2026-03-24T00:00:00Z")
    appt = book_appointment(client["id"], tech["id"], station["id"], menu["id"],
                            origin="APPOINTMENT", start_at="2026-03-25T13:00:00Z")
    inject_appointment_deposit(appt["id"], 2000)
    validate_success(api.pay_deposit(appt["id"], FRONT_DESK))
    confirm(appt["id"])
    set_clock("2026-03-25T14:00:00Z")
    validate_success(api.mark_no_show(appt["id"], FRONT_DESK))

    client_after = validate_success(api.get_client(client["id"], FRONT_DESK))
    assert client_after["active_no_show_strikes"] == 2
    assert client_after["deposit_required"] is True


def test_no_show_forfeits_held_deposit(api):
    """PRD §3.13: "If the `payment_status` was `DEPOSIT_HELD`, the deposit is
    forfeited and `payment_status` moves to `FORFEITED`."
    PRD §3.13: "moving `booking_status` from `CONFIRMED` to the terminal `NO_SHOW`."

    Design: Difficulty/transitive_cascade/no_show_cascade_depth3_strike_depositflag_forfeit
    """
    set_clock("2026-03-25T00:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=3000, duration_minutes=30,
                          requires_sterile_station=False)
    tech = make_technician(station["id"])
    client = make_client()
    inject_client_state(client["id"], active_no_show_strikes=1,
                        last_no_show_at="2026-03-24T00:00:00Z")
    appt = book_appointment(client["id"], tech["id"], station["id"], menu["id"],
                            origin="APPOINTMENT", start_at="2026-03-25T13:00:00Z")
    inject_appointment_deposit(appt["id"], 2000)
    validate_success(api.pay_deposit(appt["id"], FRONT_DESK))
    confirm(appt["id"])
    set_clock("2026-03-25T14:00:00Z")
    marked = validate_success(api.mark_no_show(appt["id"], FRONT_DESK))

    assert marked["booking_status"] == "NO_SHOW"
    assert marked["payment_status"] == "FORFEITED"


# ---------------------------------------------------------------------------
# Difficulty: deposit threshold boundary at exactly two strikes
# ---------------------------------------------------------------------------
def test_deposit_due_at_exactly_two_strikes(api):
    """PRD §3.5: "It reads the client's `active_no_show_strikes` (after decay) and,
    if that effective count is at least 2 — the deposit threshold — it sets the
    appointment's `deposit_due_cents` to the flat deposit of 2000 cents and sets
    the client's `deposit_required` to true."

    Design: Difficulty/boundary_precision_check/deposit_threshold_at_exactly_two_strikes
    """
    set_clock("2026-04-05T00:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=3000, duration_minutes=30,
                          requires_sterile_station=False)
    tech = make_technician(station["id"])
    client = make_client()
    inject_client_state(client["id"], active_no_show_strikes=2,
                        last_no_show_at="2026-04-04T00:00:00Z")
    appt = book_appointment(client["id"], tech["id"], station["id"], menu["id"],
                            origin="APPOINTMENT", start_at="2026-04-05T13:00:00Z")
    assert appt["deposit_due_cents"] == 2000


def test_no_deposit_due_at_one_strike(api):
    """PRD §3.4: "it is true exactly when `active_no_show_strikes` is at least 2,
    and false otherwise. The threshold is inclusive at 2, so one strike does not
    require a deposit but two do."
    PRD §3.5: "Otherwise it sets `deposit_due_cents` to 0 and `deposit_required` to
    false."

    Design: Difficulty/boundary_precision_check/deposit_threshold_at_exactly_two_strikes
    """
    set_clock("2026-04-05T00:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=3000, duration_minutes=30,
                          requires_sterile_station=False)
    tech = make_technician(station["id"])
    client = make_client()
    inject_client_state(client["id"], active_no_show_strikes=1,
                        last_no_show_at="2026-04-04T00:00:00Z")
    appt = book_appointment(client["id"], tech["id"], station["id"], menu["id"],
                            origin="APPOINTMENT", start_at="2026-04-05T15:00:00Z")
    assert appt["deposit_due_cents"] == 0


# ---------------------------------------------------------------------------
# Difficulty: no-show grace boundary at the exact minute
# ---------------------------------------------------------------------------
def test_no_show_one_minute_before_grace_rejected(api):
    """PRD §3.13: "This is permitted only after the grace period has elapsed: the
    current logical clock must be at or after the appointment's `start_at` plus 15
    grace minutes, or the attempt is rejected with `ERR_NO_SHOW_TOO_EARLY`."

    Design: Difficulty/boundary_precision_check/no_show_grace_boundary_at_exact_minute
    """
    set_clock("2026-04-06T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=3000, duration_minutes=30,
                          requires_sterile_station=False)
    tech = make_technician(station["id"])
    client = make_client()
    appt = book_appointment(client["id"], tech["id"], station["id"], menu["id"],
                            origin="APPOINTMENT", start_at="2026-04-06T13:00:00Z")
    confirm(appt["id"])
    set_clock("2026-04-06T13:14:00Z")   # start + 14 min, grace not elapsed
    res = api.mark_no_show(appt["id"], FRONT_DESK)
    validate_error(res, "ERR_NO_SHOW_TOO_EARLY")


def test_no_show_at_exact_grace_succeeds(api):
    """PRD §3.13: "the current logical clock must be at or after the appointment's
    `start_at` plus 15 grace minutes, or the attempt is rejected with
    `ERR_NO_SHOW_TOO_EARLY`."
    PRD §3.13: "moving `booking_status` from `CONFIRMED` to the terminal `NO_SHOW`."

    Design: Difficulty/boundary_precision_check/no_show_grace_boundary_at_exact_minute
    """
    set_clock("2026-04-06T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=3000, duration_minutes=30,
                          requires_sterile_station=False)
    tech = make_technician(station["id"])
    client = make_client()
    appt = book_appointment(client["id"], tech["id"], station["id"], menu["id"],
                            origin="APPOINTMENT", start_at="2026-04-06T13:00:00Z")
    confirm(appt["id"])
    set_clock("2026-04-06T13:15:00Z")   # exactly start + 15 min
    marked = validate_success(api.mark_no_show(appt["id"], FRONT_DESK))
    assert marked["booking_status"] == "NO_SHOW"


# ---------------------------------------------------------------------------
# Difficulty: confirm gated by client deposit posture (Appointment -> Client)
# ---------------------------------------------------------------------------
def test_confirm_blocked_when_deposit_required_and_unpaid(api):
    """PRD §3.7: "First, if the booking client's `deposit_required` is true, the
    appointment's `payment_status` must already be `DEPOSIT_HELD`; a deposit-
    required client whose deposit has not been collected cannot confirm, and the
    attempt is rejected with `ERR_DEPOSIT_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/confirm_gated_by_client_deposit_posture
    """
    set_clock("2026-04-11T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=3000, duration_minutes=30,
                          requires_sterile_station=False)
    tech = make_technician(station["id"])
    client = make_client()
    inject_client_state(client["id"], active_no_show_strikes=2,
                        last_no_show_at="2026-04-10T00:00:00Z")
    appt = book_appointment(client["id"], tech["id"], station["id"], menu["id"],
                            origin="APPOINTMENT", start_at="2026-04-11T13:00:00Z")
    res = api.confirm_appointment(appt["id"], FRONT_DESK)
    validate_error(res, "ERR_DEPOSIT_REQUIRED")


def test_confirm_succeeds_once_deposit_held(api):
    """PRD §3.7: "if the booking client's `deposit_required` is true, the
    appointment's `payment_status` must already be `DEPOSIT_HELD`".
    PRD §3.6: "This sets `deposit_paid_cents` equal to `deposit_due_cents`, advances
    `payment_status` from `UNPAID` to `DEPOSIT_HELD`".

    Design: Difficulty/cross_entity_state_dependency/confirm_gated_by_client_deposit_posture
    """
    set_clock("2026-04-11T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=3000, duration_minutes=30,
                          requires_sterile_station=False)
    tech = make_technician(station["id"])
    client = make_client()
    inject_client_state(client["id"], active_no_show_strikes=2,
                        last_no_show_at="2026-04-10T00:00:00Z")
    appt = book_appointment(client["id"], tech["id"], station["id"], menu["id"],
                            origin="APPOINTMENT", start_at="2026-04-11T13:00:00Z")
    validate_success(api.pay_deposit(appt["id"], FRONT_DESK))
    confirmed = validate_success(api.confirm_appointment(appt["id"], FRONT_DESK))
    assert confirmed["booking_status"] == "CONFIRMED"
    assert confirmed["payment_status"] == "DEPOSIT_HELD"


# ---------------------------------------------------------------------------
# Difficulty: strike decay (time-driven on strikes) vs loyalty accrual
# (event-driven on points) — two distinct conserved Client quantities.
# ---------------------------------------------------------------------------
def test_strike_decays_one_window_after_thirty_days(api):
    """PRD §3.4: "take the whole number of days that have elapsed from
    `last_no_show_at` to the current logical clock — that is, the elapsed seconds
    divided by 86,400 and rounded down — and from it derive the number of decayed
    strikes as that elapsed-day count divided by the decay window of 30 days, again
    rounded down."
    PRD §3.4: "a client past 30 days loses one strike".

    Design: Difficulty/dual_variant_calc/no_show_strike_decay_vs_loyalty_accrual_distinct_domains
    """
    set_clock("2026-04-01T00:00:00Z")
    client = make_client()
    # Raw 2 strikes, last no-show 59 days before the read clock -> 1 window decayed.
    inject_client_state(client["id"], active_no_show_strikes=2,
                        last_no_show_at="2026-02-01T00:00:00Z")
    got = validate_success(api.get_client(client["id"], FRONT_DESK))
    assert got["active_no_show_strikes"] == 1
    assert got["deposit_required"] is False   # 1 < 2


def test_loyalty_accrues_on_completion_distinct_from_strikes(api):
    """PRD §3.10: "It awards the service's `loyalty_points_award` to the client's
    `loyalty_points_balance`."
    PRD §3.3: "a `loyalty_points_award` (a non-negative integer defaulting to 0)
    credited to the client when an appointment for the service completes".

    Design: Difficulty/dual_variant_calc/no_show_strike_decay_vs_loyalty_accrual_distinct_domains
    """
    set_clock("2026-04-01T00:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=4500, duration_minutes=30,
                          loyalty_points_award=10, requires_sterile_station=False)
    tech = make_technician(station["id"])
    client = make_client()
    drive_to_completed(client["id"], tech["id"], station["id"], menu["id"],
                       origin="APPOINTMENT", start_at="2026-04-01T10:00:00Z")

    got = validate_success(api.get_client(client["id"], FRONT_DESK))
    assert got["loyalty_points_balance"] == 10
