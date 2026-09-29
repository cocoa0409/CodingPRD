"""Award booking: the pinned five-step points price, the member's own award
calendar, and the per-night inventory count that a cancellation gives back."""

from test_helpers import (
    ApiErrorId,
    assert_fund,
    assert_ledger_entry,
    assert_ledger_sum_equals,
    assert_member,
    assert_redemption,
    assert_scoped_ledger_sum_is_zero,
    count_entries_of_type,
    entries_of_type,
    factories as fac,
    fixtures as fx,
    make_member_headers,
    validate_error,
    validate_success,
)


# ----------------------------------------------------------------------
# Scenario builders
# ----------------------------------------------------------------------
def _dune_ridge_peak_only_program(api):
    """A resort selling only peak inventory in September, and a GOLD member holding
    301,234 points - enough that the price, not the balance, is what is tested."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR-DRR",
        rate_category="TRANSIENT",
        name="Dune Ridge Resort",
        brand_code="DRR",
        market_tier="RESORT",
        program_fee_pct=0.0475,
        rooms_count=140,
        trailing_12m_occupancy_pct=0.68,
        trailing_12m_adr_cents=38_000,
    )
    hotel_id = bundle["hotel"]["id"]
    fx.publish_pricing(
        api,
        hotel_id,
        season="PEAK",
        window_start_date="2026-09-01",
        window_end_date="2026-09-30",
        points_per_night=70_000,
        cash_copay_cents=2_000,
        min_tier_required="BASE",
        award_allotment_per_night=3,
    )
    member = fx.enroll_member(api)
    fx.posted_stay(
        api,
        hotel_id,
        member["id"],
        bundle["rate_plan"]["id"],
        "2026-05-01",
        "2026-05-31",
        12_345,
    )
    fx.settled_purchase(api, member["id"], 100_000, channel="DIRECT_PURCHASE")
    fx.grant_goodwill_points(
        api, member["id"], 200_000, reason="Legacy programme conversion balance"
    )

    bundle["member"] = fx.read_member(api, member["id"])
    bundle["member_headers"] = make_member_headers(member["id"])
    return bundle


def _larkspur_with_one_held_award(api):
    """A member holding 300,000 points with a four-night award already held over
    2026-09-08 to 2026-09-12, at a property whose allotment is never binding."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR-LMI",
        rate_category="TRANSIENT",
        name="Larkspur Meadows Inn",
        brand_code="LMI",
        market_tier="SELECT",
        program_fee_pct=0.04,
        rooms_count=85,
        trailing_12m_occupancy_pct=0.72,
        trailing_12m_adr_cents=19_000,
    )
    hotel_id = bundle["hotel"]["id"]
    fx.publish_standard_pricing(
        api,
        hotel_id,
        points_per_night=40_000,
        cash_copay_cents=0,
        min_tier_required="BASE",
        award_allotment_per_night=5,
    )
    member = fx.enroll_member(api)
    fx.grant_goodwill_points(
        api, member["id"], 100_000, reason="Legacy programme conversion balance"
    )
    fx.settled_purchase(api, member["id"], 200_000, channel="DIRECT_PURCHASE")
    member_headers = make_member_headers(member["id"])

    held = fx.book_award(
        api, member["id"], hotel_id, "2026-09-08", "2026-09-12", headers=member_headers
    )

    bundle["member"] = fx.read_member(api, member["id"])
    bundle["member_headers"] = member_headers
    bundle["held_award"] = held
    return bundle


def _ambergate_single_award_room(api):
    """One award room per night, one member holding it, and a second member funded
    and waiting. The fund baseline is captured before any booking."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR-AGC",
        rate_category="TRANSIENT",
        name="Ambergate Courtyard",
        brand_code="AGC",
        market_tier="SELECT",
        program_fee_pct=0.04,
        rooms_count=64,
        trailing_12m_occupancy_pct=0.70,
        trailing_12m_adr_cents=21_000,
    )
    hotel_id = bundle["hotel"]["id"]
    fx.publish_standard_pricing(
        api,
        hotel_id,
        points_per_night=40_000,
        cash_copay_cents=0,
        min_tier_required="BASE",
        award_allotment_per_night=1,
    )
    member_a = fx.enroll_member(api)
    fx.settled_purchase(api, member_a["id"], 100_000, channel="DIRECT_PURCHASE")
    member_b = fx.enroll_member(api)
    fx.grant_goodwill_points(
        api, member_b["id"], 100_000, reason="Elite status match courtesy balance"
    )

    baseline_fund = fx.read_fund(api)
    headers_a = make_member_headers(member_a["id"])
    headers_b = make_member_headers(member_b["id"])
    held = fx.book_award(
        api, member_a["id"], hotel_id, "2026-09-08", "2026-09-10", headers=headers_a
    )

    bundle["member_a"] = fx.read_member(api, member_a["id"])
    bundle["member_b"] = fx.read_member(api, member_b["id"])
    bundle["headers_a"] = headers_a
    bundle["headers_b"] = headers_b
    bundle["baseline_fund"] = baseline_fund
    bundle["held_award"] = held
    return bundle


# ----------------------------------------------------------------------
# The five-step peak price.
# ----------------------------------------------------------------------
class TestPeakAwardPriceEvaluationOrder:
    def test_the_gold_discount_is_floored_then_capped_at_three_thousand_points(
        self, api
    ):
        """A GOLD member at 70,000 points per night computes 3,500 of discount and is
        capped down to 3,000, leaving 67,000 chargeable per night.

        PRD: "First, the tier discount per night: the nightly price is multiplied by
        the member's tier percentage, which is zero for `BASE` and zero for `SILVER`,
        five percent for `GOLD` and ten percent for `PLATINUM`; that product is
        floored to whole points and then capped at 3,000 points."

        Design: Difficulty/combinatorial_formula/peak_award_price_evaluation_order_capped_discount_then_surcharge_then_floor
        """
        bundle = _dune_ridge_peak_only_program(api)
        assert_member(bundle["member"], elite_tier="GOLD", qualifying_nights=30)

        booking = fx.book_award(
            api,
            bundle["member"]["id"],
            bundle["hotel"]["id"],
            "2026-09-10",
            "2026-09-13",
            headers=bundle["member_headers"],
        )

        assert_redemption(booking, points_charged=271_350, nights=3)

    def test_the_resort_surcharge_rounds_up_after_the_discounted_gross(self, api):
        """Thirty-five percent of a 201,000-point gross is 70,350, added after the
        discount and before the per-night floor is even reachable.

        PRD: "Fourth, the peak surcharge: when the resolved season is `PEAK`, the
        gross is multiplied by the property's market surcharge — twenty-five percent
        for `URBAN`, thirty-five percent for `RESORT`, fifteen percent for `SELECT` —
        and that product is rounded **up** to whole points, never half up; when the
        season is `STANDARD` the surcharge is zero."

        Design: Difficulty/combinatorial_formula/peak_award_price_evaluation_order_capped_discount_then_surcharge_then_floor
        """
        bundle = _dune_ridge_peak_only_program(api)

        booking = fx.book_award(
            api,
            bundle["member"]["id"],
            bundle["hotel"]["id"],
            "2026-09-10",
            "2026-09-13",
            headers=bundle["member_headers"],
        )

        assert booking["points_charged"] == 201_000 + 70_350, (
            "expected a 201000-point gross plus a 70350-point resort surcharge, got "
            f"{booking['points_charged']}"
        )
        assert_redemption(booking, season="PEAK")

    def test_the_winning_peak_window_is_snapshotted_onto_the_booking(self, api):
        """Selection copies the season, the nightly price and the allotment onto the
        booking, and multiplies the nightly copay by the night count.

        PRD: "The winning row is then snapshotted onto the booking: its `season`
        becomes the booking's `season`, its `points_per_night` becomes
        `points_per_night_applied`, its `award_allotment_per_night` becomes
        `award_allotment_applied`, and its `cash_copay_cents` multiplied by `nights`
        becomes the booking's `cash_copay_cents` — a figure the property collects
        directly from the guest and the programme never touches."

        Design: Difficulty/combinatorial_formula/peak_award_price_evaluation_order_capped_discount_then_surcharge_then_floor
        """
        bundle = _dune_ridge_peak_only_program(api)

        booking = fx.book_award(
            api,
            bundle["member"]["id"],
            bundle["hotel"]["id"],
            "2026-09-10",
            "2026-09-13",
            headers=bundle["member_headers"],
        )

        assert_redemption(
            booking,
            season="PEAK",
            points_per_night=70_000,
            award_allotment=3,
            cash_copay_cents=6_000,
            nights=3,
        )

    def test_the_peak_debit_is_one_redeem_entry_for_the_whole_price(self, api):
        """The debit is a single negative entry scoped to the booking, and the
        member's balance falls by exactly that figure.

        PRD: "A `REDEEM` ledger entry is written carrying the negation of
        `points_charged` with `source_redemption_id` naming the booking, the member's
        `point_balance` falls by that amount, the property's `version` increments by
        one, and the fund's `point_liability_cents`, `solvency_ratio` and `status`
        are recomputed."

        Design: Difficulty/combinatorial_formula/peak_award_price_evaluation_order_capped_discount_then_surcharge_then_floor
        """
        bundle = _dune_ridge_peak_only_program(api)

        booking = fx.book_award(
            api,
            bundle["member"]["id"],
            bundle["hotel"]["id"],
            "2026-09-10",
            "2026-09-13",
            headers=bundle["member_headers"],
        )

        scoped = fx.ledger_for_redemption(api, booking["id"])
        assert len(scoped) == 1, f"expected one debit entry, saw {len(scoped)}"
        assert_ledger_entry(
            scoped[0],
            entry_type="REDEEM",
            points=-271_350,
            member_id=bundle["member"]["id"],
            source_redemption_id=booking["id"],
        )
        assert_member(
            fx.read_member(api, bundle["member"]["id"]),
            point_balance=29_884,
            elite_tier="GOLD",
        )


# ----------------------------------------------------------------------
# The member's own award calendar is half-open.
# ----------------------------------------------------------------------
class TestMemberAwardCalendarIsHalfOpen:
    def test_one_shared_night_refuses_the_overlapping_award(self, api):
        """An arrival inside a held booking's interval shares a night, and one shared
        night is enough.

        PRD: "Then the member must hold no other booking in `HELD`, `CONFIRMED` or
        `STAYED` at any property whose half-open interval intersects this one, else
        `ERR_MEMBER_REDEMPTION_OVERLAP`; because the test is strictly-less-than on
        both sides, a checkout on one date and a check-in the same date at a
        different property do not intersect, but one member cannot occupy two
        properties on the same night."

        Design: Difficulty/resource_temporal_overlap/member_award_stays_may_touch_at_the_checkout_date_but_not_share_a_night
        """
        bundle = _larkspur_with_one_held_award(api)
        member_id = bundle["member"]["id"]

        response = api.create_redemption(
            fac.create_redemption_payload(
                member_id,
                bundle["hotel"]["id"],
                fx.hotel_version(api, bundle["hotel"]["id"]),
                checkin_date="2026-09-11",
                checkout_date="2026-09-13",
            ),
            bundle["member_headers"],
        )

        validate_error(response, ApiErrorId.ERR_MEMBER_REDEMPTION_OVERLAP.value)

    def test_the_refused_overlap_is_geometric_and_moves_no_points(self, api):
        """The member could afford the second award - 140,000 points against a price
        of 80,000 - so the refusal writes nothing to the ledger.

        PRD: "Then the member's `point_balance` must be at least the computed
        `points_charged`, else `ERR_INSUFFICIENT_POINTS`."

        Design: Difficulty/resource_temporal_overlap/member_award_stays_may_touch_at_the_checkout_date_but_not_share_a_night
        """
        bundle = _larkspur_with_one_held_award(api)
        member_id = bundle["member"]["id"]
        assert_redemption(bundle["held_award"], points_charged=160_000, nights=4)
        assert_member(fx.read_member(api, member_id), point_balance=140_000)

        api.create_redemption(
            fac.create_redemption_payload(
                member_id,
                bundle["hotel"]["id"],
                fx.hotel_version(api, bundle["hotel"]["id"]),
                checkin_date="2026-09-11",
                checkout_date="2026-09-13",
            ),
            bundle["member_headers"],
        )

        assert_member(fx.read_member(api, member_id), point_balance=140_000)
        assert count_entries_of_type(fx.ledger_of_member(api, member_id), "REDEEM") == 1, (
            "a refused booking writes no debit"
        )

    def test_an_arrival_on_the_previous_departure_date_shares_no_night(self, api):
        """The interval is half-open, so the departure date of the held booking is
        available as the arrival date of the next one.

        PRD: "The server computes `nights` as the number of days from `checkin_date`
        to `checkout_date`, an interval that is half-open — the arrival night is
        occupied and the departure night is not."

        Design: Difficulty/resource_temporal_overlap/member_award_stays_may_touch_at_the_checkout_date_but_not_share_a_night
        """
        bundle = _larkspur_with_one_held_award(api)
        member_id = bundle["member"]["id"]

        response = api.create_redemption(
            fac.create_redemption_payload(
                member_id,
                bundle["hotel"]["id"],
                fx.hotel_version(api, bundle["hotel"]["id"]),
                checkin_date="2026-09-12",
                checkout_date="2026-09-14",
            ),
            bundle["member_headers"],
        )

        touching = validate_success(response, 201)
        assert_redemption(
            touching, fulfillment_status="HELD", points_charged=80_000, nights=2
        )
        assert_redemption(
            fx.read_redemption(api, bundle["held_award"]["id"]),
            fulfillment_status="HELD",
            points_charged=160_000,
        )
        assert_member(fx.read_member(api, member_id), point_balance=60_000)
        assert count_entries_of_type(fx.ledger_of_member(api, member_id), "REDEEM") == 2, (
            "two accepted bookings write exactly two debits"
        )

    def test_a_four_night_standard_award_earns_no_free_night(self, api):
        """The free night needs five nights; a four-night stay is charged for all
        four.

        PRD: "Second, the free night: when the resolved season is `STANDARD` and the
        booking runs five nights or more, the chargeable night count is one less than
        `nights`; otherwise every night is chargeable."

        Design: Difficulty/resource_temporal_overlap/member_award_stays_may_touch_at_the_checkout_date_but_not_share_a_night
        """
        bundle = _larkspur_with_one_held_award(api)

        assert_redemption(
            fx.read_redemption(api, bundle["held_award"]["id"]),
            season="STANDARD",
            nights=4,
            points_charged=160_000,
        )


# ----------------------------------------------------------------------
# Cancellation gives back the points and the room.
# ----------------------------------------------------------------------
class TestAwardCancellationCompensatesPointsAndInventory:
    def test_the_last_award_room_refuses_a_second_member(self, api):
        """With one award room per night, the held booking occupies both nights and a
        second member is refused on the per-night count.

        PRD: "Then award inventory: for every night of the half-open interval, count
        the property's bookings in `HELD`, `CONFIRMED` or `STAYED` that occupy that
        night, and if adding this booking would take that count past
        `award_allotment_applied` on any single night, refuse with
        `ERR_AWARD_INVENTORY_UNAVAILABLE` — the test is a per-date count against a
        capacity, not a pairwise clash, and `CANCELLED` and `NO_SHOW` bookings
        release their nights and are excluded from the count."

        Design: Difficulty/compensating_invariant/award_cancellation_restores_member_points_and_releases_the_last_award_room
        """
        bundle = _ambergate_single_award_room(api)

        response = api.create_redemption(
            fac.create_redemption_payload(
                bundle["member_b"]["id"],
                bundle["hotel"]["id"],
                fx.hotel_version(api, bundle["hotel"]["id"]),
                checkin_date="2026-09-08",
                checkout_date="2026-09-10",
            ),
            bundle["headers_b"],
        )

        validate_error(response, ApiErrorId.ERR_AWARD_INVENTORY_UNAVAILABLE.value)

    def test_cancellation_reverses_exactly_what_was_debited(self, api):
        """One positive reversal for the full debited price, pointing at the debit it
        compensates, leaves the booking's ledger scope summing to zero.

        PRD: "A `REVERSAL` ledger entry is written carrying positive `points_charged`
        — exactly what was debited, never more and never less — with
        `source_redemption_id` naming the booking and `reversal_of_entry_id` naming
        the original `REDEEM` entry; the member's `point_balance` rises by that
        amount; the nights are released from award inventory; the booking's `version`
        increments; and the fund's `outstanding_points`, `point_liability_cents`,
        `solvency_ratio` and `status` are recomputed."

        Design: Difficulty/compensating_invariant/award_cancellation_restores_member_points_and_releases_the_last_award_room
        """
        bundle = _ambergate_single_award_room(api)
        award_id = bundle["held_award"]["id"]
        debit = entries_of_type(fx.ledger_for_redemption(api, award_id), "REDEEM")[0]

        cancelled = fx.cancel_award(
            api,
            award_id,
            reason="Trip cancelled by the guest",
            headers=bundle["headers_a"],
        )

        assert_redemption(
            cancelled,
            fulfillment_status="CANCELLED",
            cancel_reason="Trip cancelled by the guest",
        )
        reversals = entries_of_type(fx.ledger_for_redemption(api, award_id), "REVERSAL")
        assert len(reversals) == 1, f"expected one reversal, saw {len(reversals)}"
        assert_ledger_entry(
            reversals[0],
            entry_type="REVERSAL",
            points=80_000,
            reversal_of_entry_id=debit["id"],
            source_redemption_id=award_id,
        )
        assert_scoped_ledger_sum_is_zero(fx.ledger_for_redemption(api, award_id))
        assert_member(fx.read_member(api, bundle["member_a"]["id"]), point_balance=100_000)

    def test_cancellation_returns_the_fund_to_its_baseline_and_moves_no_cash(self, api):
        """Liability and solvency come back to the exact figures they held before the
        booking, and programme cash never moved at all.

        PRD: "The `solvency_ratio` is `cash_balance_cents` divided by
        `point_liability_cents`, rounded half up to four decimal places, and is
        pinned to exactly 999.0000 when the liability is zero rather than dividing by
        zero — so a programme with an empty ledger reads `HEALTHY`, not impaired."

        Design: Difficulty/compensating_invariant/award_cancellation_restores_member_points_and_releases_the_last_award_room
        """
        bundle = _ambergate_single_award_room(api)
        assert_fund(
            bundle["baseline_fund"],
            cash_cents=110_000,
            outstanding_points=200_000,
            liability_cents=96_000,
            solvency_ratio=1.1458,
            status="HEALTHY",
        )

        fx.cancel_award(api, bundle["held_award"]["id"], headers=bundle["headers_a"])

        assert_fund(
            fx.read_fund(api),
            cash_cents=110_000,
            outstanding_points=200_000,
            liability_cents=96_000,
            solvency_ratio=1.1458,
            status="HEALTHY",
        )

    def test_the_released_award_night_is_bookable_again(self, api):
        """The compensation covers inventory too: the member refused moments earlier
        gets the room.

        PRD: "The nights are nevertheless released, so they stop counting toward
        award inventory for later bookings."

        Design: Difficulty/compensating_invariant/award_cancellation_restores_member_points_and_releases_the_last_award_room
        """
        bundle = _ambergate_single_award_room(api)
        fx.cancel_award(api, bundle["held_award"]["id"], headers=bundle["headers_a"])

        response = api.create_redemption(
            fac.create_redemption_payload(
                bundle["member_b"]["id"],
                bundle["hotel"]["id"],
                fx.hotel_version(api, bundle["hotel"]["id"]),
                checkin_date="2026-09-08",
                checkout_date="2026-09-10",
            ),
            bundle["headers_b"],
        )

        rebooked = validate_success(response, 201)
        assert_redemption(rebooked, fulfillment_status="HELD", points_charged=80_000)
        assert_member(fx.read_member(api, bundle["member_b"]["id"]), point_balance=20_000)
        assert_ledger_sum_equals(
            fx.ledger_for_redemption(api, rebooked["id"]), -80_000
        )
