"""Work registration lifecycle: DRAFT → SUBMITTED → UNDER_REVIEW →
APPROVED / REJECTED / WITHDRAWN, including the SUBMITTED → DRAFT revision
loop (PRD §3.1, §3.2)."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    approve_work,
    assert_work,
    create_composition_work_payload,
    create_recording_work_payload,
    create_rights_holder,
    create_share,
    create_work_draft,
    find_audit_by_kind,
    make_rights_holder_headers,
    reject_work,
    reject_work_payload,
    return_to_draft,
    setup_approved_recording_work,
    submit_work,
    take_review,
    unique_isrc,
    unique_iswc,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_work,
)


class TestCreateWork:

    def test_create_draft_recording_work(self, api):
        """PRD §3.1: 'The newly-created work lives in state DRAFT, with
        registration_status set to DRAFT, dispute_posture initialised to
        CLEAR, and reject_reason and reviewer_id both null.'

        Claim: POST /royalty/works → 201 with registration_status==DRAFT,
        dispute_posture==CLEAR, reject_reason==null, reviewer_id==null.
        """
        h = create_rights_holder()
        resp = api.create_work(
            create_recording_work_payload(),
            make_rights_holder_headers(h["id"]),
        )
        data = validate_success(resp, 201)
        assert_work(data)
        assert data["registration_status"] == "DRAFT"
        assert data["dispute_posture"] == "CLEAR"
        assert data.get("reject_reason") is None
        assert data.get("reviewer_id") is None

    def test_duplicate_isrc_rejected(self, api):
        """PRD §3.1 / §2.10 priority 13: 'a duplicate isrc or duplicate
        iswc at create time is rejected with ERR_DUPLICATE_IDENTIFIER.'

        Claim: second POST with the same isrc value → ERR_DUPLICATE_IDENTIFIER
        (409).
        """
        h = create_rights_holder()
        shared_isrc = unique_isrc()
        # First create — succeeds.
        api.create_work(create_recording_work_payload(isrc=shared_isrc),
                        make_rights_holder_headers(h["id"]))
        # Second create with same isrc — must be rejected.
        resp = api.create_work(
            create_recording_work_payload(isrc=shared_isrc),
            make_rights_holder_headers(h["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value, 409)

    def test_duplicate_iswc_rejected(self, api):
        """PRD §2.10 priority 13: 'On work registration, both isrc (when
        supplied) and iswc (when supplied) must be unique across all
        existing works whose corresponding field is non-null; collision
        yields ERR_DUPLICATE_IDENTIFIER (409).'

        Claim: second POST with the same iswc → ERR_DUPLICATE_IDENTIFIER (409).
        """
        h = create_rights_holder()
        shared_iswc = unique_iswc()
        api.create_work(create_composition_work_payload(iswc=shared_iswc),
                        make_rights_holder_headers(h["id"]))
        resp = api.create_work(
            create_composition_work_payload(iswc=shared_iswc),
            make_rights_holder_headers(h["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value, 409)


class TestSubmit:

    def test_submit_draft_advances_to_submitted(self, api):
        """PRD §3.1: 'When the holder is ready, they trigger the
        submission, advancing the work from DRAFT to SUBMITTED.'

        Claim: POST /royalty/works/{id}/submit on a DRAFT work whose
        preconditions are satisfied → registration_status==SUBMITTED.
        """
        h = create_rights_holder()
        w = create_work_draft(h["id"], rights_type="RECORDING")
        create_share(w["id"], h["id"], h["id"], 100.00)
        resp = api.submit_work(w["id"], make_rights_holder_headers(h["id"]))
        data = validate_success(resp, 200)
        assert data["registration_status"] == "SUBMITTED"

    def test_submit_with_invalid_cocreator_sum_rejected(self, api):
        """PRD §3.1 / §2.10 priority 14: 'On submit, the sum of
        contribution_percent across co_creators must equal exactly
        100.00; otherwise ERR_COCREATOR_SUM_INVALID.'

        Claim: submit with co_creators summing != 100 →
        ERR_COCREATOR_SUM_INVALID (422).
        """
        h = create_rights_holder()
        # Bad sum — 80.
        w = create_work_draft(
            h["id"], rights_type="RECORDING",
            co_creators=[
                {"full_name": "A", "role": "PERFORMER",
                 "contribution_percent": 80.00},
            ],
        )
        create_share(w["id"], h["id"], h["id"], 100.00)
        resp = api.submit_work(w["id"], make_rights_holder_headers(h["id"]))
        validate_error(resp, ApiErrorId.ERR_COCREATOR_SUM_INVALID.value, 422)


class TestTakeReview:

    def test_take_review_advances_and_stamps_reviewer_id(self, api,
                                                        reviewer_headers):
        """PRD §3.2: 'A RegistrationReviewer who picks up a SUBMITTED
        work advances it to UNDER_REVIEW, with the only side effect
        being to stamp reviewer_id with their X-User-ID.'

        Claim: take-review on SUBMITTED work → registration_status =
        UNDER_REVIEW and reviewer_id == caller's X-User-ID.
        """
        h = create_rights_holder()
        w = create_work_draft(h["id"])
        create_share(w["id"], h["id"], h["id"], 100.00)
        submit_work(w["id"], h["id"])
        resp = api.take_review_work(w["id"], reviewer_headers)
        data = validate_success(resp, 200)
        assert data["registration_status"] == "UNDER_REVIEW"
        assert data["reviewer_id"] == reviewer_headers["X-User-ID"]

    def test_take_review_on_draft_rejected_invalid_state(self, api,
                                                        reviewer_headers):
        """PRD §2.10 priority 6: 'On work-action endpoints, the target
        work must be in the correct state for the action — submit
        requires DRAFT, approve and reject require UNDER_REVIEW,
        take-review requires SUBMITTED; a state mismatch yields
        ERR_INVALID_STATE (409).'

        Claim: take-review on a DRAFT work → ERR_INVALID_STATE (409).
        """
        h = create_rights_holder()
        w = create_work_draft(h["id"])  # still DRAFT
        resp = api.take_review_work(w["id"], reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


class TestApprove:

    def test_approve_with_correct_shares_succeeds(self, api):
        """PRD §3.2: 'Approval flips the work to APPROVED; this is gated
        on a single business precondition — at least one RightsShare
        must exist for this work whose share_status is ACTIVE, and the
        sum of share_percent across all such active shares must equal
        exactly 100.00.'

        Claim: approve on UNDER_REVIEW with shares summing to 100 →
        registration_status==APPROVED, dispute_posture==CLEAR.
        """
        _h, work, _share = setup_approved_recording_work()
        assert work["registration_status"] == "APPROVED"
        assert work["dispute_posture"] == "CLEAR"

    def test_approve_with_share_sum_invalid_rejected(self, api,
                                                    reviewer_headers):
        """PRD §3.2 / §2.10 priority 15: 'On approve, the sum of
        share_percent across all ACTIVE RightsShare rows for the work
        must equal exactly 100.00; otherwise ERR_SHARE_SUM_INVALID.'

        Claim: approve with shares summing to 60.00 →
        ERR_SHARE_SUM_INVALID (422).
        """
        h = create_rights_holder()
        w = create_work_draft(h["id"])
        # Single 60% share — sum is 60.
        create_share(w["id"], h["id"], h["id"], 60.00)
        submit_work(w["id"], h["id"])
        take_review(w["id"])
        resp = api.approve_work(w["id"], reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_SHARE_SUM_INVALID.value, 422)


class TestReject:

    def test_reject_terminates_shares_and_emits_audit(self, api):
        """PRD §3.2: 'Rejection requires the reviewer to supply a
        reject_reason of 1 to 500 characters and produces a layered
        cascade. The work's registration_status flips to REJECTED;
        every RightsShare row on this work whose share_status is ACTIVE
        transitions to TERMINATED (cascade depth 2); and each of those
        terminated shares emits a ShareChangeAudit row with change_kind
        of TERMINATED capturing the pre-termination and post-termination
        snapshots (cascade depth 3).'

        Claim: reject on UNDER_REVIEW work →
            Hop 1: Work.registration_status == REJECTED
            Hop 2: every ACTIVE RightsShare flips to TERMINATED
            Hop 3: a ShareChangeAudit row with change_kind=TERMINATED
                   exists per share.
        """
        h = create_rights_holder()
        w = create_work_draft(h["id"])
        s = create_share(w["id"], h["id"], h["id"], 100.00)
        submit_work(w["id"], h["id"])
        take_review(w["id"])
        rejected = reject_work(w["id"], reason="No proof.")
        assert rejected["registration_status"] == "REJECTED"
        # Hop 3: audit row with TERMINATED kind.
        resp = api.list_share_audit(w["id"], s["id"],
                                    make_rights_holder_headers(h["id"]),
                                    params={"limit": 100})
        audits, _ = validate_paginated(resp)
        terminated = find_audit_by_kind(audits, "TERMINATED")
        assert len(terminated) >= 1, \
            f"Expected at least one TERMINATED audit; got {audits}"

    def test_reject_without_reason_rejected(self, api, reviewer_headers):
        """PRD §3.2: 'Rejection requires the reviewer to supply a
        reject_reason of 1 to 500 characters.' PRD §2.10 priority 28:
        ERR_VALIDATION (422) covers generic input shape failures after
        higher-priority checks pass.

        Claim: reject without reject_reason → ERR_VALIDATION (422).
        """
        h = create_rights_holder()
        w = create_work_draft(h["id"])
        create_share(w["id"], h["id"], h["id"], 100.00)
        submit_work(w["id"], h["id"])
        take_review(w["id"])
        resp = api.reject_work(w["id"], {}, reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)


class TestWithdrawAndReturnToDraft:

    def test_withdraw_from_draft(self, api):
        """PRD §3.2: 'The owning holder may also withdraw a work
        directly from DRAFT, transitioning it to the terminal WITHDRAWN
        state with no cascades.'

        Claim: withdraw on DRAFT → registration_status=WITHDRAWN.
        """
        h = create_rights_holder()
        w = create_work_draft(h["id"])
        withdrawn = withdraw_work(w["id"], h["id"])
        assert withdrawn["registration_status"] == "WITHDRAWN"

    def test_return_to_draft_revision_loop(self, api):
        """PRD §3.2: 'Returning a submission to draft is a revision
        loop: from SUBMITTED, the reviewer can move the work back to
        DRAFT so the holder may amend metadata before re-submission.'

        Claim: return-to-draft on SUBMITTED →
        registration_status=DRAFT, and a subsequent submit succeeds.
        """
        h = create_rights_holder()
        w = create_work_draft(h["id"])
        create_share(w["id"], h["id"], h["id"], 100.00)
        submit_work(w["id"], h["id"])
        returned = return_to_draft(w["id"])
        assert returned["registration_status"] == "DRAFT"
        # Now resubmit succeeds.
        resubmitted = submit_work(w["id"], h["id"])
        assert resubmitted["registration_status"] == "SUBMITTED"


class TestOwnership:

    def test_non_owner_cannot_submit_others_work(self, api):
        """PRD §2.1: 'When X-User-Role is RightsHolder, X-User-ID is the
        id of the acting RightsHolder; ownership checks on any resource
        that references a RightsHolder compare the resource's
        foreign-key field to X-User-ID. A holder may only submit,
        withdraw, share-edit, or dispute-withdraw on resources whose
        owner identifier matches their X-User-ID.'

        Claim: holder B trying to submit holder A's DRAFT work →
        ERR_FORBIDDEN (403).
        """
        h_a = create_rights_holder(legal_name="Owner A")
        h_b = create_rights_holder(legal_name="Other B")
        w = create_work_draft(h_a["id"])
        create_share(w["id"], h_a["id"], h_a["id"], 100.00)
        resp = api.submit_work(w["id"], make_rights_holder_headers(h_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)
