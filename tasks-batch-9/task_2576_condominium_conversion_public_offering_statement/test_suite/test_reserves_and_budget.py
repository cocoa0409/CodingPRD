"""Reserve studies and the first-year budget: the two funding methods, the adequacy
threshold, the single-pass fee tier and the per-unit assessment allocation.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import assert_cents, assert_decimal_equals, assert_page
from test_helpers.factories import (
    budget_payload,
    component_payload,
    reserve_study_payload,
    roof_standard,
)
from test_helpers.fixtures import (
    certify_plat,
    make_component,
    make_package,
    make_passed_gate,
    make_project,
    make_report,
    make_reserve_study,
    make_unit,
    project_version,
)
from test_helpers.test_users import sponsor_headers

STD_PROJECT = ("44 Cove Lane, Bangor ME", 1968, 2)


def test_component_method_reserve_study_returns_precomputed_funding_figures(api):
    """PRD: Under `COMPONENT_METHOD` each component is funded independently on a
    straight line. … Each component's annual amount is rounded **up** to whole cents —
    a ceiling, not a half-up round — and those per-component amounts are then summed
    into `recommended_annual_contribution_cents`.

    Design: Corner/calculations/component_method_reserve_study_returns_precomputed_funding_figures
    """
    project = make_project(api, *STD_PROJECT)
    gate = make_passed_gate(api, project["id"], [roof_standard()])

    study = validate_success(
        api.create_reserve_study(
            project["id"],
            reserve_study_payload(gate["report"]["id"], "COMPONENT_METHOD", 0),
            sponsor_headers(),
        ),
        expected_status=201,
    )
    assert study["method"] == "COMPONENT_METHOD"
    assert_cents(study["fully_funded_balance_cents"], 2500000, "fully_funded_balance_cents")
    assert_cents(
        study["recommended_annual_contribution_cents"],
        333334,
        "recommended_annual_contribution_cents",
    )
    assert study["percent_funded_bp"] == 0
    assert study["funding_status"] == "UNDERFUNDED"
    assert study["adoption_status"] == "PROPOSED"
    assert validate_success(api.get_project(project["id"], sponsor_headers()))[
        "suitability_gate"
    ] == "PASSED"


def test_reserve_method_variants_diverge_on_identical_component_set(api):
    """PRD: The two methods therefore diverge on the same component set whenever any two
    components' remaining useful lives differ or `opening_reserve_balance_cents` exceeds
    0: `COMPONENT_METHOD` charges per component regardless of the pool, while
    `CASH_FLOW_METHOD` solves for the single smallest level contribution that keeps the
    pool at or above the floor at every year end.

    Design: Corner/calculations/reserve_method_variants_diverge_on_identical_component_set
    """
    project = make_project(api, *STD_PROJECT)
    gate = make_passed_gate(api, project["id"], [roof_standard()])

    component_study = make_reserve_study(
        api, project["id"], gate["report"]["id"], "COMPONENT_METHOD", 0
    )
    cash_flow_study = make_reserve_study(
        api, project["id"], gate["report"]["id"], "CASH_FLOW_METHOD", 0
    )

    assert_cents(
        component_study["recommended_annual_contribution_cents"], 333334, "component method"
    )
    assert_cents(
        cash_flow_study["recommended_annual_contribution_cents"], 335000, "cash flow method"
    )
    assert (
        cash_flow_study["recommended_annual_contribution_cents"]
        - component_study["recommended_annual_contribution_cents"]
    ) == 1666
    assert_cents(component_study["fully_funded_balance_cents"], 2500000, "component ffb")
    assert_cents(cash_flow_study["fully_funded_balance_cents"], 2500000, "cash flow ffb")
    assert cash_flow_study["funding_status"] == "UNDERFUNDED"
    assert cash_flow_study["method"] == "CASH_FLOW_METHOD"


def test_budget_allocation_absorbs_negative_residual_on_first_unit(api):
    """PRD: those rounded amounts are summed; and the remainder is the total to distribute
    less that sum, a figure which may be negative when half-up rounding has
    over-allocated. When the remainder is not 0, the whole remainder is applied to
    exactly one unit — never spread — chosen by taking the included units ordered by
    `percentage_interest_bp` descending and breaking ties by `created_at` ascending, and
    taking the first.

    Design: Corner/calculations/budget_allocation_absorbs_negative_residual_on_first_unit
    """
    project = make_project(api, *STD_PROJECT)
    gate = make_passed_gate(api, project["id"], [roof_standard()])
    package = make_package(api, project["id"], "PAINT_TO_PAINT", "decl-1", "bylaws-1")
    u1 = make_unit(api, package["id"], "101", 5000, 1, 900, "as-built")
    u2 = make_unit(api, package["id"], "102", 5000, 2, 900, "as-built")
    certify_plat(api, package["id"])
    study = make_reserve_study(
        api, project["id"], gate["report"]["id"], "COMPONENT_METHOD", 0
    )

    budget = validate_success(
        api.create_budget(
            project["id"],
            budget_payload(study["id"], 1000000, project_version(api, project["id"])),
            sponsor_headers(),
        ),
        expected_status=201,
    )
    assert_cents(budget["reserve_contribution_cents"], 333334, "reserve_contribution_cents")
    assert_cents(budget["base_expense_cents"], 1333334, "base_expense_cents")
    assert budget["management_fee_bp"] == 800
    assert_cents(budget["management_fee_cents"], 106667, "management_fee_cents")
    assert_cents(budget["total_annual_expense_cents"], 1440001, "total_annual_expense_cents")
    assert_cents(budget["assessment_income_cents"], 1440001, "assessment_income_cents")
    assert_cents(
        budget["developer_deficit_funding_cents"], 0, "developer_deficit_funding_cents"
    )
    assert budget["developer_subsidy_flag"] is False
    assert budget["status"] == "DRAFT"

    first = validate_success(api.get_unit(u1["id"], sponsor_headers()))
    second = validate_success(api.get_unit(u2["id"], sponsor_headers()))
    assert_cents(first["unit_annual_assessment_cents"], 720000, "101 annual")
    assert_cents(first["unit_monthly_assessment_cents"], 60000, "101 monthly")
    assert_cents(second["unit_annual_assessment_cents"], 720001, "102 annual")
    assert_cents(second["unit_monthly_assessment_cents"], 60000, "102 monthly")
    assert first["percentage_interest_bp"] == 5000
    assert second["percentage_interest_bp"] == 5000


def test_reserve_study_rejects_engineering_report_from_another_project(api):
    """PRD: The `conversion_project_id` of the referenced engineering report … must all be
    equal to the project in scope; a mismatch is `ERR_PROJECT_SCOPE_MISMATCH` (HTTP 409).

    Design: Corner/validations/reserve_study_rejects_engineering_report_from_another_project
    """
    project_a = make_project(api, "44 Cove Lane, Bangor ME", 1968, 2)
    report_a = make_report(api, project_a["id"], "ER-1", "2026-07-10T00:00:00Z")
    project_b = make_project(api, "46 Cove Lane, Bangor ME", 1970, 2)
    report_b = make_report(api, project_b["id"], "ER-1", "2026-07-11T00:00:00Z")

    validate_error(
        api.create_reserve_study(
            project_a["id"],
            reserve_study_payload(report_b["id"], "COMPONENT_METHOD"),
            sponsor_headers(),
        ),
        "ERR_PROJECT_SCOPE_MISMATCH",
        expected_status=409,
    )
    validate_error(
        api.create_reserve_study(
            project_a["id"],
            reserve_study_payload(report_a["id"], "COMPONENT_METHOD"),
            sponsor_headers(),
        ),
        "ERR_SUITABILITY_GATE_FAILED",
        expected_status=409,
    )

    assert validate_success(api.get_report(report_b["id"], sponsor_headers()))[
        "conversion_project_id"
    ] == project_b["id"]
    assert validate_success(api.get_project(project_a["id"], sponsor_headers()))[
        "suitability_gate"
    ] == "UNEVALUATED"
    _, meta_a = validate_paginated(
        api.list_project_reserve_studies(project_a["id"], sponsor_headers())
    )
    assert_page(meta_a, total_count=0)
    _, meta_b = validate_paginated(
        api.list_project_reserve_studies(project_b["id"], sponsor_headers())
    )
    assert_page(meta_b, total_count=0)


def test_reserve_study_on_a_report_without_verified_components_is_refused(api):
    """PRD: the referenced report must have at least one `MajorComponent` at
    `verification_status` `VERIFIED`, refused otherwise with
    `ERR_NO_VERIFIED_COMPONENTS` (409).

    Design: Corner/errors/reserve_study_on_a_report_without_verified_components_is_refused
    """
    project = make_project(api, *STD_PROJECT)
    gate = make_passed_gate(api, project["id"], [roof_standard()], "ER-A")
    report_b = make_report(api, project["id"], "ER-B", "2026-07-20T00:00:00Z")
    component_b = make_component(api, report_b["id"], roof_standard())

    before = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert before["suitability_gate"] == "PASSED"
    assert_decimal_equals(before["suitability_score"], "100.00", "suitability_score")
    assert validate_success(api.get_component(component_b["id"], sponsor_headers()))[
        "verification_status"
    ] == "UNVERIFIED"
    assert validate_success(api.get_report(report_b["id"], sponsor_headers()))[
        "verified_component_count"
    ] == 0

    validate_error(
        api.create_reserve_study(
            project["id"],
            reserve_study_payload(report_b["id"], "COMPONENT_METHOD"),
            sponsor_headers(),
        ),
        "ERR_NO_VERIFIED_COMPONENTS",
        expected_status=409,
    )
    _, meta = validate_paginated(
        api.list_project_reserve_studies(project["id"], sponsor_headers())
    )
    assert_page(meta, total_count=0)

    study = validate_success(
        api.create_reserve_study(
            project["id"],
            reserve_study_payload(gate["report"]["id"], "COMPONENT_METHOD"),
            sponsor_headers(),
        ),
        expected_status=201,
    )
    assert study["engineering_report_id"] == gate["report"]["id"]
    assert_cents(study["fully_funded_balance_cents"], 2500000, "fully_funded_balance_cents")
    assert_cents(
        study["recommended_annual_contribution_cents"], 333334, "recommended contribution"
    )
    assert study["percent_funded_bp"] == 0
    assert study["funding_status"] == "UNDERFUNDED"
    assert study["adoption_status"] == "PROPOSED"


def test_stale_project_version_rejects_the_initial_budget_and_the_budget_write_consumes_the_token(api):
    """PRD: if `expected_conversion_project_version` does not match the project's current
    `version`, the request is rejected with `ERR_STALE_PROJECT_VERSION` and HTTP status
    412, and nothing is written. … On success the project's `version` is incremented by 1.

    Design: Corner/cross_cutting_complexity_layers/stale_project_version_rejects_the_initial_budget_and_the_budget_write_consumes_the_token
    """
    project = make_project(api, *STD_PROJECT)
    gate = make_passed_gate(api, project["id"], [roof_standard()])
    package = make_package(api, project["id"], "PAINT_TO_PAINT", "decl-1", "bylaws-1")
    unit = make_unit(api, package["id"], "101", 10000, 1, 900, "as-built")
    certify_plat(api, package["id"])
    study = make_reserve_study(
        api, project["id"], gate["report"]["id"], "COMPONENT_METHOD", 0
    )
    captured_version = project_version(api, project["id"])

    assert validate_success(api.get_project(project["id"], sponsor_headers()))[
        "suitability_gate"
    ] == "PASSED"
    before_unit = validate_success(api.get_unit(unit["id"], sponsor_headers()))
    assert before_unit["percentage_interest_bp"] == 10000
    assert_cents(before_unit["unit_annual_assessment_cents"], 0, "annual before")

    validate_error(
        api.create_budget(
            project["id"],
            budget_payload(study["id"], 1000000, captured_version - 1, "FY2027"),
            sponsor_headers(),
        ),
        "ERR_STALE_PROJECT_VERSION",
        expected_status=412,
    )
    _, meta = validate_paginated(api.list_project_budgets(project["id"], sponsor_headers()))
    assert_page(meta, total_count=0)
    assert_cents(
        validate_success(api.get_unit(unit["id"], sponsor_headers()))[
            "unit_annual_assessment_cents"
        ],
        0,
        "annual after refusal",
    )

    budget = validate_success(
        api.create_budget(
            project["id"],
            budget_payload(study["id"], 1000000, captured_version, "FY2027"),
            sponsor_headers(),
        ),
        expected_status=201,
    )
    assert_cents(budget["reserve_contribution_cents"], 333334, "reserve_contribution_cents")
    assert_cents(budget["base_expense_cents"], 1333334, "base_expense_cents")
    assert budget["management_fee_bp"] == 800
    assert_cents(budget["management_fee_cents"], 106667, "management_fee_cents")
    assert_cents(budget["total_annual_expense_cents"], 1440001, "total_annual_expense_cents")
    assert_cents(budget["assessment_income_cents"], 1440001, "assessment_income_cents")
    assert_cents(budget["developer_deficit_funding_cents"], 0, "deficit funding")
    assert budget["developer_subsidy_flag"] is False
    assert budget["status"] == "DRAFT"
    projected = validate_success(api.get_unit(unit["id"], sponsor_headers()))
    assert_cents(projected["unit_annual_assessment_cents"], 1440001, "annual after write")
    assert_cents(projected["unit_monthly_assessment_cents"], 120000, "monthly after write")

    validate_error(
        api.create_budget(
            project["id"],
            budget_payload(study["id"], 1000000, captured_version, "FY2028"),
            sponsor_headers(),
        ),
        "ERR_STALE_PROJECT_VERSION",
        expected_status=412,
    )
    _, meta = validate_paginated(api.list_project_budgets(project["id"], sponsor_headers()))
    assert_page(meta, total_count=1)
    assert validate_success(api.get_budget(budget["id"], sponsor_headers()))[
        "status"
    ] == "DRAFT"


def test_percent_funded_adequacy_threshold_is_inclusive_after_a_half_up_rounding(api):
    """PRD: `funding_status` then reads `ADEQUATE` when `percent_funded_bp` is **at or
    above** 7000 basis points and `UNDERFUNDED` below it; the comparison is inclusive, so
    a study sitting at exactly 7000 basis points — seventy percent funded — is `ADEQUATE`,
    while 6999 is `UNDERFUNDED`.

    Design: Corner/cross_cutting_complexity_layers/percent_funded_adequacy_threshold_is_inclusive_after_a_half_up_rounding
    """
    project = make_project(api, *STD_PROJECT)
    gate = make_passed_gate(api, project["id"], [roof_standard()])

    at_threshold = make_reserve_study(
        api, project["id"], gate["report"]["id"], "COMPONENT_METHOD", 1750000
    )
    half_up = make_reserve_study(
        api, project["id"], gate["report"]["id"], "COMPONENT_METHOD", 1749875
    )
    below = make_reserve_study(
        api, project["id"], gate["report"]["id"], "COMPONENT_METHOD", 1749874
    )

    assert_cents(at_threshold["fully_funded_balance_cents"], 2500000, "at threshold ffb")
    assert at_threshold["percent_funded_bp"] == 7000
    assert at_threshold["funding_status"] == "ADEQUATE"
    assert_cents(
        at_threshold["recommended_annual_contribution_cents"], 333334, "at threshold rac"
    )

    assert half_up["percent_funded_bp"] == 7000
    assert half_up["funding_status"] == "ADEQUATE"
    assert_cents(half_up["recommended_annual_contribution_cents"], 333334, "half up rac")

    assert below["percent_funded_bp"] == 6999
    assert below["funding_status"] == "UNDERFUNDED"
    assert_cents(below["recommended_annual_contribution_cents"], 333334, "below rac")
    assert_cents(below["fully_funded_balance_cents"], 2500000, "below ffb")

    for study in (at_threshold, half_up, below):
        assert validate_success(api.get_reserve_study(study["id"], sponsor_headers()))[
            "adoption_status"
        ] == "PROPOSED"
    _, meta = validate_paginated(
        api.list_project_reserve_studies(project["id"], sponsor_headers())
    )
    assert_page(meta, total_count=3)


def test_budget_write_projects_unit_assessments_readable_on_the_very_next_unit_get(api):
    """PRD: Step seven runs the per-unit assessment allocation described below using
    `total_annual_expense_cents` as the amount to distribute, then sets
    `assessment_income_cents` to the sum of `unit_annual_assessment_cents` over the
    project's units whose `declaration_status` is `INCLUDED`.

    Design: Corner/consistency_model/budget_write_projects_unit_assessments_readable_on_the_very_next_unit_get
    """
    project = make_project(api, *STD_PROJECT)
    gate = make_passed_gate(api, project["id"], [roof_standard()])
    package = make_package(api, project["id"], "PAINT_TO_PAINT", "decl-1", "bylaws-1")
    u1 = make_unit(api, package["id"], "101", 5000, 1, 900, "as-built")
    u2 = make_unit(api, package["id"], "102", 5000, 2, 900, "as-built")
    certify_plat(api, package["id"])
    study = make_reserve_study(
        api, project["id"], gate["report"]["id"], "COMPONENT_METHOD", 0
    )

    assert_cents(
        validate_success(api.get_unit(u1["id"], sponsor_headers()))[
            "unit_annual_assessment_cents"
        ],
        0,
        "101 annual before",
    )
    assert_cents(
        validate_success(api.get_unit(u2["id"], sponsor_headers()))[
            "unit_monthly_assessment_cents"
        ],
        0,
        "102 monthly before",
    )

    budget = validate_success(
        api.create_budget(
            project["id"],
            budget_payload(study["id"], 1000000, project_version(api, project["id"])),
            sponsor_headers(),
        ),
        expected_status=201,
    )
    assert_cents(budget["total_annual_expense_cents"], 1440001, "total_annual_expense_cents")
    assert_cents(budget["assessment_income_cents"], 1440001, "assessment_income_cents")
    assert_cents(budget["developer_deficit_funding_cents"], 0, "deficit funding")

    first = validate_success(api.get_unit(u1["id"], sponsor_headers()))
    assert_cents(first["unit_annual_assessment_cents"], 720000, "101 annual")
    assert_cents(first["unit_monthly_assessment_cents"], 60000, "101 monthly")
    assert first["percentage_interest_bp"] == 5000

    second = validate_success(api.get_unit(u2["id"], sponsor_headers()))
    assert_cents(second["unit_annual_assessment_cents"], 720001, "102 annual")
    assert_cents(second["unit_monthly_assessment_cents"], 60000, "102 monthly")

    _, meta = validate_paginated(api.list_project_budgets(project["id"], sponsor_headers()))
    assert_page(meta, total_count=1)


def test_budget_single_pass_fee_tier_no_retier_on_total(api):
    """PRD: Step six is a prohibition rather than an action: **there is no re-tiering**. Even
    when `total_annual_expense_cents` crosses a tier ceiling that `base_expense_cents` did
    not, `management_fee_bp` and `management_fee_cents` retain the values chosen in steps
    three and four.

    Design: Difficulty/combinatorial_formula/budget_single_pass_fee_tier_no_retier_on_total
    """
    project = make_project(api, "7 Larkspur Court, Albany NY", 1974, 3)
    gate = make_passed_gate(
        api,
        project["id"],
        [
            component_payload(
                "FOUNDATION",
                40,
                20,
                10000000,
                5000,
                "EXCELLENT",
                planned_remediation_gain_years=0,
                is_life_safety=False,
                is_structural=True,
            )
        ],
        "ER-B",
    )
    package = make_package(
        api,
        project["id"],
        "STUD_TO_STUD",
        "s3://decl/larkspur.pdf",
        "s3://bylaws/larkspur.pdf",
    )
    u1 = make_unit(api, package["id"], "L-1", 3333, 1, 820, "stud faces")
    u2 = make_unit(api, package["id"], "L-2", 3333, 2, 820, "stud faces")
    u3 = make_unit(api, package["id"], "L-3", 3334, 3, 840, "stud faces")
    certify_plat(api, package["id"])
    study = make_reserve_study(
        api, project["id"], gate["report"]["id"], "COMPONENT_METHOD", 0
    )
    assert_cents(study["fully_funded_balance_cents"], 3333333, "fully_funded_balance_cents")
    assert_cents(study["recommended_annual_contribution_cents"], 125000, "recommended")
    assert study["percent_funded_bp"] == 0
    assert study["funding_status"] == "UNDERFUNDED"

    budget = validate_success(
        api.create_budget(
            project["id"],
            budget_payload(study["id"], 11775000, project_version(api, project["id"])),
            sponsor_headers(),
        ),
        expected_status=201,
    )
    assert_cents(budget["reserve_contribution_cents"], 125000, "reserve_contribution_cents")
    assert_cents(budget["base_expense_cents"], 11900000, "base_expense_cents")
    assert budget["management_fee_bp"] == 800
    assert_cents(budget["management_fee_cents"], 952000, "management_fee_cents")
    assert_cents(budget["total_annual_expense_cents"], 12852000, "total_annual_expense_cents")
    assert_cents(budget["assessment_income_cents"], 12852000, "assessment_income_cents")
    assert_cents(budget["developer_deficit_funding_cents"], 0, "deficit funding")
    assert budget["developer_subsidy_flag"] is False

    def unit_cents(unit_id):
        row = validate_success(api.get_unit(unit_id, sponsor_headers()))
        return row["unit_annual_assessment_cents"], row["unit_monthly_assessment_cents"]

    assert unit_cents(u1["id"]) == (4283572, 356964)
    assert unit_cents(u2["id"])[0] == 4283572
    assert unit_cents(u3["id"]) == (4284856, 357071)

    retiered = validate_success(
        api.patch_budget(
            budget["id"], {"annual_operating_expense_cents": 11875000}, sponsor_headers()
        )
    )
    assert_cents(retiered["base_expense_cents"], 12000000, "patched base_expense_cents")
    assert retiered["management_fee_bp"] == 650
    assert_cents(retiered["management_fee_cents"], 780000, "patched management_fee_cents")
    assert_cents(retiered["total_annual_expense_cents"], 12780000, "patched total")
    assert_cents(retiered["assessment_income_cents"], 12780000, "patched income")
    assert retiered["status"] == "DRAFT"

    assert unit_cents(u1["id"]) == (4259574, 354965)
    assert unit_cents(u3["id"]) == (4260852, 355071)
