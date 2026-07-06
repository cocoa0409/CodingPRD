"""Anonymized utilization reporting: k-anonymity suppression, windowing."""
import pytest
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
)
import test_helpers.fixtures as fx

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["care_coordinator_headers"]


def test_report_cell_suppression_below_k_cohort(api):
    """PRD §3.9: "Otherwise `suppressed` is false, and the report builds
    `issue_breakdown` as a map from each `presenting_issue` value to its case
    count within the window — but each cell is itself checked against the floor:
    if the number of distinct employees behind a given issue cell is below
    `reporting_min_cohort`, that cell is replaced by the -1 sentinel while the
    cells that pass the floor show their true counts."

    Design: Corner/calculations/report_cell_suppression_below_k_cohort
    """
    contract = fx.create_contract(annual_session_cap=50, reporting_min_cohort=2)
    plan = fx.create_published_plan(contract["id"])
    fx.set_clock("2026-03-05T00:00:00Z")
    e1 = fx.create_employee(contract["id"], plan["id"], full_name="K1", external_ref="K1")
    e2 = fx.create_employee(contract["id"], plan["id"], full_name="K2", external_ref="K2")
    e3 = fx.create_employee(contract["id"], plan["id"], full_name="K3", external_ref="K3")
    fx.create_case(contract["id"], e1["id"], presenting_issue="STRESS")
    fx.create_case(contract["id"], e2["id"], presenting_issue="STRESS")
    fx.create_case(contract["id"], e3["id"], presenting_issue="GRIEF")
    report = validate_success(api.create_report(
        contract["id"],
        {"period_start": "2026-03-01T00:00:00Z", "period_end": "2026-03-31T00:00:00Z"},
        ADMIN), 201)
    assert report["suppressed"] is False
    assert report["distinct_employees"] == 3
    assert report["total_cases"] == 3
    assert report["issue_breakdown"]["STRESS"] == 2
    assert report["issue_breakdown"]["GRIEF"] == -1


def test_report_whole_suppressed_below_k(api):
    """PRD §3.9: "If the window's `distinct_employees` is below
    `reporting_min_cohort`, the whole report is suppressed: `suppressed` is true
    and the `issue_breakdown` is rendered with every cell set to the sentinel
    value of -1."

    Design: Corner/calculations/report_whole_suppressed_below_k
    """
    contract = fx.create_contract(annual_session_cap=50, reporting_min_cohort=5)
    plan = fx.create_published_plan(contract["id"])
    fx.set_clock("2026-03-05T00:00:00Z")
    e1 = fx.create_employee(contract["id"], plan["id"], full_name="S1", external_ref="S1")
    fx.create_case(contract["id"], e1["id"], presenting_issue="STRESS")
    report = validate_success(api.create_report(
        contract["id"],
        {"period_start": "2026-03-01T00:00:00Z", "period_end": "2026-03-31T00:00:00Z"},
        ADMIN), 201)
    assert report["suppressed"] is True
    assert report["distinct_employees"] == 1


def test_report_invalid_window_rejected(api):
    """PRD §3.9: "The window is half-open and must be non-empty: `period_start`
    must be strictly earlier than `period_end`, or the build is rejected with
    `ERR_INVALID_WINDOW`."

    Design: Corner/validations/report_invalid_window_rejected
    """
    contract = fx.create_contract(employer_name="WinCo")
    validate_error(api.create_report(
        contract["id"],
        {"period_start": "2026-06-01T00:00:00Z", "period_end": "2026-05-01T00:00:00Z"},
        ADMIN),
        ApiErrorId.ERR_INVALID_WINDOW.value)


def test_utilization_report_is_immutable_no_version_field(api):
    """PRD §2.4: "The `UtilizationReport` resource is the sole exception: a
    utilization report carries only an `id` and a `created_at`. It has neither an
    `updated_at` nor a `version`, because a report is an immutable snapshot of a
    window and is never mutated after it is built."

    Design: Corner/entities/utilization_report_is_immutable_no_version_field
    """
    contract = fx.create_contract(employer_name="RepCo", reporting_min_cohort=1)
    report = validate_success(api.create_report(
        contract["id"],
        {"period_start": "2026-01-01T00:00:00Z", "period_end": "2026-12-31T00:00:00Z"},
        ADMIN), 201)
    fetched = validate_success(api.get_report(report["id"], ADMIN))
    assert "version" not in fetched, "UtilizationReport must not expose a version field"
