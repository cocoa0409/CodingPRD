"""Dual-variant calculations: district interest and assessment levy variants.

Covers the two-variant calculations where two algorithms both appear in the
PRD and produce different, separately pinned results on identical data.
"""
from test_helpers import (
    api_client,
    create_active_community,
    create_adopted_budget,
    create_district_with_advances,
    create_effective_rate,
    create_proposed_budget,
    create_requested_payment,
    create_and_schedule_notice,
    set_clock,
    get_success_data,
    TEST_USERS,
)

EXEC = TEST_USERS["declarant_executive_headers"]
CTRL = TEST_USERS["declarant_controller_headers"]
DIRECTOR = TEST_USERS["association_director_headers"]


class TestDistrictInterestProvisionalVsCertified:
    def _setup_district(self):
        community = create_active_community("Solstice Ranch", 100)
        district, advances = create_district_with_advances(
            community["id"],
            [(6000000, "2026-01-01T00:00:00Z"), (4000000, "2026-03-01T00:00:00Z")],
            district_name="MUD 7",
        )
        return community, district, advances

    def test_provisional_simple_interest_figure(self):
        """PRD §3.6: "The provisional figure, recomputed whenever the district is read and before any certification, is simple interest to the logical clock: for each advance, regardless of status, take its `amount_cents` times the annual rate over one hundred times the days outstanding over 365 — days outstanding being the calendar days from `advance_date` to now, or zero when the advance date is today or in the future — rounded half-up to whole cents per advance, then summed into `provisional_interest_cents`. The certified figure, computed only at payment certification, compounds daily per advance to the certification timestamp: each advance accrues its `amount_cents` times the quantity one plus the annual rate over one hundred over 365, raised to the days outstanding, minus one — again rounded half-up to whole cents per advance and summed in first-in-first-out order."

        Design: Difficulty/dual_variant_calc/district_interest_provisional_vs_certified
        """
        _, district, _ = self._setup_district()
        # Default clock 2026-05-01: 120 and 61 days outstanding at 5%.
        # round_half_up(6000000*0.05*120/365) = 98630; round_half_up(4000000*0.05*61/365) = 33425.
        read = get_success_data(api_client.get_district(district["id"], CTRL))
        assert read["provisional_interest_cents"] == 132055, (
            f"simple-interest provisional must be 132055, got {read['provisional_interest_cents']}"
        )

    def test_certified_daily_compound_diverges(self):
        """PRD §3.6: "The certified figure, computed only at payment certification, compounds daily per advance to the certification timestamp: each advance accrues its `amount_cents` times the quantity one plus the annual rate over one hundred over 365, raised to the days outstanding, minus one — again rounded half-up to whole cents per advance and summed in first-in-first-out order. For identical data the certified figure is larger than the provisional one. Funding arrives through annual levies."
        PRD §3.6: "The certified interest, `certified_interest_cents`, is the sum of the daily-compound interest over all advances to that timestamp, and the certified principal, `certified_principal_cents`, is the claim amount minus that interest — a claim too small to cover the interest due would make that figure negative and is likewise rejected `ERR_PAYMENT_EXCEEDS_OBLIGATION`.".

        Design: Difficulty/dual_variant_calc/district_interest_provisional_vs_certified
        """
        _, district, _ = self._setup_district()
        prov = get_success_data(api_client.get_district(district["id"], CTRL))[
            "provisional_interest_cents"
        ]
        payment = create_requested_payment(district["id"], 500000)
        certified = get_success_data(api_client.certify_payment(payment["id"], DIRECTOR))
        assert certified["certified_interest_cents"] == 133000, (
            f"daily-compound certified interest must be 133000, got "
            f"{certified['certified_interest_cents']}"
        )
        assert certified["certified_interest_cents"] != prov, (
            "the two interest variants must diverge on identical data"
        )
        assert certified["certified_principal_cents"] == 367000, (
            f"interest-first waterfall: 500000 - 133000 = 367000, got "
            f"{certified['certified_principal_cents']}"
        )


class TestAssessmentUniformVsDeclarantSubsidy:
    """Two communities with byte-identical FY2028 budgets: gap 24,000,000c
    over 100 planned units with a FY2027 EFFECTIVE prior rate of 200,000c."""

    FY27_LINES = [
        ("LANDSCAPE_MAINTENANCE", 12000000),
        ("AMENITY_OPERATIONS", 6000000),
        ("MANAGEMENT", 2000000),
        ("RESERVE_CONTRIBUTION", 2000000, True),
    ]
    FY28_LINES = [
        ("LANDSCAPE_MAINTENANCE", 12000000),
        ("AMENITY_OPERATIONS", 6000000),
        ("MANAGEMENT", 3000000),
        ("RESERVE_CONTRIBUTION", 4000000, True),
        ("EVENTS_PROGRAMMING", 1000000),
    ]

    def _setup_pair(self):
        """Returns (community_a, rate27_a, budget28_a, community_b, rate27_b, budget28_b).

        Clock is left at 2027-01-20 with both FY2028 budgets ADOPTED.

        The clock is monotonic, so the two communities walk the FY2027
        budget -> rate -> EFFECTIVE pipeline in lockstep: every step's
        date is chosen so the second community's call still finds the
        send_at strictly in the future at the moment of scheduling.
        """
        from test_helpers.factories import (
            create_budget_payload,
            create_line_item_payload,
        )
        communities = [
            create_active_community(name, 100)
            for name in ("Uniform Hills", "Subsidy Springs")
        ]
        # -- FY2027: propose budgets --------------------------------------
        budgets27 = []
        for c in communities:
            b27 = get_success_data(
                api_client.create_budget(
                    create_budget_payload(
                        community_id=c["id"], fiscal_year=2027,
                        non_assessment_income_cents=2000000,
                    ),
                    CTRL,
                )
            )
            for line in self.FY27_LINES:
                cat, amt = line[0], line[1]
                extra = {"is_reserve": line[2]} if len(line) > 2 else {}
                get_success_data(
                    api_client.create_line_item(
                        create_line_item_payload(
                            budget_id=b27["id"], category=cat,
                            amount_cents=amt, **extra,
                        ),
                        CTRL,
                    )
                )
            get_success_data(api_client.propose_budget(b27["id"], CTRL))
            budgets27.append(b27)
        # -- FY2027: send adoption notices --------------------------------
        for c, b27 in zip(communities, budgets27):
            create_and_schedule_notice(
                c["id"], "BUDGET_ADOPTION", "2026-05-02T00:00:00Z",
                budget_id=b27["id"], subject=f"FY2027", body="adopt",
            )
        set_clock("2026-05-02T00:00:00Z")
        # -- FY2027: adopt at 2026-05-17 (14-day lead satisfied) ----------
        set_clock("2026-05-17T00:00:00Z")
        for b27 in budgets27:
            get_success_data(api_client.adopt_budget(b27["id"], DIRECTOR))
        # -- FY2027: create + schedule ASSESSMENT_CHANGE notices ----------
        rates27 = []
        for c, b27 in zip(communities, budgets27):
            rate = get_success_data(
                api_client.create_assessment_rate(
                    {"community_id": c["id"], "budget_id": b27["id"],
                     "fiscal_year": 2027},
                    CTRL,
                )
            )
            rates27.append(rate)
        for c, rate in zip(communities, rates27):
            create_and_schedule_notice(
                c["id"], "ASSESSMENT_CHANGE", "2026-11-01T00:00:00Z",
                assessment_rate_id=rate["id"],
                subject="FY2027 rate", body="rate",
                effective_date="2027-01-01T00:00:00Z",
            )
        set_clock("2026-11-02T00:00:00Z")
        for rate in rates27:
            get_success_data(api_client.arm_rate(rate["id"], CTRL))
        # -- Sweep past 2027-01-01: both rates flip to EFFECTIVE ----------
        set_clock("2027-01-01T00:00:00Z")
        rates27 = [
            get_success_data(api_client.get_assessment_rate(r["id"], CTRL))
            for r in rates27
        ]
        for r in rates27:
            assert r["per_unit_annual_cents"] == 200000
        # -- FY2028 budgets: propose both, schedule both notices, send,
        #    adopt both. Staggering adopt timestamps would leave the second
        #    community's notice send_at in the past, so we run the pipeline
        #    in lockstep.
        budgets28 = []
        for c in communities:
            b28 = get_success_data(
                api_client.create_budget(
                    create_budget_payload(
                        community_id=c["id"], fiscal_year=2028,
                        non_assessment_income_cents=2000000,
                    ),
                    CTRL,
                )
            )
            for line in self.FY28_LINES:
                cat, amt = line[0], line[1]
                extra = {"is_reserve": line[2]} if len(line) > 2 else {}
                get_success_data(
                    api_client.create_line_item(
                        create_line_item_payload(
                            budget_id=b28["id"], category=cat,
                            amount_cents=amt, **extra,
                        ),
                        CTRL,
                    )
                )
            get_success_data(api_client.propose_budget(b28["id"], CTRL))
            budgets28.append(b28)
        # Schedule both notices while clock is still 2027-01-01.
        for c, b28 in zip(communities, budgets28):
            create_and_schedule_notice(
                c["id"], "BUDGET_ADOPTION", "2027-01-05T00:00:00Z",
                budget_id=b28["id"], subject="FY2028", body="adopt",
            )
        set_clock("2027-01-05T00:00:00Z")
        set_clock("2027-01-20T00:00:00Z")
        for b28 in budgets28:
            get_success_data(api_client.adopt_budget(b28["id"], DIRECTOR))
        return (
            communities[0], rates27[0], budgets28[0],
            communities[1], rates27[1], budgets28[1],
        )

    def test_uniform_variant_per_unit_and_increase(self):
        """PRD §3.5: "Under the uniform variant (`subsidy_elected` false, the default), `per_unit_annual_cents` is the gap divided by `total_planned_units`, rounded half-up to a whole cent, and `declarant_subsidy_cents` is 0. Under the declarant-subsidy variant, the election is validated in a fixed order: first, `transition_stage` must be `DECLARANT_CONTROL` (otherwise `ERR_SUBSIDY_NOT_AVAILABLE`), and second, an `EFFECTIVE` rate must exist for the prior fiscal year (otherwise `ERR_NO_PRIOR_RATE`)."
        PRD §3.5: "Whenever an `EFFECTIVE` rate exists for the prior fiscal year it is linked as `prior_rate_id` and its per-unit amount captured as `prior_per_unit_cents`; `increase_pct` is then the excess of the new `per_unit_annual_cents` over `prior_per_unit_cents`, expressed as a percentage of the prior amount and rounded half-up to two decimals. With no prior rate, `prior_rate_id`, `prior_per_unit_cents`, and `increase_pct` are all null."

        Design: Difficulty/dual_variant_calc/assessment_uniform_vs_declarant_subsidy
        """
        ca, _r27a, bud28a, _cb, _r27b, _bud28b = self._setup_pair()
        rate = get_success_data(
            api_client.create_assessment_rate(
                {
                    "community_id": ca["id"],
                    "budget_id": bud28a["id"],
                    "fiscal_year": 2028,
                    "subsidy_elected": False,
                },
                CTRL,
            )
        )
        assert rate["per_unit_annual_cents"] == 240000, (
            f"uniform per-unit must be 240000 (24,000,000 / 100), got "
            f"{rate['per_unit_annual_cents']}"
        )
        assert rate["declarant_subsidy_cents"] == 0
        assert float(rate["increase_pct"]) == 20.00, (
            f"increase (240000-200000)/200000 must be 20.00, got {rate['increase_pct']}"
        )

    def test_subsidy_variant_freezes_prior_rate(self):
        """PRD §3.5: "Under the declarant-subsidy variant, the election is validated in a fixed order: first, `transition_stage` must be `DECLARANT_CONTROL` (otherwise `ERR_SUBSIDY_NOT_AVAILABLE`), and second, an `EFFECTIVE` rate must exist for the prior fiscal year (otherwise `ERR_NO_PRIOR_RATE`). When both hold, the owner rate freezes at the prior year's per-unit amount, `increase_pct` reports 0.00, and `declarant_subsidy_cents` is the gap minus the frozen per-unit amount multiplied by `total_planned_units`. Whenever an `EFFECTIVE` rate exists for the prior fiscal year it is linked as `prior_rate_id` and its per-unit amount captured as `prior_per_unit_cents`; `increase_pct` is then the excess of the new `per_unit_annual_cents` over `prior_per_unit_cents`, expressed as a percentage of the prior amount and rounded half-up to two decimals."

        Design: Difficulty/dual_variant_calc/assessment_uniform_vs_declarant_subsidy
        """
        ca, _r27a, bud28a, cb, _r27b, bud28b = self._setup_pair()
        rate_uniform = get_success_data(
            api_client.create_assessment_rate(
                {"community_id": ca["id"], "budget_id": bud28a["id"], "fiscal_year": 2028},
                CTRL,
            )
        )
        rate_subsidy = get_success_data(
            api_client.create_assessment_rate(
                {
                    "community_id": cb["id"],
                    "budget_id": bud28b["id"],
                    "fiscal_year": 2028,
                    "subsidy_elected": True,
                },
                CTRL,
            )
        )
        assert rate_subsidy["per_unit_annual_cents"] == 200000, (
            f"subsidy variant freezes at the prior 200000, got "
            f"{rate_subsidy['per_unit_annual_cents']}"
        )
        assert rate_subsidy["declarant_subsidy_cents"] == 4000000, (
            f"subsidy is gap 24,000,000 - 200,000*100 = 4,000,000, got "
            f"{rate_subsidy['declarant_subsidy_cents']}"
        )
        assert float(rate_subsidy["increase_pct"]) == 0.00
        assert rate_uniform["per_unit_annual_cents"] != rate_subsidy["per_unit_annual_cents"], (
            "identical budget data must produce different per-unit results across the variants"
        )
