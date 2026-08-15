"""Difficulty queue: boundary precision — supermajority threshold and exact-remaining pay."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adopted_and_billed_call,
    api_client,
    cast_vote,
    charter_amendment_payload,
    close_motion,
    create_and_open_motion,
    create_committee,
    add_member,
    create_policy,
    create_shareholder,
    get_committee,
    get_motion,
    list_call_assessments,
    pay_assessment_payload,
    validate_error,
    validate_success,
)


class TestSupermajorityExactThresholdBoundary:
    def _setup(self):
        create_policy(total_shares_authorized=1000000, board_quorum_count=2)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        b = create_shareholder("Dr B", 1000, "2016-01-01T00:00:00Z")
        c = create_shareholder("Dr C", 1000, "2017-01-01T00:00:00Z")
        committee = create_committee(
            name="Quality Committee", committee_type="QUALITY", quorum_count=1
        )
        add_member(committee["id"], a["id"], "MEMBER")
        return a, b, c, committee

    def test_votes_for_equal_required_adopts(self, api):
        """PRD §3.4: "For `SUPERMAJORITY`, `eligible_voter_count` is the snapshot size
        minus the recused count, `required_votes` is `supermajority_num` divided by
        `supermajority_den` multiplied by `eligible_voter_count` and rounded up to a
        whole ballot, and the motion is `ADOPTED` when `votes_for` is at least
        `required_votes` — equality adopts."
        PRD §3.4: "An adopted `CHARTER_AMENDMENT` applies `new_quorum_count` and
        `new_approval_threshold` to the referenced committee, increments
        `charter_version` by 1, and impairs the committee if the new quorum exceeds
        its active membership."
        3 eligible voters -> required_votes ceil(2/3 * 3) = 2; two FOR ballots adopt.

        Design: Difficulty/boundary_precision_check/supermajority_exact_threshold_boundary
        """
        a, b, _c, committee = self._setup()
        motion = create_and_open_motion(
            "CHARTER_AMENDMENT", a, charter_amendment_payload(new_quorum_count=1),
            committee_id=committee["id"],
        )
        assert motion["eligible_voter_count"] == 3
        assert motion["required_votes"] == 2
        cast_vote(motion["id"], a, "FOR")
        cast_vote(motion["id"], b, "FOR")
        closed = close_motion(motion["id"])
        assert closed["status"] == "ADOPTED", (
            "votes_for == 2 == required_votes must adopt (equality meets the threshold)"
        )
        assert closed["votes_for"] == 2
        committee_after = get_committee(committee["id"])
        assert committee_after["quorum_count"] == 1
        assert committee_after["charter_version"] == 2, (
            "the adoption side effect fires exactly once"
        )

    def test_votes_for_one_below_required_rejects(self, api):
        """PRD §3.4: "A motion that meets quorum but not its threshold becomes
        `REJECTED`."
        PRD §3.4: "First quorum: the count of non-voided ballots cast — of any choice,
        including `ABSTAIN` — must be at least `board_quorum_count`, otherwise
        `ERR_QUORUM_NOT_MET`."
        1 FOR + 1 AGAINST: ballots 2 >= quorum 2, but votes_for 1 < required 2.

        Design: Difficulty/boundary_precision_check/supermajority_exact_threshold_boundary
        """
        a, b, _c, committee = self._setup()
        motion = create_and_open_motion(
            "CHARTER_AMENDMENT", a, charter_amendment_payload(new_quorum_count=1),
            committee_id=committee["id"],
        )
        cast_vote(motion["id"], a, "FOR")
        cast_vote(motion["id"], b, "AGAINST")
        closed = close_motion(motion["id"])
        assert closed["status"] == "REJECTED", (
            "votes_for == 1 < required_votes == 2 must reject at the threshold boundary"
        )
        assert closed["required_votes"] == 2
        committee_after = get_committee(committee["id"])
        assert committee_after["charter_version"] == 1, (
            "a rejected motion fires no charter side effect"
        )
        assert get_motion(motion["id"])["status"] == "REJECTED"


class TestAssessmentPayExactRemainingBoundary:
    def test_exact_remaining_succeeds_to_paid(self, api):
        """PRD §3.5: "A payment below the remaining `total_due_cents` moves the
        assessment to `PARTIAL`; one that brings `paid_cents` exactly to
        `total_due_cents` moves it to `PAID` — and an amount equal to the remaining due
        always succeeds, while anything above the remaining due is rejected with
        `ERR_OVERPAYMENT`."

        Design: Difficulty/boundary_precision_check/assessment_pay_exact_remaining_boundary
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        _motion, _call, assessments = adopted_and_billed_call(
            a, 5000000, purpose="Call one"
        )
        assessment = assessments[0]
        assert assessment["assessed_cents"] == 5000000
        resp = api_client.pay_assessment(
            assessment["id"], pay_assessment_payload(5000000),
            TEST_USERS["board_admin_headers"],
        )
        paid = validate_success(resp)
        assert paid["status"] == "PAID"
        assert paid["paid_cents"] == 5000000
        assert paid["paid_cents"] == paid["total_due_cents"]

    def test_one_cent_over_rejected_one_cent_short_partial(self, api):
        """PRD §3.5: "A payment below the remaining `total_due_cents` moves the
        assessment to `PARTIAL`; one that brings `paid_cents` exactly to
        `total_due_cents` moves it to `PAID` — and an amount equal to the remaining due
        always succeeds, while anything above the remaining due is rejected with
        `ERR_OVERPAYMENT`."
        total_due + 1 is rejected with no partial application; total_due - 1 leaves
        the assessment PARTIAL one cent short.

        Design: Difficulty/boundary_precision_check/assessment_pay_exact_remaining_boundary
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        _m1, _c1, assessments = adopted_and_billed_call(a, 5000000, purpose="Call one")
        assessment = assessments[0]

        resp = api_client.pay_assessment(
            assessment["id"], pay_assessment_payload(5000001),
            TEST_USERS["board_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)

        untouched, _ = list_call_assessments(assessment["capital_call_id"])
        assert untouched[0]["paid_cents"] == 0, "a rejected overpayment applies nothing"
        assert untouched[0]["status"] == "BILLED"

        resp = api_client.pay_assessment(
            assessment["id"], pay_assessment_payload(4999999),
            TEST_USERS["board_admin_headers"],
        )
        partial = validate_success(resp)
        assert partial["status"] == "PARTIAL"
        assert partial["paid_cents"] == 4999999, "one cent short of PAID"
