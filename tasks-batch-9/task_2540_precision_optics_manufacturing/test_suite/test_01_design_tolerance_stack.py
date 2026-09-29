"""The dual-variant tolerance stack-up and the verdict it records."""

from test_helpers import (
    ERR_TOLERANCE_BUDGET_EXCEEDED,
    ERR_TOLERANCE_STACK_EMPTY,
    add_allocation,
    assert_stack_outputs_null,
    assert_tolerance_stack,
    assert_wavefront_value,
    create_design,
    make_optics_engineer_headers,
    validate_error,
    validate_success,
)

FOUR_CONTRIBUTORS = (
    {
        "contributor_type": "SURFACE_IRREGULARITY",
        "sensitivity_waves_per_unit": 1.5,
        "manufacturing_tolerance_units": 0.0250,
    },
    {
        "contributor_type": "INDEX_HOMOGENEITY",
        "sensitivity_waves_per_unit": 2.0,
        "manufacturing_tolerance_units": 0.0180,
    },
    {
        "contributor_type": "WEDGE_ANGLE",
        "sensitivity_waves_per_unit": 3.0,
        "manufacturing_tolerance_units": 0.0125,
    },
    {
        "contributor_type": "CENTER_THICKNESS",
        "sensitivity_waves_per_unit": 4.0,
        "manufacturing_tolerance_units": 0.0090,
    },
)

TINY_CONTRIBUTOR = {
    "contributor_type": "SURFACE_IRREGULARITY",
    "sensitivity_waves_per_unit": 0.5,
    "manufacturing_tolerance_units": 0.0025,
}


def _lodge(api, design_code, **overrides):
    """Lodge a design with an explicit code and return the created row."""
    return create_design(api, design_code=design_code, **overrides)


def _allocate_four(api, design_id):
    """Add the four named error contributors to a draft design."""
    return [add_allocation(api, design_id, **spec) for spec in FOUR_CONTRIBUTORS]


class TestDualVariantStackDivergence:
    """Both stack conventions are always computed; tolerance_method picks one."""

    def test_statistical_method_lets_the_root_sum_square_govern_a_passing_design(
        self, api
    ):
        """The statistical combination governs and fits inside the budget.

        The PRD states that "`rss_stack_waves` is the square root of the sum of the
        squares of the contributions, rounded half up to four decimal places".

        Design: Difficulty/dual_variant_calc/tolerance_stack_statistical_and_worst_case_variants_diverge_on_design
        """
        design = _lodge(
            api,
            "OD-2540-A",
            tolerance_budget_waves=0.0800,
            tolerance_method="STATISTICAL",
        )
        _allocate_four(api, design["id"])

        analysed = validate_success(
            api.run_tolerance_analysis(design["id"], make_optics_engineer_headers()),
            expected_status=200,
        )

        assert_tolerance_stack(analysed, 0.0735, 0.1470, 0.0735, "PASS")
        assert analysed["design_status"] == "TOLERANCED", (
            f"design_status must be TOLERANCED, got {analysed['design_status']}"
        )

    def test_worst_case_method_lets_the_arithmetic_sum_govern_and_fail(self, api):
        """The pessimistic combination governs and breaches the same budget.

        The PRD states that "`worst_case_stack_waves` is the plain arithmetic sum of
        the same contributions, rounded half up to four decimal places".

        Design: Difficulty/dual_variant_calc/tolerance_stack_statistical_and_worst_case_variants_diverge_on_design
        """
        design = _lodge(
            api,
            "OD-2540-B",
            tolerance_budget_waves=0.0800,
            tolerance_method="WORST_CASE",
        )
        _allocate_four(api, design["id"])

        analysed = validate_success(
            api.run_tolerance_analysis(design["id"], make_optics_engineer_headers()),
            expected_status=200,
        )

        assert_tolerance_stack(analysed, 0.0735, 0.1470, 0.1470, "FAIL")
        assert analysed["design_status"] == "TOLERANCED", (
            "a failing verdict still moves the design to TOLERANCED, got "
            f"{analysed['design_status']}"
        )

    def test_a_failing_verdict_is_recorded_but_not_enforced_by_the_analysis(self, api):
        """Either verdict returns 200 and either verdict advances the design.

        The PRD states that "**the analysis records a verdict but does not enforce the
        budget**: either verdict returns 200, and either verdict moves the design to
        `TOLERANCED`."

        Design: Difficulty/dual_variant_calc/tolerance_stack_statistical_and_worst_case_variants_diverge_on_design
        """
        passing = _lodge(
            api,
            "OD-2540-A2",
            tolerance_budget_waves=0.0800,
            tolerance_method="STATISTICAL",
        )
        failing = _lodge(
            api,
            "OD-2540-B2",
            tolerance_budget_waves=0.0800,
            tolerance_method="WORST_CASE",
        )
        for design_id in (passing["id"], failing["id"]):
            _allocate_four(api, design_id)

        passing_response = api.run_tolerance_analysis(
            passing["id"], make_optics_engineer_headers()
        )
        failing_response = api.run_tolerance_analysis(
            failing["id"], make_optics_engineer_headers()
        )

        passing_data = validate_success(passing_response, expected_status=200)
        failing_data = validate_success(failing_response, expected_status=200)
        assert passing_data["tolerance_verdict"] == "PASS"
        assert failing_data["tolerance_verdict"] == "FAIL"
        for data in (passing_data, failing_data):
            assert data["design_status"] == "TOLERANCED", (
                "both verdicts move the design to TOLERANCED, got "
                f"{data['design_status']}"
            )


class TestPerContributorRoundingBeforeCombination:
    """Each contribution is frozen rounded, then the rounded values combine."""

    def test_each_contribution_is_rounded_and_frozen_when_it_is_created(self, api):
        """A raw product of 0.00125 waves is stored as 0.0013 waves.

        The PRD states that the system "computes `contribution_waves` as the
        sensitivity multiplied by the assigned tolerance, rounded half up to four
        decimal places, and **freezes that rounded value on the row**".

        Design: Difficulty/combinatorial_formula/tolerance_stack_pins_round_per_contributor_before_summing
        """
        design = _lodge(
            api,
            "OD-2540-R",
            aperture_mm=80.0,
            tolerance_budget_waves=0.0800,
            tolerance_method="WORST_CASE",
        )

        allocations = [
            add_allocation(api, design["id"], **TINY_CONTRIBUTOR) for _ in range(4)
        ]

        for allocation in allocations:
            assert_wavefront_value(
                allocation["contribution_waves"], 0.0013, "contribution_waves"
            )

    def test_the_worst_case_sum_adds_the_rounded_contributions(self, api):
        """Four contributions of 0.0013 sum to 0.0052, not to the raw 0.0050.

        The PRD states that "each contribution is rounded to four decimals
        **first**, when it is created, then the rounded values are combined, then
        the combined value is rounded to four decimals again".

        Design: Difficulty/combinatorial_formula/tolerance_stack_pins_round_per_contributor_before_summing
        """
        design = _lodge(
            api,
            "OD-2540-R",
            aperture_mm=80.0,
            tolerance_budget_waves=0.0800,
            tolerance_method="WORST_CASE",
        )
        for _ in range(4):
            add_allocation(api, design["id"], **TINY_CONTRIBUTOR)

        analysed = validate_success(
            api.run_tolerance_analysis(design["id"], make_optics_engineer_headers()),
            expected_status=200,
        )

        assert_wavefront_value(
            analysed["worst_case_stack_waves"], 0.0052, "worst_case_stack_waves"
        )
        assert analysed["worst_case_stack_waves"] != 0.0050, (
            "combining the raw unrounded products and rounding once at the end is "
            "incorrect"
        )

    def test_the_root_sum_square_combines_the_rounded_contributions(self, api):
        """The statistical variant reads 0.0026, not the raw-product 0.0025.

        The PRD states that "Combining raw unrounded products and rounding only
        once at the end produces a different fourth decimal and is incorrect".

        Design: Difficulty/combinatorial_formula/tolerance_stack_pins_round_per_contributor_before_summing
        """
        design = _lodge(
            api,
            "OD-2540-R",
            aperture_mm=80.0,
            tolerance_budget_waves=0.0800,
            tolerance_method="WORST_CASE",
        )
        for _ in range(4):
            add_allocation(api, design["id"], **TINY_CONTRIBUTOR)

        analysed = validate_success(
            api.run_tolerance_analysis(design["id"], make_optics_engineer_headers()),
            expected_status=200,
        )

        assert_tolerance_stack(analysed, 0.0026, 0.0052, 0.0052, "PASS")


class TestEmptyActiveAllocationSet:
    """An analysis over an empty active set is refused before any output."""

    def test_an_analysis_over_only_retired_contributors_is_refused(self, api):
        """Retiring the only contributor empties the input set.

        The PRD states that "if the active set is empty the request is refused with
        `ERR_TOLERANCE_STACK_EMPTY` before any output is written".

        Design: Difficulty/boundary_precision_check/tolerance_analysis_on_empty_active_allocation_set_is_rejected
        """
        design = _lodge(api, "OD-2540-E", tolerance_budget_waves=0.0800)
        allocation = add_allocation(api, design["id"])
        validate_success(
            api.retire_tolerance_allocation(
                allocation["id"], make_optics_engineer_headers()
            ),
            expected_status=200,
        )

        response = api.run_tolerance_analysis(
            design["id"], make_optics_engineer_headers()
        )

        validate_error(response, ERR_TOLERANCE_STACK_EMPTY)

    def test_the_refused_analysis_leaves_the_design_and_its_outputs_untouched(
        self, api
    ):
        """No stack output is written and the design stays a draft.

        The PRD states that the refusal happens "before any output is written",
        and that a newly lodged design carries "all four computed stack outputs —
        `rss_stack_waves`, `worst_case_stack_waves`, `governing_stack_waves` and
        `allocated_tolerance_waves` — set to null".

        Design: Difficulty/boundary_precision_check/tolerance_analysis_on_empty_active_allocation_set_is_rejected
        """
        design = _lodge(api, "OD-2540-E", tolerance_budget_waves=0.0800)
        allocation = add_allocation(api, design["id"])
        api.retire_tolerance_allocation(allocation["id"], make_optics_engineer_headers())
        api.run_tolerance_analysis(design["id"], make_optics_engineer_headers())

        after = validate_success(
            api.get_optical_design(design["id"], make_optics_engineer_headers()),
            expected_status=200,
        )
        retired = validate_success(
            api.get_tolerance_allocation(
                allocation["id"], make_optics_engineer_headers()
            ),
            expected_status=200,
        )

        assert after["design_status"] == "DRAFT", (
            f"design_status must still be DRAFT, got {after['design_status']}"
        )
        assert after["tolerance_verdict"] == "PENDING", (
            f"tolerance_verdict must still be PENDING, got {after['tolerance_verdict']}"
        )
        assert_stack_outputs_null(after)
        assert retired["allocation_status"] == "RETIRED", (
            f"allocation_status must be RETIRED, got {retired['allocation_status']}"
        )

    def test_a_fresh_contributor_restores_a_non_empty_input_set(self, api):
        """One active contributor is enough for the stack-up to run.

        The PRD states that "The input set is every allocation of the design whose
        `allocation_status` is `ACTIVE`, enumerated in `created_at` ascending
        order".

        Design: Difficulty/boundary_precision_check/tolerance_analysis_on_empty_active_allocation_set_is_rejected
        """
        design = _lodge(api, "OD-2540-E", tolerance_budget_waves=0.0800)
        allocation = add_allocation(api, design["id"])
        api.retire_tolerance_allocation(allocation["id"], make_optics_engineer_headers())
        api.run_tolerance_analysis(design["id"], make_optics_engineer_headers())
        fresh = add_allocation(
            api,
            design["id"],
            contributor_type="INDEX_HOMOGENEITY",
            sensitivity_waves_per_unit=0.5,
            manufacturing_tolerance_units=0.0100,
        )

        analysed = validate_success(
            api.run_tolerance_analysis(design["id"], make_optics_engineer_headers()),
            expected_status=200,
        )

        assert_wavefront_value(
            fresh["contribution_waves"], 0.0050, "contribution_waves"
        )
        assert_tolerance_stack(analysed, 0.0050, 0.0050, 0.0050, "PASS")
        assert analysed["design_status"] == "TOLERANCED"


def test_retired_contributors_are_excluded_from_both_stack_variants(api):
    """A retired row leaves both computed variants behind.

    The PRD states that "Retiring a contributor sets its `allocation_status` to
    `RETIRED`, which removes it from every later stack-up input set".

    Design: Corner/calculations/retired_tolerance_allocations_are_excluded_from_both_stack_variants
    """
    design = _lodge(api, "OD-2540-X", tolerance_budget_waves=0.0800)
    kept = add_allocation(api, design["id"], **FOUR_CONTRIBUTORS[0])
    dropped = add_allocation(api, design["id"], **FOUR_CONTRIBUTORS[1])
    validate_success(
        api.retire_tolerance_allocation(dropped["id"], make_optics_engineer_headers()),
        expected_status=200,
    )

    analysed = validate_success(
        api.run_tolerance_analysis(design["id"], make_optics_engineer_headers()),
        expected_status=200,
    )

    assert_wavefront_value(kept["contribution_waves"], 0.0375, "contribution_waves")
    assert_wavefront_value(dropped["contribution_waves"], 0.0360, "contribution_waves")
    assert_tolerance_stack(analysed, 0.0375, 0.0375, 0.0375, "PASS")


def test_tolerance_method_selects_which_computed_stack_governs_the_verdict(api):
    """Identical contributors, opposite conventions, different governing figure.

    The PRD states that "`tolerance_method` selects which of the two stack-up
    conventions governs this design and defaults to `STATISTICAL`".

    Design: Corner/calculations/tolerance_method_selects_which_computed_stack_governs_the_verdict
    """
    specs = FOUR_CONTRIBUTORS[:2]
    statistical = _lodge(
        api, "OD-2540-M1", tolerance_budget_waves=0.0600, tolerance_method="STATISTICAL"
    )
    worst_case = _lodge(
        api, "OD-2540-M2", tolerance_budget_waves=0.0600, tolerance_method="WORST_CASE"
    )
    for design_id in (statistical["id"], worst_case["id"]):
        for spec in specs:
            add_allocation(api, design_id, **spec)

    statistical_result = validate_success(
        api.run_tolerance_analysis(statistical["id"], make_optics_engineer_headers()),
        expected_status=200,
    )
    worst_case_result = validate_success(
        api.run_tolerance_analysis(worst_case["id"], make_optics_engineer_headers()),
        expected_status=200,
    )

    assert_tolerance_stack(statistical_result, 0.0520, 0.0735, 0.0520, "PASS")
    assert_tolerance_stack(worst_case_result, 0.0520, 0.0735, 0.0735, "FAIL")


def test_a_failing_tolerance_verdict_is_refused_only_at_release(api):
    """The budget is enforced at release, and a failed design is a dead end.

    The PRD states that release "is the only place the budget is enforced: a design
    whose `tolerance_verdict` is `FAIL` is refused with
    `ERR_TOLERANCE_BUDGET_EXCEEDED` (HTTP 422)".

    Design: Corner/errors/a_failing_tolerance_verdict_is_refused_only_at_release_and_is_a_dead_end
    """
    failing = _lodge(api, "OD-2540-FAIL", tolerance_budget_waves=0.0300)
    passing = _lodge(api, "OD-2540-PASS", tolerance_budget_waves=0.0400)
    add_allocation(api, failing["id"], **FOUR_CONTRIBUTORS[0])
    add_allocation(api, passing["id"], **FOUR_CONTRIBUTORS[0])

    failing_analysis = validate_success(
        api.run_tolerance_analysis(failing["id"], make_optics_engineer_headers()),
        expected_status=200,
    )
    failing_release = api.release_optical_design(
        failing["id"], make_optics_engineer_headers()
    )
    passing_analysis = validate_success(
        api.run_tolerance_analysis(passing["id"], make_optics_engineer_headers()),
        expected_status=200,
    )
    passing_release = validate_success(
        api.release_optical_design(passing["id"], make_optics_engineer_headers()),
        expected_status=200,
    )

    assert_tolerance_stack(failing_analysis, 0.0375, 0.0375, 0.0375, "FAIL")
    validate_error(failing_release, ERR_TOLERANCE_BUDGET_EXCEEDED)
    stuck = validate_success(
        api.get_optical_design(failing["id"], make_optics_engineer_headers()),
        expected_status=200,
    )
    assert stuck["design_status"] == "TOLERANCED", (
        "a refused release leaves the design in TOLERANCED, got "
        f"{stuck['design_status']}"
    )
    assert stuck["tolerance_verdict"] == "FAIL"
    assert passing_analysis["tolerance_verdict"] == "PASS"
    assert passing_release["design_status"] == "RELEASED", (
        f"design_status must be RELEASED, got {passing_release['design_status']}"
    )
