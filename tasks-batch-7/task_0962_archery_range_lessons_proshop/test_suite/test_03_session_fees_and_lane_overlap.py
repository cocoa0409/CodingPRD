"""Lane fee dual variants (quoted vs final metered), peak/tier/walk-in
interaction, and lane half-open overlap semantics."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_wallet_participant,
    api_client,
    assert_range_session,
    book_session,
    create_lane,
    create_range_session_payload,
    get_member,
    get_session,
    make_member_headers,
    register_ready_member,
    set_clock,
    setup_booked_wallet_session,
    validate_error,
    validate_success,
)

RANGE_OFFICER = TEST_USERS["range_officer_headers"]


def _setup_metered_session(api):
    """PLUS member, 60 booked off-peak minutes, checked in at 10:00, clock at
    10:20 (20 actual minutes). Returns (member, session_id, participant)."""
    set_clock("2026-05-01T08:00:00Z")
    member, lane, session, participant = setup_booked_wallet_session(
        email="plus@x.com", tier="PLUS", wallet_cents=10000, lane_name="L1",
        start_at="2026-05-01T10:00:00Z", end_at="2026-05-01T11:00:00Z",
    )
    set_clock("2026-05-01T10:00:00Z")
    validate_success(api.check_in_session(session["id"], RANGE_OFFICER), 200)
    set_clock("2026-05-01T10:20:00Z")
    return member, session, participant


class TestSessionQuotedVsFinalMeteredCharge:
    def test_quoted_charge_metered_on_booked_minutes(self, api):
        """PRD §3.3: "The lane fee has two variants, both tiered over 30-minute
        blocks at a base rate of 1200 cents per block, with a peak multiplier of
        1.25 when the session's `start_at` falls in a peak hour — UTC hours 17
        through 20 inclusive — and a tier discount keyed to the **participant's**
        membership tier: 0% for `BASIC`, 10% for `PLUS`, 20% for `ELITE`."
        PRD §3.3: "The quoted variant, metered on `booked_minutes`, computes:
        the number of blocks is `booked_minutes` divided by 30 rounded up to a
        whole number; the base is 1200 times that block count; ... the tier
        discount is then applied and the result rounded half up; the fee is the
        greater of that discounted amount and the 1200-cent minimum charge".

        Design: Difficulty/dual_variant_calc/session_quoted_vs_final_metered_charge
        """
        set_clock("2026-05-01T08:00:00Z")
        member, lane, session, participant = setup_booked_wallet_session(
            email="plus@x.com", tier="PLUS", wallet_cents=10000, lane_name="L1",
            start_at="2026-05-01T10:00:00Z", end_at="2026-05-01T11:00:00Z",
        )
        # 60 booked off-peak minutes: 2 blocks x 1200 = 2400, PLUS 10% -> 2160.
        assert participant["quoted_fee_cents"] == 2160
        booked = get_session(session["id"])
        assert booked["quoted_charge_cents"] == 2160
        assert booked["session_status"] == "BOOKED"
        assert booked["payment_status"] == "PAID"
        assert get_member(member["id"])["wallet_balance_cents"] == 7840

    def test_final_charge_metered_on_actual_minutes_with_floor(self, api):
        """PRD §3.3: "The final variant, computed at close, is metered on
        actual checked-in time: the elapsed seconds between `checked_in_at` and
        `closed_at` are divided by 60 and rounded up to whole minutes; blocks,
        base, peak (still keyed on the session's `start_at`), discount, and the
        1200-cent floor apply exactly as in the quoted variant — but the walk-in
        surcharge is **never** applied in the final variant."
        PRD §3.3: "It stamps `closed_at`, recomputes every `ACTIVE`
        participant's `final_fee_cents` under the final variant, and sets the
        session's `final_charge_cents` to their sum."

        Design: Difficulty/dual_variant_calc/session_quoted_vs_final_metered_charge
        """
        member, session, participant = _setup_metered_session(api)

        closed = validate_success(api.close_session(session["id"], RANGE_OFFICER), 200)
        assert_range_session(closed)
        # 20 metered minutes -> 1 block -> 1200 x 0.9 = 1080 -> floor 1200.
        assert closed["final_charge_cents"] == 1200
        assert closed["quoted_charge_cents"] == 2160, (
            "quoted variant retained alongside the final variant"
        )
        assert closed["session_status"] == "CLOSED"
        assert closed["payment_status"] == "PAID"

        final_participant = validate_success(
            api.get_participant(participant["id"], RANGE_OFFICER), 200
        )
        assert final_participant["final_fee_cents"] == 1200

        # Wallet reconciliation: 10000 - 2160 quoted debit + 960 credit.
        assert get_member(member["id"])["wallet_balance_cents"] == 8800


class TestSessionFeePeakWalkinTierInteraction:
    def test_basic_walkin_peak_fee(self, api):
        """PRD §3.3: "if the session is peak, the base is multiplied by 1.25
        and rounded half up; the tier discount is then applied and the result
        rounded half up; the fee is the greater of that discounted amount and
        the 1200-cent minimum charge; and finally, for a `WALK_IN` booking only,
        a 300-cent surcharge is added **after** the minimum-charge floor."

        Design: Difficulty/combinatorial_formula/session_fee_peak_walkin_tier_interaction
        """
        set_clock("2026-05-01T08:00:00Z")
        member = register_ready_member("wb@x.com", full_name="Walk Basic",
                                       wallet_cents=10000)
        lane = create_lane("P1")
        # Same-day walk-in at 18:00 (peak hour) for 60 minutes.
        session = book_session(
            member["id"], lane["id"], "WALK_IN",
            "2026-05-01T18:00:00Z", "2026-05-01T19:00:00Z",
        )
        participant = add_wallet_participant(session["id"], member["id"], member["id"])
        # 2400 base x 1.25 peak = 3000, BASIC no discount, +300 after floor.
        assert participant["quoted_fee_cents"] == 3300
        assert get_member(member["id"])["wallet_balance_cents"] == 6700

    def test_elite_reserved_offpeak_90min_fee(self, api):
        """PRD §3.3: "the number of blocks is `booked_minutes` divided by 30
        rounded up to a whole number; the base is 1200 times that block count;
        if the session is peak, the base is multiplied by 1.25 and rounded half
        up; the tier discount is then applied and the result rounded half up;
        the fee is the greater of that discounted amount and the 1200-cent
        minimum charge".

        Design: Difficulty/combinatorial_formula/session_fee_peak_walkin_tier_interaction
        """
        set_clock("2026-05-01T08:00:00Z")
        member = register_ready_member("re@x.com", full_name="Res Elite",
                                       tier="ELITE", wallet_cents=10000)
        lane = create_lane("P2", lane_type="OUTDOOR")
        # 90 off-peak minutes on the following day.
        session = book_session(
            member["id"], lane["id"], "RESERVATION",
            "2026-05-02T10:00:00Z", "2026-05-02T11:30:00Z",
        )
        participant = add_wallet_participant(session["id"], member["id"], member["id"])
        # 3 blocks x 1200 = 3600 x 0.8 ELITE = 2880.
        assert participant["quoted_fee_cents"] == 2880
        assert get_member(member["id"])["wallet_balance_cents"] == 7120


class TestLaneHalfOpenIntervalAdjacency:
    def _setup_first_booking(self, api):
        set_clock("2026-05-01T08:00:00Z")
        member = register_ready_member("ov@x.com", full_name="Overlap Tester")
        lane = create_lane("OL", lane_type="OUTDOOR")
        first = book_session(
            member["id"], lane["id"], "RESERVATION",
            "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z",
        )
        return member, lane, first

    def test_adjacent_back_to_back_booking_allowed(self, api):
        """PRD §3.3: "Lane occupancy is the half-open interval from `start_at`
        inclusive to `end_at` exclusive, so back-to-back bookings are allowed,
        but any strict overlap with an existing `BOOKED` or `CHECKED_IN` session
        on the same lane is rejected with `ERR_LANE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/lane_half_open_interval_adjacency
        """
        member, lane, first = self._setup_first_booking(api)
        # [11:00, 12:00) touches [10:00, 11:00) but does not strictly overlap.
        resp = api.create_range_session(
            create_range_session_payload(
                lane["id"], "RESERVATION",
                "2026-05-02T11:00:00Z", "2026-05-02T12:00:00Z",
            ),
            make_member_headers(member["id"]),
        )
        second = validate_success(resp, 201)
        assert second["id"] != first["id"]
        assert second["session_status"] == "BOOKED"

    def test_strictly_overlapping_booking_rejected(self, api):
        """PRD §3.3: "Lane occupancy is the half-open interval from `start_at`
        inclusive to `end_at` exclusive, so back-to-back bookings are allowed,
        but any strict overlap with an existing `BOOKED` or `CHECKED_IN` session
        on the same lane is rejected with `ERR_LANE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/lane_half_open_interval_adjacency
        """
        member, lane, first = self._setup_first_booking(api)
        resp = api.create_range_session(
            create_range_session_payload(
                lane["id"], "RESERVATION",
                "2026-05-02T10:30:00Z", "2026-05-02T11:30:00Z",
            ),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LANE_OVERLAP)
        sessions = validate_success(
            api.list_lane_sessions(lane["id"], RANGE_OFFICER), 200
        )
        assert len(sessions) == 1, "overlapping booking must not be persisted"
