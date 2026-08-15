"""After-action reviews and corrective actions: the review revision loop,
one-review-per-drill uniqueness, self-approval segregation, the reopen
rework loop, and the verification cascade that closes review and drill."""
from test_helpers import (
    ApiErrorId,
    create_aar_payload,
    create_review,
    decide_review,
    get_corrective_action,
    get_drill,
    get_review,
    get_site,
    make_officer_headers,
    make_principal_headers,
    run_completed_drill,
    set_clock,
    setup_accepted_review_scenario,
    setup_active_eop_site,
    setup_pending_verification_action,
    submit_ca_verification,
    submit_review,
    validate_error,
    validate_success,
    verify_corrective_action,
)


class TestReviewLifecycle:
    def test_aar_return_resubmit_cycle(self, api):
        """PRD: "The officer submits the review — from `DRAFT` or from `RETURNED` — moving it to `SUBMITTED` and recording `submitted_by_user_id`. Resubmission from `RETURNED` clears the prior `return_reason`."
        PRD: "An `ACCEPT` decision moves the review from `SUBMITTED` to `ACCEPTED` and records `decided_by_user_id`."

        Design: Corner/state_machines/aar_return_resubmit_cycle
        """
        ctx = setup_active_eop_site(site_name="Cedar Grove High",
                                    enrollment_count=1200)
        drill = run_completed_drill(ctx["site"]["id"],
                                    scheduled_date="2026-09-15")
        review = create_review(drill["id"],
                               findings_summary="Initial draft findings",
                               overall_rating="NEEDS_IMPROVEMENT",
                               evacuation_assessment="NOT_MET")

        submit_review(review["id"], officer_user_id="officer-1")
        returned = decide_review(review["id"], "RETURN",
                                 principal_user_id="principal-1",
                                 return_reason="Add reunification timing analysis")
        assert returned["status"] == "RETURNED"
        assert returned.get("return_reason") == "Add reunification timing analysis"

        resubmitted = submit_review(review["id"], officer_user_id="officer-1")
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted.get("return_reason") in (None, ""), (
            "Resubmission from RETURNED must clear the prior return_reason")

        accepted = decide_review(review["id"], "ACCEPT",
                                 principal_user_id="principal-1")
        assert accepted["status"] == "ACCEPTED", (
            "The DRAFT -> SUBMITTED -> RETURNED -> SUBMITTED -> ACCEPTED loop "
            "must be reachable")

    def test_aar_exists_rejected(self, api, officer_headers):
        """PRD: "Once a drill is `COMPLETED`, the officer opens its **AfterActionReview** — at most one review per drill."
        PRD: "A second review on the same drill is rejected with `ERR_AAR_EXISTS`."

        Design: Corner/validations/aar_exists_rejected
        """
        ctx = setup_active_eop_site(site_name="Harborview Middle",
                                    enrollment_count=700)
        drill = run_completed_drill(ctx["site"]["id"],
                                    scheduled_date="2026-09-15")
        first = api.create_after_action_review(
            drill["id"], create_aar_payload(findings_summary="First review"),
            officer_headers)
        validate_success(first, 201)

        second = api.create_after_action_review(
            drill["id"], create_aar_payload(findings_summary="Duplicate review"),
            officer_headers)
        validate_error(second, ApiErrorId.ERR_AAR_EXISTS)

    def test_self_approval_forbidden_on_review_decide(self, api):
        """PRD: "The decider's `X-User-ID` must differ from the review's `submitted_by_user_id` — a self-approval is rejected with `ERR_SELF_APPROVAL_FORBIDDEN`."

        Design: Corner/rbac/self_approval_forbidden_on_review_decide
        """
        ctx = setup_active_eop_site(site_name="Maplewood K-8",
                                    enrollment_count=850)
        drill = run_completed_drill(ctx["site"]["id"],
                                    scheduled_date="2026-09-15")
        review = create_review(drill["id"], findings_summary="Findings")

        submit = api.submit_after_action_review(
            review["id"], make_officer_headers("shared-user"))
        validate_success(submit, 200)

        resp = api.decide_after_action_review(
            review["id"], {"decision": "ACCEPT"},
            make_principal_headers("shared-user"))
        validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)

        current = get_review(review["id"])
        assert current["status"] == "SUBMITTED", (
            "A self-approval rejection must leave the review SUBMITTED")


class TestCorrectiveActionStates:
    def test_verify_open_action_returns_invalid_state(self, api,
                                                      coordinator_headers):
        """PRD: "The officer submits verification by providing an `evidence_note`, moving the action from `OPEN` (or `REOPENED`) to `PENDING_VERIFICATION`. The coordinator then decides: a `decision` of `VERIFY` moves the action to `VERIFIED` (terminal), records `verified_by_user_id`, and increments the review's `ca_verified_count`."
        PRD: "(5) state validity — the target resource must be in a state from which the requested transition exists, else `ERR_INVALID_STATE`"

        Design: Corner/state_machines/verify_open_action_returns_invalid_state
        """
        ctx = setup_accepted_review_scenario(ca_spec={})
        action = ctx["action"]
        assert action["status"] == "OPEN"

        resp = api.verify_corrective_action(action["id"], {"decision": "VERIFY"},
                                            coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        current = get_corrective_action(ctx["review"]["id"], action["id"])
        assert current["status"] == "OPEN", (
            "Verify on an OPEN action must be rejected; only "
            "PENDING_VERIFICATION actions can be verified")
        review = get_review(ctx["review"]["id"])
        assert review["status"] == "ACCEPTED"

    def test_reopen_cycle_transitions(self, api):
        """PRD: "A `decision` of `REOPEN` moves the action from `PENDING_VERIFICATION` to `REOPENED`, and the site's `compliance_posture` recomputes (the action remains non-verified and may be overdue)."
        PRD: "The officer submits verification by providing an `evidence_note`, moving the action from `OPEN` (or `REOPENED`) to `PENDING_VERIFICATION`."

        Design: Difficulty/non_linear_state_machine/corrective_action_reopen_cycle
        """
        ctx = setup_pending_verification_action(
            evidence_note="Signage ordered and installed")
        action = ctx["action"]
        assert action["status"] == "PENDING_VERIFICATION"

        reopened = verify_corrective_action(action["id"], "REOPEN",
                                            note="Photo evidence missing")
        assert reopened["status"] == "REOPENED", (
            "REOPEN must move PENDING_VERIFICATION -> REOPENED")

        resubmitted = submit_ca_verification(action["id"],
                                             "Photo evidence attached")
        assert resubmitted["status"] == "PENDING_VERIFICATION", (
            "The REOPENED -> PENDING_VERIFICATION resubmission completes the "
            "rework half of the cycle")

    def test_reopen_cycle_completes_to_verified(self, api):
        """PRD: "The officer submits verification by providing an `evidence_note`, moving the action from `OPEN` (or `REOPENED`) to `PENDING_VERIFICATION`. The coordinator then decides: a `decision` of `VERIFY` moves the action to `VERIFIED` (terminal), records `verified_by_user_id`, and increments the review's `ca_verified_count`."

        Design: Difficulty/non_linear_state_machine/corrective_action_reopen_cycle
        """
        ctx = setup_pending_verification_action(
            evidence_note="Signage ordered and installed")
        action = ctx["action"]
        verify_corrective_action(action["id"], "REOPEN",
                                 note="Photo evidence missing")
        submit_ca_verification(action["id"], "Photo evidence attached")

        verified = verify_corrective_action(action["id"], "VERIFY")
        assert verified["status"] == "VERIFIED", (
            "OPEN -> PENDING_VERIFICATION -> REOPENED -> PENDING_VERIFICATION "
            "-> VERIFIED must be reachable")
        assert verified.get("evidence_note") == "Photo evidence attached", (
            "The latest evidence_note must be retained")

        review = get_review(ctx["review"]["id"])
        assert review["ca_verified_count"] == 1


class TestVerificationCascade:
    def test_verification_closes_review(self, api):
        """PRD: "When a verification causes an `ACCEPTED` review to have `ca_total_count` at least 1 and every one of its corrective actions in `VERIFIED` status, the review auto-transitions from `ACCEPTED` to `CLOSED`."

        Design: Difficulty/transitive_cascade/verification_cascade_closes_review_and_drill
        """
        ctx = setup_pending_verification_action(evidence_note="Installed")
        action = ctx["action"]

        verified = verify_corrective_action(action["id"], "VERIFY")
        assert verified["status"] == "VERIFIED"

        review = get_review(ctx["review"]["id"])
        assert review["status"] == "CLOSED", (
            f"Verifying the last open action must close the ACCEPTED review, "
            f"got {review['status']}")
        assert review["ca_total_count"] == 1
        assert review["ca_verified_count"] == 1

    def test_verification_closes_drill_and_counters_hold(self, api):
        """PRD: "That closure cascades further: the parent drill (in `COMPLETED` status) transitions to `CLOSED`, and the site's drill counters and `compliance_posture` recompute."
        PRD: "`drills_completed_count` counts drills in `COMPLETED` or `CLOSED` status."

        Design: Difficulty/transitive_cascade/verification_cascade_closes_review_and_drill
        """
        ctx = setup_pending_verification_action(evidence_note="Installed")
        verify_corrective_action(ctx["action"]["id"], "VERIFY")

        drill = get_drill(ctx["drill"]["id"])
        assert drill["status"] == "CLOSED", (
            f"The review's closure must cascade the drill COMPLETED -> CLOSED, "
            f"got {drill['status']}")

        site = get_site(ctx["site"]["id"])
        assert site["drills_completed_count"] == 1, (
            "CLOSED still feeds the completed bucket")


class TestOverduePostureBoundary:
    def test_overdue_ca_flips_posture_at_day_boundary(self, api):
        """PRD: "Every corrective action carries a computed `is_overdue` flag: true when logical today has passed the action's `due_date` and the action's `status` is not `VERIFIED`."
        PRD: "Otherwise, the posture is `AT_RISK` when either of two conditions holds: any drill at the site has `MISSED` status with a `scheduled_date` inside the current academic year; or at least 1 overdue corrective action exists."

        Design: Corner/cross_cutting_layers/overdue_ca_flips_posture_at_day_boundary
        """
        ctx = setup_accepted_review_scenario(
            site_name="Cedar Grove High", enrollment_count=1200,
            ca_spec={"description": "Replace gate signage", "priority": "MEDIUM",
                     "due_date": "2026-10-15", "assignee_name": "Facilities Lead"})
        site_id = ctx["site"]["id"]
        action = ctx["action"]

        # On the due date itself the action is NOT overdue (strict >).
        set_clock("2026-10-15T00:00:00Z")
        on_due = get_corrective_action(ctx["review"]["id"], action["id"])
        assert on_due["is_overdue"] is False, (
            "On the due_date itself the action must not yet be overdue")
        site_on_due = get_site(site_id)
        assert site_on_due["compliance_posture"] == "ON_TRACK"

        # One day later the flag flips and the posture degrades.
        set_clock("2026-10-16T00:00:00Z")
        after = get_corrective_action(ctx["review"]["id"], action["id"])
        assert after["is_overdue"] is True
        site_after = get_site(site_id)
        assert site_after["compliance_posture"] == "AT_RISK", (
            "One overdue corrective action forces at least AT_RISK")
