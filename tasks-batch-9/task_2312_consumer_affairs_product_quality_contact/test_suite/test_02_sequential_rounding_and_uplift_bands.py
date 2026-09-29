"""Multi-input formulas whose step order and step count are both normative.

Adjudicated severity rounds after each multiplier, goodwill picks its uplift
band from the base rather than from the payout, and a trend scope fires only
when two independent gates are cleared at once.
"""

from test_helpers import (
    add_complaint,
    add_contact,
    add_lot,
    add_remedy,
    assert_goodwill_math,
    assert_severity,
    assert_two_decimal_value,
    run_quality_ops,
    seed_base_world,
    set_clock,
    triage,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Sequential rounding of the two severity multipliers
# ---------------------------------------------------------------------------
INJURY_COMPLAINT = dict(
    complaint_type="FOREIGN_MATERIAL",
    foreign_object_class="HARD_BLUNT",
    medical_attention_sought=True,
    symptom_codes=["MOUTH_INJURY", "PAIN", "BLEEDING"],
    vulnerable_consumer=True,
)


def _seed_vulnerable_injury_on_regulated_lot(api):
    world = seed_base_world(api, actor_keys=("ag1", "sup1"))
    add_contact(api, world, "ct1")
    add_complaint(api, world, "cp1", **INJURY_COMPLAINT)
    return world


class TestSequentialSeverityRounding:
    def test_additive_hazard_total_is_the_whole_provisional_score(self, api):
        """Forty for the type, fifteen for the object, twenty-five medical, ten and a half symptoms.

        PRD: "Neither the regulated-food multiplier nor the vulnerability
        multiplier is applied at this stage, because at intake the product may
        not be identified at all and neither weighting could be justified."

        Design: Difficulty/combinatorial_formula/severity_sequential_rounding_order_is_normative
        """
        world = _seed_vulnerable_injury_on_regulated_lot(api)

        assert_severity(
            world["complaints"]["cp1"],
            provisional_score=90.50,
            provisional_band="S1",
        )

    def test_both_multipliers_round_one_after_the_other(self, api):
        """90.50 becomes 104.08 and then 111.89, never the fused 111.88.

        PRD: "Adjudication recomputes the score from the same additive hazard
        total described above, then applies two multipliers **one after the
        other, rounding half up to 2 decimal places after each one**."

        Design: Difficulty/combinatorial_formula/severity_sequential_rounding_order_is_normative
        """
        world = _seed_vulnerable_injury_on_regulated_lot(api)

        triaged = triage(api, world, world["complaints"]["cp1"]["id"])

        assert_two_decimal_value(triaged["adjudicated_severity_score"], 111.89)
        assert triaged["adjudicated_severity_score"] != 111.88

    def test_adjudicated_score_is_not_capped_at_one_hundred(self, api):
        """A score above 100 is published as computed and bands as S1.

        PRD: "Scores are not capped at 100."

        Design: Difficulty/combinatorial_formula/severity_sequential_rounding_order_is_normative
        """
        world = _seed_vulnerable_injury_on_regulated_lot(api)

        triaged = triage(api, world, world["complaints"]["cp1"]["id"])

        assert triaged["adjudicated_severity_score"] > 100
        assert_severity(triaged, adjudicated_band="S1", effective_band="S1")


# ---------------------------------------------------------------------------
# The uplift band is keyed on the base, the authority tier on the payout
# ---------------------------------------------------------------------------
def _seed_capped_refund(api):
    """A refund whose request exceeds the retail cap for the units claimed."""
    world = seed_base_world(api, actor_keys=("ag1", "sup1"))
    add_contact(api, world, "ct1")
    add_complaint(api, world, "cp1", complaint_type="QUALITY", units_claimed=2)
    add_remedy(
        api,
        world,
        world["complaints"]["cp1"]["id"],
        "rm1",
        remedy_type="REFUND",
        requested_value_cents=4900,
    )
    return world


class TestGoodwillUpliftBanding:
    def test_refund_base_is_capped_by_retail_price_times_units_claimed(self, api):
        """Two units at 2,500 cents cap the base at 5,000, so 4,900 survives as asked.

        PRD: "For a `REFUND`, the base is `requested_value_cents` or the
        resolved lot's product `unit_retail_price_cents` multiplied by the
        complaint's `units_claimed`, whichever is smaller; and if the
        complaint's kit has reached `LAB_ACCEPTED`, a sample-return credit of
        799 cents is then added to that capped figure and
        `kit_returned_credit_applied` is set true."

        Design: Difficulty/combinatorial_formula/goodwill_uplift_rate_keyed_on_base_not_payout
        """
        world = _seed_capped_refund(api)
        remedy = world["remedies"]["rm1"]

        assert remedy["base_value_cents"] == 4900
        assert remedy["kit_returned_credit_applied"] is False

    def test_uplift_rate_is_selected_from_the_base_and_not_from_the_payout(self, api):
        """A base of 4,900 draws 0.10, so the payout is 5,390 rather than 5,170.

        PRD: "Second, and this is the step that must not be reordered,
        `uplift_pct` is selected from `base_value_cents` **alone** and never
        from the payout it helps produce."

        Design: Difficulty/combinatorial_formula/goodwill_uplift_rate_keyed_on_base_not_payout
        """
        world = _seed_capped_refund(api)

        assert_goodwill_math(
            world["remedies"]["rm1"],
            base_value_cents=4900,
            uplift_pct=0.10,
            uplift_cents=490,
            payout_cents=5390,
            authority_tier_required="TIER_2",
        )
        assert world["remedies"]["rm1"]["payout_cents"] != 5170

    def test_authority_tier_is_banded_from_the_final_payout(self, api):
        """A payout of 5,390 sits above the TIER_1 ceiling and inside TIER_2.

        PRD: "Fourth, `authority_tier_required` is banded from the final
        payout: `TIER_1` when `payout_cents` is at most 2,500, `TIER_2` when it
        is at most 7,500, and `TIER_3` above that."

        Design: Difficulty/combinatorial_formula/goodwill_uplift_rate_keyed_on_base_not_payout
        """
        world = _seed_capped_refund(api)
        remedy = world["remedies"]["rm1"]

        assert remedy["payout_cents"] > 2500
        assert remedy["payout_cents"] <= 7500
        assert remedy["authority_tier_required"] == "TIER_2"


# ---------------------------------------------------------------------------
# A trend scope fires only when both gates are cleared
# ---------------------------------------------------------------------------
def _seed_two_lots_one_firing(api):
    """A 100,000-unit lot with three complaints and a 40,000-unit lot with two."""
    world = seed_base_world(
        api, actor_keys=("ag1", "sup1", "ql1"), product="mug", create_lot=False
    )
    add_lot(
        api,
        world,
        "lotb",
        product_key="mug",
        batch_code="LOT-B",
        code_date="2026-07-10T00:00:00Z",
        units_produced=100000,
    )
    add_lot(
        api,
        world,
        "lotc",
        product_key="mug",
        batch_code="LOT-C",
        code_date="2026-07-11T00:00:00Z",
        units_produced=40000,
    )
    add_contact(api, world, "ct1", channel="WEB")
    for index in range(1, 4):
        add_complaint(
            api,
            world,
            f"b{index}",
            complaint_type="FOREIGN_MATERIAL",
            reported_batch_code="LOTB",
        )
    for index in range(1, 3):
        add_complaint(
            api,
            world,
            f"c{index}",
            complaint_type="FOREIGN_MATERIAL",
            reported_batch_code="LOTC",
        )
    set_clock(api, "2026-08-02T00:00:00Z")
    return world


class TestTrendGateNeedsBothConditions:
    def test_scope_clearing_both_gates_emits_one_signal(self, api):
        """Three S3 complaints weigh 3.00 and read 30.00 ppm on 100,000 units.

        PRD: "A scope fires when **both** conditions hold, each comparison
        inclusive: `weighted_complaint_count` is at least 3.0, and
        `observed_rate_ppm` is at least the `threshold_ppm` for that scope
        level — 25.0 for `LOT`, 12.0 for `LINE`, and 6.0 for `PLANT`."

        Design: Difficulty/combinatorial_formula/trend_gate_requires_both_weighted_count_and_rate
        """
        world = _seed_two_lots_one_firing(api)

        run = run_quality_ops(api, world, dry_run=False)
        assert run["signals_created_count"] == 1
        assert run["memberships_created_count"] == 3

        signals, meta = validate_paginated(
            api.list_trend_signals(
                world.headers("ql1"), {"lot_id": world["lots"]["lotb"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        signal = signals[0]
        assert signal["scope_level"] == "LOT"
        assert signal["detection_source"] == "OPS_RUN"
        assert signal["status"] == "DETECTED"
        assert_two_decimal_value(signal["weighted_complaint_count"], 3.00)
        assert signal["units_in_scope"] == 100000
        assert_two_decimal_value(signal["observed_rate_ppm"], 30.00)
        assert_two_decimal_value(signal["threshold_ppm"], 25.0)
        assert signal["membership_count"] == 3

    def test_high_rate_alone_does_not_fire_a_scope(self, api):
        """Two complaints read 50.00 ppm yet weigh only 2.00, so nothing is emitted.

        PRD: "Each eligible complaint contributes a severity weight determined
        by its `effective_severity_band` — 3 for `S1`, 2 for `S2`, 1 for `S3`,
        and 0 for `S4`."

        Design: Difficulty/combinatorial_formula/trend_gate_requires_both_weighted_count_and_rate
        """
        world = _seed_two_lots_one_firing(api)

        run_quality_ops(api, world, dry_run=False)

        _lotc, lotc_meta = validate_paginated(
            api.list_trend_signals(
                world.headers("ql1"), {"lot_id": world["lots"]["lotc"]["id"]}
            )
        )
        assert lotc_meta["total_count"] == 0

    def test_waterfall_remainder_is_too_small_for_a_wider_scope(self, api):
        """After the firing lot is consumed only two weighted points remain.

        PRD: "Lines are examined next, in ascending order of `line_code` and
        then `created_at`, each evaluated over only the complaints and units not
        already consumed; a line that fires emits a signal and consumes what
        remains in its scope."

        Design: Difficulty/combinatorial_formula/trend_gate_requires_both_weighted_count_and_rate
        """
        world = _seed_two_lots_one_firing(api)

        run_quality_ops(api, world, dry_run=False)

        for scope_level in ("LINE", "PLANT"):
            _rows, meta = validate_paginated(
                api.list_trend_signals(
                    world.headers("ql1"), {"scope_level": scope_level}
                )
            )
            assert meta["total_count"] == 0, f"a {scope_level} signal was emitted"

    def test_every_plain_foreign_material_complaint_scores_the_same_band(self, api):
        """Forty points with no object, no medical attention and no symptoms bands as S3.

        PRD: "A complaint is eligible only when it has a resolved `lot_id` and
        its `handling_status` is not `DUPLICATE`."

        Design: Difficulty/combinatorial_formula/trend_gate_requires_both_weighted_count_and_rate
        """
        world = _seed_two_lots_one_firing(api)

        for key in ("b1", "b2", "b3", "c1", "c2"):
            complaint = validate_success(
                api.get_complaint(
                    world["complaints"][key]["id"], world.headers("sup1")
                )
            )
            assert_severity(complaint, provisional_score=40.00, provisional_band="S3")
            assert complaint["effective_severity_band"] == "S3"
            assert complaint["handling_status"] == "INTAKE"
