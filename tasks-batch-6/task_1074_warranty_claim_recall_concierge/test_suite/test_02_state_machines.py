"""Claim revision cycle, recall-live dependency, and invalid state transitions.

Difficulty instances get >=2 tests each; corner instances get >=1.
"""
from test_helpers import (
    validate_success, validate_error,
    make_household_owner_headers, make_concierge_headers,
    setup_refund_claim_under_review, setup_recall_published, setup_basic_draft_claim,
    request_docs, add_document, submit_claim, acknowledge_match, match_for_product,
    close_recall,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _run_revision_cycle(api):
    """SUBMITTED -> UNDER_REVIEW -> NEEDS_DOCS -> (new doc) -> re-submit."""
    ctx = setup_refund_claim_under_review(tier="BASIC", purchase_price_cents=20000,
                                          warranty_months=24, reviewer_id="cx-reviewer")
    claim_id, owner_id = ctx["claim"]["id"], ctx["owner"]["id"]
    request_docs(claim_id, "cx-reviewer")
    add_document(claim_id, owner_id, doc_type="PHOTO", file_uri="s3://r/5b")
    resubmitted = validate_success(
        api.submit_claim(claim_id, make_household_owner_headers(owner_id)), 200)
    return ctx, resubmitted


def test_claim_revision_cycle_returns_to_submitted(api):
    """PRD 3.6: "the `NEEDS_DOCS` back to `SUBMITTED` step requires that a
    `ClaimDocument` was added *after* the claim entered `NEEDS_DOCS` (a document
    created later than the moment of that transition), and if no such fresh document
    exists the re-submission is rejected with `ERR_MISSING_DOCUMENTATION`."

    Design: Difficulty/non_linear_state_machine/claim_revision_cycle_returns_to_submitted
    """
    _, resubmitted = _run_revision_cycle(api)
    assert resubmitted["status"] == "SUBMITTED"


def test_claim_revision_cycle_does_not_reincrement_claims_used(api):
    """PRD 3.6: "Crucially, this re-submission does **not** increment `claims_used`
    again — the allowance was consumed on the first submission."

    Design: Difficulty/non_linear_state_machine/claim_revision_cycle_returns_to_submitted
    """
    ctx, _ = _run_revision_cycle(api)
    sub = validate_success(api.get_subscription(ctx["sub"]["id"], ADMIN), 200)
    assert sub["claims_used"] == 1


def test_acknowledge_after_notice_closed_rejected(api):
    """PRD 3.5: "Acknowledgement carries a cross-entity precondition: the parent
    `RecallNotice` must still be `PUBLISHED` (the safety notice must be live), and if
    it is not, the request is rejected with `ERR_RECALL_NOT_LIVE`."

    Design: Difficulty/cross_entity_state_dependency/recall_ack_depends_on_notice_published
    """
    ctx = setup_recall_published(exposure_scoring_mode="WEIGHTED", severity="HIGH",
                                 serials=(20,), serial_range_start=1, serial_range_end=100,
                                 model_number="RC-2", remedy_type="REPAIR")
    prod, owner, rn, mfr = ctx["products"][0], ctx["owner"], ctx["rn"], ctx["mfr"]
    match = match_for_product(prod["id"])
    close_recall(rn["id"], mfr["id"])
    res = api.acknowledge_recall_match(match["id"], make_household_owner_headers(owner["id"]))
    validate_error(res, "ERR_RECALL_NOT_LIVE")


def test_acknowledge_after_notice_closed_leaves_match_matched(api):
    """PRD 3.5: "A member of the household — either the `HouseholdOwner` or a
    `HouseholdMember` — acknowledges a match to move it from `MATCHED` to
    `ACKNOWLEDGED`, signalling the household has seen the safety alert."

    Design: Difficulty/cross_entity_state_dependency/recall_ack_depends_on_notice_published
    """
    ctx = setup_recall_published(exposure_scoring_mode="WEIGHTED", severity="HIGH",
                                 serials=(20,), serial_range_start=1, serial_range_end=100,
                                 model_number="RC-2", remedy_type="REPAIR")
    prod, owner, rn, mfr = ctx["products"][0], ctx["owner"], ctx["rn"], ctx["mfr"]
    match = match_for_product(prod["id"])
    close_recall(rn["id"], mfr["id"])
    api.acknowledge_recall_match(match["id"], make_household_owner_headers(owner["id"]))
    after = validate_success(api.get_recall_match(match["id"], ADMIN), 200)
    assert after["status"] == "MATCHED"


def test_approve_draft_claim_returns_invalid_state(api):
    """PRD 3.7: "Both decisions also require the claim to be in `UNDER_REVIEW`, else
    `ERR_INVALID_STATE`; when both the state and duties checks would apply, the state
    check is evaluated first."

    Design: Corner/state_machines/approve_draft_claim_returns_invalid_state
    """
    ctx = setup_basic_draft_claim(price_cents=100, warranty_months=12)
    res = api.approve_claim(ctx["claim"]["id"], make_concierge_headers("cx-1"))
    validate_error(res, "ERR_INVALID_STATE")


def test_acknowledge_already_acknowledged_match_invalid_state(api):
    """PRD 3.5: "Each of the three transitions is defined only from the state named
    (`MATCHED` for acknowledge and dismiss, `ACKNOWLEDGED` for remedy), so requesting
    one from any other state is refused with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/acknowledge_already_acknowledged_match_invalid_state
    """
    ctx = setup_recall_published(exposure_scoring_mode="WEIGHTED", severity="LOW",
                                 serials=(5,), serial_range_start=1, serial_range_end=100,
                                 model_number="AK-1", remedy_type="REPAIR")
    prod, owner = ctx["products"][0], ctx["owner"]
    match = match_for_product(prod["id"])
    acknowledge_match(match["id"], owner["id"])
    res = api.acknowledge_recall_match(match["id"], make_household_owner_headers(owner["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_dismiss_acknowledged_match_invalid_state(api):
    """PRD 3.5: "Each of the three transitions is defined only from the state named
    (`MATCHED` for acknowledge and dismiss, `ACKNOWLEDGED` for remedy), so requesting
    one from any other state is refused with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/dismiss_from_acknowledged_returns_invalid_state
    """
    ctx = setup_recall_published(exposure_scoring_mode="WEIGHTED", severity="LOW",
                                 serials=(5,), serial_range_start=1, serial_range_end=100,
                                 model_number="DK-1", remedy_type="REPAIR")
    prod, owner = ctx["products"][0], ctx["owner"]
    match = match_for_product(prod["id"])
    acknowledge_match(match["id"], owner["id"])
    res = api.dismiss_recall_match(match["id"], make_household_owner_headers(owner["id"]))
    validate_error(res, "ERR_INVALID_STATE")
