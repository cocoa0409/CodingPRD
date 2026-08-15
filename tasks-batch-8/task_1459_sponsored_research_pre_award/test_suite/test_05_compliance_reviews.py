"""Ancillary compliance reviews: lifecycle, gates, cascades (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    add_budget_line,
    approve_review,
    assert_compliance_review,
    create_proposal_payload,
    finalize_budget,
    get_proposal,
    get_success_data,
    make_awarded_proposal,
    make_context,
    make_org,
    make_pi_headers,
    make_proposal,
    make_rate_agreement,
    make_sub_commitment,
    open_review,
    pledge_and_approve_cost_share,
    reset_clock,
    route_proposal,
    validate_error,
    validate_success,
    verify_sub_commitment,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


class TestInfoRequestCycle:
    def _setup(self, api):
        reset_clock()
        ctx = make_context(sponsor_code="NIH")
        prop = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="Cyc",
                             fa_base_type="MTDC")
        review = open_review(prop["id"], "IRB")
        return ctx, prop, review

    def test_cycle_traversed_twice(self, api):
        """PRD §3.6: "Requesting information moves a `PENDING` review to
        `INFO_REQUESTED` carrying the officer's `question` ... A response returns
        an `INFO_REQUESTED` review to `PENDING`".

        Design: Difficulty/non_linear_state_machine/compliance_review_info_request_cycle
        """
        ctx, prop, review = self._setup(api)
        rid = review["id"]
        pi_headers = make_pi_headers(ctx["pi"]["id"])
        st1 = validate_success(
            api.request_review_info(rid, {"question": "consent form?"}, COMPLIANCE),
            200,
        )["status"]
        st2 = validate_success(
            api.respond_to_review(rid, {"response_note": "attached"}, pi_headers),
            200,
        )["status"]
        st3 = validate_success(
            api.request_review_info(rid, {"question": "recruitment?"}, COMPLIANCE),
            200,
        )["status"]
        st4 = validate_success(
            api.respond_to_review(rid, {"response_note": "attached v2"}, pi_headers),
            200,
        )["status"]
        assert st1 == "INFO_REQUESTED"
        assert st2 == "PENDING"
        assert st3 == "INFO_REQUESTED"
        assert st4 == "PENDING"

    def test_approval_stamps_default_validity(self, api):
        """PRD §3.6: "Approval stamps the validity window: `validity_days` comes
        from the approval payload's override when supplied, else the type default
        — 365 days for `IRB`, 1095 for `IACUC`, 730 for `EXPORT_CONTROL`, 365 for
        `CONFLICT_OF_INTEREST` — and `approved_until_at` is set to the approval
        clock time plus those days."

        Design: Difficulty/non_linear_state_machine/compliance_review_info_request_cycle
        """
        ctx, prop, review = self._setup(api)
        rid = review["id"]
        pi_headers = make_pi_headers(ctx["pi"]["id"])
        api.request_review_info(rid, {"question": "consent form?"}, COMPLIANCE)
        api.respond_to_review(rid, {"response_note": "attached"}, pi_headers)
        approved = validate_success(api.approve_review(rid, {}, COMPLIANCE), 200)
        assert_compliance_review(approved)
        assert approved["status"] == "APPROVED"
        assert approved["validity_days"] == 365
        # clock pinned at 2026-08-01T00:00:00Z + 365 days
        assert approved["approved_until_at"] == "2027-08-01T00:00:00Z"


class TestReviewGates:
    def test_approve_from_approved_rejected(self, api):
        """PRD §3.6: "Approval is the officer's again, from `PENDING` only
        (`ERR_REVIEW_INVALID_STATE` otherwise)".

        Design: Corner/state_machines/review_approve_from_approved_rejected
        """
        ctx = make_context()
        prop = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="R",
                             pi_effort_pct=10.00, fa_base_type="MTDC")
        review = open_review(prop["id"], "IACUC")
        approve_review(review["id"])
        resp = api.approve_review(review["id"], {}, COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_REVIEW_INVALID_STATE.value)

    def test_duplicate_active_review_rejected(self, api):
        """PRD §3.6: "At most one active review may exist per proposal and review
        type — active meaning `PENDING`, `INFO_REQUESTED`, or `APPROVED` — and a
        duplicate attempt is rejected with `ERR_DUPLICATE_ACTIVE_REVIEW`
        (HTTP 409)."

        Design: Corner/validations/duplicate_active_review_rejected
        """
        ctx = make_context()
        prop = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="Dup",
                             pi_effort_pct=10.00, fa_base_type="MTDC")
        open_review(prop["id"], "IRB")
        dup = api.create_compliance_review(prop["id"], {"review_type": "IRB"},
                                           COMPLIANCE)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_ACTIVE_REVIEW.value)
        other = api.create_compliance_review(prop["id"], {"review_type": "IACUC"},
                                             COMPLIANCE)
        # uniqueness is per (proposal, review_type)
        assert validate_success(other, 201)["review_type"] == "IACUC"

    def test_coi_approve_requires_disclosure(self, api):
        """PRD §3.6: "a `CONFLICT_OF_INTEREST` review cannot be approved while
        `disclosure_complete` is false — the attempt fails with
        `ERR_COI_DISCLOSURE_INCOMPLETE` (HTTP 422)."

        Design: Corner/validations/coi_approve_without_disclosure_rejected
        """
        ctx = make_context()
        prop = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="COI",
                             pi_effort_pct=10.00, fa_base_type="MTDC")
        review = open_review(prop["id"], "CONFLICT_OF_INTEREST",
                             disclosure_complete=False)
        resp = api.approve_review(review["id"], {}, COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_COI_DISCLOSURE_INCOMPLETE.value)

    def test_coi_approve_after_disclosure_supplied(self, api):
        """PRD §3.6: "The owning PI — and only the owning PI, on pain of
        `ERR_NOT_RESOURCE_OWNER` — responds, optionally including a
        `response_note` and a `disclosure_complete` value that is applied when
        supplied." and "a `CONFLICT_OF_INTEREST` review cannot be approved while
        `disclosure_complete` is false".

        Design: Corner/validations/coi_approve_without_disclosure_rejected
        """
        ctx = make_context()
        prop = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="COI",
                             pi_effort_pct=10.00, fa_base_type="MTDC")
        review = open_review(prop["id"], "CONFLICT_OF_INTEREST",
                             disclosure_complete=False)
        rid = review["id"]
        api.request_review_info(rid, {"question": "disclosure?"}, COMPLIANCE)
        api.respond_to_review(
            rid, {"response_note": "disclosed", "disclosure_complete": True},
            make_pi_headers(ctx["pi"]["id"]),
        )
        approved = validate_success(api.approve_review(rid, {}, COMPLIANCE), 200)
        assert approved["status"] == "APPROVED"


class TestDisapproveCascade:
    def _setup(self, api):
        """ROUTED proposal with APPROVED cost-share, VERIFIED sub commitment,
        and a PENDING IRB review."""
        reset_clock()
        ctx = make_context(sponsor_code="NIH")
        org = make_org(legal_name="Calm Sub", uei="UEI-CALM")
        prop = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="Casc")
        comm = make_sub_commitment(prop["id"], org["id"],
                                   subaward_amount_cents=1_000_000)
        verify_sub_commitment(comm["id"])
        add_budget_line(prop["id"], amount_cents=10_000_000)
        finalize_budget(prop["id"])
        pledge_and_approve_cost_share(prop["id"], 1_000_000)
        route_proposal(prop["id"])
        review = open_review(prop["id"], "IRB")
        before = get_proposal(prop["id"])
        return prop, comm, review, before

    def test_disapprove_forces_return_and_blocks_posture(self, api):
        """PRD §3.6: "the proposal's `compliance_posture` becomes `BLOCKED`; a
        proposal sitting in `ROUTED`, `INSTITUTIONALLY_APPROVED`, `SUBMITTED`,
        `JIT_REQUESTED`, or `NEGOTIATING` is forced back to
        `RETURNED_FOR_REVISION` with its `revision_count` incremented".

        Design: Difficulty/transitive_cascade/disapprove_cascade_releases_cost_share
        """
        prop, _comm, review, before = self._setup(api)
        assert before["total_approved_cost_share_cents"] == 1_000_000
        api.disapprove_review(review["id"], {"reason": "protocol risk"}, COMPLIANCE)
        data = get_proposal(prop["id"])
        assert data["status"] == "RETURNED_FOR_REVISION"
        assert data["revision_count"] == 1
        assert data["compliance_posture"] == "BLOCKED"

    def test_disapprove_releases_cost_share_and_stales_subs(self, api):
        """PRD §3.6: "that forced return then releases every `APPROVED`
        cost-share commitment and stales every `VERIFIED` subrecipient
        commitment, exactly as a director-initiated return would; the cost-share
        totals and adequacy are recomputed". PRD §3.4: "Finally,
        `is_cost_share_adequate` holds exactly when
        `total_effective_cost_share_cents` is at least the required minimum —
        equality is adequate — and it holds vacuously, whatever the commitments
        look like, when the opportunity does not require cost share."

        Design: Difficulty/transitive_cascade/disapprove_cascade_releases_cost_share
        """
        prop, _comm, review, _before = self._setup(api)
        api.disapprove_review(review["id"], {"reason": "protocol risk"}, COMPLIANCE)
        commitments = get_success_data(
            api.list_cost_share_commitments(prop["id"], DIRECTOR)
        )
        assert commitments[0]["status"] == "RELEASED"
        subs = get_success_data(
            api.list_subrecipient_commitments(prop["id"], DIRECTOR)
        )
        assert subs[0]["status"] == "STALE"
        data = get_proposal(prop["id"])
        assert data["total_approved_cost_share_cents"] == 0
        # The opportunity does not require cost share, so recomputed adequacy
        # holds vacuously (effective 0 >= required 0).
        assert data["is_cost_share_adequate"] is True


class TestReviewExpiryCascade:
    def _setup(self, api):
        """AWARDED proposal, FINAL rate, IRB approved for 10 days, handoff READY."""
        reset_clock()
        ctx = make_context()
        # FINAL rate so mark-ready's final-basis gate passes
        make_rate_agreement(initial_status="FINAL")
        env = make_awarded_proposal(ctx=ctx)
        prop_id = env["proposal"]["id"]
        review = open_review(prop_id, "IRB")
        approved = approve_review(review["id"], validity_days=10)
        handoff_id = env["handoff"]["id"]
        ready = validate_success(
            api.mark_handoff_ready(handoff_id, DIRECTOR), 200
        )
        return prop_id, review, approved, handoff_id, ready

    def test_approved_until_uses_payload_override(self, api):
        """PRD §3.6: "Approval stamps the validity window: `validity_days` comes
        from the approval payload's override when supplied, else the type
        default" and "`approved_until_at` is set to the approval clock time plus
        those days."

        Design: Corner/state_machines/review_expiry_blocks_ready_handoff
        """
        _prop, _review, approved, _h, ready = self._setup(api)
        assert approved["approved_until_at"] == "2026-08-11T00:00:00Z"
        assert ready["status"] == "READY"

    def test_sweep_expires_review_and_blocks_handoff(self, api):
        """PRD §3.6: "When the logical clock is set, any `APPROVED` review whose
        `approved_until_at` has fallen behind the current time becomes `EXPIRED`;
        the proposal's posture is recomputed — typically back to
        `REVIEW_PENDING` — and, per §3.9, a ready handoff of that proposal
        bubbles up to `BLOCKED`." PRD §3.9: "the moment any review of the
        proposal becomes `EXPIRED` or `DISAPPROVED`, a `READY` handoff
        automatically falls back to `BLOCKED` and its `compliance_verified` flag
        resets to false."

        Design: Corner/state_machines/review_expiry_blocks_ready_handoff
        """
        prop_id, _review, _approved, handoff_id, _ready = self._setup(api)
        reset_clock("2026-08-12T00:00:00Z")
        reviews = get_success_data(api.list_compliance_reviews(prop_id, DIRECTOR))
        assert reviews[0]["status"] == "EXPIRED"
        handoffs = get_success_data(api.list_award_handoffs(prop_id, DIRECTOR))
        assert handoffs[0]["status"] == "BLOCKED"
        assert handoffs[0]["compliance_verified"] is False
        assert get_proposal(prop_id)["compliance_posture"] == "REVIEW_PENDING"
