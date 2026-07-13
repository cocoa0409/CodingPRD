"""Non-linear state machines: the attorney-review revision/re-review cycles, plus
terminal-lockdown and invalid-transition guards on subscriptions, documents, and
executors.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    make_active_subscription, add_beneficiary, generate_document, execute_document,
    setup_document_in_attorney_review, setup_review_changes_requested_resubmitted,
    ATTORNEY, NOTARY,
)


# ─── Difficulty: non_linear_state_machine / document_generated_review_cycle ─
def test_request_changes_returns_document_to_generated(api):
    """PRD §3.7: "From `IN_REVIEW`, a `REQUEST_CHANGES` decision moves the review to
    `CHANGES_REQUESTED`, stores the supplied `notes`, and drives the owning document
    back from `IN_REVIEW` to `GENERATED` so the member can revise it — this is the
    revision loop `GENERATED → IN_REVIEW → GENERATED`."

    Design: Difficulty/non_linear_state_machine/document_generated_review_cycle
    """
    ctx = setup_document_in_attorney_review()
    review, doc, hdr = ctx["review"], ctx["document"], ctx["headers"]
    validate_success(api.review_decision(
        review["id"], {"action": "REQUEST_CHANGES", "notes": "Fix clause 3"}, ATTORNEY), 200)
    doc_after = validate_success(api.get_document(doc["id"], hdr), 200)
    assert doc_after["status"] == "GENERATED"


def test_request_changes_sets_review_changes_requested(api):
    """PRD §3.7: "From `IN_REVIEW`, a `REQUEST_CHANGES` decision moves the review to
    `CHANGES_REQUESTED`, stores the supplied `notes`, and drives the owning document
    back from `IN_REVIEW` to `GENERATED` so the member can revise it".

    Design: Difficulty/non_linear_state_machine/document_generated_review_cycle
    """
    ctx = setup_document_in_attorney_review()
    review = ctx["review"]
    updated = validate_success(api.review_decision(
        review["id"], {"action": "REQUEST_CHANGES", "notes": "Fix clause 3"}, ATTORNEY), 200)
    assert updated["status"] == "CHANGES_REQUESTED"


# ─── Difficulty: non_linear_state_machine / attorney_review_changes_cycle ─
def test_rereview_returns_review_to_in_review(api):
    """PRD §3.7: "the attorney may issue `START_REVIEW` again on a `CHANGES_REQUESTED`
    review to return it to `IN_REVIEW`; that re-review is permitted only when the
    owning document is itself back in `IN_REVIEW`, forming the re-review loop
    `IN_REVIEW → CHANGES_REQUESTED → IN_REVIEW`."

    Design: Difficulty/non_linear_state_machine/attorney_review_changes_cycle
    """
    ctx = setup_review_changes_requested_resubmitted()
    review = ctx["review"]
    updated = validate_success(api.review_decision(
        review["id"], {"action": "START_REVIEW"}, ATTORNEY), 200)
    assert updated["status"] == "IN_REVIEW"


def test_rereview_keeps_document_in_review(api):
    """PRD §3.7: "that re-review is permitted only when the owning document is itself
    back in `IN_REVIEW`, forming the re-review loop
    `IN_REVIEW → CHANGES_REQUESTED → IN_REVIEW`." When the member re-submits the
    revised document "(taking it back to `IN_REVIEW`)".

    Design: Difficulty/non_linear_state_machine/attorney_review_changes_cycle
    """
    ctx = setup_review_changes_requested_resubmitted()
    review, doc, hdr = ctx["review"], ctx["document"], ctx["headers"]
    validate_success(api.review_decision(review["id"], {"action": "START_REVIEW"}, ATTORNEY), 200)
    doc_after = validate_success(api.get_document(doc["id"], hdr), 200)
    assert doc_after["status"] == "IN_REVIEW"


# ─── Corner: state_machines / cancel_already_cancelled_returns_terminal ──
def test_cancel_already_cancelled_subscription_returns_terminal(api):
    """PRD §3.4: "A `Member` may cancel a subscription that is in `PENDING_PAYMENT`,
    `ACTIVE`, or `SUSPENDED` status; attempting to cancel a subscription already in a
    terminal state (`CANCELLED` or `EXPIRED`) is rejected with `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/cancel_already_cancelled_returns_terminal
    """
    member, sub, hdr = make_active_subscription()
    validate_success(api.cancel_subscription(sub["id"], hdr), 200)
    res = api.cancel_subscription(sub["id"], hdr)
    validate_error(res, "ERR_ALREADY_TERMINAL")
    after = validate_success(api.get_subscription(sub["id"], hdr), 200)
    assert after["status"] == "CANCELLED"


# ─── Corner: state_machines / execute_from_executed_returns_invalid_state ─
def test_execute_already_executed_document_returns_invalid_state(api):
    """PRD §3.8: "Execution is legal from two states: a `GENERATED` document that never
    went through attorney review, or a `PENDING_EXECUTION` document that an attorney has
    approved; from any other state the request is rejected with `ERR_INVALID_STATE`, and
    a terminal document yields `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/execute_from_executed_returns_invalid_state
    """
    member, sub, hdr = make_active_subscription()
    add_beneficiary(sub["id"], hdr, allocation_pct=100)
    _q, doc = generate_document(sub["id"], hdr, "WILL", "CA")
    execute_document(doc["id"], witnesses_count=2)
    res = api.execute_document(doc["id"], {"witnesses_count": 2}, NOTARY)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_document(doc["id"], hdr), 200)
    assert after["status"] == "EXECUTED"


# ─── Corner: state_machines / respond_executor_twice_returns_invalid_state ─
def test_respond_to_already_accepted_executor_returns_invalid_state(api):
    """PRD §3.10: "The member records the executor's response through the respond
    operation, whose `decision` is either `ACCEPT`, moving the executor from
    `NOMINATED` to `ACCEPTED`, or `DECLINE`, moving it from `NOMINATED` to the terminal
    `DECLINED` status." PRD §2.10: "(5) that the target resource is in a state from
    which the requested transition is legal (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/respond_executor_twice_returns_invalid_state
    """
    member, sub, hdr = make_active_subscription()
    ex = get_success_data(api.create_executor({
        "subscription_id": sub["id"], "full_name": "Ex One",
        "email": "ex@example.com", "priority_order": 1}, hdr))
    validate_success(api.respond_executor(ex["id"], {"decision": "ACCEPT"}, hdr), 200)
    res = api.respond_executor(ex["id"], {"decision": "ACCEPT"}, hdr)
    validate_error(res, "ERR_INVALID_STATE")
    after_list, _meta = validate_paginated(api.list_subscription_executors(sub["id"], hdr))
    accepted = [e for e in after_list if e["id"] == ex["id"]][0]
    assert accepted["status"] == "ACCEPTED"
