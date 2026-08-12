"""Session booking windows, lane capacity, check-in/close lifecycle gates,
and the no-show sweep."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_participant_payload,
    add_wallet_participant,
    api_client,
    book_session,
    create_lane,
    create_range_session_payload,
    fund_wallet,
    get_member,
    get_session,
    list_participants_for_session,
    make_member_headers,
    register_member,
    register_ready_member,
    set_clock,
    setup_checked_in_session,
    sign_waiver,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

RANGE_OFFICER = TEST_USERS["range_officer_headers"]


class TestBookingWindows:
    def test_walkin_session_not_same_day_rejected(self, api):
        """PRD §3.3: "a `RESERVATION` must start at least 120 minutes after the
        current logical clock, while a `WALK_IN` must start on the same UTC date
        as the current clock and end after it; violations are rejected with
        `ERR_BOOKING_WINDOW_VIOLATION`."

        Design: Corner/validations/walkin_session_not_same_day_rejected
        """
        set_clock("2026-05-01T08:00:00Z")
        member = register_ready_member("wi@x.com", full_name="Walk In")
        lane = create_lane("WL1")

        resp = api.create_range_session(
            create_range_session_payload(
                lane["id"], "WALK_IN",
                "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z",
            ),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BOOKING_WINDOW_VIOLATION)
        sessions = validate_success(
            api.list_lane_sessions(lane["id"], RANGE_OFFICER), 200
        )
        assert sessions == [], "no session may be created on window violation"

    def test_reservation_lead_under_120min_rejected(self, api):
        """PRD §3.3: "a `RESERVATION` must start at least 120 minutes after the
        current logical clock, while a `WALK_IN` must start on the same UTC date
        as the current clock and end after it; violations are rejected with
        `ERR_BOOKING_WINDOW_VIOLATION`."

        Design: Corner/validations/reservation_lead_under_120min_rejected
        """
        set_clock("2026-05-01T08:00:00Z")
        member = register_ready_member("lead@x.com", full_name="Lead Time")
        lane = create_lane("LL")

        # 60 minutes of lead: under the 120-minute minimum.
        resp = api.create_range_session(
            create_range_session_payload(
                lane["id"], "RESERVATION",
                "2026-05-01T09:00:00Z", "2026-05-01T10:00:00Z",
            ),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BOOKING_WINDOW_VIOLATION)
        sessions = validate_success(
            api.list_lane_sessions(lane["id"], RANGE_OFFICER), 200
        )
        assert sessions == [], "no session may be created on window violation"


class TestLaneCapacityAndFunds:
    def test_lane_capacity_third_archer_rejected(self, api):
        """PRD §3.3: "the roster of `ACTIVE` participants must stay within the
        lane's `max_archers` (`ERR_LANE_CAPACITY_EXCEEDED`)".

        Design: Corner/validations/lane_capacity_third_archer_rejected
        """
        set_clock("2026-05-01T08:00:00Z")
        owner = register_ready_member("cap@x.com", wallet_cents=30000)
        guest1 = register_ready_member("capg1@x.com", wallet_cents=10000)
        guest2 = register_ready_member("capg2@x.com", wallet_cents=10000)
        lane = create_lane("CAPL", max_archers=2)
        session = book_session(
            owner["id"], lane["id"], "RESERVATION",
            "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z",
        )
        # Count == cap is legal: owner and guest1 fill the lane.
        add_wallet_participant(session["id"], owner["id"], owner["id"])
        add_wallet_participant(session["id"], guest1["id"], owner["id"])

        resp = api.add_participant(
            session["id"],
            add_participant_payload(guest2["id"], "WALLET"),
            make_member_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LANE_CAPACITY_EXCEEDED)
        participants = list_participants_for_session(session["id"])
        assert len(participants) == 2

    def test_participant_add_with_insufficient_funds_rejected(self, api):
        """PRD §3.3: "A wallet payment debits `quoted_fee_cents` from the
        archer's `wallet_balance_cents` (`ERR_INSUFFICIENT_FUNDS` if short)".

        Design: Corner/validations/participant_add_with_insufficient_funds_rejected
        """
        set_clock("2026-05-01T08:00:00Z")
        member = register_ready_member("poor@x.com", wallet_cents=100)
        lane = create_lane("PL")
        session = book_session(
            member["id"], lane["id"], "RESERVATION",
            "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z",
        )

        resp = api.add_participant(
            session["id"],
            add_participant_payload(member["id"], "WALLET"),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS)
        participants = list_participants_for_session(session["id"])
        assert participants == [], "no participant may be created"
        assert get_member(member["id"])["wallet_balance_cents"] == 100


class TestSessionLifecycleGates:
    def test_session_second_checkin_rejected(self, api):
        """PRD §3.3: "The session must be `BOOKED` (`ERR_SESSION_NOT_BOOKED`;
        operating on a session that already reached a terminal state such as
        `CLOSED` surfaces `ERR_SESSION_ALREADY_CLOSED`) ... A successful
        check-in stamps `checked_in_at` from the logical clock and moves
        `session_status` to `CHECKED_IN`."

        Design: Corner/state_machines/session_second_checkin_rejected
        """
        set_clock("2026-05-01T08:00:00Z")
        member, lane, session, _ = setup_checked_in_session(
            clock_checkin="2026-05-01T10:00:00Z",
            email="ci@x.com",
            lane_name="CIL",
            start_at="2026-05-01T10:00:00Z",
            end_at="2026-05-01T11:00:00Z",
        )
        checked_in_at = session["checked_in_at"]

        resp = api.check_in_session(session["id"], RANGE_OFFICER)
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_BOOKED)
        after = get_session(session["id"])
        assert after["session_status"] == "CHECKED_IN"
        assert after["checked_in_at"] == checked_in_at

    def test_session_cancel_after_close_rejected(self, api):
        """PRD §3.3: "operating on a session that already reached a terminal
        state such as `CLOSED` surfaces `ERR_SESSION_ALREADY_CLOSED`".
        PRD §3.4: "A `BOOKED` session may be cancelled voluntarily by its
        creator or a `RangeOfficer`; cancelling from any other state is
        `ERR_SESSION_NOT_BOOKED`."
        PRD §3.3: "`final_charge_cents` remains null until close, just as
        `cancellation_refund_cents` remains null until a cancellation."

        Design: Corner/state_machines/session_cancel_after_close_rejected
        """
        set_clock("2026-05-01T08:00:00Z")
        member, lane, session, _ = setup_checked_in_session(
            clock_checkin="2026-05-01T10:00:00Z",
            email="term@x.com",
            tier="PLUS",
            lane_name="TL",
            start_at="2026-05-01T10:00:00Z",
            end_at="2026-05-01T11:00:00Z",
        )
        set_clock("2026-05-01T10:30:00Z")
        closed = validate_success(api.close_session(session["id"], RANGE_OFFICER), 200)
        assert closed["session_status"] == "CLOSED"

        resp = api.cancel_session(session["id"], make_member_headers(member["id"]))
        # §3.3 names ERR_SESSION_ALREADY_CLOSED for operations on terminal
        # sessions while §3.4 names ERR_SESSION_NOT_BOOKED for cancel from a
        # non-BOOKED state; either surface is a faithful reading.
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_SESSION_ALREADY_CLOSED,
             ApiErrorId.ERR_SESSION_NOT_BOOKED],
        )
        after = get_session(session["id"])
        assert after["session_status"] == "CLOSED"
        assert after["cancellation_refund_cents"] is None


class TestNoShowSweep:
    def test_no_show_sweep_forfeits_fees(self, api):
        """PRD §3.4: "If nobody checks in, the epoch sweep does the punishing: a
        session still `BOOKED` once the clock passes fifteen minutes after
        `start_at` becomes `NO_SHOW`. All quoted fees are forfeited — wallet
        participants keep their debit and punch participants lose their punch,
        every participant becoming `FORFEITED` — and the same rental-void
        cascade runs."
        PRD §3.3: "`CANCELLED` or `NO_SHOW` sessions that issued refunds show
        `REFUNDED`."

        Design: Corner/state_machines/no_show_sweep_forfeits_fees
        """
        set_clock("2026-05-01T08:00:00Z")
        member = register_ready_member("ns@x.com", tier="PLUS", wallet_cents=10000)
        lane = create_lane("NL")
        session = book_session(
            member["id"], lane["id"], "RESERVATION",
            "2026-05-01T10:00:00Z", "2026-05-01T11:00:00Z",
        )
        participant = add_wallet_participant(session["id"], member["id"], member["id"])
        assert participant["quoted_fee_cents"] == 2160
        assert get_member(member["id"])["wallet_balance_cents"] == 7840

        # 10:16 is past start_at + 15 minutes without check-in: sweep fires.
        set_clock("2026-05-01T10:16:00Z")
        after = get_session(session["id"])
        assert after["session_status"] == "NO_SHOW"
        assert after["payment_status"] == "PAID", (
            "a NO_SHOW that issued no refund keeps payment_status PAID"
        )

        participants = list_participants_for_session(session["id"])
        assert len(participants) == 1
        assert participants[0]["status"] == "FORFEITED"
        assert get_member(member["id"])["wallet_balance_cents"] == 7840, (
            "forfeited quoted fee is NOT refunded"
        )
