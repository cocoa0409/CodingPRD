"""Difficulty queue: resource temporal overlap — half-open seat terms, closed offer windows."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    appoint_seat,
    appoint_seat_payload,
    create_board_seat,
    create_buy_in_offer,
    create_buy_in_offer_payload,
    create_physician,
    create_policy,
    create_shareholder,
    get_board_seat,
    get_buy_in_offer,
    make_physician_headers,
    respond_offer,
    set_clock,
    validate_error,
    validate_success,
)


class TestBoardSeatHalfOpenTermSuccession:
    def test_overlap_rejected_adjacency_allowed_one_successor(self, api):
        """PRD §3.3: "Terms are half-open intervals: the holder serves from
        `current_term_start` inclusive to `current_term_end` exclusive."
        PRD §3.3: "Two additional rules govern succession: only one successor may be
        booked at a time (`ERR_SUCCESSOR_ALREADY_BOOKED`), and the successor's window
        must not overlap the current term — `next_term_start` must be at or after
        `current_term_end`, so adjacency is allowed but true overlap is rejected with
        `ERR_SEAT_TERM_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/board_seat_half_open_term_succession
        """
        create_policy(total_shares_authorized=1000000)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        b = create_shareholder("Dr B", 1000, "2016-01-01T00:00:00Z")
        c = create_shareholder("Dr C", 1000, "2017-01-01T00:00:00Z")
        seat = create_board_seat("SEAT-9", "AT_LARGE")
        appoint_seat(seat["id"], a["id"], "2026-08-01T00:00:00Z", "2029-08-01T00:00:00Z")

        resp = api_client.appoint_board_seat(
            seat["id"],
            appoint_seat_payload(b["id"], term_start="2029-01-01T00:00:00Z",
                                 term_end="2032-01-01T00:00:00Z"),
            TEST_USERS["board_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SEAT_TERM_OVERLAP)

        booked = appoint_seat(
            seat["id"], b["id"], "2029-08-01T00:00:00Z", "2032-08-01T00:00:00Z"
        )
        assert booked["next_holder_physician_id"] == b["id"], (
            "adjacency (start == current_term_end) must be allowed"
        )

        resp = api_client.appoint_board_seat(
            seat["id"],
            appoint_seat_payload(c["id"], term_start="2032-08-01T00:00:00Z",
                                 term_end="2035-08-01T00:00:00Z"),
            TEST_USERS["board_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SUCCESSOR_ALREADY_BOOKED)

    def test_sweep_at_term_end_promotes_successor(self, api):
        """PRD §3.3: "The clock sweep at a term's end promotes the booked successor to
        current holder and clears the successor fields; with no successor booked, the
        seat falls `VACANT` and the current holder is cleared."

        Design: Difficulty/resource_temporal_overlap/board_seat_half_open_term_succession
        """
        create_policy(total_shares_authorized=1000000)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        b = create_shareholder("Dr B", 1000, "2016-01-01T00:00:00Z")
        seat = create_board_seat("SEAT-9", "AT_LARGE")
        appoint_seat(seat["id"], a["id"], "2026-08-01T00:00:00Z", "2029-08-01T00:00:00Z")
        appoint_seat(seat["id"], b["id"], "2029-08-01T00:00:00Z", "2032-08-01T00:00:00Z")

        set_clock("2029-08-01T00:00:00Z")
        seat_after = get_board_seat(seat["id"])
        assert seat_after["status"] == "FILLED"
        assert seat_after["current_holder_physician_id"] == b["id"]
        assert seat_after["current_term_start"].startswith("2029-08-01T00:00:00")
        assert seat_after["next_holder_physician_id"] is None, (
            "successor fields cleared on promotion"
        )


class TestBuyInOfferClosedAcceptanceWindow:
    def test_overlap_rejected_and_acceptance_at_deadline_succeeds(self, api):
        """PRD §3.2: "A physician may hold at most one offer whose acceptance window
        is still open — the window is a closed interval — so creating a second offer
        while an `OFFERED` offer's window remains open is rejected with
        `ERR_OFFER_WINDOW_OVERLAP`."
        PRD §3.2: "The `acceptance_deadline` is `offered_at` plus `offer_window_days`,
        and the interval is closed: acceptance is allowed at the deadline instant
        itself, and the clock sweep expires the offer only once the clock is strictly
        past the deadline."
        P hired 2024-01-01 offered at the 2026-08-01 default clock: tenure 2 ->
        round(10000000 * 0.96 * 11/12) = 8800000; deadline 2026-08-31.

        Design: Difficulty/resource_temporal_overlap/buy_in_offer_closed_acceptance_window
        """
        create_policy(total_shares_authorized=1000000)
        p = create_physician(full_name="Dr P", hire_date="2024-01-01T00:00:00Z")
        offer = create_buy_in_offer(p["id"], target_tier="PARTNER_TRACK",
                                    share_grant=0, installment_count=1)
        assert offer["final_amount_cents"] == 8800000
        assert offer["acceptance_deadline"].startswith("2026-08-31T00:00:00")

        resp = api_client.create_buy_in_offer(
            create_buy_in_offer_payload(p["id"]), TEST_USERS["board_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_WINDOW_OVERLAP)

        set_clock("2026-08-31T00:00:00Z")
        accepted = respond_offer(offer["id"], p, "ACCEPT")
        assert accepted["status"] == "ACCEPTED", (
            "acceptance AT the deadline instant must succeed (closed interval)"
        )

        resp = api_client.create_buy_in_offer(
            create_buy_in_offer_payload(p["id"]), TEST_USERS["board_admin_headers"]
        )
        validate_success(resp, 201)

    def test_offer_expires_strictly_after_deadline(self, api):
        """PRD §3.2: "Responding to an offer that is no longer `OFFERED` is rejected
        with `ERR_OFFER_NOT_OPEN` — and because the sweep expires offers atomically
        with the clock-set, a past-deadline offer is already `EXPIRED` by the time any
        response could arrive."

        Design: Difficulty/resource_temporal_overlap/buy_in_offer_closed_acceptance_window
        """
        create_policy(total_shares_authorized=1000000)
        q = create_physician(full_name="Dr Q", hire_date="2024-01-01T00:00:00Z")
        offer = create_buy_in_offer(q["id"], target_tier="PARTNER_TRACK",
                                    share_grant=0, installment_count=1)
        set_clock("2026-10-01T00:00:00Z")
        expired = get_buy_in_offer(offer["id"])
        assert expired["status"] == "EXPIRED", (
            "clock strictly past the 2026-08-31 deadline must expire the offer"
        )
        resp = api_client.respond_buy_in_offer(
            offer["id"], {"decision": "ACCEPT"}, make_physician_headers(q["id"])
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_OPEN)
