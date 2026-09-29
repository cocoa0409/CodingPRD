"""
Owner reimbursement intake: the bounded document-request cycle, a state machine
whose two-round cap is not a status but a counter.
"""

from test_helpers import (
    ApiErrorId,
    ReimbursementStatus,
    factories as f,
    fixtures as fx,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.test_users import CLAIMS_AUDITOR, OPERATIONS_MANAGER


def _reimbursement_after_two_document_rounds(api):
    """
    A pre-recall invoice taken twice around the request-and-re-key loop, leaving
    the request back in SUBMITTED with `document_round` at its cap.
    """
    state = fx.filed_campaign(api)
    request = fx.submit_reimbursement(
        api,
        state["campaign_id"],
        state["vehicle_id"],
        invoice_date="2026-07-15",
        invoice_amount=412.75,
        labor_hours_claimed=1.30,
        parts_amount=62.00,
        towing_amount=0.00,
    )
    state["reimbursement_id"] = request["id"]
    state["intake"] = request

    fx.request_documents(api, request["id"])
    fx.resubmit_reimbursement(api, request["id"])
    fx.request_documents(api, request["id"])
    state["reimbursement"] = fx.resubmit_reimbursement(api, request["id"])
    return state


def test_third_document_request_is_refused_at_the_two_round_cap(api):
    """
    The request is in SUBMITTED and so passes the status gate, but
    `document_round` has already reached 2, so a third round is refused.

    PRD §3.9: "That `SUBMITTED` to `DOCUMENTS_REQUESTED` and back cycle is capped
    at **two rounds**: a document request is only permitted while
    `document_round` is still below 2, and a third attempt is rejected with
    `ERR_MAX_DOCUMENT_ROUNDS_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/reimbursement_document_request_cycle_bounded_at_two_rounds
    """
    state = _reimbursement_after_two_document_rounds(api)
    assert state["reimbursement"]["status"] == ReimbursementStatus.SUBMITTED

    response = api.request_reimbursement_documents(
        state["reimbursement_id"], f.request_documents_payload(), CLAIMS_AUDITOR
    )
    validate_error(response, ApiErrorId.MAX_DOCUMENT_ROUNDS_EXCEEDED, 409)

    request = get_success_data(
        api.get_owner_reimbursement(state["reimbursement_id"], CLAIMS_AUDITOR)
    )
    assert request["document_round"] == 2
    assert request["status"] == ReimbursementStatus.SUBMITTED
    assert request["documentation_complete"] is True


def test_each_accepted_round_increments_the_counter_and_the_re_key_clears_it(api):
    """
    Intake starts at round 0 with a complete packet; each request drives the row to
    DOCUMENTS_REQUESTED with the packet marked incomplete, and each re-key forces
    it complete again on the way back to SUBMITTED.

    PRD §3.9: "A request starts in status `SUBMITTED` with `document_round` 0,
    `labor_operation_id`, `approved_amount_cents`, `requested_items` and
    `denial_reason` all unset."

    PRD §3.9: "A `ClaimsAuditor` may ask the owner for missing paperwork by
    supplying `requested_items`, which requires the request to be in status
    `SUBMITTED`, moves it to `DOCUMENTS_REQUESTED`, increments `document_round` by
    1, sets `documentation_complete` to false, and increments the request's
    `version` by 1."

    Design: Difficulty/non_linear_state_machine/reimbursement_document_request_cycle_bounded_at_two_rounds
    """
    state = fx.filed_campaign(api)
    request = validate_success(
        api.create_owner_reimbursement(
            f.owner_reimbursement_payload(
                state["campaign_id"],
                state["vehicle_id"],
                invoice_date="2026-07-15",
                invoice_amount=412.75,
                labor_hours_claimed=1.30,
                parts_amount=62.00,
                towing_amount=0.00,
            ),
            OPERATIONS_MANAGER,
        ),
        201,
    )
    assert request["document_round"] == 0
    assert request["status"] == ReimbursementStatus.SUBMITTED
    assert request["documentation_complete"] is True
    assert request["approved_amount_cents"] is None
    assert request["labor_operation_id"] is None

    first_request = fx.request_documents(api, request["id"])
    assert first_request["status"] == ReimbursementStatus.DOCUMENTS_REQUESTED
    assert first_request["document_round"] == 1
    assert first_request["documentation_complete"] is False

    first_rekey = fx.resubmit_reimbursement(api, request["id"])
    assert first_rekey["status"] == ReimbursementStatus.SUBMITTED
    assert first_rekey["document_round"] == 1
    assert first_rekey["documentation_complete"] is True

    second_request = fx.request_documents(api, request["id"])
    assert second_request["status"] == ReimbursementStatus.DOCUMENTS_REQUESTED
    assert second_request["document_round"] == 2

    second_rekey = fx.resubmit_reimbursement(api, request["id"])
    assert second_rekey["status"] == ReimbursementStatus.SUBMITTED
    assert second_rekey["document_round"] == 2
    assert second_rekey["documentation_complete"] is True
