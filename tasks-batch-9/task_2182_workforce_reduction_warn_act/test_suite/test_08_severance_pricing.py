"""Pricing the separation package: the pinned order and the two variants."""

from test_helpers import (
    ALICE,
    BEN,
    BEN_CLASS_B,
    CARLA,
    GRACE,
    IVY,
    TEST_USERS,
    ApiErrorId,
    assert_severance_offer,
    federal_rule_payload,
    generate_disclosure,
    list_offers,
    ny_state_rule_payload,
    price_offer,
    read_analysis,
    read_disclosure,
    read_plan,
    read_selection,
    run_analysis,
    setup_approved_scenario,
    setup_offer_ready_scenario,
    validate_error,
    validate_success,
)

BENEFITS = TEST_USERS["benefits_headers"]
NY_RULES = (federal_rule_payload(), ny_state_rule_payload())


def _ny_alice_offer_ready():
    """One NY selection carried to the point where pricing is admissible."""
    return setup_offer_ready_scenario(
        people=(ALICE, BEN, CARLA),
        state_code="NY",
        rules=NY_RULES,
        select_indexes=(0,),
        propose_only_indexes=(2,),
        plan_name="2026 Q4 NY Restructuring",
        decisional_unit_name="NY HQ Operations",
        script_code="MANAGER_SCRIPT_UNION",
        justification="Single-incumbent role elimination; business necessity documented.",
    )


class TestSeveranceVariantsOnOneEmployee:
    """Identical inputs, materially different awards."""

    def test_standard_floors_the_half_week_and_grants_no_bonus(self, api):
        """PRD 3.8: "The `STANDARD` variant discards any half week, taking the
        largest whole number of weeks not exceeding the capped entitlement, and
        grants no bonus."
        PRD 3.8: "`weekly_rate_cents` is the employee's `annual_base_cents`
        divided by 52 and rounded half up to a whole number of cents."
        PRD 3.8: "Fourth, `base_severance_cents` is the weekly rate multiplied by
        `weeks_awarded`, rounded half up exactly once."
        PRD 3.8: "Eighth and last, `total_separation_cost_cents` is the sum of
        `base_severance_cents`, `notice_pay_offset_cents`, `benefit_subsidy_cents`
        and `outplacement_fee_cents`."

        Design: Difficulty/dual_variant_calc/severance_standard_versus_enhanced_release_same_employee
        """
        scn = _ny_alice_offer_ready()

        offer = price_offer(scn["selection_by_index"][0]["id"], "STANDARD")
        assert_severance_offer(offer)
        assert offer["weekly_rate_cents"] == 167308
        assert offer["weeks_awarded"] == 16, "16.5 weeks floored under STANDARD"
        assert offer["base_severance_cents"] == 2676928
        assert offer["notice_shortfall_days"] == 0
        assert offer["notice_pay_offset_cents"] == 0
        assert offer["benefit_subsidy_months"] == 9
        assert offer["total_separation_cost_cents"] == 3553428
        assert read_plan(scn["plan"]["id"])["severance_reserve_cents"] == 0, (
            "pricing alone reserves nothing"
        )

    def test_enhanced_release_keeps_the_half_week_and_adds_two(self, api):
        """PRD 3.8: "The `ENHANCED_RELEASE` variant retains half-week precision
        and adds a release bonus of 2 further weeks on top of the capped
        entitlement. Identical inputs therefore yield materially different awards
        under the two variants, which is the point of offering an enhanced
        release in exchange for a signature."
        PRD 3.8: "At ten years and above it is 14.5 weeks plus 2 further weeks
        for each completed year beyond the tenth."

        Design: Difficulty/dual_variant_calc/severance_standard_versus_enhanced_release_same_employee
        """
        scn = _ny_alice_offer_ready()
        selection_id = scn["selection_by_index"][0]["id"]

        standard = price_offer(selection_id, "STANDARD")
        enhanced = price_offer(selection_id, "ENHANCED_RELEASE")

        assert enhanced["weeks_awarded"] == 18.5
        assert enhanced["base_severance_cents"] == 3095198
        assert enhanced["total_separation_cost_cents"] == 3971698
        assert (
            standard["base_severance_cents"] != enhanced["base_severance_cents"]
        ), "the two variants must diverge on identical inputs"


class TestRoundingOrderIsPartOfTheSpecification:
    """Rounding the weekly rate first is not the same as rounding once at the end."""

    @staticmethod
    def _scenario():
        return setup_offer_ready_scenario(
            people=(GRACE, BEN, CARLA),
            select_indexes=(0,),
            propose_only_indexes=(2,),
            plan_name="Austin Engineering Reduction",
            decisional_unit_name="Austin Engineering",
            justification="Role eliminated outright; no comparable retained position.",
        )

    def test_the_weekly_rate_is_rounded_before_it_is_multiplied(self, api):
        """PRD 2.7: "Rounding order is part of the specification, not an
        implementation detail. Where a formula prescribes rounding an
        intermediate rate to whole cents before multiplying it, computing the
        product first and rounding once at the end produces a different — and
        incorrect — answer, and the system must follow the step order the formula
        states."
        PRD 3.8: "`weekly_rate_cents` is the employee's `annual_base_cents`
        divided by 52 and rounded half up to a whole number of cents."
        PRD 3.8: "Fourth, `base_severance_cents` is the weekly rate multiplied by
        `weeks_awarded`, rounded half up exactly once."

        Design: Difficulty/combinatorial_formula/severance_rounding_order_weekly_rate_rounded_before_multiplication
        """
        scn = self._scenario()

        offer = price_offer(scn["selection_by_index"][0]["id"], "ENHANCED_RELEASE")
        assert offer["weekly_rate_cents"] == 181827
        assert offer["weeks_awarded"] == 13.5
        assert offer["base_severance_cents"] == 2454665
        assert offer["base_severance_cents"] != 2454663, (
            "folding the division and the multiplication together loses two cents"
        )

    def test_the_downstream_tier_and_total_follow_the_pinned_steps(self, api):
        """PRD 3.8: "When that subtotal is below 1000000 cents,
        `benefit_subsidy_months` is 3; when it is at least 1000000 cents but
        below 2500000 cents, it is 6; and at 2500000 cents or above it is 9."
        PRD 3.8: "The `outplacement_tier` is `PREMIUM` when
        `benefit_subsidy_months` is 6 or more and `STANDARD` otherwise, and
        `outplacement_fee_cents` is 350000 cents for a premium engagement and
        120000 cents for a standard one."
        PRD 3.3: "For each criterion in the plan's locked `selection_criteria`,
        the criterion's `score` from the submitted sheet is multiplied by that
        criterion's `weight_pct` and the product is divided by 100; the resulting
        per-criterion contributions are summed across all locked criteria, and
        the sum is rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/severance_rounding_order_weekly_rate_rounded_before_multiplication
        """
        scn = self._scenario()

        offer = price_offer(scn["selection_by_index"][0]["id"], "ENHANCED_RELEASE")
        assert offer["benefit_subsidy_months"] == 6
        assert offer["benefit_subsidy_cents"] == 351000
        assert offer["outplacement_fee_cents"] == 350000
        assert offer["total_separation_cost_cents"] == 3155665
        assert (
            read_selection(scn["selection_by_index"][0]["id"])["composite_score"]
            == 70.10
        )


class TestSubsidyTierKeyedOnThePreBenefitSubtotal:
    """The tier reads step four's subtotal, not step eight's total."""

    @staticmethod
    def _scenario():
        return setup_offer_ready_scenario(
            people=(IVY, BEN, CARLA),
            select_indexes=(0,),
            propose_only_indexes=(2,),
            plan_name="Austin Platform Reduction",
            decisional_unit_name="Austin Platform",
            justification="Platform consolidation; documented business necessity.",
        )

    def test_a_950000_cent_subtotal_lands_in_the_three_month_tier(self, api):
        """PRD 3.8: "The tier key is a pre-benefit subtotal formed by adding
        `notice_pay_offset_cents` to `base_severance_cents`. When that subtotal is
        below 1000000 cents, `benefit_subsidy_months` is 3; when it is at least
        1000000 cents but below 2500000 cents, it is 6; and at 2500000 cents or
        above it is 9."
        PRD 3.8: "and the order is load-bearing because the benefit tier is keyed
        on a subtotal that is itself a component of the final total."

        Design: Difficulty/combinatorial_formula/subsidy_tier_keyed_on_pre_benefit_subtotal_not_on_the_total
        """
        scn = self._scenario()

        offer = price_offer(scn["selection_by_index"][0]["id"], "STANDARD")
        assert offer["weekly_rate_cents"] == 95000
        assert offer["weeks_awarded"] == 10
        assert offer["base_severance_cents"] == 950000
        assert offer["notice_pay_offset_cents"] == 0
        assert offer["benefit_subsidy_months"] == 3
        assert offer["benefit_subsidy_months"] != 6, (
            "keying the tier on the final total would cross the 1000000-cent ceiling"
        )

    def test_the_three_month_tier_carries_a_standard_outplacement_and_total(self, api):
        """PRD 3.8: "The monthly subsidy is the employee's
        `monthly_premium_cents` multiplied by 0.65 — the employer covering
        sixty-five per cent of the group-health premium — and rounded half up to
        whole cents; `benefit_subsidy_cents` is that monthly figure multiplied by
        `benefit_subsidy_months`."
        PRD 3.8: "The `outplacement_tier` is `PREMIUM` when
        `benefit_subsidy_months` is 6 or more and `STANDARD` otherwise, and
        `outplacement_fee_cents` is 350000 cents for a premium engagement and
        120000 cents for a standard one."
        PRD 3.8: "Eighth and last, `total_separation_cost_cents` is the sum of
        `base_severance_cents`, `notice_pay_offset_cents`, `benefit_subsidy_cents`
        and `outplacement_fee_cents`."

        Design: Difficulty/combinatorial_formula/subsidy_tier_keyed_on_pre_benefit_subtotal_not_on_the_total
        """
        scn = self._scenario()

        offer = price_offer(scn["selection_by_index"][0]["id"], "STANDARD")
        assert offer["benefit_subsidy_cents"] == 175500
        assert offer["outplacement_fee_cents"] == 120000
        assert offer["total_separation_cost_cents"] == 1245500
        assert offer["total_separation_cost_cents"] != 1651000, (
            "the premium tier would have produced 1651000"
        )


class TestPricingRequiresTheLatestAnalysisCleared:
    """A superseding analysis re-closes the gate even after approval."""

    @staticmethod
    def _scenario():
        scn = setup_offer_ready_scenario(
            people=(ALICE, CARLA),
            select_indexes=(0,),
            propose_only_indexes=(1,),
            justification="First-pass clearance.",
        )
        scn["analysis_2"] = run_analysis(scn["plan"]["id"], "STANDARD_DEVIATION")
        return scn

    def test_pricing_is_refused_once_a_newer_analysis_supersedes_the_cleared_one(
        self, api
    ):
        """PRD 3.8: "The plan's latest adverse-impact analysis must be `CLEARED`,
        failing which `ERR_IMPACT_ANALYSIS_NOT_CLEARED`."
        PRD 3.5: "Creating a new analysis supersedes every earlier analysis of
        the same plan, moving each of them into `SUPERSEDED` from whichever of
        `COMPUTED`, `FLAGGED` or `CLEARED` it held, incrementing each superseded
        row's `version` by 1, and incrementing the plan's `version` by 1 as well."

        Design: Difficulty/cross_entity_state_dependency/severance_offer_blocked_while_latest_analysis_is_not_cleared
        """
        scn = self._scenario()
        selection = read_selection(scn["selection_by_index"][0]["id"])

        response = api.create_severance_offer(
            {
                "selection_id": selection["id"],
                "variant": "STANDARD",
                "expected_selection_version": selection["version"],
            },
            BENEFITS,
        )
        validate_error(response, ApiErrorId.ERR_IMPACT_ANALYSIS_NOT_CLEARED.value)
        assert response.status_code == 422

    def test_every_other_precondition_still_holds_when_pricing_is_refused(self, api):
        """PRD 3.5: "Approving the plan (`IN_LEGAL_REVIEW → APPROVED`)
        additionally requires that the plan's most recent adverse-impact
        analysis, ordered by `created_at` descending with `version` descending as
        the tie-break, exists and stands in `CLEARED` status; an absent analysis,
        or a latest analysis sitting in `COMPUTED`, `FLAGGED`, `SUPERSEDED` or
        `STALE`, is refused with `ERR_IMPACT_ANALYSIS_NOT_CLEARED`."
        PRD 3.8: "Finally the selection's `notice_status` must already be
        `DELIVERED`, failing which `ERR_NOTICE_NOT_DELIVERED` — nobody is priced
        before they are told."

        Design: Difficulty/cross_entity_state_dependency/severance_offer_blocked_while_latest_analysis_is_not_cleared
        """
        scn = self._scenario()
        selection = read_selection(scn["selection_by_index"][0]["id"])
        api.create_severance_offer(
            {
                "selection_id": selection["id"],
                "variant": "STANDARD",
                "expected_selection_version": selection["version"],
            },
            BENEFITS,
        )

        assert read_analysis(scn["analysis"]["id"])["status"] == "SUPERSEDED"
        assert read_analysis(scn["analysis_2"]["id"])["status"] == "COMPUTED"
        assert selection["notice_status"] == "DELIVERED"
        assert read_plan(scn["plan"]["id"])["approval_status"] == "APPROVED"
        assert read_disclosure(scn["disclosure"]["id"])["status"] == "ATTACHED"
        assert list_offers(selection_id=selection["id"]) == []


def test_a_second_offer_on_a_stale_selection_version_is_rejected(api):
    """PRD 2.8: "Creating a severance offer at `POST /severance-offers` requires
    a non-optional `expected_selection_version` field carrying the `version` of
    the `Selection` the client last observed. If that value does not equal the
    selection's current `version`, the request is rejected with
    `ERR_STALE_SELECTION_VERSION` and HTTP status 412."
    PRD 3.8: "The offer copies the selection's plan onto its own `plan_id`, and
    creating it increments the referenced selection's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_selection_version_rejects_a_second_offer
    """
    scn = setup_offer_ready_scenario(people=(ALICE, BEN_CLASS_B))
    selection = read_selection(scn["selection_by_index"][0]["id"])
    stale_version = selection["version"]

    first = validate_success(
        api.create_severance_offer(
            {
                "selection_id": selection["id"],
                "variant": "STANDARD",
                "expected_selection_version": stale_version,
            },
            BENEFITS,
        ),
        201,
    )
    assert first["variant"] == "STANDARD"

    response = api.create_severance_offer(
        {
            "selection_id": selection["id"],
            "variant": "ENHANCED_RELEASE",
            "expected_selection_version": stale_version,
        },
        BENEFITS,
    )
    validate_error(response, ApiErrorId.ERR_STALE_SELECTION_VERSION.value)
    assert response.status_code == 412

    assert len(list_offers(selection_id=selection["id"])) == 1


def test_missing_disclosure_outranks_the_undelivered_notice(api):
    """PRD 3.8: "For an employee whose `age_at_separation` is 40 or over, the
    plan must carry an OWBPA disclosure in status `ATTACHED` or `STALE` — that
    is, a disclosure that exists and has not been superseded — failing which
    `ERR_OWBPA_DISCLOSURE_MISSING`"
    PRD 3.8: "Finally the selection's `notice_status` must already be
    `DELIVERED`, failing which `ERR_NOTICE_NOT_DELIVERED` — nobody is priced
    before they are told."
    PRD 2.6: "When a request violates more than one rule, exactly one error is
    returned, and it is always the violation with the lowest priority number in
    the ladder below."

    Design: Corner/errors/error_owbpa_disclosure_missing_then_notice_not_delivered
    """
    scn = setup_approved_scenario(people=(ALICE, BEN_CLASS_B), propose_only_indexes=(1,))
    selection = read_selection(scn["selection_by_index"][0]["id"])

    without_disclosure = api.create_severance_offer(
        {
            "selection_id": selection["id"],
            "variant": "STANDARD",
            "expected_selection_version": selection["version"],
        },
        BENEFITS,
    )
    validate_error(without_disclosure, ApiErrorId.ERR_OWBPA_DISCLOSURE_MISSING.value)
    assert without_disclosure.status_code == 422

    disclosure = generate_disclosure(scn["plan"]["id"])
    assert disclosure["status"] == "ATTACHED"

    selection = read_selection(selection["id"])
    without_notice = api.create_severance_offer(
        {
            "selection_id": selection["id"],
            "variant": "STANDARD",
            "expected_selection_version": selection["version"],
        },
        BENEFITS,
    )
    validate_error(without_notice, ApiErrorId.ERR_NOTICE_NOT_DELIVERED.value)
    assert without_notice.status_code == 422

    assert selection["notice_status"] == "NOT_DELIVERED"
    assert list_offers(plan_id=scn["plan"]["id"]) == []
