"""Defect creation: required body fields, environment validation, quota
enforcement, and initial state of the new defect.
"""
from __future__ import annotations

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_defect,
    create_defect_payload,
    create_defect,
    default_environment,
    effective_response_sla,
    effective_resolution_sla,
    fetch_module,
    severity_priority_score,
    setup_basic_module,
    setup_module_at_quota_boundary,
    setup_team,
)


class TestDefectInitialState:
    def test_new_defect_born_with_expected_initial_fields(self):
        """PRD §3.2: "On a successful report the new defect is born with
        status NEW, sla_state RUNNING, escalation_level 0, reopen_count 0,
        and total_paused_minutes 0".
        """
        team, module = setup_basic_module()
        defect = create_defect(
            team, module, severity="MAJOR", business_impact="INTERNAL",
        )
        assert_defect(defect)
        assert defect["status"] == "NEW"
        assert defect["sla_state"] == "RUNNING"
        assert defect["escalation_level"] == 0
        assert defect["reopen_count"] == 0
        assert defect["total_paused_minutes"] == 0
        assert defect.get("assignee_id") in (None, "")
        # PRD §3.2: "report_clock_minute" snapshots project clock.
        assert defect["report_clock_minute"] == 0

    def test_new_defect_effective_severity_equals_reported_severity(self):
        """PRD §3.2: "effective_severity is initialised to the reported
        severity".
        """
        team, module = setup_basic_module()
        defect = create_defect(team, module, severity="MAJOR")
        assert defect["effective_severity"] == "MAJOR"

    def test_new_defect_priority_score_and_response_due_minute(self):
        """PRD §3.2: "The initial priority_score is computed, the
        response_due_minute and resolution_due_minute are computed".
        PRD §3.4: priority_score = severity_weight + impact_weight +
        age_factor + reopen_bonus. response_due_minute =
        report_clock_minute + ceil(base * multiplier).
        """
        team, module = setup_basic_module()
        defect = create_defect(
            team, module,
            severity="CRITICAL", business_impact="REVENUE_BLOCKING",
        )
        expected_score = severity_priority_score(
            "CRITICAL", "REVENUE_BLOCKING",
            age_minutes=0, reopen_count=0,
        )
        assert defect["priority_score"] == expected_score == 120
        # CRITICAL response base = 60; multiplier 1.0 at score 120
        # (>= 80, < 150) -> 60 minutes.
        expected_response_due = effective_response_sla("CRITICAL", 120)
        assert defect["response_due_minute"] == 0 + expected_response_due
        expected_resolution_due = effective_resolution_sla("CRITICAL", 120)
        assert defect["resolution_due_minute"] == 0 + expected_resolution_due

    def test_new_defect_decrements_module_quota(self):
        """PRD §3.2: "The module's active_defect_count increments by 1
        and quota_remaining decrements by 1."
        """
        team, module = setup_basic_module(initial_defect_quota=5)
        create_defect(team, module)
        m_after = fetch_module(team, module["id"])
        assert m_after["active_defect_count"] == 1
        assert m_after["quota_remaining"] == 4


class TestDefectEnvironmentValidation:
    @pytest.mark.parametrize("missing_key", [
        "os", "browser", "app_version", "build_id",
    ])
    def test_missing_environment_subkey_rejected(self, missing_key):
        """PRD §3.2: "an environment object that must contain all four
        sub-keys os, browser, app_version, and build_id, each non-empty
        — an environment payload missing or empty in any of these four
        fields is rejected with ERR_INVALID_ENVIRONMENT."
        """
        team, module = setup_basic_module()
        env = default_environment()
        env.pop(missing_key)
        payload = create_defect_payload(
            project_id=team.project["id"],
            module_id=module["id"],
            reporter_id=team.developer["id"],
            environment=env,
        )
        resp = api_client.create_defect(payload, team.developer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_ENVIRONMENT.value)

    @pytest.mark.parametrize("empty_key", [
        "os", "browser", "app_version", "build_id",
    ])
    def test_empty_environment_subkey_rejected(self, empty_key):
        """PRD §3.2: "an environment object that must contain all four
        sub-keys os, browser, app_version, and build_id, each non-empty
        — an environment payload missing or empty in any of these four
        fields is rejected with ERR_INVALID_ENVIRONMENT."
        """
        team, module = setup_basic_module()
        env = default_environment()
        env[empty_key] = ""
        payload = create_defect_payload(
            project_id=team.project["id"],
            module_id=module["id"],
            reporter_id=team.developer["id"],
            environment=env,
        )
        resp = api_client.create_defect(payload, team.developer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_ENVIRONMENT.value)


class TestDefectReferentialChecks:
    def test_unknown_module_id_rejected(self):
        """PRD §3.2: "Both the module_id and the reporter_id must resolve
        to ACTIVE rows in the same project as the request's project_id;
        if either reference is dangling, points at an INACTIVE row, or
        crosses a project boundary, the report is rejected with
        ERR_MODULE_OR_REPORTER_INVALID."
        """
        team = setup_team()
        payload = create_defect_payload(
            project_id=team.project["id"],
            module_id=NON_EXISTENT_UUID,
            reporter_id=team.developer["id"],
        )
        resp = api_client.create_defect(payload, team.developer_headers)
        validate_error(
            resp, ApiErrorId.ERR_MODULE_OR_REPORTER_INVALID.value,
        )

    def test_unknown_reporter_id_rejected(self):
        """PRD §3.2: "Both the module_id and the reporter_id must resolve
        to ACTIVE rows in the same project as the request's project_id;
        if either reference is dangling, points at an INACTIVE row, or
        crosses a project boundary, the report is rejected with
        ERR_MODULE_OR_REPORTER_INVALID."
        """
        team, module = setup_basic_module()
        payload = create_defect_payload(
            project_id=team.project["id"],
            module_id=module["id"],
            reporter_id=NON_EXISTENT_UUID,
        )
        resp = api_client.create_defect(payload, team.developer_headers)
        validate_error(
            resp, ApiErrorId.ERR_MODULE_OR_REPORTER_INVALID.value,
        )

    def test_reporter_from_different_project_rejected(self):
        """PRD §3.2: "Both the module_id and the reporter_id must resolve
        to ACTIVE rows in the same project as the request's project_id;
        if either reference is dangling, points at an INACTIVE row, or
        crosses a project boundary, the report is rejected with
        ERR_MODULE_OR_REPORTER_INVALID."
        """
        team_a, module_a = setup_basic_module()
        team_b = setup_team()  # Different project; team_b.developer is in
        # project B, not project A.
        payload = create_defect_payload(
            project_id=team_a.project["id"],
            module_id=module_a["id"],
            reporter_id=team_b.developer["id"],
        )
        resp = api_client.create_defect(payload, team_a.developer_headers)
        validate_error(
            resp, ApiErrorId.ERR_MODULE_OR_REPORTER_INVALID.value,
        )


class TestDefectModuleQuota:
    def test_quota_exceeded_when_module_is_full(self):
        """PRD §3.2: "The target module must additionally have
        quota_remaining strictly greater than zero — equivalently,
        active_defect_count strictly less than initial_defect_quota — or
        the eleventh simultaneous report against a ten-quota module is
        refused with ERR_MODULE_QUOTA_EXCEEDED."
        """
        team, module, _ = setup_module_at_quota_boundary(
            initial_defect_quota=2,
        )
        # quota_remaining is now 0; the next defect must be refused.
        payload = create_defect_payload(
            project_id=team.project["id"],
            module_id=module["id"],
            reporter_id=team.developer["id"],
        )
        resp = api_client.create_defect(payload, team.developer_headers)
        validate_error(resp, ApiErrorId.ERR_MODULE_QUOTA_EXCEEDED.value)


class TestDefectRBAC:
    def test_release_manager_cannot_create_defect(self):
        """PRD §4 lists POST /defects as authorized for
        Developer, QAEngineer, TriageManager (not ReleaseManager).
        PRD §2.1: "If the headers are well-formed but the role declared
        does not have permission for the requested operation, the
        response is ERR_INSUFFICIENT_PERMISSIONS."
        """
        team, module = setup_basic_module()
        payload = create_defect_payload(
            project_id=team.project["id"],
            module_id=module["id"],
            reporter_id=team.developer["id"],
        )
        resp = api_client.create_defect(payload, team.release_headers)
        validate_error(
            resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
        )
