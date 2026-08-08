"""Case investigative lifecycle: the revision loop and review preconditions."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_investigation_case,
    create_pending_review_case,
    add_evidence,
    submit_review,
    adjudicate,
    assert_case,
)

SUPERVISOR = TEST_USERS["supervisor_headers"]
INVESTIGATOR = TEST_USERS["investigator_headers"]


def test_case_return_then_resubmit_reaches_pending_review(api):
    """PRD 3.2: "`RETURN` sends the case back from `PENDING_REVIEW` to `INVESTIGATION`
    for more work (the revision loop)."
    PRD 3.2: "Submitting the case for review advances it from `INVESTIGATION` to
    `PENDING_REVIEW`, but only if at least one evidence item exists for the case; a
    submit-review attempt against a case with zero evidence is rejected with
    `ERR_NO_EVIDENCE` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/case_review_return_cycle
    """
    ctx = create_pending_review_case(api)
    case_id = ctx["case"]["id"]
    adjudicate(api, case_id, "RETURN")
    resubmitted = submit_review(api, case_id)
    assert_case(resubmitted)
    assert resubmitted["status"] == "PENDING_REVIEW", (
        f"expected PENDING_REVIEW after resubmit, got {resubmitted['status']}"
    )


def test_case_return_moves_back_to_investigation(api):
    """PRD 3.2: "`RETURN` sends the case back from `PENDING_REVIEW` to `INVESTIGATION`
    for more work (the revision loop)."

    Design: Difficulty/non_linear_state_machine/case_review_return_cycle
    """
    ctx = create_pending_review_case(api)
    case_id = ctx["case"]["id"]
    returned = validate_success(api.adjudicate_case(case_id, {"decision": "RETURN"}, SUPERVISOR))
    assert returned["status"] == "INVESTIGATION", (
        f"expected INVESTIGATION after RETURN, got {returned['status']}"
    )


def test_submit_review_from_open_rejected(api):
    """PRD 2.9: "whether the target is in a valid non-terminal state for the requested
    transition (`ERR_INVALID_STATE`, HTTP 409)."
    PRD 3.2: "Submitting the case for review advances it from `INVESTIGATION` to
    `PENDING_REVIEW`, but only if at least one evidence item exists for the case; a
    submit-review attempt against a case with zero evidence is rejected with
    `ERR_NO_EVIDENCE` (HTTP 409)."

    Design: Corner/state_machines/submit_review_from_open_returns_invalid_state
    """
    from test_helpers import create_open_case
    ctx = create_open_case(api)
    resp = api.submit_review(ctx["case"]["id"], INVESTIGATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_submit_review_with_no_evidence_rejected(api):
    """PRD 3.2: "Submitting the case for review advances it from `INVESTIGATION` to
    `PENDING_REVIEW`, but only if at least one evidence item exists for the case; a
    submit-review attempt against a case with zero evidence is rejected with
    `ERR_NO_EVIDENCE` (HTTP 409)."

    Design: Corner/validations/no_evidence_submit_review
    """
    ctx = create_investigation_case(api)
    resp = api.submit_review(ctx["case"]["id"], INVESTIGATOR)
    validate_error(resp, ApiErrorId.ERR_NO_EVIDENCE.value)
