"""State-machine transitions, branching terminals, revision loops, and the
multi-link cascades fired by seating and session-end.

Each test translates exactly one design-index instance.
"""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    make_guest_headers,
    create_reservation_payload,
    set_clock,
    create_venue,
    create_bay,
    create_member,
    create_member_with_wallet,
    create_game_card,
    create_hold_reservation,
    confirm_reservation,
    create_queue_ticket,
    setup_venue_bay_member,
    setup_confirmed_reservation,
    setup_session_on_confirmed_reservation,
    setup_walkin_session,
    create_lesson,
)

RM = TEST_USERS["range_manager_headers"]
FD = TEST_USERS["front_desk_headers"]


# ===========================================================================
# Queue A — non_linear_state_machine / reservation_branches_hold_to_three_terminals
# ===========================================================================
class TestReservationBranching:
    def test_confirmed_and_expired_diverge_under_sweep(self, api):
        """PRD §3.4: "When confirmation succeeds, the server creates a charge of kind
        `BAY_RESERVATION` for `quoted_price_cents`, drawn from the reservation's
        `pay_source`, in `SETTLED` status, and records its identifier on the
        reservation's `charge_id`."
        PRD §2.9: "The sweep is the only path by which a hold lapses to `EXPIRED`, an
        abandoned waiting ticket lapses to `EXPIRED`, and a confirmed-but-unplayed
        reservation lapses to `NO_SHOW`; the details of each transition live with the
        relevant lifecycle in §3."
        PRD §3.3: "On creation the reservation enters `HOLD` status and the server
        computes its `quoted_price_cents` using the dynamic pricing rule, then stamps
        `hold_expires_utc` as the creation-clock instant plus the hold time-to-live of
        30 minutes; if the hold is not confirmed by then, the sweep will expire it."

        Reservation A is CONFIRMED (charge created, charge_id non-null); Reservation B
        is left as an unconfirmed HOLD and the clock is advanced past its 30-min hold
        TTL, so the sweep expires it (status EXPIRED, charge_id null).

        Design: Difficulty/non_linear_state_machine/reservation_branches_hold_to_three_terminals
        """
        set_clock("2026-06-01T12:00:00Z")
        venue = create_venue()
        bay = create_bay(venue["id"])
        member = create_member_with_wallet(50000)
        res_a = create_hold_reservation(
            venue["id"], bay["id"], member["id"],
            "2026-06-02T18:00:00Z", "2026-06-02T19:00:00Z", "OFFPEAK",
            pay_source="WALLET")
        confirmed_a = confirm_reservation(res_a["id"], member["id"], bay["version"])
        res_b = create_hold_reservation(
            venue["id"], bay["id"], member["id"],
            "2026-06-02T20:00:00Z", "2026-06-02T21:00:00Z", "OFFPEAK",
            pay_source="WALLET")
        set_clock("2026-06-01T13:00:00Z")
        validate_success(api.sweep_holds(venue["id"], RM), 200)

        a_after = validate_success(api.get_reservation(res_a["id"], RM), 200)
        b_after = validate_success(api.get_reservation(res_b["id"], RM), 200)
        assert a_after["status"] == "CONFIRMED"
        assert a_after["charge_id"] is not None
        assert b_after["status"] == "EXPIRED"
        assert b_after["charge_id"] is None

    def test_hold_cancel_terminal_no_charge(self, api):
        """PRD §3.4: "Cancelling a reservation that is still in `HOLD` simply moves it
        to `CANCELLED` with no charge to reverse and the `version` incremented by 1."

        The third HOLD fork: a HOLD reservation cancelled by its owner becomes
        CANCELLED with charge_id still null (no charge ever created).

        Design: Difficulty/non_linear_state_machine/reservation_branches_hold_to_three_terminals
        """
        set_clock("2026-06-01T12:00:00Z")
        venue = create_venue()
        bay = create_bay(venue["id"])
        member = create_member_with_wallet(50000)
        res = create_hold_reservation(
            venue["id"], bay["id"], member["id"],
            "2026-06-02T18:00:00Z", "2026-06-02T19:00:00Z", "OFFPEAK",
            pay_source="WALLET")
        cancelled = validate_success(
            api.cancel_reservation(res["id"], make_guest_headers(member["id"])), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["charge_id"] is None


# ===========================================================================
# Queue A — non_linear_state_machine / event_package_cycles_quoted_negotiating_quoted
# ===========================================================================
class TestEventPackageRevisionLoop:
    def test_negotiate_then_patch_returns_to_quoted_and_reprices(self, api):
        """PRD §3.10: "A `RangeManager` may move a `QUOTED` package into
        `NEGOTIATING`. From `NEGOTIATING`, a `RangeManager` may revise the package —
        adjusting any of `headcount_estimate`, `per_head_package_cents`,
        `bay_block_cents`, or `deposit_cents` — which returns it to `QUOTED` and
        recomputes `estimated_total_cents` from the updated values using the same
        provisional formula."

        Start est=20 per_head=6500 block=15000 (estimated 145000); negotiate then
        PATCH per_head to 5750 returns to QUOTED with estimated 20*5750+15000=130000.

        Design: Difficulty/non_linear_state_machine/event_package_cycles_quoted_negotiating_quoted
        """
        from test_helpers import create_quoted_event
        venue = create_venue(bay_count=4)
        organizer = create_member()
        event = create_quoted_event(
            venue["id"], organizer["id"], 20, 6500, bay_block_cents=15000)
        assert event["estimated_total_cents"] == 145000
        validate_success(api.negotiate_event_package(event["id"], RM), 200)
        revised = validate_success(
            api.revise_event_package(event["id"], {"per_head_package_cents": 5750}, RM), 200)
        assert revised["status"] == "QUOTED"
        assert revised["estimated_total_cents"] == 130000

    def test_negotiate_moves_quoted_to_negotiating(self, api):
        """PRD §3.10: "The package moves through a revision loop before it is
        confirmed. A `RangeManager` may move a `QUOTED` package into `NEGOTIATING`."

        The first leg of the cycle: negotiate advances a QUOTED package to
        NEGOTIATING.

        Design: Difficulty/non_linear_state_machine/event_package_cycles_quoted_negotiating_quoted
        """
        from test_helpers import create_quoted_event
        venue = create_venue(bay_count=4)
        organizer = create_member()
        event = create_quoted_event(
            venue["id"], organizer["id"], 20, 6500, bay_block_cents=15000)
        assert event["status"] == "QUOTED"
        negotiating = validate_success(
            api.negotiate_event_package(event["id"], RM), 200)
        assert negotiating["status"] == "NEGOTIATING"


# ===========================================================================
# Queue A — transitive_cascade / seat_next_cascade_ticket_seated_card_decrement_card_depleted
# ===========================================================================
class TestSeatNextCascade:
    def _setup_one_credit_queue(self, api):
        set_clock("2026-06-01T12:00:00Z")
        venue = create_venue(bay_count=1)
        bay = create_bay(venue["id"])
        member = create_member()
        card = create_game_card(member["id"], credits_total=1)
        ticket = create_queue_ticket(
            venue["id"], member["id"], game_card_id=card["id"], party_size=2)
        return venue, bay, member, card, ticket

    def test_seat_next_seats_ticket_and_occupies_bay(self, api):
        """PRD §3.5: "A successful seating chooses, among the venue's `AVAILABLE`
        bays, the one with the lowest `floor_level`, breaking ties by `created_at`
        ascending, and sets that bay's `status` to `OCCUPIED`."
        PRD §3.5: "...moves the ticket to `SEATED`, and increments the ticket's
        `version` by 1 and the venue's `version` by 1..."

        Link 1 of the cascade: seat_next moves the head WAITING ticket to SEATED and
        flips the chosen bay to OCCUPIED.

        Design: Difficulty/transitive_cascade/seat_next_cascade_ticket_seated_card_decrement_card_depleted
        """
        venue, bay, member, card, ticket = self._setup_one_credit_queue(api)
        validate_success(
            api.seat_next(venue["id"], {"expected_venue_version": venue["version"]}, FD), 200)
        ticket_after = validate_success(api.get_queue_ticket(ticket["id"], FD), 200)
        bay_after = validate_success(api.get_bay(bay["id"], FD), 200)
        assert ticket_after["status"] == "SEATED"
        assert bay_after["status"] == "OCCUPIED"

    def test_seat_next_decrements_then_depletes_card(self, api):
        """PRD §3.5: "If a `game_card_id` was supplied, its `credits_remaining` is
        decremented by 1, and if that reaches 0 the card flips to `DEPLETED`."

        Links 2 and 3 of the cascade: seating consumes the card's single credit
        (credits_remaining 1 -> 0), and that decrement reaching 0 flips the card's
        status ACTIVE -> DEPLETED.

        Design: Difficulty/transitive_cascade/seat_next_cascade_ticket_seated_card_decrement_card_depleted
        """
        venue, bay, member, card, ticket = self._setup_one_credit_queue(api)
        validate_success(
            api.seat_next(venue["id"], {"expected_venue_version": venue["version"]}, FD), 200)
        card_after = validate_success(api.get_game_card(card["id"], FD), 200)
        assert card_after["credits_remaining"] == 0
        assert card_after["status"] == "DEPLETED"


# ===========================================================================
# Queue A — transitive_cascade / session_end_cascade_bay_freed_then_loyalty_confirmed
# ===========================================================================
class TestSessionEndCascade:
    def test_end_frees_bay(self, api):
        """PRD §3.6: "Ending play moves `play_status` from `OPEN` to `ENDED`. On
        ending, the server recomputes `total_score` one final time, frees the bay by
        setting its `status` back to `AVAILABLE` and its `current_session_id` to null,
        and confirms loyalty..."

        Link 1 of the cascade: ending an OPEN session sets play_status ENDED and frees
        the occupied bay back to AVAILABLE.

        Design: Difficulty/transitive_cascade/session_end_cascade_bay_freed_then_loyalty_confirmed
        """
        set_clock("2026-06-01T12:00:00Z")
        venue, bay, member, res, session = setup_session_on_confirmed_reservation(
            clock=None, tier="PLATINUM", wallet_cents=50000, base_rate_cents=2500)
        ended = validate_success(api.end_session(session["id"], FD), 200)
        assert ended["play_status"] == "ENDED"
        bay_after = validate_success(api.get_bay(bay["id"], FD), 200)
        assert bay_after["status"] == "AVAILABLE"

    def test_end_confirms_loyalty(self, api):
        """PRD §3.6: "...and confirms loyalty: it moves the provisional earn into
        confirmed points by computing the final earn on the session's net amount,
        adding that to the member's `loyalty_points` and subtracting the matching
        provisional earn from `pending_loyalty_points`."

        Link 2 of the cascade: the same end transition confirms loyalty — final earn
        floor(68*1.5)=102 lands in loyalty_points.

        Design: Difficulty/transitive_cascade/session_end_cascade_bay_freed_then_loyalty_confirmed
        """
        set_clock("2026-06-01T12:00:00Z")
        venue, bay, member, res, session = setup_session_on_confirmed_reservation(
            clock=None, tier="PLATINUM", wallet_cents=50000, base_rate_cents=2500)
        validate_success(api.end_session(session["id"], FD), 200)
        member_after = validate_success(api.get_member(member["id"], RM), 200)
        assert member_after["loyalty_points"] == 102


# ===========================================================================
# Queue B — state_machines instances
# ===========================================================================
def test_new_reservation_starts_in_hold(api):
    """PRD §3.3: "On creation the reservation enters `HOLD` status and the server
    computes its `quoted_price_cents` using the dynamic pricing rule, then stamps
    `hold_expires_utc` as the creation-clock instant plus the hold time-to-live of 30
    minutes..."
    PRD §3.3: "The reservation also carries a `charge_id` (null until it is confirmed)
    and a `no_show_fee_cents` (0 unless a late-cancel or no-show path fires)."

    A newly created reservation is HOLD with a charge_id of null.

    Design: Corner/state_machines/new_reservation_starts_in_hold
    """
    venue, bay, member = setup_venue_bay_member()
    res = create_hold_reservation(
        venue["id"], bay["id"], member["id"],
        "2026-06-02T18:00:00Z", "2026-06-02T19:00:00Z", "OFFPEAK")
    assert res["status"] == "HOLD"
    assert res["charge_id"] is None


def test_confirm_already_cancelled_reservation_returns_invalid_state(api):
    """PRD §3.4: "Confirmation is permitted only when the reservation is still in
    `HOLD`; a confirm against a reservation in any other state is rejected with
    `ERR_INVALID_STATE`."

    Confirming a CANCELLED reservation (no overlap involved) returns
    ERR_INVALID_STATE.

    Design: Corner/state_machines/confirm_already_cancelled_reservation_returns_invalid_state
    """
    venue, bay, member = setup_venue_bay_member()
    res = create_hold_reservation(
        venue["id"], bay["id"], member["id"],
        "2026-06-02T18:00:00Z", "2026-06-02T19:00:00Z", "OFFPEAK")
    validate_success(
        api.cancel_reservation(res["id"], make_guest_headers(member["id"])), 200)
    resp = api.confirm_reservation(
        res["id"], {"expected_bay_version": bay["version"]}, make_guest_headers(member["id"]))
    from test_helpers import validate_error
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)


def test_complete_lesson_twice_second_returns_invalid_state(api):
    """PRD §3.11: "A `FrontDesk` operator marks a lesson `COMPLETED`, and a `Guest`
    or `FrontDesk` operator may instead cancel it, moving it to `CANCELLED`; either
    transition increments the lesson's `version` by 1, and a transition attempted from
    a state other than `SCHEDULED` is rejected with `ERR_INVALID_STATE`."

    A COMPLETED lesson is terminal; a second complete returns ERR_INVALID_STATE.

    Design: Corner/state_machines/complete_lesson_twice_second_returns_invalid_state
    """
    venue, bay, member = setup_venue_bay_member()
    lesson = create_lesson(
        venue["id"], bay["id"], member["id"], "SIMULATOR",
        "2026-06-02T18:00:00Z", "2026-06-02T19:00:00Z", seats=1)
    validate_success(api.complete_lesson(lesson["id"], FD), 200)
    resp = api.complete_lesson(lesson["id"], FD)
    from test_helpers import validate_error
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)


def test_parallel_dimensions_void_after_end_independent_axes(api):
    """PRD §3.6: "A session carries two independent status dimensions on the same row.
    The `play_status` dimension runs from `OPEN` to `ENDED`; the `billing_status`
    dimension runs from `UNBILLED` to either `CHARGED` or `VOID`, and the two
    dimensions evolve independently."
    PRD §3.8: "A `RangeManager` may instead void a session's billing, moving
    `billing_status` from `UNBILLED` to `VOID`."

    A session ENDED on the play axis yet still UNBILLED can be VOID-ed on the billing
    axis without re-touching play_status — play stays ENDED, billing becomes VOID.

    Design: Corner/state_machines/parallel_dimensions_void_after_end_independent_axes
    """
    venue, bay, member, session = setup_walkin_session()
    validate_success(api.end_session(session["id"], FD), 200)
    voided = validate_success(api.void_session(session["id"], RM), 200)
    assert voided["play_status"] == "ENDED"
    assert voided["billing_status"] == "VOID"


def test_confirm_hold_after_expiry_returns_hold_expired(api):
    """PRD §3.4: "The current clock must be before `hold_expires_utc` — a confirm
    attempted after the hold has lapsed is rejected with `ERR_HOLD_EXPIRED`."

    A HOLD whose 30-min hold_expires_utc has passed (clock advanced well beyond it)
    cannot be confirmed; the confirm returns ERR_HOLD_EXPIRED.

    Design: Corner/state_machines/confirm_hold_after_expiry_returns_hold_expired
    """
    set_clock("2026-06-01T12:00:00Z")
    venue = create_venue()
    bay = create_bay(venue["id"])
    member = create_member()
    res = create_hold_reservation(
        venue["id"], bay["id"], member["id"],
        "2026-06-05T18:00:00Z", "2026-06-05T19:00:00Z", "OFFPEAK")
    set_clock("2026-06-01T23:00:00Z")
    resp = api.confirm_reservation(
        res["id"], {"expected_bay_version": bay["version"]}, make_guest_headers(member["id"]))
    from test_helpers import validate_error
    validate_error(resp, "ERR_HOLD_EXPIRED", expected_status=409)


def test_cancel_event_confirmed_refunds_deposit(api):
    """PRD §3.10: "A package may be cancelled from `QUOTED`, `NEGOTIATING`, or
    `CONFIRMED`. If the package was `CONFIRMED` at the time of cancellation, the full
    `deposit_cents` is credited back to the organizer's `wallet_balance_cents` as a
    deposit reversal; from `QUOTED` or `NEGOTIATING` there is no deposit to reverse.
    Cancellation moves the package to `CANCELLED` and increments its `version` by 1."

    Confirming with deposit 40000 debits the organizer wallet 60000 -> 20000;
    cancelling the CONFIRMED package credits the full 40000 back to 60000.

    Design: Corner/state_machines/cancel_event_confirmed_refunds_deposit
    """
    from test_helpers import create_quoted_event
    venue = create_venue(bay_count=4)
    organizer = create_member_with_wallet(60000)
    event = create_quoted_event(
        venue["id"], organizer["id"], 10, 5000, bay_block_cents=15000, deposit_cents=40000)
    validate_success(api.confirm_event_package(event["id"], RM), 200)
    cancelled = validate_success(api.cancel_event_package(event["id"], RM), 200)
    assert cancelled["status"] == "CANCELLED"
    organizer_after = validate_success(api.get_member(organizer["id"], RM), 200)
    assert organizer_after["wallet_balance_cents"] == 60000
