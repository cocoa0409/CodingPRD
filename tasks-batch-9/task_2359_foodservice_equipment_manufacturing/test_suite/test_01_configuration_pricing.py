"""Configuration unit pricing: the pinned order, the two variants and the tiers."""

import pytest

from test_helpers import (
    create_chain_account,
    create_chain_configuration,
    create_equipment_model,
    read_chain_configuration,
    release_configuration,
    set_clock,
    setup_approved_configuration,
    validate_success,
)

# The four-run series the pricing chain is proved against: certified 66.06
# units per hour against a 65.0 target, every hold temperature inside +/- 2 C.
FOUR_RUN_SERIES = [(95, 90, 175.0), (108, 95, 174.0), (102, 92, 176.0), (88, 96, 175.5)]

APPROVAL_KWARGS = {
    "validation_overrides": {"target_throughput_units_per_hour": 65.0},
    "runs": FOUR_RUN_SERIES,
}


class TestIndicativeVersusFirmPricing:
    def test_release_stamps_a_firm_price_that_exceeds_the_indicative_by_the_branding_charge(
        self, application_engineer
    ):
        """FULL_WRAP is added after the discount, so firm minus indicative is exactly 156000.

        PRD §3.3: "The **indicative** variant excludes the branding charge entirely,
        because at quoting time the artwork has not been signed off and branding is
        quoted separately; its result is stored in `indicative_unit_price_cents`. The
        **firm** variant adds the branding charge *after* the volume discount, so the
        branding charge is never discounted; its result is stored in
        `firm_unit_price_cents`."

        Design: Difficulty/dual_variant_calc/config_pricing_indicative_versus_firm_diverge_by_undiscounted_branding
        """
        state = setup_approved_configuration(**APPROVAL_KWARGS)
        config = state["config"]
        assert config["indicative_unit_price_cents"] == 2055186, (
            "the indicative figure for base 1850020 with SPLIT_TANK and HIGH_ALT, "
            "TOUCH_PRO controls and an 8 percent volume discount is 2055186, got "
            f"{config['indicative_unit_price_cents']}"
        )
        assert config["firm_unit_price_cents"] is None, (
            "the firm figure is stamped once, at release, so it must still be null in "
            f"ENG_APPROVED, got {config['firm_unit_price_cents']}"
        )

        released = release_configuration(config["id"])

        assert released["status"] == "RELEASED", (
            f"release moves ENG_APPROVED to RELEASED, got {released['status']}"
        )
        assert released["firm_unit_price_cents"] == 2211186, (
            "the firm figure adds the undiscounted FULL_WRAP charge of 156000 to the "
            f"discounted 2055186, so it must be 2211186, got "
            f"{released['firm_unit_price_cents']}"
        )
        assert released["indicative_unit_price_cents"] == 2055186, (
            "release must not fold branding into the indicative figure, got "
            f"{released['indicative_unit_price_cents']}"
        )
        assert (
            released["firm_unit_price_cents"] - released["indicative_unit_price_cents"]
            == 156000
        ), (
            "the two variants diverge by exactly the undiscounted FULL_WRAP charge of "
            f"156000, got a difference of "
            f"{released['firm_unit_price_cents'] - released['indicative_unit_price_cents']}"
        )

    @pytest.mark.parametrize(
        "branding_kit,expected_delta",
        [("NONE", 0), ("LOGO_BADGE", 42000), ("FULL_WRAP", 156000)],
    )
    def test_firm_minus_indicative_equals_the_undiscounted_branding_charge(
        self, branding_kit, expected_delta
    ):
        """Each branding kit's charge escapes the volume discount by exactly its face value.

        PRD §3.3: "The two variants then diverge on branding, which is worth nothing
        for `NONE`, forty-two thousand cents for `LOGO_BADGE` and one hundred fifty-six
        thousand cents for `FULL_WRAP`."

        Design: Difficulty/dual_variant_calc/config_pricing_indicative_versus_firm_diverge_by_undiscounted_branding
        """
        state = setup_approved_configuration(
            config_overrides={"branding_kit": branding_kit}, **APPROVAL_KWARGS
        )
        released = release_configuration(state["config"]["id"])

        assert released["indicative_unit_price_cents"] == 2055186, (
            "the indicative figure is branding-independent, so all three kits share "
            f"2055186, got {released['indicative_unit_price_cents']} for {branding_kit}"
        )
        assert released["firm_unit_price_cents"] == 2055186 + expected_delta, (
            f"the {branding_kit} charge of {expected_delta} is added after the volume "
            f"discount, so the firm figure is {2055186 + expected_delta}, got "
            f"{released['firm_unit_price_cents']}"
        )
        assert (
            released["firm_unit_price_cents"] - released["indicative_unit_price_cents"]
            == expected_delta
        ), (
            f"the {branding_kit} charge must never be discounted, so the divergence is "
            f"{expected_delta}, got "
            f"{released['firm_unit_price_cents'] - released['indicative_unit_price_cents']}"
        )


class TestOptionUpliftRounding:
    def test_two_option_uplift_is_rounded_per_option_before_being_summed(
        self, api, channel_manager
    ):
        """Rounding SPLIT_TANK and HIGH_ALT independently yields 2055186, not 2055185.

        PRD §3.3: "each selected option contributes its own percentage of the base
        price — `SPLIT_TANK` seven and a half percent, `HIGH_ALT` three and a quarter
        percent, `LEFT_HINGE` one and a half percent, `ENERGY_SAVER` four and a quarter
        percent — and each contribution is rounded half up to a whole cent
        **independently**, considering the options in the fixed order `SPLIT_TANK`,
        `HIGH_ALT`, `LEFT_HINGE`, `ENERGY_SAVER`, before the rounded contributions are
        summed."

        Design: Difficulty/combinatorial_formula/option_uplift_rounded_per_option_then_summed_not_summed_then_rounded
        """
        set_clock()
        model = create_equipment_model()
        account = create_chain_account()
        config = create_chain_configuration(
            account["id"],
            model["id"],
            account["version"],
            option_codes=["SPLIT_TANK", "HIGH_ALT"],
            controls_package="TOUCH_PRO",
            branding_kit="FULL_WRAP",
        )

        assert config["indicative_unit_price_cents"] == 2055186, (
            "138752 plus 60126 of independently rounded option uplift, 185000 of "
            "controls uplift and an 8 percent discount give 2055186, got "
            f"{config['indicative_unit_price_cents']}"
        )
        assert config["indicative_unit_price_cents"] != 2055185, (
            "2055185 is the figure produced by summing the percentages to 0.1075 and "
            "rounding once, which the PRD calls wrong"
        )
        assert config["firm_unit_price_cents"] is None, (
            "a DRAFT configuration has no firm price yet, got "
            f"{config['firm_unit_price_cents']}"
        )

        quote = validate_success(
            api.get_configuration_price_quote(config["id"], channel_manager)
        )

        assert quote["indicative_unit_price_cents"] == 2055186, (
            "the quote-support read recomputes the same per-option rounded figure, got "
            f"{quote['indicative_unit_price_cents']}"
        )

    def test_all_four_option_uplifts_are_rounded_per_option_before_being_summed(self):
        """With all four options the per-option order gives 2153052, not 2153051.

        PRD §3.3: "Adding the percentages together and rounding once at the end is a
        different number of cents and is wrong."

        Design: Difficulty/combinatorial_formula/option_uplift_rounded_per_option_then_summed_not_summed_then_rounded
        """
        set_clock()
        model = create_equipment_model()
        account = create_chain_account()
        config = create_chain_configuration(
            account["id"],
            model["id"],
            account["version"],
            option_codes=["SPLIT_TANK", "HIGH_ALT", "LEFT_HINGE", "ENERGY_SAVER"],
            controls_package="TOUCH_PRO",
            branding_kit="FULL_WRAP",
        )

        assert config["indicative_unit_price_cents"] == 2153052, (
            "138752 + 60126 + 27750 + 78626 = 305254 of option uplift on base 1850020, "
            "plus 185000 of controls uplift, less an 8 percent discount, gives 2153052, "
            f"got {config['indicative_unit_price_cents']}"
        )
        assert config["indicative_unit_price_cents"] != 2153051, (
            "2153051 is the figure produced by summing the four percentages to 0.165 "
            "and rounding the uplift once"
        )

        stored = read_chain_configuration(config["id"])
        assert stored["indicative_unit_price_cents"] == 2153052, (
            "the stamped figure must survive a re-read unchanged, got "
            f"{stored['indicative_unit_price_cents']}"
        )


class TestVolumeDiscountTiers:
    def test_volume_discount_tier_boundaries_at_500_200_and_50_units(self):
        """500, 200, 199 and 49 contracted units earn 12, 8, 4 and 0 percent.

        PRD §3.3: "The volume discount comes from the parent chain account's
        `contracted_unit_volume`, in three inclusive tiers: a contracted volume of at
        least 500 units earns twelve percent, at least 200 earns eight percent, at
        least 50 earns four percent, and anything below 50 earns nothing."

        Design: Corner/calculations/volume_discount_tier_boundaries_at_500_200_and_50_units
        """
        set_clock()
        model = create_equipment_model(
            supported_controls_packages=["STANDARD_DIAL"]
        )
        expected = {
            "CHN-500": (500, 1628018),
            "CHN-200": (200, 1702018),
            "CHN-199": (199, 1776019),
            "CHN-049": (49, 1850020),
        }
        prices = {}
        for account_code, (volume, _) in expected.items():
            account = create_chain_account(
                account_code=account_code, contracted_unit_volume=volume
            )
            config = create_chain_configuration(
                account["id"],
                model["id"],
                account["version"],
                config_code=f"CFG-{account_code.split('-')[1]}",
                option_codes=[],
                controls_package="STANDARD_DIAL",
                branding_kit="NONE",
            )
            prices[account_code] = config

        for account_code, (volume, expected_price) in expected.items():
            actual = prices[account_code]["indicative_unit_price_cents"]
            assert actual == expected_price, (
                f"a contracted volume of {volume} units prices base 1850020 at "
                f"{expected_price}, got {actual}"
            )
        assert prices["CHN-500"]["firm_unit_price_cents"] is None, (
            "none of these configurations is released, so the firm price stays null, "
            f"got {prices['CHN-500']['firm_unit_price_cents']}"
        )

    def test_controls_uplift_sits_inside_the_discountable_subtotal(self):
        """TOUCH_PRO is discounted with the base, giving 1872218 rather than 1887018.

        PRD §3.3: "The base price, the summed option uplift and the controls uplift
        together form the discountable subtotal — branding is deliberately outside it."

        Design: Corner/calculations/controls_uplift_sits_inside_the_discountable_subtotal
        """
        set_clock()
        model = create_equipment_model(
            supported_controls_packages=["STANDARD_DIAL", "TOUCH_PRO"]
        )
        account = create_chain_account(contracted_unit_volume=250)
        config = create_chain_configuration(
            account["id"],
            model["id"],
            account["version"],
            option_codes=[],
            controls_package="TOUCH_PRO",
            branding_kit="NONE",
        )

        assert config["controls_package"] == "TOUCH_PRO", (
            "the configuration must have kept the requested controls package, got "
            f"{config['controls_package']}"
        )
        assert config["indicative_unit_price_cents"] == 1872218, (
            "1850020 plus a 185000 controls uplift is a discountable subtotal of "
            "2035020, and an 8 percent discount of 162802 leaves 1872218, got "
            f"{config['indicative_unit_price_cents']}"
        )
        assert config["indicative_unit_price_cents"] != 1887018, (
            "1887018 is the figure produced by discounting the base alone and adding "
            "the controls uplift afterwards, which puts the uplift outside the subtotal"
        )

    def test_option_uplift_tie_rounds_half_up_and_not_to_even(self):
        """A SPLIT_TANK uplift of exactly 150004.5 cents rounds up to 150005.

        PRD §3.3: "each contribution is rounded half up to a whole cent
        **independently**, considering the options in the fixed order `SPLIT_TANK`,
        `HIGH_ALT`, `LEFT_HINGE`, `ENERGY_SAVER`, before the rounded contributions are
        summed."

        Design: Corner/calculations/option_uplift_tie_rounds_half_up_and_not_to_even
        """
        set_clock()
        model = create_equipment_model(
            model_code="OVN-500",
            name="Combi Oven 500",
            category="COMBI_OVEN",
            base_price_cents=2000060,
            supported_controls_packages=["STANDARD_DIAL"],
            rated_throughput_units_per_hour=80,
        )
        account = create_chain_account(contracted_unit_volume=250)
        config = create_chain_configuration(
            account["id"],
            model["id"],
            account["version"],
            option_codes=["SPLIT_TANK"],
            controls_package="STANDARD_DIAL",
            branding_kit="NONE",
        )

        assert config["indicative_unit_price_cents"] == 1978060, (
            "seven and a half percent of 2000060 is exactly 150004.5, which rounds half "
            "up to 150005, so the 8 percent discounted total is 1978060, got "
            f"{config['indicative_unit_price_cents']}"
        )
        assert config["indicative_unit_price_cents"] != 1978061, (
            "1978061 is the figure produced by rounding the tie down to the even cent "
            "150004 instead of half up"
        )


class TestPriceQuoteRead:
    def test_price_quote_read_refreshes_the_indicative_figure_from_current_upstream_data(
        self, api, channel_manager, compliance_engineer
    ):
        """After the model's base price is patched the quote recomputes while the stored figure does not.

        PRD §3.3: "The indicative figure is stamped when the configuration is created
        and recomputed on every quote-support read, so a dealer always sees a number
        consistent with the model's current `base_price_cents` and the chain's current
        `contracted_unit_volume`."

        Design: Corner/endpoints/price_quote_read_refreshes_the_indicative_figure_from_current_upstream_data
        """
        set_clock()
        model = create_equipment_model(supported_controls_packages=["STANDARD_DIAL"])
        account = create_chain_account(contracted_unit_volume=200)
        config = create_chain_configuration(
            account["id"],
            model["id"],
            account["version"],
            option_codes=[],
            controls_package="STANDARD_DIAL",
            branding_kit="NONE",
        )
        assert config["indicative_unit_price_cents"] == 1702018, (
            "base 1850020 at the 8 percent tier prices at 1702018, got "
            f"{config['indicative_unit_price_cents']}"
        )

        patched = validate_success(
            api.patch_equipment_model(
                model["id"], {"base_price_cents": 2000060}, compliance_engineer
            )
        )
        assert patched["version"] == 2, (
            f"patching the model increments its version to 2, got {patched['version']}"
        )

        stored = validate_success(
            api.get_chain_configuration(config["id"], channel_manager)
        )
        assert stored["indicative_unit_price_cents"] == 1702018, (
            "a plain configuration read replays the figure stamped at creation, got "
            f"{stored['indicative_unit_price_cents']}"
        )
        assert stored["firm_unit_price_cents"] is None, (
            "the configuration is not released, so the firm price is null, got "
            f"{stored['firm_unit_price_cents']}"
        )

        quote = validate_success(
            api.get_configuration_price_quote(config["id"], channel_manager)
        )
        assert quote["indicative_unit_price_cents"] == 1840055, (
            "the quote recomputes against the current base of 2000060, giving 1840055, "
            f"got {quote['indicative_unit_price_cents']}"
        )
        assert quote["firm_unit_price_cents"] is None, (
            "the firm figure is stamped only at release, got "
            f"{quote['firm_unit_price_cents']}"
        )
        assert quote["status"] == "DRAFT", (
            f"the configuration is still DRAFT, got {quote['status']}"
        )
