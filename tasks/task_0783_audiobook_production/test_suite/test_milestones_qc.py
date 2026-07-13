"""Milestone delivery, QC verdicts, the revision cycle, and QC-fail cascade."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_author_headers, make_narrator_headers, qc_headers,
    create_milestone_payload,
    setup_offered_contract, setup_accepted_contract, setup_submitted_full_milestone,
    submit_full_milestone, qc_fail, qc_pass,
)


def _title(api, ctx):
    return validate_success(api.get_title(ctx["title"]["id"], make_author_headers(ctx["author"]["id"])), 200)


def _milestone(api, ctx, milestone_id):
    return validate_success(api.get_milestone(milestone_id, make_narrator_headers(ctx["narrator"]["id"])), 200)


# ─── Difficulty: milestone_submit_requires_accepted_contract ───

def test_fifteen_min_milestone_on_offered_contract_rejected(api):
    """PRD §3.5: "Submitting requires that the contract is in `ACCEPTED` status,
    or the submission is refused with `ERR_CONTRACT_NOT_ACCEPTED`, and the caller
    must be that contract's narrator."

    Design: Difficulty/cross_entity_state_dependency/milestone_submit_requires_accepted_contract
    """
    ctx = setup_offered_contract(api)  # contract OFFERED
    payload = create_milestone_payload(ctx["contract"]["id"], "FIFTEEN_MIN")
    resp = api.create_milestone(payload, make_narrator_headers(ctx["narrator"]["id"]))
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACCEPTED.value)


def test_full_milestone_on_offered_contract_rejected(api):
    """PRD §3.5: "Submitting requires that the contract is in `ACCEPTED` status,
    or the submission is refused with `ERR_CONTRACT_NOT_ACCEPTED`, and the caller
    must be that contract's narrator."

    Design: Difficulty/cross_entity_state_dependency/milestone_submit_requires_accepted_contract
    """
    ctx = setup_offered_contract(api)  # contract OFFERED
    payload = create_milestone_payload(ctx["contract"]["id"], "FULL", finished_hours=6.0)
    resp = api.create_milestone(payload, make_narrator_headers(ctx["narrator"]["id"]))
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACCEPTED.value)


# ─── Difficulty: qc_fail_reverts_title_to_production ───

def test_qc_fail_moves_milestone_to_revision_requested(api):
    """PRD §3.5: "Each `FAIL` increments the milestone's `revision_count` by one
    and records the failing review."
    PRD §3.5: "while the current `revision_count` is below `MAX_REVISIONS`, a
    `FAIL` moves the milestone `SUBMITTED → REVISION_REQUESTED`".

    Design: Difficulty/transitive_cascade/qc_fail_reverts_title_to_production
    """
    ctx = setup_submitted_full_milestone(api)
    qc_fail(api, ctx["milestone"]["id"], notes="audio noise")
    m = _milestone(api, ctx, ctx["milestone"]["id"])
    assert m["status"] == "REVISION_REQUESTED"
    assert m["revision_count"] == 1


def test_qc_fail_walks_full_title_back_to_production(api):
    """PRD §3.5: "In either branch, when the failed milestone is a `FULL`
    deliverable, the title is walked back `IN_QC → IN_PRODUCTION` so the narrator
    can rework it."

    Design: Difficulty/transitive_cascade/qc_fail_reverts_title_to_production
    """
    ctx = setup_submitted_full_milestone(api)
    qc_fail(api, ctx["milestone"]["id"], notes="audio noise")
    assert _title(api, ctx)["status"] == "IN_PRODUCTION"


# ─── Difficulty: milestone_qc_revision_cycle ───

def test_milestone_returns_to_submitted_after_resubmit(api):
    """PRD §3.5: "it moves the milestone `REVISION_REQUESTED → SUBMITTED`, updates
    the stored `audio_url`, and bumps the milestone's version."
    PRD §3.5: "Each `FAIL` increments the milestone's `revision_count` by one and
    records the failing review."

    Design: Difficulty/non_linear_state_machine/milestone_qc_revision_cycle
    """
    ctx = setup_submitted_full_milestone(api)
    qc_fail(api, ctx["milestone"]["id"], notes="retake chapter 3")
    validate_success(
        api.resubmit_milestone(ctx["milestone"]["id"], {"audio_url": "http://audio/v2"}, make_narrator_headers(ctx["narrator"]["id"])), 200
    )
    m = _milestone(api, ctx, ctx["milestone"]["id"])
    assert m["status"] == "SUBMITTED"
    assert m["revision_count"] == 1


def test_title_reenters_qc_after_resubmit(api):
    """PRD §3.5: "When the milestone is a `FULL` deliverable, resubmission drives
    the title `IN_PRODUCTION → IN_QC` again, re-entering quality control for
    another review cycle."

    Design: Difficulty/non_linear_state_machine/milestone_qc_revision_cycle
    """
    ctx = setup_submitted_full_milestone(api)
    qc_fail(api, ctx["milestone"]["id"], notes="retake chapter 3")
    validate_success(
        api.resubmit_milestone(ctx["milestone"]["id"], {"audio_url": "http://audio/v2"}, make_narrator_headers(ctx["narrator"]["id"])), 200
    )
    assert _title(api, ctx)["status"] == "IN_QC"


# ─── Corner cases ───

def test_qc_review_on_approved_milestone_rejected(api):
    """PRD §3.5: "Recording a verdict creates a `QCReview` ... and is only
    permitted while the milestone is in `SUBMITTED`; otherwise it is refused with
    `ERR_MILESTONE_NOT_SUBMITTED`."

    Design: Corner/state_machines/qc_review_on_non_submitted_milestone_returns_invalid_state
    """
    ctx = setup_submitted_full_milestone(api)
    qc_pass(api, ctx["milestone"]["id"])  # now APPROVED
    resp = api.create_qc_review(ctx["milestone"]["id"], {"outcome": "FAIL", "notes": "late"}, qc_headers())
    validate_error(resp, ApiErrorId.ERR_MILESTONE_NOT_SUBMITTED.value)


def test_resubmit_submitted_milestone_rejected(api):
    """PRD §3.5: "Resubmitting is only allowed while the milestone is in
    `REVISION_REQUESTED` — otherwise `ERR_MILESTONE_NOT_REVISABLE` — and only by
    the contract's narrator".

    Design: Corner/errors/error_resubmit_non_revisable_milestone
    """
    ctx = setup_submitted_full_milestone(api)  # milestone SUBMITTED, not REVISION_REQUESTED
    resp = api.resubmit_milestone(
        ctx["milestone"]["id"], {"audio_url": "http://audio/again"}, make_narrator_headers(ctx["narrator"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_MILESTONE_NOT_REVISABLE.value)


def test_full_milestone_zero_finished_hours_rejected(api):
    """PRD §3.5: "For a `FULL` milestone, `finished_hours` is required and must be
    strictly greater than zero; a missing or non-positive value is rejected with
    `ERR_INVALID_FINISHED_HOURS`."

    Design: Corner/validations/full_milestone_zero_finished_hours_returns_invalid_finished_hours
    """
    ctx = setup_accepted_contract(api)  # title IN_PRODUCTION, contract ACCEPTED
    payload = create_milestone_payload(ctx["contract"]["id"], "FULL", finished_hours=0)
    resp = api.create_milestone(payload, make_narrator_headers(ctx["narrator"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_FINISHED_HOURS.value)
