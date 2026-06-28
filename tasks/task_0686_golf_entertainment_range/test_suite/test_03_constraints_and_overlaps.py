"""Validation precedence, cross-entity state dependencies, bay-window overlap
semantics, and walk-in seating constraints.

Each test translates exactly one design-index instance.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_guest_headers,
    create_reservation_payload,
    create_lesson_payload,
    set_clock,
    create_venue,
    create_bay,
    create_member,
    create_member_with_wallet,
    create_game_card,
    create_hold_reservation,
    confirm_reservation,
    create_queue_ticket,
    take_bay_out_of_service,
    setup_venue_bay_member,
    create_lesson,
    setup_walkin_session,
    open_session_tab,
    add_items,
)

RM = TEST_USERS["range_manager_headers"]
FD = TEST_USERS["front_desk_headers"]


# ===========================================================================
# Queue A — priority_pair_validation_conflict / state_beats_temporal_on_confirm_terminal_reservation
# ===========================================================================
class TestStateBeatsTemporal:
    def _setup_cancelled_overlapping_y(self, api):
        set_clock("2026-06-01T12:00:00Z")
        venue = create_venue()
        bay = create_bay(venue["id"])
        member = create_member_with_wallet(50000)
        res_x = create_hold_reservation(
            venue["id"], bay["id"], member["id"],
            "2026-06-02T18:00:00Z", "2026-06-02T19:00:00Z", "OFFPEAK", pay_source="WALLET")
        # Y is created as a HOLD while X is still a HOLD — at that point neither
        # window conflicts (PRD §3.3 rejects creation only against an already
        # CONFIRMED reservation), so the overlapping HOLD Y is born legitimately.
        res_y = create_hold_reservation(
            venue["id"], bay["id"], member["id"],
            "2026-06-02T18:30:00Z", "2026-06-02T19:30:00Z", "OFFPEAK", pay_source="WALLET")
        confirm_reservation(res_x["id"], member["id"], bay["version"])
        validate_success(
            api.cancel_reservation(res_y["id"], make_guest_headers(member["id"])), 200)
        return venue, bay, member, res_y

    def test_confirm_cancelled_overlapping_returns_invalid_state(self, api):
        """PRD §2.6: "The order is: first, authentication of the role header
        (`ERR_UNAUTHENTICATED`); then role authorization for the operation
        (`ERR_FORBIDDEN_ROLE`); then, for a `Guest` acting on a member-scoped
        resource, the ownership check (`ERR_NOT_RESOURCE_OWNER`); then existence of
        every path and foreign-key-referenced resource, validated left to right
        (`ERR_NOT_FOUND`); then request-body well-formedness (`ERR_INVALID_REQUEST`);
        then the state-precondition check that the target is in a state from which the
        requested transition is defined (`ERR_INVALID_STATE`); then the bay-window
        overlap check (`ERR_BAY_WINDOW_CONFLICT`)..."

        Confirming a CANCELLED reservation Y whose window also overlaps a CONFIRMED
        reservation X returns the higher-priority ERR_INVALID_STATE (state, priority 6)
        rather than the overlap error (priority 7).

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_confirm_terminal_reservation
        """
        venue, bay, member, res_y = self._setup_cancelled_overlapping_y(api)
        # Re-read live bay version for a fresh OCC value so the state check, not OCC,
        # is what fires.
        live_bay = validate_success(api.get_bay(bay["id"], RM), 200)
        resp = api.confirm_reservation(
            res_y["id"], {"expected_bay_version": live_bay["version"]},
            make_guest_headers(member["id"]))
        validate_error(resp, "ERR_INVALID_STATE", expected_status=409)

    def test_isolated_overlap_returns_window_conflict(self, api):
        """PRD §3.4: "The window must still be free of any `CONFIRMED` reservation or
        `SCHEDULED` lesson on the bay, re-checked at confirm time and rejected with
        `ERR_BAY_WINDOW_CONFLICT` on overlap."

        Isolating priority 7 alone: a HOLD reservation that overlaps a CONFIRMED one
        but is itself in a valid (HOLD) state surfaces ERR_BAY_WINDOW_CONFLICT — the
        single-failure counterpart to the precedence test above.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_confirm_terminal_reservation
        """
        set_clock("2026-06-01T12:00:00Z")
        venue = create_venue()
        bay = create_bay(venue["id"])
        member = create_member_with_wallet(50000)
        res_x = create_hold_reservation(
            venue["id"], bay["id"], member["id"],
            "2026-06-02T18:00:00Z", "2026-06-02T19:00:00Z", "OFFPEAK", pay_source="WALLET")
        # Create overlapping HOLD Y while X is still a HOLD (PRD §3.3 only rejects
        # creation against an already-CONFIRMED reservation), then confirm X so the
        # overlap surfaces at Y's confirm time.
        res_y = create_hold_reservation(
            venue["id"], bay["id"], member["id"],
            "2026-06-02T18:30:00Z", "2026-06-02T19:30:00Z", "OFFPEAK", pay_source="WALLET")
        confirm_reservation(res_x["id"], member["id"], bay["version"])
        live_bay = validate_success(api.get_bay(bay["id"], RM), 200)
        resp = api.confirm_reservation(
            res_y["id"], {"expected_bay_version": live_bay["version"]},
            make_guest_headers(member["id"]))
        validate_error(resp, "ERR_BAY_WINDOW_CONFLICT", expected_status=409)


# ===========================================================================
# Queue A — priority_pair_validation_conflict / safety_beats_fiscal_on_confirm_out_of_service_bay_low_wallet
# ===========================================================================
class TestSafetyBeatsFiscal:
    def test_out_of_service_bay_low_wallet_returns_bay_unavailable(self, api):
        """PRD §2.6: "...then bay-availability and lesson-capacity safety
        (`ERR_BAY_UNAVAILABLE`); then walk-in seating availability
        (`ERR_NO_BAY_AVAILABLE`); then the queue-head check (`ERR_NOT_QUEUE_HEAD`);
        then game-card credit sufficiency (`ERR_CARD_DEPLETED`); then funding
        sufficiency (`ERR_INSUFFICIENT_FUNDS`)..."
        PRD §3.4: "The reserved bay must not be `OUT_OF_SERVICE`, else
        `ERR_BAY_UNAVAILABLE`."

        Confirming a WALLET reservation on an OUT_OF_SERVICE bay while the wallet is
        also too low returns the higher-priority ERR_BAY_UNAVAILABLE (safety, priority
        8) not the funds error (priority 12).

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_confirm_out_of_service_bay_low_wallet
        """
        set_clock("2026-06-01T12:00:00Z")
        venue = create_venue()
        bay = create_bay(venue["id"])
        member = create_member(tier="STANDARD")  # wallet 0
        res = create_hold_reservation(
            venue["id"], bay["id"], member["id"],
            "2026-06-02T18:00:00Z", "2026-06-02T19:00:00Z", "PEAK",
            day_type="WEEKDAY", pay_source="WALLET")
        oos_bay = take_bay_out_of_service(bay["id"], bay["version"])
        resp = api.confirm_reservation(
            res["id"], {"expected_bay_version": oos_bay["version"]},
            make_guest_headers(member["id"]))
        validate_error(resp, "ERR_BAY_UNAVAILABLE", expected_status=409)

    def test_isolated_low_wallet_returns_insufficient_funds(self, api):
        """PRD §3.4: "If `pay_source` is `WALLET`, the member's `wallet_balance_cents`
        must be at least `quoted_price_cents`, else `ERR_INSUFFICIENT_FUNDS`."

        Isolating priority 12 alone: a WALLET confirm on an available bay whose wallet
        is below the quote surfaces ERR_INSUFFICIENT_FUNDS — the single-failure
        counterpart proving the funds path is reachable when no higher check fires.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_confirm_out_of_service_bay_low_wallet
        """
        set_clock("2026-06-01T12:00:00Z")
        venue = create_venue()
        bay = create_bay(venue["id"])
        member = create_member(tier="STANDARD")  # wallet 0
        res = create_hold_reservation(
            venue["id"], bay["id"], member["id"],
            "2026-06-02T18:00:00Z", "2026-06-02T19:00:00Z", "PEAK",
            day_type="WEEKDAY", pay_source="WALLET")
        resp = api.confirm_reservation(
            res["id"], {"expected_bay_version": bay["version"]},
            make_guest_headers(member["id"]))
        validate_error(resp, "ERR_INSUFFICIENT_FUNDS", expected_status=402)


# ===========================================================================
# Queue A — cross_entity_state_dependency / reservation_confirm_depends_on_bay_not_out_of_service
# ===========================================================================
class TestConfirmDependsOnBay:
    def test_confirm_blocked_by_out_of_service_bay(self, api):
        """PRD §3.4: "The reserved bay must not be `OUT_OF_SERVICE`, else
        `ERR_BAY_UNAVAILABLE`."

        A HOLD reservation whose bay is taken OUT_OF_SERVICE cannot confirm: the
        confirm fails with ERR_BAY_UNAVAILABLE and the reservation stays HOLD.

        Design: Difficulty/cross_entity_state_dependency/reservation_confirm_depends_on_bay_not_out_of_service
        """
        set_clock("2026-06-01T12:00:00Z")
        venue = create_venue()
        bay = create_bay(venue["id"])
        member = create_member_with_wallet(50000)
        res = create_hold_reservation(
            venue["id"], bay["id"], member["id"],
            "2026-06-02T18:00:00Z", "2026-06-02T19:00:00Z", "PEAK", day_type="WEEKDAY")
        oos_bay = take_bay_out_of_service(bay["id"], bay["version"])
        resp = api.confirm_reservation(
            res["id"], {"expected_bay_version": oos_bay["version"]},
            make_guest_headers(member["id"]))
        validate_error(resp, "ERR_BAY_UNAVAILABLE", expected_status=409)
        res_after = validate_success(api.get_reservation(res["id"], RM), 200)
        assert res_after["status"] == "HOLD"

    def test_confirm_succeeds_when_bay_in_service(self, api):
        """PRD §3.4: "Confirming a hold advances the reservation from `HOLD` to
        `CONFIRMED`."
        PRD §3.4: "The reserved bay must not be `OUT_OF_SERVICE`, else
        `ERR_BAY_UNAVAILABLE`."

        Positive counterpart of the cross-entity dependency: with the bay AVAILABLE
        (not OUT_OF_SERVICE), the same confirm succeeds and the reservation becomes
        CONFIRMED.

        Design: Difficulty/cross_entity_state_dependency/reservation_confirm_depends_on_bay_not_out_of_service
        """
        set_clock("2026-06-01T12:00:00Z")
        venue = create_venue()
        bay = create_bay(venue["id"])
        member = create_member_with_wallet(50000)
        res = create_hold_reservation(
            venue["id"], bay["id"], member["id"],
            "2026-06-02T18:00:00Z", "2026-06-02T19:00:00Z", "PEAK", day_type="WEEKDAY")
        confirmed = validate_success(api.confirm_reservation(
            res["id"], {"expected_bay_version": bay["version"]},
            make_guest_headers(member["id"])), 200)
        assert confirmed["status"] == "CONFIRMED"


# ===========================================================================
# Queue A — cross_entity_state_dependency / session_settle_depends_on_fbtab_closed
# ===========================================================================
class TestSettleDependsOnFbTab:
    def test_settle_blocked_by_open_tab(self, api):
        """PRD §3.8: "A `FrontDesk` operator settles a session — moving
        `billing_status` from `UNBILLED` to `CHARGED` — only when the session's
        `play_status` is already `ENDED` and any F&B tab attached to the session is
        `CLOSED`; a settle attempted while play is still open, or with an open attached
        tab, is rejected (the open-tab case with `ERR_FBTAB_NOT_CLOSED`, and a settle
        from a non-`UNBILLED` billing state with `ERR_INVALID_STATE`)."

        An ENDED session with an OPEN attached FBTab cannot settle; settle returns
        ERR_FBTAB_NOT_CLOSED and billing stays UNBILLED.

        Design: Difficulty/cross_entity_state_dependency/session_settle_depends_on_fbtab_closed
        """
        venue, bay, member, session = setup_walkin_session()
        tab = open_session_tab(session["id"])
        add_items(tab["id"], [("Soda", 500, 1)])
        validate_success(api.end_session(session["id"], FD), 200)
        resp = api.settle_session(session["id"], {}, FD)
        validate_error(resp, "ERR_FBTAB_NOT_CLOSED", expected_status=409)
        session_after = validate_success(api.get_session(session["id"], FD), 200)
        assert session_after["billing_status"] == "UNBILLED"

    def test_settle_succeeds_after_tab_closed(self, api):
        """PRD §3.8: "A `FrontDesk` operator settles a session — moving
        `billing_status` from `UNBILLED` to `CHARGED` — only when the session's
        `play_status` is already `ENDED` and any F&B tab attached to the session is
        `CLOSED`..."
        PRD §3.9: "Closing is the precondition that lets the tab's owning session or
        event package settle."

        Positive counterpart: once the attached tab is CLOSED (and play is ENDED) the
        settle succeeds and billing_status becomes CHARGED.

        Design: Difficulty/cross_entity_state_dependency/session_settle_depends_on_fbtab_closed
        """
        venue, bay, member, session = setup_walkin_session()
        tab = open_session_tab(session["id"])
        add_items(tab["id"], [("Soda", 500, 1)])
        validate_success(api.close_fb_tab(tab["id"], FD), 200)
        validate_success(api.end_session(session["id"], FD), 200)
        settled = validate_success(api.settle_session(session["id"], {}, FD), 200)
        assert settled["billing_status"] == "CHARGED"


# ===========================================================================
# Queue A — resource_temporal_overlap / reservation_back_to_back_allowed_overlap_rejected_on_bay
# ===========================================================================
class TestReservationOverlap:
    def _confirmed_a(self, api):
        set_clock("2026-06-01T12:00:00Z")
        venue = create_venue()
        bay = create_bay(venue["id"])
        member = create_member_with_wallet(50000)
        res_a = create_hold_reservation(
            venue["id"], bay["id"], member["id"],
            "2026-06-02T18:00:00Z", "2026-06-02T19:00:00Z", "OFFPEAK", pay_source="WALLET")
        confirm_reservation(res_a["id"], member["id"], bay["version"])
        return venue, bay, member

    def test_back_to_back_reservation_allowed(self, api):
        """PRD §3.3: "Overlap is judged on the half-open interval from `start_utc` up
        to but not including `end_utc`, so two bookings that touch exactly at a
        boundary are back-to-back and permitted; a genuine overlap is rejected with
        `ERR_BAY_WINDOW_CONFLICT`."

        A reservation B starting exactly when CONFIRMED A ends (19:00, gap 0) is
        back-to-back and permitted — B is created as a HOLD.

        Design: Difficulty/resource_temporal_overlap/reservation_back_to_back_allowed_overlap_rejected_on_bay
        """
        venue, bay, member = self._confirmed_a(api)
        payload = create_reservation_payload(
            venue["id"], bay["id"], member["id"],
            "2026-06-02T19:00:00Z", "2026-06-02T20:00:00Z", "OFFPEAK", pay_source="WALLET")
        res_b = validate_success(
            api.create_reservation(payload, make_guest_headers(member["id"])), 201)
        assert res_b["status"] == "HOLD"
        assert res_b["id"] is not None

    def test_overlapping_reservation_rejected(self, api):
        """PRD §3.3: "A reservation may not be created on a bay whose window overlaps
        an already-`CONFIRMED` reservation or a `SCHEDULED` lesson on that same bay.
        Overlap is judged on the half-open interval from `start_utc` up to but not
        including `end_utc`, so two bookings that touch exactly at a boundary are
        back-to-back and permitted; a genuine overlap is rejected with
        `ERR_BAY_WINDOW_CONFLICT`."

        A reservation overlapping CONFIRMED A by 30 minutes (18:30-19:30 vs
        18:00-19:00) is rejected with ERR_BAY_WINDOW_CONFLICT.

        Design: Difficulty/resource_temporal_overlap/reservation_back_to_back_allowed_overlap_rejected_on_bay
        """
        venue, bay, member = self._confirmed_a(api)
        payload = create_reservation_payload(
            venue["id"], bay["id"], member["id"],
            "2026-06-02T18:30:00Z", "2026-06-02T19:30:00Z", "OFFPEAK", pay_source="WALLET")
        resp = api.create_reservation(payload, make_guest_headers(member["id"]))
        validate_error(resp, "ERR_BAY_WINDOW_CONFLICT", expected_status=409)


# ===========================================================================
# Queue A — resource_temporal_overlap / lesson_overlapping_confirmed_reservation_rejected_on_bay
# ===========================================================================
class TestLessonOverlap:
    def _confirmed_reservation_bay(self, api):
        set_clock("2026-06-01T12:00:00Z")
        venue = create_venue()
        bay = create_bay(venue["id"])
        member = create_member_with_wallet(50000)
        res_a = create_hold_reservation(
            venue["id"], bay["id"], member["id"],
            "2026-06-02T18:00:00Z", "2026-06-02T19:00:00Z", "OFFPEAK", pay_source="WALLET")
        confirm_reservation(res_a["id"], member["id"], bay["version"])
        return venue, bay, member

    def test_lesson_overlapping_confirmed_reservation_rejected(self, api):
        """PRD §3.11: "A lesson may not be scheduled on a bay whose window overlaps an
        existing `CONFIRMED` reservation or `SCHEDULED` lesson on that bay, judged on
        the same half-open interval as reservations, and an overlap is rejected with
        `ERR_BAY_WINDOW_CONFLICT`; a bay that is `OUT_OF_SERVICE` likewise rejects
        with `ERR_BAY_UNAVAILABLE`."

        Scheduling a PRIVATE_LESSON 18:30-19:30 that overlaps a CONFIRMED reservation
        18:00-19:00 on the same bay is rejected with ERR_BAY_WINDOW_CONFLICT.

        Design: Difficulty/resource_temporal_overlap/lesson_overlapping_confirmed_reservation_rejected_on_bay
        """
        venue, bay, member = self._confirmed_reservation_bay(api)
        payload = create_lesson_payload(
            venue["id"], bay["id"], member["id"], "PRIVATE_LESSON",
            "2026-06-02T18:30:00Z", "2026-06-02T19:30:00Z", seats=1)
        resp = api.create_lesson(payload, make_guest_headers(member["id"]))
        validate_error(resp, "ERR_BAY_WINDOW_CONFLICT", expected_status=409)

    def test_lesson_back_to_back_reservation_allowed(self, api):
        """PRD §3.11: "A lesson may not be scheduled on a bay whose window overlaps an
        existing `CONFIRMED` reservation or `SCHEDULED` lesson on that bay, judged on
        the same half-open interval as reservations, and an overlap is rejected with
        `ERR_BAY_WINDOW_CONFLICT`; a bay that is `OUT_OF_SERVICE` likewise rejects
        with `ERR_BAY_UNAVAILABLE`."
        PRD §3.3: "...two bookings that touch exactly at a boundary are back-to-back
        and permitted..."

        Half-open semantics for the cross-entity case: a lesson 19:00-20:00 starting
        exactly when CONFIRMED reservation A ends is back-to-back and scheduled
        (status SCHEDULED), confirming the same adjacency rule applies to lessons.

        Design: Difficulty/resource_temporal_overlap/lesson_overlapping_confirmed_reservation_rejected_on_bay
        """
        venue, bay, member = self._confirmed_reservation_bay(api)
        payload = create_lesson_payload(
            venue["id"], bay["id"], member["id"], "PRIVATE_LESSON",
            "2026-06-02T19:00:00Z", "2026-06-02T20:00:00Z", seats=1)
        lesson = validate_success(
            api.create_lesson(payload, make_guest_headers(member["id"])), 201)
        assert lesson["status"] == "SCHEDULED"


# ===========================================================================
# Queue B — validations instances
# ===========================================================================
def test_peak_demand_factor_out_of_range_returns_validation_range(api):
    """PRD §3.1: "...`peak_demand_factor`, an operator-set surge factor folded into
    the dynamic price, which defaults to 1.0 and must lie between 0.5 and 1.5
    inclusive. A `peak_demand_factor` outside that band is rejected with
    `ERR_VALIDATION_RANGE`."

    Creating a venue with peak_demand_factor 2.0 (outside [0.5,1.5]) returns
    ERR_VALIDATION_RANGE (422).

    Design: Corner/validations/peak_demand_factor_out_of_range_returns_validation_range
    """
    from test_helpers import create_venue_payload
    resp = api.create_venue(create_venue_payload(peak_demand_factor=2.0), RM)
    validate_error(resp, "ERR_VALIDATION_RANGE", expected_status=422)


def test_reservation_non_30_min_span_returns_invalid_request(api):
    """PRD §3.3: "The window is validated up front: `end_utc` must be strictly after
    `start_utc`, the span must be a whole number of 30-minute segments, and the
    window must fall within the venue's open and close minutes. A malformed body — a
    missing required field, an invalid enum, a non-positive span, a span that is not a
    whole number of 30-minute segments, or a window outside venue hours — is rejected
    with `ERR_INVALID_REQUEST`."

    A 45-minute window (not a whole number of 30-min segments) returns
    ERR_INVALID_REQUEST (400).

    Design: Corner/validations/reservation_non_30_min_span_returns_invalid_request
    """
    venue, bay, member = setup_venue_bay_member()
    payload = create_reservation_payload(
        venue["id"], bay["id"], member["id"],
        "2026-06-02T18:00:00Z", "2026-06-02T18:45:00Z", "OFFPEAK")
    resp = api.create_reservation(payload, make_guest_headers(member["id"]))
    validate_error(resp, "ERR_INVALID_REQUEST", expected_status=400)


def test_seat_next_no_available_bay_returns_no_bay_available(api):
    """PRD §3.5: "There must be at least one bay at the venue whose `status` is
    `AVAILABLE`; if none is available the seating is rejected with
    `ERR_NO_BAY_AVAILABLE`."

    seat_next when the venue's only bay is OUT_OF_SERVICE returns
    ERR_NO_BAY_AVAILABLE (409).

    Design: Corner/validations/seat_next_no_available_bay_returns_no_bay_available
    """
    set_clock("2026-06-01T12:00:00Z")
    venue = create_venue(bay_count=1)
    bay = create_bay(venue["id"])
    take_bay_out_of_service(bay["id"], bay["version"])
    member = create_member()
    create_queue_ticket(venue["id"], member["id"])
    resp = api.seat_next(venue["id"], {"expected_venue_version": venue["version"]}, FD)
    validate_error(resp, "ERR_NO_BAY_AVAILABLE", expected_status=409)


def test_seat_next_non_head_ticket_blocked_by_queue_head_rule(api):
    """PRD §3.5: "Seating targets the venue, carries `expected_venue_version` (see
    §2.5), and applies to the lowest-position waiting ticket — the one whose
    `position` is 1. If the targeted operation is attempted when the queue head is
    some other ticket, it is rejected with `ERR_NOT_QUEUE_HEAD`."
    PRD §3.5: "The ticket is created `WAITING`, and its `position` is computed as its
    1-based rank among the venue's `WAITING` tickets ordered by `created_at`
    ascending."

    With two WAITING tickets, seat_next seats only T1 (the position-1 ticket); T2 stays
    WAITING and becomes the new head (position 1).

    Design: Corner/validations/seat_next_non_head_ticket_blocked_by_queue_head_rule
    """
    set_clock("2026-06-01T12:00:00Z")
    venue = create_venue(bay_count=1)
    bay = create_bay(venue["id"])
    m1 = create_member()
    m2 = create_member()
    t1 = create_queue_ticket(venue["id"], m1["id"])
    t2 = create_queue_ticket(venue["id"], m2["id"])
    validate_success(
        api.seat_next(venue["id"], {"expected_venue_version": venue["version"]}, FD), 200)
    t1_after = validate_success(api.get_queue_ticket(t1["id"], FD), 200)
    t2_after = validate_success(api.get_queue_ticket(t2["id"], FD), 200)
    assert t1_after["status"] == "SEATED"
    assert t2_after["status"] == "WAITING"
    assert t2_after["position"] == 1
