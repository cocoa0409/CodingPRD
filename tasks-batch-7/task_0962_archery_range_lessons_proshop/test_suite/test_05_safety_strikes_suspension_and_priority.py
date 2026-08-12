"""Safety-strike suspension cascade, validation priority pairs, and the
check-in cross-entity waiver gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_wallet_participant,
    api_client,
    book_session,
    create_lane,
    create_range_session_payload,
    create_rental_agreement,
    create_rental_item,
    fund_wallet,
    get_member,
    get_rental_agreement,
    get_rental_item_via_list,
    get_session,
    make_member_headers,
    purchase_punch_card_payload,
    register_member,
    register_ready_member,
    set_clock,
    setup_booked_wallet_session,
    sign_waiver,
    suspend_member_with_strikes,
    validate_error,
    validate_success,
)

RANGE_OFFICER = TEST_USERS["range_officer_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestMemberSuspensionThreeHopCascade:
    def _setup_suspension_scenario(self, api):
        """PLUS member with a future BOOKED session (self WALLET participant,
        quoted 2160) and an OPEN rental agreement linked to that session."""
        set_clock("2026-05-01T08:00:00Z")
        member = register_ready_member("risky@x.com", tier="PLUS",
                                       wallet_cents=10000)
        lane = create_lane("CL")
        session = book_session(
            member["id"], lane["id"], "RESERVATION",
            "2026-05-03T10:00:00Z", "2026-05-03T11:00:00Z",
        )
        add_wallet_participant(session["id"], member["id"], member["id"])
        item = create_rental_item("Recurve Bow 68", "BOW", 2500)
        agreement = create_rental_agreement(
            item["id"], member["id"], "2026-05-04", session_id=session["id"]
        )
        return member, session, item, agreement

    def test_third_strike_suspends_and_cancels_future_sessions(self, api):
        """PRD §3.1: "The strike that brings the count to exactly three — that
        is, the member stood at two strikes before it — auto-suspends the
        member: `status` flips from `ACTIVE` to `SUSPENDED`, and a three-hop
        cascade fires. First, every range session created by this member that is
        still `BOOKED` and whose `start_at` lies in the future transitions to
        `CANCELLED` as a system cancel, which always refunds in full."
        PRD §3.1: "Every participant of each system-cancelled session is
        refunded in full — wallet credit, punch restore, or both — and the
        session's `payment_status` becomes `REFUNDED` whenever any refund
        occurred."

        Design: Difficulty/transitive_cascade/member_suspension_three_hop_cascade
        """
        member, session, item, agreement = self._setup_suspension_scenario(api)
        assert get_member(member["id"])["wallet_balance_cents"] == 7840

        suspend_member_with_strikes(member["id"], 3)
        suspended = get_member(member["id"])
        assert suspended["status"] == "SUSPENDED"
        assert suspended["safety_strikes"] == 3

        cancelled = get_session(session["id"])
        assert cancelled["session_status"] == "CANCELLED"
        assert cancelled["payment_status"] == "REFUNDED"
        assert cancelled["cancellation_refund_cents"] == 2160, (
            "system cancel always refunds in full"
        )

    def test_suspension_cascade_voids_rental_and_releases_item(self, api):
        """PRD §3.1: "Second, each such cancellation voids that session's
        rental agreements still `OPEN`, moving them to `VOIDED`. Third, each
        voided agreement releases its rental item back to `AVAILABLE`."
        PRD §3.1: "Every participant of each system-cancelled session is
        refunded in full — wallet credit, punch restore, or both".

        Design: Difficulty/transitive_cascade/member_suspension_three_hop_cascade
        """
        member, session, item, agreement = self._setup_suspension_scenario(api)
        suspend_member_with_strikes(member["id"], 3)

        assert get_rental_agreement(agreement["id"])["status"] == "VOIDED"
        assert get_rental_item_via_list(item["id"])["status"] == "AVAILABLE"
        # 7840 after quoted debit + 2160 full system refund -> back to 10000.
        assert get_member(member["id"])["wallet_balance_cents"] == 10000


class TestValidationPriorityPairs:
    def test_state_beats_fiscal_on_suspended_punch_purchase(self, api):
        """PRD §2.8: "A consequence worth internalizing: a request that is both
        in the wrong state and short of funds always surfaces the state error,
        never the funds error."
        PRD §3.1: "Conversely, any purchase, booking, or entry attempted by a
        member whose `status` is not `ACTIVE` is rejected with
        `ERR_MEMBER_SUSPENDED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_suspended_punch_purchase
        """
        set_clock("2026-05-01T08:00:00Z")
        member = register_member("broke@x.com", full_name="Broke Archer")
        suspend_member_with_strikes(member["id"], 3)

        # Suspended AND wallet 0 < 5000 price: the state error must surface.
        resp = api.purchase_punch_card(
            member["id"], purchase_punch_card_payload(5),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED)

    def test_suspended_punch_purchase_creates_no_card(self, api):
        """PRD §3.1: "Conversely, any purchase, booking, or entry attempted by
        a member whose `status` is not `ACTIVE` is rejected with
        `ERR_MEMBER_SUSPENDED`."
        PRD §2.8: "Only after the request is well-formed do state-machine
        preconditions fire (the specific state error of the target transition,
        such as `ERR_SESSION_NOT_BOOKED`), followed by the waiver-and-consent
        gate ... and finally funds (`ERR_INSUFFICIENT_FUNDS`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_suspended_punch_purchase
        """
        set_clock("2026-05-01T08:00:00Z")
        member = register_member("broke@x.com", full_name="Broke Archer")
        suspend_member_with_strikes(member["id"], 3)

        resp = api.purchase_punch_card(
            member["id"], purchase_punch_card_payload(5),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED)
        cards = validate_success(
            api.list_punch_cards(member["id"], RANGE_OFFICER), 200
        )
        assert cards == [], "rejected purchase must not persist a card"

    def _setup_expired_waiver_and_overlap(self, api):
        """Member m whose waiver lapses before booking time; member w holding
        a BOOKED session on the lane at the target window."""
        set_clock("2025-05-01T00:00:00Z")
        m = register_member("exp@x.com", full_name="Expired Waiver")
        sign_waiver(m["id"])  # valid_until 2026-05-01
        set_clock("2026-05-01T00:00:00Z")
        w = register_member("ok@x.com", full_name="Okay Waiver",
                            date_of_birth="1991-01-01")
        sign_waiver(w["id"])
        lane = create_lane("HL")
        book_session(
            w["id"], lane["id"], "RESERVATION",
            "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z",
        )
        # Sweep flips m's waiver to EXPIRED (2026-05-02 > valid_until).
        set_clock("2026-05-02T08:00:00Z")
        return m, lane

    def test_safety_beats_constraint_on_booking(self, api):
        """PRD §2.8: "Only after the request is well-formed do state-machine
        preconditions fire (the specific state error of the target transition,
        such as `ERR_SESSION_NOT_BOOKED`), followed by the waiver-and-consent
        gate (`ERR_WAIVER_MISSING`, `ERR_WAIVER_EXPIRED`,
        `ERR_MINOR_GUARDIAN_REQUIRED`, `ERR_GUARDIAN_NOT_ADULT`), then
        resource-constraint checks (`ERR_LANE_OVERLAP`, ...)".
        PRD §2.9: "if the member's latest waiver is `EXPIRED` or `REVOKED` the
        rejection is `ERR_WAIVER_EXPIRED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_booking
        """
        m, lane = self._setup_expired_waiver_and_overlap(api)
        # Violates both the expired-waiver gate and lane overlap: the
        # waiver-and-consent gate fires first.
        resp = api.create_range_session(
            create_range_session_payload(
                lane["id"], "RESERVATION",
                "2026-05-02T10:30:00Z", "2026-05-02T11:30:00Z",
            ),
            make_member_headers(m["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WAIVER_EXPIRED)

    def test_expired_waiver_booking_creates_no_session(self, api):
        """PRD §2.9: "if the member's latest waiver is `EXPIRED` or `REVOKED`
        the rejection is `ERR_WAIVER_EXPIRED` (HTTP 422)."
        PRD §2.5: "Second, every waiver in `ACTIVE` whose `valid_until` date is
        strictly before the new current date transitions to `EXPIRED`; a waiver
        remains valid through its `valid_until` date inclusive, so expiry only
        bites on the following day."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_booking
        """
        m, lane = self._setup_expired_waiver_and_overlap(api)
        resp = api.create_range_session(
            create_range_session_payload(
                lane["id"], "RESERVATION",
                "2026-05-02T10:30:00Z", "2026-05-02T11:30:00Z",
            ),
            make_member_headers(m["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WAIVER_EXPIRED)
        sessions = validate_success(
            api.list_lane_sessions(lane["id"], RANGE_OFFICER), 200
        )
        assert len(sessions) == 1, "rejected booking must not persist"


class TestCheckinGatedByParticipantWaiver:
    def _setup_expired_waiver_session(self, api):
        """Member booked while waiver ACTIVE; the clock sweep lapses the waiver
        before the check-in window."""
        set_clock("2025-05-01T00:00:00Z")
        member = register_member("gate@x.com", full_name="Gate Archer")
        sign_waiver(member["id"])  # valid_until 2026-05-01
        fund_wallet(member["id"], 10000)
        lane = create_lane("GL")
        session = book_session(
            member["id"], lane["id"], "RESERVATION",
            "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z",
        )
        participant = add_wallet_participant(
            session["id"], member["id"], member["id"]
        )
        # 2026-05-02 > valid_until 2026-05-01 -> EXPIRED; 10:00 is in-window.
        set_clock("2026-05-02T10:00:00Z")
        return member, session, participant

    def test_checkin_rejected_when_participant_waiver_expired(self, api):
        """PRD §3.3: "— a cross-entity gate — **every** `ACTIVE` participant
        must belong to a member whose `status` is `ACTIVE` and who holds an
        `ACTIVE` waiver (`ERR_MEMBER_SUSPENDED`, `ERR_WAIVER_MISSING`, or
        `ERR_WAIVER_EXPIRED` as applicable)."

        Design: Difficulty/cross_entity_state_dependency/checkin_gated_by_participant_waiver_state
        """
        member, session, participant = self._setup_expired_waiver_session(api)
        resp = api.check_in_session(session["id"], RANGE_OFFICER)
        validate_error(resp, ApiErrorId.ERR_WAIVER_EXPIRED)
        assert get_session(session["id"])["session_status"] == "BOOKED"

    def test_failed_checkin_leaves_quoted_debit_standing(self, api):
        """PRD §3.3: "A wallet payment debits `quoted_fee_cents` from the
        archer's `wallet_balance_cents` (`ERR_INSUFFICIENT_FUNDS` if short)".
        PRD §3.3: "— a cross-entity gate — **every** `ACTIVE` participant must
        belong to a member whose `status` is `ACTIVE` and who holds an `ACTIVE`
        waiver (`ERR_MEMBER_SUSPENDED`, `ERR_WAIVER_MISSING`, or
        `ERR_WAIVER_EXPIRED` as applicable)."

        Design: Difficulty/cross_entity_state_dependency/checkin_gated_by_participant_waiver_state
        """
        member, session, participant = self._setup_expired_waiver_session(api)
        # BASIC member, 60 off-peak booked minutes: quoted 2400.
        assert participant["quoted_fee_cents"] == 2400
        wallet_before = get_member(member["id"])["wallet_balance_cents"]
        assert wallet_before == 7600

        resp = api.check_in_session(session["id"], RANGE_OFFICER)
        validate_error(resp, ApiErrorId.ERR_WAIVER_EXPIRED)
        assert get_member(member["id"])["wallet_balance_cents"] == wallet_before, (
            "a rejected check-in issues no refund"
        )


class TestSafetyStrikeRbac:
    def test_member_cannot_record_safety_strikes(self, api):
        """PRD §2.1: "`RangeOfficer` runs the range floor — check-in, close,
        safety strikes, reinstatement, rental returns and settlements".
        PRD §2.1: "A role attempting an operation outside its grant is rejected
        with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/member_cannot_record_safety_strikes
        """
        set_clock("2026-05-01T08:00:00Z")
        member = register_member("rbac1@x.com", full_name="Rbac One")

        resp = api.add_safety_strike(
            member["id"], {"reason": "self report"},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert get_member(member["id"])["safety_strikes"] == 0
