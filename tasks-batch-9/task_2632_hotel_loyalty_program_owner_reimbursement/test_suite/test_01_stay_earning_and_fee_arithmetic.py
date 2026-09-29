"""Paid-stay earning, the two bonus readings, and the programme fee ledger.

Every test here starts from an empty database and builds its property, its member
and its stay history through the programme's own endpoints.
"""

import pytest

from test_helpers import (
    assert_benefit_types,
    assert_hotel,
    assert_ledger_sum_equals,
    assert_member,
    assert_no_entry_of_type,
    assert_stay,
    count_entries_of_type,
    entries_of_type,
    fixtures as fx,
    make_member_headers,
)


# ----------------------------------------------------------------------
# Scenario builders - each composes test_helpers fixtures for one instance.
# ----------------------------------------------------------------------
def _harborline_with_a_disputed_high_revenue_stay(api):
    """A property whose guest earned a large base award while still at BASE, then
    climbed to PLATINUM on a second, much longer stay, then disputed the first.

    Returns the property bundle plus ``member``, ``first_stay`` and ``long_stay``.
    """
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR-HRB",
        rate_category="TRANSIENT",
        name="Harborline Central",
        brand_code="HRB",
        market_tier="URBAN",
        program_fee_pct=0.0475,
        rooms_count=180,
        trailing_12m_occupancy_pct=0.81,
        trailing_12m_adr_cents=42_000,
    )
    hotel_id = bundle["hotel"]["id"]
    rate_plan_id = bundle["rate_plan"]["id"]
    member = fx.enroll_member(api)

    first_stay = fx.posted_stay(
        api, hotel_id, member["id"], rate_plan_id, "2026-07-01", "2026-07-03", 1_234_500
    )
    long_stay = fx.posted_stay(
        api, hotel_id, member["id"], rate_plan_id, "2026-05-01", "2026-06-20", 12_345
    )
    fx.dispute_stay(
        api,
        first_stay["id"],
        reason="Guest challenged the folio rate for the July arrival",
        headers=make_member_headers(member["id"]),
    )

    bundle["member"] = member
    bundle["first_stay"] = first_stay
    bundle["long_stay"] = long_stay
    return bundle


def _kestrel_with_two_of_three_identical_nights_posted(api):
    """Three identically priced one-night stays at a property whose fee rate makes
    the per-stay rounding visible; the first two are already posted."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR-KIM",
        rate_category="TRANSIENT",
        name="Kestrel Inn Midtown",
        brand_code="KIM",
        market_tier="SELECT",
        program_fee_pct=0.0475,
        rooms_count=96,
        trailing_12m_occupancy_pct=0.74,
        trailing_12m_adr_cents=17_500,
    )
    hotel_id = bundle["hotel"]["id"]
    rate_plan_id = bundle["rate_plan"]["id"]
    member = fx.enroll_member(api)

    posted = [
        fx.posted_stay(
            api, hotel_id, member["id"], rate_plan_id, checkin, checkout, 12_345
        )
        for checkin, checkout in (("2026-07-01", "2026-07-02"), ("2026-07-05", "2026-07-06"))
    ]
    third = fx.capture_stay(
        api, hotel_id, member["id"], rate_plan_id, "2026-07-10", "2026-07-11", 12_345
    )

    bundle["member"] = member
    bundle["posted_stays"] = posted
    bundle["third_stay"] = third
    return bundle


def _northgate_one_night_short_of_platinum(api):
    """A member holding exactly 49 qualifying nights, with a fiftieth night
    captured at GOLD and waiting to be posted."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR-NGT",
        rate_category="TRANSIENT",
        name="Northgate Terrace",
        brand_code="NGT",
        market_tier="SELECT",
        program_fee_pct=0.04,
        rooms_count=110,
        trailing_12m_occupancy_pct=0.79,
        trailing_12m_adr_cents=22_000,
    )
    hotel_id = bundle["hotel"]["id"]
    rate_plan_id = bundle["rate_plan"]["id"]
    member = fx.enroll_member(api)

    long_stay = fx.posted_stay(
        api, hotel_id, member["id"], rate_plan_id, "2026-05-01", "2026-06-19", 490_000
    )
    fiftieth = fx.capture_stay(
        api, hotel_id, member["id"], rate_plan_id, "2026-07-01", "2026-07-02", 12_345
    )

    bundle["member"] = member
    bundle["long_stay"] = long_stay
    bundle["fiftieth_night"] = fiftieth
    return bundle


# ----------------------------------------------------------------------
# The two bonus readings: provisional at posting, final at adjustment.
# ----------------------------------------------------------------------
class TestBonusIsPricedTwiceOnTheSameStay:
    def test_posting_keys_the_bonus_on_the_check_in_tier_snapshot(self, api):
        """A stay posted while the guest stood at BASE earns no elite bonus at all,
        however far the guest climbs afterwards.

        PRD: "At posting time the multiplier is keyed on the stay's own
        `tier_at_checkin` snapshot — the tier the guest held when the stay row was
        created — so any retroactive tier movement between arrival and posting is
        deliberately ignored here."

        Design: Difficulty/dual_variant_calc/stay_bonus_provisional_tier_at_checkin_vs_final_tier_at_adjustment
        """
        bundle = _harborline_with_a_disputed_high_revenue_stay(api)
        first_stay = fx.read_stay(api, bundle["first_stay"]["id"])

        assert first_stay["tier_at_checkin"] == "BASE", (
            "the guest held BASE when the July stay row was created"
        )
        assert_stay(
            first_stay,
            base_points=123_450,
            bonus_points=0,
            bonus_multiplier=0.00,
            fee_cents=58_639,
        )
        assert_no_entry_of_type(fx.ledger_for_stay(api, first_stay["id"]), "EARN_BONUS")

    def test_adjustment_keys_the_bonus_on_the_tier_the_member_holds_now(self, api):
        """Settling the dispute reprices the same stay data under the member's
        current PLATINUM standing, which is the deliberate divergence between the
        two bonus variants.

        PRD: "This is the deliberate divergence between the two bonus variants —
        identical stay data yields two different bonus figures."

        Design: Difficulty/dual_variant_calc/stay_bonus_provisional_tier_at_checkin_vs_final_tier_at_adjustment
        """
        bundle = _harborline_with_a_disputed_high_revenue_stay(api)

        adjusted = fx.adjust_stay(api, bundle["first_stay"]["id"])

        assert_stay(
            adjusted,
            status="ADJUSTED",
            base_points=123_450,
            bonus_points=92_587,
            bonus_multiplier=0.75,
            room_revenue_cents=1_234_500,
        )
        assert adjusted["tier_at_checkin"] == "BASE", (
            "the check-in snapshot is history and is not rewritten by the adjustment"
        )

    def test_the_adjustment_writes_the_bonus_as_a_delta_not_as_an_edit(self, api):
        """The correction arrives as one additional bonus entry for the difference,
        so the stay's own ledger scope sums to the full recomputed award.

        PRD: "An additional `EARN_BONUS` entry is written whose `points` is the new
        bonus award minus the old bonus award, again only when that difference is
        non-zero."

        Design: Difficulty/dual_variant_calc/stay_bonus_provisional_tier_at_checkin_vs_final_tier_at_adjustment
        """
        bundle = _harborline_with_a_disputed_high_revenue_stay(api)
        first_stay_id = bundle["first_stay"]["id"]

        fx.adjust_stay(api, first_stay_id)

        scoped = fx.ledger_for_stay(api, first_stay_id)
        base_entries = entries_of_type(scoped, "EARN_BASE")
        bonus_entries = entries_of_type(scoped, "EARN_BONUS")
        assert len(base_entries) == 1, (
            f"an unchanged base award writes no delta entry, saw {len(base_entries)}"
        )
        assert len(bonus_entries) == 1, (
            f"expected exactly one bonus delta entry, saw {len(bonus_entries)}"
        )
        assert bonus_entries[0]["points"] == 92_587, (
            f"expected a bonus delta of 92587, got {bonus_entries[0]['points']}"
        )
        assert_no_entry_of_type(scoped, "REVERSAL")
        assert_ledger_sum_equals(scoped, 216_037)

    def test_adjustment_leaves_the_tier_count_and_the_fee_ledger_where_they_stood(
        self, api
    ):
        """`ADJUSTED` sits outside the tier-counting set, so the repriced stay's own
        nights stay out of the count while the long stay alone holds PLATINUM.

        PRD: "and note that `ADJUSTED` also sits outside the tier-counting set, so
        the stay's nights do not return to the count."

        Design: Difficulty/dual_variant_calc/stay_bonus_provisional_tier_at_checkin_vs_final_tier_at_adjustment
        """
        bundle = _harborline_with_a_disputed_high_revenue_stay(api)

        fx.adjust_stay(api, bundle["first_stay"]["id"])

        member = fx.read_member(api, bundle["member"]["id"])
        assert_member(
            member,
            elite_tier="PLATINUM",
            qualifying_nights=50,
            point_balance=217_271,
        )
        assert_hotel(
            fx.read_hotel(api, bundle["hotel"]["id"]),
            status="ACTIVE",
            fee_ledger_cents=59_225,
        )


# ----------------------------------------------------------------------
# The programme fee rounds per stay, then sums.
# ----------------------------------------------------------------------
class TestProgrammeFeeRoundsPerStayBeforeSumming:
    def test_each_stay_rounds_its_own_fee_half_up_to_the_cent(self, api):
        """Two identical one-night stays each carry the same rounded fee, and the
        ledger is the sum of those rounded figures.

        PRD: "Per stay, the fee is the stay's `room_revenue_cents` multiplied by the
        property's `program_fee_pct`, rounded half up to the whole cent, and stored
        on the stay as `program_fee_assessed_cents`; if the rate plan has
        `program_fee_eligible` false or `is_qualifying` false, that figure is 0."

        Design: Difficulty/combinatorial_formula/program_fee_rounds_per_stay_before_summing_not_after
        """
        bundle = _kestrel_with_two_of_three_identical_nights_posted(api)

        for stay in bundle["posted_stays"]:
            assert_stay(
                fx.read_stay(api, stay["id"]),
                status="POSTED_QUALIFYING",
                fee_cents=586,
                base_points=1_234,
                nights=1,
            )
        assert_hotel(
            fx.read_hotel(api, bundle["hotel"]["id"]),
            status="ACTIVE",
            fee_ledger_cents=1_172,
        )

    def test_the_third_posting_sums_the_already_rounded_figures(self, api):
        """Three stays of 12,345 cents at 0.0475 land the ledger on 1,758 cents -
        the figure that summing revenue first and rounding once would miss.

        PRD: "Three stays of 12,345 cents each at a fee rate of 0.0475 therefore
        produce 586 cents apiece and a ledger of 1,758 cents; summing the revenue
        first and applying the rate once would give 1,759 and is explicitly not the
        rule."

        Design: Difficulty/combinatorial_formula/program_fee_rounds_per_stay_before_summing_not_after
        """
        bundle = _kestrel_with_two_of_three_identical_nights_posted(api)

        third = fx.post_stay(api, bundle["third_stay"]["id"])

        assert_stay(third, status="POSTED_QUALIFYING", fee_cents=586)
        hotel = fx.read_hotel(api, bundle["hotel"]["id"])
        assert hotel["fee_ledger_balance_cents"] == 1_758, (
            "expected 1758 from three already-rounded 586-cent fees, got "
            f"{hotel['fee_ledger_balance_cents']}"
        )

    def test_three_short_stays_earn_a_floored_base_award_and_no_elite_standing(
        self, api
    ):
        """The base award floors per stay too, and three nights leaves the member at
        BASE with the property comfortably solvent.

        PRD: "The rounding never goes up, so a stay of 12,345 cents on a rate plan
        earning 10 points per dollar awards 1,234 points, not 1,235."

        Design: Difficulty/combinatorial_formula/program_fee_rounds_per_stay_before_summing_not_after
        """
        bundle = _kestrel_with_two_of_three_identical_nights_posted(api)

        fx.post_stay(api, bundle["third_stay"]["id"])

        assert_member(
            fx.read_member(api, bundle["member"]["id"]),
            elite_tier="BASE",
            qualifying_nights=3,
            qualifying_revenue_cents=37_035,
            point_balance=3_702,
            lifetime_points_earned=3_702,
        )
        assert_hotel(fx.read_hotel(api, bundle["hotel"]["id"]), status="ACTIVE")


# ----------------------------------------------------------------------
# The fiftieth qualifying night.
# ----------------------------------------------------------------------
class TestFiftiethQualifyingNightFlipsPlatinum:
    def test_exactly_fifty_qualifying_nights_reads_platinum(self, api):
        """Forty-nine nights is GOLD; the fiftieth is the inclusive boundary that
        reads PLATINUM.

        PRD: "Every comparison is inclusive of its threshold, so exactly 50 nights
        is `PLATINUM` while 49 nights is `GOLD`."

        Design: Difficulty/boundary_precision_check/fiftieth_qualifying_night_flips_platinum_while_the_same_post_floors_1234_and_pays_a_gold_bonus
        """
        bundle = _northgate_one_night_short_of_platinum(api)
        before = fx.read_member(api, bundle["member"]["id"])
        assert_member(before, elite_tier="GOLD", qualifying_nights=49)

        fx.post_stay(api, bundle["fiftieth_night"]["id"])

        assert_member(
            fx.read_member(api, bundle["member"]["id"]),
            elite_tier="PLATINUM",
            qualifying_nights=50,
        )

    def test_the_same_posting_still_pays_the_gold_bonus_it_arrived_with(self, api):
        """The tier that moves is the member's; the bonus on this stay is priced on
        the GOLD snapshot the stay row carried in.

        PRD: "Elite bonus earning follows: the multiplier is 0.00 at `BASE`, 0.20 at
        `SILVER`, 0.50 at `GOLD` and 0.75 at `PLATINUM`, and `bonus_points_awarded`
        is `base_points_awarded` multiplied by that multiplier, again rounded
        **down** to a whole point"

        Design: Difficulty/boundary_precision_check/fiftieth_qualifying_night_flips_platinum_while_the_same_post_floors_1234_and_pays_a_gold_bonus
        """
        bundle = _northgate_one_night_short_of_platinum(api)

        posted = fx.post_stay(api, bundle["fiftieth_night"]["id"])

        assert_stay(
            posted,
            status="POSTED_QUALIFYING",
            tier_at_checkin="GOLD",
            base_points=1_234,
            bonus_points=617,
            bonus_multiplier=0.50,
            fee_cents=494,
            nights=1,
        )
        assert_member(
            fx.read_member(api, bundle["member"]["id"]),
            point_balance=50_851,
            lifetime_points_earned=50_851,
        )
        assert_hotel(
            fx.read_hotel(api, bundle["hotel"]["id"]),
            status="ACTIVE",
            fee_ledger_cents=20_094,
        )

    def test_the_gold_snapshot_owes_an_upgrade_and_breakfast_but_no_late_checkout(
        self, api
    ):
        """The entitlement matrix reads the stay's own snapshot, so late checkout -
        a platinum-only benefit - is not synthesised by the night that earned
        platinum.

        PRD: "The entitlement matrix reads the stay's `tier_at_checkin`: `UPGRADE`
        is owed at `SILVER`, `GOLD` and `PLATINUM`; `BREAKFAST` is owed at `GOLD`
        and `PLATINUM`; `LATE_CHECKOUT` is owed at `PLATINUM` only; and a `BASE`
        guest is entitled to nothing at all."

        Design: Difficulty/boundary_precision_check/fiftieth_qualifying_night_flips_platinum_while_the_same_post_floors_1234_and_pays_a_gold_bonus
        """
        bundle = _northgate_one_night_short_of_platinum(api)

        fx.post_stay(api, bundle["fiftieth_night"]["id"])

        obligations = fx.obligations_for_stay(api, bundle["fiftieth_night"]["id"])
        assert_benefit_types(obligations, ["UPGRADE", "BREAKFAST"])
        assert fx.obligations_for_stay(api, bundle["long_stay"]["id"]) == [], (
            "the 49-night stay was captured at BASE, which is entitled to nothing"
        )


@pytest.mark.parametrize(
    "posted_index",
    [0, 1],
    ids=["first_night", "second_night"],
)
def test_each_posted_night_carries_its_own_rounded_fee(api, posted_index):
    """Both already-posted nights carry the same independently rounded fee, which is
    what makes the sum of rounded figures observable.

    PRD: "The rounding order is pinned and it matters: round each stay's fee to the
    cent first, then add the rounded figures."

    Design: Difficulty/combinatorial_formula/program_fee_rounds_per_stay_before_summing_not_after
    """
    bundle = _kestrel_with_two_of_three_identical_nights_posted(api)
    stay = fx.read_stay(api, bundle["posted_stays"][posted_index]["id"])
    assert_stay(stay, fee_cents=586)
    assert count_entries_of_type(fx.ledger_for_stay(api, stay["id"]), "EARN_BASE") == 1
