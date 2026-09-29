"""State machines that are not simple forward chains: a component's two
independent dimensions, the report review loop that may repeat without bound, and
the complaint fork whose two branches rejoin at closure with different traces."""

import pytest

from test_helpers import (
    REVIEWER,
    REVIEWER_USER_ID,
    approval_payload,
    board_review_issue,
    close_complaint,
    complete_component,
    design_review_payload,
    enrolled_product,
    fulfill_accommodation,
    intake_complaint,
    link_complaint_issue,
    log_issue,
    open_report,
    publishable_product,
    read_complaint,
    read_component,
    read_known_issue,
    read_product,
    read_report,
    record_design_review,
    request_changes,
    submit_report,
    triage_complaint,
    triage_issue,
    validate_success,
)

# A manual screen-reader run exercising all 40 applicable criteria puts the
# component exactly on the 45.00 attestation floor, so its testing dimension is
# COMPLETE before any design-review verdict is recorded.
APPLICABLE_CRITERIA = 40


def build_component_complete_before_any_design_review():
    setup = enrolled_product()
    built = complete_component(
        setup["product"]["id"],
        name="Web UI",
        applicable_criteria_count=APPLICABLE_CRITERIA,
        user_reach_pct=60,
        validated_categories=["VISION", "COGNITIVE"],
    )
    return {**setup, **built}


def build_report_returned_once_and_resubmitted():
    """A report driven once around the review loop and left IN_REVIEW."""
    scenario = publishable_product()
    product = scenario["product"]
    report = open_report(product["id"], scenario["standard"]["id"])
    submit_report(report["id"], product["id"])
    returned = request_changes(report["id"], "Add the keyboard-only evidence before we sign")
    submit_report(report["id"], product["id"])
    return {**scenario, "report": read_report(report["id"]), "returned": returned}


def build_two_complaints_one_per_branch():
    """One remediation-routed complaint linked to a deferred issue, one accommodation."""
    setup = enrolled_product()
    product = setup["product"]
    built = complete_component(
        product["id"],
        name="Web UI",
        applicable_criteria_count=APPLICABLE_CRITERIA,
        user_reach_pct=60,
    )
    component = built["component"]
    issue = log_issue(
        product["id"],
        component["id"],
        setup["criterion"]["id"],
        severity="SERIOUS",
        effort_points=4,
        target_remediation_date="2026-09-15",
        publish_intent="INCLUDED",
        summary="Contrast on the secondary navigation falls below the ratio",
    )
    triage_issue(issue["id"])

    remediation = intake_complaint(
        product["id"],
        component_id=component["id"],
        criterion_id=setup["criterion"]["id"],
        channel="EMAIL",
        description="Low-vision users cannot read the secondary navigation",
        disability_category="VISION",
    )
    triage_complaint(remediation["id"], route="REMEDIATION")
    link_complaint_issue(remediation["id"], issue["id"])
    board_review_issue(issue["id"], defer=True)

    accommodation = intake_complaint(
        product["id"],
        component_id=component["id"],
        channel="PHONE",
        description="Requesting an accessible PDF of the pricing sheet",
        disability_category="VISION",
    )
    triage_complaint(
        accommodation["id"],
        route="ACCOMMODATION",
        requested_accommodation="Send a tagged, screen-reader friendly PDF of the pricing sheet",
        needed_by_date="2026-08-20",
    )
    fulfill_accommodation(accommodation["id"])
    return {
        **setup,
        "component": component,
        "issue": issue,
        "remediation": remediation,
        "accommodation": accommodation,
    }


class TestComponentDimensionsAreIndependent:
    """Design review never reaches into the testing dimension, and vice versa."""

    def test_a_blocking_design_review_leaves_testing_progress_untouched(self, api):
        """PRD §2.11: "A component's `assessment_state` (testing progress) and
        its `design_review_state` (development-lifecycle sign-off) advance on
        entirely separate triggers and never gate each other: a component may
        reach `COMPLETE` testing while still `NOT_REVIEWED`, and it may be
        `REVIEWED_PASS` while still `PLANNED`."
        PRD §3.2: "What a design review never does is touch the testing
        dimension: `assessment_state`, `coverage_pct` and the product's
        `assessment_readiness` are all left exactly as they were, because the two
        dimensions of a component are independent."

        Design: Difficulty/non_linear_state_machine/component_assessment_and_design_review_dimensions_are_independent
        """
        ctx = build_component_complete_before_any_design_review()

        blocked = validate_success(
            api.design_review(
                ctx["component"]["id"],
                design_review_payload("BLOCK", "Acceptance criteria are not signed off yet"),
                REVIEWER,
            )
        )

        assert blocked["design_review_state"] == "REVIEWED_BLOCKED"
        assert blocked["assessment_state"] == "COMPLETE", (
            "a BLOCK verdict may not push the testing dimension backwards, got "
            f"{blocked['assessment_state']}"
        )
        assert blocked["coverage_pct"] == pytest.approx(45.00, abs=0.01), (
            f"coverage is left exactly as it was, expected 45.00, got {blocked['coverage_pct']}"
        )
        product = read_product(ctx["product"]["id"])
        assert product["assessment_readiness"] == "READY", (
            "the product's readiness is derived from testing progress alone, got "
            f"{product['assessment_readiness']}"
        )

    def test_the_design_dimension_is_cyclic_and_replaces_its_note(self, api):
        """PRD §3.2: "A `PASS` moves the design dimension to `REVIEWED_PASS`,
        whether the component was `NOT_REVIEWED` or `REVIEWED_BLOCKED`; a `BLOCK`
        moves it to `REVIEWED_BLOCKED`, whether the component was `NOT_REVIEWED`
        or `REVIEWED_PASS`."
        PRD §3.2: "The dimension is therefore cyclic: `NOT_REVIEWED →
        REVIEWED_PASS → REVIEWED_BLOCKED → REVIEWED_PASS` is a legal history."
        PRD §3.2: "In all four transitions the supplied `review_note` is written
        to `design_review_note`, replacing any earlier remark, a design-review
        instant is recorded from the logical clock, and both the component's
        `version` and the product's `version` increase by 1."

        Design: Difficulty/non_linear_state_machine/component_assessment_and_design_review_dimensions_are_independent
        """
        ctx = build_component_complete_before_any_design_review()

        record_design_review(ctx["component"]["id"], "BLOCK", "Acceptance criteria not signed off")
        blocked = read_component(ctx["component"]["id"])

        passed = validate_success(
            api.design_review(
                ctx["component"]["id"],
                design_review_payload("PASS", "Sign-off complete after the second walkthrough"),
                REVIEWER,
            )
        )

        assert passed["design_review_state"] == "REVIEWED_PASS", (
            "REVIEWED_BLOCKED climbs back to REVIEWED_PASS, got "
            f"{passed['design_review_state']}"
        )
        assert passed["design_review_note"] == "Sign-off complete after the second walkthrough", (
            f"the later note replaces the earlier remark, got {passed['design_review_note']}"
        )
        assert passed["version"] == blocked["version"] + 1, (
            "each design-review decision raises the component's version by exactly 1, got "
            f"{passed['version']} after {blocked['version']}"
        )
        assert passed["assessment_state"] == "COMPLETE"
        assert passed["coverage_pct"] == pytest.approx(45.00, abs=0.01)


class TestReportReviewLoopRepeatsAndRepinsEvidence:
    """Returning a report clears its pins; approval after the loop re-pins them."""

    def test_returning_the_report_clears_the_pins_and_counts_the_return(self, api):
        """PRD §3.7: "Returning it carries a `change_request_note`, moves the
        report `IN_REVIEW → CHANGES_REQUESTED`, raises `change_request_count` by
        1, and clears `pinned_assessment_ids` and `pinned_assessment_versions`
        back to empty lists."
        PRD §3.7: "From `CHANGES_REQUESTED` a fresh submission returns the report
        to `IN_REVIEW`, and the loop `IN_REVIEW → CHANGES_REQUESTED → DRAFT →
        IN_REVIEW` may repeat without bound, with `change_request_count`
        recording how many times the report has been returned."
        PRD §3.7: "On success the acting `X-User-ID` is written to
        `submitted_by_user_id`, overwriting any earlier submitter when the report
        is coming back around the review loop, and a submission instant is
        stamped from the logical clock."

        Design: Difficulty/non_linear_state_machine/report_review_loop_repeats_and_repins_evidence
        """
        ctx = build_report_returned_once_and_resubmitted()

        returned = ctx["returned"]
        assert returned["state"] == "CHANGES_REQUESTED"
        assert returned["change_request_count"] == 1, (
            f"one return has been recorded, got {returned['change_request_count']}"
        )
        assert returned["pinned_assessment_ids"] == []
        assert returned["pinned_assessment_versions"] == []

        resubmitted = ctx["report"]
        assert resubmitted["state"] == "IN_REVIEW", (
            f"a fresh submission returns the report to review, got {resubmitted['state']}"
        )
        assert resubmitted["submitted_by_user_id"] == ctx["product"]["id"], (
            "the ProductOwner's X-User-ID is the product's id, and it is recorded as the "
            f"submitter, got {resubmitted['submitted_by_user_id']}"
        )
        assert resubmitted["change_request_count"] == 1, (
            "resubmission does not reset the return counter, got "
            f"{resubmitted['change_request_count']}"
        )

    def test_approval_after_the_loop_repins_the_attested_evidence(self, api):
        """PRD §3.7: "Approval carries an `approval_note` and moves the report
        `IN_REVIEW → APPROVED`; the approving reviewer's `X-User-ID` must differ
        from the report's `submitted_by_user_id`, or the request is
        `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.7: "On approval the acting `X-User-ID` is recorded as
        `approved_by_user_id`, an approval instant is stamped from the logical
        clock, and the evidence is **pinned**: `pinned_assessment_ids` is frozen
        as the identifiers of every criterion assessment currently in `ATTESTED`
        state belonging to one of the product's in-scope components, ordered by
        the assessments' `created_at` ascending, and `pinned_assessment_versions`
        captures those same rows' `version` values in the same index-aligned
        order."

        Design: Difficulty/non_linear_state_machine/report_review_loop_repeats_and_repins_evidence
        """
        ctx = build_report_returned_once_and_resubmitted()

        approved = validate_success(
            api.approve_report(
                ctx["report"]["id"],
                approval_payload("Evidence is now complete and independently attested"),
                REVIEWER,
            )
        )

        assert approved["state"] == "APPROVED"
        assert approved["pinned_assessment_ids"] == [ctx["assessment"]["id"]], (
            "the single ATTESTED row on the in-scope component is pinned again, expected "
            f"[{ctx['assessment']['id']}], got {approved['pinned_assessment_ids']}"
        )
        assert len(approved["pinned_assessment_versions"]) == len(
            approved["pinned_assessment_ids"]
        ), "the two pinned lists are index-aligned"
        assert approved["approved_by_user_id"] == REVIEWER_USER_ID, (
            f"the approving reviewer is recorded, got {approved['approved_by_user_id']}"
        )
        assert approved["change_request_count"] == 1


class TestComplaintForkJoinBranches:
    """Both branches land in CLOSED, but they leave different traces behind."""

    def test_remediation_branch_closes_against_a_deferred_issue(self, api):
        """PRD §3.11: "On success the complaint moves `TRIAGED → LINKED`, its
        `linked_issue_id` is recorded, the issue's `linked_complaint_count` rises
        by 1, and the issue's `risk_score` is recomputed under whichever
        `risk_variant` it currently carries — which is how customer pressure
        feeds back into prioritization, since the `BOARD_REVIEW` variant
        amplifies by the complaint count while the `INTAKE_ESTIMATE` variant
        ignores it."
        PRD §3.11: "Closing from `LINKED` requires that the linked known issue
        has come to rest — its state must be `RESOLVED` or `DEFERRED`, or the
        request is `ERR_LINKED_ISSUE_UNRESOLVED` — and the `closure_outcome` must
        be either `REMEDIATION_SCHEDULED` or `NOT_A_DEFECT`; anything else is
        `ERR_COMPLAINT_ROUTE_MISMATCH`."
        PRD §3.11: "In both cases the `closure_outcome` and a `closed_at` instant
        from the logical clock are recorded; on the accommodation branch no known
        issue is touched, and on the remediation branch the linked issue keeps
        whatever state it had reached."

        Design: Difficulty/non_linear_state_machine/complaint_fork_join_branches_carry_different_side_effects
        """
        ctx = build_two_complaints_one_per_branch()

        closed = close_complaint(ctx["remediation"]["id"], "REMEDIATION_SCHEDULED")

        assert closed["state"] == "CLOSED"
        assert closed["closure_outcome"] == "REMEDIATION_SCHEDULED"
        assert closed["linked_issue_id"] == ctx["issue"]["id"]
        assert closed["accommodation_fulfilled_at"] is None, (
            "the remediation branch never records an accommodation instant, got "
            f"{closed['accommodation_fulfilled_at']}"
        )
        assert closed["requested_accommodation"] is None
        issue = read_known_issue(ctx["issue"]["id"])
        assert issue["linked_complaint_count"] == 1, (
            f"the linked complaint is counted on the issue, got {issue['linked_complaint_count']}"
        )
        assert issue["state"] == "DEFERRED", (
            f"closure leaves the linked issue where it had come to rest, got {issue['state']}"
        )

    def test_accommodation_branch_closes_with_a_fulfilment_trace(self, api):
        """PRD §3.11: "On success the complaint moves `TRIAGED → ACCOMMODATED`,
        `accommodation_fulfilled_at` is stamped from the logical clock, and the
        product's `accommodations_fulfilled_count` is rebuilt."
        PRD §3.11: "Closing from `ACCOMMODATED` imposes no cross-entity condition
        at all, and its `closure_outcome` must be either `ACCOMMODATION_PROVIDED`
        or `ACCOMMODATION_DENIED`, with the same mismatch code guarding the
        branch."
        PRD §3.1: "`accommodations_fulfilled_count` is the number of the
        product's complaints that carry a recorded accommodation-fulfilment
        instant"

        Design: Difficulty/non_linear_state_machine/complaint_fork_join_branches_carry_different_side_effects
        """
        ctx = build_two_complaints_one_per_branch()

        fulfilled = read_complaint(ctx["accommodation"]["id"])
        assert fulfilled["state"] == "ACCOMMODATED"
        assert fulfilled["accommodation_fulfilled_at"] is not None

        closed = close_complaint(ctx["accommodation"]["id"], "ACCOMMODATION_PROVIDED")

        assert closed["state"] == "CLOSED"
        assert closed["closure_outcome"] == "ACCOMMODATION_PROVIDED"
        assert closed["linked_issue_id"] is None, (
            "the accommodation branch links no known issue, got "
            f"{closed['linked_issue_id']}"
        )
        product = read_product(ctx["product"]["id"])
        assert product["accommodations_fulfilled_count"] == 1, (
            "exactly one of the two complaints carries a fulfilment instant, got "
            f"{product['accommodations_fulfilled_count']}"
        )
