"""Cross-entity state gating: order transitions gated by child task states,
estoppel currency, and delivery creation gated by the order's state."""
from test_helpers import (
    ApiErrorId,
    ESTOPPEL_PAYOFF,
    FINDINGS_EMPTY,
    UTILITY_ONLY_DEPARTMENTS,
    complete_task,
    get_order,
    make_qa_reviewer_headers,
    make_research_analyst_headers,
    place_estoppel,
    receive_estoppel,
    record_findings,
    setup_identified_order,
    setup_in_verification,
    submit_order,
    validate_error,
)

ANALYST = make_research_analyst_headers("analyst_1")
QA = make_qa_reviewer_headers("qa_1")


def test_submit_with_pending_task_blocked(api):
    """PRD 3.6: "Once every research task of an order is `COMPLETED` or
    `UNABLE_TO_REACH` — any task still `PENDING` or `IN_PROGRESS` blocks
    submission with `ERR_TASKS_OUTSTANDING` — and every estoppel order is
    `RECEIVED` (anything else blocks with `ERR_ESTOPPEL_NOT_CURRENT`) with a
    `valid_through` on or after the `closing_date` (a stale letter blocks with
    `ERR_ESTOPPEL_STALE_FOR_CLOSING`), a `ResearchAnalyst` submits the order for
    verification, moving it to `VERIFICATION` and stamping
    `research_completed_by_user_id` with the caller's identity."

    Design: Difficulty/cross_entity_state_dependency/submit_blocked_by_pending_task
    """
    ctx = setup_identified_order(
        "P-T1", departments=UTILITY_ONLY_DEPARTMENTS, with_association=False
    )
    assert ctx["tasks"][0]["status"] == "PENDING"

    response = api.submit_for_verification(ctx["order"]["id"], ANALYST)
    validate_error(response, ApiErrorId.ERR_TASKS_OUTSTANDING.value)
    assert response.status_code == 409
    assert get_order(ctx["order"]["id"])["status"] == "RESEARCH_IN_PROGRESS"


def test_submit_after_task_completion_accepted(api):
    """PRD 3.6: "Once every research task of an order is `COMPLETED` or
    `UNABLE_TO_REACH` — any task still `PENDING` or `IN_PROGRESS` blocks
    submission with `ERR_TASKS_OUTSTANDING` — and every estoppel order is
    `RECEIVED` (anything else blocks with `ERR_ESTOPPEL_NOT_CURRENT`) with a
    `valid_through` on or after the `closing_date` (a stale letter blocks with
    `ERR_ESTOPPEL_STALE_FOR_CLOSING`), a `ResearchAnalyst` submits the order for
    verification, moving it to `VERIFICATION` and stamping
    `research_completed_by_user_id` with the caller's identity."

    Design: Difficulty/cross_entity_state_dependency/submit_blocked_by_pending_task
    """
    ctx = setup_identified_order(
        "P-T2", departments=UTILITY_ONLY_DEPARTMENTS, with_association=False
    )
    task = ctx["tasks"][0]
    record_findings(task, FINDINGS_EMPTY)
    complete_task(task["id"])

    submitted = submit_order(ctx["order"]["id"])
    assert submitted["status"] == "VERIFICATION"
    assert submitted["research_completed_by_user_id"] == "analyst_1"


def test_submit_with_unreceived_estoppel_blocked(api):
    """PRD 3.6: "Once every research task of an order is `COMPLETED` or
    `UNABLE_TO_REACH` — any task still `PENDING` or `IN_PROGRESS` blocks
    submission with `ERR_TASKS_OUTSTANDING` — and every estoppel order is
    `RECEIVED` (anything else blocks with `ERR_ESTOPPEL_NOT_CURRENT`) with a
    `valid_through` on or after the `closing_date` (a stale letter blocks with
    `ERR_ESTOPPEL_STALE_FOR_CLOSING`), a `ResearchAnalyst` submits the order for
    verification, moving it to `VERIFICATION` and stamping
    `research_completed_by_user_id` with the caller's identity."

    Design: Difficulty/cross_entity_state_dependency/deliver_gated_by_order_state_and_estoppel_gate
    """
    ctx = setup_identified_order("P-G1", departments=UTILITY_ONLY_DEPARTMENTS)
    task = ctx["tasks"][0]
    record_findings(task, FINDINGS_EMPTY)
    complete_task(task["id"])
    estoppel = ctx["estoppels"][0]
    place_estoppel(estoppel["id"], 10000)  # ORDERED, never received.

    response = api.submit_for_verification(ctx["order"]["id"], ANALYST)
    validate_error(response, ApiErrorId.ERR_ESTOPPEL_NOT_CURRENT.value)
    assert response.status_code == 409


def test_delivery_creation_before_ready_state_blocked(api):
    """PRD 3.6: "With the order `READY_FOR_DELIVERY`, a `QAReviewer` creates a
    delivery for it; the creation is refused with `ERR_ORDER_NOT_DELIVERABLE`
    when the order is in any other state and with `ERR_DELIVERY_ALREADY_PENDING`
    when a `READY` delivery already exists for the order."

    Design: Difficulty/cross_entity_state_dependency/deliver_gated_by_order_state_and_estoppel_gate
    """
    # Order reaches VERIFICATION (tasks complete, estoppel received) but is not
    # yet READY_FOR_DELIVERY, so delivery creation is refused.
    ctx = setup_in_verification("P-G2", departments=UTILITY_ONLY_DEPARTMENTS)
    assert ctx["order"]["status"] == "VERIFICATION"

    response = api.create_delivery({"search_order_id": ctx["order"]["id"]}, QA)
    validate_error(response, ApiErrorId.ERR_ORDER_NOT_DELIVERABLE.value)
    assert response.status_code == 409
