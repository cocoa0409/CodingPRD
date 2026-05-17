"""Dedicated coverage for difficulty-design instances.

Every instance declared by the priority queue must be covered by at
least two tests. Most are covered by the rule-driven suites above; this
file fills in the gaps and adds the second test where needed.

Each test tags its docstring with `# difficulty: <rule_id>/<instance.name>`.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_minutes,
    add_seconds,
    advance_clock,
    adjudicate_claim,
    appeal_claim,
    create_session_payload,
    create_treatment_plan_payload,
    deny_claim,
    dispute_session_payload,
    draft_claim,
    expected_per_line_submitted_cents,
    get_authorization,
    get_clinic,
    get_patient,
    make_bcba_headers,
    pay_claim,
    schedule_session,
    setup_active_authorization,
    setup_active_treatment_plan,
    setup_basic_environment,
    setup_clinic_with_roster,
    setup_completed_evaluation,
    setup_completed_session,
    setup_completed_session_with_billed_units,
    setup_completed_sessions_for_supervision_ratio,
    setup_drafted_plan_with_in_progress_evaluation,
    setup_environment_with_two_authorizations,
    setup_ledger_for_authorization,
    setup_pending_authorization_unapproved,
    setup_two_completed_sessions_one_claim_draft,
    submit_claim,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantAuthorizationBalance:

    def test_authorization_read_exposes_both_balances(self, api):
        """PRD §2.9: "Both numbers are computed by aggregation over the
        BillingLedgerEntry rows for the Authorization and are exposed
        on every read of the Authorization as
        provisional_units_consumed and adjudicated_units_consumed."

        Claim: a freshly-created authorization's GET response carries
        both provisional_units_consumed and adjudicated_units_consumed.

        # difficulty: dual_variant_calc/authorization_unit_balance_provisional_vs_adjudicated
        """
        env = setup_basic_environment()
        auth = get_authorization(env["authorization"]["id"])
        assert "provisional_units_consumed" in auth
        assert "adjudicated_units_consumed" in auth


class TestDualVariantProgressScore:

    def test_patient_read_exposes_both_progress_scores(self, api):
        """PRD §3.7: "Every patient carries two computed progress
        scores. … It is stored on the patient's
        clinical_progress_score_provisional / _adjudicated and is
        recomputed every time a session completes (and whenever a
        downstream claim transition affects which sessions qualify)."

        Claim: a freshly-read patient carries both
        clinical_progress_score_provisional and
        clinical_progress_score_adjudicated.

        # difficulty: dual_variant_calc/patient_clinical_progress_score_provisional_vs_adjudicated
        """
        env = setup_basic_environment()
        patient = get_patient(env["patient"]["id"])
        assert "clinical_progress_score_provisional" in patient
        assert "clinical_progress_score_adjudicated" in patient


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestSessionDisputeDepth2Cascade:

    def test_session_dispute_appends_credit_with_matching_session_id(
        self, api,
    ):
        """PRD §2.11: "a session-driven entry carries the originating
        session_id … its entry_type is one of PROVISIONAL_DEBIT,
        PROVISIONAL_CREDIT, ADJUDICATED_DEBIT, or ADJUDICATED_CREDIT".
        PRD §3.5: "a PROVISIONAL_CREDIT is appended to the ledger with
        units_delta equal to the positive of billed_units and
        reason_code of SESSION_DISPUTED".

        Claim (hop 1): after /dispute on a 4-unit session, ledger
        contains a PROVISIONAL_CREDIT row whose session_id == the
        disputed session and units_delta == +4.

        # difficulty: transitive_cascade/session_dispute_depth_2_cascade
        """
        env = setup_completed_session_with_billed_units(billed_units=4)
        bcba = env["bcba"]
        api.dispute_session(
            env["session"]["id"],
            dispute_session_payload(dispute_reason="duplicate_note"),
            make_bcba_headers(bcba["id"]),
        )
        ledger = setup_ledger_for_authorization(env["authorization"]["id"])
        credits = [
            r for r in ledger
            if r["entry_type"] == "PROVISIONAL_CREDIT"
            and r["reason_code"] == "SESSION_DISPUTED"
        ]
        assert len(credits) == 1
        assert credits[0]["units_delta"] == 4
        assert credits[0].get("session_id") == env["session"]["id"]


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestStateVsReferentialOnClaimSubmit:

    def test_session_not_completed_fires_before_session_auth_mismatch(
        self, api, clinic_admin_headers,
    ):
        """PRD §2.8: "validations are evaluated in a fixed order so
        that the most foundational failure is reported first.
        Authentication is checked before role permission; role
        permission is checked before therapist-of-record ownership;
        ownership is checked before path existence; path existence is
        checked before body foreign-key existence; existence is checked
        before state preconditions; and only when the request has
        cleared all of the above does the system evaluate domain checks
        — safety/supervision compliance, referential consistency across
        entities … In particular, an ERR_INVALID_STATE rejection takes
        precedence over a downstream supervision-ratio or
        fiscal-capacity check".

        Claim: when a claim submit faces BOTH a SCHEDULED session (state
        violation) AND a session under a different authorization
        (referential violation), the state failure
        (ERR_SESSION_NOT_COMPLETED) is reported, not the referential
        failure.

        # difficulty: priority_pair_validation_conflict/state_vs_referential_on_claim_submit
        """
        roster = setup_clinic_with_roster(num_rbts=1)
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        rbt = roster["rbts"][0]
        plan = setup_active_treatment_plan(
            clinic=clinic, patient=roster["patient"], bcba=bcba,
        )
        auth_a, _ = setup_active_authorization(
            clinic=clinic, patient=roster["patient"], plan=plan,
            cpt_code="97153",
        )
        auth_b, _ = setup_active_authorization(
            clinic=clinic, patient=roster["patient"], plan=plan,
            cpt_code="97153",
        )
        # Session S1 under auth_a, NEVER completed (status SCHEDULED).
        clinic_state = get_clinic(clinic["id"])
        planned_start = add_seconds(clinic_state["now_ts"], seconds=86400)
        s1 = schedule_session(
            patient_id=roster["patient"]["id"],
            authorization_id=auth_a["id"],
            therapist_id=rbt["id"],
            session_type="DIRECT_RBT",
            planned_start=planned_start,
            planned_end=add_minutes(planned_start, minutes=60),
        )
        # Session S2 under auth_b, completed. Different authorization
        # than the claim's authorization_id (= auth_a) -> referential
        # mismatch.
        s2, _ = setup_completed_session(
            clinic=clinic, patient=roster["patient"],
            authorization=auth_b, therapist=rbt,
            therapist_role="RBT", session_type="DIRECT_RBT",
            duration_minutes=60, progress_rating=4,
        )
        # PRD §3.6 draft paragraph imposes the SAME state precondition
        # ("Each element of session_ids must reference a session in
        # COMPLETED") and the SAME referential check ("Every referenced
        # session's own authorization_id must equal the claim's
        # authorization_id — a claim is single-auth; a mismatch is
        # rejected with ERR_SESSION_AUTH_MISMATCH"). Per PRD §2.8 the
        # state precondition is evaluated before the referential check,
        # so /draft is the natural call to test the precedence — /submit
        # is unreachable because /draft itself would reject the same
        # request.
        from test_helpers import (
            create_claim_payload, validate_error_is_one_of,
        )
        res = api.create_claim(
            roster["patient"]["id"],
            create_claim_payload(
                authorization_id=auth_a["id"],
                session_ids=[s1["id"], s2["id"]],
            ),
            clinic_admin_headers,
        )
        # The state check (S1 not COMPLETED) precedes the referential
        # check (S2 under wrong auth). PRD names ERR_SESSION_NOT_COMPLETED
        # for this rule at /submit; at /draft the PRD states the rule
        # without naming an error_id, so a faithful implementer may emit
        # either ERR_SESSION_NOT_COMPLETED (the same rule) or
        # ERR_INVALID_STATE (the generic state precondition family).
        # What must NOT happen is ERR_SESSION_AUTH_MISMATCH: that would
        # violate the precedence rule under test.
        validate_error_is_one_of(
            res, ["ERR_SESSION_NOT_COMPLETED", "ERR_INVALID_STATE"],
        )


# ===========================================================================
# Rule 5 — second-instance coverage already exists in test_07.
# Add a second referential_vs_fiscal_on_session_create test here.
# ===========================================================================
class TestReferentialVsFiscalOnSessionCreate:

    def test_referential_no_rbt_to_supervise_fires_before_units_exhausted(
        self, api, clinic_admin_headers,
    ):
        """PRD §2.8: "referential consistency across entities, temporal
        admissibility of session intervals, fiscal/quota capacity
        against the authorization budget" — referential precedes fiscal.

        Claim: a BCBA_SUPERVISION create that simultaneously violates
        (a) no qualifying RBT history (referential) and (b) quota
        exhausted (fiscal) is rejected with the referential code
        ERR_NO_RBT_TO_SUPERVISE, not ERR_AUTH_UNITS_EXHAUSTED.

        # difficulty: priority_pair_validation_conflict/referential_vs_fiscal_on_session_create
        """
        # Build a supervision-only environment with approved_units=4
        # already consumed (so the next session would breach the quota).
        roster = setup_clinic_with_roster()
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        rbt = roster["rbts"][0]
        plan = setup_active_treatment_plan(
            clinic=clinic, patient=roster["patient"], bcba=bcba,
        )
        # Two auths: one 97153 (to give RBT history later if we want),
        # but we deliberately do NOT give the RBT a qualifying recent
        # session, so the referential check fires.
        bcba_auth, _ = setup_active_authorization(
            clinic=clinic, patient=roster["patient"], plan=plan,
            cpt_code="97155", approved_units=4,
        )
        # Consume the entire 4-unit quota with a BCBA supervision
        # session whose supervising RBT we don't validate against (we
        # need a precondition that an existing BCBA session can be
        # scheduled). PRD requires RBT history for supervision creation.
        # Instead of trying to exhaust the auth, we just request a
        # session whose planned_units == 5 (one more than approved):
        # both fiscal AND referential fail.
        planned_start = add_seconds(get_clinic(clinic["id"])["now_ts"],
                                    seconds=86400)
        # 5 units = 75 minutes.
        res = api.create_session(
            roster["patient"]["id"],
            create_session_payload(
                authorization_id=bcba_auth["id"],
                therapist_id=bcba["id"],
                session_type="BCBA_SUPERVISION",
                planned_start=planned_start,
                planned_end=add_minutes(planned_start, minutes=75),
                supervising_therapist_id=rbt["id"],
            ),
            clinic_admin_headers,
        )
        # PRD §2.8 places referential before fiscal, so the
        # referential error must win.
        validate_error(res, "ERR_NO_RBT_TO_SUPERVISE")


# ===========================================================================
# Rule 7 — cross_entity_state_dependency, second tests.
# ===========================================================================
class TestSessionStartRequiresAuthActiveSecondClaim:

    def test_after_clock_crosses_effective_start_session_start_succeeds(
        self, api,
    ):
        """PRD §3.4: "When the clinic's now_ts later crosses at or past
        the authorization's effective_start, the Authorization
        auto-transitions from APPROVED to ACTIVE on the next
        clock-advance."  PRD §3.5: "the Authorization must still be
        ACTIVE".

        Claim: once the Authorization is ACTIVE (because the clock has
        advanced past its effective_start) and a session has been
        scheduled under it, POST /sessions/{id}/start succeeds.

        Note: PRD §3.5 also requires the Authorization to be ACTIVE at
        scheduling time, so this happy-path test schedules the session
        AFTER the Authorization has reached ACTIVE.

        # difficulty: cross_entity_state_dependency/session_start_requires_authorization_active
        """
        # setup_basic_environment ends with an ACTIVE auth — the clock
        # has been advanced past effective_start inside the fixture so
        # the auth has auto-transitioned APPROVED → ACTIVE.
        env = setup_basic_environment()
        clinic = env["clinic"]
        rbt = env["rbts"][0]
        auth = env["authorization"]
        assert auth["status"] == "ACTIVE"
        # Schedule a session at planned_start = now_ts + 60s.
        planned_start = add_seconds(env["now_ts"], seconds=60)
        planned_end = add_minutes(planned_start, minutes=60)
        session = schedule_session(
            patient_id=env["patient"]["id"],
            authorization_id=auth["id"],
            therapist_id=rbt["id"],
            session_type="DIRECT_RBT",
            planned_start=planned_start,
            planned_end=planned_end,
        )
        # Advance the clock to planned_start.
        advance_clock(clinic["id"], 60)
        # /start should succeed: auth is ACTIVE.
        from test_helpers import make_rbt_headers
        res = api.start_session(
            session["id"], make_rbt_headers(rbt["id"]),
        )
        started = validate_success(res)
        assert started["status"] == "IN_PROGRESS"


class TestPlanActivationRequiresEvaluationCompletedSecond:

    def test_plan_activate_with_completed_evaluation_succeeds(self, api):
        """PRD §3.3: "the plan's source_evaluation_id must still
        resolve to a diagnostic evaluation in COMPLETED".

        Claim: once the source evaluation reaches COMPLETED, drafting
        and activating a plan against it succeeds — the negative path
        in test_05 covers the IN_PROGRESS case.

        # difficulty: cross_entity_state_dependency/plan_activate_requires_evaluation_completed
        """
        roster = setup_clinic_with_roster()
        bcba = roster["bcbas"][0]
        evaluation = setup_completed_evaluation(
            clinic=roster["clinic"],
            patient=roster["patient"],
            bcba=bcba,
        )
        from test_helpers import (
            activate_treatment_plan,
            draft_treatment_plan,
        )
        plan = draft_treatment_plan(
            patient_id=roster["patient"]["id"],
            source_evaluation_id=evaluation["id"],
            weekly_direct_hours_target=20,
            weekly_supervision_hours_target=2.0,
            weekly_parent_training_hours_target=1.0,
            bcba_id=bcba["id"],
        )
        activated = activate_treatment_plan(
            plan["id"], bcba_id=bcba["id"],
        )
        assert activated["status"] == "ACTIVE"


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestSessionCompleteDisputeZeroNetProvisional:

    def test_complete_then_dispute_yields_zero_net_provisional_consumption(
        self, api,
    ):
        """PRD §2.9: "provisional_units_consumed is the sum of the
        unit-deltas (sign-flipped to positive consumption) across every
        ledger entry on this authorization whose entry_type is either
        PROVISIONAL_DEBIT or PROVISIONAL_CREDIT."  PRD §3.5: a complete
        appends PROVISIONAL_DEBIT(-N); a dispute appends
        PROVISIONAL_CREDIT(+N).

        Claim: after one complete (+ -N) followed by one dispute (+
        +N), Authorization.provisional_units_consumed returns to its
        pre-action value (0 from empty), and the authorization's
        ledger contains exactly two rows with units_delta summing to 0.

        # difficulty: compensating_invariant/session_complete_dispute_zero_net_provisional_units
        """
        env = setup_completed_session_with_billed_units(billed_units=4)
        # Immediately after complete:
        auth_mid = get_authorization(env["authorization"]["id"])
        assert auth_mid["provisional_units_consumed"] == 4
        # Compensate with dispute.
        api.dispute_session(
            env["session"]["id"],
            dispute_session_payload(dispute_reason="invariant_test"),
            make_bcba_headers(env["bcba"]["id"]),
        )
        auth_final = get_authorization(env["authorization"]["id"])
        assert auth_final["provisional_units_consumed"] == 0
        ledger = setup_ledger_for_authorization(env["authorization"]["id"])
        # Exactly two rows (the complete and the dispute).
        assert len(ledger) == 2
        # And their units_delta sum is exactly 0.
        assert sum(r["units_delta"] for r in ledger) == 0

    def test_complete_then_dispute_invariant_holds_across_billed_unit_values(
        self, api,
    ):
        """PRD §2.9: provisional_units_consumed is computed by
        aggregation over the ledger. PRD §3.5: dispute appends a
        credit whose magnitude equals billed_units.

        Claim: for a session with billed_units == 8 (120 minutes),
        complete + dispute leaves provisional_units_consumed at 0 just
        as for billed_units == 4.

        # difficulty: compensating_invariant/session_complete_dispute_zero_net_provisional_units
        """
        env = setup_completed_session_with_billed_units(billed_units=8)
        api.dispute_session(
            env["session"]["id"],
            dispute_session_payload(),
            make_bcba_headers(env["bcba"]["id"]),
        )
        auth_final = get_authorization(env["authorization"]["id"])
        assert auth_final["provisional_units_consumed"] == 0


# ===========================================================================
# Rule 2 — combinatorial_formula second-test coverage.
# ===========================================================================
class TestSupervisionRatioInputArity:

    def test_supervision_ratio_with_zero_rbt_minutes_yields_one(self, api):
        """PRD §2.10: "If the RBT minute-total is zero the ratio is
        treated as exactly 1.0 (vacuously compliant — there is no RBT
        therapy to supervise)."

        Claim: when no qualifying DIRECT_RBT minutes exist in the
        trailing 30 days, GET supervision-ratio returns ratio == 1.0
        and compliant == true regardless of bcba_supervision_minutes.

        # difficulty: combinatorial_formula/supervision_ratio_three_input_non_linear_mode_a
        """
        # Use a 97155-only auth so no DIRECT_RBT sessions exist.
        env = setup_basic_environment(cpt_code="97155")
        snap = api.get_supervision_ratio(
            env["authorization"]["id"],
            {"X-User-ID": "clinic-admin-001",
             "X-User-Role": "ClinicAdmin"},
        ).json()["data"]
        assert snap["rbt_minutes"] == pytest.approx(0, abs=0.01)
        assert snap["ratio"] == pytest.approx(1.0, abs=1e-6)
        assert snap["compliant"] is True


class TestClaimSubmittedRoundingOrderingSecond:

    def test_submitted_amount_for_single_seven_unit_line_rounds_per_line(
        self, api,
    ):
        """PRD §3.6: "The session's per-line dollar amount is computed
        by multiplying the session's billed_units by the per-unit cents
        rate, dividing by 100 to obtain dollars, and multiplying by
        one minus the patient-responsibility percentage. That dollar
        amount is converted to cents by multiplying by 100 and applying
        round-half-up to obtain an integer cent amount for the line.
        The claim's submitted_amount_cents is then the integer sum of
        those per-line cent amounts."

        Claim: a single 7-unit DIRECT_RBT line yields per-line cents
        = round_half_up(7 * 3333 * 0.85) = 19831, and
        submitted_amount_cents equals exactly that.

        # difficulty: combinatorial_formula/claim_total_submitted_per_line_rounding_then_sum_mode_b
        """
        env = setup_basic_environment(approved_units=240)
        rbt = env["rbts"][0]
        s, _ = setup_completed_session(
            clinic=env["clinic"], patient=env["patient"],
            authorization=env["authorization"], therapist=rbt,
            therapist_role="RBT", session_type="DIRECT_RBT",
            duration_minutes=105,  # 7 units
            progress_rating=4,
        )
        claim = draft_claim(
            patient_id=env["patient"]["id"],
            authorization_id=env["authorization"]["id"],
            session_ids=[s["id"]],
        )
        submitted = submit_claim(claim["id"])
        expected = expected_per_line_submitted_cents(
            billed_units=7, session_type="DIRECT_RBT",
        )
        assert submitted["submitted_amount_cents"] == expected
        assert expected == 19831


# ===========================================================================
# Rule 5 — state_vs_referential second-test coverage.
# ===========================================================================
class TestStateVsReferentialSecond:

    def test_referential_alone_fires_when_state_passes(
        self, api, clinic_admin_headers,
    ):
        """PRD §3.6: "Every referenced session's own authorization_id
        must equal the claim's authorization_id — a claim is
        single-auth; a mismatch is rejected with
        ERR_SESSION_AUTH_MISMATCH."

        Claim: when only the referential violation is present (every
        referenced session is COMPLETED but belongs to a different
        authorization), the request is rejected with
        ERR_SESSION_AUTH_MISMATCH — confirming the referential check
        is exercised once the state check has cleared.

        # difficulty: priority_pair_validation_conflict/state_vs_referential_on_claim_submit
        """
        roster = setup_clinic_with_roster(num_rbts=1)
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        rbt = roster["rbts"][0]
        plan = setup_active_treatment_plan(
            clinic=clinic, patient=roster["patient"], bcba=bcba,
        )
        auth_a, _ = setup_active_authorization(
            clinic=clinic, patient=roster["patient"], plan=plan,
            cpt_code="97153",
        )
        auth_b, _ = setup_active_authorization(
            clinic=clinic, patient=roster["patient"], plan=plan,
            cpt_code="97153",
        )
        # Session under auth_b, completed (status check passes).
        s, _ = setup_completed_session(
            clinic=clinic, patient=roster["patient"],
            authorization=auth_b, therapist=rbt,
            therapist_role="RBT", session_type="DIRECT_RBT",
            duration_minutes=60, progress_rating=4,
        )
        # PRD §3.6's draft paragraph already enforces single-auth ("a
        # mismatch is rejected with ERR_SESSION_AUTH_MISMATCH"). Submit
        # only re-verifies the rule. Since draft fires the same check,
        # exercise the referential rule at /draft directly — /submit is
        # unreachable in this scenario because /draft rejects first.
        from test_helpers import create_claim_payload
        res = api.create_claim(
            roster["patient"]["id"],
            create_claim_payload(
                authorization_id=auth_a["id"],
                session_ids=[s["id"]],
            ),
            clinic_admin_headers,
        )
        validate_error(res, "ERR_SESSION_AUTH_MISMATCH")


class TestClaimSubmitDenyZeroNetBilledSessionCount:

    def test_submit_then_deny_returns_sessions_to_completed(self, api):
        """PRD §3.6: "Submission re-verifies that every referenced
        session is in COMPLETED … On submission, each referenced
        session cascades from COMPLETED to BILLED".  Then PRD §3.6 /
        §2.11: "Denying an adjudicated claim flips each referenced
        session back from BILLED to COMPLETED".

        Claim: after submit (forward) + adjudicate-with-reason + deny
        (compensate), every referenced session returns to COMPLETED;
        the count of BILLED sessions for that authorization equals its
        pre-action value (0).

        # difficulty: compensating_invariant/claim_submit_deny_zero_net_billed_session_count
        """
        env = setup_two_completed_sessions_one_claim_draft(
            billed_units_per_session=(4, 4),
        )
        submitted = submit_claim(env["claim"]["id"])
        assert submitted["status"] == "SUBMITTED"
        # Intermediate observation: sessions are BILLED.
        from test_helpers import TEST_USERS
        body = api.list_patient_sessions(
            env["patient"]["id"],
            TEST_USERS["clinic_admin_headers"],
        ).json()
        ids_mid = {s["id"]: s["status"] for s in body["data"]}
        for original in env["sessions"]:
            assert ids_mid[original["id"]] == "BILLED"
        # Compensate: adjudicate w/ reason then deny.
        adjudicate_claim(
            env["claim"]["id"], denial_reason="DUPLICATE_LINE",
        )
        deny_claim(env["claim"]["id"])
        body2 = api.list_patient_sessions(
            env["patient"]["id"],
            TEST_USERS["clinic_admin_headers"],
        ).json()
        ids_final = {s["id"]: s["status"] for s in body2["data"]}
        for original in env["sessions"]:
            assert ids_final[original["id"]] == "COMPLETED"

    def test_submit_then_deny_count_of_billed_returns_to_zero(self, api):
        """PRD §3.6: same as above — the compensating action moves
        BILLED sessions back to COMPLETED.

        Claim: count of TherapySession rows in BILLED for the
        authorization is 2 immediately after submit and 0 after
        deny — invariant restored.

        # difficulty: compensating_invariant/claim_submit_deny_zero_net_billed_session_count
        """
        env = setup_two_completed_sessions_one_claim_draft(
            billed_units_per_session=(4, 4),
        )
        submit_claim(env["claim"]["id"])
        from test_helpers import TEST_USERS
        # Count via list endpoint filtered by status=BILLED.
        body_mid = api.list_patient_sessions(
            env["patient"]["id"],
            TEST_USERS["clinic_admin_headers"],
            params={"status": "BILLED"},
        ).json()
        # Sessions belong to the test's authorization; in a fresh
        # tenant only the two we created should be present.
        count_mid = sum(
            1 for s in body_mid["data"]
            if s["authorization_id"] == env["authorization"]["id"]
        )
        assert count_mid == 2
        adjudicate_claim(env["claim"]["id"],
                         denial_reason="DUPLICATE_LINE")
        deny_claim(env["claim"]["id"])
        body_final = api.list_patient_sessions(
            env["patient"]["id"],
            TEST_USERS["clinic_admin_headers"],
            params={"status": "BILLED"},
        ).json()
        count_final = sum(
            1 for s in body_final["data"]
            if s["authorization_id"] == env["authorization"]["id"]
        )
        assert count_final == 0
