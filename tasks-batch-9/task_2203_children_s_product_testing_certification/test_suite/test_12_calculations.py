"""Computed fields pinned at their constants, their tier edges and their input filters."""

from test_helpers import (
    ApiErrorId,
    assert_distribution_ledger,
    factories,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    COORDINATOR_HEADERS,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
)


STARTUP_CLOCK = "2026-08-01T00:00:00Z"

FLAT_CATEGORY = {"durable_infant_product": False, "sampling_floor_units": 1}

LEAD_RULE = {
    "rule_code": "LEAD_CONTENT_100",
    "hazard_class": "LEAD_CONTENT",
    "severity_weight": 9,
    "limit_value": 100,
    "limit_unit": "PPM",
    "limit_comparator": "AT_OR_BELOW",
    "periodic_interval_months": 12,
    "base_method_fee_cents": 18700,
}

SMALL_PARTS_RULE = {
    "rule_code": "SMALL_PARTS_01",
    "hazard_class": "MECHANICAL_HAZARD",
    "severity_weight": 8,
    "limit_value": 31,
    "limit_unit": "MILLIMETRE",
    "applicability_condition": "IF_SMALL_PART_PRESENT",
}

PHTHALATE_RULE = {
    "rule_code": "PHTHALATE_1000",
    "hazard_class": "PHTHALATES",
    "severity_weight": 7,
    "limit_value": 1000,
    "limit_unit": "PPM",
    "applicability_condition": "IF_PLASTICIZED_PART",
}

METAL_COATING_RULE = {
    "rule_code": "METAL_COATING_04",
    "hazard_class": "LEAD_CONTENT",
    "severity_weight": 7,
    "limit_value": 90,
    "limit_unit": "PPM",
    "applicability_condition": "IF_ACCESSIBLE_METAL",
}

SURFACE_PAINT_RULE = {
    "rule_code": "SURFACE_PAINT_02",
    "hazard_class": "LEAD_PAINT",
    "severity_weight": 5,
    "limit_value": 90,
    "limit_unit": "PPM",
    "applicability_condition": "IF_PAINTED_SURFACE",
}

PAINTED_SHELL = {
    "part_name": "Moulded painted shell",
    "material_class": "PAINTED_COATING",
    "accessible_to_child": True,
    "small_part_when_detached": False,
}

PLASTICIZED_GRIP = {
    "part_name": "Plasticized handlebar grip",
    "material_class": "PLASTICIZED_PLASTIC",
    "accessible_to_child": True,
    "small_part_when_detached": True,
}

ACCESSIBLE_METAL_CLIP = {
    "part_name": "Exposed metal clip",
    "material_class": "ACCESSIBLE_METAL",
    "accessible_to_child": True,
    "small_part_when_detached": False,
}


def _five_rule_library(api):
    """One category carrying all five applicability predicates at four severities."""
    fx.set_clock(api, STARTUP_CLOCK)
    env = fx.regulatory_env(
        api,
        rule_specs=[
            dict(LEAD_RULE),
            dict(SMALL_PARTS_RULE),
            dict(PHTHALATE_RULE),
            dict(METAL_COATING_RULE),
            dict(SURFACE_PAINT_RULE),
        ],
        category=dict(FLAT_CATEGORY),
    )
    (
        env["lead"],
        env["small_parts"],
        env["phthalate"],
        env["metal"],
        env["paint"],
    ) = env["rules"]
    env["supplier"] = fx.create_supplier(api)
    return env


def _scope_product(api, env, part_specs):
    product = fx.create_product(api, env["category"]["id"])
    for spec in part_specs:
        fx.add_part(api, product["id"], env["supplier"]["id"], **spec)
    return fx.submit_for_certification(api, product["id"], "FULL_PRODUCT_TEST")


class TestRuleDerivationOrdersAndEvaluatesItsPredicates:
    """The derived array's membership and its exact ordering."""

    def test_each_predicate_is_evaluated_against_the_actual_part_list(self, api):
        """PRD 3.1: "The five conditions are `ALWAYS`, which always applies;
        `IF_PAINTED_SURFACE`, which applies when the product has at least one part of
        material class `PAINTED_COATING`; `IF_PLASTICIZED_PART`, which applies when at
        least one part is `PLASTICIZED_PLASTIC`; `IF_SMALL_PART_PRESENT`, which applies
        when at least one part fits the small-parts cylinder when detached; and
        `IF_ACCESSIBLE_METAL`, which applies when at least one part is of material class
        `ACCESSIBLE_METAL` **and** is also marked accessible to a child."

        Design: Corner/calculations/corner_calculations_rule_set_derivation_orders_by_severity_then_code_and_evaluates_predicates
        """
        env = _five_rule_library(api)
        alpha = _scope_product(api, env, [PAINTED_SHELL, PLASTICIZED_GRIP])

        assert alpha["required_rule_ids"] == [
            env["lead"]["id"],
            env["small_parts"]["id"],
            env["phthalate"]["id"],
            env["paint"]["id"],
        ]
        assert env["metal"]["id"] not in alpha["required_rule_ids"]

    def test_equal_severity_is_broken_by_rule_code_ascending(self, api):
        """PRD 3.3: "Third, walk the candidate mappings in a fixed order — descending
        `severity_weight` of the mapped rule first, and among rules of equal weight
        ascending `rule_code`; because `rule_code` is unique, this ordering never ties and
        no identifier is ever consulted as a fallback."

        Design: Corner/calculations/corner_calculations_rule_set_derivation_orders_by_severity_then_code_and_evaluates_predicates
        """
        env = _five_rule_library(api)
        beta = _scope_product(
            api, env, [PAINTED_SHELL, PLASTICIZED_GRIP, ACCESSIBLE_METAL_CLIP]
        )

        # METAL_COATING_04 was registered after PHTHALATE_1000 yet sorts ahead of it.
        assert beta["required_rule_ids"] == [
            env["lead"]["id"],
            env["small_parts"]["id"],
            env["metal"]["id"],
            env["phthalate"]["id"],
            env["paint"]["id"],
        ]

    def test_the_summary_reports_the_same_derived_set_as_uncovered(self, api):
        """PRD 3.3: "For each mapping in that order, evaluate its
        `applicability_condition` against the gathered parts using the five predicates of
        §3.1, and when the condition holds and the rule is not already in the result,
        append the rule to the result."

        Design: Corner/calculations/corner_calculations_rule_set_derivation_orders_by_severity_then_code_and_evaluates_predicates
        """
        env = _five_rule_library(api)
        alpha = _scope_product(api, env, [PAINTED_SHELL, PLASTICIZED_GRIP])

        summary = fx.get_summary(api, alpha["id"])
        assert summary["required_rule_ids"] == alpha["required_rule_ids"]
        assert sorted(summary["uncovered_rule_ids"]) == sorted(alpha["required_rule_ids"])
        assert summary["covered_rule_ids"] == []


def _three_mapping_library(api):
    """Three always-applicable mappings: one current, one future, one retired."""
    fx.set_clock(api, STARTUP_CLOCK)
    env = fx.regulatory_env(
        api,
        rule_specs=[
            dict(LEAD_RULE, effective_from=STARTUP_CLOCK),
            dict(PHTHALATE_RULE, applicability_condition="ALWAYS", effective_from="2026-09-01T00:00:00Z"),
            dict(
                SMALL_PARTS_RULE,
                applicability_condition="ALWAYS",
                effective_from="2026-01-01T00:00:00Z",
            ),
        ],
        category=dict(FLAT_CATEGORY),
    )
    env["lead"], env["phthalate"], env["small_parts"] = env["rules"]
    env["lead_mapping"], env["phthalate_mapping"], env["small_parts_mapping"] = env["mappings"]
    env["supplier"] = fx.create_supplier(api)
    return env


class TestRuleDerivationFiltersItsCandidateMappings:
    """Only ACTIVE mappings already in force reach the predicates."""

    def test_a_future_mapping_and_a_retired_mapping_are_both_excluded(self, api):
        """PRD 3.3: "First, gather the candidate mappings: every category-rule mapping
        whose `category_id` equals the product's `category_id`, whose `mapping_state` is
        `ACTIVE`, and whose `effective_from` is at or before the logical clock — the lower
        bound is inclusive, so a mapping effective exactly now counts."

        Design: Corner/calculations/corner_calculations_rule_set_derivation_input_set_excludes_future_and_retired_mappings
        """
        env = _three_mapping_library(api)
        retired = validate_success(
            api.retire_mapping(env["small_parts_mapping"]["id"], headers=ADMIN_HEADERS), 200
        )
        assert retired["mapping_state"] == "RETIRED"
        assert retired["version"] == env["small_parts_mapping"]["version"] + 1

        first = _scope_product(api, env, [PAINTED_SHELL])
        assert first["required_rule_ids"] == [env["lead"]["id"]]

    def test_the_scoped_snapshot_is_not_re_derived_when_the_clock_moves(self, api):
        """PRD 3.1: "Products that have already been scoped keep the rule snapshot they
        were scoped against, so a mid-programme retirement never silently narrows an
        in-flight certification."

        Design: Corner/calculations/corner_calculations_rule_set_derivation_input_set_excludes_future_and_retired_mappings
        """
        env = _three_mapping_library(api)
        api.retire_mapping(env["small_parts_mapping"]["id"], headers=ADMIN_HEADERS)
        first = _scope_product(api, env, [PAINTED_SHELL])

        fx.set_clock(api, "2026-09-01T00:00:00Z")
        second = _scope_product(api, env, [PAINTED_SHELL])
        assert second["required_rule_ids"] == [env["lead"]["id"], env["phthalate"]["id"]]

        assert fx.get_product(api, first["id"])["required_rule_ids"] == [env["lead"]["id"]]

    def test_retirement_frees_the_category_and_rule_pair(self, api):
        """PRD 3.1: "Retirement also frees the category-and-rule pair, so a fresh `ACTIVE`
        mapping for the same pair may be created afterwards."

        Design: Corner/calculations/corner_calculations_rule_set_derivation_input_set_excludes_future_and_retired_mappings
        """
        env = _three_mapping_library(api)
        api.retire_mapping(env["small_parts_mapping"]["id"], headers=ADMIN_HEADERS)

        replacement = fx.map_rule(
            api,
            env["category"]["id"],
            env["small_parts"]["id"],
            applicability_condition="ALWAYS",
            effective_from=STARTUP_CLOCK,
        )
        assert replacement["mapping_state"] == "ACTIVE"
        assert replacement["id"] != env["small_parts_mapping"]["id"]


def _one_rule_library(api):
    """A single always-applicable rule plus a supplier, with no category yet."""
    fx.set_clock(api, STARTUP_CLOCK)
    return {
        "rule": fx.create_rule(api, **dict(LEAD_RULE)),
        "supplier": fx.create_supplier(api),
    }


def _activated_plan_for(api, env, category_overrides, projected_annual_units, **plan_overrides):
    """Register a category, a product in it and one activated sampling plan."""
    category = fx.create_category(api, **category_overrides)
    fx.map_rule(
        api,
        category["id"],
        env["rule"]["id"],
        applicability_condition="ALWAYS",
        effective_from="2026-01-01T00:00:00Z",
    )
    product = fx.create_product(
        api, category["id"], projected_annual_units=projected_annual_units
    )
    fx.add_part(api, product["id"], env["supplier"]["id"], **PAINTED_SHELL)
    fx.submit_for_certification(api, product["id"], "FULL_PRODUCT_TEST")
    plan = fx.create_plan(api, product["id"], **plan_overrides)
    return fx.activate_plan(api, plan["id"])


class TestSampleSizingConstantsFloorAndCap:
    """The floor, the ceiling and the durable multiplier each take their turn."""

    def test_the_category_floor_lifts_a_small_raw_figure(self, api):
        """PRD 3.5: "Finally, take the greater of that figure and the category's
        `sampling_floor_units`, then take the lesser of that result and the hard ceiling of
        40 sample units; the outcome is written to `units_authorized`."

        Design: Corner/calculations/corner_calculations_sampling_size_constants_floor_and_cap_dominate_the_raw_figure
        """
        env = _one_rule_library(api)
        plan = _activated_plan_for(
            api,
            env,
            {"durable_infant_product": False, "sampling_floor_units": 10},
            100,
        )
        # The raw figure is (3 + ceil(100 / 2500)) * 1 == 4, below the floor of 10.
        assert plan["units_authorized"] == 10
        assert plan["units_committed"] == 0
        assert plan["units_available"] == 10

    def test_the_durable_multiplier_is_applied_before_the_floor_and_the_cap(self, api):
        """PRD 3.5: "Next, if the product's category is flagged `durable_infant_product`,
        double the running figure."

        Design: Corner/calculations/corner_calculations_sampling_size_constants_floor_and_cap_dominate_the_raw_figure
        """
        env = _one_rule_library(api)
        plan = _activated_plan_for(
            api,
            env,
            {"durable_infant_product": True, "sampling_floor_units": 4},
            6000,
        )
        # (3 + ceil(6000 / 2500)) * 1 == 6, doubled to 12, which already clears the floor.
        assert plan["units_authorized"] == 12
        assert plan["units_available"] == 12

    def test_the_hard_ceiling_of_forty_units_caps_a_large_raw_figure(self, api):
        """PRD 3.5: "For the `INITIAL` variant, divide the product's
        `projected_annual_units` by 2,500 and round the quotient **up** to the next whole
        number to obtain the volume component, then add a base of 3 and multiply the sum by
        the rule count."

        Design: Corner/calculations/corner_calculations_sampling_size_constants_floor_and_cap_dominate_the_raw_figure
        """
        env = _one_rule_library(api)
        plan = _activated_plan_for(
            api,
            env,
            {"durable_infant_product": False, "sampling_floor_units": 1},
            100000,
        )
        # (3 + ceil(100000 / 2500)) * 1 == 43, above the ceiling.
        assert plan["units_authorized"] == 40
        assert plan["units_committed"] == 0
        assert plan["units_available"] == 40


class TestSampleSizingVariantFollowsPlanType:
    """Which input the sizing consults is decided by `plan_type` alone."""

    def test_an_initial_plan_ignores_the_supplied_baseline(self, api):
        """PRD 3.5: "An initial plan covers a certification that has not yet produced
        anything, so its volume input is the product's forward-looking
        `projected_annual_units`."

        Design: Corner/calculations/corner_calculations_sampling_size_variant_selection_follows_plan_type_not_volume
        """
        env = _one_rule_library(api)
        plan = _activated_plan_for(
            api,
            env,
            dict(FLAT_CATEGORY),
            6000,
            plan_type="INITIAL",
            baseline_units_produced=40000,
        )
        assert plan["plan_type"] == "INITIAL"
        assert plan["units_authorized"] == 6
        assert plan["baseline_units_produced"] == 40000

    def test_a_periodic_plan_ignores_the_products_projection(self, api):
        """PRD 3.5: "For the `PERIODIC` variant, divide the plan's
        `baseline_units_produced` by 5,000 and round the quotient **down** to the preceding
        whole number to obtain the volume component, then add a base of 1 and multiply the
        sum by the rule count."

        Design: Corner/calculations/corner_calculations_sampling_size_variant_selection_follows_plan_type_not_volume
        """
        env = _one_rule_library(api)
        plan = _activated_plan_for(
            api,
            env,
            dict(FLAT_CATEGORY),
            100,
            plan_type="PERIODIC",
            baseline_units_produced=20000,
        )
        assert plan["plan_type"] == "PERIODIC"
        assert plan["units_authorized"] == 5
        assert plan["units_available"] == 5


EDGE_RULE_A = {
    "rule_code": "EDGE_METHOD_A",
    "hazard_class": "LEAD_CONTENT",
    "severity_weight": 9,
    "limit_value": 100,
    "limit_unit": "PPM",
    "base_method_fee_cents": 25000,
}

EDGE_RULE_B = {
    "rule_code": "EDGE_METHOD_B",
    "hazard_class": "PHTHALATES",
    "severity_weight": 4,
    "limit_value": 1000,
    "limit_unit": "PPM",
    "base_method_fee_cents": 16667,
}


def _tier_edge_env(api):
    """Two rules priced so that one cent separates the two expedite tiers."""
    fx.set_clock(api, STARTUP_CLOCK)
    env = fx.booking_env(
        api,
        rule_specs=[dict(EDGE_RULE_A), dict(EDGE_RULE_B)],
        category=dict(FLAT_CATEGORY),
        product={"projected_annual_units": 20000},
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 4},
        accreditation_overrides=[
            {"fee_surcharge_basis_points": 0},
            {"fee_surcharge_basis_points": 0},
        ],
        plan_overrides={"plan_type": "INITIAL"},
    )
    assert env["plan"]["units_authorized"] == 22
    env["edge_a"], env["edge_b"] = env["rules"]
    return env


def _price(api, env, rule, sample_count, expedite_requested):
    return fx.book_order(
        api,
        env["product"]["id"],
        env["plan"]["id"],
        env["laboratory"]["id"],
        rule["id"],
        sample_count=sample_count,
        expedite_requested=expedite_requested,
    )


class TestExpediteTierBoundariesAreRegressive:
    """A subtotal one cent larger buys a cheaper invoice."""

    def test_a_subtotal_of_exactly_fifty_thousand_stays_in_the_first_tier(self, api):
        """PRD 3.6: "Step two determines the expedite rate: it is zero basis points when
        `expedite_requested` is false; otherwise it is 1500 basis points when the subtotal
        is at or below 50,000 cents, 1000 basis points when the subtotal is at or below
        150,000 cents, and 600 basis points for any larger subtotal — the rate falls as the
        order grows, because expedited handling of a large job costs proportionally less."

        Design: Corner/calculations/corner_calculations_invoice_expedite_tier_boundaries_are_regressive_at_the_edge
        """
        env = _tier_edge_env(api)
        order = _price(api, env, env["edge_a"], 2, True)
        assert order["line_fee_cents"] == 50000
        assert order["invoice_total_cents"] == 57500

    def test_one_cent_past_the_ceiling_lowers_the_invoice_total(self, api):
        """PRD 3.6: "The expedite fee is the subtotal multiplied by that rate divided by
        10000, rounded half up to whole cents."

        Design: Corner/calculations/corner_calculations_invoice_expedite_tier_boundaries_are_regressive_at_the_edge
        """
        env = _tier_edge_env(api)
        at_the_ceiling = _price(api, env, env["edge_a"], 2, True)
        one_cent_past = _price(api, env, env["edge_b"], 3, True)

        assert one_cent_past["line_fee_cents"] == 50001
        assert one_cent_past["invoice_total_cents"] == 55001
        # The larger job carries the smaller invoice; the step is genuinely regressive.
        assert one_cent_past["invoice_total_cents"] < at_the_ceiling["invoice_total_cents"]

    def test_without_expedite_the_rate_is_zero_at_either_tier(self, api):
        """PRD 3.6: "Step four determines the reliance discount, which exists only for
        products on the component reliance path: the rate is zero basis points whenever the
        product's `evidence_path` is anything other than `COMPONENT_RELIANCE`; otherwise it
        is 1200 basis points when the total before discount is at or above 120,000 cents,
        800 basis points when the total before discount is at or above 60,000 cents, and
        zero basis points below that."

        Design: Corner/calculations/corner_calculations_invoice_expedite_tier_boundaries_are_regressive_at_the_edge
        """
        env = _tier_edge_env(api)
        routine = _price(api, env, env["edge_a"], 2, False)
        assert routine["expedite_requested"] is False
        assert routine["line_fee_cents"] == 50000
        # No expedite fee and no reliance discount on the full-product-test path.
        assert routine["invoice_total_cents"] == 50000
        assert fx.get_product(api, env["product"]["id"])["evidence_path"] == "FULL_PRODUCT_TEST"


DISCOUNT_RULES = [
    {
        "rule_code": "DISCOUNT_BAND_LOW",
        "hazard_class": "LEAD_CONTENT",
        "severity_weight": 9,
        "limit_value": 100,
        "limit_unit": "PPM",
        "base_method_fee_cents": 20000,
    },
    {
        "rule_code": "DISCOUNT_BAND_NONE",
        "hazard_class": "PHTHALATES",
        "severity_weight": 7,
        "limit_value": 1000,
        "limit_unit": "PPM",
        "base_method_fee_cents": 59999,
    },
    {
        "rule_code": "DISCOUNT_BAND_HIGH",
        "hazard_class": "FLAMMABILITY",
        "severity_weight": 5,
        "limit_value": 3,
        "limit_unit": "PERCENT_BY_WEIGHT",
        "base_method_fee_cents": 40000,
    },
]

ZERO_SURCHARGE = [{"fee_surcharge_basis_points": 0} for _ in range(3)]


def _reliance_pricing_env(api):
    """A component-reliance product whose three rules straddle both discount thresholds."""
    fx.set_clock(api, STARTUP_CLOCK)
    env = fx.booking_env(
        api,
        evidence_path="COMPONENT_RELIANCE",
        rule_specs=[dict(spec) for spec in DISCOUNT_RULES],
        category=dict(FLAT_CATEGORY),
        product={"projected_annual_units": 40000},
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 6},
        accreditation_overrides=[dict(spec) for spec in ZERO_SURCHARGE],
        plan_overrides={"plan_type": "INITIAL"},
    )
    env["low"], env["none"], env["high"] = env["rules"]
    return env


def _full_test_sibling(api, env):
    """A second product in the same category taken down the full-product-test path."""
    product = fx.create_product(
        api, env["category"]["id"], projected_annual_units=40000
    )
    fx.add_part(api, product["id"], env["supplier"]["id"], **PAINTED_SHELL)
    fx.submit_for_certification(api, product["id"], "FULL_PRODUCT_TEST")
    plan = fx.create_plan(api, product["id"], plan_type="INITIAL")
    return {"product": product, "plan": fx.activate_plan(api, plan["id"])}


class TestRelianceDiscountThresholdsAreInclusive:
    """Both discount bands are entered at their exact thresholds, high band first."""

    def test_a_total_of_exactly_sixty_thousand_earns_the_standard_band(self, api):
        """PRD 3.6: "Step four determines the reliance discount, which exists only for
        products on the component reliance path: the rate is zero basis points whenever the
        product's `evidence_path` is anything other than `COMPONENT_RELIANCE`; otherwise it
        is 1200 basis points when the total before discount is at or above 120,000 cents,
        800 basis points when the total before discount is at or above 60,000 cents, and
        zero basis points below that."

        Design: Corner/calculations/corner_calculations_invoice_reliance_discount_thresholds_use_inclusive_comparisons
        """
        env = _reliance_pricing_env(api)
        order = _price(api, env, env["low"], 3, False)
        assert order["line_fee_cents"] == 60000
        assert order["invoice_total_cents"] == 55200

    def test_one_cent_below_earns_nothing_while_the_high_band_wins_at_its_own_threshold(
        self, api
    ):
        """PRD 3.6: "The discount is the total before discount multiplied by that rate
        divided by 10000, rounded half up to whole cents."

        Design: Corner/calculations/corner_calculations_invoice_reliance_discount_thresholds_use_inclusive_comparisons
        """
        env = _reliance_pricing_env(api)
        below = _price(api, env, env["none"], 1, False)
        assert below["line_fee_cents"] == 59999
        assert below["invoice_total_cents"] == 59999

        high = _price(api, env, env["high"], 3, False)
        assert high["line_fee_cents"] == 120000
        # 1200 basis points takes 14400; the 800 bp band would have taken only 9600.
        assert high["invoice_total_cents"] == 105600

    def test_the_same_order_on_the_full_product_test_path_earns_no_discount(self, api):
        """PRD 3.6: "Step five subtracts the discount from the total before discount, and
        the result is written to `invoice_total_cents`."

        Design: Corner/calculations/corner_calculations_invoice_reliance_discount_thresholds_use_inclusive_comparisons
        """
        env = _reliance_pricing_env(api)
        sibling = _full_test_sibling(api, env)
        undiscounted = fx.book_order(
            api,
            sibling["product"]["id"],
            sibling["plan"]["id"],
            env["laboratory"]["id"],
            env["low"]["id"],
            sample_count=3,
        )
        assert undiscounted["line_fee_cents"] == 60000
        assert undiscounted["invoice_total_cents"] == 60000


def _sibling_with_plan(api, env, part_specs, **product_overrides):
    """A second full-product-test product in the same category, plan already active."""
    product = fx.create_product(api, env["category"]["id"], **product_overrides)
    for spec in part_specs:
        fx.add_part(api, product["id"], env["supplier"]["id"], **spec)
    product = fx.submit_for_certification(api, product["id"], "FULL_PRODUCT_TEST")
    plan = fx.create_plan(api, product["id"], plan_type="INITIAL")
    return {"product": product, "plan": fx.activate_plan(api, plan["id"])}


def _weighted_pair_env(api):
    """Two identical products under a severity-9 rule and a severity-7 rule."""
    fx.set_clock(api, STARTUP_CLOCK)
    env = fx.booking_env(
        api,
        rule_specs=[
            dict(LEAD_RULE),
            dict(PHTHALATE_RULE, applicability_condition="ALWAYS"),
        ],
        category=dict(FLAT_CATEGORY),
        part_specs=[PAINTED_SHELL, PLASTICIZED_GRIP],
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 4},
        plan_overrides={"plan_type": "INITIAL"},
    )
    env["lead"], env["phthalate"] = env["rules"]
    assert env["plan"]["units_authorized"] == 8
    env["beta"] = _sibling_with_plan(api, env, [PAINTED_SHELL, PLASTICIZED_GRIP])
    return env


class TestGapScorePercentageRoundsHalfUp:
    """Half-up rounding on a percentage that lands exactly on a quarter."""

    def test_forty_three_point_seven_five_rounds_up_to_forty_four(self, api):
        """PRD 3.3: "The base figure is 100 whenever the total weight is 0, and otherwise
        100 multiplied by the uncovered weight, divided by the total weight, rounded half up
        to a whole number."

        Design: Corner/calculations/corner_calculations_gap_score_percentage_rounds_half_up_before_penalties
        """
        env = _weighted_pair_env(api)
        fx.run_order_to_pass(
            api,
            env["product"]["id"],
            env["plan"]["id"],
            env["laboratory"]["id"],
            env["lead"]["id"],
            measured_value=40,
        )
        alpha = fx.get_product(api, env["product"]["id"])
        # Uncovered weight 7 of total 16 is 43.75, not truncated to 43.
        assert alpha["risk_weighted_gap_score"] == 44
        assert alpha["compliance_posture"] == "RESTRICTED"

    def test_fifty_six_point_two_five_rounds_down_to_fifty_six(self, api):
        """PRD 3.3: "Sum the `severity_weight` of the covered rules to get the covered
        weight; the uncovered weight is the total weight minus the covered weight."

        Design: Corner/calculations/corner_calculations_gap_score_percentage_rounds_half_up_before_penalties
        """
        env = _weighted_pair_env(api)
        fx.run_order_to_pass(
            api,
            env["beta"]["product"]["id"],
            env["beta"]["plan"]["id"],
            env["laboratory"]["id"],
            env["phthalate"]["id"],
            measured_value=400,
        )
        beta = fx.get_product(api, env["beta"]["product"]["id"])
        # Uncovered weight 9 of total 16 is 56.25: half up, never ceiling.
        assert beta["risk_weighted_gap_score"] == 56
        assert beta["compliance_posture"] == "RESTRICTED"

    def test_neither_penalty_term_is_present_in_those_figures(self, api):
        """PRD 3.3: "Two penalties are then added: 15 points for each noncompliance case on
        this product whose `case_state` is `OPEN`, `STOP_DISTRIBUTION_ISSUED`,
        `RETEST_ORDERED` or `RETEST_FAILED`, and 10 points for each sampling plan on this
        product whose `plan_state` is `RESAMPLE_DUE`."

        Design: Corner/calculations/corner_calculations_gap_score_percentage_rounds_half_up_before_penalties
        """
        env = _weighted_pair_env(api)
        fx.run_order_to_pass(
            api,
            env["product"]["id"],
            env["plan"]["id"],
            env["laboratory"]["id"],
            env["lead"]["id"],
            measured_value=40,
        )
        summary = fx.get_summary(api, env["product"]["id"])
        assert summary["open_case_count"] == 0
        assert summary["resample_due_plan_count"] == 0
        assert summary["risk_weighted_gap_score"] == 44
        assert summary["covered_rule_ids"] == [env["lead"]["id"]]
        assert summary["uncovered_rule_ids"] == [env["phthalate"]["id"]]


PAST_THE_GRACE_PERIOD = "2027-09-05T00:00:00Z"


def _cleared_product_with_a_held_batch(api):
    """A certified product, zero gap score, one furnished certificate over a held batch."""
    fx.set_clock(api, STARTUP_CLOCK)
    env = fx.distributed_env(
        api,
        release=False,
        batch_specs=[{"batch_code": "BRANCH-000801", "quantity": 100}],
        rule_specs=[dict(LEAD_RULE)],
        category=dict(FLAT_CATEGORY),
        product={"projected_annual_units": 2000},
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 4},
        measured_value=40,
        certificate_overrides={"manufacture_date_month": "2026-08"},
    )
    env["batch"] = env["batches"][0]
    return env


def _lapse_the_plan(api, env):
    """Walk the plan through resampling into its terminal lapsed state."""
    fx.set_clock(api, PAST_THE_GRACE_PERIOD)
    resample_due = fx.periodic_review(api, env["plan"]["id"])
    assert resample_due["plan_state"] == "RESAMPLE_DUE"
    lapsed = fx.periodic_review(api, env["plan"]["id"])
    assert lapsed["plan_state"] == "LAPSED"
    return lapsed


class TestPostureBranchOrderPutsSuspensionFirst:
    """A lapsed plan and a zero gap score are both true; the earlier branch wins."""

    def test_a_zero_gap_score_alone_clears_the_product(self, api):
        """PRD 3.3: "Otherwise, a product whose `risk_weighted_gap_score` is exactly 0 is
        `CLEARED`."

        Design: Corner/calculations/corner_calculations_posture_branch_order_puts_suspension_ahead_of_a_zero_gap_score
        """
        env = _cleared_product_with_a_held_batch(api)
        summary = fx.get_summary(api, env["product"]["id"])
        assert summary["risk_weighted_gap_score"] == 0
        assert summary["compliance_posture"] == "CLEARED"
        assert summary["resample_due_plan_count"] == 0

    def test_the_lapsed_plan_branch_outranks_the_zero_score_branch(self, api):
        """PRD 3.3: "The ordering matters in a way implementers routinely get wrong: a
        product holding a lapsed plan **and** a zero gap score is `SUSPENDED`, not
        `CLEARED`, because the lapsed-plan branch is evaluated first."

        Design: Corner/calculations/corner_calculations_posture_branch_order_puts_suspension_ahead_of_a_zero_gap_score
        """
        env = _cleared_product_with_a_held_batch(api)
        fx.set_clock(api, PAST_THE_GRACE_PERIOD)
        fx.periodic_review(api, env["plan"]["id"])
        during_resampling = fx.get_summary(api, env["product"]["id"])
        assert during_resampling["resample_due_plan_count"] == 1
        assert during_resampling["risk_weighted_gap_score"] == 10
        assert during_resampling["compliance_posture"] == "RESTRICTED"

        fx.periodic_review(api, env["plan"]["id"])
        after = fx.get_summary(api, env["product"]["id"])
        assert after["compliance_posture"] == "SUSPENDED"
        assert after["risk_weighted_gap_score"] == 0
        # Branch 5 is a fallback, reached only when no earlier branch matches.
        assert after["compliance_posture"] != "RESTRICTED"
        assert after["resample_due_plan_count"] == 0

    def test_the_suspension_gates_release_and_archival_outranks_it(self, api):
        """PRD 3.3: "A product whose `certification_state` is `DRAFT` or `ARCHIVED` is
        `UNSCOPED`."

        Design: Corner/calculations/corner_calculations_posture_branch_order_puts_suspension_ahead_of_a_zero_gap_score
        """
        env = _cleared_product_with_a_held_batch(api)
        _lapse_the_plan(api, env)

        validate_error(
            api.release_batch(env["batch"]["id"], headers=MANAGER_HEADERS),
            ApiErrorId.PRODUCT_POSTURE_NOT_CLEARED.value,
            422,
        )
        archived = validate_success(
            api.archive_product(env["product"]["id"], headers=ADMIN_HEADERS), 200
        )
        assert archived["certification_state"] == "ARCHIVED"
        assert archived["compliance_posture"] == "UNSCOPED"


TRACEBACK_BATCHES = (
    ("TRACE-000901", "2026-08-01T00:00:00Z"),
    ("TRACE-000902", "2026-08-10T00:00:00Z"),
    ("TRACE-000903", "2026-08-20T00:00:00Z"),
)

FAILING_WINDOW = ("2026-08-15T00:00:00Z", "2026-08-16T00:00:00Z")


def _never_passed_rule_case_env(api):
    """A case whose failed rule has no passing test order anywhere in its history.

    The product's evidence came from a supplier certificate, so the failing rule was
    never proved by a test order; a material change then voided that reliance and made
    product-level testing of the rule admissible.
    """
    fx.set_clock(api, STARTUP_CLOCK)
    env = fx.reliance_env(
        api,
        rule_specs=[dict(LEAD_RULE, component_reliance_allowed=True)],
        category=dict(FLAT_CATEGORY),
        product={"projected_annual_units": 2000},
        part_specs=[PAINTED_SHELL],
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 4},
    )
    product = fx.get_product(api, env["product"]["id"])
    assert product["certification_state"] == "EVIDENCE_COMPLETE"

    certificate = fx.draft_certificate(
        api, product["id"], product["version"], manufacture_date_month="2026-08"
    )
    env["certificate"] = fx.issue_certificate(api, certificate["id"])
    env["batches"] = [
        fx.create_batch(
            api,
            product["id"],
            certificate["id"],
            batch_code=code,
            produced_on=produced_on,
            quantity=100,
        )
        for code, produced_on in TRACEBACK_BATCHES
    ]
    plan = fx.create_plan(api, product["id"], plan_type="INITIAL")
    env["plan"] = fx.activate_plan(api, plan["id"])

    fx.record_material_change(
        api,
        product["id"],
        subject_type="COMPONENT_PART",
        component_part_id=env["parts"][0]["id"],
        change_kind="MATERIAL_SUBSTITUTION",
        description="Supplier substituted the coating resin on the moulded shell.",
    )
    env["product"] = fx.get_product(api, product["id"])
    env["failing_order"] = fx.fail_an_order(
        api,
        env,
        measured_value=250,
        window_start=FAILING_WINDOW[0],
        window_end=FAILING_WINDOW[1],
    )
    env["case"] = fx.sole_case_for_product(api, product["id"])
    assert env["case"]["case_state"] == "OPEN"
    assert env["case"]["failed_rule_id"] == env["rules"][0]["id"]
    return env


class TestCorrectiveScopeFallsBackToProductCreation:
    """With no earlier proof of conformity the traceback reaches the whole history."""

    def test_the_empty_input_set_falls_back_to_the_products_own_creation_instant(
        self, api
    ):
        """PRD 3.9: "Under `LOT_TRACEBACK`, the operator cannot bound the defect and traces
        back to the last proof of conformity: the cutoff is the greatest `reported_at` among
        the product's test orders for the same `failed_rule_id` whose `order_state` is
        `REPORTED_PASS` and whose `reported_at` precedes the failing order's `reported_at`;
        when no such earlier passing order exists, the cutoff falls back to the product's own
        `created_at` — never to an identifier and never to the beginning of time."

        PRD 3.9: "The lower bound is inclusive: a batch produced at exactly the cutoff
        instant is inside the scope."

        Design: Corner/calculations/corner_calculations_corrective_scope_falls_back_to_product_created_at_when_no_prior_pass
        """
        env = _never_passed_rule_case_env(api)
        assert fx.list_orders_for_product(
            api, env["product"]["id"], order_state="REPORTED_PASS"
        ) == []

        case = fx.issue_stop_distribution(api, env["case"]["id"], "LOT_TRACEBACK")
        assert case["scope_variant"] == "LOT_TRACEBACK"
        assert case["scope_units"] == 300

        for batch in env["batches"]:
            assert fx.get_batch(api, batch["id"])["distribution_state"] == "STOP_DISTRIBUTION"
        summary = fx.get_summary(api, env["product"]["id"])
        assert summary["units_stopped"] == 300
        assert summary["units_held"] == 0
        assert summary["ledger_balanced"] is True

    def test_the_batch_scoped_variant_cuts_at_the_failing_orders_window_start(self, api):
        """PRD 3.9: "Under `BATCH_SCOPED`, the operator asserts the defect is confined to
        the material the failing order sampled, and the cutoff is the failing order's own
        `window_start`."

        PRD 3.9: "For identical batch data, `LOT_TRACEBACK` always returns a unit count
        greater than or equal to `BATCH_SCOPED`, because its cutoff can only be earlier or
        the same."

        Design: Corner/calculations/corner_calculations_corrective_scope_falls_back_to_product_created_at_when_no_prior_pass
        """
        env = _never_passed_rule_case_env(api)
        assert env["failing_order"]["window_start"] == FAILING_WINDOW[0]

        case = fx.issue_stop_distribution(api, env["case"]["id"], "BATCH_SCOPED")
        assert case["scope_units"] == 100

        states = [fx.get_batch(api, b["id"])["distribution_state"] for b in env["batches"]]
        assert states == ["HELD", "HELD", "STOP_DISTRIBUTION"]
        summary = fx.get_summary(api, env["product"]["id"])
        assert summary["units_stopped"] == 100
        assert summary["units_held"] == 200
        assert summary["ledger_balanced"] is True


def _three_interval_env(api):
    """Twelve-month and six-month rules apply; a three-month rule is mapped but not required."""
    fx.set_clock(api, STARTUP_CLOCK)
    env = fx.booking_env(
        api,
        rule_specs=[
            dict(LEAD_RULE, periodic_interval_months=12),
            dict(
                PHTHALATE_RULE,
                applicability_condition="ALWAYS",
                periodic_interval_months=6,
            ),
            dict(METAL_COATING_RULE, severity_weight=8, periodic_interval_months=3),
        ],
        category=dict(FLAT_CATEGORY),
        part_specs=[PAINTED_SHELL],
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 4},
        plan_overrides={"plan_type": "INITIAL"},
    )
    env["lead"], env["phthalate"], env["metal"] = env["rules"]
    return env


class TestPeriodicDueDateTakesTheStrictestRequiredInterval:
    """The minimum interval across the required set, and nothing outside that set."""

    def test_the_smallest_interval_among_the_required_rules_sets_the_deadline(self, api):
        """PRD 3.5: "Take every rule in the product's `required_rule_ids` and find the
        smallest `periodic_interval_months` among them; when the required set is empty,
        `periodic_due_at` is null."

        Design: Corner/calculations/corner_calculations_periodic_due_date_selects_the_strictest_interval_across_all_required_rules
        """
        env = _three_interval_env(api)
        assert env["product"]["required_rule_ids"] == [
            env["lead"]["id"],
            env["phthalate"]["id"],
        ]
        assert env["plan"]["activated_at"] == STARTUP_CLOCK
        assert env["plan"]["last_verified_at"] == STARTUP_CLOCK
        # Six months from activation, not the mapped-but-unrequired three months,
        # and not the highest-severity rule's twelve.
        assert env["plan"]["periodic_due_at"] == "2027-02-01T00:00:00Z"

    def test_a_passing_order_rebases_the_deadline_on_the_new_verification(self, api):
        """PRD 3.5: "The baseline `last_verified_at` is the plan's `activated_at` until the
        plan's first passing test order resets it, and every subsequent passing order under
        the plan resets it again and recomputes `periodic_due_at`."

        Design: Corner/calculations/corner_calculations_periodic_due_date_selects_the_strictest_interval_across_all_required_rules
        """
        env = _three_interval_env(api)
        fx.set_clock(api, "2026-09-15T00:00:00Z")
        fx.run_order_to_pass(
            api,
            env["product"]["id"],
            env["plan"]["id"],
            env["laboratory"]["id"],
            env["lead"]["id"],
            measured_value=40,
            window_start="2026-09-16T00:00:00Z",
            window_end="2026-09-17T00:00:00Z",
        )
        plan = fx.get_plan(api, env["plan"]["id"])
        assert plan["plan_state"] == "ACTIVE"
        assert plan["last_verified_at"] == "2026-09-15T00:00:00Z"
        assert plan["periodic_due_at"] == "2027-03-15T00:00:00Z"


def _two_rule_evidence_complete_env(api):
    """A two-rule product whose evidence is complete on both rules."""
    fx.set_clock(api, STARTUP_CLOCK)
    env = fx.evidence_complete_env(
        api,
        rule_specs=[
            dict(LEAD_RULE),
            dict(PHTHALATE_RULE, applicability_condition="ALWAYS"),
        ],
        category=dict(FLAT_CATEGORY),
        part_specs=[PAINTED_SHELL, PLASTICIZED_GRIP],
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 4},
        measured_value=40,
    )
    assert env["product"]["certification_state"] == "EVIDENCE_COMPLETE"
    return env


class TestContentCompletenessCountsSevenSlots:
    """Five content fields plus two citation relationships, floored over seven."""

    def test_all_seven_slots_satisfied_reports_one_hundred(self, api):
        """PRD 3.7: "The seven slots are: `certifier_legal_name` is non-empty after
        trimming; `certifier_contact_email` contains an at-sign; `manufacture_place` is
        non-empty after trimming; `manufacture_date_month` matches the four-digit-year,
        hyphen, two-digit-month-between-01-and-12 pattern; `testing_place` is non-empty after
        trimming; `cited_rule_ids` is non-empty and equals the product's `required_rule_ids`
        when compared as sets; and `cited_evidence_count` is at least as large as the number
        of entries in `cited_rule_ids`."

        Design: Corner/calculations/corner_calculations_certificate_content_completeness_counts_seven_slots_including_evidence_coverage
        """
        env = _two_rule_evidence_complete_env(api)
        product = fx.get_product(api, env["product"]["id"])
        certificate = fx.draft_certificate(api, product["id"], product["version"])

        assert certificate["content_completeness_pct"] == 100
        assert set(certificate["cited_rule_ids"]) == set(product["required_rule_ids"])
        assert certificate["cited_evidence_count"] >= len(certificate["cited_rule_ids"])
        assert certificate["cited_evidence_count"] == 2

    def test_one_unsatisfied_slot_floors_the_percentage_at_eighty_five(self, api):
        """PRD 3.7: "**Content completeness** is then computed as a percentage over exactly
        seven required-content slots, and the certificate's `content_completeness_pct` is the
        count of satisfied slots multiplied by 100, divided by 7, with the result floored to a
        whole number."

        PRD 3.7: "All seven satisfied yields exactly 100; six of seven yields 85."

        Design: Corner/calculations/corner_calculations_certificate_content_completeness_counts_seven_slots_including_evidence_coverage
        """
        env = _two_rule_evidence_complete_env(api)
        product = fx.get_product(api, env["product"]["id"])
        # A blank-but-present place of manufacture leaves six of the seven slots satisfied.
        certificate = fx.draft_certificate(
            api, product["id"], product["version"], manufacture_place="   "
        )
        assert certificate["content_completeness_pct"] == 85

        validate_error(
            api.issue_certificate(certificate["id"], headers=OFFICER_HEADERS),
            ApiErrorId.CERTIFICATE_CONTENT_INCOMPLETE.value,
            422,
        )
        assert fx.get_certificate(api, certificate["id"])["issuance_status"] == "DRAFT"

    def test_the_citation_snapshot_survives_a_later_mapping_retirement(self, api):
        """PRD 3.7: "`cited_rule_ids` is set to a snapshot of the product's
        `required_rule_ids`."

        Design: Corner/calculations/corner_calculations_certificate_content_completeness_counts_seven_slots_including_evidence_coverage
        """
        env = _two_rule_evidence_complete_env(api)
        product = fx.get_product(api, env["product"]["id"])
        certificate = fx.draft_certificate(api, product["id"], product["version"])

        validate_success(
            api.retire_mapping(env["mappings"][1]["id"], headers=ADMIN_HEADERS), 200
        )
        after = fx.get_certificate(api, certificate["id"])
        assert after["cited_rule_ids"] == certificate["cited_rule_ids"]
        assert (
            fx.get_product(api, product["id"])["required_rule_ids"]
            == product["required_rule_ids"]
        )


def _labelled_batches_env(api):
    """Two held batches under a furnished certificate: one part-labelled, one complete."""
    fx.set_clock(api, STARTUP_CLOCK)
    env = fx.distributed_env(
        api,
        release=False,
        batch_specs=[
            {
                "batch_code": "LABELS-000201",
                "quantity": 100,
                "label_on_packaging": False,
            },
            {"batch_code": "LABELS-000202", "quantity": 100},
        ],
        rule_specs=[dict(LEAD_RULE)],
        category=dict(FLAT_CATEGORY),
        product={"projected_annual_units": 2000},
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 4},
        measured_value=40,
        certificate_overrides={"manufacture_date_month": "2026-08"},
    )
    env["partial"], env["complete"] = env["batches"]
    assert env["product"]["manufacture_site_code"] == "SITE01"
    return env


class TestTrackingLabelFlagIsAFiveWayConjunction:
    """Every conjunct is required, and the flag is recomputed on every edit."""

    def test_a_label_on_the_product_alone_is_not_compliant(self, api):
        """PRD 3.8: "A label present on the product alone, or on the packaging alone, is not
        compliant — the regulation demands both surfaces, so partial labelling earns no
        partial credit."

        Design: Corner/calculations/corner_calculations_tracking_label_flag_requires_all_five_conjuncts_including_batch_code_format
        """
        env = _labelled_batches_env(api)
        assert env["partial"]["label_on_product"] is True
        assert env["partial"]["label_on_packaging"] is False
        assert env["partial"]["tracking_label_compliant"] is False

        validate_error(
            api.release_batch(env["partial"]["id"], headers=MANAGER_HEADERS),
            ApiErrorId.TRACKING_LABEL_NONCOMPLIANT.value,
            422,
        )
        assert fx.get_batch(api, env["partial"]["id"])["distribution_state"] == "HELD"

    def test_completing_the_flags_flips_the_computed_flag_and_permits_release(self, api):
        """PRD 3.8: "**Tracking-label compliance** is a strict conjunction of five
        conditions, all of which must hold: `label_on_product` is true, `label_on_packaging`
        is true, `label_batch_code_printed` is true, the `batch_code` matches the required
        format, and the owning product's `manufacture_site_code` is non-empty."

        Design: Corner/calculations/corner_calculations_tracking_label_flag_requires_all_five_conjuncts_including_batch_code_format
        """
        env = _labelled_batches_env(api)
        relabelled = validate_success(
            api.update_tracking_label(
                env["partial"]["id"],
                factories.tracking_label_payload(),
                headers=MANAGER_HEADERS,
            ),
            200,
        )
        assert relabelled["tracking_label_compliant"] is True
        assert relabelled["version"] == env["partial"]["version"] + 1

        released = fx.release_batch(api, env["partial"]["id"])
        assert released["distribution_state"] == "RELEASED"
        assert fx.get_summary(api, env["product"]["id"])["units_released"] == 100

    def test_the_conjunction_is_re_evaluated_on_every_edit(self, api):
        """PRD 3.8: "The manager may revise the three label flags at any time while the
        batch is in `HELD` or `STOP_DISTRIBUTION`, submitting all three of
        `label_on_product`, `label_on_packaging` and `label_batch_code_printed`; the flags are
        stored, `tracking_label_compliant` is recomputed, and the batch's `version` increments
        by 1."

        Design: Corner/calculations/corner_calculations_tracking_label_flag_requires_all_five_conjuncts_including_batch_code_format
        """
        env = _labelled_batches_env(api)
        assert env["complete"]["tracking_label_compliant"] is True

        undone = validate_success(
            api.update_tracking_label(
                env["complete"]["id"],
                factories.tracking_label_payload(label_batch_code_printed=False),
                headers=MANAGER_HEADERS,
            ),
            200,
        )
        assert undone["tracking_label_compliant"] is False

        validate_error(
            api.release_batch(env["complete"]["id"], headers=MANAGER_HEADERS),
            ApiErrorId.TRACKING_LABEL_NONCOMPLIANT.value,
            422,
        )


CHANGE_KINDS = (
    "SUPPLIER_SWITCH",
    "MATERIAL_SUBSTITUTION",
    "COATING_CHANGE",
    "DESIGN_GEOMETRY_CHANGE",
    "PACKAGING_ONLY",
)


def _rounds_env(api):
    """A stopped case with enough authorised units for three retest rounds."""
    fx.set_clock(api, STARTUP_CLOCK)
    return fx.stopped_case_env(
        api,
        rule_specs=[dict(LEAD_RULE)],
        category=dict(FLAT_CATEGORY),
        product={"projected_annual_units": 6000},
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 5},
        measured_value=40,
        certificate_overrides={"manufacture_date_month": "2026-08"},
        batch_specs=[{"batch_code": "ROUNDS-001301", "quantity": 100}],
    )


def _fail_the_live_retest(api, env):
    """Report a failing measurement on the case's active retest order."""
    order_id = env["case"]["active_retest_order_id"]
    fx.start_order(api, order_id, env["laboratory"]["id"])
    fx.report(api, order_id, env["laboratory"]["id"], 250)
    return fx.get_case(api, env["case"]["id"])


class TestThresholdDecisionsCoverTheirWholeInputDomain:
    """The resample decision over every change kind, and the round counter over its ladder."""

    def test_packaging_only_is_the_single_non_triggering_change_kind(self, api):
        """PRD 3.10: "`triggers_resample` is false when `change_kind` is `PACKAGING_ONLY`,
        and true for all four other kinds."

        PRD 3.10: "`PACKAGING_ONLY` is the single non-triggering kind, on the reasoning that
        a new carton does not change what the child touches."

        Design: Corner/calculations/corner_calculations_material_change_and_retest_threshold_decisions_cover_their_enums
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.scoped_product_env(
            api,
            rule_specs=[dict(LEAD_RULE)],
            category=dict(FLAT_CATEGORY),
            part_specs=[PAINTED_SHELL],
        )
        decisions = {}
        for kind in CHANGE_KINDS:
            event = fx.record_material_change(
                api,
                env["product"]["id"],
                subject_type="PRODUCT",
                change_kind=kind,
                description=f"Recorded change of kind {kind} for the audit file.",
            )
            decisions[kind] = event["triggers_resample"]

        assert decisions["PACKAGING_ONLY"] is False
        assert decisions["SUPPLIER_SWITCH"] is True
        assert decisions["MATERIAL_SUBSTITUTION"] is True
        assert decisions["COATING_CHANGE"] is True
        assert decisions["DESIGN_GEOMETRY_CHANGE"] is True
        assert fx.get_product(api, env["product"]["id"])["material_change_count"] == 5

    def test_rounds_zero_one_and_two_each_order_another_retest(self, api):
        """PRD 3.9: "The retest endpoint is at once the cycle edge and the loop-termination
        edge of the case machine, and which of the two it takes is decided by a single
        comparison against `retest_round_count` **as it stands before this call increments
        it**."

        PRD 3.9: "A case at 2 orders one more retest and lands at 3."

        Design: Corner/calculations/corner_calculations_material_change_and_retest_threshold_decisions_cover_their_enums
        """
        env = _rounds_env(api)
        assert env["case"]["retest_round_count"] == 0

        for expected_count in (1, 2, 3):
            env["case"] = fx.order_retest(
                api, env["case"]["id"], env["plan"]["id"], env["laboratory"]["id"]
            )
            assert env["case"]["case_state"] == "RETEST_ORDERED"
            assert env["case"]["retest_round_count"] == expected_count
            env["case"] = _fail_the_live_retest(api, env)
            assert env["case"]["case_state"] == "RETEST_FAILED"
            assert env["case"]["active_retest_order_id"] is None

    def test_a_counter_of_exactly_three_escalates_and_is_terminal(self, api):
        """PRD 3.9: "When `retest_round_count` is at or above the maximum of 3 retest
        rounds, the case escalates; otherwise it orders another round."

        PRD 3.9: "A case whose `retest_round_count` is exactly 3 escalates."

        Design: Corner/calculations/corner_calculations_material_change_and_retest_threshold_decisions_cover_their_enums
        """
        env = _rounds_env(api)
        for _ in range(3):
            env["case"] = fx.order_retest(
                api, env["case"]["id"], env["plan"]["id"], env["laboratory"]["id"]
            )
            env["case"] = _fail_the_live_retest(api, env)
        assert env["case"]["retest_round_count"] == 3

        escalated = fx.order_retest(
            api, env["case"]["id"], env["plan"]["id"], env["laboratory"]["id"]
        )
        assert escalated["case_state"] == "ESCALATED_RECALL"
        assert escalated["scope_variant"] == "LOT_TRACEBACK"
        assert escalated["retest_round_count"] == 3

        validate_error(
            api.order_retest(
                env["case"]["id"],
                factories.retest_payload(env["plan"]["id"], env["laboratory"]["id"]),
                headers=COORDINATOR_HEADERS,
            ),
            ApiErrorId.CASE_STATE_INVALID.value,
            409,
        )


def _reconciliation_env(api):
    """Five hundred produced units split across one released and one held batch."""
    fx.set_clock(api, STARTUP_CLOCK)
    env = fx.distributed_env(
        api,
        release=False,
        batch_specs=[
            {"batch_code": "LEDGER-001401", "quantity": 300},
            {"batch_code": "LEDGER-001402", "quantity": 200},
        ],
        rule_specs=[dict(LEAD_RULE)],
        category=dict(FLAT_CATEGORY),
        product={"projected_annual_units": 2000},
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 4},
        measured_value=40,
        certificate_overrides={"manufacture_date_month": "2026-08"},
    )
    env["released_batch"], env["held_batch"] = env["batches"]
    fx.release_batch(api, env["released_batch"]["id"])

    env["cancelled_order"] = fx.book_order(
        api,
        env["product"]["id"],
        env["plan"]["id"],
        env["laboratory"]["id"],
        env["rules"][0]["id"],
        window_start="2026-08-11T00:00:00Z",
        window_end="2026-08-12T00:00:00Z",
    )
    validate_success(
        api.cancel_test_order(env["cancelled_order"]["id"], headers=COORDINATOR_HEADERS),
        200,
    )
    return env


class TestTheComputedSummaryReconcilesEveryLedger:
    """One read reports the buckets, their derived total and whether they balance."""

    def test_the_four_buckets_sum_to_the_total_produced(self, api):
        """PRD 2.8: "The invariant is that the sum of those four counters equals the total
        `quantity` produced across every batch of the product, with no status filter applied
        to that total."

        Design: Corner/calculations/corner_calculations_three_ledgers_reconcile_in_the_computed_compliance_summary
        """
        env = _reconciliation_env(api)
        summary = fx.get_summary(api, env["product"]["id"])
        assert summary["units_total_produced"] == 500
        assert summary["units_held"] == 200
        assert summary["units_released"] == 300
        assert summary["units_stopped"] == 0
        assert summary["units_destroyed"] == 0
        assert summary["ledger_balanced"] is True
        assert_distribution_ledger(summary)

    def test_the_summary_is_a_projection_of_the_product_row(self, api):
        """PRD 3.3: "It reports `product_id`, the derived `required_rule_ids`, the split of
        those rules into `covered_rule_ids` and `uncovered_rule_ids`, the recomputed
        `risk_weighted_gap_score` and `compliance_posture`, the `open_case_count` and
        `resample_due_plan_count` that fed the penalties, the four distribution counters
        `units_held`, `units_released`, `units_stopped` and `units_destroyed`, the
        `units_total_produced` they must sum to, and a `ledger_balanced` boolean stating
        whether they do."

        Design: Corner/calculations/corner_calculations_three_ledgers_reconcile_in_the_computed_compliance_summary
        """
        env = _reconciliation_env(api)
        summary = fx.get_summary(api, env["product"]["id"])
        product = fx.get_product(api, env["product"]["id"])

        assert summary["product_id"] == product["id"]
        for bucket in ("units_held", "units_released", "units_stopped", "units_destroyed"):
            assert summary[bucket] == product[bucket]
        assert summary["risk_weighted_gap_score"] == product["risk_weighted_gap_score"]
        assert summary["compliance_posture"] == product["compliance_posture"]
        assert summary["open_case_count"] == 0
        assert summary["resample_due_plan_count"] == 0

        covered = set(summary["covered_rule_ids"])
        uncovered = set(summary["uncovered_rule_ids"])
        assert covered | uncovered == set(summary["required_rule_ids"])
        assert covered & uncovered == set()

    def test_the_sample_unit_and_fee_ledgers_still_square_after_the_cancellation(self, api):
        """PRD 2.8: "The invariant is that `units_committed` plus `units_available` equals
        `units_authorized` at all times, and it must hold identically before an order is
        booked and after that same order is cancelled — cancellation returns exactly the units
        the booking took, with no drift."

        Design: Corner/calculations/corner_calculations_three_ledgers_reconcile_in_the_computed_compliance_summary
        """
        env = _reconciliation_env(api)
        plan = fx.get_plan(api, env["plan"]["id"])
        assert plan["units_committed"] + plan["units_available"] == plan["units_authorized"]
        assert plan["units_committed"] == 1

        laboratory = fx.get_laboratory(api, env["laboratory"]["id"])
        surviving = fx.get_order(api, env["orders"][0]["id"])
        assert (
            laboratory["billed_fee_cents_total"] - laboratory["credited_fee_cents_total"]
            == surviving["invoice_total_cents"]
        )
        assert (
            laboratory["credited_fee_cents_total"]
            == env["cancelled_order"]["invoice_total_cents"]
        )
