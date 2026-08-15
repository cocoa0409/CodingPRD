"""Projects and safety plans: creation defaults, revision numbering, not-found
handling, and the plan-activation optimistic concurrency rule (PRD §3.1, §2.11)."""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, api_client,
    validate_error, validate_success,
    assert_project, assert_safety_plan,
    create_project, create_plan, activate_plan, get_project,
    create_project_payload, create_safety_plan_payload,
    make_safety_manager_headers,
)

SM = make_safety_manager_headers()


class TestProjectCreation:

    def test_project_create_applies_system_defaults(self, api):
        """PRD §3.1: "A new project starts with `safety_posture` of `NORMAL`,
        `issued_permit_count` of 0, `open_deficiency_count` of 0, and
        `current_active_plan_id` null until the first plan activation."

        Design: Corner/entities/project_create_defaults_applied
        """
        payload = create_project_payload(
            name="U District Station", location="Seattle", annual_hours_worked=60000
        )
        resp = api.create_project(payload, SM)
        data = validate_success(resp, 201)
        assert_project(data)
        assert data["safety_posture"] == "NORMAL", (
            f"new project must start NORMAL, got {data['safety_posture']}"
        )
        assert data["issued_permit_count"] == 0
        assert data["open_deficiency_count"] == 0
        assert data["current_active_plan_id"] is None

    def test_get_project_not_found_returns_404(self, api):
        """PRD §2.10: "the first identifier that does not resolve yields that
        resource's not-found error: `ERR_PROJECT_NOT_FOUND`" with HTTP 404.

        Design: Corner/entities/entity_get_not_found_returns_404
        """
        create_project(name="Existing", location="Seattle", annual_hours_worked=10000)
        resp = api.get_project(NON_EXISTENT_UUID, SM)
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_FOUND)


class TestSafetyPlanRevisions:

    def test_safety_plan_revision_numbers_increment(self, api):
        """PRD §3.1: "the server assigns its `revision_no` as one more than the
        count of pre-existing plans for the same project at creation time, so the
        first plan of a project is revision 1."
        PRD §3.1: "Every plan begins life in `DRAFT` status with `activated_at` null"

        Design: Corner/entities/safety_plan_revision_no_increments
        """
        project = create_project(name="Ridge", location="Kent", annual_hours_worked=20000)
        plan1 = create_plan(project["id"], effective_date="2026-08-01")
        plan2 = create_plan(project["id"], effective_date="2026-09-01",
                            revision_notes="rev2")
        assert_safety_plan(plan1)
        assert plan1["revision_no"] == 1, (
            f"first plan must be revision 1, got {plan1['revision_no']}"
        )
        assert plan1["status"] == "DRAFT"
        assert plan1["activated_at"] is None
        assert plan2["revision_no"] == 2, (
            f"second plan must be revision 2, got {plan2['revision_no']}"
        )
        assert plan2["status"] == "DRAFT"


class TestPlanActivationOcc:

    def test_second_activation_with_stale_version_rejected(self, api):
        """PRD §2.11: "activating a safety plan requires the request to carry
        `expected_project_version`, holding the value of the parent project's
        `version` that the client last observed. If the project's current `version`
        has advanced beyond that observed value — for example because another plan
        was activated against the same project in the meantime, which is a
        legitimate supersede under the plan lifecycle — the activation is rejected
        as stale with `ERR_STALE_VERSION` (HTTP 412)"
        PRD §3.1: "any other plan of the same project that was `ACTIVE` automatically
        transitions to `SUPERSEDED` — a terminal state — as part of the same
        activation."
        PRD §3.1: "A successful activation increments the project's `version` by 1."

        Design: Corner/cross_cutting_layers/occ_stale_project_version_on_second_activation
        """
        project = create_project(name="Capitol Hill", location="Seattle",
                                 annual_hours_worked=80000)
        observed_version = project["version"]
        plan_a = create_plan(project["id"], effective_date="2026-08-01")
        plan_b = create_plan(project["id"], effective_date="2026-09-01")

        # Plan A activates against the observed version.
        resp_a = api.activate_safety_plan(
            plan_a["id"], {"expected_project_version": observed_version}, SM
        )
        data_a = validate_success(resp_a, 200)
        assert data_a["status"] == "ACTIVE"

        # Plan B with the same (now stale) observed version is rejected 412.
        resp_b_stale = api.activate_safety_plan(
            plan_b["id"], {"expected_project_version": observed_version}, SM
        )
        validate_error(resp_b_stale, ApiErrorId.ERR_STALE_VERSION)

        # The stale rejection changed nothing: A is still the governing plan and
        # the project version advanced exactly once.
        project_after = get_project(project["id"])
        assert project_after["version"] == observed_version + 1, (
            f"one activation increments version by 1: {observed_version} -> "
            f"{project_after['version']}"
        )
        assert project_after["current_active_plan_id"] == plan_a["id"]

        # Re-reading and retrying with the fresh version succeeds and supersedes A.
        data_b = activate_plan(plan_b["id"], project_after["version"])
        assert data_b["status"] == "ACTIVE"
        plan_a_after = validate_success(api.get_safety_plan(plan_a["id"], SM))
        assert plan_a_after["status"] == "SUPERSEDED"
