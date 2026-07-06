"""Compliance review lifecycle: resubmit cycle, clear gating, and the
block-and-revert cascade.

Design queues:
  A (Difficulty): non_linear_state_machine/compliance_review_resubmit_cycle,
                  transitive_cascade/compliance_reject_blocks_event_reverts_assignment_depth3,
                  cross_entity_state_dependency/assignment_confirm_requires_event_cleared
  B (Corner): compliance clear validations; clear-from-draft invalid state
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_draft_event, create_cleared_event, create_bartender,
    add_assignment, add_confirmed_assignment,
    TEST_USERS, ApiErrorId,
    create_compliance_review_payload,
)

COORD = TEST_USERS["coordinator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine / compliance_review_resubmit_cycle
# ---------------------------------------------------------------------------
def test_resubmit_after_changes_increments_revision_round(api):
    """PRD §3.4: "the coordinator resubmits, advancing `CHANGES_REQUESTED →
    SUBMITTED` and incrementing `revision_round` by 1 on each resubmission."

    Design: Difficulty/non_linear_state_machine/compliance_review_resubmit_cycle
    """
    bundle = create_draft_event(api)
    ev_id = bundle["event"]["id"]
    review = get_success_data(api.create_compliance_review(
        ev_id, create_compliance_review_payload(liquor_liability_insurance_verified=False), COORD))
    rid = review["id"]
    get_success_data(api.submit_review(rid, {}, COORD))
    get_success_data(api.request_changes_review(rid, {"reviewer_notes": "insurance cert missing"}, OFFICER))
    get_success_data(api.submit_review(rid, {"liquor_liability_insurance_verified": True}, COORD))
    cleared = validate_success(api.clear_review(rid, {}, OFFICER))
    assert cleared["status"] == "CLEARED"
    assert cleared["revision_round"] == 1


def test_resubmit_cycle_lifts_event_posture_to_cleared(api):
    """PRD §3.4: "A successful clear sets the review's `status` to `CLEARED` and
    lifts the parent event's `compliance_posture` to `CLEARED`."

    Design: Difficulty/non_linear_state_machine/compliance_review_resubmit_cycle
    """
    bundle = create_draft_event(api)
    ev_id = bundle["event"]["id"]
    review = get_success_data(api.create_compliance_review(
        ev_id, create_compliance_review_payload(liquor_liability_insurance_verified=False), COORD))
    rid = review["id"]
    get_success_data(api.submit_review(rid, {}, COORD))
    get_success_data(api.request_changes_review(rid, {"reviewer_notes": "insurance cert missing"}, OFFICER))
    get_success_data(api.submit_review(rid, {"liquor_liability_insurance_verified": True}, COORD))
    get_success_data(api.clear_review(rid, {}, OFFICER))
    ev = get_success_data(api.get_event(ev_id, COORD))
    assert ev["compliance_posture"] == "CLEARED"


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade / compliance_reject_blocks_event_reverts_assignment_depth3
# ---------------------------------------------------------------------------
def _cleared_event_with_confirmed_lead(api):
    bundle = create_cleared_event(api)
    ev_id = bundle["event"]["id"]
    bartender = create_bartender(api)
    asg = add_confirmed_assignment(api, ev_id, bartender["id"], role_on_event="LEAD")
    return bundle, asg


def test_request_changes_blocks_event_posture(api):
    """PRD §3.4: "When it fires, three effects cascade: the parent event's
    compliance_posture moves to BLOCKED; because the event is now blocked, every
    child assignment currently in CONFIRMED reverts to PROPOSED; and each
    reverted assignment's bartender has their reliability scores recomputed".

    Design: Difficulty/transitive_cascade/compliance_reject_blocks_event_reverts_assignment_depth3
    """
    bundle, asg = _cleared_event_with_confirmed_lead(api)
    rid = bundle["review"]["id"]
    ev_id = bundle["event"]["id"]
    changed = validate_success(api.request_changes_review(
        rid, {"reviewer_notes": "re-inspection: insurance lapsed"}, OFFICER))
    assert changed["status"] == "CHANGES_REQUESTED"
    assert get_success_data(api.get_event(ev_id, COORD))["compliance_posture"] == "BLOCKED"


def test_request_changes_reverts_confirmed_assignment_to_proposed(api):
    """PRD §3.4: "because the event is now blocked, every child assignment
    currently in CONFIRMED reverts to PROPOSED".

    Design: Difficulty/transitive_cascade/compliance_reject_blocks_event_reverts_assignment_depth3
    """
    bundle, asg = _cleared_event_with_confirmed_lead(api)
    rid = bundle["review"]["id"]
    get_success_data(api.request_changes_review(
        rid, {"reviewer_notes": "re-inspection: insurance lapsed"}, OFFICER))
    reverted = get_success_data(api.get_assignment(asg["id"], COORD))
    assert reverted["status"] == "PROPOSED"


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency / assignment_confirm_requires_event_cleared
# ---------------------------------------------------------------------------
def test_confirm_assignment_while_posture_pending_rejected(api):
    """PRD §3.5: "a coordinator confirms a proposed assignment, advancing
    PROPOSED → CONFIRMED, but only when the parent event's compliance_posture is
    CLEARED; a confirm attempted while posture is not cleared is rejected with
    ERR_COMPLIANCE_NOT_CLEARED (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/assignment_confirm_requires_event_cleared
    """
    bundle = create_draft_event(api)  # posture stays PENDING (no cleared review)
    bartender = create_bartender(api)
    asg = add_assignment(api, bundle["event"]["id"], bartender["id"], role_on_event="BACK")
    resp = api.confirm_assignment(asg["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_COMPLIANCE_NOT_CLEARED.value)


def test_confirm_assignment_succeeds_once_posture_cleared(api):
    """PRD §3.5: "confirms a proposed assignment, advancing `PROPOSED →
    CONFIRMED`, but only when the parent event's `compliance_posture` is
    `CLEARED`; a confirm attempted while posture is not cleared is rejected with
    `ERR_COMPLIANCE_NOT_CLEARED` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/assignment_confirm_requires_event_cleared
    """
    bundle = create_cleared_event(api)
    bartender = create_bartender(api)
    asg = add_assignment(api, bundle["event"]["id"], bartender["id"], role_on_event="BACK")
    confirmed = validate_success(api.confirm_assignment(asg["id"], COORD))
    assert confirmed["status"] == "CONFIRMED"


# ---------------------------------------------------------------------------
# Queue B — validations: clear gating
# ---------------------------------------------------------------------------
def _submitted_review(api, **review_overrides):
    bundle = create_draft_event(api)
    ev_id = bundle["event"]["id"]
    review = get_success_data(api.create_compliance_review(
        ev_id, create_compliance_review_payload(**review_overrides), COORD))
    get_success_data(api.submit_review(review["id"], {}, COORD))
    return review


def test_clear_rejected_when_abc_model_not_host_no_sale(api):
    """PRD §3.4: "If abc_model is not HOST_NO_SALE, clearing fails with
    ERR_ABC_MODEL_INVALID (HTTP 422); if the insurance is not verified, it fails
    with ERR_INSURANCE_NOT_VERIFIED (HTTP 422)".

    Design: Corner/validations/compliance_clear_abc_model_invalid
    """
    review = _submitted_review(api, abc_model="CASH_BAR")
    resp = api.clear_review(review["id"], {}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_ABC_MODEL_INVALID.value)


def test_clear_rejected_when_insurance_not_verified(api):
    """PRD §3.4: "if the insurance is not verified, it fails with
    ERR_INSURANCE_NOT_VERIFIED (HTTP 422); if either the host attestation or the
    server-certification attestation is false, it fails with
    ERR_HOST_ATTESTATION_MISSING (HTTP 422)."

    Design: Corner/validations/compliance_clear_insurance_not_verified
    """
    review = _submitted_review(api, liquor_liability_insurance_verified=False)
    resp = api.clear_review(review["id"], {}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_INSURANCE_NOT_VERIFIED.value)


def test_clear_rejected_when_host_attestation_missing(api):
    """PRD §3.4: "if either the host attestation or the server-certification
    attestation is false, it fails with ERR_HOST_ATTESTATION_MISSING (HTTP
    422)."

    Design: Corner/errors/error_host_attestation_missing_triggerable
    """
    review = _submitted_review(api, host_alcohol_ownership_attested=False)
    resp = api.clear_review(review["id"], {}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_HOST_ATTESTATION_MISSING.value)


def test_clear_from_draft_is_invalid_state(api):
    """PRD §2.7: "the target resource is in a status from which the requested
    transition is defined, else ERR_INVALID_STATE (HTTP 409). Terminal states
    reject every transition, and re-issuing a transition already applied is
    likewise an invalid-state rejection."

    Design: Corner/state_machines/compliance_clear_from_draft_invalid_state
    """
    bundle = create_draft_event(api)
    review = get_success_data(api.create_compliance_review(
        bundle["event"]["id"], create_compliance_review_payload(), COORD))
    # Never submitted — still DRAFT.
    resp = api.clear_review(review["id"], {}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
