"""Project, Module, and TeamMember CRUD plus their archive lifecycles."""
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
    assert_module,
    assert_project,
    assert_team_member,
    create_module_payload,
    create_project_payload,
    create_team_member_payload,
    fetch_defect,
    fetch_module,
    fetch_project,
    make_triage_manager_headers,
    setup_basic_module,
    setup_defect_in_state,
    setup_team,
)


class TestProjectCreation:
    def test_create_project_returns_active_with_clock_zero(self):
        """PRD §3.1: "The new row is born ACTIVE with clock_minute set to 0".
        """
        headers = make_triage_manager_headers("bootstrap-triage")
        resp = api_client.create_project(create_project_payload(), headers)
        data = validate_success(resp, expected_status=201)
        assert_project(data)
        assert data["status"] == "ACTIVE"
        assert data["clock_minute"] == 0

    def test_get_project_not_found_returns_err_project_not_found(self):
        """PRD §2.9: "the project is resolved first; if it does not exist
        the response is ERR_PROJECT_NOT_FOUND".
        """
        headers = make_triage_manager_headers("bootstrap-triage")
        resp = api_client.get_project(NON_EXISTENT_UUID, headers)
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_FOUND.value)


class TestModuleCreation:
    def test_create_module_initialises_quota_fields(self):
        """PRD §3.1: "On a successful create, active_defect_count is
        initialised to 0 and quota_remaining is initialised to the
        initial_defect_quota itself".
        """
        team = setup_team()
        payload = create_module_payload(
            owner_team_member_id=team.developer["id"],
            kloc=2.0, initial_defect_quota=5,
        )
        resp = api_client.create_module(
            team.project["id"], payload, team.triage_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_module(data)
        assert data["active_defect_count"] == 0
        assert data["quota_remaining"] == 5
        assert data["initial_defect_quota"] == 5
        assert data["status"] == "ACTIVE"

    def test_create_module_with_zero_kloc_rejected(self):
        """PRD §3.1: "The kloc value must be strictly greater than zero —
        a non-positive kloc is rejected with ERR_INVALID_MODULE_KLOC".
        """
        team = setup_team()
        payload = create_module_payload(
            owner_team_member_id=team.developer["id"],
            kloc=0, initial_defect_quota=5,
        )
        resp = api_client.create_module(
            team.project["id"], payload, team.triage_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_MODULE_KLOC.value)

    def test_create_module_with_negative_kloc_rejected(self):
        """PRD §3.1: "The kloc value must be strictly greater than zero —
        a non-positive kloc is rejected with ERR_INVALID_MODULE_KLOC".
        """
        team = setup_team()
        payload = create_module_payload(
            owner_team_member_id=team.developer["id"],
            kloc=-1.0, initial_defect_quota=5,
        )
        resp = api_client.create_module(
            team.project["id"], payload, team.triage_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_MODULE_KLOC.value)

    def test_get_module_with_missing_project_fails_first(self):
        """PRD §2.9: "the project is resolved first; if it does not exist
        the response is ERR_PROJECT_NOT_FOUND and the module is never
        queried."
        """
        headers = make_triage_manager_headers("bootstrap-triage")
        resp = api_client.get_module(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID, headers,
        )
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_FOUND.value)

    def test_get_module_with_real_project_and_missing_module(self):
        """PRD §2.9: "Only after the project resolves does the module
        lookup happen, producing ERR_MODULE_NOT_FOUND if the module is
        missing."
        """
        team = setup_team()
        resp = api_client.get_module(
            team.project["id"], NON_EXISTENT_UUID, team.triage_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MODULE_NOT_FOUND.value)


class TestTeamMemberCreation:
    def test_create_team_member_is_active_with_zero_workload(self):
        """PRD §3.1: "New members are born with status ACTIVE and
        active_workload 0".
        """
        team = setup_team()
        resp = api_client.create_team_member(
            team.project["id"],
            create_team_member_payload(role="DEVELOPER"),
            team.triage_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_team_member(data)
        assert data["status"] == "ACTIVE"
        assert data["active_workload"] == 0


class TestArchiveCascades:
    def test_archive_module_with_active_defect_rejected(self):
        """PRD §3.1: "A module archive likewise refuses to proceed when
        that module's active_defect_count is greater than zero, returning
        ERR_MODULE_HAS_ACTIVE_DEFECTS".
        """
        team, module = setup_basic_module(initial_defect_quota=3)
        setup_defect_in_state(team, module, "NEW")
        resp = api_client.archive_module(
            team.project["id"], module["id"], team.triage_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_MODULE_HAS_ACTIVE_DEFECTS.value,
        )
        # Module remains ACTIVE.
        m_after = fetch_module(team, module["id"])
        assert m_after["status"] == "ACTIVE"

    def test_archive_module_with_no_active_defects_succeeds(self):
        """PRD §3.1: "A single module can also be individually archived,
        but only when that module's active_defect_count is zero".
        """
        team, module = setup_basic_module()
        resp = api_client.archive_module(
            team.project["id"], module["id"], team.triage_headers,
        )
        data = validate_success(resp)
        assert data["status"] == "ARCHIVED"

    def test_archive_project_with_non_terminal_defect_refused(self):
        """PRD §2.8: "If the project still has any non-terminal Defect
        rows ... the archive is refused entirely; nothing changes."
        """
        team, module = setup_basic_module(initial_defect_quota=3)
        setup_defect_in_state(team, module, "NEW")
        resp = api_client.archive_project(
            team.project["id"], team.triage_headers,
        )
        # The PRD prescribes the cascade is aborted; the specific error_id
        # for the "any non-terminal defect" rejection isn't named in
        # prose, but the parallel section gives ERR_MODULE_HAS_ACTIVE_DEFECTS
        # for the analogous module case. Two readers could reasonably ship
        # different ERR ids here — accept the cascade-abort error class.
        assert resp.status_code in (400, 409)
        # Confirm the project is still ACTIVE.
        proj = fetch_project(team)
        assert proj["status"] == "ACTIVE"
        m_after = fetch_module(team, module["id"])
        assert m_after["status"] == "ACTIVE"

    def test_archive_project_cascades_to_modules(self):
        """PRD §2.8: "When a TriageManager archives a Project, all child
        Module rows transition from ACTIVE to ARCHIVED inside the same
        transaction, the project's own status flips to ARCHIVED".
        """
        team, module = setup_basic_module()
        resp = api_client.archive_project(
            team.project["id"], team.triage_headers,
        )
        validate_success(resp)
        proj = fetch_project(team)
        assert proj["status"] == "ARCHIVED"
        m_after = fetch_module(team, module["id"])
        assert m_after["status"] == "ARCHIVED"
