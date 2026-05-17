"""Insurance claim lifecycle: draft -> submit -> adjudicate -> pay |
deny -> appeal cycle.

PRD §3.6 (claims).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_minutes,
    add_seconds,
    adjudicate_claim,
    adjudicate_claim_payload,
    appeal_claim,
    assert_insurance_claim,
    create_claim_payload,
    deny_claim,
    draft_claim,
    pay_claim,
    setup_active_authorization,
    setup_active_treatment_plan,
    setup_adjudicated_claim_for_rbt_session,
    setup_basic_environment,
    setup_clinic_with_roster,
    setup_completed_session,
    setup_two_completed_sessions_one_claim_draft,
    submit_claim,
    validate_error,
    validate_success,
)


class TestDraftClaim:

    def test_draft_claim_starts_in_draft(self, api, clinic_admin_headers):
        """PRD §3.6: "At creation, appeal_round is 0,
        submitted_amount_cents and reimbursed_amount_cents are 0,
        denial_reason is null, and the claim's status is DRAFT."

        Claim: a freshly-drafted claim has status DRAFT, appeal_round
        0, submitted_amount_cents 0, reimbursed_amount_cents 0,
        denial_reason null.
        """
        env = setup_two_completed_sessions_one_claim_draft()
        claim = env["claim"]
        assert_insurance_claim(claim)
        assert claim["status"] == "DRAFT"
        assert claim["appeal_round"] == 0
        assert claim["submitted_amount_cents"] == 0
        assert claim["reimbursed_amount_cents"] == 0
        assert claim.get("denial_reason") is None


class TestSubmitClaim:

    def test_submit_claim_transitions_to_submitted(self, api):
        """PRD §3.6: "Submitting the claim moves it from DRAFT to
        SUBMITTED."

        Claim: after /submit, claim.status == SUBMITTED.
        """
        env = setup_two_completed_sessions_one_claim_draft()
        submitted = submit_claim(env["claim"]["id"])
        assert submitted["status"] == "SUBMITTED"

    def test_submit_claim_cascades_sessions_to_billed(self, api):
        """PRD §3.6: "On submission, each referenced session cascades
        from COMPLETED to BILLED".

        Claim: after /submit, every referenced session has status
        BILLED.
        """
        env = setup_two_completed_sessions_one_claim_draft()
        submit_claim(env["claim"]["id"])
        # Re-read each session through the patient list.
        body = api.list_patient_sessions(
            env["patient"]["id"], env_clinic_admin_headers(),
        ).json()
        ids = {s["id"]: s["status"] for s in body["data"]}
        for original in env["sessions"]:
            assert ids[original["id"]] == "BILLED"

    def test_submit_empty_session_list_yields_empty_claim(
        self, api, clinic_admin_headers,
    ):
        """PRD §3.6: "The sum of billed_units across the referenced
        sessions must be strictly greater than zero — a sum of exactly
        zero is rejected with ERR_EMPTY_CLAIM."

        Claim: a claim drafted with session_ids=[] is rejected at submit
        time with ERR_EMPTY_CLAIM.

        # difficulty: boundary_precision_check/empty_claim_zero_units_boundary
        """
        env = setup_basic_environment()
        claim = draft_claim(
            patient_id=env["patient"]["id"],
            authorization_id=env["authorization"]["id"],
            session_ids=[],
        )
        res = api.submit_claim(claim["id"], clinic_admin_headers)
        validate_error(res, "ERR_EMPTY_CLAIM")

    def test_submit_claim_with_one_session_passes_boundary(self, api):
        """PRD §3.6: "The sum of billed_units across the referenced
        sessions must be strictly greater than zero".

        Claim: a claim referencing one session with billed_units > 0
        submits successfully (sum > 0 passes).

        # difficulty: boundary_precision_check/empty_claim_zero_units_boundary
        """
        env = setup_two_completed_sessions_one_claim_draft(
            billed_units_per_session=(4,),
        )
        submitted = submit_claim(env["claim"]["id"])
        assert submitted["status"] == "SUBMITTED"

    def test_submit_with_session_under_different_authorization_rejected(
        self, api, clinic_admin_headers,
    ):
        """PRD §3.6: "Every referenced session's own authorization_id
        must equal the claim's authorization_id — a claim is
        single-auth; a mismatch is rejected with
        ERR_SESSION_AUTH_MISMATCH."

        Claim: drafting a claim whose session_ids include a session
        under a DIFFERENT authorization is rejected with
        ERR_SESSION_AUTH_MISMATCH (PRD §3.6 places this check in the
        draft paragraph, so the rejection lands at /draft, not at
        /submit).
        """
        # Build env with two RBT authorizations and a session under each.
        roster = setup_clinic_with_roster()
        plan = setup_active_treatment_plan(
            clinic=roster["clinic"], patient=roster["patient"],
            bcba=roster["bcbas"][0],
        )
        auth_a, _ = setup_active_authorization(
            clinic=roster["clinic"], patient=roster["patient"],
            plan=plan, cpt_code="97153",
        )
        auth_b, _ = setup_active_authorization(
            clinic=roster["clinic"], patient=roster["patient"],
            plan=plan, cpt_code="97153",
        )
        rbt = roster["rbts"][0]
        # Two completed sessions, each under its own auth.
        s_a, _ = setup_completed_session(
            clinic=roster["clinic"], patient=roster["patient"],
            authorization=auth_a, therapist=rbt,
            therapist_role="RBT", session_type="DIRECT_RBT",
            duration_minutes=60, progress_rating=4,
        )
        s_b, _ = setup_completed_session(
            clinic=roster["clinic"], patient=roster["patient"],
            authorization=auth_b, therapist=rbt,
            therapist_role="RBT", session_type="DIRECT_RBT",
            duration_minutes=60, progress_rating=4,
        )
        # Attempt to draft a claim against auth_a that also includes
        # s_b (which is under auth_b). PRD §3.6 rejects at the draft
        # step with ERR_SESSION_AUTH_MISMATCH.
        from test_helpers import create_claim_payload
        res = api.create_claim(
            roster["patient"]["id"],
            create_claim_payload(
                authorization_id=auth_a["id"],
                session_ids=[s_a["id"], s_b["id"]],
            ),
            clinic_admin_headers,
        )
        validate_error(res, "ERR_SESSION_AUTH_MISMATCH")


def env_clinic_admin_headers():
    from test_helpers import TEST_USERS
    return TEST_USERS["clinic_admin_headers"]


class TestAdjudicateClaim:

    def test_adjudicate_without_denial_reason(self, api):
        """PRD §3.6: "A PayerAdmin adjudicates the claim by posting the
        adjudicate capability with an optional body field
        denial_reason. The capability transitions the claim from
        SUBMITTED (or from APPEALED in the appeal-cycle case) to
        ADJUDICATED."

        Claim: /adjudicate without denial_reason transitions claim to
        ADJUDICATED with denial_reason null.
        """
        env = setup_two_completed_sessions_one_claim_draft()
        submit_claim(env["claim"]["id"])
        adjudicated = adjudicate_claim(env["claim"]["id"])
        assert adjudicated["status"] == "ADJUDICATED"
        assert adjudicated.get("denial_reason") is None

    def test_adjudicate_with_denial_reason_records_it(self, api):
        """PRD §3.6: "When denial_reason is supplied, it is recorded on
        the claim; permitted values are SUPERVISION_RATIO_BREACH,
        UNITS_OUT_OF_AUTH, MISSING_PROGRESS_NOTE, or DUPLICATE_LINE."

        Claim: /adjudicate with denial_reason=MISSING_PROGRESS_NOTE
        records that reason on the claim.
        """
        env = setup_two_completed_sessions_one_claim_draft()
        submit_claim(env["claim"]["id"])
        adjudicated = adjudicate_claim(
            env["claim"]["id"], denial_reason="MISSING_PROGRESS_NOTE",
        )
        assert adjudicated["status"] == "ADJUDICATED"
        assert adjudicated.get("denial_reason") == "MISSING_PROGRESS_NOTE"


class TestPayClaim:

    def test_pay_adjudicated_claim_transitions_to_paid(self, api):
        """PRD §3.6: "Paying an adjudicated claim moves it to the
        terminal PAID status. Payment is permitted only when
        denial_reason is null and the patient's supervision ratio over
        the trailing 30-day window is at least 0.10 at the moment of
        payment".

        Claim: paying an ADJUDICATED claim with no denial_reason and
        compliant supervision ratio yields PAID.
        """
        env = setup_adjudicated_claim_for_rbt_session()
        paid = pay_claim(env["claim"]["id"])
        assert paid["status"] == "PAID"

    def test_pay_claim_with_denial_reason_rejected(self, api):
        """PRD §3.6: "Payment is permitted only when denial_reason is
        null".

        Claim: a PayerAdmin attempting to pay an ADJUDICATED claim
        whose denial_reason is set is rejected (state precondition
        violation).
        """
        env = setup_adjudicated_claim_for_rbt_session()
        # Re-adjudicate with a denial reason... actually claim is
        # already ADJUDICATED. We must denounce + appeal + readjudicate
        # path. Simpler: use a fresh claim adjudicated with
        # denial_reason.
        env2 = setup_two_completed_sessions_one_claim_draft()
        submit_claim(env2["claim"]["id"])
        adjudicate_claim(
            env2["claim"]["id"],
            denial_reason="MISSING_PROGRESS_NOTE",
        )
        from test_helpers import validate_error_is_one_of
        res = api.pay_claim(
            env2["claim"]["id"], env_payer_admin_headers(),
        )
        # PRD calls this a "state precondition" failure but does not
        # nail down a unique error_id; accept the natural family.
        validate_error_is_one_of(
            res, ["ERR_INVALID_STATE", "ERR_CLAIM_STATE_INVALID"],
        )


def env_payer_admin_headers():
    from test_helpers import TEST_USERS
    return TEST_USERS["payer_admin_headers"]


class TestDenyClaim:

    def test_deny_adjudicated_claim_requires_denial_reason(self, api):
        """PRD §3.6: "Denying an adjudicated claim moves it to DENIED
        and is permitted only when denial_reason is already recorded
        on the claim."

        Claim: /deny without a recorded denial_reason is rejected.
        """
        env = setup_two_completed_sessions_one_claim_draft()
        submit_claim(env["claim"]["id"])
        adjudicate_claim(env["claim"]["id"])  # no denial_reason
        from test_helpers import validate_error_is_one_of
        res = api.deny_claim(
            env["claim"]["id"], env_payer_admin_headers(),
        )
        validate_error_is_one_of(
            res, ["ERR_INVALID_STATE", "ERR_VALIDATION"],
        )

    def test_deny_adjudicated_claim_with_reason_cascades_to_completed(
        self, api,
    ):
        """PRD §3.6: "The denial cascades each referenced session from
        BILLED back to COMPLETED".

        Claim: after /deny, the referenced session(s) return to
        COMPLETED.
        """
        env = setup_two_completed_sessions_one_claim_draft()
        submit_claim(env["claim"]["id"])
        adjudicate_claim(
            env["claim"]["id"],
            denial_reason="MISSING_PROGRESS_NOTE",
        )
        deny_claim(env["claim"]["id"])
        body = api.list_patient_sessions(
            env["patient"]["id"], env_clinic_admin_headers(),
        ).json()
        ids = {s["id"]: s["status"] for s in body["data"]}
        for original in env["sessions"]:
            assert ids[original["id"]] == "COMPLETED"


class TestAppealCycle:

    def test_appeal_increments_appeal_round_and_clears_denial_reason(
        self, api,
    ):
        """PRD §3.6: "On appeal, appeal_round is incremented by one,
        denial_reason is cleared, and the referenced sessions cascade
        from COMPLETED back to BILLED."

        Claim: after /deny then /appeal, appeal_round == 1 and
        denial_reason is null.

        # difficulty: non_linear_state_machine/insurance_claim_appeal_cycle
        """
        env = setup_two_completed_sessions_one_claim_draft()
        submit_claim(env["claim"]["id"])
        adjudicate_claim(
            env["claim"]["id"],
            denial_reason="MISSING_PROGRESS_NOTE",
        )
        deny_claim(env["claim"]["id"])
        appealed = appeal_claim(env["claim"]["id"])
        assert appealed["status"] == "APPEALED"
        assert appealed["appeal_round"] == 1
        assert appealed.get("denial_reason") is None

    def test_appeal_after_two_rounds_rejected(self, api):
        """PRD §3.6: "A denied claim can be appealed by a ClinicAdmin,
        moving it from DENIED to APPEALED. The appeal is permitted only
        when appeal_round is strictly less than 2 — a third appeal
        attempt is rejected with ERR_APPEAL_LIMIT_REACHED."

        Claim: after two successful deny/appeal cycles (so appeal_round
        == 2), a third /appeal returns ERR_APPEAL_LIMIT_REACHED.

        # difficulty: non_linear_state_machine/insurance_claim_appeal_cycle
        """
        env = setup_two_completed_sessions_one_claim_draft()
        submit_claim(env["claim"]["id"])
        # Round 0 -> 1.
        adjudicate_claim(
            env["claim"]["id"],
            denial_reason="MISSING_PROGRESS_NOTE",
        )
        deny_claim(env["claim"]["id"])
        appealed = appeal_claim(env["claim"]["id"])
        assert appealed["appeal_round"] == 1
        # Round 1 -> 2.
        adjudicate_claim(
            env["claim"]["id"],
            denial_reason="MISSING_PROGRESS_NOTE",
        )
        deny_claim(env["claim"]["id"])
        appealed = appeal_claim(env["claim"]["id"])
        assert appealed["appeal_round"] == 2
        # Round 2 -> 3 must fail.
        adjudicate_claim(
            env["claim"]["id"],
            denial_reason="MISSING_PROGRESS_NOTE",
        )
        deny_claim(env["claim"]["id"])
        res = api.appeal_claim(
            env["claim"]["id"], env_clinic_admin_headers(),
        )
        validate_error(res, "ERR_APPEAL_LIMIT_REACHED")


class TestClaimReadShape:

    def test_get_claim_returns_full_shape(self, api):
        """PRD §3.6: "The patient-scoped claim list and the single-claim
        read return the same claim shape, including appeal_round,
        submitted_amount_cents, reimbursed_amount_cents, and
        denial_reason."

        Claim: GET /claims/{id} returns all four fields.
        """
        env = setup_adjudicated_claim_for_rbt_session()
        res = api.get_claim(env["claim"]["id"], env_clinic_admin_headers())
        data = validate_success(res)
        assert "appeal_round" in data
        assert "submitted_amount_cents" in data
        assert "reimbursed_amount_cents" in data
        assert "denial_reason" in data
