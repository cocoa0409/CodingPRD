"""Proposal lifecycle: creation gates, submit ceilings, review quorum, the
cyclic negotiation loop, PATCH reset semantics, tier computation, OCC."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_gift_officer_headers,
    create_prospect, create_fundraiser, rate_prospect, assign_prospect,
    move_prospect, get_prospect, get_fundraiser, get_proposal,
    create_proposal_for, create_submitted_proposal, create_approved_proposal,
    setup_rated_assigned_prospect, create_proposal_payload,
)

RES = TEST_USERS["researcher_headers"]
DIR = TEST_USERS["director_headers"]
VP = TEST_USERS["vp_headers"]
VP2 = TEST_USERS["vp2_headers"]


class TestProposalCreationGates:
    """Queue A: cross_entity_state_dependency / proposal_requires_rated_prospect."""

    def test_proposal_rejected_while_in_screening_then_allowed_when_rated(self, api):
        """PRD §3.4: "Creation is gated on the prospect's readiness:
        `research_status` must be `RATED` (otherwise `ERR_PROSPECT_NOT_RATED`)
        and `moves_stage` must be one of `CULTIVATION`, `SOLICITATION`, or
        `NEGOTIATION` (otherwise `ERR_PROSPECT_NOT_SOLICITABLE`)."

        Design: Difficulty/cross_entity_state_dependency/proposal_requires_rated_prospect
        """
        f = create_fundraiser()
        p = create_prospect()
        # File an assessment but do NOT review it: prospect is IN_SCREENING.
        resp = api.create_assessment(p["id"], {
            "assessed_capacity_cents": 30000000, "engagement_score": 80,
            "philanthropy_score": 70, "recency_score": 60,
            "evidence_tier": "VERIFIED_DOCUMENT",
        }, RES)
        a = validate_success(resp, expected_status=201)
        assign_prospect(f["id"], p["id"])
        move_prospect(p["id"], f["id"], "CULTIVATION")

        officer = make_gift_officer_headers(f["id"])
        p_now = get_prospect(p["id"], officer)
        resp = api.create_proposal(
            create_proposal_payload(p["id"], p_now["version"]), officer,
        )
        validate_error(resp, ApiErrorId.ERR_PROSPECT_NOT_RATED)

        # Approve the assessment: the cross-entity dependency flips to RATED.
        validate_success(api.review_assessment(a["id"], {"decision": "APPROVE"}, DIR))
        p_rated = get_prospect(p["id"], officer)
        assert p_rated["research_status"] == "RATED"
        prop = create_proposal_for(p["id"], f["id"], 1000000)
        assert prop["status"] == "DRAFT"

    def test_proposal_rejected_on_identified_prospect(self, api):
        """PRD §3.4: "Creation is gated on the prospect's readiness:
        `research_status` must be `RATED` (otherwise `ERR_PROSPECT_NOT_RATED`)
        and `moves_stage` must be one of `CULTIVATION`, `SOLICITATION`, or
        `NEGOTIATION` (otherwise `ERR_PROSPECT_NOT_SOLICITABLE`)."

        Design: Difficulty/cross_entity_state_dependency/proposal_requires_rated_prospect
        """
        f = create_fundraiser()
        p = create_prospect()  # IDENTIFIED, never screened
        assign_prospect(f["id"], p["id"])
        move_prospect(p["id"], f["id"], "CULTIVATION")
        officer = make_gift_officer_headers(f["id"])
        p_now = get_prospect(p["id"], officer)
        resp = api.create_proposal(
            create_proposal_payload(p["id"], p_now["version"]), officer,
        )
        validate_error(resp, ApiErrorId.ERR_PROSPECT_NOT_RATED)

    def test_proposal_on_qualification_stage_rejected(self, api):
        """PRD §3.4: "`moves_stage` must be one of `CULTIVATION`, `SOLICITATION`,
        or `NEGOTIATION` (otherwise `ERR_PROSPECT_NOT_SOLICITABLE`)."

        Design: Corner/validations/proposal_on_qualification_stage_rejected
        """
        f = create_fundraiser()
        p = create_prospect()
        rate_prospect(p["id"])
        assign_prospect(f["id"], p["id"])
        officer = make_gift_officer_headers(f["id"])
        p_now = get_prospect(p["id"], officer)
        assert p_now["moves_stage"] == "QUALIFICATION"
        resp = api.create_proposal(
            create_proposal_payload(p["id"], p_now["version"]), officer,
        )
        validate_error(resp, ApiErrorId.ERR_PROSPECT_NOT_SOLICITABLE)


class TestProposalSubmitCeilings:
    def test_ask_exceeding_rated_capacity_rejected(self, api):
        """PRD §3.4: "First, the ask may not exceed the prospect's rated
        capacity: `ask_amount_cents` greater than the prospect's
        `rated_adjusted_capacity_cents` is rejected with
        `ERR_ASK_EXCEEDS_CAPACITY`."

        Design: Corner/validations/ask_exceeding_rated_capacity_rejected
        """
        f, p, _ = setup_rated_assigned_prospect(
            assessed_capacity_cents=30000000, move_to="CULTIVATION",
        )
        prop = create_proposal_for(p["id"], f["id"], 30000001)
        officer = make_gift_officer_headers(f["id"])
        resp = api.submit_proposal(prop["id"], officer)
        validate_error(resp, ApiErrorId.ERR_ASK_EXCEEDS_CAPACITY)

        prop_after = get_proposal(prop["id"])
        assert prop_after["status"] == "DRAFT"
        assert prop_after["approval_tier"] is None

    def test_open_ask_load_boundary_at_exact_cap(self, api):
        """PRD §3.4: "Second, the fundraiser's open-ask load may not exceed its
        ceiling: the fundraiser's `current_open_ask_cents` plus this proposal's
        `ask_amount_cents` must be no more than `max_open_ask_cents` — equality
        is allowed — otherwise the submission fails with
        `ERR_OPEN_ASK_LOAD_EXCEEDED`."

        Design: Corner/validations/open_ask_load_boundary_at_exact_cap
        """
        f = create_fundraiser(max_open_ask_cents=4000000)
        p = create_prospect()
        rate_prospect(p["id"])
        assign_prospect(f["id"], p["id"])
        move_prospect(p["id"], f["id"], "CULTIVATION")

        prop1 = create_submitted_proposal(p["id"], f["id"], 4000000)
        assert prop1["status"] == "UNDER_REVIEW"  # 0 + 4000000 <= 4000000

        prop2 = create_proposal_for(p["id"], f["id"], 1, designation_purpose="One cent more")
        officer = make_gift_officer_headers(f["id"])
        resp = api.submit_proposal(prop2["id"], officer)
        validate_error(resp, ApiErrorId.ERR_OPEN_ASK_LOAD_EXCEEDED)
        assert get_proposal(prop2["id"])["status"] == "DRAFT"


class TestProposalStateMachine:
    def test_proposal_submit_twice_rejected(self, api):
        """PRD §3.4: "The owning officer may submit from `DRAFT`, `RETURNED`,
        `REJECTED`, or `NEGOTIATING` (from any other state,
        `ERR_PROPOSAL_STATE_FORBIDS`)."

        Design: Corner/state_machines/proposal_submit_twice_rejected
        """
        f, p, _ = setup_rated_assigned_prospect(move_to="CULTIVATION")
        prop = create_submitted_proposal(p["id"], f["id"], 1000000)
        officer = make_gift_officer_headers(f["id"])
        resp = api.submit_proposal(prop["id"], officer)
        validate_error(resp, ApiErrorId.ERR_PROPOSAL_STATE_FORBIDS)

        prop_after = get_proposal(prop["id"])
        assert prop_after["status"] == "UNDER_REVIEW"
        assert prop_after["approval_tier"] == "STANDARD"

    def test_proposal_review_from_draft_rejected(self, api):
        """PRD §3.4: "A reviewer — `AdvancementDirector` or `VPAdvancement`,
        matching the tier's requirement or the request fails with
        `ERR_TIER_APPROVAL_ROLE_VIOLATION` — acts on a proposal in
        `UNDER_REVIEW` (otherwise `ERR_PROPOSAL_NOT_UNDER_REVIEW`)."

        Design: Corner/state_machines/proposal_review_from_draft_rejected
        """
        f, p, _ = setup_rated_assigned_prospect(move_to="CULTIVATION")
        prop = create_proposal_for(p["id"], f["id"], 1000000)
        resp = api.review_proposal(prop["id"], {"decision": "APPROVE"}, DIR)
        validate_error(resp, ApiErrorId.ERR_PROPOSAL_NOT_UNDER_REVIEW)

        prop_after = get_proposal(prop["id"])
        assert prop_after["status"] == "DRAFT"
        assert prop_after["approvals_received"] == 0

    def test_proposal_supersede_on_second_approval(self, api):
        """PRD §3.4: "approval is exclusive per prospect, so any other proposal
        of the same prospect currently `APPROVED` moves to `SUPERSEDED`."

        Design: Corner/state_machines/proposal_supersede_on_second_approval
        """
        f, p, _ = setup_rated_assigned_prospect(move_to="CULTIVATION")
        prop1 = create_approved_proposal(p["id"], f["id"], 1000000, designation_purpose="First")
        prop2 = create_approved_proposal(p["id"], f["id"], 2000000, designation_purpose="Second")

        assert get_proposal(prop2["id"])["status"] == "APPROVED"
        assert get_proposal(prop1["id"])["status"] == "SUPERSEDED"

    def test_principal_quorum_requires_two_distinct_vps(self, api):
        """PRD §3.4: "for `PRINCIPAL` the first approval merely leaves the
        proposal `UNDER_REVIEW` with `approvals_received` at 1, and only the
        second distinct `VPAdvancement` approval completes it. On the final
        approval the proposal becomes `APPROVED`, `decided_by` records the
        deciding reviewer, and `approved_at` is stamped from the logical clock."

        Design: Corner/state_machines/principal_quorum_requires_two_distinct_vps
        """
        f, p, _ = setup_rated_assigned_prospect(
            assessed_capacity_cents=200000000, move_to="CULTIVATION",
            max_open_ask_cents=1000000000,
        )
        prop = create_submitted_proposal(p["id"], f["id"], 100000000)
        assert prop["approval_tier"] == "PRINCIPAL"

        r1 = api.review_proposal(prop["id"], {"decision": "APPROVE"}, VP)
        d1 = validate_success(r1)
        assert d1["status"] == "UNDER_REVIEW"
        assert d1["approvals_received"] == 1

        r2 = api.review_proposal(prop["id"], {"decision": "APPROVE"}, VP2)
        d2 = validate_success(r2)
        assert d2["status"] == "APPROVED"
        assert d2["approvals_received"] == 2
        assert d2["decided_by"] == "vp-2"
        assert d2["approved_at"] is not None

    def test_principal_same_vp_twice_rejected(self, api):
        """PRD §3.4: "each approval is recorded: `approvals_received` increments
        and the reviewer's `X-User-ID` joins `approver_ids`, so a `VPAdvancement`
        who has already approved the current round cannot approve it again
        (`ERR_DUPLICATE_APPROVAL`)."

        Design: Corner/state_machines/principal_same_vp_twice_rejected
        """
        f, p, _ = setup_rated_assigned_prospect(
            assessed_capacity_cents=200000000, move_to="CULTIVATION",
            max_open_ask_cents=1000000000,
        )
        prop = create_submitted_proposal(p["id"], f["id"], 100000000)
        validate_success(api.review_proposal(prop["id"], {"decision": "APPROVE"}, VP))

        resp = api.review_proposal(prop["id"], {"decision": "APPROVE"}, VP)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPROVAL)

        prop_after = get_proposal(prop["id"])
        assert prop_after["status"] == "UNDER_REVIEW"
        assert prop_after["approvals_received"] == 1


class TestProposalNegotiationCycle:
    """Queue A: non_linear_state_machine / proposal_negotiation_revision_cycle."""

    def _setup_proposal(self):
        f, p, _ = setup_rated_assigned_prospect(move_to="CULTIVATION")
        prop = create_proposal_for(p["id"], f["id"], 20000000, designation_purpose="Programs")
        return f, p, prop

    def test_full_negotiation_revision_cycle(self, api):
        """PRD §3.4: "The loop from `UNDER_REVIEW` through `NEGOTIATING`,
        `RETURNED`, or `REJECTED`, back to `DRAFT` by edit, and forward to
        `UNDER_REVIEW` again is the sanctioned negotiation cycle."
        PRD §3.4: "the edit resets the proposal to `DRAFT` and clears the review
        machinery — `approval_tier`, `effective_ask_cents`, and
        `pinned_capacity_band` return to null, `approvals_received` returns to
        zero, and `approver_ids` empties — so every renegotiated ask faces a
        fresh review round."

        Design: Difficulty/non_linear_state_machine/proposal_negotiation_revision_cycle
        """
        f, p, prop = self._setup_proposal()
        officer = make_gift_officer_headers(f["id"])
        pid = prop["id"]

        d = validate_success(api.submit_proposal(pid, officer))
        assert d["status"] == "UNDER_REVIEW" and d["approval_tier"] == "STANDARD"

        d = validate_success(api.review_proposal(pid, {"decision": "NEGOTIATE", "decision_rationale": "counter lower"}, DIR))
        assert d["status"] == "NEGOTIATING"

        d = validate_success(api.patch_proposal(pid, {"ask_amount_cents": 18000000}, officer))
        assert d["status"] == "DRAFT" and d["approval_tier"] is None

        d = validate_success(api.submit_proposal(pid, officer))
        assert d["status"] == "UNDER_REVIEW" and d["approval_tier"] == "STANDARD"

        d = validate_success(api.review_proposal(pid, {"decision": "RETURN", "decision_rationale": "needs detail"}, DIR))
        assert d["status"] == "RETURNED"

        d = validate_success(api.patch_proposal(pid, {"designation_purpose": "Programs v2"}, officer))
        assert d["status"] == "DRAFT"

        validate_success(api.submit_proposal(pid, officer))
        d = validate_success(api.review_proposal(pid, {"decision": "REJECT", "decision_rationale": "not now"}, DIR))
        assert d["status"] == "REJECTED"

        d = validate_success(api.patch_proposal(pid, {"ask_amount_cents": 15000000}, officer))
        assert d["status"] == "DRAFT"

        validate_success(api.submit_proposal(pid, officer))
        d = validate_success(api.review_proposal(pid, {"decision": "APPROVE"}, DIR))
        assert d["status"] == "APPROVED"
        assert d["approvals_received"] == 1

    def test_patch_clears_tier_and_quorum_fields(self, api):
        """PRD §3.4: "the edit resets the proposal to `DRAFT` and clears the
        review machinery — `approval_tier`, `effective_ask_cents`, and
        `pinned_capacity_band` return to null, `approvals_received` returns to
        zero, and `approver_ids` empties — so every renegotiated ask faces a
        fresh review round."

        Design: Difficulty/non_linear_state_machine/proposal_negotiation_revision_cycle
        """
        f, p, prop = self._setup_proposal()
        officer = make_gift_officer_headers(f["id"])
        pid = prop["id"]

        d = validate_success(api.submit_proposal(pid, officer))
        assert d["approval_tier"] == "STANDARD"
        assert d["effective_ask_cents"] == 20000000
        assert d["pinned_capacity_band"] == "C"

        validate_success(api.review_proposal(pid, {"decision": "NEGOTIATE", "decision_rationale": "counter"}, DIR))
        d = validate_success(api.patch_proposal(pid, {"ask_amount_cents": 19000000}, officer))
        assert d["status"] == "DRAFT"
        assert d["approval_tier"] is None
        assert d["effective_ask_cents"] is None
        assert d["pinned_capacity_band"] is None
        assert d["approvals_received"] == 0
        assert d["approver_ids"] == []

        # Resubmission recomputes the tier from the new ask.
        d = validate_success(api.submit_proposal(pid, officer))
        assert d["status"] == "UNDER_REVIEW"
        assert d["approval_tier"] == "STANDARD"
        assert d["effective_ask_cents"] == 19000000


class TestApprovalTierBoundary:
    """Queue A: boundary_precision_check / principal_tier_boundary_at_exactly_one_million."""

    def _rated_band_b_prospect(self):
        return setup_rated_assigned_prospect(
            assessed_capacity_cents=200000000, move_to="CULTIVATION",
            max_open_ask_cents=1000000000,
        )

    def test_effective_ask_one_cent_below_principal_is_major(self, api):
        """PRD §3.4: "`STANDARD` when the effective ask is less than $250,000
        (25000000 cents), `MAJOR` when it is at least $250,000 but less than
        $1,000,000 (100000000 cents), and `PRINCIPAL` when it is at least
        $1,000,000."

        Design: Difficulty/boundary_precision_check/principal_tier_boundary_at_exactly_one_million
        """
        f, p, _ = self._rated_band_b_prospect()
        prop = create_submitted_proposal(p["id"], f["id"], 99999999, designation_purpose="Just under")
        assert prop["approval_tier"] == "MAJOR"  # 99999999 < 100000000
        assert prop["effective_ask_cents"] == 99999999

    def test_effective_ask_exactly_at_principal_min_is_principal(self, api):
        """PRD §3.4: "`STANDARD` when the effective ask is less than $250,000
        (25000000 cents), `MAJOR` when it is at least $250,000 but less than
        $1,000,000 (100000000 cents), and `PRINCIPAL` when it is at least
        $1,000,000."
        PRD §3.4: "A successful submission runs the tier determination below,
        pins the prospect's current `capacity_band` onto the proposal as
        `pinned_capacity_band`."

        Design: Difficulty/boundary_precision_check/principal_tier_boundary_at_exactly_one_million
        """
        f, p, _ = self._rated_band_b_prospect()
        prop = create_submitted_proposal(p["id"], f["id"], 100000000, designation_purpose="Exactly at")
        assert prop["approval_tier"] == "PRINCIPAL"  # >= boundary is inclusive
        assert prop["effective_ask_cents"] == 100000000
        assert prop["pinned_capacity_band"] == "B"  # band B receives no shift
