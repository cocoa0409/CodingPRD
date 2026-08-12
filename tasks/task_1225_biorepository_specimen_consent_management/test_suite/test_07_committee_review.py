"""Committee review: quorum boundaries, revision cycle cap, ballot guards, voter identity."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_active_agreement,
    create_draft_request,
    create_under_review_request,
    cast_approve_vote,
    cast_reject_vote,
    submit_request,
    get_request,
    make_researcher_headers,
    make_reviewer_headers,
    create_vote_payload,
)


class TestQuorumExactApproval:
    """Inclusive quorum boundary on the approval side."""

    def test_two_approvals_leave_request_under_review(self, api):
        """PRD §3.6: "The committee numbers five members and decides by a quorum ratio
        of 0.6, making the quorum count three — five times 0.6 rounded up. `votes_for`
        counts `APPROVE` votes and `votes_against` counts `REJECT` votes in the current
        round. The moment `votes_for` reaches at least 3 the request auto-flips from
        `UNDER_REVIEW` to `APPROVED`"

        Design: Difficulty/boundary_precision_check/quorum_exact_approval
        """
        agreement = create_active_agreement(total_committed_volume_ml=100.0)
        request = create_under_review_request(agreement["id"], volume_needed_ml=5.0)
        cast_approve_vote(request["id"], "rev-1")
        cast_approve_vote(request["id"], "rev-2")
        request = get_request(request["id"])
        assert request["votes_for"] == 2
        assert request["status"] == "UNDER_REVIEW", "2 < 3: quorum not yet reached"

    def test_third_approval_flips_to_approved(self, api):
        """PRD §3.6: "The moment `votes_for` reaches at least 3 the request auto-flips
        from `UNDER_REVIEW` to `APPROVED`; the moment `votes_against` reaches at least
        3 — the committee size minus the quorum count plus one — it auto-flips to
        `REJECTED`. Both boundaries are inclusive: exactly three approvals approve,
        exactly three rejections reject."

        Design: Difficulty/boundary_precision_check/quorum_exact_approval
        """
        agreement = create_active_agreement(total_committed_volume_ml=100.0)
        request = create_under_review_request(agreement["id"], volume_needed_ml=5.0)
        for reviewer in ("rev-1", "rev-2", "rev-3"):
            cast_approve_vote(request["id"], reviewer)
        request = get_request(request["id"])
        assert request["votes_for"] == 3
        assert request["status"] == "APPROVED", "3 >= 3: inclusive boundary must approve"


def test_quorum_rejection_threshold(api):
    """PRD §3.6: "the moment `votes_against` reaches at least 3 — the committee size
    minus the quorum count plus one — it auto-flips to `REJECTED`. Both boundaries are
    inclusive: exactly three approvals approve, exactly three rejections reject."

    Design: Corner/calculations/quorum_rejection_threshold
    """
    agreement = create_active_agreement(total_committed_volume_ml=100.0)
    request = create_under_review_request(agreement["id"], volume_needed_ml=5.0)
    cast_reject_vote(request["id"], "rev-1")
    cast_reject_vote(request["id"], "rev-2")
    request = get_request(request["id"])
    assert request["votes_against"] == 2
    assert request["status"] == "UNDER_REVIEW"
    cast_reject_vote(request["id"], "rev-3")
    request = get_request(request["id"])
    assert request["votes_against"] == 3
    assert request["status"] == "REJECTED"


class TestSampleRequestRevisionCycle:
    """Bounded revision cycle: UNDER_REVIEW -> REVISION_REQUESTED -> UNDER_REVIEW,
    revision_round incrementing per loop, hard cap of 2."""

    def _cycle_once(self, api, request_id, researcher_id, reviewer_id, rationale):
        resp = api.request_revision(request_id, {"rationale": rationale},
                                    make_reviewer_headers(reviewer_id))
        validate_success(resp, expected_status=200)
        submit_request(request_id, researcher_id)

    def test_revision_round_increments_per_cycle(self, api):
        """PRD §3.6: "From `REVISION_REQUESTED`, resubmission additionally requires
        `revision_round` to still be below the hard cap of 2 rounds, failing at the cap
        with `ERR_MAX_REVISION_ROUNDS` (HTTP 409), and increments `revision_round` by
        one on success."

        Design: Difficulty/non_linear_state_machine/sample_request_revision_cycle
        """
        agreement = create_active_agreement(total_committed_volume_ml=100.0)
        request = create_under_review_request(agreement["id"], volume_needed_ml=5.0)
        self._cycle_once(api, request["id"], "researcher-1", "rev-1",
                         "please clarify cohort selection criteria")
        request = get_request(request["id"])
        assert request["revision_round"] == 1
        assert request["status"] == "UNDER_REVIEW"
        self._cycle_once(api, request["id"], "researcher-1", "rev-2",
                         "still missing ethics attachment text")
        request = get_request(request["id"])
        assert request["revision_round"] == 2
        assert request["status"] == "UNDER_REVIEW"

    def test_third_request_revision_rejected(self, api):
        """PRD §3.6: "Requesting a revision requires the request to be `UNDER_REVIEW`
        (`ERR_REQUEST_NOT_UNDER_REVIEW`) and `revision_round` still below 2
        (`ERR_MAX_REVISION_ROUNDS`), and takes a `rationale` subject to the same
        20-character minimum (`ERR_JUSTIFICATION_TOO_SHORT`)."

        Design: Difficulty/non_linear_state_machine/sample_request_revision_cycle
        """
        agreement = create_active_agreement(total_committed_volume_ml=100.0)
        request = create_under_review_request(agreement["id"], volume_needed_ml=5.0)
        self._cycle_once(api, request["id"], "researcher-1", "rev-1",
                         "please clarify cohort selection criteria")
        self._cycle_once(api, request["id"], "researcher-1", "rev-2",
                         "still missing ethics attachment text")
        resp = api.request_revision(request["id"],
                                    {"rationale": "third revision should be refused now"},
                                    make_reviewer_headers("rev-3"))
        validate_error(resp, ApiErrorId.ERR_MAX_REVISION_ROUNDS)


def test_vote_on_draft_request_rejected(api):
    """PRD §3.6: "Four checks guard the ballot, in this order: the request must be
    `UNDER_REVIEW`, failing as `ERR_REQUEST_NOT_UNDER_REVIEW` (HTTP 409); the reviewer
    must not be the request's own requester, failing as `ERR_SEGREGATION_OF_DUTIES`"

    Design: Corner/state_machines/vote_on_draft_request_rejected
    """
    agreement = create_active_agreement(total_committed_volume_ml=100.0)
    request = create_draft_request(agreement["id"], title="RQ-DRAFT", volume_needed_ml=5.0)
    resp = api.cast_vote(request["id"], create_vote_payload(), make_reviewer_headers("rev-1"))
    validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_UNDER_REVIEW)


def test_duplicate_vote_rejected(api):
    """PRD §3.6: "the reviewer must not already have voted on this request in the
    current review round, failing as `ERR_DUPLICATE_VOTE` (HTTP 409)"

    Design: Corner/validations/duplicate_vote_rejected
    """
    agreement = create_active_agreement(total_committed_volume_ml=100.0)
    request = create_under_review_request(agreement["id"], volume_needed_ml=5.0)
    cast_approve_vote(request["id"], "rev-1")
    resp = api.cast_vote(
        request["id"],
        create_vote_payload(decision="REJECT", rationale="changed my mind on this one"),
        make_reviewer_headers("rev-1"),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_VOTE)
    request = get_request(request["id"])
    assert request["votes_for"] == 1
    assert request["votes_against"] == 0


def test_requester_cannot_vote_on_own_request(api):
    """PRD §2.9: "A committee reviewer may not vote on a sample request they themselves
    submitted — the reviewer's `X-User-ID` must differ from the request's
    `requester_user_id`."

    Design: Corner/validations/requester_cannot_vote_on_own_request
    """
    agreement = create_active_agreement(total_committed_volume_ml=100.0)
    request = create_under_review_request(agreement["id"], volume_needed_ml=5.0)
    resp = api.cast_vote(
        request["id"],
        create_vote_payload(rationale="self review should never pass here"),
        make_reviewer_headers("researcher-1"),  # same user id as the requester
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def test_vote_rationale_too_short_rejected(api):
    """PRD §3.6: "A `CommitteeReviewer` casts a vote with a `decision` of `APPROVE` or
    `REJECT` and a free-text `rationale` of at least 20 characters, failing shorter
    input with `ERR_JUSTIFICATION_TOO_SHORT` (HTTP 400)."

    Design: Corner/validations/vote_rationale_too_short_rejected
    """
    agreement = create_active_agreement(total_committed_volume_ml=100.0)
    request = create_under_review_request(agreement["id"], volume_needed_ml=5.0)
    resp = api.cast_vote(
        request["id"],
        create_vote_payload(decision="APPROVE", rationale="short"),
        make_reviewer_headers("rev-1"),
    )
    validate_error(resp, ApiErrorId.ERR_JUSTIFICATION_TOO_SHORT)


def test_agreement_scope_insufficient_at_request_create(api):
    """PRD §3.6: "At creation the referenced agreement's `scope_uses` must cover every
    element of `required_uses`, failing otherwise with
    `ERR_AGREEMENT_SCOPE_INSUFFICIENT` (HTTP 409)."

    Design: Corner/validations/agreement_scope_insufficient_at_request_create
    """
    agreement = create_active_agreement(total_committed_volume_ml=100.0,
                                        scope_uses=["GENERAL_RESEARCH"])
    resp = api.create_sample_request(
        {"title": "RQ-SCOPE", "required_uses": ["GENETIC_ANALYSIS"],
         "specimen_type": "BLOOD", "volume_needed_ml": 5.0,
         "sharing_agreement_id": agreement["id"]},
        make_researcher_headers("researcher-1"),
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_SCOPE_INSUFFICIENT)


def test_reviewer_identity_recorded_on_vote(api):
    """PRD §3.6: "Each vote is an immutable `ReviewVote` record carrying the
    `sample_request_id` it was cast on and the reviewer's `reviewer_user_id`."
    PRD §3.6: "The creating user's `X-User-ID` is recorded as `requester_user_id`."

    Design: Corner/rbac/reviewer_identity_recorded_on_vote
    """
    agreement = create_active_agreement(total_committed_volume_ml=100.0)
    request = create_under_review_request(agreement["id"], volume_needed_ml=5.0)
    resp = api.cast_vote(
        request["id"],
        create_vote_payload(rationale="identity recording check vote ok"),
        make_reviewer_headers("rev-7"),
    )
    vote = validate_success(resp, expected_status=201)
    assert vote["reviewer_user_id"] == "rev-7"
    request = get_request(request["id"])
    assert request["requester_user_id"] == "researcher-1"
