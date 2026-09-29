"""Derived money figures: signed sums, filtered input sets, replays and roll-ups."""

from test_helpers import (
    fixtures,
    make_agency_officer_headers,
    validate_paginated,
    validate_success,
)

DOT = {"agency_code": "DOT", "name": "Department of Transportation", "agency_type": "EXECUTIVE"}

THREE_FUND_APPROPRIATIONS = (
    {"fund_type": "GENERAL", "program_code": "P100", "introduced_amount_cents": 2_000_000_000},
    {"fund_type": "FEDERAL", "program_code": "P200", "introduced_amount_cents": 1_000_000_000},
    {"fund_type": "DEDICATED", "program_code": "P300", "introduced_amount_cents": 1_000_000_000},
)


class TestRequestTotalSignRules:
    def test_the_three_additive_types_are_summed_and_reductions_are_subtracted(self, api):
        """PRD §3.2: "Of those, sum the `amount_cents` of every package whose `package_type` is `EXPANSION`, `TECHNICAL`, or `FEDERAL_MATCH` to obtain the additive total, and sum the `amount_cents` of every package whose `package_type` is `REDUCTION` to obtain the subtractive total."
        PRD §3.2: "The request total is `base_budget_cents` plus the additive total minus the subtractive total."
        PRD §3.2: "A package carries `agency_request_id`, a `package_type` of `EXPANSION`, `REDUCTION`, `TECHNICAL`, or `FEDERAL_MATCH`, a `priority_rank` of at least 1 that is unique within the request (lower rank is funded first), and an `amount_cents` strictly greater than zero which is always a positive magnitude — for a `REDUCTION` package it is the magnitude of savings offered, not a negative number."
        PRD §3.2: "Submission recomputes `total_request_cents` and increments the request's `version` by 1."

        Design: Corner/calculations/request_total_adds_three_package_types_and_subtracts_reductions
        """
        ctx = fixtures.setup_development_cycle(agencies=(DOT,))
        agency_id = ctx["agency"]["id"]
        request, _packages = fixtures.setup_request_with_packages(
            ctx["cycle"]["id"],
            agency_id,
            base_budget_cents=1_000_000_000,
            packages=(
                {
                    "package_type": "EXPANSION",
                    "priority_rank": 1,
                    "amount_cents": 400_000_000,
                    "measures": [{"measure_code": "TRIPS", "baseline_value": 10, "target_value": 20}],
                },
                {"package_type": "TECHNICAL", "priority_rank": 2, "amount_cents": 300_000_000},
                {"package_type": "FEDERAL_MATCH", "priority_rank": 3, "amount_cents": 250_000_000},
                {"package_type": "REDUCTION", "priority_rank": 4, "amount_cents": 150_000_000},
            ),
        )

        submitted = validate_success(
            api.submit_agency_request(request["id"], make_agency_officer_headers(agency_id)), 200
        )

        assert submitted["status"] == "SUBMITTED"
        assert submitted["total_request_cents"] == 1_800_000_000
        assert submitted["total_request_cents"] != 2_100_000_000
        assert submitted["base_budget_cents"] == 1_000_000_000


class TestMoeSpendInputSet:
    @staticmethod
    def _two_funds_with_three_charges():
        ctx = fixtures.setup_execution_cycle(appropriations=THREE_FUND_APPROPRIATIONS[:2])
        general = ctx["appropriations"]["P100"]
        federal = ctx["appropriations"]["P200"]
        agency_id = ctx["agency"]["id"]
        fixtures.released_allotment(general["id"], quarter=1, requested_cents=440_000_000)
        fixtures.released_allotment(federal["id"], quarter=1, requested_cents=250_000_000)

        fixtures.post_expenditure(
            general["id"],
            agency_id,
            quarter=1,
            amount_cents=300_000_000,
            object_code="5100",
            vendor_reference="INV-GEN-KEEP",
        )
        voided = fixtures.post_expenditure(
            general["id"],
            agency_id,
            quarter=1,
            amount_cents=100_000_000,
            object_code="5100",
            vendor_reference="INV-GEN-VOID",
        )
        fixtures.void_expenditure(voided["id"], "charge belonged to another program")
        fixtures.post_expenditure(
            federal["id"],
            agency_id,
            quarter=1,
            amount_cents=200_000_000,
            object_code="5200",
            vendor_reference="INV-FED",
        )
        ctx["general"] = general
        ctx["federal"] = federal
        ctx["grant"] = fixtures.record_federal_grant(
            agency_id, ctx["cycle"]["id"], moe_baseline_cents=350_000_000
        )
        return ctx

    def test_only_the_posted_general_fund_charge_counts_toward_maintenance_of_effort(self, api):
        """PRD §3.8: "The assessment first refreshes `moe_current_spend_cents`: the sum of `amount_cents` over every expenditure in status `POSTED` charged to an appropriation whose `fund_type` is `GENERAL` and whose `agency_id` and `budget_cycle_id` match the grant's; `FEDERAL` and `DEDICATED` charges and `VOIDED` rows are excluded."
        PRD §3.8: "Under `SINGLE_YEAR` the assessed spend is `moe_current_spend_cents` alone, so a state that front-loads the current year passes."
        PRD §3.8: "The verdict compares integers, never the reported ratio: `moe_compliance_status` is `COMPLIANT` when the assessed spend is greater than or equal to `moe_baseline_cents` — exact equality is compliant — and `DEFICIENT` otherwise."
        PRD §3.8: "The assessment also writes `moe_compliance_ratio`, the assessed spend divided by `moe_baseline_cents` rounded half up to 6 decimal places, and records the basis used in `moe_assessed_basis`."
        PRD §2.11: "An appropriation's `expended_cents` equals the sum of `amount_cents` over its expenditures in status `POSTED`."

        Design: Corner/calculations/moe_current_spend_excludes_federal_fund_charges_and_voided_rows
        """
        ctx = self._two_funds_with_three_charges()

        assessed = fixtures.assess_moe(ctx["grant"]["id"], "SINGLE_YEAR")

        assert assessed["moe_current_spend_cents"] == 300_000_000
        assert assessed["moe_current_spend_cents"] not in (400_000_000, 600_000_000)
        assert assessed["moe_assessed_basis"] == "SINGLE_YEAR"
        assert assessed["moe_compliance_status"] == "DEFICIENT"
        assert assessed["moe_compliance_ratio"] == 0.857143

        assert fixtures.read_appropriation(ctx["general"]["id"])["expended_cents"] == 300_000_000
        assert fixtures.read_appropriation(ctx["federal"]["id"])["expended_cents"] == 200_000_000


class TestCommitteeReplayOutOfOrderInsert:
    @staticmethod
    def _chain_with_a_gap_at_sequence_three():
        ctx = fixtures.setup_legislative_cycle(
            appropriations=(
                {
                    "fund_type": "GENERAL",
                    "program_code": "P100",
                    "introduced_amount_cents": 2_000_000_000,
                    "enact": False,
                },
            )
        )
        appropriation_id = ctx["appropriations"]["P100"]["id"]
        fixtures.record_committee_action(
            appropriation_id,
            chamber="HOUSE",
            committee_name="Appropriations",
            action_type="INCREASE",
            amount_cents=500_000_000,
            sequence_number=1,
        )
        fixtures.record_committee_action(
            appropriation_id,
            chamber="SENATE",
            committee_name="Finance",
            action_type="DECREASE",
            amount_cents=300_000_000,
            sequence_number=2,
        )
        fixtures.record_committee_action(
            appropriation_id,
            chamber="CONFERENCE",
            committee_name="Conference",
            action_type="DECREASE",
            amount_cents=200_000_000,
            sequence_number=4,
        )
        ctx["appropriation_id"] = appropriation_id
        return ctx

    def test_a_late_restore_at_a_lower_sequence_rewrites_the_later_running_balance(
        self, api, legislative_fiscal_officer_headers
    ):
        """PRD §3.4: "The server discards the previous result and replays the appropriation's entire action set from scratch, with no status filter, ordered by `sequence_number` ascending and, for equal sequence numbers, by `created_at` ascending."
        PRD §3.4: "The replay starts from `introduced_amount_cents` and applies each action in turn, writing the post-action balance onto that action as its `running_balance_cents`."
        PRD §3.4: "The five action types behave as follows: `SET` replaces the balance with the action's amount, `INCREASE` adds the amount to the balance, `DECREASE` subtracts the amount from the balance, `RESTORE` resets the balance to the line's `introduced_amount_cents`, and `STRIKE` zeroes the line."
        PRD §3.4: "The consequence to design for is that inserting an action with a *lower* `sequence_number` than actions that already exist rewrites the `running_balance_cents` of every later action and can change `committee_balance_cents` for an unchanged set of actions — applying actions in arrival order instead of sequence order would leave earlier running balances untouched and produce a different final balance from the identical inputs."
        PRD §3.4: "The actions of an appropriation can be listed in `sequence_number` ascending order."

        Design: Corner/calculations/late_low_sequence_restore_action_rewrites_every_later_running_balance
        """
        ctx = self._chain_with_a_gap_at_sequence_three()
        appropriation_id = ctx["appropriation_id"]

        before_rows, _meta = validate_paginated(
            api.list_appropriation_committee_actions(
                appropriation_id, legislative_fiscal_officer_headers
            )
        )
        assert [(row["sequence_number"], row["running_balance_cents"]) for row in before_rows] == [
            (1, 2_500_000_000),
            (2, 2_200_000_000),
            (4, 2_000_000_000),
        ]
        assert (
            fixtures.read_appropriation(appropriation_id)["committee_balance_cents"]
            == 2_000_000_000
        )

        inserted = validate_success(
            api.create_committee_action(
                {
                    "appropriation_id": appropriation_id,
                    "chamber": "SENATE",
                    "committee_name": "Finance",
                    "action_type": "RESTORE",
                    "amount_cents": 0,
                    "sequence_number": 3,
                },
                legislative_fiscal_officer_headers,
            ),
            201,
        )
        assert inserted["running_balance_cents"] == 2_000_000_000

        after_rows, _after_meta = validate_paginated(
            api.list_appropriation_committee_actions(
                appropriation_id, legislative_fiscal_officer_headers
            )
        )
        assert [(row["sequence_number"], row["running_balance_cents"]) for row in after_rows] == [
            (1, 2_500_000_000),
            (2, 2_200_000_000),
            (3, 2_000_000_000),
            (4, 1_800_000_000),
        ]

        appropriation = fixtures.read_appropriation(appropriation_id)
        assert appropriation["committee_balance_cents"] == 1_800_000_000
        assert appropriation["authority_status"] == "PENDING"
        assert appropriation["introduced_amount_cents"] == 2_000_000_000


class TestCycleReleasedRollUp:
    def test_all_three_fund_types_roll_up_into_one_cycle_release_total(
        self, api, budget_director_headers
    ):
        """PRD §3.5: "A `GENERAL`-fund line may release 22 percent of its authority in quarter 1 and 26 percent in each of quarters 2, 3, and 4. A `FEDERAL` line is level: 25 percent in each of the four quarters. A `DEDICATED` line is front-loaded: 30 percent in each of quarters 1 and 2 and 20 percent in each of quarters 3 and 4."
        PRD §3.5: "`binding_constraint` records which limit bound, and ties are broken by a fixed precedence rather than by discovery order: scan the labels `REQUEST`, `QUARTER_CAP`, `UNRELEASED_AUTHORITY`, `CASH_FLOW` in that order and record the first whose limit equals the ceiling."
        PRD §2.11: "A cycle's `total_released_cents` equals the sum of `released_cents` over its appropriations, which equals the sum of `released_cents` over all allotments in status `RELEASED` whose appropriation belongs to that cycle."
        PRD §3.5: "A cycle's `projected_cumulative_cash_cents` is its `adopted_general_fund_revenue_cents` multiplied by the cash-flow factor of the *current* quarter as derived from the logical clock, rounded half up to the cent."
        PRD §3.5: "Its `cash_utilization_pct` is `total_released_cents` divided by that projected figure — using 1 as the divisor whenever the projected figure is zero or less, so the ratio is always defined — rounded half up to 4 decimal places."
        PRD §3.5: "The `cash_posture` is `CONSTRAINED` when `cash_utilization_pct` is greater than or equal to 0.90, and `NORMAL` otherwise."

        Design: Corner/calculations/cycle_total_released_aggregates_across_all_three_fund_types
        """
        ctx = fixtures.setup_execution_cycle(appropriations=THREE_FUND_APPROPRIATIONS)

        general = fixtures.released_allotment(
            ctx["appropriations"]["P100"]["id"], quarter=1, requested_cents=440_000_000
        )
        federal = fixtures.released_allotment(
            ctx["appropriations"]["P200"]["id"], quarter=1, requested_cents=250_000_000
        )
        dedicated = fixtures.released_allotment(
            ctx["appropriations"]["P300"]["id"], quarter=1, requested_cents=300_000_000
        )

        assert general["released_cents"] == 440_000_000
        assert federal["released_cents"] == 250_000_000
        assert dedicated["released_cents"] == 300_000_000
        for allotment in (general, federal, dedicated):
            assert allotment["computed_release_cents"] == allotment["requested_cents"]
            assert allotment["binding_constraint"] == "REQUEST"

        cycle = validate_success(
            api.get_budget_cycle(ctx["cycle"]["id"], budget_director_headers), 200
        )
        assert cycle["total_released_cents"] == 990_000_000
        assert cycle["projected_cumulative_cash_cents"] == 2_000_000_000
        assert cycle["cash_utilization_pct"] == 0.495
        assert cycle["cash_posture"] == "NORMAL"


class TestRepeatedMoeAssessment:
    @staticmethod
    def _grant_over_a_single_posted_charge():
        ctx = fixtures.setup_appropriation_with_released_cash(
            requested_cents=440_000_000, appropriation_cents=2_000_000_000, quarter=1
        )
        fixtures.post_expenditure(
            ctx["appropriation"]["id"],
            ctx["agency"]["id"],
            quarter=1,
            amount_cents=300_000_000,
            object_code="5100",
            vendor_reference="INV-MOE",
        )
        ctx["grant"] = fixtures.record_federal_grant(
            ctx["agency"]["id"],
            ctx["cycle"]["id"],
            moe_baseline_cents=350_000_000,
            moe_prior_year1_spend_cents=400_000_000,
            moe_prior_year2_spend_cents=500_000_000,
        )
        return ctx

    def test_each_assessment_overwrites_the_previous_verdict_rather_than_keeping_it(self, api):
        """PRD §3.8: "At creation the grant's `required_state_match_cents` is fixed once as `award_cents` multiplied by `required_match_ratio`, rounded half up to the cent; `committed_match_cents` and `moe_current_spend_cents` are 0, `moe_compliance_ratio` is 0, `moe_assessed_basis` is null, `match_status` is `UNMET`, and `moe_compliance_status` is `NOT_ASSESSED`."
        PRD §3.8: "Under `THREE_YEAR_AVERAGE` the assessed spend is the sum of `moe_current_spend_cents`, `moe_prior_year1_spend_cents`, and `moe_prior_year2_spend_cents` divided by three, rounded half up to the cent before any comparison; identical current-year data therefore yields a lower assessed figure whenever the prior years were leaner, and the same grant can be `COMPLIANT` under one basis and `DEFICIENT` under the other."
        PRD §3.8: "The verdict compares integers, never the reported ratio: `moe_compliance_status` is `COMPLIANT` when the assessed spend is greater than or equal to `moe_baseline_cents` — exact equality is compliant — and `DEFICIENT` otherwise."
        PRD §3.8: "The assessment also writes `moe_compliance_ratio`, the assessed spend divided by `moe_baseline_cents` rounded half up to 6 decimal places, and records the basis used in `moe_assessed_basis`. The grant's `version` increments by 1."

        Design: Corner/calculations/repeated_moe_assessment_overwrites_the_stored_basis_ratio_and_verdict
        """
        ctx = self._grant_over_a_single_posted_charge()
        grant_id = ctx["grant"]["id"]

        unassessed = fixtures.read_federal_grant(grant_id)
        assert unassessed["moe_compliance_status"] == "NOT_ASSESSED"
        assert unassessed["moe_assessed_basis"] is None
        assert unassessed["moe_compliance_ratio"] == 0
        assert unassessed["moe_current_spend_cents"] == 0
        assert unassessed["match_status"] == "UNMET"

        first = fixtures.assess_moe(grant_id, "SINGLE_YEAR")
        assert first["moe_assessed_basis"] == "SINGLE_YEAR"
        assert first["moe_current_spend_cents"] == 300_000_000
        assert first["moe_compliance_status"] == "DEFICIENT"
        assert first["moe_compliance_ratio"] == 0.857143
        assert first["version"] == unassessed["version"] + 1

        second = fixtures.assess_moe(grant_id, "THREE_YEAR_AVERAGE")
        assert second["moe_assessed_basis"] == "THREE_YEAR_AVERAGE"
        assert second["moe_compliance_status"] == "COMPLIANT"
        assert second["moe_compliance_ratio"] == 1.142857
        assert second["version"] == first["version"] + 1

        third = fixtures.assess_moe(grant_id, "SINGLE_YEAR")
        assert third["moe_assessed_basis"] == "SINGLE_YEAR"
        assert third["moe_compliance_status"] == "DEFICIENT"
        assert third["moe_compliance_ratio"] == 0.857143
        assert third["version"] == second["version"] + 1

        stored = fixtures.read_federal_grant(grant_id)
        assert stored["moe_compliance_status"] == "DEFICIENT"
        assert stored["moe_current_spend_cents"] == 300_000_000
        assert stored["match_status"] == "UNMET"
