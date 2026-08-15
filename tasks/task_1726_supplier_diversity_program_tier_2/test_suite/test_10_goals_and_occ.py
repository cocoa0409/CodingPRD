"""Program goals: publish segregation of duties, and optimistic concurrency
on goal creation against the business unit's version."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_business_unit,
    create_draft_goal,
    create_goal_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN1 = TEST_USERS["admin_1_headers"]


class TestGoalPublishSoD:
    def test_goal_publish_by_creator_returns_sod_violation(self, api):
        """PRD §3.6: "Publishing moves a `DRAFT` goal to `PUBLISHED`.
        Segregation of duties requires the publisher's `X-User-ID` to differ
        from `created_by_user_id`; a match is `ERR_SOD_VIOLATION`."

        Design: Corner/validations/goal_publish_by_creator_returns_sod_violation
        """
        bu = create_business_unit()
        goal = create_draft_goal(bu, target_value=25.00, headers=ADMIN1)
        assert goal["created_by_user_id"] == "admin-1"
        resp = api.publish_goal(goal["id"], ADMIN1)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        goals, _meta = validate_paginated(api.list_goals(bu["id"], ADMIN1))
        assert goals[0]["status"] == "DRAFT", (
            "The SoD-rejected publish leaves the goal DRAFT"
        )


class TestGoalOptimisticConcurrency:
    def test_goal_create_stale_bu_version_returns_412(self, api):
        """PRD §2.7: "The request must carry `expected_business_unit_version`
        holding the `version` of the parent `BusinessUnit` as the client last
        observed it. If the business unit's current `version` does not match
        `expected_business_unit_version` — for example because another writer
        has since created a goal for the same `(cert_category, fiscal_year)`
        key, which legitimately supersedes the prior DRAFT under the
        goal-supersession rule of §3.6 — the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on
        a stale view of the business unit."
        PRD §3.6: "Goal creation also supersedes: any existing `DRAFT` goal
        for the same `(business_unit_id, cert_category, fiscal_year)`
        automatically becomes `SUPERSEDED`."

        Design: Corner/cross_cutting_complexity_layers/goal_create_stale_bu_version_returns_412
        """
        bu = create_business_unit()
        assert bu["version"] == 1
        # First create against the observed version succeeds (BU version
        # advances to 2 because goal creation mutates the business unit).
        goal1 = create_draft_goal(bu, target_value=25.00, headers=ADMIN1)
        assert goal1["status"] == "DRAFT"
        # Replaying the stale observed version is rejected.
        resp = api.create_goal(
            bu["id"],
            create_goal_payload(1, target_value=30.00),
            ADMIN1)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        # Re-reading yields the fresh version; the retry succeeds and
        # supersedes the prior DRAFT with the same key.
        fresh = validate_success(api.get_business_unit(bu["id"], ADMIN1))
        assert fresh["version"] == 2
        goal2 = validate_success(
            api.create_goal(
                bu["id"],
                create_goal_payload(fresh["version"], target_value=30.00),
                ADMIN1),
            201)
        assert goal2["status"] == "DRAFT"
        goals, _meta = validate_paginated(api.list_goals(bu["id"], ADMIN1))
        by_id = {g["id"]: g for g in goals}
        assert by_id[goal1["id"]]["status"] == "SUPERSEDED", (
            "The successful retry superseded the prior DRAFT"
        )
        assert by_id[goal2["id"]]["status"] == "DRAFT"
