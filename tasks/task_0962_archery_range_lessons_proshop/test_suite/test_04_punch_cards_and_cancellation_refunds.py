"""Punch card lifecycle and the cancellation refund tiers."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_punch_participant,
    add_wallet_participant,
    api_client,
    assert_punch_card_invariants,
    book_session,
    create_lane,
    fund_wallet,
    get_member,
    get_punch_card,
    get_session,
    list_participants_for_session,
    make_member_headers,
    purchase_punch_card,
    purchase_punch_card_payload,
    register_member,
    register_ready_member,
    set_clock,
    sign_waiver,
    validate_error,
    validate_success,
)

RANGE_OFFICER = TEST_USERS["range_officer_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestPunchExhaustionBoundary:
    def _setup_card_and_session(self, api):
        """Owner with a 5-punch card; RESERVED session; six waivered guests.
        Returns (owner, card, session, guest_ids)."""
        set_clock("2026-05-01T08:00:00Z")
        owner = register_ready_member("host@x.com", wallet_cents=10000)
        card = purchase_punch_card(owner["id"], 5)
        lane = create_lane("BL", max_archers=8)
        session = book_session(
            owner["id"], lane["id"], "RESERVATION",
            "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z",
        )
        guests = []
        for i in range(1, 7):
            guest = register_member(f"g{i}@x.com", full_name=f"Guest {i}")
            sign_waiver(guest["id"])
            guests.append(guest["id"])
        return owner, card, session, guests

    def test_fifth_punch_flips_card_to_exhausted_at_exact_equality(self, api):
        """PRD §3.5: "The card exhausts at the exact boundary — when a consume
        makes `punches_used` equal to `punches_total`, the card flips from
        `ACTIVE` to its terminal `EXHAUSTED`."
        PRD §3.3: "A punch card used for payment must exist, belong to the
        session's creator (creators may pay for their guests), be `ACTIVE`, and
        have at least one punch remaining".

        Design: Difficulty/boundary_precision_check/punch_exhaustion_at_exact_last_punch
        """
        owner, card, session, guests = self._setup_card_and_session(api)
        for guest_id in guests[:5]:
            add_punch_participant(session["id"], guest_id, card["id"], owner["id"])

        after = get_punch_card(card["id"])
        assert after["punches_used"] == 5
        assert after["punches_total"] == 5
        assert after["status"] == "EXHAUSTED", (
            "exact-equality consume (used == total) is the legal boundary"
        )
        assert_punch_card_invariants(after)

    def test_sixth_punch_rejected_and_wallet_untouched(self, api):
        """PRD §3.3: "A punch card used for payment must exist, belong to the
        session's creator (creators may pay for their guests), be `ACTIVE`, and
        have at least one punch remaining; any of these failing is
        `ERR_PUNCH_CARD_EXHAUSTED`."
        PRD §3.3: "For punch-paid participants both fee figures are recorded for
        reporting, with no wallet movement."

        Design: Difficulty/boundary_precision_check/punch_exhaustion_at_exact_last_punch
        """
        owner, card, session, guests = self._setup_card_and_session(api)
        for guest_id in guests[:5]:
            add_punch_participant(session["id"], guest_id, card["id"], owner["id"])

        resp = api.add_participant(
            session["id"],
            {"member_id": guests[5], "payment_method": "PUNCH_CARD",
             "punch_card_id": card["id"]},
            make_member_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PUNCH_CARD_EXHAUSTED)
        after = get_punch_card(card["id"])
        assert after["punches_used"] == 5, "rejected consume must not mutate"
        # Punch payments never touch the wallet: 10000 - 5000 purchase only.
        assert get_member(owner["id"])["wallet_balance_cents"] == 5000


class TestCancellationRefundBoundary:
    def _setup_two_sessions(self, api):
        """PLUS member with two identical RESERVED sessions on two lanes,
        each self-participated at quoted 2160. Clock ends at
        2026-05-01T10:00:00Z (exactly 24h before start)."""
        set_clock("2026-05-01T08:00:00Z")
        member = register_ready_member("cxl@x.com", tier="PLUS",
                                       wallet_cents=10000)
        lane1 = create_lane("RL1")
        lane2 = create_lane("RL2")
        session_a = book_session(
            member["id"], lane1["id"], "RESERVATION",
            "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z",
        )
        add_wallet_participant(session_a["id"], member["id"], member["id"])
        session_b = book_session(
            member["id"], lane2["id"], "RESERVATION",
            "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z",
        )
        add_wallet_participant(session_b["id"], member["id"], member["id"])
        set_clock("2026-05-01T10:00:00Z")
        return member, session_a, session_b

    def test_notice_exactly_24h_refunds_full(self, api):
        """PRD §3.4: "Notice of at least 24 hours refunds 100% of each `ACTIVE`
        participant's quoted fees; notice of at least 4 hours but under 24 hours
        refunds 50%, rounded half up per participant; notice under 4 hours
        refunds nothing. The boundaries are inclusive upward: exactly 24 hours
        is a full refund, exactly 4 hours is the 50% tier."

        Design: Difficulty/boundary_precision_check/cancellation_refund_24h_exact_boundary
        """
        member, session_a, _ = self._setup_two_sessions(api)
        # Clock 2026-05-01T10:00 -> notice to 2026-05-02T10:00 is exactly 24h.
        cancelled = validate_success(
            api.cancel_session(session_a["id"], make_member_headers(member["id"])),
            200,
        )
        assert cancelled["cancellation_refund_cents"] == 2160
        assert cancelled["session_status"] == "CANCELLED"
        assert cancelled["payment_status"] == "REFUNDED"

    def test_notice_23h59m_refunds_half(self, api):
        """PRD §3.4: "Notice of at least 24 hours refunds 100% of each `ACTIVE`
        participant's quoted fees; notice of at least 4 hours but under 24 hours
        refunds 50%, rounded half up per participant; notice under 4 hours
        refunds nothing. The boundaries are inclusive upward: exactly 24 hours
        is a full refund, exactly 4 hours is the 50% tier."

        Design: Difficulty/boundary_precision_check/cancellation_refund_24h_exact_boundary
        """
        member, session_a, session_b = self._setup_two_sessions(api)
        validate_success(
            api.cancel_session(session_a["id"], make_member_headers(member["id"])),
            200,
        )
        set_clock("2026-05-01T10:01:00Z")
        # 23h59m of notice: just under the full-refund boundary.
        cancelled_b = validate_success(
            api.cancel_session(session_b["id"], make_member_headers(member["id"])),
            200,
        )
        assert cancelled_b["cancellation_refund_cents"] == 1080, (
            "round_half_up(2160 x 0.5)"
        )
        assert cancelled_b["payment_status"] == "REFUNDED"
        # 5680 after two quoted debits + 2160 full refund + 1080 half refund.
        assert get_member(member["id"])["wallet_balance_cents"] == 8920


class TestPunchConsumeAndCancelRestoreInvariant:
    def _setup_punch_session(self, api):
        set_clock("2026-05-01T08:00:00Z")
        owner = register_ready_member("host2@x.com", wallet_cents=10000)
        card = purchase_punch_card(owner["id"], 5)
        guest = register_member("gst@x.com", full_name="Guest Archer")
        sign_waiver(guest["id"])
        lane = create_lane("IL")
        session = book_session(
            owner["id"], lane["id"], "RESERVATION",
            "2026-05-03T10:00:00Z", "2026-05-03T11:00:00Z",
        )
        add_punch_participant(session["id"], guest["id"], card["id"], owner["id"])
        return owner, card, session

    def test_cancel_restores_punch_and_conserves_count(self, api):
        """PRD §3.4: "the punch is restored to the card (decrementing
        `punches_used`, and reactivating an `EXHAUSTED` card to `ACTIVE`) if and
        only if notice is at least 4 hours or the cancel is a system cancel;
        below four hours the punch is forfeited with no restore."
        PRD §3.5: "`punches_remaining` is always the pack size minus
        `punches_used`."

        Design: Difficulty/compensating_invariant/punch_consume_and_cancel_restore_invariant
        """
        owner, card, session = self._setup_punch_session(api)
        mid = get_punch_card(card["id"])
        assert mid["punches_used"] == 1
        assert_punch_card_invariants(mid)

        set_clock("2026-05-01T09:00:00Z")  # notice far above 24h
        validate_success(
            api.cancel_session(session["id"], make_member_headers(owner["id"])), 200
        )
        after = get_punch_card(card["id"])
        assert after["punches_used"] == 0, "consume + full-notice cancel restores"
        assert after["status"] == "ACTIVE"
        assert_punch_card_invariants(after)

    def test_cancel_marks_session_refunded_and_participant_refunded(self, api):
        """PRD §3.4: "A participant who receives any refund or punch restore
        transitions from `ACTIVE` to `REFUNDED`; one who forfeits — voluntary
        cancel under four hours' notice, or the no-show sweep — transitions to
        `FORFEITED`."

        Note: no `payment_status` assertion here — for a punch-only cancel the
        refunded amount is 0, and PRD §3.4 pins `REFUNDED` only to "whenever
        the refunded amount is greater than zero", so the zero-money branch is
        not uniquely determined by the PRD.

        Design: Difficulty/compensating_invariant/punch_consume_and_cancel_restore_invariant
        """
        owner, card, session = self._setup_punch_session(api)
        set_clock("2026-05-01T09:00:00Z")
        cancelled = validate_success(
            api.cancel_session(session["id"], make_member_headers(owner["id"])), 200
        )
        assert cancelled["session_status"] == "CANCELLED"
        participants = list_participants_for_session(session["id"])
        assert len(participants) == 1
        assert participants[0]["status"] == "REFUNDED"


class TestWalletChargeAndFullRefundInvariant:
    def _setup_wallet_session(self, api):
        set_clock("2026-05-01T08:00:00Z")
        member = register_ready_member("inv@x.com", tier="PLUS",
                                       wallet_cents=10000)
        lane = create_lane("WL")
        session = book_session(
            member["id"], lane["id"], "RESERVATION",
            "2026-05-03T10:00:00Z", "2026-05-03T11:00:00Z",
        )
        add_wallet_participant(session["id"], member["id"], member["id"])
        return member, session

    def test_full_refund_restores_exact_prepair_wallet(self, api):
        """PRD §3.4: "Notice of at least 24 hours refunds 100% of each `ACTIVE`
        participant's quoted fees".
        PRD §3.1: "The prepaid wallet, `wallet_balance_cents`, is the single
        funding source for lane fees, punch-card purchases, lesson fees, league
        entries, rental settlements, and repair pickups; it is mutated only by
        charges, refunds, and admin adjustments."

        Design: Difficulty/compensating_invariant/wallet_charge_and_full_refund_invariant
        """
        member, session = self._setup_wallet_session(api)
        assert get_member(member["id"])["wallet_balance_cents"] == 7840, (
            "quoted debit 2160 applied"
        )
        set_clock("2026-05-01T09:00:00Z")  # notice > 24h
        cancelled = validate_success(
            api.cancel_session(session["id"], make_member_headers(member["id"])), 200
        )
        assert cancelled["cancellation_refund_cents"] == 2160
        assert get_member(member["id"])["wallet_balance_cents"] == 10000, (
            "charge + full-refund pair leaves zero drift"
        )

    def test_full_refund_marks_session_cancelled_and_refunded(self, api):
        """PRD §3.4: "The cancellation records the total in
        `cancellation_refund_cents`, and `payment_status` becomes `REFUNDED`
        whenever the refunded amount is greater than zero."

        Design: Difficulty/compensating_invariant/wallet_charge_and_full_refund_invariant
        """
        member, session = self._setup_wallet_session(api)
        set_clock("2026-05-01T09:00:00Z")
        cancelled = validate_success(
            api.cancel_session(session["id"], make_member_headers(member["id"])), 200
        )
        assert cancelled["session_status"] == "CANCELLED"
        assert cancelled["payment_status"] == "REFUNDED"
        assert cancelled["cancellation_refund_cents"] == 2160


class TestPunchCardShapeAndLookup:
    def test_punch_card_invalid_pack_size_rejected(self, api):
        """PRD §3.5: "naming a `punches_total` of exactly 5 or exactly 10 (any
        other pack size is `ERR_INVALID_REQUEST`)".

        Design: Corner/entities/punch_card_invalid_pack_size_rejected
        """
        set_clock("2026-05-01T08:00:00Z")
        member = register_member("pack@x.com", full_name="Pack Buyer")
        fund_wallet(member["id"], 10000)

        resp = api.purchase_punch_card(
            member["id"], purchase_punch_card_payload(7),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert get_member(member["id"])["wallet_balance_cents"] == 10000
        cards = validate_success(
            api.list_punch_cards(member["id"], RANGE_OFFICER), 200
        )
        assert cards == [], "no card may be created for an invalid pack size"

    def test_punch_card_not_found_returns_404(self, api):
        """PRD §2.10: "the leftmost segment that does not resolve determines the
        not-found error — ... `ERR_PUNCH_CARD_NOT_FOUND`, ... each HTTP 404."

        Design: Corner/errors/punch_card_not_found_returns_404
        """
        resp = api.get_punch_card(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", RANGE_OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_PUNCH_CARD_NOT_FOUND)
