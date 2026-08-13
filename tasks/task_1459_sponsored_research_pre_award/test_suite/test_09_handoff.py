"""Award handoff readiness gates and setup completion (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    add_budget_line,
    approve_institutional,
    approve_review,
    finalize_budget,
    get_proposal,
    get_success_data,
    get_version,
    make_awarded_proposal,
    make_context,
    make_org,
    make_proposal,
    make_rate_agreement,
    make_sub_commitment,
    make_submitted_proposal,
    open_offer,
    open_review,
    reset_clock,
    route_proposal,
    submit_proposal,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
ANALYST = TEST_USERS["analyst_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


class TestMarkReadyGates:
    def test_pending_review_blocks_ready(self, api):
        """PRD §3.9: "no review may remain `PENDING` or `INFO_REQUESTED`
        (`ERR_COMPLIANCE_REVIEW_PENDING`, 409)".

        Design: Difficulty/cross_entity_state_dependency/handoff_ready_requires_reviews_approved
        """
        reset_clock()
        ctx = make_context()
        make_rate_agreement(initial_status="FINAL")
        env = make_awarded_proposal(ctx=ctx)
        open_review(env["proposal"]["id"], "IRB")  # left PENDING
        resp = api.mark_handoff_ready(env["handoff"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_REVIEW_PENDING.value)

    def test_ready_after_reviews_approved(self, api):
        """PRD §3.9: "All three checklist flags, `budget_verified`,
        `compliance_verified`, and `subrecipient_verified`, are set true, and the
        handoff becomes `READY`."

        Design: Difficulty/cross_entity_state_dependency/handoff_ready_requires_reviews_approved
        """
        reset_clock()
        ctx = make_context()
        make_rate_agreement(initial_status="FINAL")
        env = make_awarded_proposal(ctx=ctx)
        review = open_review(env["proposal"]["id"], "IRB")
        approve_review(review["id"])
        ready = validate_success(
            api.mark_handoff_ready(env["handoff"]["id"], DIRECTOR), 200
        )
        assert ready["status"] == "READY"
        assert ready["budget_verified"] is True
        assert ready["compliance_verified"] is True
        assert ready["subrecipient_verified"] is True


class TestHandoffTransition:
    def test_handoff_before_ready_rejected(self, api):
        """PRD §3.9: "The final act is the handoff itself, performed by an
        `OSPDirector` and permitted only from `READY` (`ERR_HANDOFF_INVALID_STATE`
        otherwise)."

        Design: Corner/state_machines/handoff_handoff_before_ready_rejected
        """
        reset_clock()
        env = make_awarded_proposal()  # auto-created handoff is DRAFT
        resp = api.complete_handoff(env["handoff"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_HANDOFF_INVALID_STATE.value)


class TestFinalRateGate:
    def test_mark_ready_without_final_rate_rejected(self, api):
        """PRD §3.9: "a `FINAL` rate agreement must cover `project_start_on`
        (`ERR_RATE_NOT_FINAL`, 409)". PRD §3.2: "At award-readiness time (the
        final basis), only `FINAL` agreements are eligible, and the absence of a
        covering one fails readiness with `ERR_RATE_NOT_FINAL` (HTTP 409)."

        Design: Corner/errors/mark_ready_without_final_rate_rejected
        """
        reset_clock()
        env = make_awarded_proposal()  # budget ran on the PROVISIONAL 54% rate
        resp = api.mark_handoff_ready(env["handoff"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_RATE_NOT_FINAL.value)

    def test_mark_ready_after_rate_finalized(self, api):
        """PRD §3.9: "All three checklist flags, `budget_verified`,
        `compliance_verified`, and `subrecipient_verified`, are set true, and the
        handoff becomes `READY`."
        PRD §3.2: "Finalization moves a `PROVISIONAL` agreement to `FINAL` —
        finalizing anything else is rejected with
        `ERR_RATE_AGREEMENT_INVALID_STATE` (HTTP 409)."

        Design: Corner/errors/mark_ready_without_final_rate_rejected
        """
        reset_clock()
        env = make_awarded_proposal()
        rate_id = env["ctx"]["rate"]["id"]
        validate_success(api.finalize_fa_rate_agreement(rate_id, DIRECTOR), 200)
        ready = validate_success(
            api.mark_handoff_ready(env["handoff"]["id"], DIRECTOR), 200
        )
        assert ready["status"] == "READY"


class TestSubrecipientGate:
    def test_unverified_subrecipient_blocks_ready(self, api):
        """PRD §3.9: "every non-`VOIDED` subrecipient commitment must be
        `VERIFIED` (`ERR_SUBRECIPIENT_NOT_VERIFIED`, 409)".

        Design: Corner/errors/unverified_subrecipient_blocks_handoff
        """
        reset_clock()
        ctx = make_context()
        make_rate_agreement(initial_status="FINAL")
        org = make_org(legal_name="UnV", uei="UEI-UNV1")
        env = make_awarded_proposal(ctx=ctx)
        # DRAFT commitment attached (never verified)
        make_sub_commitment(env["proposal"]["id"], org["id"],
                            subaward_amount_cents=500_000)
        resp = api.mark_handoff_ready(env["handoff"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_SUBRECIPIENT_NOT_VERIFIED.value)


class TestExpiredGate:
    def _setup(self, api):
        """AWARDED proposal; IRB approved for 10 days; clock advanced past the
        approval window so the review is EXPIRED."""
        reset_clock()
        ctx = make_context()
        make_rate_agreement(initial_status="FINAL")
        env = make_awarded_proposal(ctx=ctx)
        review = open_review(env["proposal"]["id"], "IRB")
        approve_review(review["id"], validity_days=10)
        reset_clock("2026-08-12T00:00:00Z")
        return env

    def test_expired_review_blocks_ready(self, api):
        """PRD §3.9: "no review may be `EXPIRED` or past its `approved_until_at`
        (`ERR_COMPLIANCE_APPROVAL_EXPIRED`, 409)".

        Design: Corner/errors/expired_review_blocks_handoff
        """
        env = self._setup(api)
        resp = api.mark_handoff_ready(env["handoff"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_APPROVAL_EXPIRED.value)


class TestSafetyVsTemporal:
    def _setup(self, api):
        """AWARDED proposal with IRB APPROVED (365d) and COI PENDING; COI then
        DISAPPROVED; clock advanced so the IRB approval lapses to EXPIRED."""
        reset_clock()
        ctx = make_context()
        make_rate_agreement(initial_status="FINAL")
        env = make_awarded_proposal(ctx=ctx)
        prop_id = env["proposal"]["id"]
        irb = open_review(prop_id, "IRB")
        approve_review(irb["id"])  # valid until 2027-08-01T00:00:00Z
        coi = open_review(prop_id, "CONFLICT_OF_INTEREST")
        api.disapprove_review(coi["id"], {"reason": "unmanaged conflict"}, COMPLIANCE)
        reset_clock("2027-08-02T00:00:00Z")  # sweeps IRB to EXPIRED
        return env

    def test_disapproved_beats_expired(self, api):
        """PRD §3.9: "Readiness re-runs every gate, in this order: no review of
        the proposal may be `DISAPPROVED` (`ERR_COMPLIANCE_DISAPPROVED`, 409); no
        review may be `EXPIRED` or past its `approved_until_at`
        (`ERR_COMPLIANCE_APPROVAL_EXPIRED`, 409)". PRD §2.8: "7. **Compliance
        gates.** No `DISAPPROVED` review at readiness
        (`ERR_COMPLIANCE_DISAPPROVED`, 409) ... 9. **Temporal gates.** ... no
        approval may be lapsed at readiness (`ERR_COMPLIANCE_APPROVAL_EXPIRED`,
        409)."

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_on_handoff
        """
        env = self._setup(api)
        # Both hold: COI DISAPPROVED and IRB EXPIRED — safety gate wins
        resp = api.mark_handoff_ready(env["handoff"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_DISAPPROVED.value)

    def test_disapproval_sets_blocked_posture_on_awarded(self, api):
        """PRD §3.6: "the proposal's `compliance_posture` becomes `BLOCKED`; a
        proposal sitting in `ROUTED`, `INSTITUTIONALLY_APPROVED`, `SUBMITTED`,
        `JIT_REQUESTED`, or `NEGOTIATING` is forced back to
        `RETURNED_FOR_REVISION` with its `revision_count` incremented".

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_on_handoff
        """
        env = self._setup(api)
        prop = get_proposal(env["proposal"]["id"])
        # AWARDED is not among the forced-back states: status survives
        assert prop["status"] == "AWARDED"
        assert prop["compliance_posture"] == "BLOCKED"


class TestFinalBasisRecompute:
    def _setup(self, api):
        """Proposal awarded on a PROVISIONAL 54% snapshot; a FINAL 56.5%
        agreement published before mark-ready."""
        reset_clock()
        env = make_awarded_proposal()  # snapshot: PROVISIONAL 54% on 10_000_000 TDC
        make_rate_agreement(rate_pct=56.50, initial_status="FINAL")
        return env

    def test_snapshot_used_provisional_basis(self, api):
        """PRD §3.2: "At budget-finalization time (the provisional basis), the
        server prefers a `FINAL` agreement of the resolved type whose window
        contains `project_start_on`, falling back to a `PROVISIONAL` one".

        Design: Difficulty/dual_variant_calc/provisional_vs_final_rate_at_handoff
        """
        env = self._setup(api)
        snap = env["proposal"]
        assert snap["total_indirect_cents"] == 5_400_000
        assert snap["applied_rate_source"] == "PROVISIONAL_RATE"
        assert snap["fa_rate_pct_applied"] == 54.0

    def test_mark_ready_recomputes_under_final_basis(self, api):
        """PRD §3.9: "`final_indirect_cents` is the indirect cost recomputed
        under the final basis of §3.2 — the same base portions as the pinned
        snapshot, but only `FINAL` agreements eligible, so a different selected
        rate legitimately yields different cents than the snapshot shows — and
        `final_total_cents` is the proposal's `total_direct_cents` plus that
        `final_indirect_cents`."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_rate_at_handoff
        """
        env = self._setup(api)
        ready = validate_success(
            api.mark_handoff_ready(env["handoff"]["id"], DIRECTOR), 200
        )
        assert ready["status"] == "READY"
        # FINAL 56.5% on the 10_000_000 base: 5_650_000 indirect
        assert ready["final_indirect_cents"] == 5_650_000
        assert ready["final_total_cents"] == 15_650_000
        assert ready["final_indirect_cents"] != env["proposal"]["total_indirect_cents"]


class TestJitBudgetAmendmentPinning:
    def _setup(self, api):
        """Proposal SUBMITTED (snapshot 1 pinned at approval) then JIT_REQUESTED;
        FINAL 54% rate present."""
        reset_clock()
        ctx = make_context()
        make_rate_agreement(initial_status="FINAL")
        env = make_submitted_proposal(ctx=ctx, idempotency_key="sub-pin-1")
        prop_id = env["proposal"]["id"]
        validate_success(
            api.create_jit_notice(
                prop_id, {"sponsor_reference": "NIH-JIT-2", "due_in_days": 14},
                DIRECTOR,
            ),
            200,
        )
        return env, prop_id

    def test_jit_amendment_marks_budget_amended(self, api):
        """PRD §3.3: "The same mutation while `JIT_REQUESTED` supersedes the
        snapshot and sets `budget_amended_since_approval` true while leaving the
        status itself untouched."

        Design: Corner/cross_cutting_layers/jit_budget_amendment_stales_pinned_snapshot
        """
        env, prop_id = self._setup(api)
        add_budget_line(prop_id, category="TRAVEL", description="jit add",
                        amount_cents=500_000)
        mid = get_proposal(prop_id)
        assert mid["budget_amended_since_approval"] is True
        assert mid["status"] == "JIT_REQUESTED"
        snap2 = finalize_budget(prop_id)
        assert snap2["snapshot_index"] == 2
        assert snap2["status"] == "CURRENT"

    def test_stale_pin_blocks_ready_until_repinned(self, api):
        """PRD §3.9: "the proposal's `pinned_budget_snapshot_id` must equal its
        `current_snapshot_id`, catching budgets amended since approval
        (`ERR_STALE_BUDGET_SNAPSHOT`, 409)". PRD §3.5: "From `AWARDED`, the same
        action re-pins a snapshot whose budget was amended after the award
        carried through — again only when `budget_amended_since_approval` is
        true — re-pinning and clearing the flag while the proposal stays
        `AWARDED`."

        Design: Corner/cross_cutting_layers/jit_budget_amendment_stales_pinned_snapshot
        """
        env, prop_id = self._setup(api)
        add_budget_line(prop_id, category="TRAVEL", description="jit add",
                        amount_cents=500_000)
        finalize_budget(prop_id)  # snapshot 2 CURRENT; pin still on snapshot 1
        offer = open_offer(prop_id, offered_total_cents=16_000_000)
        validate_success(api.accept_negotiation_offer(offer["id"], DIRECTOR), 200)
        handoffs = get_success_data(api.list_award_handoffs(prop_id, DIRECTOR))
        handoff_id = handoffs[0]["id"]
        stale = api.mark_handoff_ready(handoff_id, DIRECTOR)
        validate_error(stale, ApiErrorId.ERR_STALE_BUDGET_SNAPSHOT.value)
        # Re-approval from AWARDED re-pins the current snapshot
        approve_institutional(prop_id)
        ready = validate_success(api.mark_handoff_ready(handoff_id, DIRECTOR), 200)
        assert ready["status"] == "READY"
        # FINAL_BASIS on the amended direct total 10_500_000 at 54%
        assert ready["final_indirect_cents"] == 5_670_000
