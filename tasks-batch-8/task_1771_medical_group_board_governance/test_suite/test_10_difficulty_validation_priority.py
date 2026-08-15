"""Difficulty queue: priority-pair validation conflicts (state>fiscal, safety>temporal)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    adopted_and_billed_call,
    api_client,
    create_and_open_motion,
    create_policy,
    create_shareholder,
    file_coi_disclosure,
    get_motion,
    get_physician,
    list_call_assessments,
    make_physician_headers,
    pay_assessment_payload,
    review_coi_disclosure,
    set_clock,
    capital_call_payload,
    validate_error,
)


class TestAssessmentPayStateBeatsFiscal:
    def test_pay_defaulted_overpay_amount_returns_state_error(self, api):
        """PRD §2.7: "Sixth, state gates: the target resource must be in a status that
        permits the operation — the various state errors described in §3. Seventh,
        compliance gates on voting and sponsorship: recusal, unreviewed disclosures,
        and segregation of duties. Eighth, temporal gates: voting windows and term
        windows. Ninth, uniqueness, overlap, and cardinality rules. Tenth and last,
        money guards: overpayment, the distribution cap, treasury sufficiency, and
        installment exactness."
        PRD §2.7: "Every request is validated in a fixed priority order, and the first
        failure wins."
        A 99000000-cent payment on a DEFAULTED assessment is both a state failure
        (ERR_ASSESSMENT_NOT_PAYABLE) and a money-guard failure (ERR_OVERPAYMENT); the
        state error wins.

        Design: Difficulty/priority_pair_validation_conflict/assessment_pay_state_beats_fiscal
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        _motion, _call, assessments = adopted_and_billed_call(
            a, 5000000, due_date="2026-08-10T00:00:00Z", purpose="malpractice tail"
        )
        assessment = assessments[0]
        set_clock("2026-08-11T00:00:00Z")
        set_clock("2026-09-10T00:00:00Z")

        resp = api_client.pay_assessment(
            assessment["id"], pay_assessment_payload(99000000),
            TEST_USERS["board_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_PAYABLE)

    def test_default_sweep_applies_late_fee_once_and_suspends(self, api):
        """PRD §3.5: "An assessment not fully paid once the clock passes its
        `due_date` becomes `DELINQUENT`, and the late fee — `late_fee_cents`, computed
        as `assessed_cents` multiplied by `late_fee_pct` and rounded half-up — is
        applied exactly once; re-sweeps never compound it"
        PRD §3.5: "Once the clock passes `due_date` plus `delinquency_grace_days` —
        strictly; at exactly that instant the assessment is still `DELINQUENT` — the
        assessment becomes `DEFAULTED`, and the cascade fires: the physician's
        `standing` moves to `SUSPENDED` from either `GOOD_STANDING` or `PROBATION`"

        Design: Difficulty/priority_pair_validation_conflict/assessment_pay_state_beats_fiscal
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        _motion, call, assessments = adopted_and_billed_call(
            a, 5000000, due_date="2026-08-10T00:00:00Z", purpose="malpractice tail"
        )
        assessment = assessments[0]

        set_clock("2026-08-11T00:00:00Z")
        after_due, _ = list_call_assessments(call["id"])
        assert after_due[0]["status"] == "DELINQUENT"
        assert after_due[0]["late_fee_cents"] == 500000
        assert after_due[0]["total_due_cents"] == 5500000

        set_clock("2026-09-10T00:00:00Z")
        after_grace, _ = list_call_assessments(call["id"])
        assert after_grace[0]["status"] == "DEFAULTED"
        assert after_grace[0]["late_fee_cents"] == 500000, "late fee must not compound"
        physician = get_physician(a["id"])
        assert physician["standing"] == "SUSPENDED", (
            "the default cascade suspends the physician"
        )


class TestRecusedVoteSafetyBeatsTemporal:
    def _setup_recused_at_closes_at(self):
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        b = create_shareholder("Dr B", 1000, "2016-01-01T00:00:00Z")
        motion = create_and_open_motion(
            "CAPITAL_CALL", a, capital_call_payload(100000, purpose="Supplies")
        )
        disclosure = file_coi_disclosure(
            b, "B owns the supplier company", related_motion_id=motion["id"]
        )
        review_coi_disclosure(disclosure["id"], "FLAGGED")
        set_clock("2026-08-15T00:00:00Z")
        return a, b, motion

    def test_recused_voter_at_closes_at_gets_recused_error(self, api):
        """PRD §2.7: "Seventh, compliance gates on voting and sponsorship: recusal,
        unreviewed disclosures, and segregation of duties. Eighth, temporal gates:
        voting windows and term windows."
        PRD §2.7: "Every request is validated in a fixed priority order, and the first
        failure wins."
        PRD §3.4: "the voter must not appear in `recused_physician_ids` for this
        motion (`ERR_VOTER_RECUSED`)".
        A ballot from a recused voter at exactly closes_at is both recused and outside
        the voting window; the compliance gate fires first.

        Design: Difficulty/priority_pair_validation_conflict/recused_vote_safety_beats_temporal
        """
        _a, b, motion = self._setup_recused_at_closes_at()
        resp = api_client.cast_vote(
            motion["id"], {"vote_choice": "FOR"}, make_physician_headers(b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_VOTER_RECUSED)

    def test_motion_stays_open_at_exactly_closes_at(self, api):
        """PRD §3.4: "The clock sweep expires `OPEN` and `TABLED` motions once the
        clock passes `closes_at`."
        At clock == closes_at the strict-past sweep has not fired, so the motion is
        still OPEN; the rejected ballot leaves votes_for at 0.

        Design: Difficulty/priority_pair_validation_conflict/recused_vote_safety_beats_temporal
        """
        _a, b, motion = self._setup_recused_at_closes_at()
        resp = api_client.cast_vote(
            motion["id"], {"vote_choice": "FOR"}, make_physician_headers(b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_VOTER_RECUSED)
        motion_after = get_motion(motion["id"])
        assert motion_after["status"] == "OPEN", (
            "clock == closes_at must not trigger the strict-past expiry sweep"
        )
        assert motion_after["votes_for"] == 0
