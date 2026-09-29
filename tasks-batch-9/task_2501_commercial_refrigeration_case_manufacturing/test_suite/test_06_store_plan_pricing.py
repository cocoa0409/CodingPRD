"""Configured lines, the four-part case price and the six-step plan waterfall.

PRD §3.6 rounds only the base term of a case price, then rolls the plan up in a
pinned order: subtotal, discount tier, discount, net, freight, allowance, total.
"""

import pytest

from test_helpers import *  # noqa: F401,F403

PROPANE_BLEND = {
    "refrigerant_code": "R-290",
    "trade_name": "Propane",
    "gwp_100yr": 3,
    "safety_class": "A3",
    "max_charge_grams": 300,
    "allowed_system_types": ["REMOTE", "SELF_CONTAINED"],
}

OVER_CEILING_MODEL = {
    "model_code": "MDL-MT-8P",
    "charge_grams": 280,
    "line_set_length_ft": 120,
}


def _empty_draft_plan(ctx, **plan_overrides):
    """Open a plan with no lines on it and record it on the scenario."""
    ctx["store_plan"] = validate_success(
        api_client.create_store_plan(
            create_store_plan_payload(**plan_overrides),
            TEST_USERS["sales_engineer_headers"],
        ),
        expected_status=201,
    )
    return ctx["store_plan"]


class TestPlanRollUp:
    """PRD §3.6 — the waterfall order is pinned and observable."""

    def test_01_plan_total_follows_the_pinned_discount_then_freight_cap_order(
        self, api
    ):
        """Five 8 ft cases price to 5389938 cents with a capped freight term.

        PRD §3.6: "`freight_cents` is the **lesser** of two candidates: a
        per-foot tariff of 9500 cents multiplied by the plan's total linear
        footage, rounded half up to whole cents; and a cap of four hundredths of
        `net_cents`, likewise rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/store_plan_total_pinned_evaluation_order_discount_then_freight_cap
        """
        ctx = setup_plan_with_line(line_overrides={"quantity": 5})

        priced = validate_success(
            api.price_store_plan(
                ctx["store_plan"]["id"], TEST_USERS["sales_engineer_headers"]
            )
        )
        assert_pricing_waterfall(priced)
        assert priced["subtotal_cents"] == 5217500
        assert priced["volume_discount_bps"] == 300, (
            "the tier is keyed on the subtotal, which has crossed 5000000 cents"
        )
        assert priced["volume_discount_cents"] == 156525
        assert priced["net_cents"] == 5060975
        assert priced["freight_cents"] == 202439, (
            "the four percent cap on the post-discount net beats the 380000 tariff"
        )
        assert priced["install_allowance_cents"] == 126524
        assert priced["total_cents"] == 5389938
        assert priced["commercial_status"] == "PRICED"
        assert priced["production_status"] == "NOT_RELEASED"

        line = validate_success(
            api.get_store_plan_line(
                ctx["store_plan_line"]["id"], TEST_USERS["sales_engineer_headers"]
            )
        )
        assert line["unit_price_cents"] == 1043500
        assert line["extended_price_cents"] == 5217500

    def test_02_a_deeper_discount_tier_shrinks_the_freight_cap_it_feeds(self, api):
        """At 550 basis points the cap is taken from the reduced net, not the subtotal.

        PRD §3.6: "The order is pinned because the discount tier is keyed on the
        subtotal while freight and the install allowance are keyed on the
        post-discount net, so reading the six equations as one simultaneous
        system would be circular."

        Design: Difficulty/combinatorial_formula/store_plan_total_pinned_evaluation_order_discount_then_freight_cap
        """
        ctx = setup_plan_with_line(
            plan_overrides={"credit_limit_cents": 20000000},
            line_overrides={"quantity": 10},
        )

        priced = validate_success(
            api.price_store_plan(
                ctx["store_plan"]["id"], TEST_USERS["sales_engineer_headers"]
            )
        )
        assert_pricing_waterfall(priced)
        assert priced["subtotal_cents"] == 10435000
        assert priced["volume_discount_bps"] == 550
        assert priced["volume_discount_cents"] == 573925
        assert priced["net_cents"] == 9861075
        assert priced["freight_cents"] == 394443, (
            "four hundredths of the net, not of the subtotal"
        )
        assert priced["install_allowance_cents"] == 246527
        assert priced["total_cents"] == 10502045

    def test_03_volume_discount_tier_straddles_four_versus_five_units(self, api):
        """Four cases earn no discount; the fifth pulls the plan into 300 bps.

        PRD §3.6: "The tier boundaries are strict, so a subtotal of exactly
        5000000 cents lands in the 300-basis-point tier and a subtotal of exactly
        20000000 cents lands in the 800-basis-point tier."

        Design: Corner/calculations/store_plan_volume_discount_tier_straddle_four_versus_five_units
        """
        ctx = setup_certified_case_model()
        line_config = {
            "quantity": 4,
            "end_cap": "LEFT",
            "merchandising_options": ["LED_CANOPY"],
        }

        _empty_draft_plan(ctx, store_number="0412")
        four_line = validate_success(add_line(ctx, **line_config), expected_status=201)
        plan_a = validate_success(
            api.price_store_plan(
                ctx["store_plan"]["id"], TEST_USERS["sales_engineer_headers"]
            )
        )

        _empty_draft_plan(ctx, store_number="0413")
        validate_success(
            add_line(ctx, **dict(line_config, quantity=5)), expected_status=201
        )
        plan_b = validate_success(
            api.price_store_plan(
                ctx["store_plan"]["id"], TEST_USERS["sales_engineer_headers"]
            )
        )

        priced_four = validate_success(
            api.get_store_plan_line(
                four_line["id"], TEST_USERS["sales_engineer_headers"]
            )
        )
        assert priced_four["unit_price_cents"] == 1015000

        assert plan_a["subtotal_cents"] == 4060000
        assert plan_a["volume_discount_bps"] == 0
        assert plan_a["volume_discount_cents"] == 0
        assert plan_a["net_cents"] == 4060000
        assert plan_a["freight_cents"] == 162400
        assert plan_a["install_allowance_cents"] == 101500
        assert plan_a["total_cents"] == 4323900
        assert plan_a["commercial_status"] == "PRICED"
        assert plan_a["priced_by_user_id"] == SALES_ENGINEER_USER_ID

        assert plan_b["subtotal_cents"] == 5075000
        assert plan_b["volume_discount_bps"] == 300
        assert plan_b["volume_discount_cents"] == 152250
        assert plan_b["net_cents"] == 4922750
        assert plan_b["freight_cents"] == 196910
        assert plan_b["install_allowance_cents"] == 123069
        assert plan_b["total_cents"] == 5242729
        assert plan_b["commercial_status"] == "PRICED"
        assert plan_b["priced_by_user_id"] == SALES_ENGINEER_USER_ID

    def test_04_plan_read_returns_the_computed_pricing_rollup(self, api):
        """A read after pricing repeats every roll-up field and both line prices.

        PRD §3.6: "The result is stored as `unit_price_cents`, and
        `extended_price_cents` is `unit_price_cents` multiplied by the line's
        `quantity`."

        Design: Corner/endpoints/store_plan_read_returns_computed_pricing_rollup
        """
        ctx = setup_priced_plan(line_overrides={"quantity": 2})

        plan = validate_success(
            api.get_store_plan(
                ctx["store_plan"]["id"], TEST_USERS["sales_engineer_headers"]
            )
        )
        assert_store_plan(plan)
        assert_pricing_waterfall(plan)
        assert plan["commercial_status"] == "PRICED"
        assert plan["unit_count"] == 2
        assert plan["subtotal_cents"] == 2087000
        assert plan["volume_discount_bps"] == 0
        assert plan["volume_discount_cents"] == 0
        assert plan["freight_cents"] == 83480
        assert plan["install_allowance_cents"] == 52175
        assert plan["total_cents"] == 2222655
        assert plan["priced_by_user_id"] == SALES_ENGINEER_USER_ID

        line = validate_success(
            api.get_store_plan_line(
                ctx["store_plan_line"]["id"], TEST_USERS["sales_engineer_headers"]
            )
        )
        assert_store_plan_line(line)
        assert line["unit_price_cents"] == 1043500
        assert line["extended_price_cents"] == 2087000
        assert line["length_ft"] == 8
        assert line["quantity"] == 2
        assert line["compliance_hold"] is False

    def test_05_adding_a_line_to_a_priced_plan_invalidates_the_quote(self, api):
        """The plan falls back to DRAFT with all seven roll-up fields cleared.

        PRD §3.6: "Adding a line to a plan that has already been priced
        deliberately invalidates the quote: the plan moves `PRICED → DRAFT` and
        `subtotal_cents`, `volume_discount_bps`, `volume_discount_cents`,
        `net_cents`, `freight_cents`, `install_allowance_cents`, `total_cents`
        and `priced_by_user_id` are all cleared to absent, forcing a re-price."

        Design: Corner/state_machines/store_plan_priced_returns_to_draft_when_second_line_added
        """
        ctx = setup_priced_plan(line_overrides={"quantity": 2})
        assert ctx["store_plan"]["total_cents"] == 2222655

        second = validate_success(
            add_line(
                ctx,
                quantity=1,
                end_cap="NONE",
                merchandising_options=["LED_CANOPY"],
            ),
            expected_status=201,
        )
        assert second.get("unit_price_cents") is None, (
            "a new line is unpriced until the plan is priced again"
        )

        plan = refresh_store_plan(ctx)
        assert plan["commercial_status"] == "DRAFT"
        assert_pricing_cleared(plan)
        assert plan["line_count"] == 2
        assert plan["unit_count"] == 3


class TestLineConfigurationRules:
    """PRD §3.6 — four domain rules guard a new line, in ascending rank order."""

    def test_06_line_for_an_uncertified_model_is_rejected(self, api):
        """A design still in test cannot be ordered.

        PRD §3.6: "At rank 15, the ordered model's `status` must be exactly
        `CERTIFIED`, else `ERR_MODEL_NOT_CERTIFIED` (HTTP 422) — a design still
        in test, or one that has been decertified, cannot be sold."

        Design: Corner/validations/line_added_for_uncertified_model_rejected
        """
        ctx = setup_modeled_case_model()
        _empty_draft_plan(ctx)

        response = add_line(ctx)
        validate_error(response, ApiErrorId.ERR_MODEL_NOT_CERTIFIED.value)

        plan = refresh_store_plan(ctx)
        assert plan["line_count"] == 0
        assert plan["unit_count"] == 0
        assert plan["commercial_status"] == "DRAFT"

    def test_07_line_length_not_offered_by_the_model_is_rejected(self, api):
        """A 12 ft order against an 8 ft design is refused.

        PRD §3.6: "At rank 19, the requested `length_ft` must equal the ordered
        model's `nominal_length_ft`, because we build only the lengths a model is
        engineered for; a mismatch is `ERR_LENGTH_NOT_OFFERED` (HTTP 422)."

        Design: Corner/validations/line_length_not_offered_by_model_rejected
        """
        ctx = setup_certified_case_model()
        _empty_draft_plan(ctx)
        assert ctx["case_model"]["nominal_length_ft"] == 8

        response = add_line(ctx, length_ft=12)
        validate_error(response, ApiErrorId.ERR_LENGTH_NOT_OFFERED.value)

        plan = refresh_store_plan(ctx)
        assert plan["line_count"] == 0

    def test_08_glass_door_upgrade_on_an_open_case_is_rejected(self, api):
        """An open case takes a night curtain, never a glass-door upgrade.

        PRD §3.6: "`GLASS_DOOR_UPGRADE` may only be ordered on a model whose
        `door_type` is `GLASS_DOOR`, and `NIGHT_CURTAIN` may only be ordered on a
        model whose `door_type` is `OPEN` — a night curtain is meaningless on a
        case that already has doors."

        Design: Corner/validations/glass_door_upgrade_on_open_case_rejected
        """
        ctx = setup_certified_case_model()
        _empty_draft_plan(ctx)
        assert ctx["case_model"]["door_type"] == "OPEN"

        rejected = add_line(ctx, merchandising_options=["GLASS_DOOR_UPGRADE"])
        validate_error(rejected, ApiErrorId.ERR_OPTION_NOT_COMPATIBLE.value)

        accepted = validate_success(
            add_line(ctx, merchandising_options=["NIGHT_CURTAIN"]),
            expected_status=201,
        )
        assert accepted["merchandising_options"] == ["NIGHT_CURTAIN"]

        priced = validate_success(
            api.price_store_plan(
                ctx["store_plan"]["id"], TEST_USERS["sales_engineer_headers"]
            )
        )
        assert priced["commercial_status"] == "PRICED"
        priced_line = validate_success(
            api.get_store_plan_line(
                accepted["id"], TEST_USERS["sales_engineer_headers"]
            )
        )
        assert priced_line["unit_price_cents"] == 1001500

    def test_09_line_create_on_an_unknown_plan_returns_not_found(self, api):
        """The path id is checked before the body is considered at all.

        PRD §2.5: "Because resolution is strictly left to right, the leftmost
        unresolvable segment determines the error."

        Design: Corner/entities/store_plan_line_create_on_unknown_plan_returns_not_found
        """
        ctx = setup_certified_case_model()

        response = api.add_store_plan_line(
            NON_EXISTENT_UUID,
            create_store_plan_line_payload(ctx["case_model"]["id"]),
            TEST_USERS["sales_engineer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_STORE_PLAN_NOT_FOUND.value)


class TestLineRulePriority:
    """PRD §3.6 — rank 11 speaks before rank 15 on the same line add."""

    def test_10_charge_ceiling_breach_outranks_the_certification_check(self, api):
        """An over-charged, uncertified design reports the safety breach first.

        PRD §3.6: "At rank 11, the ordered model's installed charge basis must be
        at or below its blend's `max_charge_grams`, else
        `ERR_REFRIGERANT_CHARGE_LIMIT_EXCEEDED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/charge_limit_safety_outranks_model_not_certified_on_line_add
        """
        ctx = setup_modeled_case_model(
            refrigerant_overrides=PROPANE_BLEND,
            model_overrides=OVER_CEILING_MODEL,
        )
        assert ctx["case_model"]["installed_charge_grams"] == 3400
        assert ctx["case_model"]["status"] == "MODELED"
        _empty_draft_plan(ctx)

        response = add_line(
            ctx, end_cap="NONE", merchandising_options=["LED_CANOPY"]
        )
        validate_error(
            response, ApiErrorId.ERR_REFRIGERANT_CHARGE_LIMIT_EXCEEDED.value
        )

        model = refresh_case_model(ctx)
        assert model["installed_charge_grams"] == 3400
        assert model["status"] == "MODELED"

        plan = refresh_store_plan(ctx)
        assert plan["line_count"] == 0
        assert plan["unit_count"] == 0

    def test_11_clearing_the_charge_ceiling_uncovers_the_certification_check(
        self, api
    ):
        """Once the installed basis fits, rank 15 becomes the blocking rule.

        PRD §2.5: "Every request walks a fixed evaluation ladder, and the
        **lowest-ranked** failing check is the one whose error is returned."

        Design: Difficulty/priority_pair_validation_conflict/charge_limit_safety_outranks_model_not_certified_on_line_add
        """
        ctx = setup_modeled_case_model(
            refrigerant_overrides=PROPANE_BLEND,
            model_overrides=OVER_CEILING_MODEL,
        )
        _empty_draft_plan(ctx)
        validate_error(
            add_line(ctx, end_cap="NONE", merchandising_options=["LED_CANOPY"]),
            ApiErrorId.ERR_REFRIGERANT_CHARGE_LIMIT_EXCEEDED.value,
        )

        validate_success(
            open_engineering_change(
                ctx,
                refrigerant_id=ctx["refrigerant"]["id"],
                charge_grams=100,
                line_set_length_ft=5,
                change_note="Charge reduced to fit the propane ceiling",
            )
        )
        remodelled = validate_success(
            api.run_airflow_model(
                ctx["case_model"]["id"], TEST_USERS["design_engineer_headers"]
            )
        )
        assert remodelled["installed_charge_grams"] == 230
        assert remodelled["status"] == "MODELED"

        response = add_line(
            ctx, end_cap="NONE", merchandising_options=["LED_CANOPY"]
        )
        validate_error(response, ApiErrorId.ERR_MODEL_NOT_CERTIFIED.value)

        plan = refresh_store_plan(ctx)
        assert plan["line_count"] == 0
