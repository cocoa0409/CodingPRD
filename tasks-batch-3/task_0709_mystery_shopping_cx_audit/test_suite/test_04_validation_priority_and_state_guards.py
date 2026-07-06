"""Validation precedence and cross-entity state guards: state outranks the fiscal
1099 gate, ownership outranks evidence completeness, validation is blocked by a
child scorecard FRAUD_HOLD, assignment creation is blocked by an uncertified
shopper, plus invalid-transition / terminal-lockdown / existence-before-state
corners.

Covers difficulty rules priority_pair_validation_conflict and
cross_entity_state_dependency, plus corner state-machine and validation instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    ApiErrorId, NON_EXISTENT_UUID, fixtures,
)
from test_helpers.test_users import (
    make_shopper_headers,
    make_qa_validator_headers,
    make_finance_officer_headers,
    make_client_manager_headers,
    make_platform_admin_headers,
)


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / state_beats_fiscal_tax_id_on_paid_batch
# ---------------------------------------------------------------------------
def test_paying_already_paid_batch_returns_invalid_state_not_tax_id(api):
    """PRD 3.9: "Paying a batch moves it OPEN -> PAID. Payment requires the batch to
    be OPEN, every member reimbursement to still be BATCHED (none reversed since
    batching), and -- when the batch requires 1099 reporting -- the payee's
    tax_id_on_file to be true (otherwise ERR_TAX_ID_REQUIRED)..."

    A second pay on an already-PAID batch fails the OPEN-state precondition first.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_tax_id_on_paid_batch
    """
    # tax_id_on_file true, small gross (below 1099 threshold) so the first pay succeeds.
    cat = fixtures.setup_batched_reimbursement(due_at="2026-06-25T00:00:00Z", tax_id_on_file=True)
    batch_id = cat["batch"]["id"]
    validate_success(api.pay_payout_batch(batch_id, make_finance_officer_headers()))
    resp = api.pay_payout_batch(batch_id, make_finance_officer_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_paying_voided_batch_returns_invalid_state(api):
    """PRD 3.9: "Paying a batch moves it OPEN -> PAID. Payment requires the batch to
    be OPEN, every member reimbursement to still be BATCHED (none reversed since
    batching)..."

    Isolating the state precondition: a VOIDED batch (not OPEN) fails the OPEN
    requirement with ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_tax_id_on_paid_batch
    """
    cat = fixtures.setup_batched_reimbursement(due_at="2026-06-25T00:00:00Z", tax_id_on_file=True)
    batch_id = cat["batch"]["id"]
    validate_success(api.void_payout_batch(batch_id, make_finance_officer_headers()))
    resp = api.pay_payout_batch(batch_id, make_finance_officer_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / not_owner_beats_evidence_incomplete_on_submit
# ---------------------------------------------------------------------------
def test_non_owner_submit_returns_not_resource_owner_not_evidence_incomplete(api):
    """PRD 2.1: "A shopper acting on an assignment that is not their own is rejected
    with ERR_NOT_RESOURCE_OWNER."
    PRD 3.5: "Submitting moves the assignment IN_FIELD -> SUBMITTED. Submission
    requires the assignment to be IN_FIELD, the acting shopper to be its own
    shopper, and the logical clock to be at or before due_at."

    Shopper B submitting shopper A's evidence-less IN_FIELD assignment is rejected
    for ownership before the evidence-completeness check.

    Design: Difficulty/priority_pair_validation_conflict/not_owner_beats_evidence_incomplete_on_submit
    """
    cat = fixtures.setup_catalog_with_shopper(loc_lat=40.0, loc_lng=-74.0)
    cid, wave_id = cat["client"]["id"], cat["wave"]["id"]
    loc_id, script_id = cat["location"]["id"], cat["script"]["id"]
    shopper_a = cat["shopper"]["id"]
    shopper_b = fixtures.register_shopper(tax_id_on_file=True, home_lat=40.0, home_lng=-74.0)
    fixtures.certify_shopper(shopper_b["id"], scenario_family="RETAIL")
    # Shopper A accepts; no evidence, no scorecard.
    fixtures.create_in_field_assignment(cid, wave_id, shopper_a, loc_id, script_id, "2026-06-25T00:00:00Z")
    # Re-create the assignment id capture cleanly via list (single assignment).
    asgs = validate_success(api.list_assignments(make_qa_validator_headers(), params={"shopper_id": shopper_a}))
    aid = (asgs[0] if isinstance(asgs, list) else asgs)["id"]
    resp = api.submit_assignment(aid, make_shopper_headers(shopper_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_non_owner_submit_rejected_even_when_evidence_complete(api):
    """PRD 2.1: "A shopper acting on an assignment that is not their own is rejected
    with ERR_NOT_RESOURCE_OWNER."

    Isolating the ownership rule: even when the assignment IS submittable (complete
    approved evidence + scorecard), a non-owner shopper is still rejected for
    ownership.

    Design: Difficulty/priority_pair_validation_conflict/not_owner_beats_evidence_incomplete_on_submit
    """
    cat = fixtures.setup_catalog_with_shopper(loc_lat=40.0, loc_lng=-74.0)
    cid, wave_id = cat["client"]["id"], cat["wave"]["id"]
    loc_id, script_id = cat["location"]["id"], cat["script"]["id"]
    shopper_a = cat["shopper"]["id"]
    shopper_b = fixtures.register_shopper(tax_id_on_file=True, home_lat=40.0, home_lng=-74.0)
    fixtures.certify_shopper(shopper_b["id"], scenario_family="RETAIL")
    asg = fixtures.create_in_field_assignment(
        cid, wave_id, shopper_a, loc_id, script_id, "2026-06-25T00:00:00Z")
    aid = asg["id"]
    # Make the assignment fully submittable so only the ownership rule can fire.
    fixtures.add_approved_photo(aid, shopper_a)
    fixtures.create_scorecard(aid, shopper_a, {"greeting": 88})
    resp = api.submit_assignment(aid, make_shopper_headers(shopper_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / validate_blocked_by_scorecard_fraud_hold
# ---------------------------------------------------------------------------
def test_validate_blocked_by_scorecard_fraud_hold(api):
    """PRD 3.6: "Validation moves the assignment SUBMITTED -> VALIDATED. It requires
    the assignment to be SUBMITTED, the scorecard's fraud_status to not be
    FRAUD_HOLD, and the shopper to not be SUSPENDED."
    PRD 3.6: "A FRAUD_HOLD blocks validation until it is cleared."

    Design: Difficulty/cross_entity_state_dependency/validate_blocked_by_scorecard_fraud_hold
    """
    cat = fixtures.setup_submitted_assignment(
        due_at="2026-06-25T00:00:00Z", section_scores_json={"greeting": 88},
    )
    aid = cat["assignment"]["id"]
    validate_success(api.fraud_check_scorecard(aid, {"decision": "HOLD"}, make_qa_validator_headers()))
    resp = api.validate_assignment(aid, make_qa_validator_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_validate_succeeds_when_fraud_status_not_hold(api):
    """PRD 3.6: "Validation moves the assignment SUBMITTED -> VALIDATED. It requires
    the assignment to be SUBMITTED, the scorecard's fraud_status to not be
    FRAUD_HOLD, and the shopper to not be SUSPENDED."

    Design: Difficulty/cross_entity_state_dependency/validate_blocked_by_scorecard_fraud_hold
    """
    cat = fixtures.setup_submitted_assignment(
        due_at="2026-06-25T00:00:00Z", section_scores_json={"greeting": 88},
    )
    aid = cat["assignment"]["id"]
    validated = validate_success(api.validate_assignment(aid, make_qa_validator_headers()))
    assert validated["status"] == "VALIDATED", (
        f"validate must succeed with fraud_status UNCHECKED, got {validated['status']}"
    )


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / assignment_create_blocked_by_uncertified_shopper
# ---------------------------------------------------------------------------
def test_assignment_create_blocked_by_uncertified_shopper(api):
    """PRD 3.4: "The shopper must be CERTIFIED and certified in the location's
    scenario_family; a non-certified shopper, or one not certified in that family,
    is rejected with ERR_SHOPPER_NOT_CERTIFIED."

    Design: Difficulty/cross_entity_state_dependency/assignment_create_blocked_by_uncertified_shopper
    """
    cat = fixtures.setup_catalog(scenario_family="RETAIL", loc_lat=40.0, loc_lng=-74.0)
    # REGISTERED shopper (never certified).
    shopper = fixtures.register_shopper(tax_id_on_file=False, home_lat=40.0, home_lng=-74.0)
    cm = make_client_manager_headers(cat["client"]["id"])
    payload = fixtures.factories.create_assignment_payload(
        cat["wave"]["id"], shopper["id"], cat["location"]["id"], cat["script"]["id"],
        "2026-06-25T00:00:00Z",
    )
    resp = api.create_assignment(payload, cm)
    validate_error(resp, ApiErrorId.ERR_SHOPPER_NOT_CERTIFIED.value)


def test_assignment_create_succeeds_for_certified_shopper(api):
    """PRD 3.4: "The shopper must be CERTIFIED and certified in the location's
    scenario_family; a non-certified shopper, or one not certified in that family,
    is rejected with ERR_SHOPPER_NOT_CERTIFIED."

    The inverse: a CERTIFIED shopper in the right family is accepted.

    Design: Difficulty/cross_entity_state_dependency/assignment_create_blocked_by_uncertified_shopper
    """
    cat = fixtures.setup_catalog_with_shopper(scenario_family="RETAIL", loc_lat=40.0, loc_lng=-74.0)
    cm = make_client_manager_headers(cat["client"]["id"])
    payload = fixtures.factories.create_assignment_payload(
        cat["wave"]["id"], cat["shopper"]["id"], cat["location"]["id"],
        cat["script"]["id"], "2026-06-25T00:00:00Z",
    )
    asg = validate_success(api.create_assignment(payload, cm), expected_status=201)
    assert asg["status"] == "ASSIGNED"


# ---------------------------------------------------------------------------
# state_machines / accept_from_validated_assignment_returns_invalid_state
# ---------------------------------------------------------------------------
def test_accept_on_validated_assignment_returns_invalid_state(api):
    """PRD 3.5: "A shopper takes up an assignment by accepting it, which moves it
    ASSIGNED -> IN_FIELD. Acceptance requires the assignment to be ASSIGNED, the
    acting shopper to be the assignment's own shopper, and the logical clock to be
    at or before the assignment's due_at."

    Accepting a VALIDATED (terminal) assignment is not a defined transition.

    Design: Corner/state_machines/accept_from_validated_assignment_returns_invalid_state
    """
    cat = fixtures.setup_validated_assignment(due_at="2026-06-10T00:00:00Z", loc_lat=40.0, loc_lng=-74.0)
    aid, sid = cat["assignment"]["id"], cat["shopper"]["id"]
    resp = api.accept_assignment(aid, make_shopper_headers(sid))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    asg = validate_success(api.get_assignment(aid, make_qa_validator_headers()))
    assert asg["status"] == "VALIDATED", "assignment must stay VALIDATED after a rejected accept"


# ---------------------------------------------------------------------------
# state_machines / terminal_state_archived_script_cannot_be_published_again
# ---------------------------------------------------------------------------
def test_archived_script_cannot_be_published_again(api):
    """PRD 3.3: "A PUBLISHED script may be archived, moving it PUBLISHED ->
    ARCHIVED, but only when no assignment referencing the script is in a
    non-terminal state... ARCHIVED is terminal for a script."

    Re-publishing from the ARCHIVED terminal state is not a defined transition.

    Design: Corner/state_machines/terminal_state_archived_script_cannot_be_published_again
    """
    client = fixtures.register_client(fee_per_completed_shop_cents=15000)
    cid = client["id"]
    cm = make_client_manager_headers(cid)
    script = fixtures.create_and_publish_script(cid, scenario_family="RETAIL",
                                                weights_json={"greeting": 1.0})
    validate_success(api.archive_script(script["id"], cm))
    resp = api.publish_script(script["id"], cm)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# validations / existence_beats_state_unknown_assignment_validate
# ---------------------------------------------------------------------------
def test_validate_unknown_assignment_returns_not_found(api):
    """PRD 2.4: "A request is rejected with ERR_NOT_FOUND for the first path segment
    whose identifier does not resolve to an existing resource, before any later
    segment or any body foreign key is examined."

    Design: Corner/validations/existence_beats_state_unknown_assignment_validate
    """
    resp = api.validate_assignment(NON_EXISTENT_UUID, make_qa_validator_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
