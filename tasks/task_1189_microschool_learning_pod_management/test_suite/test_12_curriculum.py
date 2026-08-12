"""Curriculum-plan approval claims (PRD 3.2)."""
from test_helpers import (
    ApiErrorId,
    create_curriculum_plan_payload,
    create_pod_payload,
    create_safety_policy_payload,
    get_success_data,
    validate_error,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import create_site, set_clock

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["pod_operator_headers"]


class TestCurriculumAdequacy:
    def test_err_curriculum_inadequate_triggerable(self, api):
        """PRD 3.2: "Plan approval is reserved for a `PlatformAdmin` and
        enforces two checks, rejected jointly as `ERR_CURRICULUM_INADEQUATE`
        (HTTP 422): the pod must hold at least one `APPROVED` safety policy,
        and the plan must clear the 1200-minute weekly floor while covering
        every grade band present among enrolled seats."

        Design: Corner/errors/err_curriculum_inadequate_triggerable
        """
        set_clock("2026-06-01T00:00:00Z")
        site = create_site()
        pod = validate_success(
            api.create_pod(create_pod_payload(site["id"]), OPERATOR),
            expected_status=201,
        )
        # Approved safety policy present, so only the minutes floor can fail.
        policy = get_success_data(api.create_safety_policy(
            pod["id"], create_safety_policy_payload(), OPERATOR
        ))
        get_success_data(api.approve_safety_policy(pod["id"], policy["id"], ADMIN))
        plan = get_success_data(api.create_curriculum_plan(
            pod["id"],
            create_curriculum_plan_payload(
                plan_name="Short Plan",
                total_instructional_minutes_per_week=1100,
            ),
            OPERATOR,
        ))
        plan = get_success_data(
            api.submit_curriculum_plan(pod["id"], plan["id"], OPERATOR)
        )
        assert plan["plan_status"] == "SUBMITTED"
        resp = api.approve_curriculum_plan(pod["id"], plan["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CURRICULUM_INADEQUATE,
                       expected_status=422)
