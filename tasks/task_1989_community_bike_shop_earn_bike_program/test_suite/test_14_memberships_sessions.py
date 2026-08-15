"""Tool memberships and stand sessions: suspend/reinstate cycle (queue A),
cross-entity session gating (queue A), stand buffer semantics (queue A), and
membership/session corner cases (queue B)."""
from test_helpers import (
    api_client, validate_success, validate_error,
    make_membership, book_session, set_clock,
    TEST_USERS, make_member_headers,
    ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]
DIRECTOR = TEST_USERS["director_headers"]


class TestMembershipSuspendReinstateCycle:
    def test_booking_rejected_while_suspended(self):
        """PRD §3.12: "Booking — by a coordinator, or by the member for their
        own membership — requires the membership `ACTIVE` (else
        `ERR_MEMBERSHIP_NOT_ACTIVE`)".

        Design: Difficulty/non_linear_state_machine/membership_suspend_reinstate_cycle
        """
        m = make_membership(member_name="M Cyc", member_email="mc@x.org",
                            tier="PRO", end_date="2026-12-31")
        s1 = book_session(m["id"], 1, "2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z")
        assert s1["status"] == "BOOKED"
        validate_success(
            api_client.suspend_membership(m["id"], {"reason": "misuse"}, COORD)
        )
        r = api_client.book_session(
            m["id"],
            {"stand_number": 1, "start_time": "2026-08-05T12:00:00Z",
             "end_time": "2026-08-05T13:00:00Z"},
            make_member_headers(m["id"]),
        )
        validate_error(r, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE)

    def test_booking_succeeds_again_after_reinstate(self):
        """PRD §3.12: "A coordinator may suspend a membership — recording an
        optional `suspended_reason` — and later reinstate it; the `ACTIVE →
        SUSPENDED → ACTIVE` cycle may repeat freely."

        Design: Difficulty/non_linear_state_machine/membership_suspend_reinstate_cycle
        """
        m = make_membership(member_name="M Cyc2", member_email="mc2@x.org",
                            tier="PRO", end_date="2026-12-31")
        validate_success(
            api_client.suspend_membership(m["id"], {"reason": "misuse"}, COORD)
        )
        reinstated = validate_success(api_client.reinstate_membership(m["id"], COORD))
        assert reinstated["status"] == "ACTIVE"
        s3 = book_session(m["id"], 1, "2026-08-05T14:00:00Z", "2026-08-05T15:00:00Z")
        assert s3["status"] == "BOOKED"


class TestSessionBookingGatedOnMembership:
    def test_session_booking_blocked_when_membership_not_active(self):
        """PRD §3.12: "Booking — by a coordinator, or by the member for their
        own membership — requires the membership `ACTIVE` (else
        `ERR_MEMBERSHIP_NOT_ACTIVE`)" and "The ops sweep expires a membership
        from either `ACTIVE` or `SUSPENDED` once the clock's date passes
        `end_date`, moving it to `EXPIRED`."

        Design: Difficulty/cross_entity_state_dependency/session_booking_blocked_when_membership_not_active
        """
        ma = make_membership(member_name="M A", member_email="ma@x.org",
                             tier="BASIC", end_date="2026-12-31")
        mb = make_membership(member_name="M B", member_email="mb@x.org",
                             tier="BASIC", end_date="2026-08-10")
        validate_success(
            api_client.suspend_membership(ma["id"], {"reason": "misuse"}, COORD)
        )
        set_clock("2026-08-20T00:00:00Z")
        sweep = validate_success(api_client.run_sweep(COORD))
        assert sweep["memberships_expired"] == 1
        mb_after = validate_success(api_client.get_membership(mb["id"], COORD))
        assert mb_after["status"] == "EXPIRED"

        ra = api_client.book_session(
            ma["id"],
            {"stand_number": 1, "start_time": "2026-08-21T10:00:00Z",
             "end_time": "2026-08-21T11:00:00Z"},
            make_member_headers(ma["id"]),
        )
        validate_error(ra, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE)
        rb = api_client.book_session(
            mb["id"],
            {"stand_number": 2, "start_time": "2026-08-21T10:00:00Z",
             "end_time": "2026-08-21T11:00:00Z"},
            make_member_headers(mb["id"]),
        )
        validate_error(rb, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE)

    def test_suspended_membership_blocks_session_start_and_booking_identically(self):
        """PRD §3.12: "Booking — by a coordinator, or by the member for their
        own membership — requires the membership `ACTIVE` (else
        `ERR_MEMBERSHIP_NOT_ACTIVE`)" and "The membership must still be `ACTIVE`
        (else `ERR_MEMBERSHIP_NOT_ACTIVE`)".

        Design: Difficulty/cross_entity_state_dependency/session_booking_blocked_when_membership_not_active
        """
        m = make_membership(member_name="M G", member_email="mg@x.org",
                            tier="BASIC", end_date="2026-12-31")
        s = book_session(m["id"], 1, "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")
        validate_success(
            api_client.suspend_membership(m["id"], {"reason": "misuse"}, COORD)
        )
        set_clock("2026-08-10T10:00:00Z")
        r_start = api_client.start_session(s["id"], make_member_headers(m["id"]))
        validate_error(r_start, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE)
        r_book = api_client.book_session(
            m["id"],
            {"stand_number": 1, "start_time": "2026-08-10T12:00:00Z",
             "end_time": "2026-08-10T13:00:00Z"},
            make_member_headers(m["id"]),
        )
        validate_error(r_book, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE)


class TestStandBuffer:
    def test_stand_buffer_gap_semantics(self):
        """PRD §3.12: "The shop enforces a 15-minute cleanup buffer per stand:
        against every `BOOKED` or `IN_USE` session on the same stand, the new
        session must either begin at least 15 minutes after the existing
        session ends or end at least 15 minutes before the existing one begins;
        mere adjacency with a shorter gap is rejected with
        `ERR_STAND_BUFFER_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/stand_buffer_gap_semantics
        """
        m = make_membership(member_name="M S", member_email="ms@x.org",
                            tier="BASIC", end_date="2026-12-31")
        book_session(m["id"], 2, "2026-08-10T10:00:00Z", "2026-08-10T12:00:00Z")
        r_adj = api_client.book_session(
            m["id"],
            {"stand_number": 2, "start_time": "2026-08-10T12:00:00Z",
             "end_time": "2026-08-10T14:00:00Z"},
            make_member_headers(m["id"]),
        )
        validate_error(r_adj, ApiErrorId.ERR_STAND_BUFFER_CONFLICT)
        r_14 = api_client.book_session(
            m["id"],
            {"stand_number": 2, "start_time": "2026-08-10T12:14:00Z",
             "end_time": "2026-08-10T14:00:00Z"},
            make_member_headers(m["id"]),
        )
        validate_error(r_14, ApiErrorId.ERR_STAND_BUFFER_CONFLICT)
        ok_15 = validate_success(
            api_client.book_session(
                m["id"],
                {"stand_number": 2, "start_time": "2026-08-10T12:15:00Z",
                 "end_time": "2026-08-10T14:00:00Z"},
                make_member_headers(m["id"]),
            ),
            expected_status=201,
        )
        assert ok_15["status"] == "BOOKED"
        ok_other = validate_success(
            api_client.book_session(
                m["id"],
                {"stand_number": 3, "start_time": "2026-08-10T10:30:00Z",
                 "end_time": "2026-08-10T11:30:00Z"},
                make_member_headers(m["id"]),
            ),
            expected_status=201,
        )
        assert ok_other["status"] == "BOOKED"

    def test_stand_buffer_applies_before_existing_session(self):
        """PRD §3.12: "The shop enforces a 15-minute cleanup buffer per stand:
        against every `BOOKED` or `IN_USE` session on the same stand, the new
        session must either begin at least 15 minutes after the existing
        session ends or end at least 15 minutes before the existing one begins;
        mere adjacency with a shorter gap is rejected with
        `ERR_STAND_BUFFER_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/stand_buffer_gap_semantics
        """
        m = make_membership(member_name="M S2", member_email="ms2@x.org",
                            tier="BASIC", end_date="2026-12-31")
        # existing session 12:00-14:00 on stand 1
        book_session(m["id"], 1, "2026-08-10T12:00:00Z", "2026-08-10T14:00:00Z")
        # new session ends 11:45 -> gap exactly 15m before existing start: allowed
        ok = validate_success(
            api_client.book_session(
                m["id"],
                {"stand_number": 1, "start_time": "2026-08-10T10:00:00Z",
                 "end_time": "2026-08-10T11:45:00Z"},
                make_member_headers(m["id"]),
            ),
            expected_status=201,
        )
        assert ok["status"] == "BOOKED"
        # new session ends 11:46 -> gap 14m < 15m: rejected
        r = api_client.book_session(
            m["id"],
            {"stand_number": 1, "start_time": "2026-08-10T10:00:00Z",
             "end_time": "2026-08-10T11:46:00Z"},
            make_member_headers(m["id"]),
        )
        validate_error(r, ApiErrorId.ERR_STAND_BUFFER_CONFLICT)


class TestSessionCorners:
    def test_expired_membership_lockdown(self):
        """PRD §3.12: "The ops sweep expires a membership from either `ACTIVE`
        or `SUSPENDED` once the clock's date passes `end_date`, moving it to
        `EXPIRED`." and PRD §2.7: "`ERR_INVALID_STATE` when no more specific
        code applies".

        Design: Corner/state_machines/expired_membership_lockdown
        """
        m = make_membership(member_name="M X", member_email="mx@x.org",
                            tier="BASIC", end_date="2026-08-10")
        set_clock("2026-08-20T00:00:00Z")
        sweep = validate_success(api_client.run_sweep(COORD))
        assert sweep["memberships_expired"] == 1
        r1 = api_client.suspend_membership(m["id"], {"reason": "late"}, COORD)
        validate_error(r1, ApiErrorId.ERR_INVALID_STATE)
        r2 = api_client.reinstate_membership(m["id"], COORD)
        validate_error(r2, ApiErrorId.ERR_INVALID_STATE)

    def test_session_duration_and_stand_range(self):
        """PRD §3.12: "a `stand_number` between 1 and 4 inclusive (else
        `ERR_STAND_NUMBER_INVALID`), and a `start_time` and `end_time` whose
        span runs 30 to 180 minutes inclusive (else
        `ERR_SESSION_DURATION_INVALID`)".

        Design: Corner/validations/session_duration_and_stand_range
        """
        m = make_membership(member_name="M R", member_email="mr@x.org",
                            tier="BASIC", end_date="2026-12-31")
        r_stand = api_client.book_session(
            m["id"],
            {"stand_number": 5, "start_time": "2026-08-10T10:00:00Z",
             "end_time": "2026-08-10T11:00:00Z"},
            make_member_headers(m["id"]),
        )
        validate_error(r_stand, ApiErrorId.ERR_STAND_NUMBER_INVALID)
        r_dur = api_client.book_session(
            m["id"],
            {"stand_number": 1, "start_time": "2026-08-10T10:00:00Z",
             "end_time": "2026-08-10T10:20:00Z"},
            make_member_headers(m["id"]),
        )
        validate_error(r_dur, ApiErrorId.ERR_SESSION_DURATION_INVALID)
        ok30 = validate_success(
            api_client.book_session(
                m["id"],
                {"stand_number": 4, "start_time": "2026-08-10T10:00:00Z",
                 "end_time": "2026-08-10T10:30:00Z"},
                make_member_headers(m["id"]),
            ),
            expected_status=201,
        )
        assert ok30["status"] == "BOOKED"
        ok180 = validate_success(
            api_client.book_session(
                m["id"],
                {"stand_number": 4, "start_time": "2026-08-10T11:00:00Z",
                 "end_time": "2026-08-10T14:00:00Z"},
                make_member_headers(m["id"]),
            ),
            expected_status=201,
        )
        assert ok180["status"] == "BOOKED"

    def test_session_start_too_early_boundary(self):
        """PRD §3.12: "the clock must have reached 10 minutes before
        `start_time` — starting earlier is rejected with
        `ERR_START_TOO_EARLY`."

        Design: Corner/validations/session_start_too_early_boundary
        """
        m = make_membership(member_name="M E", member_email="me@x.org",
                            tier="BASIC", end_date="2026-12-31")
        s = book_session(m["id"], 1, "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")
        set_clock("2026-08-10T09:49:00Z")
        r = api_client.start_session(s["id"], make_member_headers(m["id"]))
        validate_error(r, ApiErrorId.ERR_START_TOO_EARLY)
        set_clock("2026-08-10T09:50:00Z")
        ok = validate_success(
            api_client.start_session(s["id"], make_member_headers(m["id"]))
        )
        assert ok["status"] == "IN_USE"
        assert ok["started_at"] is not None

    def test_member_cannot_book_for_other_membership(self):
        """PRD §3.12: "Booking — by a coordinator, or by the member for their
        own membership" and PRD §2.1: "A request whose authenticated role is
        not in the endpoint's authorized list, or whose entity-backed identity
        does not own the targeted resource, is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/member_cannot_book_for_other_membership
        """
        m1 = make_membership(member_name="M 1", member_email="m1@x.org",
                             tier="BASIC", end_date="2026-12-31")
        m2 = make_membership(member_name="M 2", member_email="m2@x.org",
                             tier="BASIC", end_date="2026-12-31")
        r = api_client.book_session(
            m2["id"],
            {"stand_number": 1, "start_time": "2026-08-10T10:00:00Z",
             "end_time": "2026-08-10T11:00:00Z"},
            make_member_headers(m1["id"]),
        )
        validate_error(r, ApiErrorId.ERR_FORBIDDEN)
