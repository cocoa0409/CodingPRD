"""Emergency operations plan lifecycle: submit gates, the return/resubmit
revision loop, activation supersession, and decision RBAC."""
from test_helpers import (
    ApiErrorId,
    activate_eop,
    complete_walkthrough,
    create_eop,
    create_site,
    decide_eop,
    get_eop,
    is_iso8601_timestamp,
    publish_site_plan,
    schedule_walkthrough,
    submit_eop,
    validate_error,
    validate_success,
)


class TestSubmitSitePlanGate:
    def test_eop_submit_requires_current_site_plan_rejected(self, api,
                                                            officer_headers):
        """PRD: "When the officer submits the plan — transitioning it from `DRAFT` to `SUBMITTED` — the system enforces two referential gates, evaluated in pinned order: first, the site must have a SitePlanDocument in `CURRENT` status (else `ERR_SITE_PLAN_REQUIRED`, HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/eop_submit_requires_current_site_plan
        """
        site = create_site(name="Cedar Grove High", enrollment_count=1200)
        walkthrough = schedule_walkthrough(site["id"], agency="POLICE",
                                           scheduled_date="2026-07-22")
        complete_walkthrough(walkthrough["id"], completed_date="2026-07-22")
        eop = create_eop(site["id"])

        resp = api.submit_eop(eop["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_SITE_PLAN_REQUIRED)

        current = get_eop(site["id"], eop["id"])
        assert current["status"] == "DRAFT", (
            f"Rejected submit must leave the plan DRAFT, got {current['status']}")

    def test_eop_submit_requires_current_site_plan_then_succeeds(
            self, api, officer_headers):
        """PRD: "first, the site must have a SitePlanDocument in `CURRENT` status (else `ERR_SITE_PLAN_REQUIRED`, HTTP 409); second, the site must have a FirstResponderWalkthrough in `COMPLETED` status whose `completed_date` falls within the trailing 365-day window ending at logical today, inclusive of the boundary (a walkthrough completed exactly 365 days before today is eligible; else `ERR_WALKTHROUGH_REQUIRED`, HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/eop_submit_requires_current_site_plan
        """
        site = create_site(name="Cedar Grove High", enrollment_count=1200)
        walkthrough = schedule_walkthrough(site["id"], agency="POLICE",
                                           scheduled_date="2026-07-22")
        complete_walkthrough(walkthrough["id"], completed_date="2026-07-22")
        eop = create_eop(site["id"])

        blocked = api.submit_eop(eop["id"], officer_headers)
        validate_error(blocked, ApiErrorId.ERR_SITE_PLAN_REQUIRED)

        publish_site_plan(site["id"])
        submitted = api.submit_eop(eop["id"], officer_headers)
        plan = validate_success(submitted, 200)
        assert plan["status"] == "SUBMITTED", (
            "With a CURRENT site plan and in-window walkthrough, submit must succeed")


class TestReturnResubmitCycle:
    def test_eop_return_resubmit_loop_reaches_active(self, api):
        """PRD: "A returned plan may be resubmitted: the submit endpoint accepts both `DRAFT` and `RETURNED` plans, and resubmission from `RETURNED` clears the previously recorded `return_reason` while again enforcing both the site-plan and walkthrough gates."
        PRD: "Activation cascades — any other plan at the same site currently in `ACTIVE` status transitions to `SUPERSEDED` (with its `updated_at` refreshed and `version` incremented), and the newly activated plan's `activated_at` is stamped with the logical timestamp."

        Design: Difficulty/non_linear_state_machine/eop_return_resubmit_cycle
        """
        site = create_site()
        publish_site_plan(site["id"])
        walkthrough = schedule_walkthrough(site["id"], scheduled_date="2026-07-20")
        complete_walkthrough(walkthrough["id"], completed_date="2026-07-20")
        eop = create_eop(site["id"])
        submit_eop(eop["id"])

        returned = decide_eop(eop["id"], "RETURN",
                              return_reason="Missing reunification section")
        assert returned["status"] == "RETURNED"
        assert returned.get("return_reason") == "Missing reunification section"

        resubmitted = submit_eop(eop["id"])
        assert resubmitted["status"] == "SUBMITTED"

        decide_eop(eop["id"], "APPROVE")
        activated = activate_eop(eop["id"])
        assert activated["status"] == "ACTIVE", (
            "The DRAFT -> SUBMITTED -> RETURNED -> SUBMITTED -> APPROVED -> ACTIVE "
            "loop must be reachable")
        assert is_iso8601_timestamp(activated.get("activated_at", "")), (
            "activated_at must be stamped with the logical timestamp")

    def test_eop_resubmission_clears_return_reason(self, api):
        """PRD: "If the decision is `RETURN`, the plan transitions from `SUBMITTED` to `RETURNED` — but a `return_reason` must be present in the request (else `ERR_VALIDATION`), and the provided reason is recorded on the plan. A returned plan may be resubmitted: the submit endpoint accepts both `DRAFT` and `RETURNED` plans, and resubmission from `RETURNED` clears the previously recorded `return_reason` while again enforcing both the site-plan and walkthrough gates."

        Design: Difficulty/non_linear_state_machine/eop_return_resubmit_cycle
        """
        site = create_site()
        publish_site_plan(site["id"])
        walkthrough = schedule_walkthrough(site["id"], scheduled_date="2026-07-20")
        complete_walkthrough(walkthrough["id"], completed_date="2026-07-20")
        eop = create_eop(site["id"])
        submit_eop(eop["id"])

        decide_eop(eop["id"], "RETURN", return_reason="Missing reunification section")
        after_return = get_eop(site["id"], eop["id"])
        assert after_return["status"] == "RETURNED"
        assert after_return.get("return_reason") == "Missing reunification section"

        submit_eop(eop["id"])
        after_resubmit = get_eop(site["id"], eop["id"])
        assert after_resubmit["status"] == "SUBMITTED"
        assert after_resubmit.get("return_reason") in (None, ""), (
            f"Resubmission from RETURNED must clear return_reason, "
            f"got {after_resubmit.get('return_reason')!r}")


class TestActivation:
    def test_eop_activate_supersedes_previous_active(self, api):
        """PRD: "Activation cascades — any other plan at the same site currently in `ACTIVE` status transitions to `SUPERSEDED` (with its `updated_at` refreshed and `version` incremented), and the newly activated plan's `activated_at` is stamped with the logical timestamp."

        Design: Corner/state_machines/eop_activate_supersedes_previous_active
        """
        site = create_site(name="Maplewood K-8", enrollment_count=850)
        publish_site_plan(site["id"])
        walkthrough = schedule_walkthrough(site["id"], scheduled_date="2026-07-20")
        complete_walkthrough(walkthrough["id"], completed_date="2026-07-20")

        plan_a = create_eop(site["id"], title="EOP 2026",
                            plan_version_label="v2026.0")
        submit_eop(plan_a["id"])
        decide_eop(plan_a["id"], "APPROVE")
        activate_eop(plan_a["id"])

        plan_b = create_eop(site["id"], title="EOP 2026 rev",
                            plan_version_label="v2026.1",
                            content_summary="Procedures revised")
        submit_eop(plan_b["id"])
        decide_eop(plan_b["id"], "APPROVE")
        activated_b = activate_eop(plan_b["id"])

        assert activated_b["status"] == "ACTIVE"
        superseded_a = get_eop(site["id"], plan_a["id"])
        assert superseded_a["status"] == "SUPERSEDED", (
            f"The previously ACTIVE plan must be SUPERSEDED, "
            f"got {superseded_a['status']}")

    def test_principal_cannot_decide_eop_returns_forbidden(
            self, api, principal_headers):
        """PRD: "A request whose role is not listed as authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD endpoint table: POST /emergency-operations-plans/{id}/decide is authorized for DistrictSafetyCoordinator only.

        Design: Corner/rbac/principal_cannot_decide_eop_returns_forbidden
        """
        site = create_site(name="Cedar Grove High", enrollment_count=1200)
        publish_site_plan(site["id"])
        walkthrough = schedule_walkthrough(site["id"], scheduled_date="2026-07-20")
        complete_walkthrough(walkthrough["id"], completed_date="2026-07-20")
        eop = create_eop(site["id"])
        submit_eop(eop["id"])

        resp = api.decide_eop(eop["id"], {"decision": "APPROVE"},
                              principal_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        current = get_eop(site["id"], eop["id"])
        assert current["status"] == "SUBMITTED", (
            "A forbidden decide must not move the plan out of SUBMITTED")
