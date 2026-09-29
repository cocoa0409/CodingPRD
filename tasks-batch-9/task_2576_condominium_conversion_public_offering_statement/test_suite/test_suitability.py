"""Suitability assessments: the verified-component population, the life-safety
critical cap, the two scoring variants and the report version token they consume.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import as_decimal, assert_decimal_equals, assert_page
from test_helpers.factories import assessment_payload, component_payload
from test_helpers.fixtures import (
    accept_report,
    make_assessment,
    make_component,
    make_project,
    make_report,
    report_version,
    submit_report,
)
from test_helpers.test_users import engineer_headers, peer_headers, sponsor_headers

STD_PROJECT = ("44 Cove Lane, Bangor ME", 1968, 2)


def test_suitability_population_excludes_unverified_components_and_falls_back_to_zero(api):
    """PRD: The population is the report's `VERIFIED` child components only; when the
    population is empty the score is 0.00 with `basis` `NO_VERIFIED_COMPONENTS`.

    Design: Corner/calculations/suitability_population_excludes_unverified_components_and_falls_back_to_zero
    """
    project = make_project(api, *STD_PROJECT)
    report = make_report(api, project["id"])
    roof = make_component(
        api, report["id"], component_payload("ROOF", 30, 10, 10000000, 0, "EXCELLENT")
    )
    hvac = make_component(
        api, report["id"], component_payload("HVAC", 1, 24, 90000000, 0, "POOR")
    )
    submit_report(api, report["id"])
    validate_success(api.verify_component(hvac["id"], False, peer_headers()))

    before = validate_success(api.get_report(report["id"], engineer_headers()))
    assert before["verified_component_count"] == 1
    assert before["total_replacement_cost_cents"] == 10000000

    first = make_assessment(api, report["id"])
    assert first["basis"] == "VERIFIED_COMPONENTS"
    assert_decimal_equals(first["score"], "100.00", "score")
    assert first["verdict"] == "PASSED"
    assert first["critical_cap_applied"] is False
    assert validate_success(api.get_project(project["id"], sponsor_headers()))[
        "suitability_gate"
    ] == "PASSED"

    validate_success(api.verify_component(roof["id"], False, peer_headers()))
    second = make_assessment(api, report["id"])
    assert second["basis"] == "NO_VERIFIED_COMPONENTS"
    assert_decimal_equals(second["score"], "0.00", "score")
    assert second["verdict"] == "FAILED"
    assert second["critical_cap_applied"] is False
    assert validate_success(api.get_assessment(first["id"], peer_headers()))[
        "status"
    ] == "SUPERSEDED"

    after = validate_success(api.get_report(report["id"], engineer_headers()))
    assert after["verified_component_count"] == 0
    project_after = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert project_after["suitability_gate"] == "FAILED"
    assert_decimal_equals(
        project_after["suitability_score"], "0.00", "suitability_score"
    )


def test_life_safety_critical_cap_binds_below_five_years_only(api):
    """PRD: If any `VERIFIED` component with `is_life_safety` true has a
    `remaining_useful_life_years` strictly below 5, the score is capped at 40.00 and
    `critical_cap_applied` is true.

    Design: Corner/calculations/life_safety_critical_cap_binds_below_five_years_only
    """
    project_a = make_project(api, "44 Cove Lane, Bangor ME", 1968, 2)
    report_a = make_report(api, project_a["id"], "ER-A", "2026-07-10T00:00:00Z")
    roof_a = make_component(
        api, report_a["id"], component_payload("ROOF", 30, 10, 9000000, 0, "EXCELLENT")
    )
    elevator_a = make_component(
        api,
        report_a["id"],
        component_payload("ELEVATOR", 4, 26, 1000000, 0, "GOOD", is_life_safety=True),
    )
    submit_report(api, report_a["id"])
    validate_success(api.verify_component(roof_a["id"], True, peer_headers()))
    validate_success(api.verify_component(elevator_a["id"], True, peer_headers()))

    project_b = make_project(api, "46 Cove Lane, Bangor ME", 1968, 2)
    report_b = make_report(api, project_b["id"], "ER-B", "2026-07-10T00:00:00Z")
    roof_b = make_component(
        api, report_b["id"], component_payload("ROOF", 30, 10, 9000000, 0, "EXCELLENT")
    )
    elevator_b = make_component(
        api,
        report_b["id"],
        component_payload("ELEVATOR", 5, 25, 1000000, 0, "GOOD", is_life_safety=True),
    )
    submit_report(api, report_b["id"])
    validate_success(api.verify_component(roof_b["id"], True, peer_headers()))
    validate_success(api.verify_component(elevator_b["id"], True, peer_headers()))

    capped = make_assessment(api, report_a["id"])
    assert_decimal_equals(capped["score"], "40.00", "score")
    assert capped["critical_cap_applied"] is True
    assert capped["verdict"] == "FAILED"
    assert capped["basis"] == "VERIFIED_COMPONENTS"

    uncapped = make_assessment(api, report_b["id"])
    assert_decimal_equals(uncapped["score"], "91.17", "score")
    assert uncapped["critical_cap_applied"] is False
    assert uncapped["verdict"] == "PASSED"


def test_assessment_success_invalidates_the_very_version_token_it_consumed(api):
    """PRD: The assessment write carries `expected_engineering_report_version`; a
    mismatch fails with `ERR_STALE_REPORT_VERSION`, HTTP 412.

    Design: Corner/cross_cutting_complexity_layers/assessment_success_invalidates_the_very_version_token_it_consumed
    """
    project = make_project(api, *STD_PROJECT)
    report = make_report(api, project["id"])
    component = make_component(
        api, report["id"], component_payload("ROOF", 30, 10, 10000000, 0, "EXCELLENT")
    )
    submit_report(api, report["id"])
    validate_success(api.verify_component(component["id"], True, peer_headers()))
    token = report_version(api, report["id"])
    assert validate_success(api.get_project(project["id"], sponsor_headers()))[
        "suitability_gate"
    ] == "UNEVALUATED"

    validate_error(
        api.create_assessment(
            report["id"],
            assessment_payload("AS_INSPECTED", token - 1),
            peer_headers(),
        ),
        "ERR_STALE_REPORT_VERSION",
        expected_status=412,
    )
    _, meta = validate_paginated(
        api.list_report_assessments(report["id"], peer_headers())
    )
    assert_page(meta, total_count=0)

    assessment = validate_success(
        api.create_assessment(
            report["id"], assessment_payload("AS_INSPECTED", token), peer_headers()
        ),
        expected_status=201,
    )
    assert_decimal_equals(assessment["score"], "100.00", "score")
    assert assessment["verdict"] == "PASSED"
    assert assessment["status"] == "EFFECTIVE"
    assert validate_success(api.get_project(project["id"], sponsor_headers()))[
        "suitability_gate"
    ] == "PASSED"

    validate_error(
        api.create_assessment(
            report["id"], assessment_payload("AS_INSPECTED", token), peer_headers()
        ),
        "ERR_STALE_REPORT_VERSION",
        expected_status=412,
    )
    assert validate_success(api.get_assessment(assessment["id"], peer_headers()))[
        "status"
    ] == "EFFECTIVE"
    _, meta = validate_paginated(
        api.list_report_assessments(report["id"], peer_headers())
    )
    assert_page(meta, total_count=1)
    assert_decimal_equals(
        validate_success(api.get_project(project["id"], sponsor_headers()))[
            "suitability_score"
        ],
        "100.00",
        "suitability_score",
    )


def test_suitability_score_as_inspected_vs_post_remediation(api):
    """PRD: The `AS_INSPECTED` variant scores the components as found, while the
    `POST_REMEDIATION` variant adds each component's
    `planned_remediation_gain_years` to its remaining useful life first.

    Design: Difficulty/dual_variant_calc/suitability_score_as_inspected_vs_post_remediation
    """
    project = make_project(api, "18 Harbor Row, Portland ME", 1972, 3)
    report = make_report(api, project["id"], "ER-A", "2026-07-15T00:00:00Z")
    roof = make_component(
        api,
        report["id"],
        component_payload(
            "ROOF",
            20,
            10,
            4000000,
            0,
            "GOOD",
            planned_remediation_gain_years=10,
            is_life_safety=False,
            is_structural=False,
        ),
    )
    elevator = make_component(
        api,
        report["id"],
        component_payload(
            "ELEVATOR",
            8,
            22,
            6000000,
            2000,
            "FAIR",
            planned_remediation_gain_years=12,
            is_life_safety=True,
            is_structural=False,
        ),
    )
    foundation = make_component(
        api,
        report["id"],
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
        ),
    )
    submit_report(api, report["id"])
    for row in (roof, elevator, foundation):
        validate_success(api.verify_component(row["id"], True, peer_headers()))
    accept_report(api, report["id"])

    as_inspected = validate_success(
        api.create_assessment(
            report["id"],
            assessment_payload("AS_INSPECTED", report_version(api, report["id"])),
            sponsor_headers(),
        ),
        expected_status=201,
    )
    assert as_inspected["variant"] == "AS_INSPECTED"
    assert_decimal_equals(as_inspected["score"], "65.83", "score")
    assert as_inspected["basis"] == "VERIFIED_COMPONENTS"
    assert as_inspected["critical_cap_applied"] is False
    assert as_inspected["verdict"] == "PASSED"

    post_remediation = validate_success(
        api.create_assessment(
            report["id"],
            assessment_payload("POST_REMEDIATION", report_version(api, report["id"])),
            sponsor_headers(),
        ),
        expected_status=201,
    )
    assert post_remediation["variant"] == "POST_REMEDIATION"
    assert_decimal_equals(post_remediation["score"], "87.50", "score")
    assert post_remediation["verdict"] == "PASSED"

    assert validate_success(api.get_assessment(as_inspected["id"], peer_headers()))[
        "status"
    ] == "EFFECTIVE"
    assert as_decimal(post_remediation["score"]) - as_decimal(
        as_inspected["score"]
    ) == as_decimal("21.67")

    final = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert_decimal_equals(final["suitability_score"], "87.50", "suitability_score")
    assert final["suitability_gate"] == "PASSED"
    assert final["status"] == "DOCUMENTS_PREPARATION"
    reread = validate_success(api.get_report(report["id"], engineer_headers()))
    assert reread["verified_component_count"] == 3
    assert reread["total_replacement_cost_cents"] == 20000000
