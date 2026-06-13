"""Compliance review, the depth-3 fail cascade, and the cyclic revision loop.

Covers queue A (Difficulty) transitive_cascade and non_linear_state_machine
instances, plus queue B cross_entity_state_dependency for report-submission
revisability.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, factories, fixtures,
)

COORD = TEST_USERS["coordinator_headers"]
REVIEWER = TEST_USERS["compliance_reviewer_headers"]


def test_compliance_fail_cascades_depth3(api):
    """PRD §3.5 (FAIL): "A failure creates a `RevisionRequest` with origin `COMPLIANCE` in
    status `OPEN`, then runs the depth-three compliance-fail cascade: the report moves from
    `UNDER_REVIEW` to `REVISION_REQUESTED`, the assignment moves from `ACCEPTED` to
    `REVISION` (incrementing its `revision_round` by one), and the order reverts from
    `IN_QC` to `IN_PROGRESS` (incrementing the order's `version`)."
    PRD §3.5: "**FAIL** results when either snapshot boolean is false, or when
    `finding_codes` contains at least one USPAP code."

    Design: Difficulty/transitive_cascade/compliance_fail_cascades_review_report_assignment_order_depth3
    """
    # 2 comparables -> USPAP minimum NOT met -> FAIL.
    base = fixtures.setup_order_in_qc(comparable_count=2)
    review = base["review"]
    cr = validate_success(
        api.finalize_compliance_review(
            review["id"], factories.finalize_review_payload(finding_codes=["USPAP_1004_MIN_COMPS"]), REVIEWER,
        ),
        200,
    )
    assert cr["outcome"] == "FAIL", f"USPAP-deficient review must FAIL, got {cr['outcome']}"

    report = validate_success(api.get_report(base["report"]["id"], REVIEWER), 200)
    assert report["status"] == "REVISION_REQUESTED", f"report must be REVISION_REQUESTED, got {report['status']}"

    asg = validate_success(api.get_assignment(base["assignment"]["id"], COORD), 200)
    assert asg["status"] == "REVISION", f"assignment must move to REVISION, got {asg['status']}"
    assert asg["revision_round"] == 1, f"revision_round must increment to 1, got {asg['revision_round']}"

    order = validate_success(api.get_order(base["order"]["id"], COORD), 200)
    assert order["status"] == "IN_PROGRESS", f"order must revert to IN_PROGRESS, got {order['status']}"


def test_compliance_fail_recomputes_revision_penalty(api):
    """PRD §3.5 (FAIL): "Because the assignment entered a revision round, the fee split's
    revision penalty is recomputed and the appraiser and AMC shares are re-split with
    conservation preserved (see §3.6)."
    PRD §3.6: "for each completed revision round on the assignment, a flat penalty equal to
    the `order_fee_cents` multiplied by the revision-penalty fraction of five percent —
    rounded half-up to whole cents for that one round — is added to the running penalty".

    Design: Difficulty/transitive_cascade/compliance_fail_cascades_review_report_assignment_order_depth3
    """
    # fee 50000 share 0.50 -> base 25000; one revision penalty 2500.
    base = fixtures.setup_order_ready_to_assign(order_fee_cents=50000, base_fee_share_pct=0.50)
    order = base["order"]
    asg = fixtures.assign_order(order["id"], order["version"])
    fixtures.accept_assignment(asg["id"], base["appraiser"]["id"])
    report = fixtures.submit_report(asg["id"], base["appraiser"]["id"], comparable_count=2)
    cr = fixtures.open_review(report["id"])
    validate_success(
        api.finalize_compliance_review(
            cr["id"], factories.finalize_review_payload(finding_codes=["USPAP_1004_MIN_COMPS"]), REVIEWER,
        ),
        200,
    )
    fee_split = validate_success(api.get_order_fee_split(order["id"], COORD), 200)[0]
    assert fee_split["revision_penalty_cents"] == 2500, (
        f"one revision round penalty must be round_half_up(50000*0.05)=2500, "
        f"got {fee_split['revision_penalty_cents']}"
    )
    assert fee_split["appraiser_fee_cents"] + fee_split["amc_fee_cents"] == 50000, "fee conservation"


def test_report_revision_cycle_returns_to_under_review(api):
    """PRD §3.4: "A resubmission applies when the report is currently in
    `REVISION_REQUESTED`: it supersedes the report in place, advancing it to `RESUBMITTED`,
    marks the open revision request as `RESOLVED`".
    PRD §3.5: "A `ComplianceReviewer` (or a `PlatformAdmin`) opens a review on a report
    that is in `SUBMITTED` or `RESUBMITTED`; this creates a `ComplianceReview` in `PENDING`
    and moves the report to `UNDER_REVIEW`."
    PRD §3.5: "Each open of a review on a resubmitted report creates a new `ComplianceReview`."

    Design: Difficulty/non_linear_state_machine/report_revision_cycle_loops_back_to_under_review
    """
    base = fixtures.setup_order_in_qc(comparable_count=2)
    report_id = base["report"]["id"]
    asg_id = base["assignment"]["id"]
    # Finalize FAIL once -> revision opens.
    validate_success(
        api.finalize_compliance_review(
            base["review"]["id"], factories.finalize_review_payload(finding_codes=["USPAP_1004_MIN_COMPS"]), REVIEWER,
        ),
        200,
    )
    # Resubmit (4 comps) -> report RESUBMITTED, assignment back to ACCEPTED.
    fixtures.submit_report(asg_id, base["appraiser"]["id"], comparable_count=4)
    # Re-open compliance review -> report re-enters UNDER_REVIEW (the loop closes).
    validate_success(api.open_compliance_review(report_id, {}, REVIEWER), 201)

    report = validate_success(api.get_report(report_id, REVIEWER), 200)
    assert report["status"] == "UNDER_REVIEW", f"report must re-enter UNDER_REVIEW, got {report['status']}"
    asg = validate_success(api.get_assignment(asg_id, COORD), 200)
    assert asg["revision_round"] == 1, f"revision_round must be 1 after one loop, got {asg['revision_round']}"


def test_revision_resubmit_closes_loop_assignment_and_order(api):
    """PRD §3.4: "A resubmission applies when the report is currently in
    `REVISION_REQUESTED`: it supersedes the report in place, advancing it to `RESUBMITTED`,
    marks the open revision request as `RESOLVED`, and runs the revision-loop close — the
    assignment returns from `REVISION` to `ACCEPTED`, and the order climbs from
    `IN_PROGRESS` back to `IN_QC`."

    Design: Difficulty/non_linear_state_machine/report_revision_cycle_loops_back_to_under_review
    """
    base = fixtures.setup_order_in_qc(comparable_count=2)
    report_id = base["report"]["id"]
    asg_id = base["assignment"]["id"]
    order_id = base["order"]["id"]
    # Finalize FAIL -> report REVISION_REQUESTED, assignment REVISION, order IN_PROGRESS.
    validate_success(
        api.finalize_compliance_review(
            base["review"]["id"], factories.finalize_review_payload(finding_codes=["USPAP_1004_MIN_COMPS"]), REVIEWER,
        ),
        200,
    )
    # Resubmit -> closes the loop.
    report = fixtures.submit_report(asg_id, base["appraiser"]["id"], comparable_count=4)
    assert report["status"] == "RESUBMITTED", f"resubmit must advance report to RESUBMITTED, got {report['status']}"
    asg = validate_success(api.get_assignment(asg_id, COORD), 200)
    assert asg["status"] == "ACCEPTED", f"assignment must return to ACCEPTED on resubmit, got {asg['status']}"
    order = validate_success(api.get_order(order_id, COORD), 200)
    assert order["status"] == "IN_QC", f"order must climb back to IN_QC on resubmit, got {order['status']}"


def test_report_submission_requires_accepted_assignment(api):
    """PRD §3.4: "A submission is only honored when its target assignment is in `ACCEPTED`
    or `REVISION` status and that assignment belongs to the acting appraiser; otherwise it
    is rejected with `ERR_ASSIGNMENT_NOT_REVISABLE`."

    Design: Difficulty/cross_entity_state_dependency/report_submission_requires_assignment_accepted_pair_report_assignment
    """
    base = fixtures.setup_order_ready_to_assign()
    order = base["order"]
    asg = fixtures.assign_order(order["id"], order["version"])  # OFFERED, not yet accepted
    resp = api.submit_report(
        asg["id"],
        factories.submit_report_payload(comparable_count=5),
        fixtures.make_appraiser_headers(base["appraiser"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_REVISABLE.value, 409)


def test_report_submission_offered_assignment_no_revision_round(api):
    """PRD §3.4: "A submission is only honored when its target assignment is in `ACCEPTED`
    or `REVISION` status and that assignment belongs to the acting appraiser; otherwise it
    is rejected with `ERR_ASSIGNMENT_NOT_REVISABLE`."
    PRD §2.10: "**Report-target revisability** on report submission — the assignment must
    be in an acceptable state and owned by the acting appraiser, else
    `ERR_ASSIGNMENT_NOT_REVISABLE`".

    Design: Difficulty/cross_entity_state_dependency/report_submission_requires_assignment_accepted_pair_report_assignment
    """
    base = fixtures.setup_order_ready_to_assign()
    order = base["order"]
    asg = fixtures.assign_order(order["id"], order["version"])  # OFFERED
    resp = api.submit_report(
        asg["id"],
        factories.submit_report_payload(comparable_count=3),
        fixtures.make_appraiser_headers(base["appraiser"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_REVISABLE.value, 409)
    # No assignment side effects: it stays OFFERED with revision_round 0.
    asg_after = validate_success(api.get_assignment(asg["id"], COORD), 200)
    assert asg_after["status"] == "OFFERED", f"rejected submission must leave assignment OFFERED, got {asg_after['status']}"
    assert asg_after["revision_round"] == 0
