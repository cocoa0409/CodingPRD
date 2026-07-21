"""Design consult cyclic review/revision loop (PRD §3.6)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS, create_account,
)

SM = TEST_USERS["sm_headers"]


def _new_consult(api, business_name="DesignerCo"):
    acct = create_account(api, business_name=business_name, contact_email="d@x.com")
    resp = api.create_design_consult(
        {"trade_account_id": acct["id"], "room_type": "KITCHEN", "fee_cents": 15000}, SM
    )
    return validate_success(resp, 201)


def test_revision_cycle_reaches_approved_with_two_revisions(api):
    """PRD §3.6: "From `IN_REVIEW` the designer may request a revision, which moves it to
    `REVISION` and increments `revision_count` by one; re-submitting after revising loops a
    `REVISION` consult back to `IN_REVIEW`. This review-and-revise cycle may repeat any
    number of times."
    PRD §3.6: "Only a store manager may approve a consult, and only from `IN_REVIEW`, moving
    it to the terminal `APPROVED` state."

    Design: Difficulty/non_linear_state_machine/design_consult_revision_cycle
    """
    dc = _new_consult(api)
    api.submit_review_design_consult(dc["id"], SM)      # -> IN_REVIEW
    api.request_revision_design_consult(dc["id"], SM)   # -> REVISION (count 1)
    api.submit_review_design_consult(dc["id"], SM)      # -> IN_REVIEW
    api.request_revision_design_consult(dc["id"], SM)   # -> REVISION (count 2)
    api.submit_review_design_consult(dc["id"], SM)      # -> IN_REVIEW
    approved = validate_success(api.approve_design_consult(dc["id"], SM), 200)
    assert approved["status"] == "APPROVED"
    assert approved["revision_count"] == 2


def test_each_request_revision_increments_revision_count(api):
    """PRD §3.6: "From `IN_REVIEW` the designer may request a revision, which moves it to
    `REVISION` and increments `revision_count` by one; re-submitting after revising loops a
    `REVISION` consult back to `IN_REVIEW`. This review-and-revise cycle may repeat any
    number of times."

    Design: Difficulty/non_linear_state_machine/design_consult_revision_cycle
    """
    dc = _new_consult(api, business_name="DesignerCo2")
    api.submit_review_design_consult(dc["id"], SM)
    first = validate_success(api.request_revision_design_consult(dc["id"], SM), 200)
    assert first["status"] == "REVISION"
    assert first["revision_count"] == 1
    api.submit_review_design_consult(dc["id"], SM)
    second = validate_success(api.request_revision_design_consult(dc["id"], SM), 200)
    assert second["status"] == "REVISION"
    assert second["revision_count"] == 2


def test_approve_from_requested_returns_invalid_state(api):
    """PRD §3.6: "Only a store manager may approve a consult, and only from `IN_REVIEW`,
    moving it to the terminal `APPROVED` state. Any of these moves attempted from the wrong
    state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/design_consult_approve_from_requested_returns_invalid_state
    """
    acct = create_account(api, business_name="DC2", contact_email="dc2@x.com")
    dc = validate_success(
        api.create_design_consult({"trade_account_id": acct["id"], "room_type": "BATH"}, SM), 201
    )
    resp = api.approve_design_consult(dc["id"], SM)  # still REQUESTED
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
