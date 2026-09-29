"""Multi-factor formulas where the order of rounding and keying is the contract."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    assert_money,
    fixtures,
    make_application_engineer_headers,
    make_contracts_administrator_headers,
)


def _disinfection_only_project(api):
    """A project whose single objective is E. coli, so the train is one UV stage."""
    state = {
        "material_spec": fixtures.seed_material_spec(api),
        "disinfection_technology": fixtures.seed_disinfection_technology(api),
        "test_bay": fixtures.seed_test_bay(api),
    }
    project = fixtures.create_draft_project(api)
    state["project"] = project
    state["influent_profile"] = fixtures.add_accepted_influent_profile(api, project["id"])
    state["ecoli_objective"] = fixtures.add_ecoli_objective(api, project["id"])
    stages = fixtures.run_selection(api, project["id"])
    state["stages"] = stages
    state["disinfection_stage"] = stages[0]
    return state


class TestBidWaterfallKeysTheBondTierOnTheBase:
    """The bond rate is chosen from the base, never from the evaluated total."""

    def _bid_ready_disinfection_project(self, api):
        state = _disinfection_only_project(api)
        package = fixtures.add_draft_package(
            api,
            state["disinfection_stage"]["id"],
            state["material_spec"]["id"],
            tag_number="D-100",
            design_pressure_psig=110,
        )
        state["package"] = fixtures.approve_package(api, package["id"])
        state.update(fixtures.preapproved_submittal(api, state["project"]["id"]))
        return state

    def test_bid_posts_the_five_step_waterfall_from_a_single_uv_stage(self, api):
        """A 96,949,116 cent base takes the lowest tier's 1.25 percent bond rate.

        Step 1 of the waterfall says "each line's amount is that package's
        `firm_cost_cents` multiplied by one plus the pinned overhead of 18.5 percent,
        rounded half up to whole cents." Step 2 says "the payment and performance
        bond rate is selected from `base_bid_amount_cents` alone -- never from the
        evaluated total that the premium is later folded into, which is exactly what
        makes the definition well founded" and "a base of at most 100,000,000 cents
        (one million dollars) takes a rate of 1.25 percent". Step 4 multiplies the
        base by "2 percent when the posture is `ON_TRACK`", and step 5 makes
        "`evaluated_bid_price_cents` the integer sum of `base_bid_amount_cents`,
        `bond_premium_cents` and `contingency_cents`."

        Design: Difficulty/combinatorial_formula/bid_evaluated_price_bond_tier_keyed_on_base_not_on_total
        """
        state = self._bid_ready_disinfection_project(api)

        project = validate_success(
            api.submit_bid(
                state["project"]["id"],
                {"offered_price_cents": 108107959},
                make_contracts_administrator_headers(),
            )
        )

        assert_money(project["base_bid_amount_cents"], 96949116, "base_bid_amount_cents")
        assert_money(project["bond_premium_cents"], 1211864, "bond_premium_cents")
        assert_money(project["contingency_cents"], 1938982, "contingency_cents")
        assert_money(
            project["evaluated_bid_price_cents"], 100099962, "evaluated_bid_price_cents"
        )
        assert_money(project["offered_price_cents"], 108107959, "offered_price_cents")
        assert project["status"] == "BID_SUBMITTED"

    def test_the_priced_package_feeding_the_bid_carries_both_cost_variants(self, api):
        """The line item entering the base is the package's frozen firm cost, not its budgetary cost.

        The base is taken "per non-superseded stage of the project, from that stage's
        equipment package in `APPROVED` status or later", and the pressure uplift is
        "one plus three percent for every hundred psig of the package's
        `design_pressure_psig`; the design pressure is divided by 100 and that
        quotient multiplied by 0.03, so a 250 psig package carries an uplift factor
        of 1.075 rather than a stepped one." A 110 psig UV package therefore carries
        1.033, and with a `NONE` code stamp -- "nothing for `NONE`" -- the whole
        difference between the two variants is the material cost index.

        Design: Difficulty/combinatorial_formula/bid_evaluated_price_bond_tier_keyed_on_base_not_on_total
        """
        state = self._bid_ready_disinfection_project(api)

        package = validate_success(
            api.get_equipment_package(
                state["package"]["id"], make_application_engineer_headers()
            )
        )

        assert_money(package["budgetary_cost_cents"], 74376000, "budgetary_cost_cents")
        assert_money(package["firm_cost_cents"], 81813600, "firm_cost_cents")


class TestReserveAccrualRoundsPerDrawBeforeSumming:
    """Two draws of the same odd unit cost expose the per-line rounding order."""

    ODD_UNIT_COST_CENTS = 1000025

    def _two_draws(self, api):
        state = fixtures.service_active_project(api)
        first = fixtures.post_draw(
            api,
            state["agreement"]["id"],
            draw_type="CONSUMABLE",
            quantity=1,
            catalog_unit_cost_cents=self.ODD_UNIT_COST_CENTS,
            invoiced_unit_cost_cents=self.ODD_UNIT_COST_CENTS,
        )
        second = fixtures.post_draw(
            api,
            state["agreement"]["id"],
            draw_type="CONSUMABLE",
            quantity=1,
            catalog_unit_cost_cents=self.ODD_UNIT_COST_CENTS,
            invoiced_unit_cost_cents=self.ODD_UNIT_COST_CENTS,
        )
        state["draws"] = [first, second]
        return state

    def test_each_draw_row_is_rounded_on_its_own_line(self, api):
        """Each draw rounds its own half-cent product half up before anything is summed.

        The PRD pins the accrual line as "`quantity` multiplied by
        `catalog_unit_cost_cents`, marked up by 22 percent, rounded half up to whole
        cents", the settled line as "uplifted by 6.5 percent freight, rounded half up
        to whole cents", and for a `CONSUMABLE` draw "`warranty_credit_cents` is 0."
        Rounding half up is the default: "round" in this document means **round half
        up**, and every monetary value is an integer count of cents, never a decimal
        currency amount."

        Design: Difficulty/combinatorial_formula/reserve_accrual_rounds_per_draw_before_summing
        """
        state = self._two_draws(api)

        for draw in state["draws"]:
            assert_money(draw["accrual_amount_cents"], 1220031, "accrual_amount_cents")
            assert_money(draw["settled_amount_cents"], 1065027, "settled_amount_cents")
            assert_money(draw["warranty_credit_cents"], 0, "warranty_credit_cents")

    def test_agreement_totals_are_integer_sums_of_the_already_rounded_lines(self, api):
        """Summing the rounded lines gives one cent more accrual than rounding the sum would.

        The PRD is explicit that "draw rows are rounded individually as they are
        written and the agreement totals are integer sums of those already-rounded
        lines; re-deriving the totals from unrounded products and rounding once at
        the end is the wrong order." Section 2.6 names this ledger as one of "the two
        pinned per-line-then-sum ledgers".

        Design: Difficulty/combinatorial_formula/reserve_accrual_rounds_per_draw_before_summing
        """
        state = self._two_draws(api)

        agreement = fixtures.current_agreement(api, state["agreement"]["id"])

        assert_money(
            agreement["reserve_committed_accrual_cents"],
            2440062,
            "reserve_committed_accrual_cents",
        )
        assert_money(
            agreement["reserve_committed_settled_cents"],
            2130054,
            "reserve_committed_settled_cents",
        )
        assert_money(
            agreement["reserve_available_cents"], 9759938, "reserve_available_cents"
        )
        assert_money(
            agreement["settlement_variance_cents"],
            -310008,
            "settlement_variance_cents",
        )

        rows, meta = validate_paginated(
            api.list_consumable_draws(
                make_contracts_administrator_headers(),
                {"service_agreement_id": state["agreement"]["id"]},
            )
        )
        assert meta["total_count"] == 2
        assert sum(row["accrual_amount_cents"] for row in rows) == 2440062
