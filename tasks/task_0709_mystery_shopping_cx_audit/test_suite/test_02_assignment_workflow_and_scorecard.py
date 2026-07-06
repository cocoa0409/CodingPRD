"""Assignment workflow and scorecard dimensions: the revision cycle, the parallel
audit/fraud state axes on a scorecard, initial state, and request-revision's
evidence reset side effect.

Covers difficulty rule non_linear_state_machine and the corner state_machine
instances.
"""
from test_helpers import validate_success, fixtures
from test_helpers.test_users import (
    make_shopper_headers,
    make_qa_validator_headers,
    make_client_manager_headers,
)


def _card(sc):
    return sc[0] if isinstance(sc, list) else sc


# ---------------------------------------------------------------------------
# non_linear_state_machine / assignment_revision_cycle_returns_to_in_field
# ---------------------------------------------------------------------------
def test_request_revision_then_resume_cycles_back_to_in_field(api):
    """PRD 3.6: "From REVISION_REQUESTED the shopper resumes, moving the assignment
    back to IN_FIELD; resuming requires the assignment to be REVISION_REQUESTED, the
    acting shopper to be its own shopper, and the clock to be at or before due_at.
    This forms the revision cycle SUBMITTED -> REVISION_REQUESTED -> IN_FIELD ->
    SUBMITTED."

    Design: Difficulty/non_linear_state_machine/assignment_revision_cycle_returns_to_in_field
    """
    cat = fixtures.setup_submitted_assignment(
        due_at="2026-06-25T00:00:00Z", section_scores_json={"greeting": 88},
    )
    aid, sid = cat["assignment"]["id"], cat["shopper"]["id"]
    after_rev = validate_success(api.request_revision(aid, make_qa_validator_headers()))
    assert after_rev["status"] == "REVISION_REQUESTED", (
        f"expected REVISION_REQUESTED after request-revision, got {after_rev['status']}"
    )
    after_resume = validate_success(api.resume_assignment(aid, make_shopper_headers(sid)))
    assert after_resume["status"] == "IN_FIELD", (
        f"expected IN_FIELD after resume, got {after_resume['status']}"
    )


def test_submission_count_increments_on_revision_resubmit(api):
    """PRD 3.5: "On a successful submission the platform increments submission_count
    by 1 (this counts every entry into SUBMITTED, including revision resubmissions),
    sets claimed_out_of_pocket_cents to the sum of receipt_amount_cents over the
    APPROVED RECEIPT items, computes the provisional reimbursement, and computes the
    estimated score."

    Design: Difficulty/non_linear_state_machine/assignment_revision_cycle_returns_to_in_field
    """
    cat = fixtures.setup_submitted_assignment(
        due_at="2026-06-25T00:00:00Z", section_scores_json={"greeting": 88},
    )
    aid, sid = cat["assignment"]["id"], cat["shopper"]["id"]
    assert cat["assignment"]["submission_count"] == 1
    validate_success(api.request_revision(aid, make_qa_validator_headers()))
    validate_success(api.resume_assignment(aid, make_shopper_headers(sid)))
    # request-revision reset the APPROVED photo to PENDING; re-approve before resubmit.
    ev = validate_success(api.list_evidence(aid, make_qa_validator_headers()))
    ev_id = ev[0]["id"] if isinstance(ev, list) else ev["id"]
    validate_success(api.review_evidence(ev_id, {"decision": "APPROVE"}, make_qa_validator_headers()))
    resubmitted = validate_success(api.submit_assignment(aid, make_shopper_headers(sid)))
    assert resubmitted["submission_count"] == 2, (
        f"submission_count expected 2 after second submit, got {resubmitted['submission_count']}"
    )


# ---------------------------------------------------------------------------
# non_linear_state_machine / scorecard_parallel_audit_and_fraud_dimensions...
# ---------------------------------------------------------------------------
def test_fraud_hold_leaves_audit_status_draft(api):
    """PRD 3.5: "A new scorecard begins with audit_status of DRAFT and fraud_status
    of UNCHECKED; these two dimensions evolve independently."
    PRD 3.6: "A fraud check with a hold decision moves fraud_status from UNCHECKED to
    FRAUD_HOLD; a clear decision moves fraud_status from UNCHECKED to CLEARED, or
    from FRAUD_HOLD to CLEARED. A FRAUD_HOLD blocks validation until it is cleared."

    Design: Difficulty/non_linear_state_machine/scorecard_parallel_audit_and_fraud_dimensions_evolve_independently
    """
    cat = fixtures.setup_submitted_assignment(
        due_at="2026-06-25T00:00:00Z", section_scores_json={"greeting": 88},
    )
    aid = cat["assignment"]["id"]
    held = validate_success(api.fraud_check_scorecard(aid, {"decision": "HOLD"}, make_qa_validator_headers()))
    assert held["fraud_status"] == "FRAUD_HOLD", (
        f"expected fraud_status FRAUD_HOLD, got {held['fraud_status']}"
    )
    assert held["audit_status"] == "DRAFT", (
        f"audit axis must stay DRAFT under fraud HOLD, got {held['audit_status']}"
    )


def test_clearing_fraud_hold_unblocks_validation_and_flips_audit_status(api):
    """PRD 3.6: "Validation moves the assignment SUBMITTED -> VALIDATED. It requires
    the assignment to be SUBMITTED, the scorecard's fraud_status to not be
    FRAUD_HOLD, and the shopper to not be SUSPENDED. On validation the platform
    performs the full settlement cascade atomically: it computes the audited score
    and sets the scorecard's audit_status to AUDITED..."

    Design: Difficulty/non_linear_state_machine/scorecard_parallel_audit_and_fraud_dimensions_evolve_independently
    """
    cat = fixtures.setup_submitted_assignment(
        due_at="2026-06-25T00:00:00Z", section_scores_json={"greeting": 88},
    )
    aid = cat["assignment"]["id"]
    validate_success(api.fraud_check_scorecard(aid, {"decision": "HOLD"}, make_qa_validator_headers()))
    cleared = validate_success(api.fraud_check_scorecard(aid, {"decision": "CLEAR"}, make_qa_validator_headers()))
    assert cleared["fraud_status"] == "CLEARED", (
        f"expected fraud_status CLEARED, got {cleared['fraud_status']}"
    )
    validated = validate_success(api.validate_assignment(aid, make_qa_validator_headers()))
    assert validated["status"] == "VALIDATED"
    sc = validate_success(api.get_scorecard(aid, make_qa_validator_headers()))
    assert _card(sc)["audit_status"] == "AUDITED", (
        "audit_status must flip to AUDITED only on validation"
    )


# ---------------------------------------------------------------------------
# state_machines / initial_state_assignment_is_assigned
# ---------------------------------------------------------------------------
def test_new_assignment_starts_assigned_with_zero_submission_count(api):
    """PRD 3.4: "A ClientManager or PlatformAdmin supplies wave_id, shopper_id,
    location_id, script_id, and a due_at deadline. The new assignment starts in
    ASSIGNED."

    Design: Corner/state_machines/initial_state_assignment_is_assigned
    """
    cat = fixtures.setup_catalog_with_shopper(loc_lat=40.0, loc_lng=-74.0)
    asg = fixtures.create_assignment(
        cat["client"]["id"], cat["wave"]["id"], cat["shopper"]["id"],
        cat["location"]["id"], cat["script"]["id"], "2026-06-10T00:00:00Z",
    )
    assert asg["status"] == "ASSIGNED", f"expected ASSIGNED, got {asg['status']}"
    assert asg["submission_count"] == 0, (
        f"submission_count expected 0 at creation, got {asg['submission_count']}"
    )


# ---------------------------------------------------------------------------
# state_machines / request_revision_resets_approved_evidence_to_pending
# ---------------------------------------------------------------------------
def test_request_revision_resets_approved_evidence_to_pending(api):
    """PRD 3.6: "Requesting a revision sets every APPROVED evidence item on the
    assignment back to PENDING, so the shopper must shepherd that evidence through
    review again."

    Design: Corner/state_machines/request_revision_resets_approved_evidence_to_pending
    """
    cat = fixtures.setup_submitted_assignment(
        due_at="2026-06-20T00:00:00Z", section_scores_json={"greeting": 88},
    )
    aid = cat["assignment"]["id"]
    validate_success(api.request_revision(aid, make_qa_validator_headers()))
    ev = validate_success(api.list_evidence(aid, make_qa_validator_headers()))
    item = ev[0] if isinstance(ev, list) else ev
    assert item["review_status"] == "PENDING", (
        f"evidence review_status expected PENDING after request-revision, got {item['review_status']}"
    )
