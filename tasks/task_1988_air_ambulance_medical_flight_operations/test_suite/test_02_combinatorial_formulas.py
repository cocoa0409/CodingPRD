"""Combinatorial formulas: the weather decision matrix, pinned invoice rounding
order, and the logistics surcharge tier keyed on the pre-logistics subtotal."""
from test_helpers import (
    assert_invoice,
    create_invoice,
    get_success_data,
    post_weather,
    setup_completed_mission,
    setup_planning_mission,
    api_client,
    TEST_USERS,
)

BILL = TEST_USERS["billing_specialist_headers"]
DISP = TEST_USERS["dispatcher_headers"]


class TestWeatherDecisionMatrixMultifactor:
    def test_ceiling_just_under_marginal_band_yields_marginal(self):
        """PRD §3.4: "Otherwise the decision is `MARGINAL` when any of the
        following holds: the `precip` is `HEAVY`; the ceiling is strictly below
        1.2 times the required ceiling; the visibility is strictly below the
        required visibility plus one-half statute mile; or the crosswind
        strictly exceeds five knots below the maximum."

        Design: Difficulty/combinatorial_formula/weather_decision_matrix_multifactor
        """
        ctx = setup_planning_mission(estimated_loaded_miles=60)
        pilot = ctx["roster"]["PILOT"]
        mission = ctx["mission"]
        # ROTOR_WING DAY FLAT: required ceiling 500; 590 < 500*1.2=600 -> MARGINAL.
        # Wind 21 > 25-5=20 is also a marginal condition.
        wa = post_weather(mission["id"], mission["version"], pilot,
                          ceiling_ft=590, visibility_sm=1.2, wind_kt=21)
        assert wa["decision"] == "MARGINAL", (
            f"Expected MARGINAL for ceiling 590 (< 600), got {wa['decision']}"
        )

    def test_marginal_band_upper_edges_yield_go(self):
        """PRD §3.4: "The boundaries are pinned: a ceiling exactly equal to the
        requirement passes, as does visibility exactly equal to the requirement;
        a ceiling exactly 1.2 times the requirement is `GO`, not `MARGINAL`; and
        a crosswind exactly equal to the maximum passes, because the violation
        test is strict."

        Design: Difficulty/combinatorial_formula/weather_decision_matrix_multifactor
        """
        ctx = setup_planning_mission(estimated_loaded_miles=60)
        pilot = ctx["roster"]["PILOT"]
        mission = ctx["mission"]
        # ROTOR_WING DAY FLAT: ceiling 600 == 500*1.2 (not strictly below),
        # vis 1.5 !< 1.0+0.5, wind 20 !> 25-5=20 -> GO.
        wa = post_weather(mission["id"], mission["version"], pilot,
                          ceiling_ft=600, visibility_sm=1.5, wind_kt=20)
        assert wa["decision"] == "GO", (
            f"Expected GO at marginal-band upper edges, got {wa['decision']}"
        )
        refreshed = get_success_data(api_client.get_mission(mission["id"], DISP))
        assert refreshed["last_weather_decision"] == "GO"


class TestInvoiceRoundingOrderPerLineThenSum:
    def test_pinned_rounding_order_mileage_first_then_fuel_from_rounded(self):
        """PRD §3.8: "Consider a rotor-wing mission finalized with
        `actual_loaded_miles` of 16.6666 and no acuity or logistics exposure:
        the pinned order rounds the mileage line to 266,666 cents, derives the
        fuel line as 18,667 cents from that rounded figure, and totals 2,085,333
        cents with the base line; summing the unrounded products and rounding
        once at the end yields 2,085,332 cents and is forbidden."
        PRD §2.5: "Every charge line on an invoice is rounded half-up to whole
        cents *before* the lines are summed, and the total is the sum of
        already-rounded lines. The fuel surcharge is computed from the
        already-rounded mileage line, and the logistics surcharge is computed
        from the already-rounded pre-logistics subtotal."

        Design: Difficulty/combinatorial_formula/invoice_rounding_order_per_line_then_sum
        """
        ctx = setup_completed_mission(
            subscales={"cardio": 2, "resp": 1, "neuro": 1, "interv": 0},
            medical_config="BLS_CAPABLE",
            estimated_loaded_miles=10,
            planned_duration_min=90,
            origin_facility="Clinic West",
        )
        invoice = create_invoice(ctx["mission"]["id"])
        invoice = get_success_data(
            api_client.finalize_invoice(invoice["id"], {"actual_loaded_miles": 16.6666}, BILL)
        )
        assert_invoice(invoice)
        assert invoice["mileage_line_cents"] == 266666, (
            f"Expected mileage 266666 (round_half_up(266665.6)), got {invoice['mileage_line_cents']}"
        )
        assert invoice["fuel_line_cents"] == 18667, (
            f"Expected fuel 18667 from the ROUNDED mileage line, got {invoice['fuel_line_cents']}"
        )
        # subtotal 1,800,000+266,666+18,667+0 = 2,085,333 < 2,500,000 -> logistics 0.
        assert invoice["logistics_line_cents"] == 0
        assert invoice["final_total_cents"] == 2085333, (
            f"Expected final 2085333 (sum-then-round would give 2085332), "
            f"got {invoice['final_total_cents']}"
        )

    def test_pinned_rounding_order_applies_at_invoice_creation_too(self):
        """PRD §2.5: "Every charge line on an invoice is rounded half-up to
        whole cents *before* the lines are summed, and the total is the sum of
        already-rounded lines."
        PRD §3.8: "The `fuel_line_cents` is 7% of the already-rounded mileage
        line, itself rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/invoice_rounding_order_per_line_then_sum
        """
        # Provisional variant on a fractional padded mileage: est 14.6667 ->
        # ceil(14.6667*1.15) = ceil(16.866705) = 17 miles; mileage 17*16000 =
        # 272000; fuel round(272000*.07)=19040; subtotal 1,800,000+272,000+19,040+0
        # = 2,091,040 < threshold; total == 2,091,040.
        ctx = setup_planning_mission(
            subscales={"cardio": 2, "resp": 1, "neuro": 1, "interv": 0},
            medical_config="BLS_CAPABLE",
            estimated_loaded_miles=14.6667,
            planned_duration_min=90,
            origin_facility="Clinic West",
        )
        invoice = create_invoice(ctx["mission"]["id"])
        assert invoice["mileage_line_cents"] == 272000
        assert invoice["fuel_line_cents"] == 19040
        assert invoice["logistics_line_cents"] == 0
        assert invoice["provisional_total_cents"] == 2091040


class TestLogisticsSurchargeSubtotalTierOrder:
    def test_subtotal_just_below_threshold_produces_no_surcharge(self):
        """PRD §3.8: "The `logistics_line_cents` is 4% of that subtotal, rounded
        half-up to whole cents, but only when the subtotal reaches the
        2,500,000-cent ($25,000.00) threshold — a subtotal of exactly 2,500,000
        cents triggers the surcharge, and the tier test reads the pre-logistics
        subtotal, never the post-surcharge total, so no circularity arises."

        Design: Difficulty/combinatorial_formula/logistics_surcharge_subtotal_tier_order
        """
        ctx = setup_completed_mission(
            subscales={"cardio": 2, "resp": 1, "neuro": 1, "interv": 0},
            medical_config="BLS_CAPABLE",
            estimated_loaded_miles=33,
            planned_duration_min=120,
            origin_facility="Clinic West",
        )
        invoice = create_invoice(ctx["mission"]["id"])
        invoice = get_success_data(
            api_client.finalize_invoice(
                invoice["id"], {"actual_loaded_miles": 37.9673125}, BILL
            )
        )
        # mileage round_half_up(37.9673125*16000)=607,477; fuel round(607,477*0.07)=42,523;
        # pre-logistics subtotal 1,800,000+607,477+42,523 = 2,450,000 < 2,500,000 -> 0.
        # Keying on the would-be total (2,450,000*1.04 = 2,548,000) would wrongly add 98,000.
        assert invoice["mileage_line_cents"] == 607477
        assert invoice["fuel_line_cents"] == 42523
        assert invoice["logistics_line_cents"] == 0, (
            f"Tier must read the pre-logistics subtotal (2,450,000 < 2,500,000); "
            f"got logistics {invoice['logistics_line_cents']}"
        )
        assert invoice["final_total_cents"] == 2450000

    def test_subtotal_reaching_threshold_triggers_surcharge(self):
        """PRD §3.8: "a subtotal of exactly 2,500,000 cents triggers the
        surcharge, and the tier test reads the pre-logistics subtotal, never the
        post-surcharge total, so no circularity arises."
        PRD §3.8: "The `logistics_line_cents` is 4% of that subtotal, rounded
        half-up to whole cents, but only when the subtotal reaches the
        2,500,000-cent ($25,000.00) threshold."

        Design: Difficulty/combinatorial_formula/logistics_surcharge_subtotal_tier_order
        """
        # ROTOR BLS: need base+mileage+fuel == 2,500,000 exactly.
        # mileage M, fuel round(M*0.07): pick M=654,206 -> fuel 45,794 (round(45,794.42));
        # 1,800,000+654,206+45,794 = 2,500,000 exactly. miles = 654206/16000 = 40.887875.
        ctx = setup_completed_mission(
            subscales={"cardio": 2, "resp": 1, "neuro": 1, "interv": 0},
            medical_config="BLS_CAPABLE",
            estimated_loaded_miles=40,
            planned_duration_min=120,
            origin_facility="Clinic West",
        )
        invoice = create_invoice(ctx["mission"]["id"])
        invoice = get_success_data(
            api_client.finalize_invoice(
                invoice["id"], {"actual_loaded_miles": 40.887875}, BILL
            )
        )
        assert invoice["mileage_line_cents"] == 654206
        assert invoice["fuel_line_cents"] == 45794
        # Subtotal reaches the threshold exactly -> 4% surcharge applies (>= inclusive).
        assert invoice["logistics_line_cents"] == 100000, (
            f"Expected logistics 100000 (4% of 2,500,000), got {invoice['logistics_line_cents']}"
        )
        assert invoice["final_total_cents"] == 2600000
