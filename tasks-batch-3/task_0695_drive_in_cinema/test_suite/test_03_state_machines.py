"""State-machine tests: cyclic showtime, parallel reservation dimensions, valid/invalid
transitions, terminal lockdown, idempotency, time-gated preconditions.

Covers Difficulty queue (non_linear_state_machine) and Corner queue (state_machines section).
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    make_patron_headers,
    TEST_USERS,
    setup_venue_lot_film,
    setup_scheduled_showtime,
    create_showtime,
    make_reservation,
    create_paid_reservation,
    create_checked_in_reservation,
    create_approved_rental,
    set_clock,
    list_refunds_for_reservation,
)

OPERATOR = TEST_USERS["venue_operator_headers"]
GATE = TEST_USERS["gate_attendant_headers"]


# =====================================================================
# Difficulty: non_linear_state_machine / showtime_cyclic_weather_hold_loop
# =====================================================================
def test_showtime_cyclic_weather_hold_reenters(api):
    """PRD §3.10: "The hold is cyclic and resumable: a `VenueOperator` may clear the hold,
    which is permitted only when `status` is `WEATHER_HOLD` and returns `status` to
    `SCHEDULED` (again incrementing `version`); a showtime can move between `SCHEDULED` and
    `WEATHER_HOLD` repeatedly."

    Design: Difficulty/non_linear_state_machine/showtime_cyclic_weather_hold_loop
    """
    venue, lot, film, st = setup_scheduled_showtime(
        clock="2026-06-01T00:00:00Z", start_utc="2026-06-18T02:00:00Z"
    )
    # First ADVISORY -> WEATHER_HOLD
    validate_success(api.create_weather_event(st["id"], {"severity": "ADVISORY"}, OPERATOR),
                     expected_status=201)
    held = validate_success(api.get_showtime(st["id"], OPERATOR))
    assert held["status"] == "WEATHER_HOLD"
    # Clear -> SCHEDULED
    cleared = validate_success(api.clear_weather_hold(st["id"], OPERATOR))
    assert cleared["status"] == "SCHEDULED"
    # Second ADVISORY -> WEATHER_HOLD again, proving the cycle re-enters
    validate_success(api.create_weather_event(st["id"], {"severity": "ADVISORY"}, OPERATOR),
                     expected_status=201)
    again = validate_success(api.get_showtime(st["id"], OPERATOR))
    assert again["status"] == "WEATHER_HOLD"


def test_showtime_clear_returns_to_scheduled(api):
    """PRD §3.10: "a `VenueOperator` may clear the hold, which is permitted only when
    `status` is `WEATHER_HOLD` and returns `status` to `SCHEDULED`."

    Design: Difficulty/non_linear_state_machine/showtime_cyclic_weather_hold_loop
    """
    venue, lot, film, st = setup_scheduled_showtime(
        clock="2026-06-01T00:00:00Z", start_utc="2026-06-19T02:00:00Z"
    )
    validate_success(api.create_weather_event(st["id"], {"severity": "ADVISORY"}, OPERATOR),
                     expected_status=201)
    cleared = validate_success(api.clear_weather_hold(st["id"], OPERATOR))
    assert cleared["status"] == "SCHEDULED"


# =====================================================================
# Difficulty: non_linear_state_machine / reservation_parallel_occupancy_payment_dimensions
# =====================================================================
def test_reservation_parallel_dimensions_checkin_and_paid(api):
    """PRD §3.4: "A reservation evolves along two independent dimensions: its
    `occupancy_status`, one of `CONFIRMED`, `CHECKED_IN`, `SCANNED`, `NO_SHOW`, or
    `CANCELLED`, beginning at `CONFIRMED`; and its `payment_status`, one of `UNPAID`, `PAID`,
    or `REFUNDED`, beginning at `UNPAID`."
    PRD §3.5: "Check-in advances `occupancy_status` from `CONFIRMED` to `CHECKED_IN`."

    Design: Difficulty/non_linear_state_machine/reservation_parallel_occupancy_payment_dimensions
    """
    venue, lot, film, st = setup_scheduled_showtime(
        clock="2026-06-20T01:30:00Z", start_utc="2026-06-20T02:00:00Z"
    )
    paid = create_paid_reservation(st, "patron-eee", occupant_count=2)
    assert paid["payment_status"] == "PAID"
    assert paid["occupancy_status"] == "CONFIRMED"
    checked_in = validate_success(api.check_in_reservation(paid["id"], GATE))
    assert checked_in["occupancy_status"] == "CHECKED_IN"
    assert checked_in["payment_status"] == "PAID"


def test_reservation_pay_independent_of_occupancy(api):
    """PRD §3.4: "Paying a reservation, performed by the owning `Patron`, advances
    `payment_status` from `UNPAID` to `PAID` and is allowed only while `payment_status` is
    `UNPAID` and `occupancy_status` is `CONFIRMED`; on payment, `amount_paid_cents` is set
    equal to `amount_due_cents`."

    Design: Difficulty/non_linear_state_machine/reservation_parallel_occupancy_payment_dimensions
    """
    venue, lot, film, st = setup_scheduled_showtime(
        clock="2026-06-20T00:00:00Z", start_utc="2026-06-21T02:00:00Z"
    )
    resv = make_reservation(st, "patron-eee2", occupant_count=2)
    assert resv["payment_status"] == "UNPAID"
    paid = validate_success(api.pay_reservation(resv["id"], make_patron_headers("patron-eee2")))
    assert paid["payment_status"] == "PAID"
    assert paid["occupancy_status"] == "CONFIRMED"  # occupancy dimension untouched by pay
    assert paid["amount_paid_cents"] == paid["amount_due_cents"]


# =====================================================================
# Corner: state_machines / showtime_complete_valid_after_end
# =====================================================================
def test_showtime_complete_after_end(api):
    """PRD §3.11: "Completion is permitted only when the showtime's `status` is `SCHEDULED`
    and the logical clock has reached the showtime's `end_utc` ... Completion sets `status`
    to `COMPLETED`."

    Design: Corner/state_machines/showtime_complete_valid_after_end
    """
    venue, lot, film, st = setup_scheduled_showtime(
        clock="2026-06-01T00:00:00Z", start_utc="2026-07-23T02:00:00Z"
    )
    set_clock("2026-07-23T05:00:00Z")
    completed = validate_success(api.complete_showtime(st["id"], OPERATOR))
    assert completed["status"] == "COMPLETED"


# =====================================================================
# Corner: state_machines / complete_before_end_returns_too_early
# =====================================================================
def test_complete_before_end_too_early(api):
    """PRD §3.11: "an attempt before the clock reaches `end_utc` is rejected with
    `ERR_COMPLETE_TOO_EARLY` (HTTP 409)."

    Design: Corner/state_machines/complete_before_end_returns_too_early
    """
    venue, lot, film, st = setup_scheduled_showtime(
        clock="2026-06-01T00:00:00Z", start_utc="2026-07-24T02:00:00Z"
    )
    res = api.complete_showtime(st["id"], OPERATOR)
    validate_error(res, "ERR_COMPLETE_TOO_EARLY")


# =====================================================================
# Corner: state_machines / clear_weather_hold_from_scheduled_invalid
# =====================================================================
def test_clear_weather_hold_from_scheduled_invalid(api):
    """PRD §3.10: "a `VenueOperator` may clear the hold, which is permitted only when
    `status` is `WEATHER_HOLD` and returns `status` to `SCHEDULED`."

    Design: Corner/state_machines/clear_weather_hold_from_scheduled_invalid
    """
    venue, lot, film, st = setup_scheduled_showtime(
        clock="2026-06-01T00:00:00Z", start_utc="2026-07-25T02:00:00Z"
    )
    res = api.clear_weather_hold(st["id"], OPERATOR)
    validate_error(res, "ERR_INVALID_STATE")


# =====================================================================
# Corner: state_machines / reject_after_approve_terminal_lockdown
# =====================================================================
def test_reject_after_approve_invalid_state(api):
    """PRD §3.7: "A rental in `REQUESTED` may instead be **rejected** by a `VenueOperator`,
    advancing `status` to `REJECTED`."
    PRD §3.7: "Approval, by a `VenueOperator`, advances `status` from `REQUESTED` to
    `APPROVED`. It is allowed only while `status` is `REQUESTED`."

    Design: Corner/state_machines/reject_after_approve_terminal_lockdown
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z")
    approved = create_approved_rental(
        venue["id"], lot["id"], "org-x", "2026-07-26T02:00:00Z", "2026-07-26T05:00:00Z"
    )
    res = api.reject_private_rental(approved["id"], OPERATOR)
    validate_error(res, "ERR_INVALID_STATE")


# =====================================================================
# Corner: state_machines / double_cancel_reservation_idempotency_rejected
# =====================================================================
def test_double_cancel_reservation_rejected(api):
    """PRD §3.5: "Cancellation is initiated by the owning `Patron` and advances
    `occupancy_status` to `CANCELLED`. It is allowed only while `occupancy_status` is
    `CONFIRMED` or `CHECKED_IN`."

    Design: Corner/state_machines/double_cancel_reservation_idempotency_rejected
    """
    venue, lot, film, st = setup_scheduled_showtime(
        clock="2026-06-01T00:00:00Z", start_utc="2026-07-27T02:00:00Z"
    )
    resv = make_reservation(st, "patron-idem", occupant_count=2)
    cancelled = validate_success(
        api.cancel_reservation(resv["id"], resv["version"], make_patron_headers("patron-idem"))
    )
    assert cancelled["occupancy_status"] == "CANCELLED"
    res = api.cancel_reservation(resv["id"], cancelled["version"], make_patron_headers("patron-idem"))
    validate_error(res, "ERR_INVALID_STATE")


# =====================================================================
# Corner: state_machines / scan_with_wrong_gate_code_rejected
# =====================================================================
def test_scan_wrong_gate_code_rejected(api):
    """PRD §3.5: "The supplied `gate_code` must equal the reservation's minted `gate_code`;
    a mismatch is rejected with `ERR_GATE_CODE_MISMATCH` (HTTP 409)."

    Design: Corner/state_machines/scan_with_wrong_gate_code_rejected
    """
    venue, lot, film, st = setup_scheduled_showtime(
        clock="2026-07-28T01:30:00Z", start_utc="2026-07-28T02:00:00Z"
    )
    checked_in = create_checked_in_reservation(st, "patron-scan", occupant_count=2)
    res = api.scan_reservation(checked_in["id"], "WRONG-CODE", GATE)
    validate_error(res, "ERR_GATE_CODE_MISMATCH")
    after = validate_success(api.get_reservation(checked_in["id"], GATE))
    assert after["occupancy_status"] == "CHECKED_IN"


# =====================================================================
# Corner: state_machines / checkin_before_window_rejected
# =====================================================================
def test_checkin_before_window_rejected(api):
    """PRD §3.5: "An attempt before that point — that is, while the logical clock reads
    earlier than `start_utc` minus 60 minutes — is rejected with `ERR_CHECKIN_WINDOW_CLOSED`
    (HTTP 409)."

    Design: Corner/state_machines/checkin_before_window_rejected
    """
    venue, lot, film, st = setup_scheduled_showtime(
        clock="2026-06-01T00:00:00Z", start_utc="2026-07-29T02:00:00Z"
    )
    paid = create_paid_reservation(st, "patron-cw", occupant_count=2)
    res = api.check_in_reservation(paid["id"], GATE)
    validate_error(res, "ERR_CHECKIN_WINDOW_CLOSED")


# =====================================================================
# Corner: state_machines / no_show_sweep_too_early_rejected
# =====================================================================
def test_no_show_sweep_too_early_rejected(api):
    """PRD §3.5: "It may run only once the logical clock has reached the showtime's
    `start_utc` plus the venue's `no_show_grace_minutes`; an earlier attempt is rejected with
    `ERR_SWEEP_TOO_EARLY` (HTTP 409)."

    Design: Corner/state_machines/no_show_sweep_too_early_rejected
    """
    venue, lot, film, st = setup_scheduled_showtime(
        clock="2026-06-01T00:00:00Z", start_utc="2026-07-30T02:00:00Z",
        venue_overrides={"no_show_grace_minutes": 15},
    )
    res = api.run_no_show_sweep(st["id"], OPERATOR)
    validate_error(res, "ERR_SWEEP_TOO_EARLY")


# =====================================================================
# Corner: state_machines / no_show_sweep_flips_confirmed_releases_stall
# =====================================================================
def test_no_show_sweep_flips_confirmed_releases_stall(api):
    """PRD §3.5: "For each reservation on the showtime still in `occupancy_status`
    `CONFIRMED` once the grace period has elapsed, the sweep sets that reservation's
    `occupancy_status` to `NO_SHOW`, decrements the showtime's `reserved_stall_count` by the
    reservation's `stalls_used`."
    PRD §3.5: "A no-show forfeits the spot and carries no refund."

    Design: Corner/state_machines/no_show_sweep_flips_confirmed_releases_stall
    """
    venue, lot, film, st = setup_scheduled_showtime(
        clock="2026-08-01T01:30:00Z", start_utc="2026-08-01T02:00:00Z",
        stall_count=5, venue_overrides={"no_show_grace_minutes": 15},
    )
    resv = create_paid_reservation(st, "patron-ns", occupant_count=2)
    set_clock("2026-08-01T02:20:00Z")
    validate_success(api.run_no_show_sweep(st["id"], GATE))
    resv_after = validate_success(api.get_reservation(resv["id"], GATE))
    assert resv_after["occupancy_status"] == "NO_SHOW"
    showtime_after = validate_success(api.get_showtime(st["id"], GATE))
    assert showtime_after["reserved_stall_count"] == 0
    refunds = list_refunds_for_reservation(resv["id"])
    assert refunds == [], f"no refund expected for a no-show, got {refunds}"


# =====================================================================
# Corner: endpoints / scan_success_admits_patron
# =====================================================================
def test_scan_success_admits_patron(api):
    """PRD §3.5: "Scanning advances `occupancy_status` from `CHECKED_IN` to `SCANNED` and
    admits the party. The request supplies a `gate_code`, and the transition is permitted
    only when `occupancy_status` is `CHECKED_IN`."

    Design: Corner/endpoints/scan_success_admits_patron
    """
    venue, lot, film, st = setup_scheduled_showtime(
        clock="2026-08-16T01:30:00Z", start_utc="2026-08-16T02:00:00Z"
    )
    resv = make_reservation(st, "patron-ok", occupant_count=2)
    gate_code = resv["gate_code"]
    validate_success(api.pay_reservation(resv["id"], make_patron_headers("patron-ok")))
    validate_success(api.check_in_reservation(resv["id"], GATE))
    scanned = validate_success(api.scan_reservation(resv["id"], gate_code, GATE))
    assert scanned["occupancy_status"] == "SCANNED"
