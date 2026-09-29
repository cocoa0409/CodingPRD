"""Derived-money and derived-unit formulas, each pinned on one hand-computed case.

Every test here fixes the inputs of a single formula and asserts the exact
integer the PRD's arithmetic produces, so an implementation that rounds the
wrong way, skips a component or prices off the wrong base is caught.
"""

from test_helpers import (
    AGENT,
    api_client,
    assert_instant,
    assert_refund_ledger_identity,
    create_bundle,
    create_customer_row,
    create_model,
    file_attribution_claim,
    file_quality_claim,
    accept_attribution_for_review,
    adjudicate_claim,
    get_success_data,
    make_finance_controller_headers,
    make_trial_support_agent_headers,
    read_order,
    read_return_case,
    read_route,
    resolve_attribution_payload,
    set_clock,
    setup_delivered_order,
    setup_partner_channel_order,
    setup_return_lifecycle,
    trial_order_payload,
    validate_success,
)

WARRANTY_AGENT = make_trial_support_agent_headers("agent-c2")
COMMISSION_CONTROLLER = make_finance_controller_headers("fin-c9")


class TestBundleDiscountRounding:
    """The percent-off discount is rounded, not truncated, before it leaves the quote."""

    def test_a_fractional_bundle_discount_rounds_up_to_the_nearest_cent(self):
        """PRD §3.3: "When a bundle is attached, `bundle_discount_cents` is the quoted `gross_price_cents` multiplied by the bundle's `percent_off_bps` and divided by 10000, rounded to the nearest whole cent with ties away from zero."

        1250 basis points of a 119999-cent quote is 14999.875 cents exactly, so
        the discount rounds to 15000 and the refundable principal is
        119999 - 15000 = 104999 cents; a truncating implementation would keep
        14999 and charge 105000.

        Design: Corner/calculations/order_pricing_rounds_the_bundle_discount_half_up
        """
        set_clock("2026-08-01T00:00:00Z")
        model = create_model(sku="MDL-Q-C1", name="Comfort Q", list_price_cents=120000)
        bundle = create_bundle(
            code="BUNDLE-C1",
            unwind_policy="FORFEIT_NONE",
            accessory_retail_cents=0,
            gift_card_cents=0,
            percent_off_bps=1250,
        )
        customer = create_customer_row(
            email="c1@example.com", full_name="Cal Calc", household_hash="HH-C1"
        )

        order = validate_success(
            api_client.create_trial_order(
                trial_order_payload(
                    customer["id"],
                    model["id"],
                    gross_price_cents=119999,
                    bundle_id=bundle["id"],
                ),
                AGENT,
            ),
            201,
        )

        assert order["bundle_discount_cents"] == 15000, (
            "119999 * 1250 / 10000 is 14999.875, which rounds to 15000, got "
            f"{order['bundle_discount_cents']}"
        )
        assert order["paid_amount_cents"] == 104999, (
            "the principal is the quote less the rounded discount, got "
            f"{order['paid_amount_cents']}"
        )
        assert order["outstanding_refundable_cents"] == 104999
        assert order["refunded_total_cents"] == 0
        assert order["retained_amount_cents"] == 0
        assert_refund_ledger_identity(order)


class TestWarrantyCreditDecay:
    """Two completed ownership years cost the warranty 2000 basis points of coverage."""

    def test_an_indentation_credit_prices_at_the_decayed_coverage_rate(self):
        """PRD §3.4: "Coverage starts at 10000 basis points and loses 1000 basis points for each completed ownership year, but never falls below a floor of 2000 basis points; in other words, coverage is whichever is larger of 2000 and 10000 less one thousand times `ownership_years`."

        A mattress delivered 2026-08-01 and reported on 2028-09-10 has been owned
        for 771 days, which is two complete 365-day years, so coverage has decayed
        to 8000 basis points and the credit on the 120000-cent principal is
        120000 * 8000 / 10000 = 96000 cents.

        Design: Corner/calculations/warranty_indentation_credit_decays_one_thousand_bps_per_ownership_year
        """
        scenario = setup_delivered_order(
            model_overrides={
                "sku": "MDL-Q-C2",
                "name": "Comfort Q",
                "list_price_cents": 120000,
                "indentation_warranty_threshold_mm": 25,
            },
            customer_overrides={
                "email": "c2@example.com",
                "full_name": "Cara Calc",
                "household_hash": "HH-C2",
            },
        )
        set_clock("2026-09-10T00:00:00Z")
        kept = get_success_data(
            api_client.keep_trial_order(scenario["order"]["id"], {}, AGENT)
        )
        assert kept["trial_status"] == "KEPT"

        set_clock("2028-09-10T00:00:00Z")
        claim = file_quality_claim(
            scenario["order"]["id"],
            "WARRANTY_INDENTATION",
            1,
            measurement_method="LASER_SCAN",
            measured_indentation_mm=30,
        )
        assert claim["ownership_years"] == 2, (
            "2026-08-01 to 2028-09-10 is 771 days, which is 2 complete 365-day "
            f"years, got {claim['ownership_years']}"
        )
        assert claim["coverage_bps"] == 8000, (
            f"10000 - 1000 * 2 is 8000 basis points, got {claim['coverage_bps']}"
        )
        assert_instant(claim["reported_at"], "2028-09-10T00:00:00Z", "reported_at")

        adjudicated = adjudicate_claim(claim["id"], "CREDIT", headers=WARRANTY_AGENT)
        assert adjudicated["status"] == "APPROVED"
        assert adjudicated["resolution"] == "CREDIT"
        assert adjudicated["credit_cents"] == 96000, (
            "an indentation credit is paid_amount_cents * coverage_bps / 10000 = "
            f"120000 * 8000 / 10000 = 96000, got {adjudicated['credit_cents']}"
        )
        assert adjudicated["approved_by_user_id"] == "agent-c2"

        order = read_order(scenario["order"]["id"])
        assert order["fulfillment_status"] == "CLOSED", (
            "an indentation claim never touches the fulfillment axis"
        )
        assert order["goodwill_credit_cents"] == 0, (
            "the credit only reaches the order at settlement, got "
            f"{order['goodwill_credit_cents']}"
        )


class TestBundleUnwindComponents:
    """The three claw-back components are each switched on by their own condition."""

    def test_returning_the_accessory_waives_the_two_accessory_components_only(self):
        """PRD §3.8: "The accessory is waived entirely when the bundle's `requires_accessory_return` is true and the inspection recorded `accessory_returned` as true."

        A DEDUCT_RETAIL bundle worth a 20000-cent accessory and a 10000-cent gift
        card would normally claw back 20000 for the accessory and a 1714-cent
        share of the mattress discount, but returning the accessory zeroes both:
        only the gift card's full 10000 cents survives, so the provisional refund
        is 108000 - 12150 - 10000 = 85850 cents.

        Design: Corner/calculations/returning_the_accessory_waives_both_accessory_components_but_not_the_gift_card
        """
        scenario = setup_return_lifecycle(
            stage="INSPECTED",
            model_overrides={
                "sku": "MDL-Q-C3",
                "name": "Comfort Q",
                "list_price_cents": 120000,
            },
            bundle_overrides={
                "code": "BUNDLE-C3",
                "unwind_policy": "DEDUCT_RETAIL",
                "accessory_retail_cents": 20000,
                "gift_card_cents": 10000,
                "percent_off_bps": 1000,
                "requires_accessory_return": True,
            },
            customer_overrides={
                "email": "c3@example.com",
                "full_name": "Cy Calc",
                "household_hash": "HH-C3",
            },
            condition_grade="A",
            soil_flag=False,
            accessory_returned=True,
        )
        case = scenario["return_case"]

        assert scenario["order"]["paid_amount_cents"] == 108000
        assert case["accessory_returned"] is True
        assert case["nights_used"] == 45
        assert case["bundle_unwind_cents"] == 10000, (
            "the waiver zeroes the accessory value and the discount reallocation, "
            f"leaving only the 10000-cent gift card, got {case['bundle_unwind_cents']}"
        )
        assert case["damage_offset_cents"] == 0
        assert case["proration_deduction_cents"] == 12150, (
            "108000 * 45 * 2500 / (100 * 10000) is 12150, got "
            f"{case['proration_deduction_cents']}"
        )
        assert case["provisional_refund_cents"] == 85850, (
            f"108000 - 12150 - 10000 - 0 is 85850, got "
            f"{case['provisional_refund_cents']}"
        )

    def test_a_forfeit_none_bundle_claws_back_nothing_at_all(self):
        """PRD §3.8: "The first component covers the accessory's value: it is zero when the `unwind_policy` is `FORFEIT_NONE` or the accessory was waived; it is the full `accessory_retail_cents` when the policy is `DEDUCT_RETAIL`; and under `DEDUCT_PRORATED` it is `accessory_retail_cents` multiplied by the unearned share of the trial — that is, by the model's `trial_nights` less whichever is smaller of `nights_used` and `trial_nights`, divided by `trial_nights` — rounded to the nearest whole cent with ties away from zero, so the customer earns the gift progressively over the trial."

        The same 20000-cent accessory and 10000-cent gift card under FORFEIT_NONE
        are kept by the customer for free even though the accessory never came
        back, so the unwind is zero and the provisional refund is
        108000 - 12150 = 95850 cents.

        Design: Corner/calculations/forfeit_none_policy_deducts_nothing_even_when_the_accessory_is_kept
        """
        scenario = setup_return_lifecycle(
            stage="INSPECTED",
            model_overrides={
                "sku": "MDL-Q-C4",
                "name": "Comfort Q",
                "list_price_cents": 120000,
            },
            bundle_overrides={
                "code": "BUNDLE-C4",
                "unwind_policy": "FORFEIT_NONE",
                "accessory_retail_cents": 20000,
                "gift_card_cents": 10000,
                "percent_off_bps": 1000,
                "requires_accessory_return": False,
            },
            customer_overrides={
                "email": "c4@example.com",
                "full_name": "Cleo Calc",
                "household_hash": "HH-C4",
            },
            condition_grade="A",
            soil_flag=False,
            accessory_returned=False,
        )
        case = scenario["return_case"]

        assert scenario["order"]["paid_amount_cents"] == 108000
        assert case["accessory_returned"] is False
        assert case["bundle_unwind_cents"] == 0, (
            "all three components are zero under FORFEIT_NONE, got "
            f"{case['bundle_unwind_cents']}"
        )
        assert case["condition_grade"] == "A"
        assert case["damage_offset_cents"] == 0
        assert case["proration_deduction_cents"] == 12150
        assert case["provisional_refund_cents"] == 95850, (
            f"108000 - 12150 - 0 - 0 is 95850, got {case['provisional_refund_cents']}"
        )


class TestDamageOffset:
    """Grade and soiling stack additively until the 4000-basis-point cap bites."""

    def test_a_soiled_grade_c_unit_retains_the_summed_rate_below_the_cap(self):
        """PRD §3.8: "Each grade carries a retention rate in basis points — grade `A` zero, grade `B` 500, grade `C` 1500 and grade `D` 3000 — and a soiled unit adds a further 1000 basis points on top of the grade's rate."

        Grade C's 1500 basis points plus 1000 for soiling is 2500, still under the
        4000-point cap, so the offset on the 120000-cent principal is
        120000 * 2500 / 10000 = 30000 cents and the provisional refund is
        120000 - 13500 - 30000 = 76500 cents.

        Design: Corner/calculations/damage_offset_adds_grade_and_soil_bps_while_still_under_the_cap
        """
        scenario = setup_return_lifecycle(
            stage="INSPECTED",
            model_overrides={
                "sku": "MDL-Q-C5",
                "name": "Comfort Q",
                "list_price_cents": 120000,
            },
            customer_overrides={
                "email": "c5@example.com",
                "full_name": "Cass Calc",
                "household_hash": "HH-C5",
            },
            condition_grade="C",
            soil_flag=True,
        )
        case = scenario["return_case"]

        assert scenario["order"]["paid_amount_cents"] == 120000
        assert case["condition_grade"] == "C"
        assert case["soil_flag"] is True
        assert case["nights_used"] == 45
        assert case["damage_offset_cents"] == 30000, (
            "1500 for grade C plus 1000 for soiling is 2500 bps of 120000, got "
            f"{case['damage_offset_cents']}"
        )
        assert case["bundle_unwind_cents"] == 0
        assert case["proration_deduction_cents"] == 13500
        assert case["provisional_refund_cents"] == 76500, (
            f"120000 - 13500 - 0 - 30000 is 76500, got "
            f"{case['provisional_refund_cents']}"
        )


class TestPickupUnitSizing:
    """Truck capacity is consumed by bed size, not by case count."""

    def test_a_king_booking_consumes_three_of_the_six_route_units(self):
        """PRD §3.7: "The slot's `units` are not supplied by the caller; they are derived from the bed size of the returned order's model, with a `TWIN` counting as one unit, a `QUEEN` as two and a `KING` as three."

        A single KING collection on a six-unit route therefore books 3 units and
        leaves 3 available — the caller never sends a unit count.

        Design: Corner/calculations/pickup_units_sizes_a_king_booking_at_three_units
        """
        scenario = setup_return_lifecycle(
            stage="PICKUP_SCHEDULED",
            model_overrides={
                "sku": "MDL-K-C6",
                "name": "Comfort King",
                "size": "KING",
                "list_price_cents": 180000,
            },
            customer_overrides={
                "email": "c6@example.com",
                "full_name": "Kip Calc",
                "household_hash": "HH-C6",
            },
            route_overrides={"capacity_units": 6},
        )
        appointment = scenario["appointment"]

        assert appointment["units"] == 3, (
            f"a KING counts as three units, got {appointment['units']}"
        )
        assert appointment["status"] == "BOOKED"
        assert_instant(
            appointment["slot_start_at"], "2026-09-15T09:00:00Z", "slot_start_at"
        )

        route = read_route(scenario["route"]["id"])
        assert route["capacity_units"] == 6
        assert route["booked_units"] == 3
        assert route["available_units"] == 3
        reloaded_case = read_return_case(scenario["return_case"]["id"])
        assert reloaded_case["logistics_status"] == "PICKUP_SCHEDULED"


class TestDispositionPartnerSelection:
    """Rank comes first in the sort, and the donation pool can fall through."""

    def test_the_lower_ranked_partner_wins_despite_having_less_headroom(self):
        """PRD §3.8: "When a type yields at least one eligible partner, the winner is chosen deterministically: lowest `priority_rank` first; among equal ranks, the partner with the greatest remaining intake headroom for that date — its `daily_intake_capacity_units` less its already-booked units — wins; and if that is still tied, the partner with the earliest `created_at` wins."

        Two eligible recyclers compete: one at rank 2 with 10 units of headroom
        and one at rank 1 with only 4. Rank is the primary key, so the rank-1
        partner wins even though it has the smaller day, and its 4000-cent
        per-unit fee prices the two-unit QUEEN at 8000 cents.

        Design: Corner/calculations/disposition_priority_rank_outranks_remaining_capacity_in_the_partner_sort
        """
        scenario = setup_return_lifecycle(
            stage="DISPOSITIONED",
            model_overrides={
                "sku": "MDL-Q-C7",
                "name": "Comfort Q",
                "list_price_cents": 120000,
                "donation_eligible": False,
            },
            customer_overrides={
                "email": "c7@example.com",
                "full_name": "Cora Calc",
                "household_hash": "HH-C7",
            },
            partner_specs=[
                {
                    "name": "Recycler BIG",
                    "partner_type": "RECYCLER",
                    "region_code": "CA",
                    "daily_intake_capacity_units": 10,
                    "accepts_condition_grades": ["A", "B", "C", "D"],
                    "soil_policy": "ACCEPT_SOILED",
                    "priority_rank": 2,
                    "recycle_fee_cents_per_unit": 3000,
                },
                {
                    "name": "Recycler PREF",
                    "partner_type": "RECYCLER",
                    "region_code": "CA",
                    "daily_intake_capacity_units": 4,
                    "accepts_condition_grades": ["A", "B", "C", "D"],
                    "soil_policy": "ACCEPT_SOILED",
                    "priority_rank": 1,
                    "recycle_fee_cents_per_unit": 4000,
                },
            ],
            disposition="RECYCLE",
            intake_date="2026-09-16",
        )
        preferred = scenario["partners"][1]
        assignment = scenario["assignment"]

        assert assignment["partner_id"] == preferred["id"], (
            "priority_rank 1 outranks the roomier rank-2 partner, got a different "
            "winner"
        )
        assert assignment["units"] == 2
        assert assignment["fee_cents"] == 8000, (
            f"2 units at 4000 cents each is 8000, got {assignment['fee_cents']}"
        )
        assert assignment["disposition_type"] == "RECYCLE"
        assert assignment["fallback_applied"] is False, (
            "a recycle request never falls through, so no fallback was applied"
        )
        assert assignment["status"] == "ASSIGNED"
        assert assignment["intake_date"] == "2026-09-16"
        assert scenario["return_case"]["disposition"] == "RECYCLE"
        assert scenario["return_case"]["logistics_status"] == "DISPOSITIONED"

    def test_a_donation_falls_through_to_the_recycler_when_the_charity_is_out_of_region(self):
        """PRD §3.8: "Partner selection then runs a waterfall over partner types. A donation request tries `CHARITY` partners first and, if none can take the unit, falls through to `RECYCLER` partners; a recycle request considers only `RECYCLER` partners."

        The unit is donation-eligible, grade A and unsoiled, so the only reason the
        charity cannot take it is that it serves TX while the route collected in
        CA. The waterfall therefore drops to the CA recycler, marks
        fallback_applied true, and books a real 5000-cent-per-unit fee on the
        two-unit QUEEN.

        Design: Corner/calculations/donation_waterfall_falls_back_to_a_recycler_when_no_charity_qualifies
        """
        scenario = setup_return_lifecycle(
            stage="DISPOSITIONED",
            model_overrides={
                "sku": "MDL-Q-C8",
                "name": "Comfort Q",
                "list_price_cents": 120000,
                "donation_eligible": True,
            },
            customer_overrides={
                "email": "c8@example.com",
                "full_name": "Colin Calc",
                "household_hash": "HH-C8",
            },
            partner_specs=[
                {
                    "name": "Charity OUT",
                    "partner_type": "CHARITY",
                    "region_code": "TX",
                    "daily_intake_capacity_units": 6,
                    "accepts_condition_grades": ["A", "B"],
                    "soil_policy": "REJECT_SOILED",
                    "priority_rank": 1,
                },
                {
                    "name": "Recycler IN",
                    "partner_type": "RECYCLER",
                    "region_code": "CA",
                    "daily_intake_capacity_units": 6,
                    "accepts_condition_grades": ["A", "B", "C", "D"],
                    "soil_policy": "ACCEPT_SOILED",
                    "priority_rank": 2,
                    "recycle_fee_cents_per_unit": 5000,
                },
            ],
            condition_grade="A",
            soil_flag=False,
            disposition="DONATION",
            intake_date="2026-09-16",
        )
        recycler = scenario["partners"][1]
        assignment = scenario["assignment"]

        assert assignment["partner_id"] == recycler["id"], (
            "the out-of-region charity is ineligible, so the CA recycler must win"
        )
        assert assignment["fallback_applied"] is True, (
            "a donation that fell through to a recycler sets fallback_applied"
        )
        assert assignment["disposition_type"] == "RECYCLE"
        assert assignment["units"] == 2
        assert assignment["fee_cents"] == 10000, (
            f"2 units at 5000 cents each is 10000, got {assignment['fee_cents']}"
        )
        assert assignment["status"] == "ASSIGNED"
        assert scenario["return_case"]["disposition"] == "RECYCLE", (
            "the case's disposition follows the winner's partner_type"
        )


class TestAttributionCommission:
    """Commission is a slice of the discounted principal, not of the sticker price."""

    def test_the_commission_is_priced_off_the_paid_principal(self):
        """PRD §3.10: "For a sales-attribution claim, `commission_cents` is the order's `paid_amount_cents` multiplied by the partner's `commission_bps` and divided by 10000, rounded to the nearest whole cent with ties away from zero, and `price_match_credit_cents` stays zero."

        A 120000-cent QUEEN sold with a 1000-basis-point bundle has a principal of
        108000, so an 800-basis-point commission is 8640 cents — pricing off the
        120000-cent gross would wrongly pay 9600.

        Design: Corner/calculations/attribution_commission_is_priced_off_paid_amount_not_gross_price
        """
        set_clock("2026-08-01T00:00:00Z")
        bundle = create_bundle(
            code="BUNDLE-C9",
            unwind_policy="DEDUCT_RETAIL",
            accessory_retail_cents=0,
            gift_card_cents=0,
            percent_off_bps=1000,
        )
        scenario = setup_partner_channel_order(
            partner_overrides={
                "name": "Sleep Gallery C9",
                "region_code": "CA",
                "commission_bps": 800,
                "price_match_policy": "MATCH_TO_LOWEST",
            },
            model_overrides={
                "sku": "MDL-Q-C9",
                "name": "Comfort Q",
                "list_price_cents": 120000,
            },
            customer_overrides={
                "email": "c9@example.com",
                "full_name": "Cody Calc",
                "household_hash": "HH-C9",
            },
            order_overrides={"bundle_id": bundle["id"]},
        )
        order = scenario["order"]
        assert order["gross_price_cents"] == 120000
        assert order["paid_amount_cents"] == 108000

        set_clock("2026-08-10T00:00:00Z")
        claim = file_attribution_claim(
            scenario["partner"], order["id"], "SALES_ATTRIBUTION", 2
        )
        accept_attribution_for_review(claim["id"])
        resolved = get_success_data(
            api_client.resolve_attribution_claim(
                claim["id"], resolve_attribution_payload("APPROVE"), COMMISSION_CONTROLLER
            )
        )

        assert resolved["status"] == "APPROVED"
        assert_instant(resolved["resolved_at"], "2026-08-10T00:00:00Z", "resolved_at")
        assert resolved["commission_cents"] == 8640, (
            "108000 * 800 / 10000 is 8640; 9600 would mean the commission was "
            f"priced off gross_price_cents, got {resolved['commission_cents']}"
        )
        assert resolved["price_match_credit_cents"] == 0

        reloaded = read_order(order["id"])
        assert reloaded["paid_amount_cents"] == 108000
        assert reloaded["price_match_credit_cents"] == 0, (
            "a sales-attribution approval never touches the order's price-match "
            f"counter, got {reloaded['price_match_credit_cents']}"
        )
        assert_refund_ledger_identity(reloaded)
