"""HACCP plan review loop, supersession, CCP constraints, duplicate plans."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures

QA = TEST_USERS["qa_manager_headers"]


class TestPlanRejectResubmitCycle:
    def test_reject_resubmit_cycle_increments_revision(self, api):
        """PRD §3.2: "A rejected plan re-enters the loop: resubmission moves `REJECTED` back to `SUBMITTED`, increments `revision_number` by one, clears `rejection_reason` to null, and refreshes `submitted_at`."
        PRD §3.2: "A new plan starts in `DRAFT` with `revision_number` zero."

        Design: Difficulty/non_linear_state_machine/haccp_plan_reject_resubmit_cycle_and_supersede
        """
        plant = fixtures.create_plant(establishment_number="EST-1645-E1")
        plan = fixtures.create_draft_plan(plant["id"])
        assert plan["revision_number"] == 0
        fixtures.add_ccp(plan["id"])

        submitted = fixtures.submit_plan(plan["id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["revision_number"] == 0

        rejected = validate_success(
            api.reject_haccp_plan(
                plan["id"],
                {"rejection_reason": "Monitoring frequency unspecified for CCP-2"},
                fixtures.make_inspector_headers(fixtures.INSPECTOR_1),
            ),
            200,
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == (
            "Monitoring frequency unspecified for CCP-2"
        )

        resubmitted = fixtures.submit_plan(plan["id"])
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_number"] == 1, (
            "resubmission from REJECTED must increment revision_number by one"
        )
        assert resubmitted.get("rejection_reason") is None, (
            "resubmission clears rejection_reason to null"
        )

    def test_activate_supersedes_previous_effective_plan(self, api):
        """PRD §3.2: "an `APPROVED` plan becomes `EFFECTIVE`, and any previously `EFFECTIVE` plan of the same plant and `process_type` is simultaneously moved to `SUPERSEDED`, so at most one plan per plant and process type is ever effective."

        Design: Difficulty/non_linear_state_machine/haccp_plan_reject_resubmit_cycle_and_supersede
        """
        plant = fixtures.create_plant(establishment_number="EST-1645-E2")
        plan1, _ccp1 = fixtures.create_effective_plan(plant["id"])
        assert plan1["status"] == "EFFECTIVE"

        plan2 = fixtures.create_draft_plan(plant["id"])
        fixtures.add_ccp(plan2["id"], description="Chill cooler v2",
                         monitoring_frequency_minutes=30)
        fixtures.submit_plan(plan2["id"])
        fixtures.approve_plan(plan2["id"])
        plan2 = fixtures.activate_plan(plan2["id"])
        assert plan2["status"] == "EFFECTIVE"

        plan1_after = validate_success(api.get_haccp_plan(plan1["id"], QA), 200)
        assert plan1_after["status"] == "SUPERSEDED", (
            "activating plan2 must supersede the previously EFFECTIVE sibling"
        )


class TestPlanSubmitPreconditions:
    def test_submit_without_ccp_returns_plan_has_no_ccp(self, api):
        """PRD §3.2: "The state check runs first, then the content check: a plan with zero critical control points cannot be submitted and is rejected with `ERR_PLAN_HAS_NO_CCP`."

        Design: Corner/state_machines/plan_submit_without_ccp_returns_plan_has_no_ccp
        """
        plant = fixtures.create_plant(establishment_number="EST-1645-01")
        plan = fixtures.create_draft_plan(plant["id"])

        resp = api.submit_haccp_plan(plan["id"], QA)
        validate_error(resp, ApiErrorId.ERR_PLAN_HAS_NO_CCP)
        assert resp.status_code == 422

        after = validate_success(api.get_haccp_plan(plan["id"], QA), 200)
        assert after["status"] == "DRAFT"

    def test_superseded_plan_submit_returns_plan_invalid_state(self, api):
        """PRD §3.2: "`SUPERSEDED` is terminal."
        PRD §3.2: "Submitting the plan moves it from `DRAFT` to `SUBMITTED` and stamps `submitted_at` from the logical clock."

        Design: Corner/state_machines/superseded_plan_submit_returns_plan_invalid_state
        """
        plant = fixtures.create_plant(establishment_number="EST-1645-02")
        plan1, _ = fixtures.create_effective_plan(plant["id"])
        plan2 = fixtures.create_draft_plan(plant["id"])
        fixtures.add_ccp(plan2["id"], description="Chill cooler v2")
        fixtures.submit_plan(plan2["id"])
        fixtures.approve_plan(plan2["id"])
        fixtures.activate_plan(plan2["id"])

        resp = api.submit_haccp_plan(plan1["id"], QA)
        validate_error(resp, ApiErrorId.ERR_PLAN_INVALID_STATE)
        assert resp.status_code == 409

        after = validate_success(api.get_haccp_plan(plan1["id"], QA), 200)
        assert after["status"] == "SUPERSEDED"


class TestCcpCreationConstraints:
    def test_min_greater_than_max_returns_limit_invalid(self, api):
        """PRD §3.2: "Critical limits are optional per side but not both absent: at least one of `critical_limit_min_f` and `critical_limit_max_f` must be supplied, and when both are present the minimum must be strictly below the maximum; violations surface as `ERR_CCP_LIMIT_INVALID` at the business-constraint stage, after body-schema validation has already run."

        Design: Corner/validations/ccp_min_greater_than_max_returns_limit_invalid
        """
        plant = fixtures.create_plant(establishment_number="EST-1645-25")
        plan = fixtures.create_draft_plan(plant["id"])

        resp = api.create_ccp(
            plan["id"],
            {
                "ccp_code": "CCP-X",
                "hazard_category": "BIOLOGICAL",
                "description": "Inverted limits",
                "critical_limit_min_f": 50.0,
                "critical_limit_max_f": 40.0,
                "monitoring_frequency_minutes": 60,
            },
            QA,
        )
        validate_error(resp, ApiErrorId.ERR_CCP_LIMIT_INVALID)
        assert resp.status_code == 422

        ccps, meta = validate_paginated(
            api.list_ccps(QA, params={"haccp_plan_id": plan["id"]})
        )
        assert ccps == [], "the rejected CCP must not be persisted"
        assert meta["total_count"] == 0


class TestDuplicatePlanConstraint:
    def test_duplicate_draft_plan_same_process_returns_duplicate_active_plan(self, api):
        """PRD §3.2: "Only one plan per plant and process type may be in flight at a time: if another plan for the same pair already exists in `DRAFT`, `SUBMITTED`, or `APPROVED` status, creation is rejected with `ERR_DUPLICATE_ACTIVE_PLAN`."

        Design: Corner/validations/duplicate_draft_plan_same_process_returns_duplicate_active_plan
        """
        plant = fixtures.create_plant(establishment_number="EST-1645-26")
        fixtures.create_draft_plan(plant["id"], process_type="RAW_GROUND")

        dup = api.create_haccp_plan(plant["id"], {"process_type": "RAW_GROUND"}, QA)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_ACTIVE_PLAN)
        assert dup.status_code == 422

        other = api.create_haccp_plan(plant["id"], {"process_type": "COOKED_RTE"}, QA)
        other_plan = validate_success(other, 201)
        assert other_plan["status"] == "DRAFT"
        assert other_plan["process_type"] == "COOKED_RTE"
