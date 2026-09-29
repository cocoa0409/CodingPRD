"""Stale-version guards on the four protected writes, and read-your-writes.

Each test replays a version token that a prior accepted write has already
consumed, and then proves two things: the refused call changed nothing, and the
identical body succeeds once the token is refreshed. The last two tests pin the
tier threshold to its exact constant and show that every figure a write derives
is already visible in the response that caused it.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    booking_version,
    clearance_version,
    close_engagement,
    counter_payload,
    enrol_member,
    lodge_counter_round,
    lodge_donation,
    open_showtime_sales,
    place_showtime,
    read_booking,
    read_clearance,
    read_member,
    read_showtime,
    register_distributor,
    register_venue,
    catalogue_title,
    open_engagement,
    auto_schedule_payload,
    settlement_payload,
    showtime_payload,
    ticket_order_payload,
    make_member_headers,
    setup_programming_baseline,
    validate_error,
    validate_paginated,
    validate_success,
)

PROGRAMMER = TEST_USERS["programmer_headers"]
BOX_OFFICE = TEST_USERS["box_office_headers"]
EXECUTIVE_DIRECTOR = TEST_USERS["executive_director_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


def _canonical_engagement():
    """Venue, distributor, title and an OFFERED engagement at the canonical terms."""
    venue = register_venue()
    distributor = register_distributor()
    title = catalogue_title(distributor["id"])
    booking = open_engagement(title["id"], distributor["id"], venue["id"])
    return venue, distributor, title, booking


def _showtime_body(world, start_at, expected_clearance_version, **overrides):
    """A complete manual-placement body with the caller's own version token."""
    return showtime_payload(
        world["venue"]["id"],
        world["title"]["id"],
        world["booking"]["id"],
        world["clearance"]["id"],
        world["asset"]["id"],
        start_at,
        expected_clearance_version,
        **overrides,
    )


class TestStaleBookingVersion:

    def test_counter_replaying_a_consumed_booking_version_is_refused(self, api):
        """PRD §2.6: "`POST /bookings/{id}/counter` must carry
        `expected_booking_version` holding the client's last observed `version` of
        the target booking. If that value does not equal the booking's current
        `version`, the counter is rejected with `ERR_STALE_BOOKING_VERSION` (HTTP
        412). Lodging a counter is legitimately repeatable — it is valid from both
        the offered and the countered state — so without this guard a caller
        answering a round that another writer has already superseded would silently
        succeed against a negotiation it has not seen."

        PRD §3.2: "Each such round supersedes whatever round it answers: the
        engagement's currently `PENDING` round has its `outcome` flipped to
        `COUNTERED`, a new round is created with `round_index` one greater than the
        engagement's `round_count`, `proposed_by` set to `DISTRIBUTOR`, `outcome`
        `PENDING` and the four posted `proposed_*` figures, the engagement's
        `round_count` increases by one, and the engagement's `version` increments."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_booking_version_on_counter_returns_412
        """
        _venue, _distributor, _title, booking = _canonical_engagement()
        booking_id = booking["id"]
        assert booking["status"] == "OFFERED", (
            f"Expected the engagement OFFERED, got {booking['status']}"
        )
        assert booking["round_count"] == 1, (
            f"Expected round_count 1 at creation, got {booking['round_count']}"
        )
        assert booking["version"] == 1, (
            f"Expected version 1 at creation, got {booking['version']}"
        )

        # The token the client is holding. The first counter consumes it.
        b_v1 = booking["version"]
        lodge_counter_round(
            booking_id,
            expected_booking_version=b_v1,
            proposed_house_nut_cents=14000,
            proposed_distributor_share_pct=0.40,
            proposed_min_run_days=5,
            proposed_guarantee_cents=4000,
        )

        # The negotiation budget is four rounds and only two are spent, so nothing
        # but the spent token can refuse a third.
        refused = api.counter_booking(
            booking_id,
            counter_payload(
                b_v1,
                proposed_house_nut_cents=13000,
                proposed_distributor_share_pct=0.38,
                proposed_min_run_days=4,
                proposed_guarantee_cents=3500,
            ),
            PROGRAMMER,
        )
        validate_error(refused, ApiErrorId.ERR_STALE_BOOKING_VERSION.value)
        assert refused.status_code == 412, (
            f"Expected 412 for a superseded token, got {refused.status_code}"
        )

        held = read_booking(booking_id)
        assert held["round_count"] == 2, (
            f"The rejected call must not open a round, got {held['round_count']}"
        )
        assert held["version"] == 2, (
            f"The rejected call must not bump the version, got {held['version']}"
        )
        assert held["status"] == "COUNTERED", (
            f"Expected COUNTERED, got {held['status']}"
        )

        rounds, meta = validate_paginated(
            api.list_booking_offers(booking_id, PROGRAMMER, params={"limit": 10})
        )
        assert meta["total_count"] == 2, (
            f"Expected exactly 2 rounds in the log, got {meta['total_count']}"
        )
        by_index = {row["round_index"]: row for row in rounds}
        assert by_index[1]["outcome"] == "COUNTERED", (
            f"Expected round 1 superseded, got {by_index[1]['outcome']}"
        )
        assert by_index[2]["outcome"] == "PENDING", (
            f"Expected round 2 still open, got {by_index[2]['outcome']}"
        )
        assert by_index[2]["proposed_house_nut_cents"] == 14000, (
            "Expected the accepted round's terms, got "
            f"{by_index[2]['proposed_house_nut_cents']}"
        )
        assert all(row["proposed_house_nut_cents"] != 13000 for row in rounds), (
            f"The refused terms must appear nowhere in the log, got {rounds}"
        )

        # The identical body lands once the token is refreshed, which is what
        # shows the payload was never the problem.
        accepted = lodge_counter_round(
            booking_id,
            expected_booking_version=booking_version(booking_id),
            proposed_house_nut_cents=13000,
            proposed_distributor_share_pct=0.38,
            proposed_min_run_days=4,
            proposed_guarantee_cents=3500,
        )
        assert accepted["round_index"] == 3, (
            f"Expected the retry to open round 3, got {accepted['round_index']}"
        )
        assert accepted["proposed_house_nut_cents"] == 13000, (
            "Expected the once-refused terms to be recorded verbatim, got "
            f"{accepted['proposed_house_nut_cents']}"
        )
        assert read_booking(booking_id)["round_count"] == 3, (
            f"Expected round_count 3, got {read_booking(booking_id)['round_count']}"
        )

    def test_settlement_replaying_the_version_its_own_draft_consumed_is_refused(
        self, api
    ):
        """PRD §2.6: "`POST /settlements` must carry `expected_booking_version`
        holding the client's last observed `version` of the booking being settled. A
        mismatch with the booking's current `version` is rejected with
        `ERR_STALE_BOOKING_VERSION` (HTTP 412). A fresh draft settlement legitimately
        supersedes an earlier draft on the same engagement, so the guard is what
        catches the caller whose view of the closed engagement's playing days and
        shortfall penalty predates another writer's draft."

        PRD §3.9: "A fresh draft may legitimately supersede an earlier draft on the
        same engagement, which is exactly why the stale-version guard exists.
        Drafting computes and stores every figure, copies the engagement's
        `min_run_penalty_cents` onto the settlement, creates the settlement in
        `DRAFT` with `submitted_by_user_id`, `finalized_by_user_id` and
        `dispute_note` all null, and increments the engagement's `version`."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_booking_version_on_settlement_creation_returns_412
        """
        world = setup_programming_baseline()
        booking_id = world["booking"]["id"]

        # One screening was scheduled but never played, so the engagement closes
        # with no playing days at all and carries the full four-day shortfall.
        place_showtime(world, "2026-08-14T12:00:00Z")
        closed = close_engagement(booking_id)
        assert closed["status"] == "CLOSED", (
            f"Expected the engagement CLOSED, got {closed['status']}"
        )
        assert closed["min_run_penalty_cents"] == 6250, (
            f"Expected a 6250-cent shortfall, got {closed['min_run_penalty_cents']}"
        )

        # The token the drafting clerk is holding. Their own draft consumes it.
        b_v1 = booking_version(booking_id, BOX_OFFICE)
        first = validate_success(
            api.create_settlement(
                settlement_payload(booking_id, b_v1, "PROVISIONAL"), BOX_OFFICE
            ),
            expected_status=201,
        )

        refused = api.create_settlement(
            settlement_payload(booking_id, b_v1, "FINAL"), BOX_OFFICE
        )
        validate_error(refused, ApiErrorId.ERR_STALE_BOOKING_VERSION.value)
        assert refused.status_code == 412, (
            f"Expected 412 for a superseded token, got {refused.status_code}"
        )

        rows, meta = validate_paginated(
            api.list_settlements(BOX_OFFICE, params={"booking_id": booking_id})
        )
        assert meta["total_count"] == 1, (
            f"The refused draft must not exist, got {meta['total_count']} rows"
        )
        assert [row["id"] for row in rows] == [first["id"]], (
            f"Expected only the accepted draft, got {[row['id'] for row in rows]}"
        )
        assert rows[0]["variant"] == "PROVISIONAL", (
            f"Expected the accepted variant, got {rows[0]['variant']}"
        )
        assert rows[0]["status"] == "DRAFT", (
            f"Expected DRAFT, got {rows[0]['status']}"
        )
        assert rows[0]["min_run_penalty_cents"] == 6250, (
            "The refused call must not disturb the accepted figures, got "
            f"{rows[0]['min_run_penalty_cents']}"
        )

        held = read_booking(booking_id, BOX_OFFICE)
        assert held["status"] == "CLOSED", (
            f"Expected the engagement still CLOSED, got {held['status']}"
        )
        assert held["version"] == b_v1 + 1, (
            "Only the accepted draft may advance the engagement version: expected "
            f"{b_v1 + 1}, got {held['version']}"
        )

        # A refreshed token admits the very body that was just refused.
        second = validate_success(
            api.create_settlement(
                settlement_payload(
                    booking_id, booking_version(booking_id, BOX_OFFICE), "FINAL"
                ),
                BOX_OFFICE,
            ),
            expected_status=201,
        )
        assert second["id"] != first["id"], (
            "Expected a second settlement row, got the first one back"
        )
        assert second["variant"] == "FINAL", (
            f"Expected FINAL, got {second['variant']}"
        )


class TestStaleClearanceVersion:

    def test_showtime_replaying_a_drawn_down_clearance_version_is_refused(self, api):
        """PRD §2.6: "`POST /showtimes` must carry `expected_clearance_version`
        holding the client's last observed `version` of the rights clearance the
        screening will draw down. A mismatch with the clearance's current `version`
        is rejected with `ERR_STALE_CLEARANCE_VERSION` (HTTP 412). Many screenings
        legitimately draw on one clearance, so a repeat call would otherwise
        succeed; the guard catches the caller whose remaining-screenings figure
        predates another writer's draw-down or a cancellation's restore."

        PRD §3.5: "It then draws down the licence: `screenings_used` rises by one,
        `screenings_remaining` falls by one, the licence's `version` increments, and
        the engagement's `scheduled_showtime_count` rises by one."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_clearance_version_on_showtime_creation_returns_412
        """
        world = setup_programming_baseline()
        venue_id = world["venue"]["id"]
        clearance_id = world["clearance"]["id"]
        booking_id = world["booking"]["id"]

        # The token the scheduler is holding. Placing the first screening spends it.
        c_v1 = clearance_version(clearance_id)
        first = place_showtime(world, "2026-08-14T12:00:00Z",
                              expected_clearance_version=c_v1)

        # The candidate is a day later on an empty screen and inside both the
        # licence window and the engagement, so only the spent token can refuse it.
        refused = api.create_showtime(
            _showtime_body(world, "2026-08-15T12:00:00Z", c_v1), PROGRAMMER
        )
        validate_error(refused, ApiErrorId.ERR_STALE_CLEARANCE_VERSION.value)
        assert refused.status_code == 412, (
            f"Expected 412 for a spent token, got {refused.status_code}"
        )

        licence = read_clearance(clearance_id)
        assert licence["screenings_used"] == 1, (
            f"The refused call drew nothing down, got {licence['screenings_used']}"
        )
        assert licence["screenings_remaining"] == 5, (
            f"Expected screenings_remaining 5, got {licence['screenings_remaining']}"
        )

        rows, meta = validate_paginated(
            api.list_showtimes(PROGRAMMER, params={"venue_id": venue_id})
        )
        assert meta["total_count"] == 1, (
            f"Expected exactly 1 screening at the auditorium, got {meta['total_count']}"
        )
        assert [row["id"] for row in rows] == [first["id"]], (
            f"Expected only the accepted screening, got {[row['id'] for row in rows]}"
        )
        assert read_booking(booking_id)["scheduled_showtime_count"] == 1, (
            "Expected scheduled_showtime_count 1, got "
            f"{read_booking(booking_id)['scheduled_showtime_count']}"
        )

        # Refresh the token and the same screening lands, drawing the allowance on.
        second = place_showtime(world, "2026-08-15T12:00:00Z")
        assert second["start_at"] == "2026-08-15T12:00:00.000Z", (
            f"Expected the same instant to be accepted, got {second['start_at']}"
        )
        licence = read_clearance(clearance_id)
        assert licence["screenings_used"] == 2, (
            f"Expected screenings_used 2, got {licence['screenings_used']}"
        )
        assert licence["screenings_remaining"] == 4, (
            f"Expected screenings_remaining 4, got {licence['screenings_remaining']}"
        )

    def test_auto_schedule_replaying_a_spent_clearance_version_scores_no_slot(
        self, api
    ):
        """PRD §2.6: "`POST /showtimes/auto-schedule` carries the same
        `expected_clearance_version` guard, with the same
        `ERR_STALE_CLEARANCE_VERSION` (HTTP 412) rejection. The optimiser reads both
        the clearance's remaining allowance and the day's existing occupancy before
        it mints a slot, so a caller holding an out-of-date clearance version is
        refused before any slot is created."

        PRD §3.5: "Surviving slots are then scored, and the winner's score is stored
        on the created screening as `slot_score` — a field that is only ever
        populated by the optimiser and stays null on a hand-placed screening."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_clearance_version_on_auto_schedule_returns_412
        """
        world = setup_programming_baseline()
        venue_id = world["venue"]["id"]
        clearance_id = world["clearance"]["id"]

        c_v1 = clearance_version(clearance_id)
        by_hand = place_showtime(world, "2026-08-14T12:00:00Z",
                                 expected_clearance_version=c_v1)
        assert by_hand["slot_score"] is None, (
            f"A hand-placed screening carries no score, got {by_hand['slot_score']}"
        )

        # 16 August is an entirely empty day inside both windows, so the optimiser
        # would certainly find a legal slot were the token not spent: the refusal
        # must be the guard and not an exhausted search.
        refused = api.auto_schedule_showtime(
            auto_schedule_payload(
                venue_id,
                world["title"]["id"],
                world["booking"]["id"],
                clearance_id,
                world["asset"]["id"],
                "2026-08-16",
                "11:00",
                "22:00",
                c_v1,
            ),
            PROGRAMMER,
        )
        validate_error(refused, ApiErrorId.ERR_STALE_CLEARANCE_VERSION.value)
        assert refused.status_code == 412, (
            f"Expected 412 rather than a search failure, got {refused.status_code}"
        )

        # Nothing was minted on the target date.
        rows, meta = validate_paginated(
            api.list_showtimes(
                PROGRAMMER,
                params={"venue_id": venue_id, "start_from": "2026-08-16T00:00:00Z"},
            )
        )
        assert meta["total_count"] == 0, (
            f"The optimiser must not create a slot, got {meta['total_count']} rows"
        )
        assert rows == [], f"Expected no rows on the target date, got {rows}"

        licence = read_clearance(clearance_id)
        assert licence["screenings_used"] == 1, (
            f"Expected screenings_used 1, got {licence['screenings_used']}"
        )
        assert licence["screenings_remaining"] == 5, (
            f"Expected screenings_remaining 5, got {licence['screenings_remaining']}"
        )
        assert licence["version"] == c_v1 + 1, (
            "Only the hand-placed draw-down may advance the licence version: "
            f"expected {c_v1 + 1}, got {licence['version']}"
        )

        # Refresh the token and the optimiser both mints and scores a slot.
        placed = validate_success(
            api.auto_schedule_showtime(
                auto_schedule_payload(
                    venue_id,
                    world["title"]["id"],
                    world["booking"]["id"],
                    clearance_id,
                    world["asset"]["id"],
                    "2026-08-16",
                    "11:00",
                    "22:00",
                    clearance_version(clearance_id),
                ),
                PROGRAMMER,
            ),
            expected_status=201,
        )
        assert placed["slot_score"] is not None, (
            "The optimiser must record the winning score, got null"
        )
        assert read_showtime(placed["id"])["slot_score"] == placed["slot_score"], (
            "The stored score must match the one just returned"
        )


class TestDerivationBoundariesAndImmediateReads:

    def test_member_tier_fires_at_the_threshold_and_not_one_cent_below(self, api):
        """PRD §3.7: "Each figure is then mapped to a tier by the same thresholds:
        `DONOR_CIRCLE` at 50000 cents or more of giving, `SUPPORTER` at 15000 cents
        or more, `BASIC` at 6000 cents or more, and `PROSPECT` below that."

        PRD §3.7: "The rolling figure yields `rolling_tier`, the fiscal figure yields
        `fiscal_tier`, and `effective_tier` is whichever of the two ranks higher on
        the ordering `PROSPECT`, then `BASIC`, then `SUPPORTER`, then
        `DONOR_CIRCLE`; when the two agree, that agreed value is the effective one."

        PRD §3.7: "`discount_pct` is exactly 0.00 for `PROSPECT`, 0.10 for `BASIC`,
        0.15 for `SUPPORTER` and 0.25 for `DONOR_CIRCLE`, and is never rounded.
        `advance_access_hours` — the number of hours before a screening's
        `public_sale_opens_at` at which this member may already buy — is 0 for
        `PROSPECT`, 24 for `BASIC`, 48 for `SUPPORTER` and a full week, 168 hours,
        for `DONOR_CIRCLE`. `comp_tickets_granted` is 0 for both `PROSPECT` and
        `BASIC`, 2 for `SUPPORTER` and 6 for `DONOR_CIRCLE`, being the comp
        allowance for the current membership term."

        Design: Corner/cross_cutting_complexity_layers/member_tier_threshold_fires_at_the_exact_constant_and_not_one_cent_below
        """
        # Both gifts are stamped at the same instant, inside the trailing 365 days
        # but before the fiscal year opens, so the fiscal figure stays at zero for
        # both and the rolling figure is the only thing separating them.
        ada = enrol_member(full_name="Ada Wells", email="ada@example.com")
        cy = enrol_member(full_name="Cy Marsh", email="cy@example.com")

        at_threshold = lodge_donation(ada["id"], 15000, "2026-03-01T10:00:00Z")
        one_cent_short = lodge_donation(cy["id"], 14999, "2026-03-01T10:00:00Z")

        assert at_threshold["rolling_donation_cents"] == 15000, (
            f"Expected rolling 15000, got {at_threshold['rolling_donation_cents']}"
        )
        assert at_threshold["rolling_tier"] == "SUPPORTER", (
            f"15000 is the constant itself, got {at_threshold['rolling_tier']}"
        )
        assert at_threshold["fiscal_ytd_donation_cents"] == 0, (
            "A March gift falls outside the fiscal year, got "
            f"{at_threshold['fiscal_ytd_donation_cents']}"
        )
        assert at_threshold["fiscal_tier"] == "PROSPECT", (
            f"Expected fiscal_tier PROSPECT, got {at_threshold['fiscal_tier']}"
        )
        assert at_threshold["effective_tier"] == "SUPPORTER", (
            f"The higher of the two must win, got {at_threshold['effective_tier']}"
        )
        assert at_threshold["discount_pct"] == 0.15, (
            f"Expected discount_pct 0.15, got {at_threshold['discount_pct']}"
        )
        assert at_threshold["advance_access_hours"] == 48, (
            f"Expected 48 advance hours, got {at_threshold['advance_access_hours']}"
        )
        assert at_threshold["comp_tickets_granted"] == 2, (
            f"Expected 2 comps granted, got {at_threshold['comp_tickets_granted']}"
        )
        assert at_threshold["comp_tickets_remaining"] == 2, (
            f"Expected 2 comps unspent, got {at_threshold['comp_tickets_remaining']}"
        )

        assert one_cent_short["rolling_donation_cents"] == 14999, (
            f"Expected rolling 14999, got {one_cent_short['rolling_donation_cents']}"
        )
        assert one_cent_short["rolling_tier"] == "BASIC", (
            "One cent below the constant is still BASIC, got "
            f"{one_cent_short['rolling_tier']}"
        )
        assert one_cent_short["fiscal_tier"] == "PROSPECT", (
            f"Expected fiscal_tier PROSPECT, got {one_cent_short['fiscal_tier']}"
        )
        assert one_cent_short["effective_tier"] == "BASIC", (
            f"Expected effective_tier BASIC, got {one_cent_short['effective_tier']}"
        )
        assert one_cent_short["discount_pct"] == 0.10, (
            f"Expected discount_pct 0.10, got {one_cent_short['discount_pct']}"
        )
        assert one_cent_short["advance_access_hours"] == 24, (
            f"Expected 24 advance hours, got {one_cent_short['advance_access_hours']}"
        )
        assert one_cent_short["comp_tickets_granted"] == 0, (
            f"BASIC grants no comps, got {one_cent_short['comp_tickets_granted']}"
        )
        assert one_cent_short["comp_tickets_remaining"] == 0, (
            f"BASIC holds no comps, got {one_cent_short['comp_tickets_remaining']}"
        )

        # Both cleared the 6000-cent activation floor, and both take their expiry
        # from the same donation instant, so the tier split is not a state split.
        for label, member in (("at threshold", at_threshold), ("one short", one_cent_short)):
            assert member["status"] == "ACTIVE", (
                f"{label}: expected ACTIVE, got {member['status']}"
            )
            assert member["expires_at"] == "2027-03-01T10:00:00.000Z", (
                f"{label}: expected expiry 2027-03-01T10:00:00.000Z, got "
                f"{member['expires_at']}"
            )

        # The single missing cent, given at the very same instant, crosses it.
        lifted = lodge_donation(cy["id"], 1, "2026-03-01T10:00:00Z")
        assert lifted["rolling_donation_cents"] == 15000, (
            f"Expected rolling 15000, got {lifted['rolling_donation_cents']}"
        )
        assert lifted["rolling_tier"] == "SUPPORTER", (
            f"Expected SUPPORTER, got {lifted['rolling_tier']}"
        )
        assert lifted["effective_tier"] == "SUPPORTER", (
            f"Expected SUPPORTER, got {lifted['effective_tier']}"
        )
        assert lifted["discount_pct"] == 0.15, (
            f"Expected discount_pct 0.15, got {lifted['discount_pct']}"
        )
        assert lifted["comp_tickets_granted"] == 2, (
            f"Expected 2 comps granted, got {lifted['comp_tickets_granted']}"
        )
        assert read_member(ada["id"])["effective_tier"] == "SUPPORTER", (
            "The other member's standing must be untouched"
        )

    def test_order_response_already_carries_every_figure_it_derived(self, api):
        """PRD §3.8: "Fourth — and this is the step that must not be reordered —
        `unit_price_cents` is the gross unit price multiplied by one minus the
        discount, **rounded half up to a whole cent at this point, per ticket,
        before any multiplication**. Fifth `line_subtotal_cents` is that rounded
        `unit_price_cents` multiplied by the paid quantity. Sixth
        `facility_fee_cents` is 150 cents per seat multiplied by the order's full
        `quantity` — comp seats pay the facility fee too — and the fee is retained by
        the cinema rather than shared with the distributor."

        PRD §3.8: "An admitted order is created in `RESERVED` with a null
        `refund_destination`, and it moves the ledgers immediately: the member's
        `credit_balance_cents` falls by `applied_credit_cents`, the member's
        `comp_tickets_remaining` falls by `comp_quantity`, the screening's
        `seats_sold` rises by `quantity`, `seats_available` is recomputed, and the
        screening flips `ON_SALE → SOLD_OUT` if that lands on exactly zero."

        PRD §2.10: "After every mutation, including every cascade, the identity holds
        that `seats_sold` plus `seats_available` plus the venue's `house_hold_seats`
        equals the venue's `seat_capacity` — the house hold seats are permanently
        withheld from sale and are never sellable."

        Design: Corner/consistency_model/every_derived_figure_is_visible_in_the_same_response_that_caused_it
        """
        world = setup_programming_baseline()
        showtime = place_showtime(world, "2026-08-14T12:00:00Z")
        showtime_id = showtime["id"]
        on_sale = open_showtime_sales(showtime_id)
        assert on_sale["seats_sold"] == 0, (
            f"Expected an unsold screening, got {on_sale['seats_sold']}"
        )
        assert on_sale["seats_available"] == 8, (
            f"Expected 8 sellable seats of 12, got {on_sale['seats_available']}"
        )

        member = enrol_member(full_name="Ada Wells", email="ada@example.com")
        member = lodge_donation(member["id"], 20000, "2026-03-01T10:00:00Z")
        assert member["effective_tier"] == "SUPPORTER", (
            f"Expected SUPPORTER, got {member['effective_tier']}"
        )

        # Three seats, one of them a comp, bought by the member themselves.
        created = validate_success(
            api.create_ticket_order(
                ticket_order_payload(
                    showtime_id,
                    3,
                    member_id=member["id"],
                    comp_quantity=1,
                    purchaser_email="ada@example.com",
                ),
                make_member_headers(member["id"]),
            ),
            expected_status=201,
        )

        # Every derived money figure is already in the creation body: no follow-up
        # read is needed to learn what the write computed.
        assert created["status"] == "RESERVED", (
            f"Expected RESERVED, got {created['status']}"
        )
        assert created["unit_price_cents"] == 1233, (
            f"Expected unit_price_cents 1233, got {created['unit_price_cents']}"
        )
        assert created["line_subtotal_cents"] == 2466, (
            f"Expected line_subtotal_cents 2466, got {created['line_subtotal_cents']}"
        )
        assert created["facility_fee_cents"] == 450, (
            f"Expected facility_fee_cents 450, got {created['facility_fee_cents']}"
        )
        assert created["total_cents"] == 2916, (
            f"Expected total_cents 2916, got {created['total_cents']}"
        )
        assert created["applied_credit_cents"] == 0, (
            f"Expected no credit applied, got {created['applied_credit_cents']}"
        )
        assert created["refund_destination"] is None, (
            f"Expected a null refund_destination, got {created['refund_destination']!r}"
        )

        # The very next read of the screening already sees the seats move.
        first_read = api.get_showtime(showtime_id, ANONYMOUS)
        sold = validate_success(first_read, expected_status=200)
        assert sold["seats_sold"] == 3, (
            f"Comps occupy seats too: expected 3, got {sold['seats_sold']}"
        )
        assert sold["seats_available"] == 5, (
            f"Expected 5 seats left, got {sold['seats_available']}"
        )
        assert sold["sale_status"] == "ON_SALE", (
            f"Five seats remain, so not SOLD_OUT: got {sold['sale_status']}"
        )
        assert sold["seats_sold"] + sold["seats_available"] + 4 == 12, (
            "Seat conservation broke: "
            f"{sold['seats_sold']} + {sold['seats_available']} + 4 != 12"
        )

        # And the very next read of the member already sees the comp spent.
        first_member_read = api.get_member(member["id"], BOX_OFFICE)
        spent = validate_success(first_member_read, expected_status=200)
        assert spent["comp_tickets_granted"] == 2, (
            f"Expected 2 comps granted, got {spent['comp_tickets_granted']}"
        )
        assert spent["comp_tickets_remaining"] == 1, (
            f"One comp was spent on the order, got {spent['comp_tickets_remaining']}"
        )
        assert spent["effective_tier"] == "SUPPORTER", (
            f"Buying does not change standing, got {spent['effective_tier']}"
        )
        assert spent["discount_pct"] == 0.15, (
            f"Expected discount_pct 0.15, got {spent['discount_pct']}"
        )
        assert spent["credit_balance_cents"] == 0, (
            f"No credit was held or spent, got {spent['credit_balance_cents']}"
        )

        # Reads are pure: repeating either one returns the identical body.
        assert validate_success(
            api.get_showtime(showtime_id, ANONYMOUS), expected_status=200
        ) == sold, "A repeated read of the screening must be identical"
        assert validate_success(
            api.get_member(member["id"], BOX_OFFICE), expected_status=200
        ) == spent, "A repeated read of the member must be identical"
