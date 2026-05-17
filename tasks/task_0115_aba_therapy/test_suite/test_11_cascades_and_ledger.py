"""Cascade chains and ledger causality.

PRD §2.11 (cascading side effects, ledger causality), §3.4
(authorization auto-EXHAUSTED on claim pay).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    adjudicate_claim,
    advance_clock,
    appeal_claim,
    deny_claim,
    draft_claim,
    get_authorization,
    pay_claim,
    setup_active_authorization,
    setup_active_treatment_plan,
    setup_basic_environment,
    setup_clinic_with_roster,
    setup_completed_session,
    setup_completed_sessions_for_supervision_ratio,
    setup_ledger_for_authorization,
    setup_two_completed_sessions_one_claim_draft,
    submit_claim,
    validate_success,
)


class TestClaimPayCascadeDepth3:
    """Trigger: POST /claims/{id}/pay. Three sequential hops:
    (1) claim ADJUDICATED -> PAID + ADJUDICATED_DEBIT appended,
    (2) Authorization.adjudicated_units_consumed recomputes,
    (3) Authorization auto-transitions ACTIVE -> EXHAUSTED on hitting
        the budget.
    """

    def test_claim_pay_appends_adjudicated_debit_ledger_row(self, api):
        """PRD §2.11: "Paying an adjudicated claim appends an
        ADJUDICATED_DEBIT entry with reason_code of CLAIM_PAID,
        recomputes the Authorization's adjudicated_units_consumed".

        Claim (hop 1): after /pay, the authorization's ledger contains
        an ADJUDICATED_DEBIT row with reason_code == CLAIM_PAID whose
        units_delta is the negated sum of billed_units across the
        claim.

        # difficulty: transitive_cascade/claim_pay_depth_3_cascade
        """
        # 4-unit RBT session, fully paid via the supervision-compliant
        # pipeline.
        env = setup_completed_sessions_for_supervision_ratio(
            rbt_minutes_total=100, bcba_minutes_total=10,
        )
        claimed = env["rbt_sessions"][0]
        claim = draft_claim(
            patient_id=env["patient"]["id"],
            authorization_id=env["rbt_auth"]["id"],
            session_ids=[claimed["id"]],
        )
        claim = submit_claim(claim["id"])
        claim = adjudicate_claim(claim["id"])
        paid = pay_claim(claim["id"])
        assert paid["status"] == "PAID"
        ledger = setup_ledger_for_authorization(env["rbt_auth"]["id"])
        adj_debits = [
            r for r in ledger
            if r["entry_type"] == "ADJUDICATED_DEBIT"
            and r["reason_code"] == "CLAIM_PAID"
        ]
        assert len(adj_debits) == 1
        # The claimed session was 100/5 = 20 minutes RBT? No — each RBT
        # session was 100/5 = 20 minutes => 2 units. Verify via the
        # session's billed_units.
        assert adj_debits[0]["units_delta"] == -claimed["billed_units"]

    def test_claim_pay_recomputes_adjudicated_units_consumed(self, api):
        """PRD §2.11: "Paying an adjudicated claim … recomputes the
        Authorization's adjudicated_units_consumed".

        Claim (hop 2): after /pay, Authorization.adjudicated_units_consumed
        equals the absolute value of the appended ADJUDICATED_DEBIT.
        """
        env = setup_completed_sessions_for_supervision_ratio(
            rbt_minutes_total=100, bcba_minutes_total=10,
        )
        claimed = env["rbt_sessions"][0]
        claim = draft_claim(
            patient_id=env["patient"]["id"],
            authorization_id=env["rbt_auth"]["id"],
            session_ids=[claimed["id"]],
        )
        claim = submit_claim(claim["id"])
        adjudicate_claim(claim["id"])
        pay_claim(claim["id"])
        auth_after = get_authorization(env["rbt_auth"]["id"])
        assert auth_after["adjudicated_units_consumed"] == (
            claimed["billed_units"]
        )

    def test_claim_pay_drives_authorization_to_exhausted_on_zero_balance(
        self, api,
    ):
        """PRD §2.11: "if the recomputed adjudicated balance is at or
        below zero the Authorization auto-transitions from ACTIVE to
        EXHAUSTED in the same operation".

        Claim (hop 3): after paying a claim whose
        cumulative adjudicated debit equals approved_units, the
        authorization transitions to EXHAUSTED.

        # difficulty: transitive_cascade/claim_pay_depth_3_cascade
        """
        # Use an authorization with a tight quota so a single claim
        # drains it.
        roster = setup_clinic_with_roster()
        plan = setup_active_treatment_plan(
            clinic=roster["clinic"], patient=roster["patient"],
            bcba=roster["bcbas"][0],
        )
        # Two authorizations: one tight RBT (4 units approved), one
        # BCBA_SUPERVISION for the supervision-ratio gate.
        rbt_auth, _ = setup_active_authorization(
            clinic=roster["clinic"], patient=roster["patient"],
            plan=plan, cpt_code="97153", approved_units=4,
        )
        bcba_auth, _ = setup_active_authorization(
            clinic=roster["clinic"], patient=roster["patient"],
            plan=plan, cpt_code="97155", approved_units=4,
        )
        rbt = roster["rbts"][0]
        bcba = roster["bcbas"][0]
        # Complete one 4-unit RBT session (the entire RBT quota).
        rbt_session, _ = setup_completed_session(
            clinic=roster["clinic"], patient=roster["patient"],
            authorization=rbt_auth, therapist=rbt,
            therapist_role="RBT", session_type="DIRECT_RBT",
            duration_minutes=60, progress_rating=4,
        )
        # Provide a BCBA supervision session so the patient's
        # supervision ratio is compliant when we pay.
        setup_completed_session(
            clinic=roster["clinic"], patient=roster["patient"],
            authorization=bcba_auth, therapist=bcba,
            therapist_role="BCBA", session_type="BCBA_SUPERVISION",
            duration_minutes=15, progress_rating=4,
            supervising_therapist_id=rbt["id"],
        )
        claim = draft_claim(
            patient_id=roster["patient"]["id"],
            authorization_id=rbt_auth["id"],
            session_ids=[rbt_session["id"]],
        )
        submit_claim(claim["id"])
        adjudicate_claim(claim["id"])
        pay_claim(claim["id"])
        auth_after = get_authorization(rbt_auth["id"])
        assert auth_after["status"] == "EXHAUSTED"


class TestClaimDenyCascade:
    """Cascade: ADJUDICATED -> DENIED. Sessions BILLED -> COMPLETED,
    PROVISIONAL_CREDIT appended."""

    def test_deny_appends_provisional_credit_ledger_row(self, api):
        """PRD §2.11: "Denying an adjudicated claim flips each
        referenced session back from BILLED to COMPLETED and appends a
        PROVISIONAL_CREDIT ledger entry with reason_code of
        CLAIM_DENIED."

        Claim: after /deny, the authorization's ledger contains a
        PROVISIONAL_CREDIT row with reason_code == CLAIM_DENIED.
        """
        env = setup_two_completed_sessions_one_claim_draft()
        submit_claim(env["claim"]["id"])
        adjudicate_claim(
            env["claim"]["id"],
            denial_reason="MISSING_PROGRESS_NOTE",
        )
        deny_claim(env["claim"]["id"])
        ledger = setup_ledger_for_authorization(env["authorization"]["id"])
        denied_credits = [
            r for r in ledger
            if r["entry_type"] == "PROVISIONAL_CREDIT"
            and r["reason_code"] == "CLAIM_DENIED"
        ]
        assert len(denied_credits) == 1


class TestClaimAppealCascade:

    def test_appeal_cascades_sessions_back_to_billed(self, api):
        """PRD §2.11: "Appealing a denied claim again flips each
        referenced session from COMPLETED to BILLED."

        Claim: after /appeal, the referenced sessions are once again
        in BILLED status.

        # difficulty: non_linear_state_machine/insurance_claim_appeal_cycle
        """
        env = setup_two_completed_sessions_one_claim_draft()
        submit_claim(env["claim"]["id"])
        adjudicate_claim(
            env["claim"]["id"],
            denial_reason="MISSING_PROGRESS_NOTE",
        )
        deny_claim(env["claim"]["id"])
        appeal_claim(env["claim"]["id"])
        # Re-read sessions through the list endpoint.
        from test_helpers import TEST_USERS
        body = api.list_patient_sessions(
            env["patient"]["id"],
            TEST_USERS["clinic_admin_headers"],
        ).json()
        ids = {s["id"]: s["status"] for s in body["data"]}
        for original in env["sessions"]:
            assert ids[original["id"]] == "BILLED"


class TestAuthorizationExpiryCascade:
    """PRD §2.11 + §3.4: ACTIVE Authorization moving to EXPIRED cascades
    its SCHEDULED sessions to CANCELLED."""

    def test_authorization_expiry_cancels_scheduled_sessions(self, api):
        """PRD §2.11: "An Authorization moving from ACTIVE to EXPIRED
        cascades each of its SCHEDULED sessions to CANCELLED."

        Claim: after the clock crosses an authorization's effective_end,
        its SCHEDULED sessions become CANCELLED.
        """
        from test_helpers import (
            add_days,
            add_minutes,
            add_seconds,
            schedule_session,
            TEST_USERS,
        )
        env = setup_basic_environment()
        # Schedule a session well inside the window.
        rbt = env["rbts"][0]
        planned_start = add_days(env["now_ts"], days=1)
        planned_end = add_minutes(planned_start, minutes=60)
        session = schedule_session(
            patient_id=env["patient"]["id"],
            authorization_id=env["authorization"]["id"],
            therapist_id=rbt["id"],
            session_type="DIRECT_RBT",
            planned_start=planned_start,
            planned_end=planned_end,
        )
        # Push clock past effective_end (auth window is 180 days).
        advance_clock(env["clinic"]["id"], 200 * 86400)
        # Re-read the session via the list endpoint.
        body = api.list_patient_sessions(
            env["patient"]["id"], TEST_USERS["clinic_admin_headers"],
        ).json()
        ids = {s["id"]: s["status"] for s in body["data"]}
        assert ids[session["id"]] == "CANCELLED"
