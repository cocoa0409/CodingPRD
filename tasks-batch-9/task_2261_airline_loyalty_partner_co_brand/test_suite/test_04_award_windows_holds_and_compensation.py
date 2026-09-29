"""Temporal window exclusion, compensating seat/liability restoration and the
ordering of the backdated-window check against the promotion overlap check.
"""
from test_helpers import (
    PROGRAM_ADMIN,
    REVENUE_ACCOUNTANT,
    assert_award_booking,
    assert_award_inventory_window,
    assert_mile_transaction,
    assert_promotion_campaign,
    award_inventory_window_payload,
    create_campaign,
    create_member,
    create_program,
    create_window,
    hold_seats,
    member_headers_for,
    post_transaction,
    promotion_campaign_payload,
    read_member,
    read_program,
    read_window,
    refund_booking,
    run_epoch,
    set_clock,
    ticket_booking,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------- #
# Half-open promotion windows: adjacency allowed, overlap refused, per channel
# --------------------------------------------------------------------------- #
def _program_with_september_flight_campaign():
    """A programme plus one SCHEDULED FLIGHT campaign over September 2026."""
    program = create_program(name="SkyMiles Windows", current_period="2026-08")
    incumbent = create_campaign(
        program["id"],
        code="FLIGHT-SEP",
        earn_channel="FLIGHT",
        multiplier_bps=15000,
        stacking_mode="ADDITIVE",
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-10-01T00:00:00Z",
    )
    return program, incumbent


class TestPromotionHalfOpenWindowOverlap:
    def test_campaign_starting_exactly_at_incumbent_window_end_is_adjacency(self, api):
        """PRD §3.4: "And the half-open window must not overlap that of any `SCHEDULED` or `LIVE` campaign sharing the same `program_id` and `earn_channel`; because the window is half-open, exact adjacency — one campaign's `window_end` equal to the next campaign's `window_start` — is explicitly allowed, while any genuine overlap raises `ERR_PROMOTION_WINDOW_OVERLAP`."
        PRD §3.4: "A campaign's `status` begins at `SCHEDULED`."
        PRD §3.4: "It is the epoch sweep, not the create call, that moves it `SCHEDULED → LIVE` once `window_start` is at or before the clock's now, and `LIVE → ENDED` once `window_end` is at or before now; only a `LIVE` campaign may be referenced as the `promotion_id` on an earning row."

        Design: Difficulty/resource_temporal_overlap/promotion_half_open_window_overlap_same_channel_adjacency_allowed
        """
        program, incumbent = _program_with_september_flight_campaign()

        resp = api.create_promotion_campaign(
            promotion_campaign_payload(
                program["id"],
                code="FLIGHT-OCT",
                earn_channel="FLIGHT",
                multiplier_bps=15000,
                stacking_mode="ADDITIVE",
                window_start="2026-10-01T00:00:00Z",
                window_end="2026-11-01T00:00:00Z",
            ),
            PROGRAM_ADMIN,
        )
        adjacent = validate_success(resp, expected_status=201)
        assert_promotion_campaign(adjacent)

        assert adjacent["window_start"].startswith("2026-10-01T00:00:00"), (
            "the adjacent campaign keeps the window_start it was created with, "
            f"got {adjacent['window_start']}"
        )
        assert adjacent["status"] == "SCHEDULED", (
            f"a freshly created campaign begins at SCHEDULED, got {adjacent['status']}"
        )

        incumbent_now = validate_success(
            api.get_promotion_campaign(incumbent["id"], PROGRAM_ADMIN)
        )
        assert incumbent_now["status"] == "SCHEDULED", (
            "the incumbent campaign remains SCHEDULED, got "
            f"{incumbent_now['status']}"
        )

    def test_campaign_starting_one_second_before_incumbent_end_overlaps(self, api):
        """PRD §3.4: "And the half-open window must not overlap that of any `SCHEDULED` or `LIVE` campaign sharing the same `program_id` and `earn_channel`; because the window is half-open, exact adjacency — one campaign's `window_end` equal to the next campaign's `window_start` — is explicitly allowed, while any genuine overlap raises `ERR_PROMOTION_WINDOW_OVERLAP`."
        PRD §2.9: "A new campaign's window does not overlap an existing `SCHEDULED` or `LIVE` campaign sharing the same `program_id` and `earn_channel` — otherwise `ERR_PROMOTION_WINDOW_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/promotion_half_open_window_overlap_same_channel_adjacency_allowed
        """
        program, _incumbent = _program_with_september_flight_campaign()

        resp = api.create_promotion_campaign(
            promotion_campaign_payload(
                program["id"],
                code="FLIGHT-CLASH",
                earn_channel="FLIGHT",
                multiplier_bps=12500,
                stacking_mode="ADDITIVE",
                window_start="2026-09-30T23:59:59Z",
                window_end="2026-10-15T00:00:00Z",
            ),
            PROGRAM_ADMIN,
        )
        validate_error(resp, "ERR_PROMOTION_WINDOW_OVERLAP", 409)

        listed, meta = validate_paginated(
            api.list_promotion_campaigns(
                PROGRAM_ADMIN, params={"program_id": program["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            "the refused campaign was not persisted, so only the incumbent remains; "
            f"got total_count {meta['total_count']}"
        )
        assert [row["code"] for row in listed] == ["FLIGHT-SEP"], (
            f"only FLIGHT-SEP survives, got {[row['code'] for row in listed]}"
        )

    def test_same_colliding_interval_is_accepted_on_a_different_earn_channel(self, api):
        """PRD §3.4: "And the half-open window must not overlap that of any `SCHEDULED` or `LIVE` campaign sharing the same `program_id` and `earn_channel`; because the window is half-open, exact adjacency — one campaign's `window_end` equal to the next campaign's `window_start` — is explicitly allowed, while any genuine overlap raises `ERR_PROMOTION_WINDOW_OVERLAP`."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` counts the rows matching the filters before pagination is applied and `has_more` states whether any matching row remains beyond the current page."
        PRD §2.3: "Promotion campaigns filter by `program_id`, `earn_channel` and `status`."

        Design: Difficulty/resource_temporal_overlap/promotion_half_open_window_overlap_same_channel_adjacency_allowed
        """
        program, _incumbent = _program_with_september_flight_campaign()

        adjacent = validate_success(
            api.create_promotion_campaign(
                promotion_campaign_payload(
                    program["id"],
                    code="FLIGHT-OCT",
                    earn_channel="FLIGHT",
                    multiplier_bps=15000,
                    stacking_mode="ADDITIVE",
                    window_start="2026-10-01T00:00:00Z",
                    window_end="2026-11-01T00:00:00Z",
                ),
                PROGRAM_ADMIN,
            ),
            expected_status=201,
        )

        # The interval that collided on FLIGHT is legitimate on CARD_SPEND.
        other_channel = validate_success(
            api.create_promotion_campaign(
                promotion_campaign_payload(
                    program["id"],
                    code="CARD-CLASH-OK",
                    earn_channel="CARD_SPEND",
                    multiplier_bps=12500,
                    stacking_mode="ADDITIVE",
                    window_start="2026-09-30T23:59:59Z",
                    window_end="2026-10-15T00:00:00Z",
                ),
                PROGRAM_ADMIN,
            ),
            expected_status=201,
        )
        assert_promotion_campaign(other_channel)
        assert other_channel["earn_channel"] == "CARD_SPEND", (
            "the accepted campaign sits on the CARD_SPEND channel, got "
            f"{other_channel['earn_channel']}"
        )
        assert other_channel["status"] == "SCHEDULED", (
            f"a freshly created campaign begins at SCHEDULED, got {other_channel['status']}"
        )

        _all_rows, all_meta = validate_paginated(
            api.list_promotion_campaigns(
                PROGRAM_ADMIN, params={"program_id": program["id"]}
            )
        )
        assert all_meta["total_count"] == 3, (
            "three campaigns were accepted for this programme, got total_count "
            f"{all_meta['total_count']}"
        )

        flight_rows, flight_meta = validate_paginated(
            api.list_promotion_campaigns(
                PROGRAM_ADMIN,
                params={"program_id": program["id"], "earn_channel": "FLIGHT"},
            )
        )
        assert flight_meta["total_count"] == 2, (
            "only the two FLIGHT campaigns match the earn_channel filter, got "
            f"total_count {flight_meta['total_count']}"
        )
        assert adjacent["id"] in {row["id"] for row in flight_rows}, (
            "the adjacent FLIGHT campaign appears under the earn_channel filter"
        )


# --------------------------------------------------------------------------- #
# Closed award-window intervals with a two clear day buffer per route and cabin
# --------------------------------------------------------------------------- #
def _program_with_september_business_window():
    """A programme plus one JFK-LHR BUSINESS window over 2026-09-01..2026-09-30."""
    program = create_program(name="SkyMiles Buffer", current_period="2026-08")
    window = create_window(
        program["id"],
        route_code="JFK-LHR",
        cabin="BUSINESS",
        window_start_date="2026-09-01",
        window_end_date="2026-09-30",
        authorized_seats=10,
    )
    return program, window


class TestAwardWindowTwoDayBuffer:
    def test_one_clear_day_after_the_incumbent_violates_the_buffer(self, api):
        """PRD §3.5: "Beyond correct interval ordering and the no-opening-in-the-past rule, a new window must leave at least two clear days between its closed interval and that of every existing window sharing the same `program_id`, `route_code` and `cabin`; an overlap or an insufficient gap raises `ERR_AWARD_WINDOW_BUFFER_VIOLATION`."
        PRD §2.9: "A new award inventory window leaves at least two clear days between its closed date interval and that of every existing window sharing the same `program_id`, `route_code` and `cabin` — otherwise `ERR_AWARD_WINDOW_BUFFER_VIOLATION` (409)."

        Design: Difficulty/resource_temporal_overlap/award_window_closed_interval_two_day_buffer_same_route_cabin
        """
        program, incumbent = _program_with_september_business_window()

        # 2026-10-01 is the only clear day between 2026-09-30 and 2026-10-02.
        resp = api.create_award_inventory_window(
            award_inventory_window_payload(
                program["id"],
                route_code="JFK-LHR",
                cabin="BUSINESS",
                window_start_date="2026-10-02",
                window_end_date="2026-10-31",
                authorized_seats=10,
            ),
            PROGRAM_ADMIN,
        )
        validate_error(resp, "ERR_AWARD_WINDOW_BUFFER_VIOLATION", 409)

        _rows, meta = validate_paginated(
            api.list_award_inventory_windows(
                PROGRAM_ADMIN, params={"program_id": program["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            "the refused window was not persisted, so only the incumbent remains; "
            f"got total_count {meta['total_count']}"
        )

        incumbent_now = read_window(incumbent["id"])
        assert incumbent_now["capacity_control_state"] == "OPEN", (
            "the untouched incumbent window stays OPEN, got "
            f"{incumbent_now['capacity_control_state']}"
        )

    def test_two_clear_days_after_the_incumbent_is_accepted(self, api):
        """PRD §3.5: "Beyond correct interval ordering and the no-opening-in-the-past rule, a new window must leave at least two clear days between its closed interval and that of every existing window sharing the same `program_id`, `route_code` and `cabin`; an overlap or an insufficient gap raises `ERR_AWARD_WINDOW_BUFFER_VIOLATION`."
        PRD §3.5: "A fresh window starts with `seats_held`, `seats_confirmed` and `saver_seats_consumed` at zero, `load_factor_bps` at zero, `capacity_control_state` at `OPEN`, and `demand_multiplier_bps` seeded at 9000 — the rung an empty window occupies on the demand ladder."

        Design: Difficulty/resource_temporal_overlap/award_window_closed_interval_two_day_buffer_same_route_cabin
        """
        program, _incumbent = _program_with_september_business_window()

        # 2026-10-01 and 2026-10-02 are two clear days after the 2026-09-30 end.
        resp = api.create_award_inventory_window(
            award_inventory_window_payload(
                program["id"],
                route_code="JFK-LHR",
                cabin="BUSINESS",
                window_start_date="2026-10-03",
                window_end_date="2026-10-31",
                authorized_seats=10,
            ),
            PROGRAM_ADMIN,
        )
        buffered = validate_success(resp, expected_status=201)
        assert_award_inventory_window(buffered)

        assert buffered["window_start_date"] == "2026-10-03", (
            "the accepted window keeps its requested start date, got "
            f"{buffered['window_start_date']}"
        )
        assert buffered["seats_held"] == 0, (
            f"a fresh window starts with seats_held 0, got {buffered['seats_held']}"
        )
        assert buffered["seats_confirmed"] == 0, (
            "a fresh window starts with seats_confirmed 0, got "
            f"{buffered['seats_confirmed']}"
        )
        assert buffered["load_factor_bps"] == 0, (
            "a fresh window starts with load_factor_bps 0, got "
            f"{buffered['load_factor_bps']}"
        )
        assert buffered["capacity_control_state"] == "OPEN", (
            "a fresh window starts OPEN, got "
            f"{buffered['capacity_control_state']}"
        )
        assert buffered["demand_multiplier_bps"] == 9000, (
            "a fresh window seeds demand_multiplier_bps at 9000, got "
            f"{buffered['demand_multiplier_bps']}"
        )

    def test_buffer_is_scoped_per_route_code_and_cabin(self, api):
        """PRD §3.5: "Beyond correct interval ordering and the no-opening-in-the-past rule, a new window must leave at least two clear days between its closed interval and that of every existing window sharing the same `program_id`, `route_code` and `cabin`; an overlap or an insufficient gap raises `ERR_AWARD_WINDOW_BUFFER_VIOLATION`."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` counts the rows matching the filters before pagination is applied and `has_more` states whether any matching row remains beyond the current page."
        PRD §2.3: "Award inventory windows filter by `program_id`, `route_code`, `cabin` and `capacity_control_state`."

        Design: Difficulty/resource_temporal_overlap/award_window_closed_interval_two_day_buffer_same_route_cabin
        """
        program, _incumbent = _program_with_september_business_window()

        buffered = validate_success(
            api.create_award_inventory_window(
                award_inventory_window_payload(
                    program["id"],
                    route_code="JFK-LHR",
                    cabin="BUSINESS",
                    window_start_date="2026-10-03",
                    window_end_date="2026-10-31",
                    authorized_seats=10,
                ),
                PROGRAM_ADMIN,
            ),
            expected_status=201,
        )

        # Dates identical to the incumbent's, but on another cabin.
        other_cabin = validate_success(
            api.create_award_inventory_window(
                award_inventory_window_payload(
                    program["id"],
                    route_code="JFK-LHR",
                    cabin="ECONOMY",
                    window_start_date="2026-09-01",
                    window_end_date="2026-09-30",
                    authorized_seats=40,
                ),
                PROGRAM_ADMIN,
            ),
            expected_status=201,
        )
        assert_award_inventory_window(other_cabin)
        assert other_cabin["cabin"] == "ECONOMY", (
            f"the accepted window sits on the ECONOMY cabin, got {other_cabin['cabin']}"
        )
        assert other_cabin["window_start_date"] == "2026-09-01", (
            "the ECONOMY window carries the incumbent's own dates, got "
            f"{other_cabin['window_start_date']}"
        )

        _all_rows, all_meta = validate_paginated(
            api.list_award_inventory_windows(
                PROGRAM_ADMIN, params={"program_id": program["id"]}
            )
        )
        assert all_meta["total_count"] == 3, (
            "three windows were accepted for this programme, got total_count "
            f"{all_meta['total_count']}"
        )

        business_rows, business_meta = validate_paginated(
            api.list_award_inventory_windows(
                PROGRAM_ADMIN,
                params={"program_id": program["id"], "cabin": "BUSINESS"},
            )
        )
        assert business_meta["total_count"] == 2, (
            "only the two BUSINESS windows match the cabin filter, got total_count "
            f"{business_meta['total_count']}"
        )
        assert buffered["id"] in {row["id"] for row in business_rows}, (
            "the buffered October window appears under the BUSINESS cabin filter"
        )


# --------------------------------------------------------------------------- #
# Refunding a ticketed booking restores balance, liability and seats
# --------------------------------------------------------------------------- #
def _ticketed_saver_booking(seats=1, travel_date="2026-09-10"):
    """Programme, member funded with 100000 miles, window, and a ticketed hold."""
    program = create_program(name="SkyMiles Refund", current_period="2026-08")
    member = create_member(
        program["id"], external_member_ref="MBR-REFUND", home_region="AMER"
    )
    post_transaction(
        member["id"],
        "CARD_SPEND_EARN",
        "2026-07-02",
        headers=REVENUE_ACCOUNTANT,
        qualifying_spend_cents=10000000,
    )
    window = create_window(
        program["id"],
        route_code="JFK-LHR",
        cabin="BUSINESS",
        window_start_date="2026-09-01",
        window_end_date="2026-09-30",
        authorized_seats=10,
        saver_seat_share_bps=3000,
    )
    booking = hold_seats(
        member["id"],
        window["id"],
        window["version"],
        headers=member_headers_for(member["id"]),
        travel_date=travel_date,
        seats=seats,
        fare_class="SAVER",
    )
    ticket_booking(booking["id"], headers=member_headers_for(member["id"]))
    return program, member, window, booking


class TestBookingRefundRestoresLiability:
    def test_hold_price_is_frozen_at_the_pre_booking_demand_rung(self):
        """PRD §3.5: "That pre-booking load factor selects `demand_multiplier_bps_applied` from a four-rung ladder whose lower bounds are inclusive: 9000 basis points below 5000, 10000 from 5000 through 7499, 12500 from 7500 through 8999, and 16000 at 9000 and above."
        PRD §3.5: "The gross award miles per seat are `chart_miles_per_seat` multiplied by `demand_multiplier_bps_applied` and by `partner_uplift_bps_applied`, divided by 100000000 (that is, both basis-point factors converted to plain multipliers), rounded half up."
        PRD §3.5: "The band also fixes the cash side: `cash_surcharge_cents` is 560 cents per seat at `SURCHARGE_LOW`, 1120 at `SURCHARGE_MID` and 2240 at `SURCHARGE_HIGH`, multiplied by `seats`."
        PRD §3.5: "A `BASE` member receives no discount in any band."

        Design: Difficulty/compensating_invariant/booking_refund_restores_outstanding_mile_liability
        """
        _program, _member, _window, booking = _ticketed_saver_booking()
        assert_award_booking(booking)

        assert booking["demand_multiplier_bps_applied"] == 9000, (
            "an empty window prices at the 9000 basis point rung, got "
            f"{booking['demand_multiplier_bps_applied']}"
        )
        assert booking["chart_miles_per_seat"] == 50000, (
            "BUSINESS at SAVER charges 50000 chart miles, got "
            f"{booking['chart_miles_per_seat']}"
        )
        assert booking["partner_uplift_bps_applied"] == 10000, (
            "an own-metal award carries a 10000 basis point uplift, got "
            f"{booking['partner_uplift_bps_applied']}"
        )
        assert booking["surcharge_band"] == "SURCHARGE_MID", (
            f"a 45000-mile gross falls in SURCHARGE_MID, got {booking['surcharge_band']}"
        )
        assert booking["cash_surcharge_cents"] == 1120, (
            "SURCHARGE_MID charges 1120 cents for the single seat, got "
            f"{booking['cash_surcharge_cents']}"
        )
        assert booking["elite_discount_bps_applied"] == 0, (
            "a BASE member receives no elite discount, got "
            f"{booking['elite_discount_bps_applied']}"
        )
        assert booking["quoted_miles"] == 45000, (
            f"the undiscounted single-seat quote is 45000 miles, got {booking['quoted_miles']}"
        )

    def test_refund_returns_member_balance_and_program_outstanding_miles(self):
        """PRD §3.5: "A refund inserts a mile ledger row of `txn_type` `REVERSAL` with `total_miles` equal to positive `quoted_miles`, `award_booking_id` naming this booking and `reverses_transaction_id` naming the `REDEEM` row it undoes; restores the member's `mile_balance` and the programme's `outstanding_miles` by exactly `quoted_miles`, returning both to their pre-ticket values; decreases the window's `seats_confirmed` by `seats` and, for a `SAVER` booking, `saver_seats_consumed` by `seats`; recomputes the window's posture; and moves `status` `TICKETED → REFUNDED`."
        PRD §3.5: "The member's `mile_balance` falls by `quoted_miles` and the programme's `outstanding_miles` falls by the same amount — the liability is discharged."

        Design: Difficulty/compensating_invariant/booking_refund_restores_outstanding_mile_liability
        """
        program, member, _window, booking = _ticketed_saver_booking()

        ticketed_member = read_member(member["id"])
        assert ticketed_member["mile_balance"] == 55000, (
            "ticketing debits the 45000-mile quote from the 100000-mile balance, got "
            f"{ticketed_member['mile_balance']}"
        )

        refunded = refund_booking(booking["id"])
        assert_award_booking(refunded)
        assert refunded["status"] == "REFUNDED", (
            f"refunding moves the booking to REFUNDED, got {refunded['status']}"
        )
        assert refunded["quoted_miles"] == 45000, (
            "the refund does not reprice the award, got quoted_miles "
            f"{refunded['quoted_miles']}"
        )

        member_after = read_member(member["id"])
        assert member_after["mile_balance"] == 100000, (
            "the refund restores the member's pre-ticket balance of 100000 miles, got "
            f"{member_after['mile_balance']}"
        )

        program_after = read_program(program["id"])
        assert program_after["outstanding_miles"] == 100000, (
            "the refund restores the programme's outstanding_miles to 100000, got "
            f"{program_after['outstanding_miles']}"
        )

    def test_refund_inserts_a_reversal_row_naming_the_redeem_it_undoes(self, api):
        """PRD §3.5: "A refund inserts a mile ledger row of `txn_type` `REVERSAL` with `total_miles` equal to positive `quoted_miles`, `award_booking_id` naming this booking and `reverses_transaction_id` naming the `REDEEM` row it undoes; restores the member's `mile_balance` and the programme's `outstanding_miles` by exactly `quoted_miles`, returning both to their pre-ticket values; decreases the window's `seats_confirmed` by `seats` and, for a `SAVER` booking, `saver_seats_consumed` by `seats`; recomputes the window's posture; and moves `status` `TICKETED → REFUNDED`."
        PRD §2.4: "Corrections to the mile ledger are made by inserting a further row — a reversal or an adjustment — never by rewriting history."

        Design: Difficulty/compensating_invariant/booking_refund_restores_outstanding_mile_liability
        """
        _program, member, _window, booking = _ticketed_saver_booking()

        redeem_rows, redeem_meta = validate_paginated(
            api.list_mile_transactions(
                PROGRAM_ADMIN,
                params={"member_id": member["id"], "txn_type": "REDEEM"},
            )
        )
        assert redeem_meta["total_count"] == 1, (
            "ticketing inserted exactly one REDEEM row, got total_count "
            f"{redeem_meta['total_count']}"
        )
        redeem_row = redeem_rows[0]

        refund_booking(booking["id"])

        all_rows, all_meta = validate_paginated(
            api.list_mile_transactions(
                PROGRAM_ADMIN, params={"member_id": member["id"]}
            )
        )
        assert all_meta["total_count"] == 3, (
            "the earn, the REDEEM and the REVERSAL all survive as separate rows, got "
            f"total_count {all_meta['total_count']}"
        )
        assert [row["txn_type"] for row in all_rows] == [
            "CARD_SPEND_EARN",
            "REDEEM",
            "REVERSAL",
        ], f"the ledger is append-only, got {[row['txn_type'] for row in all_rows]}"

        reversal_rows, reversal_meta = validate_paginated(
            api.list_mile_transactions(
                PROGRAM_ADMIN,
                params={"member_id": member["id"], "txn_type": "REVERSAL"},
            )
        )
        assert reversal_meta["total_count"] == 1, (
            "the refund inserted exactly one REVERSAL row, got total_count "
            f"{reversal_meta['total_count']}"
        )
        reversal = reversal_rows[0]
        assert_mile_transaction(reversal)
        assert reversal["total_miles"] == 45000, (
            "the REVERSAL row carries positive quoted_miles of 45000, got "
            f"{reversal['total_miles']}"
        )
        assert reversal["reverses_transaction_id"] == redeem_row["id"], (
            "the REVERSAL row names the REDEEM row it undoes, got "
            f"{reversal['reverses_transaction_id']} instead of {redeem_row['id']}"
        )
        assert reversal["award_booking_id"] == booking["id"], (
            "the REVERSAL row names the refunded booking, got "
            f"{reversal['award_booking_id']}"
        )

    def test_refund_releases_confirmed_and_saver_seats_and_repostures_the_window(self):
        """PRD §3.5: "A refund inserts a mile ledger row of `txn_type` `REVERSAL` with `total_miles` equal to positive `quoted_miles`, `award_booking_id` naming this booking and `reverses_transaction_id` naming the `REDEEM` row it undoes; restores the member's `mile_balance` and the programme's `outstanding_miles` by exactly `quoted_miles`, returning both to their pre-ticket values; decreases the window's `seats_confirmed` by `seats` and, for a `SAVER` booking, `saver_seats_consumed` by `seats`; recomputes the window's posture; and moves `status` `TICKETED → REFUNDED`."
        PRD §3.5: "`load_factor_bps` is `seats_held` plus `seats_confirmed`, multiplied by 10000, divided by `authorized_seats`, rounded half up, and defined as zero when `authorized_seats` is zero."
        PRD §3.5: "`capacity_control_state` then follows from it against two inclusive lower bounds: a load factor below 7500 basis points (75% sold) is `OPEN`, a load factor from 7500 through 9999 is `CONSTRAINED`, and a load factor of 10000 or more is `CLOSED`."

        Design: Difficulty/compensating_invariant/booking_refund_restores_outstanding_mile_liability
        """
        _program, _member, window, booking = _ticketed_saver_booking()

        ticketed_window = read_window(window["id"])
        assert ticketed_window["seats_confirmed"] == 1, (
            "ticketing converted the held seat into a confirmed one, got "
            f"{ticketed_window['seats_confirmed']}"
        )

        refund_booking(booking["id"])

        window_after = read_window(window["id"])
        assert_award_inventory_window(window_after)
        assert window_after["seats_confirmed"] == 0, (
            "the refund releases the confirmed seat, got "
            f"{window_after['seats_confirmed']}"
        )
        assert window_after["seats_held"] == 0, (
            f"no seat remains held after the refund, got {window_after['seats_held']}"
        )
        assert window_after["saver_seats_consumed"] == 0, (
            "the refund releases the SAVER allotment seat, got "
            f"{window_after['saver_seats_consumed']}"
        )
        assert window_after["load_factor_bps"] == 0, (
            "an emptied window recomputes to a load factor of 0, got "
            f"{window_after['load_factor_bps']}"
        )
        assert window_after["capacity_control_state"] == "OPEN", (
            "a load factor below 7500 basis points is OPEN, got "
            f"{window_after['capacity_control_state']}"
        )


# --------------------------------------------------------------------------- #
# The epoch sweep expires a lapsed hold and returns its seats to inventory
# --------------------------------------------------------------------------- #
def _held_three_seat_saver_booking():
    """Programme, funded member, window and a HELD 3-seat SAVER booking."""
    program = create_program(name="SkyMiles Hold Expiry", current_period="2026-08")
    member = create_member(
        program["id"], external_member_ref="MBR-HOLD", home_region="AMER"
    )
    post_transaction(
        member["id"],
        "CARD_SPEND_EARN",
        "2026-07-02",
        headers=REVENUE_ACCOUNTANT,
        qualifying_spend_cents=10000000,
    )
    window = create_window(
        program["id"],
        route_code="JFK-LHR",
        cabin="BUSINESS",
        window_start_date="2026-09-01",
        window_end_date="2026-09-30",
        authorized_seats=10,
        saver_seat_share_bps=3000,
    )
    booking = hold_seats(
        member["id"],
        window["id"],
        window["version"],
        headers=member_headers_for(member["id"]),
        travel_date="2026-09-12",
        seats=3,
        fare_class="SAVER",
    )
    return program, member, window, booking


class TestHoldExpiryRestoresSeatInventory:
    def test_hold_expires_seventy_two_hours_after_it_was_created(self):
        """PRD §3.5: "The hold survives 72 hours: `hold_expires_at` is stamped as the logical clock's now plus 72 hours, and the booking lands with `status` `HELD` and `partner_settled` false."
        PRD §3.5: "`quoted_miles` is then the gross per-seat figure multiplied by the quantity (10000 minus `elite_discount_bps_applied`), divided by 10000, rounded half up **per seat**, and only then multiplied by `seats`."

        Design: Difficulty/compensating_invariant/hold_expiry_restores_award_seat_inventory
        """
        _program, _member, window, booking = _held_three_seat_saver_booking()
        assert_award_booking(booking)

        assert booking["hold_expires_at"].startswith("2026-08-04T00:00:00"), (
            "the hold created at 2026-08-01T00:00:00Z lapses 72 hours later, got "
            f"{booking['hold_expires_at']}"
        )
        assert booking["status"] == "HELD", (
            f"a new booking lands in HELD, got {booking['status']}"
        )
        assert booking["partner_settled"] is False, (
            f"a new booking lands with partner_settled false, got {booking['partner_settled']}"
        )
        assert booking["quoted_miles"] == 135000, (
            "the 45000-mile per-seat price times three seats is 135000, got "
            f"{booking['quoted_miles']}"
        )

        held_window = read_window(window["id"])
        assert held_window["seats_held"] == 3, (
            f"the hold reserved three seats, got {held_window['seats_held']}"
        )
        assert held_window["saver_seats_consumed"] == 3, (
            "the SAVER hold consumed three of the saver allotment, got "
            f"{held_window['saver_seats_consumed']}"
        )
        assert held_window["load_factor_bps"] == 3000, (
            "three of ten authorised seats is a load factor of 3000, got "
            f"{held_window['load_factor_bps']}"
        )

    def test_epoch_sweep_expires_the_lapsed_hold_and_releases_its_seats(self, api):
        """PRD §3.1: "Within one sweep, award booking holds whose `hold_expires_at` is at or before now move `HELD → EXPIRED` and release their seats; campaigns whose `window_start` has arrived move `SCHEDULED → LIVE` and campaigns whose `window_end` has arrived move `LIVE → ENDED`; member accounts whose `status_match_expires_at` is at or before now move `TRIAL → LAPSED`; programme change notices advance `ANNOUNCED → IN_GRANDFATHER`, `ANNOUNCED → EFFECTIVE` or `IN_GRANDFATHER → EFFECTIVE` as their dates dictate; active agreements whose `term_end_date` now lies before the clock's calendar date move `ACTIVE → EXPIRED`, which drops them out of the ratified-and-active set and therefore recomputes the issuer's `aggregate_committed_miles`; and every award inventory window recomputes `load_factor_bps`, `demand_multiplier_bps` and `capacity_control_state`."
        PRD §3.5: "**Expiry** is the epoch sweep's equivalent for a hold whose `hold_expires_at` has passed: it moves `HELD → EXPIRED` with the identical seat release and recompute, and it explicitly leaves `mile_balance` untouched, because a hold never debited any miles in the first place."

        Design: Difficulty/compensating_invariant/hold_expiry_restores_award_seat_inventory
        """
        program, _member, window, booking = _held_three_seat_saver_booking()

        set_clock("2026-08-04T00:00:01Z")
        report = run_epoch(program["id"])
        assert report["holds_expired"] == 1, (
            f"the single lapsed hold was expired, got holds_expired {report['holds_expired']}"
        )

        booking_after = validate_success(
            api.get_award_booking(booking["id"], PROGRAM_ADMIN)
        )
        assert booking_after["status"] == "EXPIRED", (
            f"the lapsed hold moves HELD to EXPIRED, got {booking_after['status']}"
        )

        window_after = read_window(window["id"])
        assert_award_inventory_window(window_after)
        assert window_after["seats_held"] == 0, (
            "all three held seats were released, got "
            f"{window_after['seats_held']}"
        )
        assert window_after["saver_seats_consumed"] == 0, (
            "the saver allotment was unwound from 3 back to 0, got "
            f"{window_after['saver_seats_consumed']}"
        )
        assert window_after["load_factor_bps"] == 0, (
            "the load factor was unwound from 3000 back to 0, got "
            f"{window_after['load_factor_bps']}"
        )
        assert window_after["capacity_control_state"] == "OPEN", (
            "a load factor below 7500 basis points is OPEN, got "
            f"{window_after['capacity_control_state']}"
        )

    def test_hold_expiry_leaves_the_member_mile_liability_untouched(self, api):
        """PRD §3.5: "**Expiry** is the epoch sweep's equivalent for a hold whose `hold_expires_at` has passed: it moves `HELD → EXPIRED` with the identical seat release and recompute, and it explicitly leaves `mile_balance` untouched, because a hold never debited any miles in the first place."
        PRD §3.1: "`outstanding_miles` is the member-held mile liability: the sum of `total_miles` across every mile ledger row belonging to a member of this programme, taking every `txn_type` and respecting the sign of each row, recomputed on every insert."

        Design: Difficulty/compensating_invariant/hold_expiry_restores_award_seat_inventory
        """
        program, member, _window, _booking = _held_three_seat_saver_booking()

        set_clock("2026-08-04T00:00:01Z")
        run_epoch(program["id"])

        member_after = read_member(member["id"])
        assert member_after["mile_balance"] == 100000, (
            "the expired hold never debited miles, so the balance stays at 100000, got "
            f"{member_after['mile_balance']}"
        )

        program_after = read_program(program["id"])
        assert program_after["outstanding_miles"] == 100000, (
            "no ledger row was inserted, so outstanding_miles stays at 100000, got "
            f"{program_after['outstanding_miles']}"
        )

        _rows, meta = validate_paginated(
            api.list_mile_transactions(
                PROGRAM_ADMIN, params={"member_id": member["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            "only the original card-spend earn sits in the ledger, got total_count "
            f"{meta['total_count']}"
        )

    def test_second_epoch_sweep_does_not_release_the_seats_twice(self):
        """PRD §3.1: "Within one sweep, award booking holds whose `hold_expires_at` is at or before now move `HELD → EXPIRED` and release their seats; campaigns whose `window_start` has arrived move `SCHEDULED → LIVE` and campaigns whose `window_end` has arrived move `LIVE → ENDED`; member accounts whose `status_match_expires_at` is at or before now move `TRIAL → LAPSED`; programme change notices advance `ANNOUNCED → IN_GRANDFATHER`, `ANNOUNCED → EFFECTIVE` or `IN_GRANDFATHER → EFFECTIVE` as their dates dictate; active agreements whose `term_end_date` now lies before the clock's calendar date move `ACTIVE → EXPIRED`, which drops them out of the ratified-and-active set and therefore recomputes the issuer's `aggregate_committed_miles`; and every award inventory window recomputes `load_factor_bps`, `demand_multiplier_bps` and `capacity_control_state`."
        PRD §3.5: "**Expiry** is the epoch sweep's equivalent for a hold whose `hold_expires_at` has passed: it moves `HELD → EXPIRED` with the identical seat release and recompute, and it explicitly leaves `mile_balance` untouched, because a hold never debited any miles in the first place."

        Design: Difficulty/compensating_invariant/hold_expiry_restores_award_seat_inventory
        """
        program, _member, window, _booking = _held_three_seat_saver_booking()

        set_clock("2026-08-04T00:00:01Z")
        first = run_epoch(program["id"])
        assert first["holds_expired"] == 1, (
            f"the first sweep expires the lapsed hold, got {first['holds_expired']}"
        )

        second = run_epoch(program["id"])
        assert second["holds_expired"] == 0, (
            "the already-EXPIRED booking is terminal, so no hold expires twice; got "
            f"holds_expired {second['holds_expired']}"
        )

        window_after = read_window(window["id"])
        assert window_after["seats_held"] == 0, (
            "the seat release is not applied twice, got seats_held "
            f"{window_after['seats_held']}"
        )
        assert window_after["saver_seats_consumed"] == 0, (
            "the saver allotment release is not applied twice, got "
            f"{window_after['saver_seats_consumed']}"
        )
        assert window_after["load_factor_bps"] == 0, (
            "the load factor stays at 0 after the idempotent second sweep, got "
            f"{window_after['load_factor_bps']}"
        )


# --------------------------------------------------------------------------- #
# Rung 15 (backdated window) is reported ahead of rung 19 (channel overlap)
# --------------------------------------------------------------------------- #
def _program_with_september_card_spend_campaign():
    """A programme plus one SCHEDULED CARD_SPEND campaign over September 2026."""
    program = create_program(name="SkyMiles Promo Priority", current_period="2026-08")
    incumbent = create_campaign(
        program["id"],
        code="SEPT-SPEND",
        earn_channel="CARD_SPEND",
        multiplier_bps=15000,
        stacking_mode="ADDITIVE",
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-10-01T00:00:00Z",
    )
    return program, incumbent


class TestWindowInPastBeatsPromotionOverlap:
    def test_backdated_and_overlapping_campaign_reports_window_in_past(self, api):
        """PRD §2.9: "Checks are evaluated in ascending order, and **the first check that fails is the response** — no later check runs, and no partial mutation is retained."
        PRD §2.9: "A newly created promotion campaign or award inventory window does not open in the past: its `window_start`, or its `window_start_date` read at `00:00:00Z`, is at or after the logical clock's current instant — otherwise `ERR_WINDOW_IN_PAST` (422)."
        PRD §2.9: "A new campaign's window does not overlap an existing `SCHEDULED` or `LIVE` campaign sharing the same `program_id` and `earn_channel` — otherwise `ERR_PROMOTION_WINDOW_OVERLAP` (409)."

        Design: Difficulty/priority_pair_validation_conflict/promotion_window_in_past_temporal_beats_overlap_constraint
        """
        program, _incumbent = _program_with_september_card_spend_campaign()

        # Backdated (rung 15) and overlapping the incumbent CARD_SPEND window (rung 19).
        resp = api.create_promotion_campaign(
            promotion_campaign_payload(
                program["id"],
                code="BACKDATED-OVERLAP",
                earn_channel="CARD_SPEND",
                multiplier_bps=12500,
                stacking_mode="ADDITIVE",
                window_start="2026-07-01T00:00:00Z",
                window_end="2026-09-15T00:00:00Z",
            ),
            PROGRAM_ADMIN,
        )
        validate_error(resp, "ERR_WINDOW_IN_PAST", 422)

        body = resp.json()
        assert body["data"]["error_id"] != "ERR_PROMOTION_WINDOW_OVERLAP", (
            "the lower-numbered backdated-window rung owns the response, not the "
            f"overlap rung; got {body['data']['error_id']}"
        )
        assert resp.status_code != 409, (
            f"the overlap status 409 must not be reported, got {resp.status_code}"
        )

    def test_refused_backdated_campaign_leaves_the_incumbent_untouched(self, api):
        """PRD §2.9: "Checks are evaluated in ascending order, and **the first check that fails is the response** — no later check runs, and no partial mutation is retained."
        PRD §3.4: "The window must be correctly ordered, with `window_start` strictly before `window_end`, and it must not open before the current logical-clock instant, else `ERR_WINDOW_IN_PAST`."

        Design: Difficulty/priority_pair_validation_conflict/promotion_window_in_past_temporal_beats_overlap_constraint
        """
        program, incumbent = _program_with_september_card_spend_campaign()

        resp = api.create_promotion_campaign(
            promotion_campaign_payload(
                program["id"],
                code="BACKDATED-OVERLAP",
                earn_channel="CARD_SPEND",
                multiplier_bps=12500,
                stacking_mode="ADDITIVE",
                window_start="2026-07-01T00:00:00Z",
                window_end="2026-09-15T00:00:00Z",
            ),
            PROGRAM_ADMIN,
        )
        validate_error(resp, "ERR_WINDOW_IN_PAST", 422)

        rows, meta = validate_paginated(
            api.list_promotion_campaigns(
                PROGRAM_ADMIN, params={"program_id": program["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            "no partial mutation is retained, so only the incumbent campaign exists; "
            f"got total_count {meta['total_count']}"
        )
        assert [row["code"] for row in rows] == ["SEPT-SPEND"], (
            f"only SEPT-SPEND survives, got {[row['code'] for row in rows]}"
        )

        incumbent_now = validate_success(
            api.get_promotion_campaign(incumbent["id"], PROGRAM_ADMIN)
        )
        assert_promotion_campaign(incumbent_now)
        assert incumbent_now["status"] == "SCHEDULED", (
            "the incumbent campaign is untouched and stays SCHEDULED, got "
            f"{incumbent_now['status']}"
        )
        assert incumbent_now["version"] == incumbent["version"], (
            "the refused request mutated nothing, so the incumbent's version is "
            f"unchanged at {incumbent['version']}, got {incumbent_now['version']}"
        )
