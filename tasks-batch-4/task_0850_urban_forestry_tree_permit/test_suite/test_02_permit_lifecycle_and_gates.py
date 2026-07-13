"""Protected-tree permit lifecycle: state machine, gates, fee, and issuance priority."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_permit_payload, review_payload, pay_fee_payload,
    setup_tree, setup_submitted_removal_permit, setup_approved_removal_permit,
    new_permit, new_inspection, submit,
    TEST_USERS, make_applicant_headers, APPLICANT_1,
)

APPLICANT = TEST_USERS["applicant_headers"]
ARBORIST = TEST_USERS["arborist_headers"]


def test_new_permit_starts_in_draft(api):
    """PRD §3.4: "The server records the acting `X-User-ID` as the permit's
    `requested_by_user_id` and starts the permit in `DRAFT`."

    Design: Corner/state_machines/permit_initial_state_draft
    """
    zone, species, tree = setup_tree(dbh=20.0)
    res = api.create_permit(create_permit_payload(tree["id"], permit_type="REMOVAL",
                                                  reason="decay"), APPLICANT)
    permit = validate_success(res, 201)
    assert permit["status"] == "DRAFT"


def test_submit_denied_permit_rejected(api):
    """PRD §3.4: "The permit moves through the states `DRAFT`, `UNDER_REVIEW`,
    `INFO_REQUESTED`, `APPROVED`, `DENIED`, `ISSUED`, `CLOSED`, and `REVOKED`, of which
    `DENIED`, `CLOSED`, and `REVOKED` are terminal."
    PRD §2.5: "Only after all of that does the server evaluate state-machine legality
    (`ERR_INVALID_STATE`, 409)".

    Design: Corner/state_machines/submit_denied_permit_rejects_invalid_state
    """
    ctx = setup_submitted_removal_permit()
    api.review_permit(ctx["permit"]["id"], review_payload("DENY", review_notes="no"), ARBORIST)
    res = api.submit_permit(ctx["permit"]["id"], APPLICANT)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_submit_permit_for_unprotected_tree_rejected(api):
    """PRD §3.4: "Submitting a permit for a non-protected tree is rejected with
    `ERR_TREE_NOT_PROTECTED` (422)."

    Design: Corner/validations/submit_permit_on_unprotected_tree_rejects
    """
    zone, species, tree = setup_tree(dbh=5.0, species_overrides={"is_protected_species": False})
    assert tree["is_protected"] is False
    permit = new_permit(tree["id"], permit_type="REMOVAL", reason="small tree")
    res = api.submit_permit(permit["id"], APPLICANT)
    validate_error(res, "ERR_TREE_NOT_PROTECTED", expected_status=422)


def test_pay_fee_amount_mismatch_rejected(api):
    """PRD §3.4: "The owning `Applicant` **pays the fee** by submitting an `amount_cents`
    value, which must exactly equal the permit's `mitigation_fee_cents`; a mismatch is
    rejected with `ERR_FEE_AMOUNT_MISMATCH` (422)."

    Design: Corner/validations/pay_fee_amount_mismatch_rejected
    """
    ctx = setup_approved_removal_permit(mitigation_method="REPLACEMENT_COST", dbh=20.0)
    assert ctx["permit"]["mitigation_fee_cents"] == 40312
    res = api.pay_fee(ctx["permit"]["id"], pay_fee_payload(40000), APPLICANT)
    validate_error(res, "ERR_FEE_AMOUNT_MISMATCH", expected_status=422)


# ── non_linear_state_machine: permit revision loop ───────────────────────
def test_request_info_moves_permit_to_info_requested(api):
    """PRD §3.4: "A `DENY` decision moves the permit to `DENIED`; a `REQUEST_INFO`
    decision moves it to `INFO_REQUESTED`."

    Design: Difficulty/non_linear_state_machine/permit_info_request_revision_cycle
    """
    ctx = setup_submitted_removal_permit()
    res = api.review_permit(ctx["permit"]["id"],
                            review_payload("REQUEST_INFO", review_notes="need more"), ARBORIST)
    permit = validate_success(res, 200)
    assert permit["status"] == "INFO_REQUESTED"


def test_provide_info_returns_permit_to_under_review(api):
    """PRD §3.4: "From `INFO_REQUESTED`, the owning `Applicant` responds through the
    provide-info step (optionally attaching a `response_note`), which returns the permit
    `INFO_REQUESTED → UNDER_REVIEW`; provide-info also enforces the same ownership check
    as submit."

    Design: Difficulty/non_linear_state_machine/permit_info_request_revision_cycle
    """
    ctx = setup_submitted_removal_permit()
    api.review_permit(ctx["permit"]["id"],
                      review_payload("REQUEST_INFO", review_notes="need more"), ARBORIST)
    res = api.provide_info(ctx["permit"]["id"], {"response_note": "here it is"}, APPLICANT)
    permit = validate_success(res, 200)
    assert permit["status"] == "UNDER_REVIEW"


# ── priority_pair_validation_conflict: issue state vs fiscal ─────────────
def test_issue_unapproved_unpaid_permit_returns_not_approved(api):
    """PRD §3.4: "the state precondition — the permit must be in `APPROVED` — is checked
    first and outranks the fiscal precondition. If the permit is not in `APPROVED`,
    issuance fails with `ERR_PERMIT_NOT_APPROVED` (409) regardless of payment".

    Design: Difficulty/priority_pair_validation_conflict/issue_state_outranks_fiscal
    """
    ctx = setup_submitted_removal_permit()  # UNDER_REVIEW, fee neither computed nor paid
    res = api.issue_permit(ctx["permit"]["id"], ARBORIST)
    validate_error(res, "ERR_PERMIT_NOT_APPROVED", expected_status=409)


def test_issue_approved_unpaid_permit_returns_fee_unpaid(api):
    """PRD §3.4: "only once the permit is confirmed `APPROVED` does the server check that
    `fee_paid` is true, failing with `ERR_FEE_UNPAID` (402) when it is not."

    Design: Difficulty/priority_pair_validation_conflict/issue_state_outranks_fiscal
    """
    ctx = setup_approved_removal_permit(mitigation_method="REPLACEMENT_COST", dbh=20.0)
    res = api.issue_permit(ctx["permit"]["id"], ARBORIST)  # APPROVED but unpaid
    validate_error(res, "ERR_FEE_UNPAID", expected_status=402)


# ── cross_entity_state_dependency: approve gated on finalized inspection ─
def test_removal_approve_without_finalized_inspection_rejected(api):
    """PRD §3.4: "For a `REMOVAL` permit, approval has two preconditions: the tree's
    `current_inspection_id` must reference an inspection whose status is `FINALIZED`
    (otherwise `ERR_INSPECTION_REQUIRED`, 422)".

    Design: Difficulty/cross_entity_state_dependency/removal_approve_requires_finalized_inspection
    """
    zone, species, tree = setup_tree(dbh=20.0)
    # DRAFT inspection (created, never finalized) -> current_inspection_id set but not FINALIZED.
    new_inspection(tree["id"], tree["version"], inspection_type="RISK",
                   likelihood_score=2, consequence_score=2, target_rating=2)
    permit = new_permit(tree["id"], permit_type="REMOVAL", reason="decay")
    submit(permit["id"])
    res = api.review_permit(permit["id"],
                            review_payload("APPROVE", mitigation_method="REPLACEMENT_COST"),
                            ARBORIST)
    validate_error(res, "ERR_INSPECTION_REQUIRED", expected_status=422)


def test_removal_approve_with_finalized_inspection_succeeds(api):
    """PRD §3.4: "An `APPROVE` decision moves the permit `UNDER_REVIEW → APPROVED` and is
    the point at which mitigation is computed. For a `REMOVAL` permit, approval has two
    preconditions: the tree's `current_inspection_id` must reference an inspection whose
    status is `FINALIZED` (otherwise `ERR_INSPECTION_REQUIRED`, 422)".

    Design: Difficulty/cross_entity_state_dependency/removal_approve_requires_finalized_inspection
    """
    ctx = setup_submitted_removal_permit(dbh=20.0)  # inspection is FINALIZED
    res = api.review_permit(ctx["permit"]["id"],
                            review_payload("APPROVE", mitigation_method="REPLACEMENT_COST"),
                            ARBORIST)
    permit = validate_success(res, 200)
    assert permit["status"] == "APPROVED"
