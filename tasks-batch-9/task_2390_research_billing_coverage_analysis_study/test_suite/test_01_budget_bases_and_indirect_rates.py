"""The sponsor budget: the two per-patient bases, the indirect-rate branches,
and the way the budget dimension moves independently of the lifecycle.
"""

import pytest

from test_helpers import (
    ANALYST_ONE,
    MANAGER_ONE,
    MANAGER_TWO,
    REVIEWER_ONE,
    add_items,
    api_client,
    approve_analysis,
    budget_build_payload,
    execute_budget,
    file_amendment,
    implement_amendment,
    item_spec,
    make_manager_headers,
    open_analysis,
    read_study,
    route_spec,
    set_clock,
    setup_published_calendar,
    setup_study_with_approved_analysis,
    setup_study_with_executed_budget,
    study_version,
    submit_analysis,
    validate_success,
    visit_spec,
)

# The grid both budget bases are computed from.  Two sponsor-borne per-patient
# items project 12,000 + 360,000 = 372,000 cents of per-patient work; one
# routine-care item is billable to the payer and one milestone fee is
# invoiceable rather than per-patient.
GRID = [
    item_spec(
        "36415",
        classification="RESEARCH_PAID",
        budget_category="PER_PATIENT",
        charge_master_unit_cents=5000,
        negotiated_unit_cents=3000,
        expected_occurrences=4,
    ),
    item_spec(
        "71260",
        classification="RESEARCH_PAID",
        budget_category="PER_PATIENT",
        charge_master_unit_cents=250000,
        negotiated_unit_cents=180000,
        expected_occurrences=2,
    ),
    item_spec(
        "80053",
        classification="ROUTINE_CARE",
        medicare_coverage_basis="STANDARD_OF_CARE",
        budget_category="PER_PATIENT",
        charge_master_unit_cents=9000,
        negotiated_unit_cents=9000,
        expected_occurrences=1,
    ),
    item_spec(
        "IRB-FEE",
        classification="RESEARCH_PAID",
        budget_category="INVOICEABLE",
        charge_master_unit_cents=300000,
        negotiated_unit_cents=300000,
        expected_occurrences=1,
    ),
]

VISITS = [visit_spec("Cycle 1 Day 1", 1, 0, 0, 3)]

# The calendar routes 36415 three times where the analysis projected four, and
# routes the routine-care panel once, which the sponsor never pays for.
ROUTES = [
    route_spec("Cycle 1 Day 1", "36415", occurrences=3),
    route_spec("Cycle 1 Day 1", "71260", occurrences=2),
    route_spec("Cycle 1 Day 1", "80053", occurrences=1),
]


def _build(study_id, analysis_id, basis, rate, user_id=MANAGER_ONE):
    payload = budget_build_payload(
        analysis_id,
        study_version(study_id),
        basis=basis,
        indirect_rate_pct=rate,
    )
    return validate_success(
        api_client.build_budget(study_id, payload, make_manager_headers(user_id)), 200
    )


class TestBudgetBasisDivergence:
    """The same approved analysis priced two ways."""

    def test_01_coverage_driven_basis_prices_the_protocols_own_projection(self):
        """The coverage-driven per-patient subtotal is the analysis' projection.

        PRD §3.5: "Under `COVERAGE_DRIVEN`, `per_patient_subtotal_cents` is the
        sum, over the source analysis' items whose `billable_to` is `SPONSOR`
        and whose `budget_category` is `PER_PATIENT`, of that item's
        `units_per_occurrence` multiplied by its `expected_occurrences`
        multiplied by its `negotiated_unit_cents` — the protocol's own
        projection."

        Design: Difficulty/dual_variant_calc/budget_basis_variant_divergence_on_same_analysis
        """
        ctx = setup_published_calendar(
            GRID,
            VISITS,
            ROUTES,
            qct_basis=None,
            study_overrides={
                "protocol_number": "AMC-2390-A",
                "funding_source": "INDUSTRY_SPONSORED",
            },
        )
        study = _build(ctx["study"]["id"], ctx["analysis"]["id"], "COVERAGE_DRIVEN", 30.0)

        assert study["budget_basis"] == "COVERAGE_DRIVEN"
        assert study["budget_status"] == "BUILT"
        assert study["effective_indirect_rate_pct"] == 32.0
        assert study["per_patient_subtotal_cents"] == 372000
        assert study["per_patient_budget_cents"] == 491040
        assert study["invoiceable_subtotal_cents"] == 300000
        assert study["invoiceable_budget_cents"] == 396000

    def test_02_calendar_driven_basis_prices_what_the_ehr_will_actually_drop(self):
        """Rebuilding calendar-driven on the same analysis moves only the
        per-patient side, because the calendar routes 36415 three times where
        the analysis projected four.

        PRD §3.5: "The two figures differ whenever the calendar routes an item a
        different number of times than the analysis projected."

        Design: Difficulty/dual_variant_calc/budget_basis_variant_divergence_on_same_analysis
        """
        ctx = setup_published_calendar(
            GRID,
            VISITS,
            ROUTES,
            qct_basis=None,
            study_overrides={
                "protocol_number": "AMC-2390-A",
                "funding_source": "INDUSTRY_SPONSORED",
            },
        )
        coverage = _build(
            ctx["study"]["id"], ctx["analysis"]["id"], "COVERAGE_DRIVEN", 30.0
        )
        calendar = _build(
            ctx["study"]["id"], ctx["analysis"]["id"], "CALENDAR_DRIVEN", 30.0
        )

        assert calendar["budget_basis"] == "CALENDAR_DRIVEN"
        assert calendar["per_patient_subtotal_cents"] == 369000
        assert calendar["per_patient_budget_cents"] == 487080
        assert calendar["per_patient_subtotal_cents"] != coverage["per_patient_subtotal_cents"]

    def test_03_invoiceable_subtotal_is_identical_under_both_bases(self):
        """Only the per-patient subtotal diverges; the milestone fee does not.

        PRD §3.5: "The invoiceable subtotal is identical under both bases."

        Design: Difficulty/dual_variant_calc/budget_basis_variant_divergence_on_same_analysis
        """
        ctx = setup_published_calendar(
            GRID,
            VISITS,
            ROUTES,
            qct_basis=None,
            study_overrides={
                "protocol_number": "AMC-2390-A",
                "funding_source": "INDUSTRY_SPONSORED",
            },
        )
        coverage = _build(
            ctx["study"]["id"], ctx["analysis"]["id"], "COVERAGE_DRIVEN", 30.0
        )
        calendar = _build(
            ctx["study"]["id"], ctx["analysis"]["id"], "CALENDAR_DRIVEN", 30.0
        )

        assert coverage["invoiceable_subtotal_cents"] == 300000
        assert calendar["invoiceable_subtotal_cents"] == 300000
        assert coverage["invoiceable_budget_cents"] == calendar["invoiceable_budget_cents"] == 396000


class TestIndirectRateBranches:
    """funding source, per-patient tier, and requested rate interacting."""

    @pytest.mark.parametrize(
        "requested_rate, expected_rate, expected_budget",
        [
            # The surcharge is added first and then capped along with the rate.
            (30.0, 32.0, 491040),
            # Below the cap the surcharge really is added: 28.0 + 3.0 = 31.0.
            (28.0, 31.0, 487320),
        ],
    )
    def test_04_small_industry_study_adds_the_surcharge_before_the_cap(
        self, requested_rate, expected_rate, expected_budget
    ):
        """A small industry study's surcharge is capped with the rate, not on top.

        PRD §3.5: "The order matters: a small industry study requesting 30.0
        percent lands on 32.0 percent, not 33.0 percent, because the surcharge
        is capped along with the rate rather than added on top of the cap."

        Design: Difficulty/combinatorial_formula/indirect_rate_surcharge_before_cap_three_input_interaction
        """
        ctx = setup_study_with_approved_analysis(
            GRID,
            qct_basis=None,
            study_overrides={
                "protocol_number": "AMC-2390-C",
                "funding_source": "INDUSTRY_SPONSORED",
            },
        )
        study = _build(
            ctx["study"]["id"], ctx["analysis"]["id"], "COVERAGE_DRIVEN", requested_rate
        )

        assert study["per_patient_subtotal_cents"] == 372000
        assert study["indirect_rate_pct"] == requested_rate
        assert study["effective_indirect_rate_pct"] == expected_rate
        assert study["per_patient_budget_cents"] == expected_budget
        # Neither the uncapped surcharge nor the bare requested rate.
        assert study["per_patient_budget_cents"] != 494760
        assert study["per_patient_budget_cents"] != 483600

    @pytest.mark.parametrize(
        "funding_source, requested_rate, expected_rate, expected_budget",
        [
            ("FEDERALLY_FUNDED", 40.0, 26.0, 468720),
            ("INVESTIGATOR_INITIATED", 40.0, 0.0, 372000),
        ],
    )
    def test_05_non_industry_funding_never_takes_the_small_study_surcharge(
        self, funding_source, requested_rate, expected_rate, expected_budget
    ):
        """The federal cap and the investigator-initiated zero ignore the tier.

        PRD §3.5: "A `FEDERALLY_FUNDED` study takes the lesser of the requested
        `indirect_rate_pct` and the federal cap of 26.0 percent. An
        `INVESTIGATOR_INITIATED` study takes 0.0 percent outright, whatever was
        requested."

        Design: Difficulty/combinatorial_formula/indirect_rate_surcharge_before_cap_three_input_interaction
        """
        ctx = setup_study_with_approved_analysis(
            GRID,
            qct_basis=None,
            study_overrides={
                "protocol_number": "AMC-2390-D",
                "funding_source": funding_source,
            },
        )
        study = _build(
            ctx["study"]["id"], ctx["analysis"]["id"], "COVERAGE_DRIVEN", requested_rate
        )

        assert study["per_patient_subtotal_cents"] == 372000
        assert study["effective_indirect_rate_pct"] == expected_rate
        assert study["per_patient_budget_cents"] == expected_budget


class TestIndustryTierBoundary:
    """The industry tier threshold sits at exactly 500,000 cents."""

    def test_06_one_cent_below_the_tier_takes_the_small_study_surcharge(self):
        """A 499,999-cent subtotal is below the threshold, so 20.0 becomes 23.0.

        PRD §3.5: "below that threshold a small-study surcharge of 3.0
        percentage points is added to the requested rate *first* and the
        industry cap of 32.0 percent is applied to that sum"

        Design: Difficulty/boundary_precision_check/industry_indirect_tier_boundary_at_500000_subtotal
        """
        ctx = setup_study_with_approved_analysis(
            [
                item_spec(
                    "J3490",
                    classification="RESEARCH_PAID",
                    budget_category="PER_PATIENT",
                    negotiated_unit_cents=499999,
                    charge_master_unit_cents=600000,
                    expected_occurrences=1,
                )
            ],
            qct_basis=None,
            study_overrides={
                "protocol_number": "AMC-2390-S",
                "funding_source": "INDUSTRY_SPONSORED",
            },
        )
        study = _build(ctx["study"]["id"], ctx["analysis"]["id"], "COVERAGE_DRIVEN", 20.0)

        assert study["per_patient_subtotal_cents"] == 499999
        assert study["effective_indirect_rate_pct"] == 23.0
        assert study["per_patient_budget_cents"] == 614999

    def test_07_exactly_at_the_tier_takes_the_bare_requested_rate(self):
        """A 500,000-cent subtotal is at the threshold, so 20.0 stays 20.0 — and
        the larger protocol therefore carries the smaller budget.

        PRD §3.5: "An `INDUSTRY_SPONSORED` study is tiered on the per-patient
        subtotal just computed: at or above 500,000 cents — that is, five
        thousand dollars of sponsor-borne per-patient work — it takes the lesser
        of the requested rate and the industry cap of 32.0 percent"

        Design: Difficulty/boundary_precision_check/industry_indirect_tier_boundary_at_500000_subtotal
        """
        ctx = setup_study_with_approved_analysis(
            [
                item_spec(
                    "J3490",
                    classification="RESEARCH_PAID",
                    budget_category="PER_PATIENT",
                    negotiated_unit_cents=250000,
                    charge_master_unit_cents=300000,
                    expected_occurrences=2,
                )
            ],
            qct_basis=None,
            study_overrides={
                "protocol_number": "AMC-2390-T",
                "funding_source": "INDUSTRY_SPONSORED",
            },
        )
        study = _build(ctx["study"]["id"], ctx["analysis"]["id"], "COVERAGE_DRIVEN", 20.0)

        assert study["per_patient_subtotal_cents"] == 500000
        assert study["effective_indirect_rate_pct"] == 20.0
        assert study["per_patient_budget_cents"] == 600000
        # One cent more of sponsor work buys 14,999 cents less budget.
        assert study["per_patient_budget_cents"] < 614999


class TestLifecycleAndBudgetDimensionsMoveApart:
    """An implemented amendment walks the lifecycle back while the budget
    dimension walks forward into ``SUPERSEDED``."""

    SMALL_GRID = [
        item_spec(
            "36415",
            classification="RESEARCH_PAID",
            budget_category="PER_PATIENT",
            charge_master_unit_cents=5000,
            negotiated_unit_cents=3000,
            expected_occurrences=4,
        )
    ]

    def _executed(self):
        return setup_study_with_executed_budget(
            self.SMALL_GRID,
            indirect_rate_pct=40.0,
            qct_basis=None,
            study_overrides={
                "protocol_number": "AMC-2390-Q",
                "funding_source": "FEDERALLY_FUNDED",
            },
        )

    def test_08_implementing_a_reanalysis_amendment_cycles_the_lifecycle_back(self):
        """The lifecycle returns to ``COVERAGE_PENDING`` while the budget moves
        ``EXECUTED -> SUPERSEDED`` in the same request.

        PRD §3.9: "The second link fires only when `reanalysis_required` is
        true: the study's `lifecycle_status` moves to `COVERAGE_PENDING` —
        cycling back from `COVERAGE_APPROVED` or from `OPEN_TO_ACCRUAL` — and,
        if the budget stood at `EXECUTED`, `budget_status` moves `EXECUTED →
        SUPERSEDED`."

        Design: Difficulty/non_linear_state_machine/study_lifecycle_cycles_back_while_budget_dimension_supersedes
        """
        ctx = self._executed()
        assert ctx["study"]["lifecycle_status"] == "COVERAGE_APPROVED"
        assert ctx["study"]["budget_status"] == "EXECUTED"
        assert ctx["study"]["effective_indirect_rate_pct"] == 26.0
        assert ctx["study"]["per_patient_budget_cents"] == 15120

        amendment = file_amendment(
            ctx["study"]["id"], scope="ITEM_CHANGE", effective_date="2026-08-10"
        )
        set_clock("2026-08-12T00:00:00Z")
        implemented = implement_amendment(amendment["id"])
        study = read_study(ctx["study"]["id"])

        assert implemented["status"] == "IMPLEMENTED"
        assert implemented["reanalysis_required"] is True
        assert implemented["calendar_rebuild_required"] is False
        assert study["lifecycle_status"] == "COVERAGE_PENDING"
        assert study["budget_status"] == "SUPERSEDED"
        assert study["rebuild_required_calendar_count"] == 0
        assert study["billing_hold_posture"] == "PAYER_BLOCKED"
        # Superseding the budget does not recompute its figures.
        assert study["per_patient_budget_cents"] == 15120

    def test_09_re_approval_restores_the_lifecycle_without_touching_the_budget(self):
        """A fresh approved revision lifts the lifecycle back to
        ``COVERAGE_APPROVED`` while the budget is still ``SUPERSEDED``, and only
        a rebuild moves the budget dimension — clearing the executor.

        PRD §3.5: "The build also records `budget_source_analysis_id` as the
        analysis drawn from, `budget_basis` as the `COVERAGE_DRIVEN` or
        `CALENDAR_DRIVEN` variant used, `indirect_rate_pct` as the rate
        requested, and `budget_built_by_user_id` as the acting user — and it
        clears `budget_executed_by_user_id` back to null."

        Design: Difficulty/non_linear_state_machine/study_lifecycle_cycles_back_while_budget_dimension_supersedes
        """
        ctx = self._executed()
        amendment = file_amendment(
            ctx["study"]["id"], scope="ITEM_CHANGE", effective_date="2026-08-10"
        )
        set_clock("2026-08-12T00:00:00Z")
        implement_amendment(amendment["id"])

        revision = open_analysis(
            ctx["study"]["id"],
            user_id=ANALYST_ONE,
            supersedes_analysis_id=ctx["analysis"]["id"],
        )
        assert revision["revision_number"] == 2
        add_items(revision["id"], self.SMALL_GRID)
        submit_analysis(revision["id"])
        approve_analysis(revision["id"], user_id=REVIEWER_ONE)

        study = read_study(ctx["study"]["id"])
        assert study["lifecycle_status"] == "COVERAGE_APPROVED"
        assert study["budget_status"] == "SUPERSEDED"

        rebuilt = _build(study["id"], revision["id"], "COVERAGE_DRIVEN", 40.0)
        assert rebuilt["budget_status"] == "BUILT"
        assert rebuilt["budget_built_by_user_id"] == MANAGER_ONE
        assert rebuilt["budget_executed_by_user_id"] is None
        assert rebuilt["budget_source_analysis_id"] == revision["id"]

        executed = execute_budget(study["id"], user_id=MANAGER_TWO)
        assert executed["budget_status"] == "EXECUTED"
        assert executed["lifecycle_status"] == "COVERAGE_APPROVED"
