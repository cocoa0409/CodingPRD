"""State-machine transitions: proposal revision cycle, deliverable parallel axes,
engagement lifecycle, match lifecycle, revision-request lifecycle, and their
preconditions. Difficulty queue rule 3 plus corner-design state_machines.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, fixtures,
    TEST_USERS, ApiErrorId, make_client_contact_headers,
)

AM = TEST_USERS["account_manager_headers"]
GW = TEST_USERS["grant_writer_headers"]


# ==========================================================================
# Difficulty Rule 3 — non_linear_state_machine
# ==========================================================================
class TestNonLinearStateMachines:
    def test_proposal_revision_cycle_increments_round_each_loop(self, api):
        """PRD §3.6: "This is the revision-cycle edge and may repeat: a proposal can
        go `IN_REVIEW`, back to `DRAFTING`, and into `IN_REVIEW` again. Requesting
        changes increments the proposal's `revision_round` by one and, as a cascade,
        resets every deliverable under that proposal whose `approval_status` is
        `APPROVED` back to `CHANGES_REQUESTED`, so previously cleared work must be
        re-blessed after substantive changes."

        Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_in_review_back_to_drafting
        """
        ctx = fixtures.setup_review_ready_proposal()
        prop_id = ctx["proposal"]["id"]
        cc = make_client_contact_headers(ctx["client"]["id"])
        get_success_data(api.submit_proposal_for_review(prop_id, GW))
        get_success_data(api.request_changes_proposal(prop_id, cc))      # round -> 1
        get_success_data(api.submit_proposal_for_review(prop_id, GW))
        get_success_data(api.request_changes_proposal(prop_id, cc))      # round -> 2
        prop = fixtures.get_proposal(prop_id)
        assert prop["status"] == "DRAFTING", f"expected DRAFTING, got {prop['status']}"
        assert prop["revision_round"] == 2, f"expected 2, got {prop['revision_round']}"

    def test_proposal_revision_round_starts_at_zero_increments_to_one(self, api):
        """PRD §3.4: "A new proposal opens in `DRAFTING` with its `revision_round`
        at zero and its computed `budget_total_cents` at zero. The `revision_round`
        increments by one each time the proposal returns from `IN_REVIEW` to
        `DRAFTING`."

        Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_in_review_back_to_drafting
        """
        ctx = fixtures.setup_review_ready_proposal()
        prop_id = ctx["proposal"]["id"]
        assert ctx["proposal"]["revision_round"] == 0
        cc = make_client_contact_headers(ctx["client"]["id"])
        get_success_data(api.submit_proposal_for_review(prop_id, GW))
        get_success_data(api.request_changes_proposal(prop_id, cc))
        prop = fixtures.get_proposal(prop_id)
        assert prop["revision_round"] == 1, f"expected 1, got {prop['revision_round']}"
        assert prop["status"] == "DRAFTING"

    def test_deliverable_content_axis_advances_independently_of_approval(self, api):
        """PRD §3.4: "A deliverable carries two genuinely independent state
        dimensions. Its `content_status` describes the maturity of the writing and
        runs `OUTLINE`, `DRAFTED`, `FINAL`; its `approval_status` describes the
        client's verdict and runs `UNREVIEWED`, `CHANGES_REQUESTED`, `APPROVED`."

        Design: Difficulty/non_linear_state_machine/deliverable_parallel_content_and_approval_axes_evolve_independently
        """
        ctx = fixtures.setup_drafting_proposal()
        cc = make_client_contact_headers(ctx["client"]["id"])
        deliv = fixtures.add_deliverable(ctx["proposal"]["id"], body="drafted body")
        get_success_data(api.advance_deliverable_content(deliv["id"], GW))
        get_success_data(api.approve_deliverable(deliv["id"], cc))
        d = fixtures.get_deliverable(deliv["id"])
        assert d["content_status"] == "DRAFTED", f"expected DRAFTED, got {d['content_status']}"
        assert d["approval_status"] == "APPROVED", f"expected APPROVED, got {d['approval_status']}"

    def test_deliverable_approve_from_unreviewed_leaves_content_outline_path(self, api):
        """PRD §3.5: "Approving directly from `UNREVIEWED` is also allowed, but in
        that case both conditions are checked: the `content_status` must be
        `DRAFTED` or `FINAL` (otherwise `ERR_NOT_REVIEWABLE`) and
        `open_revision_count` must be zero (otherwise
        `ERR_OPEN_REVISIONS_BLOCK_APPROVAL`)."

        Design: Difficulty/non_linear_state_machine/deliverable_parallel_content_and_approval_axes_evolve_independently
        """
        ctx = fixtures.setup_drafting_proposal()
        cc = make_client_contact_headers(ctx["client"]["id"])
        deliv = fixtures.add_deliverable(ctx["proposal"]["id"], body="drafted body")
        # Advance content to DRAFTED first (approve-from-UNREVIEWED needs DRAFTED/FINAL).
        get_success_data(api.advance_deliverable_content(deliv["id"], GW))
        get_success_data(api.approve_deliverable(deliv["id"], cc))
        d = fixtures.get_deliverable(deliv["id"])
        # Approval advanced while content_status remains exactly DRAFTED (independent axes).
        assert d["approval_status"] == "APPROVED"
        assert d["content_status"] == "DRAFTED"


# ==========================================================================
# Corner — state_machines: valid transitions
# ==========================================================================
class TestValidTransitions:
    def test_engagement_activate_draft_to_active(self, api):
        """PRD §3.2: "An account manager activates it, moving `DRAFT` to `ACTIVE`,
        but only when two conditions hold."

        Design: Corner/state_machines/engagement_activate_from_draft_to_active_valid_transition
        """
        client = fixtures.create_client()
        eng = fixtures.create_engagement(client["id"], fee_model="HOURLY", hourly_rate_cents=12000)
        out = validate_success(api.activate_engagement(eng["id"], AM), 200)
        assert out["status"] == "ACTIVE", f"expected ACTIVE, got {out['status']}"

    def test_engagement_pause_then_reactivate_cycle(self, api):
        """PRD §3.2: "An `ACTIVE` engagement may be paused, moving `ACTIVE` to
        `PAUSED`, with no further precondition. A `PAUSED` engagement may be
        reactivated, moving `PAUSED` back to `ACTIVE`, again only while the owning
        client is `ACTIVE` (otherwise `ERR_CLIENT_NOT_ACTIVE`)."

        Design: Corner/state_machines/engagement_pause_then_reactivate_cycle
        """
        client = fixtures.create_client()
        eng = fixtures.create_active_engagement(client["id"], fee_model="HOURLY",
                                                hourly_rate_cents=12000)
        get_success_data(api.pause_engagement(eng["id"], AM))
        out = validate_success(api.activate_engagement(eng["id"], AM), 200)
        assert out["status"] == "ACTIVE", f"expected ACTIVE, got {out['status']}"

    def test_match_decline_from_proposed(self, api):
        """PRD §3.3: "Declining from `PROPOSED` to the terminal `DECLINED` state is
        unconditional."

        Design: Corner/state_machines/match_decline_from_proposed_valid_transition
        """
        client = fixtures.create_client()
        opp = fixtures.create_opportunity()
        m = get_success_data(api.create_match(
            {"client_id": client["id"], "opportunity_id": opp["id"]}, AM))
        out = validate_success(api.decline_match(m["id"], AM), 200)
        assert out["status"] == "DECLINED", f"expected DECLINED, got {out['status']}"


# ==========================================================================
# Corner — state_machines: precondition enforcement
# ==========================================================================
class TestPreconditionEnforcement:
    def test_engagement_activate_fee_model_incomplete(self, api):
        """PRD §3.2: "a `SUCCESS_FEE` engagement needs `success_fee_pct` greater
        than zero ... A model missing its required fee field is rejected with
        `ERR_FEE_MODEL_INCOMPLETE`."

        Design: Corner/state_machines/engagement_activate_fee_model_incomplete_precondition
        """
        client = fixtures.create_client()
        eng = get_success_data(api.create_engagement(
            {"client_id": client["id"], "fee_model": "SUCCESS_FEE"}, AM))
        validate_error(api.activate_engagement(eng["id"], AM),
                       ApiErrorId.ERR_FEE_MODEL_INCOMPLETE.value)

    def test_engagement_activate_client_not_active(self, api):
        """PRD §3.2: "The owning client must currently be `ACTIVE`; if it is not, the
        activation is rejected with `ERR_CLIENT_NOT_ACTIVE`."

        Design: Corner/state_machines/engagement_activate_client_not_active_precondition
        """
        client = fixtures.create_client()
        eng = fixtures.create_engagement(client["id"], fee_model="HOURLY", hourly_rate_cents=12000)
        get_success_data(api.suspend_client(client["id"], AM))
        validate_error(api.activate_engagement(eng["id"], AM),
                       ApiErrorId.ERR_CLIENT_NOT_ACTIVE.value)

    def test_engagement_close_with_open_work_rejected(self, api):
        """PRD §3.2: "An engagement may be closed from either `ACTIVE` or `PAUSED`,
        moving it to the terminal `CLOSED` state, but only when no proposal under
        that engagement is still in `DRAFTING` or `IN_REVIEW`; open work blocks
        closure with `ERR_ENGAGEMENT_HAS_OPEN_WORK`."

        Design: Corner/state_machines/engagement_close_with_open_work_rejected
        """
        ctx = fixtures.setup_drafting_proposal()
        validate_error(api.close_engagement(ctx["engagement"]["id"], AM),
                       ApiErrorId.ERR_ENGAGEMENT_HAS_OPEN_WORK.value)

    def test_proposal_approve_with_unapproved_deliverable_rejected(self, api):
        """PRD §3.6: "the owning contact may approve the proposal, moving it from
        `IN_REVIEW` to `APPROVED`, but only when every deliverable under the
        proposal has `approval_status` equal to `APPROVED`; if any deliverable is
        not approved, the request is rejected with `ERR_DELIVERABLES_NOT_APPROVED`."

        Design: Corner/state_machines/proposal_approve_with_unapproved_deliverable_rejected
        """
        ctx = fixtures.setup_review_ready_proposal()
        prop_id = ctx["proposal"]["id"]
        cc = make_client_contact_headers(ctx["client"]["id"])
        get_success_data(api.submit_proposal_for_review(prop_id, GW))
        validate_error(api.approve_proposal(prop_id, cc),
                       ApiErrorId.ERR_DELIVERABLES_NOT_APPROVED.value)

    def test_proposal_submit_for_review_no_narrative_rejected(self, api):
        """PRD §3.6: "The proposal must have at least one deliverable whose `kind`
        is `NARRATIVE`, or it is rejected with `ERR_NO_NARRATIVE`."

        Design: Corner/state_machines/proposal_submit_for_review_no_narrative_rejected
        """
        ctx = fixtures.setup_drafting_proposal()
        fixtures.add_budget_line(ctx["proposal"]["id"], amount_cents=100000)
        validate_error(api.submit_proposal_for_review(ctx["proposal"]["id"], GW),
                       ApiErrorId.ERR_NO_NARRATIVE.value)

    def test_proposal_submit_for_review_empty_budget_rejected(self, api):
        """PRD §3.6: "And the proposal's `budget_total_cents` must be greater than
        zero, or it is rejected with `ERR_EMPTY_BUDGET`."

        Design: Corner/state_machines/proposal_submit_for_review_empty_budget_rejected
        """
        ctx = fixtures.setup_drafting_proposal()
        fixtures.add_deliverable(ctx["proposal"]["id"], body="b")
        validate_error(api.submit_proposal_for_review(ctx["proposal"]["id"], GW),
                       ApiErrorId.ERR_EMPTY_BUDGET.value)

    def test_deliverable_advance_content_empty_body_rejected(self, api):
        """PRD §3.5: "Moving `content_status` from `OUTLINE` to `DRAFTED` requires
        that the deliverable's `body` is non-empty; an empty body is rejected with
        `ERR_EMPTY_BODY`."

        Design: Corner/state_machines/deliverable_advance_content_empty_body_rejected
        """
        ctx = fixtures.setup_drafting_proposal()
        deliv = get_success_data(api.create_deliverable(
            {"proposal_id": ctx["proposal"]["id"], "kind": "NARRATIVE", "title": "Empty"}, GW))
        validate_error(api.advance_deliverable_content(deliv["id"], GW),
                       ApiErrorId.ERR_EMPTY_BODY.value)

    def test_deliverable_approve_with_open_revision_blocked(self, api):
        """PRD §3.5: "From `CHANGES_REQUESTED` this requires only that
        `open_revision_count` is zero — every revision request resolved or
        superseded — otherwise the approval is rejected with
        `ERR_OPEN_REVISIONS_BLOCK_APPROVAL`."

        Design: Corner/state_machines/deliverable_approve_with_open_revision_blocked
        """
        ctx = fixtures.setup_drafted_deliverable_with_open_revision()
        cc = make_client_contact_headers(ctx["client"]["id"])
        validate_error(api.approve_deliverable(ctx["deliverable"]["id"], cc),
                       ApiErrorId.ERR_OPEN_REVISIONS_BLOCK_APPROVAL.value)

    def test_deliverable_advance_final_blocked_by_open_revisions(self, api):
        """PRD §3.5: "Moving `content_status` from `DRAFTED` to `FINAL` requires
        that the deliverable has no open revision requests — its
        `open_revision_count` must be zero — otherwise the advance is rejected with
        `ERR_OPEN_REVISIONS_BLOCK_FINAL`."

        Design: Corner/state_machines/deliverable_advance_content_final_blocked_by_open_revisions
        """
        ctx = fixtures.setup_drafted_deliverable_with_open_revision()
        validate_error(api.advance_deliverable_content(ctx["deliverable"]["id"], GW),
                       ApiErrorId.ERR_OPEN_REVISIONS_BLOCK_FINAL.value)

    def test_award_close_out_with_outstanding_report_rejected(self, api):
        """PRD §3.9: "a `ComplianceOfficer` closes out an award, moving it from
        `ACTIVE` to the terminal `CLOSED_OUT` state, but only when the award has no
        compliance report still in `PENDING` or `LATE`; any outstanding report
        blocks close-out with `ERR_REPORTS_OUTSTANDING`."

        Design: Corner/state_machines/award_close_out_with_outstanding_report_rejected
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_active_award(period_of_performance_months=12, report_cadence_months=3)
        CO = TEST_USERS["compliance_officer_headers"]
        validate_error(api.close_out_award(ctx["award"]["id"], CO),
                       ApiErrorId.ERR_REPORTS_OUTSTANDING.value)


# ==========================================================================
# Corner — state_machines: side effects, invalid transitions, idempotency
# ==========================================================================
class TestStateSideEffectsAndInvalid:
    def test_revision_resolve_recomputes_open_count(self, api):
        """PRD §3.5: "A `GrantWriter` resolves an open revision request, moving it
        from `OPEN` to `RESOLVED` and recomputing the owning deliverable's
        `open_revision_count` downward."

        Design: Corner/state_machines/revision_resolve_recomputes_open_count_then_approval_succeeds
        """
        ctx = fixtures.setup_drafted_deliverable_with_open_revision()
        get_success_data(api.resolve_revision_request(ctx["revision"]["id"], GW))
        rev = fixtures.get_revision_request(ctx["revision"]["id"])
        assert rev["status"] == "RESOLVED", f"expected RESOLVED, got {rev['status']}"
        d = fixtures.get_deliverable(ctx["deliverable"]["id"])
        assert d["open_revision_count"] == 0, f"expected 0, got {d['open_revision_count']}"

    def test_revision_supersede_marks_prior_superseded(self, api):
        """PRD §3.5: "When a `supersedes_revision_id` is given, the referenced open
        request transitions to `SUPERSEDED` as the new one is created; the
        superseded request no longer counts toward the open count while the new one
        does, and the deliverable's `open_revision_count` reflects that net change."

        Design: Corner/state_machines/revision_supersede_marks_prior_superseded
        """
        ctx = fixtures.setup_drafted_deliverable_with_open_revision()
        cc = make_client_contact_headers(ctx["client"]["id"])
        rev2 = validate_success(api.create_revision_request(
            {"deliverable_id": ctx["deliverable"]["id"], "note": "replacement",
             "supersedes_revision_id": ctx["revision"]["id"]}, cc), 201)
        rev1 = fixtures.get_revision_request(ctx["revision"]["id"])
        assert rev1["status"] == "SUPERSEDED", f"expected SUPERSEDED, got {rev1['status']}"
        assert rev2["status"] == "OPEN", f"expected OPEN, got {rev2['status']}"
        d = fixtures.get_deliverable(ctx["deliverable"]["id"])
        assert d["open_revision_count"] == 1, f"expected 1, got {d['open_revision_count']}"

    def test_request_changes_resets_approved_deliverable(self, api):
        """PRD §3.6: "Requesting changes increments the proposal's `revision_round`
        by one and, as a cascade, resets every deliverable under that proposal
        whose `approval_status` is `APPROVED` back to `CHANGES_REQUESTED`, so
        previously cleared work must be re-blessed after substantive changes."

        Design: Corner/state_machines/request_changes_resets_approved_deliverable_to_changes_requested
        """
        ctx = fixtures.setup_review_ready_proposal()
        prop_id = ctx["proposal"]["id"]
        cc = make_client_contact_headers(ctx["client"]["id"])
        get_success_data(api.advance_deliverable_content(ctx["deliverable"]["id"], GW))
        get_success_data(api.approve_deliverable(ctx["deliverable"]["id"], cc))
        get_success_data(api.submit_proposal_for_review(prop_id, GW))
        get_success_data(api.request_changes_proposal(prop_id, cc))
        prop = fixtures.get_proposal(prop_id)
        assert prop["status"] == "DRAFTING"
        assert prop["revision_round"] == 1
        d = fixtures.get_deliverable(ctx["deliverable"]["id"])
        assert d["approval_status"] == "CHANGES_REQUESTED", \
            f"expected CHANGES_REQUESTED, got {d['approval_status']}"

    def test_decline_from_declined_invalid_state(self, api):
        """PRD §2.5: "on a state-transition endpoint, the target resource must
        currently be in a state from which the transition is allowed
        (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/cancel_match_from_declined_invalid_transition
        """
        client = fixtures.create_client()
        opp = fixtures.create_opportunity()
        m = get_success_data(api.create_match(
            {"client_id": client["id"], "opportunity_id": opp["id"]}, AM))
        get_success_data(api.decline_match(m["id"], AM))
        validate_error(api.decline_match(m["id"], AM), ApiErrorId.ERR_INVALID_STATE.value)

    def test_submit_for_review_twice_invalid_state(self, api):
        """PRD §2.5: "on a state-transition endpoint, the target resource must
        currently be in a state from which the transition is allowed
        (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/submit_for_review_from_already_in_review_invalid_state
        """
        ctx = fixtures.setup_review_ready_proposal()
        get_success_data(api.submit_proposal_for_review(ctx["proposal"]["id"], GW))
        validate_error(api.submit_proposal_for_review(ctx["proposal"]["id"], GW),
                       ApiErrorId.ERR_INVALID_STATE.value)
