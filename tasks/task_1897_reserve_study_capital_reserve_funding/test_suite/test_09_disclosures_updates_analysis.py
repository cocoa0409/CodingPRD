"""Member disclosures (allocation lines, distribution), the annual update
checkpoint, and the special-assessment risk analysis."""
from test_helpers import (
    ApiErrorId,
    F1_COMPONENTS,
    create_draft_study,
    get_study,
    line_share_cents,
    list_components,
    list_disclosures,
    onboard_association,
    setup_adopted_study,
    validate_error,
    validate_success,
)


class TestAdoptionSummaryAllocation:
    def test_disclosure_allocation_largest_remainder(
            self, api, reserve_specialist_headers):
        """PRD §3.7: "When the sum of the weights is positive, each
        component's share is the floor of the total contribution multiplied by
        its weight and divided by the weight sum, and the leftover — the
        contribution minus the sum of the floored shares — is distributed one
        cent at a time to the components whose exact division left the largest
        fractional remainder, ties broken in favor of the component created
        earlier, with no component receiving more than one extra cent." and
        "Lines cover only components that are `ACTIVE` and included in
        funding, and are ordered by `created_at` ascending."

        Design: Difficulty/combinatorial_formula/disclosure_allocation_largest_remainder
        """
        # Equal first-replacement weights (103000/103000) and an odd
        # contribution: raw shares 25742.5/25742.5, so the remainder cent
        # goes to the earliest-created component.
        ctx = setup_adopted_study(
            state_code="CA", cash=100000, association_name="Even Split HOA",
            components=[
                {"name": "A1 Roof", "category": "ROOFING",
                 "useful_life_years": 5, "remaining_useful_life_years": 1,
                 "current_replacement_cost_cents": 100000,
                 "is_included_in_funding": True},
                {"name": "A2 Elevator", "category": "MECHANICAL",
                 "useful_life_years": 9, "remaining_useful_life_years": 1,
                 "current_replacement_cost_cents": 100000,
                 "is_included_in_funding": True},
            ])
        contribution = ctx["plan"]["annual_contribution_cents"]
        assert contribution == 51485, (
            f"BASELINE solve over the two-component inventory; got "
            f"{contribution}")

        disclosures = list_disclosures(ctx["study"]["id"])
        assert len(disclosures) == 1
        disclosure = disclosures[0]
        assert disclosure["disclosure_type"] == "ADOPTION_SUMMARY"

        lines = disclosure["allocation_lines"]
        assert len(lines) == 2
        first_share = line_share_cents(lines[0])
        second_share = line_share_cents(lines[1])
        assert first_share == 25743, (
            "A1 (earliest created_at) wins the fractional tie; got "
            f"{first_share}")
        assert second_share == 25742
        assert first_share + second_share == contribution, (
            "per-line floor + largest remainder sums exactly to the "
            f"contribution {contribution}; got {first_share + second_share}")

    def test_disclosure_allocation_zero_weights_greatest_cost_gets_all(
            self, api, reserve_specialist_headers):
        """PRD §3.7: "When every weight is zero, the entire contribution
        falls to the component with the greatest
        `current_replacement_cost_cents` — ties again broken by earliest
        creation — and every other line is zero." and "a component with no
        replacement inside the horizon weighs zero."

        Design: Difficulty/combinatorial_formula/disclosure_allocation_largest_remainder
        """
        # Both components first fall due in year 35, beyond the 0..29
        # horizon, so every weight is zero.
        ctx = setup_adopted_study(
            state_code="NV", cash=1000, association_name="Zero Weight HOA",
            plan_type="FULL",
            components=[
                {"name": "Membrane", "category": "ROOFING",
                 "useful_life_years": 40, "remaining_useful_life_years": 35,
                 "current_replacement_cost_cents": 100000,
                 "is_included_in_funding": True},
                {"name": "Structure", "category": "EXTERIOR",
                 "useful_life_years": 40, "remaining_useful_life_years": 35,
                 "current_replacement_cost_cents": 80000,
                 "is_included_in_funding": True},
            ])
        contribution = ctx["plan"]["annual_contribution_cents"]
        assert contribution > 0, (
            "the FULL floor at year 1 (27810) exceeds the grown opening "
            f"cash (round(1000*1.02) = 1020), so the solve is positive; got "
            f"{contribution}")

        disclosures = list_disclosures(ctx["study"]["id"])
        assert len(disclosures) == 1
        lines = disclosures[0]["allocation_lines"]
        assert len(lines) == 2
        # created_at ASC: the 100000-cost component was created first.
        assert line_share_cents(lines[0]) == contribution, (
            "greatest-cost component takes the entire contribution; got "
            f"{line_share_cents(lines[0])} of {contribution}")
        assert line_share_cents(lines[1]) == 0


class TestDisclosureDistribution:
    def test_disclosure_distribute_terminal_lockdown(
            self, api, association_manager_headers):
        """PRD §3.7: "Both open in `PENDING` status with a `due_date` set
        `disclosure_deadline_days` after the date of creation, per the state
        rule. An `AssociationManager` distributes a pending disclosure to
        members, moving it from `PENDING` to `DISTRIBUTED` with
        `distributed_at` stamped from the logical clock; when the
        distribution date falls strictly after the `due_date`, `is_late`
        records true."

        Design: Corner/state_machines/disclosure_distribute_terminal_lockdown
        """
        ctx = setup_adopted_study(state_code="CA", cash=500000,
                                  association_name="Disclose HOA",
                                  components=[{
                                      "name": "Roof", "category": "ROOFING",
                                      "useful_life_years": 5,
                                      "remaining_useful_life_years": 2,
                                      "current_replacement_cost_cents": 100000,
                                      "is_included_in_funding": True,
                                  }])
        disclosure = list_disclosures(ctx["study"]["id"])[0]
        assert disclosure["due_date"] == "2026-08-31", (
            "adoption at the default clock 2026-08-01 + 30 deadline days; "
            f"got {disclosure['due_date']}")

        distributed = validate_success(
            api.distribute_disclosure(disclosure["id"],
                                      association_manager_headers), 200)
        assert distributed["status"] == "DISTRIBUTED"
        assert distributed["is_late"] is False, (
            "distributed 2026-08-01, on or before the 2026-08-31 due date")

        res = api.distribute_disclosure(disclosure["id"],
                                        association_manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestAnnualUpdate:
    def test_annual_update_rolldown_recomputes_and_rearms(
            self, api, platform_admin_headers,
            reserve_specialist_headers):
        """PRD §3.8: "First, every `ACTIVE` component of the current adopted
        study ages by one year: its `remaining_useful_life_years` decreases
        by one, floored at zero so a component already at the end of its life
        stays at zero" and "Third, an `ANNUAL_STATEMENT` disclosure is
        created in `PENDING` status, its `due_date` set
        `disclosure_deadline_days` after the current date. Fourth, the
        association's `last_annual_update_fiscal_year` is stamped with the
        current fiscal year" and "it may not repeat within a fiscal year: the
        current fiscal year under the logical clock must be strictly later
        than the association's `last_annual_update_fiscal_year` — a null
        value, as on a freshly onboarded association, always passes — or the
        run is rejected with `ERR_ANNUAL_UPDATE_ALREADY_RUN`."

        Design: Corner/calculations/annual_update_rolldown_recomputes_and_rearms
        """
        ctx = setup_adopted_study(state_code="CA", cash=500000,
                                  association_name="Rollover HOA",
                                  components=F1_COMPONENTS)
        study_id = ctx["study"]["id"]
        validate_success(api.set_clock("2027-01-05T00:00:00Z",
                                       platform_admin_headers))

        association = validate_success(
            api.run_annual_update(ctx["association"]["id"],
                                  reserve_specialist_headers), 200)
        assert association["last_annual_update_fiscal_year"] == 2027

        components = list_components(study_id)
        assert components[0]["remaining_useful_life_years"] == 1, (
            f"C1 rolls 2 -> 1; got "
            f"{components[0]['remaining_useful_life_years']}")
        assert components[1]["remaining_useful_life_years"] == 0, (
            f"C2 rolls 1 -> 0 (floor at 0); got "
            f"{components[1]['remaining_useful_life_years']}")

        study = get_study(study_id)
        assert study["fully_funded_balance_cents"] == 130000, (
            "round(100000*4/5) + round(50000*4/4); got "
            f"{study['fully_funded_balance_cents']}")
        assert study["percent_funded"] == 384.62, (
            "round_half_up(500000*100/130000, 2); got "
            f"{study['percent_funded']}")

        statements = list_disclosures(
            study_id, params={"disclosure_type": "ANNUAL_STATEMENT"})
        assert len(statements) == 1
        assert statements[0]["status"] == "PENDING"
        assert statements[0]["due_date"] == "2027-02-04", (
            "2027-01-05 + 30 deadline days; got "
            f"{statements[0]['due_date']}")

        res = api.run_annual_update(ctx["association"]["id"],
                                    reserve_specialist_headers)
        validate_error(res, ApiErrorId.ERR_ANNUAL_UPDATE_ALREADY_RUN)


class TestSpecialAssessmentAnalysis:
    def test_special_assessment_analysis_literals(
            self, api, reserve_specialist_headers):
        """PRD §3.9: "`risk` is `AT_RISK` when at least one shortfall year
        exists and `NONE` otherwise. `first_shortfall_year` is the study's
        `fiscal_year` plus the offset of the earliest shortfall year, or null
        when there is none. `projected_min_balance_cents` is the lowest
        year-end balance across the thirty-year projection.
        `max_shortfall_cents` is the depth of that trough: the negation of
        the minimum when the minimum is negative, and zero otherwise."

        Design: Corner/calculations/special_assessment_analysis_literals
        """
        ctx = setup_adopted_study(
            state_code="NV", cash=5000, association_name="Risk HOA",
            components=[{
                "name": "Roof", "category": "ROOFING",
                "useful_life_years": 10, "remaining_useful_life_years": 1,
                "current_replacement_cost_cents": 100000,
                "is_included_in_funding": True,
            }],
            association_overrides={"current_annual_contribution_cents": 0})
        analysis = validate_success(
            api.get_special_assessment_analysis(ctx["study"]["id"],
                                                reserve_specialist_headers),
            200)
        assert analysis["risk"] == "AT_RISK"
        assert analysis["first_shortfall_year"] == 2028, (
            "study FY2026 + shortfall at projection year 2; got "
            f"{analysis['first_shortfall_year']}")
        assert analysis["projected_min_balance_cents"] == -597833, (
            f"got {analysis['projected_min_balance_cents']}")
        assert analysis["max_shortfall_cents"] == 597833

    def test_special_assessment_analysis_requires_adopted(
            self, api, reserve_specialist_headers):
        """PRD §3.9: "The read requires the addressed study to be `ADOPTED`;
        any other status fails with `ERR_INVALID_STATE`."

        Design: Corner/calculations/special_assessment_analysis_requires_adopted
        """
        association = onboard_association("CA", name="Draft Analysis HOA")
        study = create_draft_study(association["id"])
        res = api.get_special_assessment_analysis(study["id"],
                                                  reserve_specialist_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
