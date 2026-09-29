"""What the rate category alone decides, what room revenue alone earns and is
charged for, what each benefit type recovers, and which stays a property's fee
ledger is allowed to count."""

from test_helpers import (
    assert_all_deliveries_status,
    assert_delivery,
    assert_entitlement_for_tier,
    assert_hotel,
    assert_member,
    assert_non_qualifying_stay_is_inert,
    assert_rate_plan_derivation,
    assert_stay,
    collect_all,
    factories as fac,
    fixtures as fx,
    make_admin_headers,
    make_auditor_headers,
    make_hotel_owner_headers,
    validate_success,
)


# ----------------------------------------------------------------------
# Scenario builders
# ----------------------------------------------------------------------
def _ratecard_hotel_carrying_all_six_categories(api):
    """One property with a rate plan of every category the programme recognises,
    filed before activation because registration does not wait for it."""
    hotel = fx.create_onboarding_hotel(
        api,
        name="Ratecard Hotel",
        brand_code="RCH",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=100,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    hotel_id = hotel["id"]
    owner_headers = make_hotel_owner_headers(hotel_id)
    plans = {
        "TRANSIENT": fx.add_rate_plan(
            api, hotel_id, rate_code="BAR", rate_category="TRANSIENT"
        ),
        "CORPORATE_NEGOTIATED": validate_success(
            api.create_rate_plan(
                hotel_id,
                fac.create_rate_plan_payload(
                    rate_code="CORP", rate_category="CORPORATE_NEGOTIATED"
                ),
                owner_headers,
            ),
            201,
        ),
        "GROUP": fx.add_rate_plan(api, hotel_id, rate_code="GRP", rate_category="GROUP"),
        "OPAQUE_WHOLESALE": fx.add_rate_plan(
            api, hotel_id, rate_code="OPQ", rate_category="OPAQUE_WHOLESALE"
        ),
        "EMPLOYEE_COMP": fx.add_rate_plan(
            api, hotel_id, rate_code="COMP", rate_category="EMPLOYEE_COMP"
        ),
        "AWARD": fx.add_rate_plan(api, hotel_id, rate_code="AWD", rate_category="AWARD"),
    }

    return {"hotel": hotel, "plans": plans}


def _groupblock_stay_posted_with_heavy_incidentals(api):
    """A ten-night group stay of 12,345 cents of room revenue and 50,000 cents of
    incidentals, posted at a property charging five percent."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="GRP",
        rate_category="GROUP",
        name="Groupblock Hotel",
        brand_code="GBH",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=220,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    hotel_id = bundle["hotel"]["id"]
    member = fx.enroll_member(
        api,
        email="gb1@example.com",
        full_name="Tobias Reuter",
        enrollment_date="2026-01-11",
    )
    stay = fx.capture_stay(
        api,
        hotel_id,
        member["id"],
        bundle["rate_plan"]["id"],
        "2026-06-01",
        "2026-06-11",
        12_345,
        incidental_revenue_cents=50_000,
        headers=bundle["owner_headers"],
    )
    posted = fx.post_stay(api, stay["id"], headers=bundle["owner_headers"])

    bundle["member"] = member
    bundle["captured"] = stay
    bundle["stay"] = posted
    return bundle


def _recovery_regent_with_three_platinum_obligations(api):
    """A property with an 80,000-cent daily rate, a guest driven to the top tier by a
    fifty-night stay, and a later three-night stay owing all three benefits."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Recovery Regent",
        brand_code="RRG",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=240,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=80_000,
    )
    hotel_id = bundle["hotel"]["id"]
    member = fx.enroll_member(
        api,
        email="rr1@example.com",
        full_name="Selma Aune",
        enrollment_date="2026-01-04",
    )
    fx.posted_stay(
        api,
        hotel_id,
        member["id"],
        bundle["rate_plan"]["id"],
        "2026-06-01",
        "2026-07-21",
        500_000,
    )
    stay = fx.posted_stay(
        api,
        hotel_id,
        member["id"],
        bundle["rate_plan"]["id"],
        "2026-07-22",
        "2026-07-25",
        30_000,
    )

    bundle["member"] = fx.read_member(api, member["id"])
    bundle["stay"] = stay
    bundle["obligations"] = {
        benefit_type: fx.obligation_of_type(api, stay["id"], benefit_type)
        for benefit_type in ("UPGRADE", "BREAKFAST", "LATE_CHECKOUT")
    }
    return bundle


def _ledger_alpha_and_bravo_with_five_stays(api):
    """Two properties on different fee rates, and five stays spread across them in
    four different statuses."""
    alpha = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Ledger Alpha",
        brand_code="LGA",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=100,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    alpha_id = alpha["hotel"]["id"]
    alpha_opaque = fx.add_rate_plan(
        api, alpha_id, rate_code="OPQ", rate_category="OPAQUE_WHOLESALE"
    )
    bravo = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Ledger Bravo",
        brand_code="LGB",
        market_tier="RESORT",
        program_fee_pct=0.10,
        rooms_count=80,
        trailing_12m_occupancy_pct=0.78,
        trailing_12m_adr_cents=40_000,
    )
    bravo_id = bravo["hotel"]["id"]
    member = fx.enroll_member(
        api,
        email="lg1@example.com",
        full_name="Aleksi Rinne",
        enrollment_date="2026-01-16",
    )
    member_id = member["id"]

    unposted = fx.capture_stay(
        api, alpha_id, member_id, alpha["rate_plan"]["id"], "2026-06-01", "2026-06-03", 100_000
    )
    qualifying = fx.posted_stay(
        api, alpha_id, member_id, alpha["rate_plan"]["id"], "2026-06-05", "2026-06-07", 12_345
    )
    opaque = fx.posted_stay(
        api, alpha_id, member_id, alpha_opaque["id"], "2026-06-10", "2026-06-12", 200_000
    )
    voided_source = fx.capture_stay(
        api, alpha_id, member_id, alpha["rate_plan"]["id"], "2026-06-15", "2026-06-17", 300_000
    )
    voided = fx.void_stay(api, voided_source["id"], reason="Duplicate folio.")
    other_property = fx.posted_stay(
        api, bravo_id, member_id, bravo["rate_plan"]["id"], "2026-06-20", "2026-06-22", 50_000
    )

    return {
        "alpha": alpha["hotel"],
        "bravo": bravo["hotel"],
        "member": member,
        "unposted": unposted,
        "qualifying": qualifying,
        "opaque": opaque,
        "voided": voided,
        "other_property": other_property,
    }


# ----------------------------------------------------------------------
# One category decides four fields.
# ----------------------------------------------------------------------
class TestRateCategoryTableMapsSixCategoriesToFourFlags:
    def test_the_two_elite_bearing_categories_earn_ten_and_eight(self, api):
        """Transient and corporate-negotiated business sits inside every one of the
        three sets and earns the two highest rates.

        PRD: "The `base_earn_rate_per_dollar` — points earned per whole dollar of room
        revenue — is 10 for `TRANSIENT`, 8 for `CORPORATE_NEGOTIATED`, 6 for `GROUP`,
        and 0 for each of `OPAQUE_WHOLESALE`, `EMPLOYEE_COMP` and `AWARD`."

        Design: Corner/calculations/rate_category_table_maps_six_categories_to_four_derived_flags
        """
        bundle = _ratecard_hotel_carrying_all_six_categories(api)

        transient = bundle["plans"]["TRANSIENT"]
        corporate = bundle["plans"]["CORPORATE_NEGOTIATED"]
        assert transient["base_earn_rate_per_dollar"] == 10, (
            f"TRANSIENT earns 10 per dollar, got {transient['base_earn_rate_per_dollar']}"
        )
        assert corporate["base_earn_rate_per_dollar"] == 8, (
            f"CORPORATE_NEGOTIATED earns 8 per dollar, got "
            f"{corporate['base_earn_rate_per_dollar']}"
        )
        for plan in (transient, corporate):
            assert_rate_plan_derivation(plan)

    def test_group_business_earns_and_pays_a_fee_yet_lifts_no_tier(self, api):
        """Group is the one category that is qualifying and fee-bearing while sitting
        outside the elite set, which is exactly why the two flags are separate.

        PRD: "The flag `counts_toward_elite` is true for only `TRANSIENT` and
        `CORPORATE_NEGOTIATED`: group business earns points and is fee-assessed, but
        never accrues elite nights, and that asymmetry is the whole reason
        `counts_toward_elite` exists as a flag separate from `is_qualifying`."

        Design: Corner/calculations/rate_category_table_maps_six_categories_to_four_derived_flags
        """
        bundle = _ratecard_hotel_carrying_all_six_categories(api)

        group = bundle["plans"]["GROUP"]
        assert group["base_earn_rate_per_dollar"] == 6, (
            f"GROUP earns 6 per dollar, got {group['base_earn_rate_per_dollar']}"
        )
        assert group["is_qualifying"] is True, "group business is qualifying revenue"
        assert group["program_fee_eligible"] is True, "group business is fee-assessed"
        assert group["counts_toward_elite"] is False, (
            "group nights never accrue toward a tier"
        )
        assert_rate_plan_derivation(group)

    def test_the_three_excluded_families_earn_nothing_and_owe_nothing(self, api):
        """Opaque wholesale, employee comp and award stays fall outside all three sets
        and earn at a rate of zero.

        PRD: "The flag `is_qualifying` is true exactly when the category is one of
        `TRANSIENT`, `CORPORATE_NEGOTIATED` or `GROUP`, and false for the three excluded
        families."

        Design: Corner/calculations/rate_category_table_maps_six_categories_to_four_derived_flags
        """
        bundle = _ratecard_hotel_carrying_all_six_categories(api)

        for category in ("OPAQUE_WHOLESALE", "EMPLOYEE_COMP", "AWARD"):
            plan = bundle["plans"][category]
            assert plan["base_earn_rate_per_dollar"] == 0, (
                f"{category} earns nothing, got {plan['base_earn_rate_per_dollar']}"
            )
            assert plan["is_qualifying"] is False, f"{category} is not qualifying"
            assert plan["program_fee_eligible"] is False, f"{category} owes no fee"
            assert plan["counts_toward_elite"] is False, f"{category} lifts no tier"
            assert_rate_plan_derivation(plan)

    def test_all_six_plans_belong_to_the_property_that_registered_them(self, api):
        """Every plan records its owning property, so the property's own collection
        returns all six and nothing else.

        PRD: "A rate plan records the property it belongs to through its `hotel_id`."

        Design: Corner/calculations/rate_category_table_maps_six_categories_to_four_derived_flags
        """
        bundle = _ratecard_hotel_carrying_all_six_categories(api)
        hotel_id = bundle["hotel"]["id"]

        plans = collect_all(api.list_rate_plans, make_auditor_headers(), hotel_id=hotel_id)

        assert len(plans) == 6, f"the property carries six rate plans, got {len(plans)}"
        assert {plan["rate_category"] for plan in plans} == {
            "TRANSIENT",
            "CORPORATE_NEGOTIATED",
            "GROUP",
            "OPAQUE_WHOLESALE",
            "EMPLOYEE_COMP",
            "AWARD",
        }, "all six categories are represented exactly once"
        assert all(plan["hotel_id"] == hotel_id for plan in plans), (
            "every plan names the property it was registered beneath"
        )


# ----------------------------------------------------------------------
# Room revenue alone drives the earning and the fee.
# ----------------------------------------------------------------------
class TestGroupStayEarnsFlooredPointsOnRoomRevenueAlone:
    def test_the_base_award_floors_the_group_earn_rate(self, api):
        """Twelve thousand three hundred and forty-five cents at six points a dollar
        computes 740.7 and awards 740 - the rounding never goes up.

        PRD: "`base_points_awarded` is the stay's `room_revenue_cents` multiplied by the
        rate plan's `base_earn_rate_per_dollar`, divided by one hundred to convert cents
        into whole dollars, with the result rounded **down** to a whole point."

        Design: Corner/calculations/group_stay_earns_floored_points_on_room_revenue_alone_and_lifts_no_tier
        """
        bundle = _groupblock_stay_posted_with_heavy_incidentals(api)

        assert_stay(
            bundle["stay"],
            status="POSTED_QUALIFYING",
            base_points=740,
            nights=10,
            room_revenue_cents=12_345,
        )

    def test_the_fee_is_assessed_on_room_revenue_and_ignores_the_incidentals(self, api):
        """The 50,000 cents of food and beverage are four times the room revenue and
        still contribute nothing to the fee.

        PRD: "Room-only revenue arrives as `room_revenue_cents` and is the sole base for
        both earning and fee assessment; `incidental_revenue_cents` — food, beverage and
        everything else — is optional, defaults to 0, and never earns a point nor
        attracts a cent of programme fee under any rate category."

        Design: Corner/calculations/group_stay_earns_floored_points_on_room_revenue_alone_and_lifts_no_tier
        """
        bundle = _groupblock_stay_posted_with_heavy_incidentals(api)

        assert bundle["stay"]["incidental_revenue_cents"] == 50_000, (
            "the stay really does carry the larger incidental figure"
        )
        assert_stay(bundle["stay"], fee_cents=617)
        assert_hotel(
            fx.read_hotel(api, bundle["hotel"]["id"]),
            status="ACTIVE",
            fee_ledger_cents=617,
        )

    def test_a_base_snapshot_multiplies_the_bonus_to_nothing(self, api):
        """The guest held no tier at check-in, so the bonus arm computes with a zero
        multiplier and writes no second award.

        PRD: "the multiplier is 0.00 at `BASE`, 0.20 at `SILVER`, 0.50 at `GOLD` and
        0.75 at `PLATINUM`, and `bonus_points_awarded` is `base_points_awarded`
        multiplied by that multiplier, again rounded **down** to a whole point"

        Design: Corner/calculations/group_stay_earns_floored_points_on_room_revenue_alone_and_lifts_no_tier
        """
        bundle = _groupblock_stay_posted_with_heavy_incidentals(api)

        assert_stay(
            bundle["stay"], tier_at_checkin="BASE", bonus_points=0, bonus_multiplier=0.0
        )
        assert len(fx.ledger_for_stay(api, bundle["stay"]["id"])) == 1, (
            "only the base award became a ledger entry"
        )

    def test_ten_group_nights_move_the_revenue_counter_but_not_the_tier(self, api):
        """The nights counter is fed only by plans inside the elite set, so a ten-night
        group stay leaves the guest exactly where it found them.

        PRD: "the member's `qualifying_nights_ytd` is recomputed as well whenever the
        stay's rate plan has `counts_toward_elite` true."

        Design: Corner/calculations/group_stay_earns_floored_points_on_room_revenue_alone_and_lifts_no_tier
        """
        bundle = _groupblock_stay_posted_with_heavy_incidentals(api)

        assert_member(
            fx.read_member(api, bundle["member"]["id"]),
            elite_tier="BASE",
            qualifying_nights=0,
            qualifying_revenue_cents=12_345,
            point_balance=740,
        )


# ----------------------------------------------------------------------
# Three benefit types, three different recovery rules.
# ----------------------------------------------------------------------
class TestBenefitRecoveryCapsTheUpgradeAndScalesBreakfast:
    def test_the_top_tier_snapshot_owes_all_three_benefits(self, api):
        """The three-night stay was captured after the guest reached the top tier, so
        the posting synthesised the full entitlement set.

        PRD: "The entitlement matrix reads the stay's `tier_at_checkin`: `UPGRADE` is
        owed at `SILVER`, `GOLD` and `PLATINUM`; `BREAKFAST` is owed at `GOLD` and
        `PLATINUM`; `LATE_CHECKOUT` is owed at `PLATINUM` only; and a `BASE` guest is
        entitled to nothing at all."

        Design: Corner/calculations/benefit_recovery_caps_the_upgrade_and_scales_breakfast_by_night_count
        """
        bundle = _recovery_regent_with_three_platinum_obligations(api)

        assert_stay(bundle["stay"], tier_at_checkin="PLATINUM", nights=3)
        obligations = fx.obligations_for_stay(api, bundle["stay"]["id"])
        assert_entitlement_for_tier(obligations, "PLATINUM")
        assert_all_deliveries_status(obligations, "OBLIGATED")

    def test_the_upgrade_recovery_is_capped_after_the_rounding(self, api):
        """Fifteen percent of an 80,000-cent daily rate is 12,000, and the hard ceiling
        brings the credit down to 9,000.

        PRD: "An `UPGRADE` recovers fifteen percent of the property's
        `trailing_12m_adr_cents` as read at delivery time, rounded half up to the cent
        and then capped at 9,000 cents; the rounding happens before the cap, and the cap
        is a hard ceiling"

        Design: Corner/calculations/benefit_recovery_caps_the_upgrade_and_scales_breakfast_by_night_count
        """
        bundle = _recovery_regent_with_three_platinum_obligations(api)

        delivered = fx.deliver_obligation(
            api, bundle["obligations"]["UPGRADE"]["id"], headers=bundle["owner_headers"]
        )

        assert_delivery(
            delivered,
            status="DELIVERED",
            benefit_type="UPGRADE",
            cost_recovery_cents=9_000,
        )

    def test_the_breakfast_recovery_scales_with_the_night_count(self, api):
        """Breakfast is the one benefit whose credit multiplies by nights, so three
        nights recover three times 1,800.

        PRD: "A `BREAKFAST` recovers 1,800 cents for each of the originating stay's
        `nights`."

        Design: Corner/calculations/benefit_recovery_caps_the_upgrade_and_scales_breakfast_by_night_count
        """
        bundle = _recovery_regent_with_three_platinum_obligations(api)

        delivered = fx.deliver_obligation(
            api, bundle["obligations"]["BREAKFAST"]["id"], headers=bundle["owner_headers"]
        )

        assert_delivery(
            delivered,
            status="DELIVERED",
            benefit_type="BREAKFAST",
            cost_recovery_cents=5_400,
        )

    def test_the_late_checkout_recovery_is_a_flat_constant(self, api):
        """Late checkout ignores both the daily rate and the night count and credits the
        same 1,200 cents either way.

        PRD: "A `LATE_CHECKOUT` recovers a flat 1,200 cents. The figure lands in
        `cost_recovery_cents`, the property's `benefit_recovery_owed_cents` is
        recomputed, and the obligation's `version` increments."

        Design: Corner/calculations/benefit_recovery_caps_the_upgrade_and_scales_breakfast_by_night_count
        """
        bundle = _recovery_regent_with_three_platinum_obligations(api)

        delivered = fx.deliver_obligation(
            api,
            bundle["obligations"]["LATE_CHECKOUT"]["id"],
            headers=bundle["owner_headers"],
        )

        assert_delivery(
            delivered,
            status="DELIVERED",
            benefit_type="LATE_CHECKOUT",
            cost_recovery_cents=1_200,
        )

    def test_the_property_is_owed_the_sum_of_the_three_recoveries(self, api):
        """Honouring all three benefits credits the property once for each, and none of
        them counts as a denial.

        PRD: "the benefit recovery owed is the sum of `cost_recovery_cents` across the
        elite benefit obligations of that property's stays whose `status` is `DELIVERED`"

        Design: Corner/calculations/benefit_recovery_caps_the_upgrade_and_scales_breakfast_by_night_count
        """
        bundle = _recovery_regent_with_three_platinum_obligations(api)

        for benefit_type in ("UPGRADE", "BREAKFAST", "LATE_CHECKOUT"):
            fx.deliver_obligation(
                api,
                bundle["obligations"][benefit_type]["id"],
                headers=bundle["owner_headers"],
            )

        assert_hotel(
            fx.read_hotel(api, bundle["hotel"]["id"]),
            status="ACTIVE",
            benefit_recovery_owed_cents=15_600,
            benefit_denial_count=0,
        )


# ----------------------------------------------------------------------
# The fee ledger counts only its own property's posted stays.
# ----------------------------------------------------------------------
class TestFeeLedgerSumsOnlyThePostedStaysOfItsOwnProperty:
    def test_each_property_assesses_at_its_own_rate(self, api):
        """The same formula run at two different properties gives two different figures,
        because the rate is the property's own.

        PRD: "Per stay, the fee is the stay's `room_revenue_cents` multiplied by the
        property's `program_fee_pct`, rounded half up to the whole cent, and stored on
        the stay as `program_fee_assessed_cents`"

        Design: Corner/calculations/fee_ledger_sums_only_the_posted_stays_of_its_own_property
        """
        bundle = _ledger_alpha_and_bravo_with_five_stays(api)

        assert_stay(bundle["qualifying"], status="POSTED_QUALIFYING", fee_cents=617)
        assert_stay(bundle["other_property"], status="POSTED_QUALIFYING", fee_cents=5_000)

    def test_an_opaque_wholesale_stay_is_neither_fee_bearing_nor_earning(self, api):
        """Two hundred thousand cents of revenue on an excluded category posts to the
        non-qualifying arm and contributes nothing to either total.

        PRD: "if the rate plan has `program_fee_eligible` false or `is_qualifying` false,
        that figure is 0."

        Design: Corner/calculations/fee_ledger_sums_only_the_posted_stays_of_its_own_property
        """
        bundle = _ledger_alpha_and_bravo_with_five_stays(api)

        assert_stay(
            bundle["opaque"],
            status="POSTED_NON_QUALIFYING",
            base_points=0,
            fee_cents=0,
            room_revenue_cents=200_000,
        )
        assert_non_qualifying_stay_is_inert(bundle["opaque"])

    def test_the_ledger_excludes_the_unposted_and_the_voided_stay(self, api):
        """The pending stay's 100,000 cents and the voided stay's 300,000 cents sit
        outside the status filter, so the ledger reads only the one posted fee.

        PRD: "The property's `fee_ledger_balance_cents` is then re-derived as the sum of
        the **already-rounded** per-stay figures across all of that property's stays
        whose `status` is one of `POSTED_QUALIFYING`, `POSTED_NON_QUALIFYING`, `DISPUTED`
        or `ADJUSTED` — stays in `PENDING_POSTING` and `VOID` are excluded, and there is
        no monthly window, the ledger spans all time"

        Design: Corner/calculations/fee_ledger_sums_only_the_posted_stays_of_its_own_property
        """
        bundle = _ledger_alpha_and_bravo_with_five_stays(api)

        assert_stay(fx.read_stay(api, bundle["unposted"]["id"]), status="PENDING_POSTING")
        assert_stay(bundle["voided"], status="VOID")
        assert_hotel(
            fx.read_hotel(api, bundle["alpha"]["id"]),
            status="ACTIVE",
            fee_ledger_cents=617,
        )

    def test_the_other_propertys_posted_stay_is_outside_the_scope(self, api):
        """Each ledger reads its own property's stays, so the two balances are computed
        from disjoint input sets.

        PRD: "Paid stays filter on `member_id`, `hotel_id`, `rate_plan_id` and `status`."

        Design: Corner/calculations/fee_ledger_sums_only_the_posted_stays_of_its_own_property
        """
        bundle = _ledger_alpha_and_bravo_with_five_stays(api)
        admin = make_admin_headers()

        alpha_stays = collect_all(api.list_stays, admin, hotel_id=bundle["alpha"]["id"])
        bravo_stays = collect_all(api.list_stays, admin, hotel_id=bundle["bravo"]["id"])

        assert len(alpha_stays) == 4, (
            f"the first property holds four stays, got {len(alpha_stays)}"
        )
        assert len(bravo_stays) == 1, (
            f"the second property holds one stay, got {len(bravo_stays)}"
        )
        assert_hotel(fx.read_hotel(api, bundle["bravo"]["id"]), fee_ledger_cents=5_000)

    def test_only_the_qualifying_stays_moved_the_guests_counters(self, api):
        """One guest took all five stays, and only the two posted transient ones show up
        in the earning and revenue totals.

        PRD: "`qualifying_revenue_cents_ytd` is the sum of `room_revenue_cents` across
        that member's stays whose `status` is `POSTED_QUALIFYING` and whose
        `checkin_date` falls in the logical clock's current year"

        Design: Corner/calculations/fee_ledger_sums_only_the_posted_stays_of_its_own_property
        """
        bundle = _ledger_alpha_and_bravo_with_five_stays(api)

        assert_member(
            fx.read_member(api, bundle["member"]["id"]),
            elite_tier="BASE",
            point_balance=6_234,
            qualifying_nights=4,
            qualifying_revenue_cents=62_345,
        )
