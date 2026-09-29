"""Behaviour pinned at the exact boundary value and one step away from it."""

from test_helpers import (
    add_complaint,
    add_contact,
    add_lot,
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
# The severe band cuts at exactly ninety
# ---------------------------------------------------------------------------
def _seed_band_boundary_complaints(api):
    """Three complaints on an unregulated lot for a consumer in no vulnerable cohort."""
    world = seed_base_world(
        api,
        actor_keys=("ag1", "sup1"),
        consumer={"is_vulnerable_flag": False},
        product="mug",
        lot={"batch_code": "LOT-N", "code_date": "2026-07-12T00:00:00Z"},
    )
    add_contact(api, world, "ct1", channel="WEB")
    add_complaint(
        api,
        world,
        "cpa",
        complaint_type="FOREIGN_MATERIAL",
        reported_batch_code="LOTN",
        foreign_object_class="HARD_BLUNT",
        hospitalization=True,
        vulnerable_consumer=False,
    )
    add_complaint(
        api,
        world,
        "cpb",
        complaint_type="PACKAGING",
        reported_batch_code="LOTN",
        foreign_object_class="HARD_SHARP",
        medical_attention_sought=True,
        symptom_codes=["CUT", "PAIN", "SWELLING", "BLEEDING"],
        vulnerable_consumer=False,
    )
    add_complaint(
        api,
        world,
        "cpc",
        complaint_type="PACKAGING",
        reported_batch_code="LOTN",
        foreign_object_class="HARD_SHARP",
        medical_attention_sought=True,
        symptom_codes=["CUT", "PAIN", "SWELLING", "BLEEDING", "NAUSEA", "HEADACHE"],
        vulnerable_consumer=False,
    )
    return world


class TestSeverityBandBoundary:
    def test_a_score_of_exactly_ninety_bands_as_the_most_severe(self, api):
        """Forty plus fifteen plus thirty-five lands on the boundary inclusively.

        PRD: "Its `provisional_severity_band` is `S1` when the score is at least
        90, otherwise `S2` when it is at least 60, otherwise `S3` when it is at
        least 30, and otherwise `S4`."

        Design: Difficulty/boundary_precision_check/severity_band_boundary_at_exactly_ninety
        """
        world = _seed_band_boundary_complaints(api)

        assert_severity(
            world["complaints"]["cpa"], provisional_score=90.00, provisional_band="S1"
        )

    def test_one_point_below_the_boundary_bands_one_step_milder(self, api):
        """Twenty plus thirty plus twenty-five plus fourteen misses the boundary by a point.

        PRD: "At intake — and until adjudication happens —
        `effective_severity_band` equals `provisional_severity_band`."

        Design: Difficulty/boundary_precision_check/severity_band_boundary_at_exactly_ninety
        """
        world = _seed_band_boundary_complaints(api)
        complaint = world["complaints"]["cpb"]

        assert_severity(complaint, provisional_score=89.00, provisional_band="S2")
        assert complaint["effective_severity_band"] == "S2"

    def test_only_the_first_four_symptom_codes_score(self, api):
        """Six symptoms score exactly what four score.

        PRD: "The number of scoring symptoms is the count of entries in
        `symptom_codes`, or 4 if there are more than 4 — only the first four
        reported symptoms score."

        Design: Difficulty/boundary_precision_check/severity_band_boundary_at_exactly_ninety
        """
        world = _seed_band_boundary_complaints(api)

        four = world["complaints"]["cpb"]
        six = world["complaints"]["cpc"]
        assert_two_decimal_value(
            six["provisional_severity_score"], four["provisional_severity_score"]
        )
        assert_severity(six, provisional_score=89.00, provisional_band="S2")

    def test_inert_multipliers_leave_the_adjudicated_score_on_the_boundary(self, api):
        """With no vulnerability and no regulated food the additive total survives triage.

        PRD: "The vulnerability condition is satisfied when the complaint's own
        `vulnerable_consumer` flag is true or the consumer's standing
        `is_vulnerable_flag` is true; when it holds, the additive total is
        multiplied by 1.15 and the product is rounded half up to 2 decimal
        places, and when it does not hold the additive total simply carries
        forward unchanged."

        Design: Difficulty/boundary_precision_check/severity_band_boundary_at_exactly_ninety
        """
        world = _seed_band_boundary_complaints(api)

        severe = triage(api, world, world["complaints"]["cpa"]["id"])
        mild = triage(api, world, world["complaints"]["cpb"]["id"])

        assert_severity(severe, adjudicated_score=90.00, adjudicated_band="S1")
        assert_severity(mild, adjudicated_score=89.00, adjudicated_band="S2")

        lot = validate_success(
            api.get_production_lot(world["lot"]["id"], world.headers("sup1"))
        )
        assert lot["release_status"] == "HOLD"


# ---------------------------------------------------------------------------
# A zero denominator on the rate read
# ---------------------------------------------------------------------------
def _seed_degenerate_denominators(api):
    """One lot with no units at all and one with a single unit, a complaint each."""
    world = seed_base_world(api, actor_keys=("ag1", "sup1"), create_lot=False)
    add_lot(
        api,
        world,
        "lotzero",
        batch_code="LOT-ZERO",
        code_date="2026-07-13T00:00:00Z",
        units_produced=0,
    )
    add_lot(
        api,
        world,
        "lotone",
        batch_code="LOT-ONE",
        code_date="2026-07-14T00:00:00Z",
        units_produced=1,
    )
    add_contact(api, world, "ct1", channel="EMAIL")
    add_complaint(
        api, world, "cpz", complaint_type="QUALITY", reported_batch_code="LOTZERO"
    )
    add_complaint(
        api, world, "cpo", complaint_type="QUALITY", reported_batch_code="LOTONE"
    )
    return world


class TestZeroUnitDenominator:
    def test_zero_denominator_is_reported_as_undefined_rather_than_divided(self, api):
        """No error, no division, and a sentinel flag instead.

        PRD: "In both variants, when `units_produced` is 0 the rate is reported
        as 0.00 with `rate_undefined` true, and no division is attempted and no
        error is raised; otherwise `rate_ppm` is the numerator divided by
        `units_produced`, multiplied by one million, rounded half up to 2 decimal
        places, with `rate_undefined` false."

        Design: Difficulty/boundary_precision_check/zero_unit_denominator_returns_undefined_not_error
        """
        world = _seed_degenerate_denominators(api)

        response = api.get_lot_complaint_rate(
            world["lots"]["lotzero"]["id"],
            world.headers("sup1"),
            {"variant": "provisional"},
        )
        read = validate_success(response, 200)

        assert read["numerator"] == 1
        assert read["units_produced"] == 0
        assert_two_decimal_value(read["rate_ppm"], 0.00)
        assert read["rate_undefined"] is True

    def test_smallest_non_zero_denominator_gives_the_largest_finite_rate(self, api):
        """One complaint against one unit reads a million parts per million.

        PRD: "Reading a lot's rate reports `production_lot_id`, the `variant`
        applied, the `numerator` used, the lot's `units_produced`, the resulting
        `rate_ppm`, and a `rate_undefined` flag."

        Design: Difficulty/boundary_precision_check/zero_unit_denominator_returns_undefined_not_error
        """
        world = _seed_degenerate_denominators(api)

        read = validate_success(
            api.get_lot_complaint_rate(
                world["lots"]["lotone"]["id"],
                world.headers("sup1"),
                {"variant": "provisional"},
            )
        )

        assert read["numerator"] == 1
        assert read["units_produced"] == 1
        assert_two_decimal_value(read["rate_ppm"], 1000000.00)
        assert read["rate_undefined"] is False

    def test_only_the_flag_distinguishes_an_empty_lot_from_a_clean_one(self, api):
        """The zero-denominator lot reports the same number a clean lot would.

        PRD: "The `observed_rate_ppm` is 0.00 when `units_in_scope` is 0, and
        otherwise `weighted_complaint_count` divided by `units_in_scope`,
        multiplied by one million, rounded half up to 2 decimal places."

        Design: Difficulty/boundary_precision_check/zero_unit_denominator_returns_undefined_not_error
        """
        world = _seed_degenerate_denominators(api)

        undefined = validate_success(
            api.get_lot_complaint_rate(
                world["lots"]["lotzero"]["id"], world.headers("sup1")
            )
        )
        assert_two_decimal_value(undefined["rate_ppm"], 0.00)
        assert undefined["rate_undefined"] is True


# ---------------------------------------------------------------------------
# Both detection gates exercised on their inclusive boundary
# ---------------------------------------------------------------------------
def _seed_three_lots_for_the_checkpoint(api):
    """Nine complaints spread over lots that sit on, above and below the gates."""
    world = seed_base_world(
        api, actor_keys=("ag1", "ql1"), product="mug", create_lot=False
    )
    add_lot(
        api, world, "lotb", product_key="mug", batch_code="LOT-B",
        code_date="2026-07-10T00:00:00Z", units_produced=100000,
    )
    add_lot(
        api, world, "lotc", product_key="mug", batch_code="LOT-C",
        code_date="2026-07-11T00:00:00Z", units_produced=40000,
    )
    add_lot(
        api, world, "lotd", product_key="mug", batch_code="LOT-D",
        code_date="2026-07-12T00:00:00Z", units_produced=200000,
    )
    add_contact(api, world, "ct1", channel="SOCIAL")
    for index in range(1, 4):
        add_complaint(
            api, world, f"b{index}", complaint_type="FOREIGN_MATERIAL",
            reported_batch_code="LOTB",
        )
    for index in range(1, 3):
        add_complaint(
            api, world, f"c{index}", complaint_type="FOREIGN_MATERIAL",
            reported_batch_code="LOTC",
        )
    add_complaint(
        api, world, "d1", complaint_type="ILLNESS", reported_batch_code="LOTD",
        medical_attention_sought=True,
    )
    for index in range(2, 5):
        add_complaint(
            api, world, f"d{index}", complaint_type="FOREIGN_MATERIAL",
            reported_batch_code="LOTD",
        )
    set_clock(api, "2026-08-02T00:00:00Z")
    return world


class TestOpsRunFiresOnBothInclusiveBoundaries:
    def test_weighted_count_boundary_is_inclusive(self, api):
        """Three S3 complaints weigh exactly the minimum weighted count and fire.

        PRD: "For a given scope, `weighted_complaint_count` is the sum of those
        weights carried to 2 decimal places, and `units_in_scope` is the sum of
        `units_produced` over the lots in that scope."

        Design: Difficulty/boundary_precision_check/ops_run_fires_at_exact_weighted_count_and_exact_threshold_ppm
        """
        world = _seed_three_lots_for_the_checkpoint(api)

        run_quality_ops(api, world, dry_run=False)

        signals, meta = validate_paginated(
            api.list_trend_signals(
                world.headers("ql1"), {"lot_id": world["lots"]["lotb"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert_two_decimal_value(signals[0]["weighted_complaint_count"], 3.00)
        assert signals[0]["units_in_scope"] == 100000
        assert_two_decimal_value(signals[0]["observed_rate_ppm"], 30.00)

    def test_rate_boundary_is_inclusive(self, api):
        """Five weighted points over 200,000 units read exactly the lot threshold.

        PRD: "A scope fires when **both** conditions hold, each comparison
        inclusive: `weighted_complaint_count` is at least 3.0, and
        `observed_rate_ppm` is at least the `threshold_ppm` for that scope level
        — 25.0 for `LOT`, 12.0 for `LINE`, and 6.0 for `PLANT`."

        Design: Difficulty/boundary_precision_check/ops_run_fires_at_exact_weighted_count_and_exact_threshold_ppm
        """
        world = _seed_three_lots_for_the_checkpoint(api)

        run_quality_ops(api, world, dry_run=False)

        signals, meta = validate_paginated(
            api.list_trend_signals(
                world.headers("ql1"), {"lot_id": world["lots"]["lotd"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        signal = signals[0]
        assert_two_decimal_value(signal["weighted_complaint_count"], 5.00)
        assert signal["units_in_scope"] == 200000
        assert_two_decimal_value(signal["observed_rate_ppm"], 25.00)
        assert_two_decimal_value(signal["threshold_ppm"], 25.0)
        assert signal["membership_count"] == 4

    def test_scope_below_the_count_gate_never_fires_and_the_waterfall_stops(self, api):
        """Two signals, seven memberships, and no wider scope behind them.

        PRD: "The periodic quality checkpoint applies these tests in a
        **narrowest-scope-wins waterfall**, so that no complaint is ever counted
        into two signals."

        Design: Difficulty/boundary_precision_check/ops_run_fires_at_exact_weighted_count_and_exact_threshold_ppm
        """
        world = _seed_three_lots_for_the_checkpoint(api)

        run = run_quality_ops(api, world, dry_run=False)
        assert run["signals_created_count"] == 2
        assert run["memberships_created_count"] == 7

        _rows, lotc_meta = validate_paginated(
            api.list_trend_signals(
                world.headers("ql1"), {"lot_id": world["lots"]["lotc"]["id"]}
            )
        )
        assert lotc_meta["total_count"] == 0

        for scope_level in ("LINE", "PLANT"):
            _rows, meta = validate_paginated(
                api.list_trend_signals(
                    world.headers("ql1"), {"scope_level": scope_level}
                )
            )
            assert meta["total_count"] == 0
