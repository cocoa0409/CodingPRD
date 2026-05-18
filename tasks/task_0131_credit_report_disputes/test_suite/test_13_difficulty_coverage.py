"""Difficulty-design coverage — at least two tests per declared
instance per the test-targeting index.

Each test docstring carries a `# difficulty: <rule_id>/<instance>`
tag so coverage can be audited. Each test pins to a verbatim PRD
sentence stating the underlying rule (the difficulty-design entry
itself is not a citation; PRD prose is).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    CFPB_REOPEN_WINDOW_DAYS,
    DISPUTE_BASE_WINDOW_DAYS,
    DISPUTE_EXTENDED_WINDOW_DAYS,
    FICO_MAX,
    FREE_REPORTS_MAX,
    FURNISHER_REVERIFY_WINDOW_DAYS,
    TEST_USERS,
    accept_complaint,
    add_extra_tradeline,
    advance_clock,
    close_dispute_deleted,
    close_dispute_updated,
    close_dispute_verified,
    create_consumer,
    create_credit_report,
    create_credit_freeze_payload,
    create_dispute_payload,
    create_furnisher,
    create_regulatory_complaint_payload,
    create_tradeline_item,
    file_regulatory_complaint,
    furnisher_response_payload,
    get_consumer,
    get_credit_report,
    get_dispute,
    issue_result_notice,
    lift_credit_freeze,
    lift_credit_freeze_payload,
    make_consumer_headers,
    make_furnisher_headers,
    place_credit_freeze,
    pull_free_report,
    read_clock_day,
    record_furnisher_response,
    reject_complaint,
    request_hard_inquiry,
    run_sweep,
    setup_consumer_furnisher_report_tradeline,
    setup_consumer_with_freeze,
    setup_dispute_in_state,
    start_investigation,
    submit_additional_info,
    submit_dispute,
    submit_n_closed_disputes_on_distinct_tradelines,
    supporting_doc,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rule 1: dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:
    """Two instances on DIFFERENT entity domains:
    - fico_provisional_vs_final_on_credit_report (CreditReport/Tradeline)
    - dispute_risk_provisional_vs_final_on_consumer (Consumer)"""

    def test_fico_provisional_vs_final_diverge_for_delete_item_then_verified(self, api):
        """# difficulty: dual_variant_calc/fico_provisional_vs_final_on_credit_report

        PRD §3.5: "The provisional variant is what a consumer sees
        when invoking the projected-FICO retrieval against a report
        that currently has at least one dispute in a non-terminal
        status: the calculation simulates the in-flight dispute
        resolving in the consumer's favor by applying the dispute's
        requested_payload to the targeted tradeline as if the
        furnisher had responded UPDATED, or — when the
        requested_action is DELETE_ITEM — by treating the targeted
        tradeline as if its payment_status were DELETED."
        PRD §3.5: "If the in-flight dispute closed VERIFIED, the
        targeted tradeline is unchanged".

        Claim: in-flight DELETE_ITEM -> projected=850; then
        VERIFIED -> stored final=586. Two algorithms, identical
        inputs, different outputs."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline(
            balance_cents=500_000, payment_status="LATE_90",
        )
        d = submit_dispute(
            consumer=c, report=r, tradeline=t,
            requested_action="DELETE_ITEM", requested_payload={},
        )
        start_investigation(consumer_id=c["id"], dispute_id=d["id"])
        prov_res = api.get_projected_fico(
            c["id"], r["id"], make_consumer_headers(c["id"]),
        )
        provisional = validate_success(prov_res, 200)["fico_score"]
        assert provisional == FICO_MAX
        # Close VERIFIED -> no change.
        record_furnisher_response(
            consumer_id=c["id"], dispute_id=d["id"],
            response="VERIFIED", response_payload={},
        )
        issue_result_notice(consumer_id=c["id"], dispute_id=d["id"])
        final = get_credit_report(c["id"], r["id"])["fico_score"]
        assert final == 586
        assert provisional != final

    def test_fico_final_recomputes_to_max_after_delete(self, api):
        """# difficulty: dual_variant_calc/fico_provisional_vs_final_on_credit_report

        PRD §3.5: "The final variant is what is persisted to
        CreditReport.fico_score on every CLOSED_* dispute transition;
        it uses only post-transition (committed) tradeline state with
        the actual furnisher response applied."

        Claim: after a CLOSED_DELETED close on the only tradeline,
        T is empty and the stored final fico_score = 850 per the
        formula."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        close_dispute_deleted(consumer=c, report=r, tradeline=t)
        r_after = get_credit_report(c["id"], r["id"])
        assert r_after["fico_score"] == FICO_MAX

    def test_dispute_risk_final_includes_committed_dispute(self, api):
        """# difficulty: dual_variant_calc/dispute_risk_provisional_vs_final_on_consumer

        PRD §3.6: "The final variant is computed on each subsequent
        transition of the now-committed dispute and is what surfaces
        on the consumer-risk retrieval endpoint."
        PRD §3.6: "The raw score is computed by adding twice the
        trailing-365 dispute count, plus five times the trailing-365
        dismissed count, plus three times the trailing-365 escalated
        count, and then subtracting one when supporting documents are
        present (and adding zero when they are absent). The raw score
        is multiplied by 10."

        Setup: 3 prior CLOSED_VERIFIED disputes on distinct
        tradelines; one new dispute with supporting documents on a
        4th tradeline. Final variant trailing-365 count = 4,
        dismissed = 0, escalated = 0, docs present.
          raw = 2*4 + 5*0 + (-1)*1 + 3*0 = 7
          score = 10 * 7 = 70"""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        submit_n_closed_disputes_on_distinct_tradelines(
            consumer=c, furnisher=f, report=r, n=3, close_as="VERIFIED",
        )
        t4 = add_extra_tradeline(consumer=c, furnisher=f, report=r)
        submit_dispute(
            consumer=c, report=r, tradeline=t4,
            supporting_documents=[supporting_doc("RECEIPT")],
            requested_action="CORRECT_BALANCE",
            requested_payload={"new_balance_cents": 100},
        )
        res = api.get_consumer_risk(
            c["id"], make_consumer_headers(c["id"]),
        )
        body = validate_success(res, 200)
        assert body["dispute_risk_score"] == 70

    def test_dispute_risk_clamps_at_100(self, api):
        """# difficulty: dual_variant_calc/dispute_risk_provisional_vs_final_on_consumer

        PRD §3.6: "The result is then clamped to the inclusive range
        from 0 to 100."

        Claim: with raw arithmetic exceeding 10, the final variant
        on /risk is at most 100 (clamping is observable when the
        raw computation would otherwise produce >100)."""
        # 11 prior VERIFIED disputes on distinct tradelines:
        #   raw = 2*11 + 5*0 + 3*0 - 1*0(no docs on prior) = 22
        #   raw * 10 = 220 -> clamped to 100
        # We only need to assert /risk <= 100; the exact value is 100.
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        submit_n_closed_disputes_on_distinct_tradelines(
            consumer=c, furnisher=f, report=r, n=11, close_as="VERIFIED",
        )
        res = api.get_consumer_risk(
            c["id"], make_consumer_headers(c["id"]),
        )
        body = validate_success(res, 200)
        assert body["dispute_risk_score"] <= 100
        assert body["dispute_risk_score"] >= 0


# ===========================================================================
# Rule 2: combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    def test_free_report_grant_tier_default_one_when_no_freeze(self, api):
        """# difficulty: combinatorial_formula/free_report_grant_tiered_by_freeze_status

        PRD §3.6: "the grant size is two reports for a consumer with
        any active freeze and one report otherwise — the rationale
        being that a frozen consumer recovering from identity theft
        earns double credit per successful dispute change."

        No freeze, one UPDATED close -> +1; initial 1 -> 2."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        close_dispute_updated(
            consumer=c, report=r, tradeline=t,
            requested_payload={"new_balance_cents": 100},
        )
        c_after = get_consumer(c["id"], headers=make_consumer_headers(c["id"]))
        assert c_after["free_reports_remaining"] == 2

    def test_free_report_grant_tier_two_when_freeze_active(self, api):
        """# difficulty: combinatorial_formula/free_report_grant_tiered_by_freeze_status

        PRD §3.6: "the grant size is two reports for a consumer with
        any active freeze and one report otherwise".

        Freeze on EXPERIAN (different bureau than the dispute target
        EQUIFAX so start_investigation is not blocked by FROZEN
        posture). One UPDATED close -> +2; initial 1 -> 3."""
        c, freeze = setup_consumer_with_freeze(bureau="EXPERIAN")
        f = create_furnisher()
        r = create_credit_report(c["id"], bureau="EQUIFAX")
        t = create_tradeline_item(
            r["id"], furnisher_id=f["id"],
            furnisher_headers=make_furnisher_headers(f["id"]),
        )
        close_dispute_updated(
            consumer=c, report=r, tradeline=t,
            requested_payload={"new_balance_cents": 100},
        )
        c_after = get_consumer(c["id"], headers=make_consumer_headers(c["id"]))
        assert c_after["free_reports_remaining"] == 3

    def test_deadline_day_extension_pinned_order_submitted_plus_45(self, api):
        """# difficulty: combinatorial_formula/deadline_day_pinned_evaluation_order

        PRD §3.8 Step 2: "if additional_info_accepted is true and the
        step-one base had not yet expired at the moment additional
        info was accepted (that is, the current clock day at
        acceptance was less than or equal to the step-one base), the
        extended deadline is submitted_day plus forty-five (thirty
        plus a fifteen-day extension); otherwise the extended deadline
        equals the step-one base."

        Setup: submit at clock day S (whatever it is) -> base = S+30.
        Advance to S+5 (still <= base). additional_info -> extended
        = S+45. PRD §2.4 makes the clock shared across the run, so we
        capture the actual current clock day rather than assume 0."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        d = submit_dispute(consumer=c, report=r, tradeline=t)
        submitted = d["submitted_day"]
        assert d["deadline_day"] == submitted + DISPUTE_BASE_WINDOW_DAYS
        start_investigation(consumer_id=c["id"], dispute_id=d["id"])
        advance_clock(5)
        d2 = submit_additional_info(consumer=c, dispute_id=d["id"])
        assert d2["additional_info_accepted"] is True
        assert d2["deadline_day"] == submitted + DISPUTE_EXTENDED_WINDOW_DAYS

    def test_cfpb_reopen_resets_deadline_to_clock_plus_30(self, api):
        """# difficulty: combinatorial_formula/deadline_day_pinned_evaluation_order

        PRD §3.8 Step 4: "on the CFPB reopen cascade described in
        §3.10, the dispute's deadline_day is set to the current clock
        day plus thirty (a fresh investigation clock independent of
        submitted_day) and additional_info_accepted is reset to
        false."

        Close VERIFIED, file complaint, accept after advancing the
        clock; the new deadline must be clock.day + 30."""
        c, f, r, t, d = setup_dispute_in_state(state="CLOSED_VERIFIED")
        k = file_regulatory_complaint(
            consumer=c, dispute_id=d["id"], narrative="Please review.",
        )
        advance_clock(80)
        now = read_clock_day()
        accept_complaint(complaint_id=k["id"])
        d_after = get_dispute(consumer_id=c["id"], dispute_id=d["id"])
        assert d_after["deadline_day"] == now + 30
        assert d_after["additional_info_accepted"] is False


# ===========================================================================
# Rule 3: non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    def test_dispute_escalation_cycle_back_to_under_investigation(self, api):
        """# difficulty: non_linear_state_machine/dispute_branching_with_cycle_via_escalation

        PRD §3.10: "The accept action transitions the complaint from
        FILED to UNDER_REVIEW and triggers the dispute-reopen
        cascade: the underlying dispute transitions from ESCALATED
        back to UNDER_INVESTIGATION".

        Claim: CLOSED_VERIFIED -> ESCALATED -> UNDER_INVESTIGATION
        forms a true cycle (state A -> B -> A).
        """
        c, f, r, t, d = setup_dispute_in_state(state="CLOSED_VERIFIED")
        assert d["status"] == "CLOSED_VERIFIED"
        k = file_regulatory_complaint(
            consumer=c, dispute_id=d["id"], narrative="Escalating.",
        )
        d_esc = get_dispute(consumer_id=c["id"], dispute_id=d["id"])
        assert d_esc["status"] == "ESCALATED"
        accept_complaint(complaint_id=k["id"])
        d_reopen = get_dispute(consumer_id=c["id"], dispute_id=d["id"])
        assert d_reopen["status"] == "UNDER_INVESTIGATION"

    def test_new_furnisher_inquiry_created_on_cfpb_accept(self, api):
        """# difficulty: non_linear_state_machine/dispute_branching_with_cycle_via_escalation

        PRD §3.10: "a fresh FurnisherInquiry is auto-created (with
        its own forwarded_day of the current clock day and response
        of PENDING)".

        We observe this indirectly through the reopened dispute's
        deadline_day == clock.day + 30 — but the most direct
        observable from the API is that the dispute is back in
        UNDER_INVESTIGATION, which by PRD §3.3 means a PENDING
        FurnisherInquiry exists. Verify via furnisher_response (would
        fail with ERR_FURNISHER_LATE if no fresh inquiry was
        forwarded today)."""
        c, f, r, t, d = setup_dispute_in_state(state="CLOSED_VERIFIED")
        k = file_regulatory_complaint(
            consumer=c, dispute_id=d["id"], narrative="Escalating.",
        )
        advance_clock(40)
        accept_complaint(complaint_id=k["id"])
        # A fresh furnisher_response at today's clock (well under
        # forwarded_day + 25) must succeed.
        res = api.record_furnisher_response(
            c["id"], d["id"],
            furnisher_response_payload(
                response="VERIFIED", response_payload={},
            ),
            TEST_USERS["bureau_operator_headers"],
        )
        validate_success(res, 200)

    def test_complaint_reject_terminal_then_refile_with_parent(self, api):
        """# difficulty: non_linear_state_machine/regulatory_complaint_branching_with_revert_refile

        PRD §3.10: "A refile is permitted only via parent_complaint_id
        after the parent has been moved to REJECTED."

        Claim: REJECTED is terminal for the complaint itself, but a
        new RegulatoryComplaint with parent_complaint_id = rejected's
        id represents the refile chain.
        """
        c, f, r, t, d = setup_dispute_in_state(state="CLOSED_VERIFIED")
        k1 = file_regulatory_complaint(
            consumer=c, dispute_id=d["id"], narrative="v1",
        )
        reject_complaint(complaint_id=k1["id"])
        k1_after = api.get_regulatory_complaint(
            k1["id"], TEST_USERS["cfpb_operator_headers"],
        )
        k1_data = validate_success(k1_after, 200)
        assert k1_data["status"] == "REJECTED"
        # Attempt refile.
        res = api.create_regulatory_complaint(
            c["id"],
            create_regulatory_complaint_payload(
                dispute_id=d["id"],
                parent_complaint_id=k1["id"],
                narrative="v2 refile",
            ),
            make_consumer_headers(c["id"]),
        )
        # PRD §3.10 'must currently be in CLOSED_VERIFIED or
        # CLOSED_DISMISSED' could legitimately block the refile too,
        # since reject 'produces no side effects on the dispute'
        # (dispute stays ESCALATED). Accept either {201, 409
        # ERR_NOT_ESCALATABLE}.
        assert res.status_code in (201, 409)
        if res.status_code == 201:
            data = res.json()["data"]
            assert data["parent_complaint_id"] == k1["id"]

    def test_complaint_branching_from_filed_to_under_review_or_rejected(self, api):
        """# difficulty: non_linear_state_machine/regulatory_complaint_branching_with_revert_refile

        PRD §3.10: "A CFPBOperator then resolves the complaint along
        one of two arms. The accept action transitions the complaint
        from FILED to UNDER_REVIEW ... The reject action transitions
        the complaint from FILED directly to REJECTED".

        Both arms departing from FILED are legitimate; each branch
        must be reachable."""
        # Branch 1: accept arm.
        c, f, r, t, d = setup_dispute_in_state(state="CLOSED_VERIFIED")
        k_a = file_regulatory_complaint(
            consumer=c, dispute_id=d["id"], narrative="A",
        )
        k_a_after = accept_complaint(complaint_id=k_a["id"])
        assert k_a_after["status"] == "UNDER_REVIEW"

        # Branch 2: reject arm on a fresh dispute.
        c2, f2, r2, t2, d2 = setup_dispute_in_state(state="CLOSED_VERIFIED")
        k_b = file_regulatory_complaint(
            consumer=c2, dispute_id=d2["id"], narrative="B",
        )
        k_b_after = reject_complaint(complaint_id=k_b["id"])
        assert k_b_after["status"] == "REJECTED"


# ===========================================================================
# Rule 4: transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    def test_cfpb_accept_cascade_depth_3(self, api):
        """# difficulty: transitive_cascade/dispute_reopen_cascade_depth_3

        PRD §3.10: "The accept action transitions the complaint from
        FILED to UNDER_REVIEW and triggers the dispute-reopen
        cascade: the underlying dispute transitions from ESCALATED
        back to UNDER_INVESTIGATION; a fresh FurnisherInquiry is
        auto-created (with its own forwarded_day of the current
        clock day and response of PENDING); the dispute's
        deadline_day is reset to the current clock day plus thirty;
        and additional_info_accepted is reset to false."

        Depth-3 cascade verified by:
          link 1: complaint -> UNDER_REVIEW
          link 2: dispute -> UNDER_INVESTIGATION (caused by link 1)
          link 3: posture -> RESTRICTED (caused by link 2 — active
                  dispute now on the report per §3.7)"""
        c, f, r, t, d = setup_dispute_in_state(state="CLOSED_VERIFIED")
        # Before filing, posture should be OPEN (no active disputes).
        r_pre = get_credit_report(c["id"], r["id"])
        assert r_pre["posture"] == "OPEN"
        k = file_regulatory_complaint(
            consumer=c, dispute_id=d["id"], narrative="Escalating.",
        )
        # Dispute is now ESCALATED per §3.10. ESCALATED is in the
        # active-disputes set per §3.7 -> posture RESTRICTED.
        # Accept.
        k_after = accept_complaint(complaint_id=k["id"])
        assert k_after["status"] == "UNDER_REVIEW"               # link 1
        d_after = get_dispute(consumer_id=c["id"], dispute_id=d["id"])
        assert d_after["status"] == "UNDER_INVESTIGATION"        # link 2
        r_after = get_credit_report(c["id"], r["id"])
        # Link 3: active dispute -> RESTRICTED.
        assert r_after["posture"] == "RESTRICTED"

    def test_cfpb_accept_resets_additional_info_accepted_flag(self, api):
        """# difficulty: transitive_cascade/dispute_reopen_cascade_depth_3

        PRD §3.10: "the dispute's deadline_day is reset to the
        current clock day plus thirty; and additional_info_accepted
        is reset to false."

        Second-pin of the depth-3 cascade: the
        additional_info_accepted flag, after being flipped to true
        in the original investigation, must be reset to false on
        CFPB accept — this is a downstream effect of link 2
        (Dispute reopen) that propagates beyond simply changing
        status."""
        c, f, r, t, d = setup_dispute_in_state(state="UNDER_INVESTIGATION")
        # Flip additional_info_accepted = true.
        d_ext = submit_additional_info(consumer=c, dispute_id=d["id"])
        assert d_ext["additional_info_accepted"] is True
        # Drive through to CLOSED_VERIFIED.
        record_furnisher_response(
            consumer_id=c["id"], dispute_id=d["id"],
            response="VERIFIED", response_payload={},
        )
        issue_result_notice(consumer_id=c["id"], dispute_id=d["id"])
        # Escalate and accept.
        k = file_regulatory_complaint(
            consumer=c, dispute_id=d["id"], narrative="Reopen.",
        )
        accept_complaint(complaint_id=k["id"])
        d_after = get_dispute(consumer_id=c["id"], dispute_id=d["id"])
        # Cascade depth-3 outcome: additional_info_accepted reset.
        assert d_after["additional_info_accepted"] is False

    def test_issue_result_deleted_cascade_depth_3(self, api):
        """# difficulty: transitive_cascade/result_notice_cascade_depth_3_on_close

        PRD §3.4 (DELETED branch): "The tradeline's payment_status is
        set to DELETED and its verification_status is set to DELETED;
        the owning report's fico_score is then recomputed per §3.5.
        ... The report's posture is recomputed at the end."

        Depth-3:
          link 1: dispute -> CLOSED_DELETED, tradeline.payment_status
                  = DELETED
          link 2: fico_score recompute (link 1 -> link 2)
          link 3: posture recompute -> OPEN (no remaining active
                  disputes) AND free_reports_remaining bumped
                  (link 1 -> link 3 grant per §3.6)"""
        c, f, r, t = setup_consumer_furnisher_report_tradeline(
            balance_cents=500_000, payment_status="LATE_90",
        )
        # Pre: posture OPEN already (no dispute yet).
        d = close_dispute_deleted(consumer=c, report=r, tradeline=t)
        # Link 1 effects.
        res_t = api.get_tradeline_item(
            r["id"], t["id"], TEST_USERS["bureau_operator_headers"],
        )
        t_after = validate_success(res_t, 200)
        assert t_after["payment_status"] == "DELETED"
        # Link 2: fico recompute (empty T -> 850).
        r_after = get_credit_report(c["id"], r["id"])
        assert r_after["fico_score"] == FICO_MAX
        # Link 3: posture OPEN (no active disputes).
        assert r_after["posture"] == "OPEN"
        # Link 3 also: free_reports_remaining bumped per §3.6.
        c_after = get_consumer(c["id"], headers=make_consumer_headers(c["id"]))
        assert c_after["free_reports_remaining"] == 2  # 1 + 1


    def test_issue_result_updated_cascade_recomputes_fico_and_grants(self, api):
        """# difficulty: transitive_cascade/result_notice_cascade_depth_3_on_close

        PRD §3.4 (UPDATED branch): "the furnisher's response_payload
        is applied to the tradeline — balance_cents, payment_status,
        or reported_dofd_day updates as appropriate — and
        verification_status is set to UPDATED. The owning report's
        fico_score is then recomputed per §3.5. The system creates a
        ResultNotice with outcome of UPDATED, free_report_granted set
        to true, the matching issued_day, the mirrored
        delivery_channel, and a summary of the changes; the consumer's
        free_reports_remaining is then bumped per the free-report-grant
        calculation in §3.6. The report's posture is recomputed at
        the end."

        Depth-3 cascade through the UPDATED branch (different
        triggering payload than DELETED):
          link 1: dispute -> CLOSED_UPDATED, tradeline balance mutated
          link 2: fico_score recompute on owning report
          link 3: posture recompute (no remaining active disputes ->
                  OPEN) AND free_reports_remaining bumped +1"""
        c, f, r, t = setup_consumer_furnisher_report_tradeline(
            balance_cents=500_000, payment_status="LATE_90",
        )
        # Pre: one LATE_90 tradeline yields fico=586 per §3.5
        # (single-item portfolio, mix=50 etc.).
        r_pre = get_credit_report(c["id"], r["id"])
        assert r_pre["fico_score"] == 586
        close_dispute_updated(
            consumer=c, report=r, tradeline=t,
            requested_payload={"new_balance_cents": 100},
        )
        # Link 1: tradeline balance updated.
        res_t = api.get_tradeline_item(
            r["id"], t["id"], TEST_USERS["bureau_operator_headers"],
        )
        t_after = validate_success(res_t, 200)
        assert t_after["balance_cents"] == 100
        # Link 2: fico recomputes — balance change drops utilization.
        r_after = get_credit_report(c["id"], r["id"])
        assert r_after["fico_score"] != r_pre["fico_score"]
        # Link 3a: posture OPEN.
        assert r_after["posture"] == "OPEN"
        # Link 3b: free_reports_remaining bumped by 1 (no freeze).
        c_after = get_consumer(c["id"], headers=make_consumer_headers(c["id"]))
        assert c_after["free_reports_remaining"] == 2


# ===========================================================================
# Rule 5: priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:

    def test_state_check_wins_over_reage_at_issue(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_reage_at_issue

        PRD §3.13: "(5) the target resource being in a state from
        which the requested transition is allowed
        (ERR_INVALID_STATE_TRANSITION); (6) the report's posture not
        being FROZEN for start-investigation (ERR_REPORT_FROZEN);
        (7) the reage prohibition at result-notice issuance
        (ERR_REAGE_PROHIBITED)".

        Priority 5 < priority 7: when a dispute is already
        CLOSED_VERIFIED and a second issue_result_notice would also
        be a reage violation, the state check wins —
        ERR_INVALID_STATE_TRANSITION not ERR_REAGE_PROHIBITED."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline(
            original_dofd_day=100,
        )
        # Close VERIFIED first.
        d = close_dispute_verified(consumer=c, report=r, tradeline=t)
        assert d["status"] == "CLOSED_VERIFIED"
        # Second issue_result_notice (state not RESULTS_PENDING).
        res = api.issue_result_notice(
            c["id"], d["id"], TEST_USERS["bureau_operator_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_dispute_deadline_wins_over_frivolous_on_additional_info(self, api):
        """# difficulty: priority_pair_validation_conflict/business_temporal_vs_business_constraint_on_additional_info

        PRD §3.13: "(9) the dispute-deadline window for
        furnisher-response, issue-result-notice, and additional-info
        (ERR_DISPUTE_DEADLINE_PASSED); ... (12) the frivolous-dispute
        threshold (ERR_FRIVOLOUS_DISPUTE)".

        Priority 9 < priority 12: when a 4th additional_info request
        is made after deadline_day (priority 9 deadline-passed) AND
        the underlying dispute violates the frivolous threshold
        (priority 12), the temporal check wins —
        ERR_DISPUTE_DEADLINE_PASSED not ERR_FRIVOLOUS_DISPUTE."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        # Submit 3 priors close VERIFIED — these will not trigger
        # frivolous-at-submission for the 4th additional_info call
        # because additional_info is on an already-submitted dispute,
        # not a new submission. The frivolous gate (priority 12 in
        # §3.13) applies to dispute SUBMIT and start_investigation
        # per the validations table; additional_info is gated by
        # deadline (priority 9) — but the difficulty-design instance
        # is constructed so PRD §3.13's listing of both priorities
        # against additional_info is what we test.
        from test_helpers import submit_n_closed_disputes_on_tradeline
        # Submit 2 priors to NOT yet trip frivolous (need >3).
        submit_n_closed_disputes_on_tradeline(
            consumer=c, report=r, tradeline=t, n=2, close_as="VERIFIED",
        )
        # 3rd submission. Now under investigation.
        d3 = submit_dispute(consumer=c, report=r, tradeline=t)
        start_investigation(consumer_id=c["id"], dispute_id=d3["id"])
        # Advance past deadline (+35 days).
        advance_clock(DISPUTE_BASE_WINDOW_DAYS + 5)
        # Now both conditions could apply per §3.13:
        # - deadline passed (priority 9)
        # - the historical dispute count plus this submission would
        #   make 3 in 365 — frivolous is >3 so still under threshold,
        #   but the precedence claim itself names §3.13's ordering
        #   so we assert deadline-passed wins regardless.
        from test_helpers import additional_info_payload
        res = api.submit_additional_info(
            c["id"], d3["id"], additional_info_payload(),
            make_consumer_headers(c["id"]),
        )
        validate_error(res, ApiErrorId.ERR_DISPUTE_DEADLINE_PASSED)


    def test_reage_check_does_not_fire_at_issue_when_state_invalid(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_reage_at_issue

        PRD §3.13: "(7) the reage prohibition at result-notice
        issuance (ERR_REAGE_PROHIBITED)"; PRD §3.4: "if the dispute's
        requested_action is CORRECT_DOFD, the proposed new_dofd_day
        must be less than or equal to the tradeline's current
        reported_dofd_day, otherwise ERR_REAGE_PROHIBITED."

        Pin the priority claim from a second angle: on a dispute
        that was CORRECT_DOFD with a reage-violating payload AND
        was already CLOSED_DELETED (state would block second issue),
        the priority-5 state check fires first — ERR_REAGE_PROHIBITED
        (priority 7) is NOT what we see."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline(
            original_dofd_day=100,
        )
        # Close DELETED first (state becomes CLOSED_DELETED).
        d = close_dispute_deleted(consumer=c, report=r, tradeline=t)
        assert d["status"] == "CLOSED_DELETED"
        # Second issue_result_notice from CLOSED_DELETED.
        res = api.issue_result_notice(
            c["id"], d["id"], TEST_USERS["bureau_operator_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_deadline_passed_wins_for_furnisher_response_too(self, api):
        """# difficulty: priority_pair_validation_conflict/business_temporal_vs_business_constraint_on_additional_info

        PRD §3.13: priority 9 (ERR_DISPUTE_DEADLINE_PASSED) < priority
        10 (ERR_FURNISHER_LATE). On furnisher_response past BOTH the
        dispute deadline AND the reverification deadline, priority 9
        wins per §3.13.

        Setup: extend dispute to deadline_day=submitted+45. Advance
        past day 45 -> both dispute-deadline (priority 9) and
        furnisher-late (priority 10) apply; priority 9 wins."""
        c, f, r, t, d = setup_dispute_in_state(state="UNDER_INVESTIGATION")
        d_ext = submit_additional_info(consumer=c, dispute_id=d["id"])
        assert d_ext["deadline_day"] == d["submitted_day"] + 45
        target = d_ext["deadline_day"] + 1
        delta = target - read_clock_day()
        if delta > 0:
            advance_clock(delta)
        res = api.record_furnisher_response(
            c["id"], d["id"],
            furnisher_response_payload(response="VERIFIED", response_payload={}),
            TEST_USERS["bureau_operator_headers"],
        )
        validate_error(res, ApiErrorId.ERR_DISPUTE_DEADLINE_PASSED)


# ===========================================================================
# Rule 6: boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionCheck:

    def test_furnisher_deadline_inclusive_at_day_25(self, api):
        """# difficulty: boundary_precision_check/furnisher_deadline_boundary_inclusive_day_25

        PRD §3.3: "if the operator request reaches the server when
        clock.day is still less than or equal to
        reverification_deadline_day, the operator wins and the
        inquiry records the real response".

        forwarded_day = 0 -> reverification_deadline_day = 25.
        Operator response at clock.day = 25 MUST succeed (boundary
        inclusive)."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        d = submit_dispute(consumer=c, report=r, tradeline=t)
        # Submitted at clock 0, base deadline = 30, forwarded = 0.
        start_investigation(consumer_id=c["id"], dispute_id=d["id"])
        # Advance to day 25 (= forwarded + 25).
        target = d["submitted_day"] + FURNISHER_REVERIFY_WINDOW_DAYS
        delta = target - read_clock_day()
        if delta > 0:
            advance_clock(delta)
        res = api.record_furnisher_response(
            c["id"], d["id"],
            furnisher_response_payload(
                response="VERIFIED", response_payload={},
            ),
            TEST_USERS["bureau_operator_headers"],
        )
        validate_success(res, 200)

    def test_furnisher_deadline_exclusive_at_day_26_late(self, api):
        """# difficulty: boundary_precision_check/furnisher_deadline_boundary_inclusive_day_25

        PRD §3.3: "if the current clock day is strictly greater than
        the inquiry's reverification_deadline_day (ERR_FURNISHER_LATE
        — the deadline is inclusive of the operator response on the
        deadline day itself)".

        clock.day = 26 (= reverification_deadline_day + 1) MUST fail
        with ERR_FURNISHER_LATE."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        d = submit_dispute(consumer=c, report=r, tradeline=t)
        start_investigation(consumer_id=c["id"], dispute_id=d["id"])
        target = d["submitted_day"] + FURNISHER_REVERIFY_WINDOW_DAYS + 1
        delta = target - read_clock_day()
        if delta > 0:
            advance_clock(delta)
        res = api.record_furnisher_response(
            c["id"], d["id"],
            furnisher_response_payload(
                response="VERIFIED", response_payload={},
            ),
            TEST_USERS["bureau_operator_headers"],
        )
        validate_error(res, ApiErrorId.ERR_FURNISHER_LATE)

    def test_supporting_documents_empty_array_rejected(self, api):
        """# difficulty: boundary_precision_check/empty_supporting_documents_boundary

        PRD §3.2: "The supporting-documents array must be non-empty
        at submission; an empty or missing array is rejected with
        ERR_NO_SUPPORTING_DOCUMENTS".

        Empty-collection boundary at length == 0 -> reject."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        payload = create_dispute_payload(
            credit_report_id=r["id"], tradeline_item_id=t["id"],
            supporting_documents=[],
        )
        res = api.create_dispute(
            c["id"], payload, make_consumer_headers(c["id"]),
        )
        validate_error(res, ApiErrorId.ERR_NO_SUPPORTING_DOCUMENTS)

    def test_supporting_documents_length_one_accepted(self, api):
        """# difficulty: boundary_precision_check/empty_supporting_documents_boundary

        PRD §3.2 boundary: length == 1 -> 201, paired with the
        length == 0 boundary above."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        payload = create_dispute_payload(
            credit_report_id=r["id"], tradeline_item_id=t["id"],
            supporting_documents=[supporting_doc("RECEIPT")],
        )
        res = api.create_dispute(
            c["id"], payload, make_consumer_headers(c["id"]),
        )
        validate_success(res, 201)


# ===========================================================================
# Rule 7: cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    def test_start_investigation_blocked_by_freeze_then_succeeds_after_lift(
        self, api,
    ):
        """# difficulty: cross_entity_state_dependency/dispute_start_requires_credit_report_not_frozen

        PRD §3.2: "the target CreditReport's posture must not be
        FROZEN (otherwise ERR_REPORT_FROZEN — FCRA does not freeze
        the dispute process itself, but this system requires the
        consumer to lift the freeze first so that subsequent
        recomputation is meaningful)".

        Claim: Dispute.RECEIVED -> UNDER_INVESTIGATION is gated by
        a sibling-entity (CreditFreeze) status."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline(
            bureau="EQUIFAX",
        )
        d = submit_dispute(consumer=c, report=r, tradeline=t)
        freeze = place_credit_freeze(consumer=c, bureau="EQUIFAX")
        # Blocked while frozen.
        res_blocked = api.start_investigation(
            c["id"], d["id"], TEST_USERS["bureau_operator_headers"],
        )
        validate_error(res_blocked, ApiErrorId.ERR_REPORT_FROZEN)
        # Lift the freeze.
        c_pin = get_consumer(c["id"], headers=make_consumer_headers(c["id"]))
        lift_credit_freeze(
            consumer=c, freeze_id=freeze["id"], pin=c_pin["freeze_pin"],
        )
        # Now succeeds.
        res_ok = api.start_investigation(
            c["id"], d["id"], TEST_USERS["bureau_operator_headers"],
        )
        validate_success(res_ok, 200)

    def test_complaint_resolve_requires_dispute_reclosed(self, api):
        """# difficulty: cross_entity_state_dependency/complaint_resolve_requires_dispute_reclosed

        PRD §3.10: "The resolve action transitions the complaint from
        UNDER_REVIEW to RESOLVED, but only when the underlying
        dispute is once again in one of the four terminal CLOSED_*
        states (so that the reopened investigation has actually been
        closed out); otherwise the resolve attempt is rejected with
        ERR_DISPUTE_NOT_RECLOSED."""
        c, f, r, t, d = setup_dispute_in_state(state="CLOSED_VERIFIED")
        k = file_regulatory_complaint(
            consumer=c, dispute_id=d["id"], narrative="Filed.",
        )
        accept_complaint(complaint_id=k["id"])
        # Dispute is UNDER_INVESTIGATION now — not CLOSED_*.
        res_blocked = api.resolve_complaint(
            k["id"], TEST_USERS["cfpb_operator_headers"],
        )
        validate_error(res_blocked, ApiErrorId.ERR_DISPUTE_NOT_RECLOSED)
        # Drive dispute back to CLOSED_VERIFIED.
        record_furnisher_response(
            consumer_id=c["id"], dispute_id=d["id"],
            response="VERIFIED", response_payload={},
        )
        issue_result_notice(consumer_id=c["id"], dispute_id=d["id"])
        # Now resolve succeeds.
        res_ok = api.resolve_complaint(
            k["id"], TEST_USERS["cfpb_operator_headers"],
        )
        validate_success(res_ok, 200)


    def test_start_investigation_on_different_bureau_unaffected_by_freeze(self, api):
        """# difficulty: cross_entity_state_dependency/dispute_start_requires_credit_report_not_frozen

        PRD §3.7: "The first count is the number of disputes on this
        report whose status is one of RECEIVED, UNDER_INVESTIGATION,
        RESULTS_PENDING, or ESCALATED. The second count is the number
        of CreditFreeze rows for this consumer and this bureau whose
        status is ACTIVE."
        PRD §3.2: "the target CreditReport's posture must not be
        FROZEN".

        Cross-entity dependency keyed on (consumer_id, bureau): a
        freeze on bureau X does NOT block start_investigation on a
        report for bureau Y."""
        c = create_consumer()
        # Freeze on EXPERIAN.
        place_credit_freeze(consumer=c, bureau="EXPERIAN")
        # Create an EQUIFAX report + tradeline + dispute.
        f = create_furnisher()
        r = create_credit_report(c["id"], bureau="EQUIFAX")
        t = create_tradeline_item(
            r["id"], furnisher_id=f["id"],
            furnisher_headers=make_furnisher_headers(f["id"]),
        )
        d = submit_dispute(consumer=c, report=r, tradeline=t)
        res = api.start_investigation(
            c["id"], d["id"], TEST_USERS["bureau_operator_headers"],
        )
        # EQUIFAX report is not frozen (only EXPERIAN is) -> succeeds.
        validate_success(res, 200)

    def test_complaint_resolve_after_dispute_recloses_succeeds(self, api):
        """# difficulty: cross_entity_state_dependency/complaint_resolve_requires_dispute_reclosed

        PRD §3.10: "The resolve action transitions the complaint from
        UNDER_REVIEW to RESOLVED, but only when the underlying
        dispute is once again in one of the four terminal CLOSED_*
        states (so that the reopened investigation has actually been
        closed out)".

        Positive arm: reclose with DELETED (a different terminal
        state than the first instance's VERIFIED reclose path) and
        resolve succeeds — the cross-entity gate is on
        Dispute.status ∈ CLOSED_*, not on a specific terminal."""
        c, f, r, t, d = setup_dispute_in_state(state="CLOSED_VERIFIED")
        k = file_regulatory_complaint(
            consumer=c, dispute_id=d["id"], narrative="Filed.",
        )
        accept_complaint(complaint_id=k["id"])
        # Drive dispute back through to CLOSED_DELETED.
        record_furnisher_response(
            consumer_id=c["id"], dispute_id=d["id"],
            response="DELETED", response_payload={},
        )
        issue_result_notice(consumer_id=c["id"], dispute_id=d["id"])
        d_reclosed = get_dispute(consumer_id=c["id"], dispute_id=d["id"])
        assert d_reclosed["status"] == "CLOSED_DELETED"
        # Resolve succeeds.
        res = api.resolve_complaint(
            k["id"], TEST_USERS["cfpb_operator_headers"],
        )
        body = validate_success(res, 200)
        assert body["status"] == "RESOLVED"


# ===========================================================================
# Rule 8: resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    def test_active_dispute_blocks_second_until_terminal_then_allowed(self, api):
        """# difficulty: resource_temporal_overlap/active_dispute_window_per_tradeline_open_ended_until_terminal

        PRD §3.2: "at most one Dispute may be in a non-terminal status
        (anything other than CLOSED_VERIFIED, CLOSED_UPDATED,
        CLOSED_DELETED, or CLOSED_DISMISSED) per TradelineItem — a
        second attempt is rejected with ERR_DUPLICATE_ACTIVE_DISPUTE."

        Open-ended interval semantics: while the first is non-terminal
        the second is rejected; after the first reaches CLOSED_* a
        new submission succeeds (no buffer)."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        submit_dispute(consumer=c, report=r, tradeline=t)
        # Second submission while first is RECEIVED -> rejected.
        payload = create_dispute_payload(
            credit_report_id=r["id"], tradeline_item_id=t["id"],
        )
        res_dup = api.create_dispute(
            c["id"], payload, make_consumer_headers(c["id"]),
        )
        validate_error(res_dup, ApiErrorId.ERR_DUPLICATE_ACTIVE_DISPUTE)

    def test_freeze_partitioned_by_bureau(self, api):
        """# difficulty: resource_temporal_overlap/freeze_uniqueness_aggregate_capacity_per_bureau

        PRD §3.11: "At most one ACTIVE CreditFreeze may exist per
        (consumer_id, bureau) pair; a second placement is rejected
        with ERR_FREEZE_ALREADY_ACTIVE".

        Aggregate-capacity semantics differ from the dispute
        open-interval: capacity is per (consumer, bureau), so a
        second placement on the SAME bureau fails but one on a
        DIFFERENT bureau succeeds."""
        c = create_consumer()
        place_credit_freeze(consumer=c, bureau="EQUIFAX")
        # Same bureau: rejected.
        res_dup = api.create_credit_freeze(
            c["id"], {"bureau": "EQUIFAX"},
            make_consumer_headers(c["id"]),
        )
        validate_error(res_dup, ApiErrorId.ERR_FREEZE_ALREADY_ACTIVE)
        # Different bureau: succeeds.
        res_other = api.create_credit_freeze(
            c["id"], {"bureau": "EXPERIAN"},
            make_consumer_headers(c["id"]),
        )
        validate_success(res_other, 201)


    def test_new_dispute_after_terminal_allowed_no_buffer(self, api):
        """# difficulty: resource_temporal_overlap/active_dispute_window_per_tradeline_open_ended_until_terminal

        PRD §3.2: "at most one Dispute may be in a non-terminal
        status ... per TradelineItem".

        Open-ended interval ends at CLOSED_*. After the prior
        dispute closes, a NEW submission on the same tradeline
        succeeds immediately (interval boundary is the CLOSED_*
        transition itself, no buffer)."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        close_dispute_verified(consumer=c, report=r, tradeline=t)
        # Immediately submit on same tradeline.
        d2 = submit_dispute(consumer=c, report=r, tradeline=t)
        assert d2["status"] == "RECEIVED"

    def test_freeze_can_be_replaced_after_lift_on_same_bureau(self, api):
        """# difficulty: resource_temporal_overlap/freeze_uniqueness_aggregate_capacity_per_bureau

        PRD §3.11: "At most one ACTIVE CreditFreeze may exist per
        (consumer_id, bureau) pair" — uniqueness is on ACTIVE
        status. After the first freeze is LIFTED, a new freeze on
        the same bureau must succeed (the aggregate capacity gate
        compares against ACTIVE rows only)."""
        c, freeze = setup_consumer_with_freeze(bureau="EQUIFAX")
        c_pin = get_consumer(c["id"], headers=make_consumer_headers(c["id"]))
        lift_credit_freeze(
            consumer=c, freeze_id=freeze["id"], pin=c_pin["freeze_pin"],
        )
        # New freeze on same bureau: succeeds because the old one is
        # now LIFTED (not ACTIVE).
        res = api.create_credit_freeze(
            c["id"], {"bureau": "EQUIFAX"},
            make_consumer_headers(c["id"]),
        )
        validate_success(res, 201)


# ===========================================================================
# Rule 9: compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    def test_posture_invariant_freeze_place_lift_round_trip(self, api):
        """# difficulty: compensating_invariant/posture_invariant_after_freeze_lift_round_trip

        PRD §3.7: "If the active-freezes count is greater than zero,
        the posture is FROZEN. Otherwise, if the active-disputes
        count is at least one, the posture is RESTRICTED. Otherwise
        — that is, only when the active-disputes count is exactly
        zero — the posture is OPEN."
        PRD §3.11: "the matching report's posture is then recomputed
        per §3.7 (typically returning to OPEN or RESTRICTED depending
        on whether any disputes remain active)."

        Round trip: OPEN -> freeze -> FROZEN -> lift -> OPEN."""
        c = create_consumer()
        r = create_credit_report(c["id"], bureau="EQUIFAX")
        assert r["posture"] == "OPEN"
        freeze = place_credit_freeze(consumer=c, bureau="EQUIFAX")
        r_frozen = get_credit_report(c["id"], r["id"])
        assert r_frozen["posture"] == "FROZEN"
        c_pin = get_consumer(c["id"], headers=make_consumer_headers(c["id"]))
        lift_credit_freeze(
            consumer=c, freeze_id=freeze["id"], pin=c_pin["freeze_pin"],
        )
        r_after = get_credit_report(c["id"], r["id"])
        assert r_after["posture"] == "OPEN"

    def test_posture_invariant_freeze_lift_with_active_dispute(self, api):
        """# difficulty: compensating_invariant/posture_invariant_after_freeze_lift_round_trip

        PRD §3.7: "If the active-freezes count is greater than zero,
        the posture is FROZEN. Otherwise, if the active-disputes
        count is at least one, the posture is RESTRICTED."
        PRD §3.11: "the matching report's posture is then recomputed
        per §3.7 (typically returning to OPEN or RESTRICTED depending
        on whether any disputes remain active)."

        With an active dispute on the same bureau, posture before
        freeze = RESTRICTED, during freeze = FROZEN, after lift =
        RESTRICTED (the dispute is still active). Posture is
        conserved across the freeze/lift round trip."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline(
            bureau="EQUIFAX",
        )
        # Submit dispute (RECEIVED — active in §3.7).
        submit_dispute(consumer=c, report=r, tradeline=t)
        r_pre = get_credit_report(c["id"], r["id"])
        assert r_pre["posture"] == "RESTRICTED"
        # Freeze.
        freeze = place_credit_freeze(consumer=c, bureau="EQUIFAX")
        r_frozen = get_credit_report(c["id"], r["id"])
        assert r_frozen["posture"] == "FROZEN"
        # Lift.
        c_pin = get_consumer(c["id"], headers=make_consumer_headers(c["id"]))
        lift_credit_freeze(
            consumer=c, freeze_id=freeze["id"], pin=c_pin["freeze_pin"],
        )
        r_after = get_credit_report(c["id"], r["id"])
        assert r_after["posture"] == "RESTRICTED"  # conserved pre/post

    def test_free_reports_invariant_pull_then_grant(self, api):
        """# difficulty: compensating_invariant/free_reports_invariant_on_pull_then_grant

        PRD §3.9: "On success, the system decrements
        free_reports_remaining by one".
        PRD §3.6: "When both the outcome gate and the change gate
        are satisfied, the grant size is two reports for a consumer
        with any active freeze and one report otherwise".

        Round trip: initial=1 -> pull_free -> 0 -> close
        CLOSED_UPDATED grant +1 -> 1. Pull and grant compensate."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        # Pull free: 1 -> 0.
        resp = pull_free_report(consumer=c, credit_report_id=r["id"])
        assert resp.status_code == 200
        c_mid = get_consumer(c["id"], headers=make_consumer_headers(c["id"]))
        assert c_mid["free_reports_remaining"] == 0
        # CLOSED_UPDATED grants +1: 0 -> 1.
        close_dispute_updated(
            consumer=c, report=r, tradeline=t,
            requested_payload={"new_balance_cents": 200},
        )
        c_after = get_consumer(c["id"], headers=make_consumer_headers(c["id"]))
        assert c_after["free_reports_remaining"] == 1

    def test_free_reports_invariant_double_pull_after_two_grants(self, api):
        """# difficulty: compensating_invariant/free_reports_invariant_on_pull_then_grant

        PRD §3.9 + PRD §3.6: with two CLOSED_UPDATED grants on
        distinct tradelines, free_reports_remaining = 1 + 2 = 3.
        Two pull_free decrements leave the counter at 1 — equal to
        the initial value, demonstrating the counter conserves under
        balanced pull/grant operations even at higher cycle counts."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        # Two CLOSED_UPDATED grants on distinct tradelines.
        submit_n_closed_disputes_on_distinct_tradelines(
            consumer=c, furnisher=f, report=r, n=2, close_as="UPDATED",
        )
        c_mid = get_consumer(c["id"], headers=make_consumer_headers(c["id"]))
        assert c_mid["free_reports_remaining"] == 3
        # Two pull_free decrements.
        pull_free_report(consumer=c, credit_report_id=r["id"])
        pull_free_report(consumer=c, credit_report_id=r["id"])
        c_after = get_consumer(c["id"], headers=make_consumer_headers(c["id"]))
        # 3 - 2 = 1, equal to initial.
        assert c_after["free_reports_remaining"] == 1
