"""Compound BackgroundCheckOrder.status walking PENDING -> IN_REVIEW ->
COMPLETE, and the transitive cascade where the third REPORT drives the
parent to COMPLETE+CONSIDER which auto-creates AdverseAction in
PRE_ADVERSE_SENT.
"""
from test_helpers import (
    validate_success,
    order_with_three_pending_verifications,
    make_recruiter_headers, CO,
)
from test_helpers.fixtures import report_verification, api_client


def test_order_status_pending_then_in_review_then_complete_via_three_reports(api):
    """The order's compound status is derived from its three child
    Verifications: PENDING when all children are PENDING, IN_REVIEW once
    at least one has reported, COMPLETE once all three have reported.

    PRD §3.4: "The order's `status` is computed from its three children:
    `PENDING` until any child is non-`PENDING`; `IN_REVIEW` once at least
    one child has reported but at least one remains `PENDING`; `COMPLETE`
    once all three are in `REPORTED` or `RESOLVED` (the system also bridges
    any sibling that was `REPORTED` to `RESOLVED` as part of the same
    transition). The first report on a `PENDING` order normally drives the
    order from `PENDING` to `IN_REVIEW`"

    Design: Difficulty/non_linear_state_machine/order_compound_status_derived_from_three_parallel_children
    """
    (jur, applicant, app, consent, order,
     crim, mvr, edu) = order_with_three_pending_verifications(
         state_code="OR", recruiter_id="rec-carol",
    )
    initial = validate_success(api.get_order(order["id"],
                                              make_recruiter_headers("rec-carol")), 200)
    assert initial["status"] == "PENDING", \
        f"order with three PENDING verifications must be PENDING, got {initial['status']!r}"
    report_verification(crim["id"], "PASS", crim["version"])
    mid = validate_success(api.get_order(order["id"],
                                          make_recruiter_headers("rec-carol")), 200)
    assert mid["status"] == "IN_REVIEW", \
        f"after one REPORT, order must be IN_REVIEW, got {mid['status']!r}"
    report_verification(mvr["id"], "PASS", mvr["version"])
    report_verification(edu["id"], "PASS", edu["version"])
    final = validate_success(api.get_order(order["id"],
                                            make_recruiter_headers("rec-carol")), 200)
    assert final["status"] == "COMPLETE", \
        f"after three REPORTS, order must be COMPLETE, got {final['status']!r}"
    assert final["overall_result"] == "CLEAR", \
        f"all-PASS order must be CLEAR, got {final['overall_result']!r}"


def test_third_report_cascades_order_to_complete_and_auto_creates_adverse_action(api):
    """The third Verification REPORT triggers an order posture recompute:
    PENDING/IN_REVIEW -> COMPLETE with overall_result=CONSIDER (any FAIL),
    and that completion atomically auto-creates the AdverseAction row in
    PRE_ADVERSE_SENT.

    PRD §3.4: "Whenever the order's status recompute lands on `COMPLETE`
    with `overall_result` equal to `CONSIDER` — whether via the `IN_REVIEW`
    to `COMPLETE` transition or via the atomic-burst `PENDING` to
    `COMPLETE` transition — the cascade also auto-creates a single
    `AdverseAction` row in `PRE_ADVERSE_SENT`, with `pre_adverse_sent_at`
    stamped from `current_utc` and `earliest_final_at` computed (per §3.5).
    This is the bridge from order completion to the adverse-action
    workflow; it fires exactly once."

    Design: Difficulty/transitive_cascade/third_verification_report_cascades_to_order_complete_to_adverse_action_create
    """
    (jur, applicant, app, consent, order,
     crim, mvr, edu) = order_with_three_pending_verifications(
         state_code="GA", recruiter_id="rec-eve",
    )
    # Report PASSes on MVR + EDUCATION → order is IN_REVIEW.
    report_verification(mvr["id"], "PASS", mvr["version"])
    report_verification(edu["id"], "PASS", edu["version"])
    pre = validate_success(api.get_order(order["id"],
                                          make_recruiter_headers("rec-eve")), 200)
    assert pre["status"] == "IN_REVIEW", \
        f"after two REPORTs, order must be IN_REVIEW, got {pre['status']!r}"
    pre_aa_list = validate_success(
        api.list_order_adverse_action(order["id"], CO), 200,
    )
    # Before the third report, no AdverseAction exists.
    assert isinstance(pre_aa_list, list) and len(pre_aa_list) == 0, \
        f"before COMPLETE+CONSIDER, no AdverseAction should exist, got {pre_aa_list!r}"
    # Third REPORT with FAIL → cascade COMPLETE + CONSIDER + AA auto-create.
    report_verification(crim["id"], "FAIL", crim["version"],
                        report_payload={"hits": 1})
    post = validate_success(api.get_order(order["id"],
                                           make_recruiter_headers("rec-eve")), 200)
    assert post["status"] == "COMPLETE", \
        f"after third REPORT, order must be COMPLETE, got {post['status']!r}"
    assert post["overall_result"] == "CONSIDER", \
        f"any-FAIL order must be CONSIDER, got {post['overall_result']!r}"
    aa_list = validate_success(api.list_order_adverse_action(order["id"], CO), 200)
    assert isinstance(aa_list, list) and len(aa_list) == 1, \
        f"COMPLETE+CONSIDER must auto-create exactly one AdverseAction, got {aa_list!r}"
    assert aa_list[0]["status"] == "PRE_ADVERSE_SENT", \
        f"auto-created AdverseAction must start in PRE_ADVERSE_SENT, got {aa_list[0]['status']!r}"
