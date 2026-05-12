"""Document drafting cycle: state machine, segregation of duties,
reviewer rank, version-pinning, and lock immutability.

PRD §3.3.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    assert_document_draft,
    create_draft_payload,
    create_template_payload,
    register_template,
    create_draft,
    setup_draft_in_review,
    setup_draft_locked,
    setup_three_lawyers_and_active_case,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Draft creation: template / case / version pinning
# ---------------------------------------------------------------------------
def test_draft_template_case_type_must_match(api):
    """PRD §3.3: 'otherwise the draft is rejected with
    ERR_TEMPLATE_CASE_TYPE_MISMATCH. On creation, the system pins'
    """
    bundle = setup_three_lawyers_and_active_case(case_type="CIVIL")
    template = register_template(
        case_type="CRIMINAL", partner_headers=bundle["partner_headers"]
    )
    payload = create_draft_payload(
        case_id=bundle["case"]["id"],
        template_id=template["id"],
        drafter_lawyer_id=bundle["junior"]["id"],
    )
    res = api.create_draft(payload, bundle["junior_headers"])
    validate_error(res, "ERR_TEMPLATE_CASE_TYPE_MISMATCH",
                   expected_status=422)


def test_draft_pins_template_version_at_creation(api):
    """PRD §3.3: 'On creation, the system pins the template's current
    version into the draft's template_version_pinned field (so that any
    subsequent template edit cannot alter the rendered output).'
    """
    bundle = setup_three_lawyers_and_active_case()
    template = register_template(
        case_type="CIVIL", partner_headers=bundle["partner_headers"]
    )
    draft = create_draft(
        case_id=bundle["case"]["id"], template_id=template["id"],
        drafter_lawyer_id=bundle["junior"]["id"],
        actor_headers=bundle["junior_headers"],
    )
    assert draft["template_version_pinned"] == template["version"]


def test_draft_initial_state_is_drafting(api):
    """PRD §3.3 documents the draft state machine starting at DRAFTING.

    Specifically: 'A draft moves through DRAFTING → IN_REVIEW → REVISING
    → DRAFTING → IN_REVIEW → SIGNED_OFF → LOCKED, possibly with multiple
    cycles back to DRAFTING.'
    """
    bundle = setup_three_lawyers_and_active_case()
    template = register_template(
        case_type="CIVIL", partner_headers=bundle["partner_headers"]
    )
    draft = create_draft(
        case_id=bundle["case"]["id"], template_id=template["id"],
        drafter_lawyer_id=bundle["junior"]["id"],
        actor_headers=bundle["junior_headers"],
    )
    assert draft["status"] == "DRAFTING"
    assert draft["version_number"] == 1


# ---------------------------------------------------------------------------
# State machine transitions
# ---------------------------------------------------------------------------
def test_submit_for_review_transitions_to_in_review(api):
    """PRD §3.3: 'The drafter submits for review, transitioning the
    draft from DRAFTING to IN_REVIEW; this requires the underlying case
    to be in ACTIVE status and rendered_body to be non-empty.'
    """
    bundle = setup_three_lawyers_and_active_case()
    template = register_template(
        case_type="CIVIL", partner_headers=bundle["partner_headers"]
    )
    draft = create_draft(
        case_id=bundle["case"]["id"], template_id=template["id"],
        drafter_lawyer_id=bundle["junior"]["id"],
        actor_headers=bundle["junior_headers"],
    )
    res = api.submit_draft_for_review(draft["id"], bundle["junior_headers"])
    in_review = validate_success(res, 200)
    assert in_review["status"] == "IN_REVIEW"


def test_request_revisions_returns_to_revising(api):
    """PRD §3.3: 'A senior may request revisions, returning the draft to
    REVISING and stamping the next iteration's version_number.'
    """
    bundle = setup_draft_in_review()
    res = api.request_revisions(
        bundle["draft"]["id"], bundle["senior_headers"]
    )
    revising = validate_success(res, 200)
    assert revising["status"] == "REVISING"


def test_resume_drafting_drafter_only(api):
    """PRD §3.3: 'From REVISING, only the original drafter may resume
    drafting, which moves the draft back to DRAFTING; the acting
    X-User-ID must equal drafter_lawyer_id.'
    """
    bundle = setup_draft_in_review()
    revising = validate_success(
        api.request_revisions(bundle["draft"]["id"],
                              bundle["senior_headers"]), 200,
    )
    # Senior tries to resume — must fail (drafter is the JUNIOR).
    res = api.resume_drafting(revising["id"], bundle["senior_headers"])
    assert res.status_code >= 400
    # JUNIOR (the drafter) succeeds.
    drafting = validate_success(
        api.resume_drafting(revising["id"], bundle["junior_headers"]), 200,
    )
    assert drafting["status"] == "DRAFTING"


def test_partner_signoff_requires_senior_pass_recorded(api):
    """PRD §3.3: 'Partner signoff moves the draft from IN_REVIEW to
    SIGNED_OFF; it requires the acting Lawyer.role to be exactly PARTNER,
    the acting lawyer to not be the drafter, and senior_reviewer_lawyer_id
    to be set (so that a senior pass occurred at some point in the draft's
    history).'

    Claim: partner-signoff on a draft with senior_reviewer_lawyer_id null
    → ERR_INVALID_STATE.
    """
    bundle = setup_draft_in_review()
    # senior_reviewer_lawyer_id is unset; partner attempts signoff.
    res = api.partner_signoff(
        bundle["draft"]["id"], bundle["partner_headers"]
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_full_drafting_to_locked_lifecycle(api):
    """PRD §3.3: 'A draft moves through DRAFTING → IN_REVIEW → REVISING →
    DRAFTING → IN_REVIEW → SIGNED_OFF → LOCKED, possibly with multiple
    cycles back to DRAFTING.'

    Claim: end-to-end the locked draft is in LOCKED status with
    partner_signoff_lawyer_id and signed_off_at populated.
    """
    bundle = setup_draft_locked()
    locked = bundle["draft"]
    assert locked["status"] == "LOCKED"
    assert locked["partner_signoff_lawyer_id"] == bundle["partner"]["id"]
    assert locked["signed_off_at"] is not None


# ---------------------------------------------------------------------------
# Segregation of duties (priority 9)
# ---------------------------------------------------------------------------
def test_drafter_cannot_partner_signoff_own_draft(api):
    """PRD §3.3: 'The reviewer-rank rule and the segregation-of-duties
    rule apply across four endpoints — request revisions, senior pass,
    partner signoff, and lock. In all four, an attempt by the drafter
    against their own draft surfaces ERR_SEGREGATION_OF_DUTIES.'
    """
    bundle = setup_three_lawyers_and_active_case()
    template = register_template(
        case_type="CIVIL", partner_headers=bundle["partner_headers"]
    )
    # Have the PARTNER both draft and try to sign off.
    draft = create_draft(
        case_id=bundle["case"]["id"], template_id=template["id"],
        drafter_lawyer_id=bundle["partner"]["id"],
        actor_headers=bundle["partner_headers"],
    )
    validate_success(
        api.submit_draft_for_review(draft["id"],
                                    bundle["partner_headers"]), 200
    )
    res = api.partner_signoff(draft["id"], bundle["partner_headers"])
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)


def test_drafter_cannot_request_revisions_on_own_draft(api):
    """PRD §3.3: 'The reviewer-rank rule and the segregation-of-duties
    rule apply across four endpoints — request revisions, senior pass,
    partner signoff, and lock. In all four, an attempt by the drafter
    against their own draft surfaces ERR_SEGREGATION_OF_DUTIES.'
    """
    bundle = setup_three_lawyers_and_active_case()
    template = register_template(
        case_type="CIVIL", partner_headers=bundle["partner_headers"]
    )
    # Senior drafts their own.
    draft = create_draft(
        case_id=bundle["case"]["id"], template_id=template["id"],
        drafter_lawyer_id=bundle["senior"]["id"],
        actor_headers=bundle["senior_headers"],
    )
    validate_success(
        api.submit_draft_for_review(draft["id"],
                                    bundle["senior_headers"]), 200
    )
    res = api.request_revisions(draft["id"], bundle["senior_headers"])
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)


# ---------------------------------------------------------------------------
# Reviewer rank (priority 18)
# ---------------------------------------------------------------------------
# Tests test_junior_cannot_senior_pass and test_senior_cannot_partner_signoff
# were removed: PRD §4 matrix and PRD §3.3 contradict each other, so a faithful
# PRD-only implementer can produce either ERR_FORBIDDEN (priority 2 from matrix)
# or ERR_REVIEWER_RANK_INSUFFICIENT (priority 18 from §3.3) on the same input.
# Unique-derivability collapse → tests deleted.


# ---------------------------------------------------------------------------
# Lock immutability
# ---------------------------------------------------------------------------
def test_locked_draft_rejects_further_mutation(api):
    """PRD §3.3: 'From SIGNED_OFF, a partner may lock the draft,
    transitioning it to LOCKED; locking re-verifies that
    template_version_pinned is still set, after which any further
    mutation against the draft is rejected with ERR_DRAFT_LOCKED.'
    """
    bundle = setup_draft_locked()
    # Attempt to submit-for-review (a mutation) on the LOCKED draft.
    res = api.submit_draft_for_review(
        bundle["draft"]["id"], bundle["junior_headers"]
    )
    validate_error(res, "ERR_DRAFT_LOCKED", expected_status=409)
