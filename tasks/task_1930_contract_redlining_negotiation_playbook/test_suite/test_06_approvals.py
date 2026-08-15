"""Approval workflows: parallel approval dimension, escalation, segregation of
duties, playbook staleness, and OCC on decisions."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    assert_deviation, assert_negotiation,
    setup_redlining_ctx, record_deviation, begin_review, decide, decide_ok,
    approve_deviation, withdraw_deviation, refresh_negotiation, get_deviation,
    finalize_redlining, create_clause_payload,
)

TWO_OPERATIONAL_CLAUSES = [
    {"clause_key": "A", "category": "OPERATIONAL", "standard_text": "a",
     "fallback_positions": ["a_fb"], "approver_role_required": "LEGAL_COUNSEL",
     "deviation_severity_cap": "MEDIUM"},
    {"clause_key": "B", "category": "OPERATIONAL", "standard_text": "b",
     "fallback_positions": ["b_fb"], "approver_role_required": "LEGAL_COUNSEL",
     "deviation_severity_cap": "MEDIUM"},
]


class TestApprovalDimensionLoop:
    def test_blocked_then_recovered_to_approved_with_deviations(self, api):
        """Full loop: DEVIATIONS_PENDING -> BLOCKED (reject) -> DEVIATIONS_PENDING
        (withdraw rejected) -> APPROVED_WITH_DEVIATIONS (approve remaining), while
        draft_status stays REDLINING.

        PRD §3.6: "the approval dimension hardens to `BLOCKED`: a rejected deviation is
        a wall across the deal."
        PRD §3.6: "Withdrawing from `REJECTED` is how a blocked deal gets unstuck: the
        approval dimension is recomputed and moves from `BLOCKED` to
        `DEVIATIONS_PENDING` if other open deviations remain".
        PRD §3.6: "When the count of open deviations thereby falls from above zero to
        exactly zero with at least one deviation `APPROVED` and none `REJECTED`, the
        approval dimension settles at `APPROVED_WITH_DEVIATIONS`."

        Design: Difficulty/non_linear_state_machine/deviation_parallel_dimension_blocked_recover_loop
        """
        ctx = setup_redlining_ctx(clause_specs=TWO_OPERATIONAL_CLAUSES)
        dev_a = record_deviation(ctx, clause_index=0, proposed_text="altA", fallback_index=0)
        dev_b = record_deviation(ctx, clause_index=1, proposed_text="altB", fallback_index=0)
        negotiation = refresh_negotiation(ctx)
        assert negotiation["approval_status"] == "DEVIATIONS_PENDING"

        # Reject A -> BLOCKED; withdraw the rejected A -> DEVIATIONS_PENDING.
        begin_review(ctx, dev_a)
        decide_ok(ctx, dev_a, "REJECT", rationale="not acceptable")
        assert refresh_negotiation(ctx)["approval_status"] == "BLOCKED"
        withdraw_deviation(ctx, dev_a)
        assert refresh_negotiation(ctx)["approval_status"] == "DEVIATIONS_PENDING"

        # Approve B -> all resolved, one APPROVED, none REJECTED remaining.
        begin_review(ctx, dev_b)
        decide_ok(ctx, dev_b, "APPROVE")

        negotiation = refresh_negotiation(ctx)
        assert_negotiation(negotiation)
        assert negotiation["approval_status"] == "APPROVED_WITH_DEVIATIONS"
        assert negotiation["draft_status"] == "REDLINING"
        assert negotiation["open_deviation_count"] == 0
        assert get_deviation(ctx, dev_a["id"])["status"] == "WITHDRAWN"
        assert get_deviation(ctx, dev_b["id"])["status"] == "APPROVED"

    def test_rejection_blocks_deal_until_drafter_withdraws(self, api):
        """The BLOCKED wall stands while the REJECTED record exists and lifts to
        DEVIATIONS_PENDING only on drafter withdrawal.

        PRD §3.6: "Rejection moves it `IN_REVIEW → REJECTED` with the same resolution
        stamping and count decrements, but the approval dimension hardens to `BLOCKED`:
        a rejected deviation is a wall across the deal."
        PRD §3.6: "Withdrawing from `REJECTED` is how a blocked deal gets unstuck: the
        approval dimension is recomputed and moves from `BLOCKED` to
        `DEVIATIONS_PENDING` if other open deviations remain".

        Design: Difficulty/non_linear_state_machine/deviation_parallel_dimension_blocked_recover_loop
        """
        ctx = setup_redlining_ctx(clause_specs=TWO_OPERATIONAL_CLAUSES)
        dev_a = record_deviation(ctx, clause_index=0, proposed_text="altA", fallback_index=0)
        dev_b = record_deviation(ctx, clause_index=1, proposed_text="altB", fallback_index=0)

        begin_review(ctx, dev_a)
        decide_ok(ctx, dev_a, "REJECT", rationale="not acceptable")

        negotiation = refresh_negotiation(ctx)
        assert negotiation["approval_status"] == "BLOCKED"
        assert negotiation["draft_status"] == "REDLINING", (
            "the approval dimension must evolve independently of the draft dimension")
        assert get_deviation(ctx, dev_a["id"])["status"] == "REJECTED"
        assert get_deviation(ctx, dev_b["id"])["status"] == "OPEN"

        withdraw_deviation(ctx, dev_a)
        negotiation = refresh_negotiation(ctx)
        assert negotiation["approval_status"] == "DEVIATIONS_PENDING"
        assert get_deviation(ctx, dev_a["id"])["status"] == "WITHDRAWN"


class TestEscalationCascade:
    ESCALATION_CLAUSES = [
        {"clause_key": "INDEMNITY", "category": "RISK", "standard_text": "std indemnity",
         "fallback_positions": ["fallback indemnity"],
         "approver_role_required": "LEGAL_COUNSEL", "deviation_severity_cap": "MEDIUM"},
    ]

    def test_escalation_reroutes_deviation_to_chief_counsel(self, api):
        """A successful ESCALATE flips the flag, raises the required role to
        CHIEF_COUNSEL, re-resolves the assignee to the chief, and records the
        decision row.

        PRD §3.6: "A successful escalation records the decision row, sets the
        deviation's `escalated_to_chief_counsel` flag true, sets its
        `required_approver_role` to `CHIEF_COUNSEL`, recomputes its `risk_score`, and
        re-resolves `assigned_approver_id` to the user holding `primary_role`
        `CHIEF_COUNSEL` with the lowest active deviation load, ties broken in favor of
        the earliest-created user account."

        Design: Difficulty/transitive_cascade/escalation_cascade_depth_2
        """
        ctx = setup_redlining_ctx(clause_specs=self.ESCALATION_CLAUSES,
                                  value_cents=500_000)
        dev = record_deviation(ctx, clause_index=0, proposed_text="broadened indemnity",
                               fallback_index=-1)
        begin_review(ctx, dev)
        resp = decide(ctx, dev, "ESCALATE", rationale="exceeds my authority")
        escalated = validate_success(resp, expected_status=200)

        assert_deviation(escalated)
        assert escalated["status"] == "ESCALATED"
        assert escalated["escalated_to_chief_counsel"] is True
        assert escalated["required_approver_role"] == "CHIEF_COUNSEL"
        assert escalated["assigned_approver_id"] == ctx.users["cc"]["id"], (
            "the single CHIEF_COUNSEL user must be re-resolved as assignee")

        decisions, _ = validate_paginated(api.list_approval_decisions(
            ctx.negotiation["id"], dev["id"], ctx.headers[ctx.users["lc"]["id"]]))
        assert len(decisions) == 1
        assert decisions[0]["decision"] == "ESCALATE"

    def test_escalated_deviation_is_finished_by_chief(self, api):
        """Once escalated, the assigned ChiefCounsel casts APPROVE directly from
        ESCALATED, resolving the deviation and settling the approval dimension.

        PRD §3.6: "Once escalated, only the chief can finish it. A `ChiefCounsel` who
        is the assigned approver — and who is not the drafter — casts `APPROVE` or
        `REJECT` against the escalated deviation with the same version guard. Approval
        moves `ESCALATED → APPROVED` with resolution stamping and both count
        decrements".

        Design: Difficulty/transitive_cascade/escalation_cascade_depth_2
        """
        ctx = setup_redlining_ctx(clause_specs=self.ESCALATION_CLAUSES,
                                  value_cents=500_000)
        dev = record_deviation(ctx, clause_index=0, proposed_text="broadened indemnity",
                               fallback_index=-1)
        begin_review(ctx, dev)
        decide_ok(ctx, dev, "ESCALATE", rationale="exceeds my authority")

        resp = decide(ctx, get_deviation(ctx, dev["id"]), "APPROVE",
                      actor_id=ctx.users["cc"]["id"])
        approved = validate_success(resp, expected_status=200)
        assert approved["status"] == "APPROVED"
        assert approved["resolved_at"] is not None

        negotiation = refresh_negotiation(ctx)
        assert negotiation["approval_status"] == "APPROVED_WITH_DEVIATIONS"
        assert negotiation["open_deviation_count"] == 0
        assert negotiation["blocking_deviation_count"] == 0


class TestDecisionGuardOrder:
    def test_reject_without_rationale_rejected(self, api):
        """Body completeness is enforced last: REJECT without decision_rationale
        yields 400 once the earlier guards pass.

        PRD §3.6: "body completeness comes last, with `decision_rationale` required on
        `REJECT` and `ESCALATE` (`ERR_INVALID_REQUEST`)."

        Design: Corner/validations/reject_decision_missing_rationale_returns_400
        """
        ctx = setup_redlining_ctx()
        dev = record_deviation(ctx, clause_index=0, proposed_text="alt", fallback_index=0)
        begin_review(ctx, dev)

        resp = decide(ctx, dev, "REJECT")  # no rationale
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400

    def test_low_cap_clause_cannot_escalate(self, api):
        """A deviation on a LOW-cap clause can only be approved or rejected.

        PRD §3.6: "a clause whose `deviation_severity_cap` is `LOW` cannot be escalated
        at all — its deviations must be approved or rejected on the spot, and the
        attempt is refused with `ERR_SEVERITY_NOT_ESCATABLE` (HTTP 409)."

        Design: Corner/validations/escalate_low_severity_cap_clause_returns_409
        """
        ctx = setup_redlining_ctx(clause_specs=[{
            "clause_key": "A", "category": "OPERATIONAL", "standard_text": "a",
            "fallback_positions": ["fb"], "approver_role_required": "LEGAL_COUNSEL",
            "deviation_severity_cap": "LOW"}])
        dev = record_deviation(ctx, clause_index=0, proposed_text="alt", fallback_index=0)
        begin_review(ctx, dev)

        resp = decide(ctx, dev, "ESCALATE", rationale="try anyway")
        validate_error(resp, ApiErrorId.ERR_SEVERITY_NOT_ESCATABLE)
        assert resp.status_code == 409

    def test_decide_with_stale_negotiation_version_rejected(self, api):
        """An approval decision carrying a version captured before an intervening
        mutation is rejected at the version gate.

        PRD §2.7: "Any intervening mutation — a new round opened, another deviation
        decided, an escalation re-resolving the assigned approver — advances the
        negotiation's `version`; a mismatch is rejected with `ERR_STALE_VERSION`
        (HTTP 412) rather than letting the decision land on a negotiation state the
        approver never saw."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_decide
        """
        ctx = setup_redlining_ctx()
        dev1 = record_deviation(ctx, clause_index=0, proposed_text="alt", fallback_index=0)
        begin_review(ctx, dev1)
        stale_version = refresh_negotiation(ctx)["version"]
        # Approve dev1 (bumps the negotiation version beyond the captured one).
        resp = decide(ctx, dev1, "APPROVE")
        get_success_data(resp)

        # A second deviation enters IN_REVIEW; decide it with the stale version.
        dev2 = record_deviation(ctx, clause_index=0, proposed_text="alt2", fallback_index=0)
        begin_review(ctx, dev2)
        assigned = get_deviation(ctx, dev2["id"])["assigned_approver_id"]
        resp = api.decide_deviation(
            ctx.negotiation["id"], dev2["id"],
            {"decision": "APPROVE", "expected_negotiation_version": stale_version},
            ctx.headers[assigned])
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412


class TestSegregationAndStateOrdering:
    def test_drafter_role_forbidden_from_deciding(self, api):
        """A ContractAnalyst (the drafter) calling /decide is stopped at the role
        gate, ahead of every domain check.

        PRD §2.1: "A caller whose role is not permitted on the target endpoint is
        rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/negotiations/{negotiationId}/deviations/{deviationId}/decide`
        | Cast an approval decision (`APPROVE`/`REJECT`/`ESCALATE`) | LegalCounsel,
        BusinessOwner, FinanceController, ChiefCounsel |"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_segregation_of_duties
        """
        ctx = setup_redlining_ctx()
        dev = record_deviation(ctx, clause_index=0, proposed_text="alt", fallback_index=0)
        version = refresh_negotiation(ctx)["version"]
        ca = ctx.headers[ctx.users["ca"]["id"]]

        resp = api.decide_deviation(
            ctx.negotiation["id"], dev["id"],
            {"decision": "APPROVE", "expected_negotiation_version": version}, ca)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert resp.status_code == 403

    def test_state_validity_checked_before_segregation_of_duties(self, api):
        """A drafter holding an approver role who decides on an OPEN deviation hits
        the state guard first — segregation of duties would also fire, but state
        validity precedes it in the fixed order.

        PRD §2.8: "On a deviation decision, the order is state validity, then version
        freshness, then segregation of duties (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`),
        then approver-role sufficiency (`ERR_INSUFFICIENT_APPROVER_ROLE`)".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_segregation_of_duties
        """
        # The drafter is the LegalCounsel user, so the role gate passes and the
        # state guard is the first domain check that can fire.
        ctx = setup_redlining_ctx(drafter="lc")
        dev = record_deviation(ctx, clause_index=0, proposed_text="alt", fallback_index=0)
        assert dev["status"] == "OPEN"
        assert ctx.negotiation["drafter_user_id"] == ctx.users["lc"]["id"]
        version = refresh_negotiation(ctx)["version"]
        lc = ctx.headers[ctx.users["lc"]["id"]]

        resp = api.decide_deviation(
            ctx.negotiation["id"], dev["id"],
            {"decision": "APPROVE", "expected_negotiation_version": version}, lc)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert resp.status_code == 409
        assert get_deviation(ctx, dev["id"])["status"] == "OPEN"


class TestSegregationVsPlaybookStaleness:
    def test_drafter_who_is_assigned_approver_hits_segregation_guard(self, api):
        """When the assigned approver is also the negotiation's drafter, the
        decision is refused as a segregation-of-duties violation.

        PRD §2.10: "the user recorded as a negotiation's `drafter_user_id` may record
        and withdraw deviations but may never cast an approval decision on them, and
        any attempt to do so is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`
        (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_playbook_stale
        """
        # RISK category keeps required_approver_role at LEGAL_COUNSEL so the
        # LegalCounsel-drafter is also the assigned approver.
        ctx = setup_redlining_ctx(drafter="lc", clause_specs=[{
            "clause_key": "A", "category": "RISK", "standard_text": "a",
            "fallback_positions": ["a_fb"], "approver_role_required": "LEGAL_COUNSEL",
            "deviation_severity_cap": "MEDIUM"}])
        dev = record_deviation(ctx, clause_index=0, proposed_text="altA", fallback_index=0)
        assert dev["assigned_approver_id"] == ctx.users["lc"]["id"]
        begin_review(ctx, dev)  # begin-review has no segregation gate (PRD §3.6)
        version = refresh_negotiation(ctx)["version"]
        lc = ctx.headers[ctx.users["lc"]["id"]]

        resp = api.decide_deviation(
            ctx.negotiation["id"], dev["id"],
            {"decision": "APPROVE", "expected_negotiation_version": version}, lc)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
        assert resp.status_code == 403
        assert get_deviation(ctx, dev["id"])["status"] == "IN_REVIEW"

    def test_stale_playbook_blocks_finalize_until_override(self, api):
        """A playbook whose version advanced past the negotiation's pin blocks
        finalize-redlining; the deliberate override waives the check.

        PRD §3.7: "If the finalize request carries `playbook_staleness_override` set to
        true, the staleness check is waived and the negotiation proceeds against the
        pinned snapshot it knows; without the override, a drifted playbook is rejected
        with `ERR_PLAYBOOK_STALE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_playbook_stale
        """
        ctx = setup_redlining_ctx()
        lc = ctx.headers[ctx.users["lc"]["id"]]
        cc = ctx.headers[ctx.users["cc"]["id"]]

        # Drift the playbook: adding a clause bumps the playbook's version (PRD §3.1).
        get_success_data(api.create_clause(
            ctx.playbook["id"],
            create_clause_payload(clause_key="LATE", fallback_positions=[]),
            cc))

        resp = api.finalize_redlining(ctx.negotiation["id"], {}, lc)
        validate_error(resp, ApiErrorId.ERR_PLAYBOOK_STALE)
        assert resp.status_code == 409

        finalized = validate_success(
            api.finalize_redlining(
                ctx.negotiation["id"], {"playbook_staleness_override": True}, lc),
            expected_status=200)
        assert finalized["draft_status"] == "AWAITING_COUNTERSIGN"


class TestSignatoryRoleDenial:
    def test_signatory_cannot_decide_deviation(self, api):
        """Signatory is absent from the /decide role list and is refused at the
        role gate.

        PRD §2.1: "A caller whose role is not permitted on the target endpoint is
        rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/negotiations/{negotiationId}/deviations/{deviationId}/decide`
        | Cast an approval decision (`APPROVE`/`REJECT`/`ESCALATE`) | LegalCounsel,
        BusinessOwner, FinanceController, ChiefCounsel |"

        Design: Corner/roles/signatory_cannot_decide_deviation
        """
        ctx = setup_redlining_ctx()
        dev = record_deviation(ctx, clause_index=0, proposed_text="alt", fallback_index=0)
        begin_review(ctx, dev)
        version = refresh_negotiation(ctx)["version"]
        sg = ctx.headers[ctx.users["sg"]["id"]]

        resp = api.decide_deviation(
            ctx.negotiation["id"], dev["id"],
            {"decision": "APPROVE", "expected_negotiation_version": version}, sg)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert resp.status_code == 403
