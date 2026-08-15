"""Appeals: the FILED → UNDER_REVIEW → {UPHELD, OVERTURNED} fork, the
overturn cascade onto policy/ledger/report, and segregation of duties.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_reinstatement,
    cancel_policy_effective,
    create_appeal_payload,
    decide_payload,
    file_appeal_under_review,
    make_compliance_officer_headers,
    make_policyholder_headers,
    open_cancellation_case,
    approve_cancellation,
    dispatch_cancellation_notices,
    submit_reinstatement,
    get_policy,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx

OFFICER = TEST_USERS["compliance_officer_headers"]


def _cancelled_0820(state_code, policy_number, premium_cents=40000, **profile_over):
    """A CANCELLED policy effective 2026-08-20 (noticed 2026-08-05)."""
    bundle = cancel_policy_effective(
        state_code,
        request_clock="2026-08-05T00:00:00Z",
        scheduled_effective_date="2026-08-20",
        mailed_on_date="2026-08-05",
        premium_cents=premium_cents,
        profile_over=profile_over,
        policy_number=policy_number,
    )
    fx.set_clock("2026-08-25T00:00:00Z")
    return bundle


class TestAppealTerminality:
    def test_appeal_overturned_is_terminal_cannot_decide_again(self, api):
        """PRD §3.8: "A decision then closes it: the deciding officer submits
        a `decision` of `UPHELD` or `OVERTURNED`, and segregation of duties
        forbids the accepting officer from also deciding — the decider's
        `X-User-ID` must differ from the accepter's, or the decision is
        rejected with `ERR_SEGREGATION_OF_DUTIES`. Either decision stamps
        `decided_on_date` with the current clock date, and both outcomes are
        terminal."

        Design: Corner/state_machines/appeal_overturned_is_terminal_cannot_decide_again
        """
        bundle = _cancelled_0820("OH", "P-OH-1", premium_cents=10000)
        appeal = file_appeal_under_review(
            bundle["case"]["id"], bundle["holder"]["id"], accept_officer_id="officer-oh-a"
        )
        decided = validate_success(
            api.decide_appeal(
                appeal["id"], decide_payload("UPHELD"), make_compliance_officer_headers("officer-oh-b")
            )
        )
        assert decided["status"] == "UPHELD"

        resp = api.decide_appeal(
            appeal["id"], decide_payload("OVERTURNED"), make_compliance_officer_headers("officer-oh-c")
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert fx.get_appeal(appeal["id"])["status"] == "UPHELD"


class TestAppealFork:
    def test_upheld_leaves_cancellation_untouched(self, api):
        """PRD §3.8: "An `UPHELD` outcome leaves the cancellation untouched."

        Design: Difficulty/non_linear_state_machine/appeal_case_branching_fork_overturn_vs_uphold
        """
        bundle = _cancelled_0820("AZ", "P-AP-1", premium_cents=40000)
        appeal = file_appeal_under_review(
            bundle["case"]["id"], bundle["holder"]["id"], grounds_text="Payment was mailed on time",
            accept_officer_id="officer-accept-1",
        )
        decided = validate_success(
            api.decide_appeal(
                appeal["id"], decide_payload("UPHELD"), make_compliance_officer_headers("officer-decide-1")
            )
        )
        assert decided["status"] == "UPHELD"
        assert get_policy(bundle["policy"]["id"])["status"] == "CANCELLED"
        assert fx.get_cancellation_case(bundle["case"]["id"])["status"] == "EFFECTIVE"

    def test_overturned_unwinds_effective_cancellation(self, api):
        """PRD §3.8: "An `OVERTURNED` outcome unwinds an effective
        cancellation: when the linked case is `EFFECTIVE`, the case is moved
        to `RESCINDED`, the policy returns `CANCELLED → ACTIVE` with its
        `reinstatements_used` unchanged, a compensating ledger entry of kind
        `RETURN_PRO_RATA` is posted with a positive amount exactly equal to
        the original negative return entry, the `rescinded_count` for the
        pinned profile and the current clock month is incremented, and the
        policy's `version` is bumped."

        Design: Difficulty/non_linear_state_machine/appeal_case_branching_fork_overturn_vs_uphold
        """
        bundle = _cancelled_0820("AZ", "P-AP-2", premium_cents=40000)
        appeal = file_appeal_under_review(
            bundle["case"]["id"], bundle["holder"]["id"], grounds_text="Bank error",
            accept_officer_id="officer-accept-2",
        )
        decided = validate_success(
            api.decide_appeal(
                appeal["id"], decide_payload("OVERTURNED"),
                make_compliance_officer_headers("officer-decide-2"),
            )
        )
        assert decided["status"] == "OVERTURNED"

        policy = get_policy(bundle["policy"]["id"])
        assert policy["status"] == "ACTIVE"
        assert policy["reinstatements_used"] == 0, "an overturn consumes no reinstatement slot"
        assert fx.get_cancellation_case(bundle["case"]["id"])["status"] == "RESCINDED"

        # 40000 premium, effective 2026-08-20: unearned = 14685; the
        # compensating entry mirrors the original negative return line.
        returns = [
            e for e in fx.policy_ledger(bundle["policy"]["id"])
            if e["entry_kind"] == "RETURN_PRO_RATA"
        ]
        amounts = sorted(e["amount_cents"] for e in returns)
        assert amounts == [-14685, 14685], f"expected -14685/+14685 pair, got {amounts}"


class TestOverturnCascade:
    def test_overturn_flips_case_and_policy(self, api):
        """PRD §3.8: "An `OVERTURNED` outcome unwinds an effective
        cancellation: when the linked case is `EFFECTIVE`, the case is moved
        to `RESCINDED`, the policy returns `CANCELLED → ACTIVE` with its
        `reinstatements_used` unchanged, a compensating ledger entry of kind
        `RETURN_PRO_RATA` is posted with a positive amount exactly equal to
        the original negative return entry, the `rescinded_count` for the
        pinned profile and the current clock month is incremented, and the
        policy's `version` is bumped."

        Design: Difficulty/transitive_cascade/appeal_overturn_to_policy_and_ledger_cascade
        """
        bundle = _cancelled_0820("NV", "P-OV-1", premium_cents=36500)
        appeal = file_appeal_under_review(
            bundle["case"]["id"], bundle["holder"]["id"], grounds_text="Proof of payment attached",
            accept_officer_id="officer-x",
        )
        decided = validate_success(
            api.decide_appeal(
                appeal["id"], decide_payload("OVERTURNED"), make_compliance_officer_headers("officer-y")
            )
        )
        assert decided["status"] == "OVERTURNED"

        case = fx.get_cancellation_case(bundle["case"]["id"])
        assert case["status"] == "RESCINDED"
        policy = get_policy(bundle["policy"]["id"])
        assert policy["status"] == "ACTIVE"
        assert policy["cancellation_effective_date"] is None

    def test_overturn_nets_ledger_and_balances_report(self, api):
        """PRD §3.8: "An `OVERTURNED` outcome unwinds an effective
        cancellation: when the linked case is `EFFECTIVE`, the case is moved
        to `RESCINDED`, the policy returns `CANCELLED → ACTIVE` with its
        `reinstatements_used` unchanged, a compensating ledger entry of kind
        `RETURN_PRO_RATA` is posted with a positive amount exactly equal to
        the original negative return entry, the `rescinded_count` for the
        pinned profile and the current clock month is incremented, and the
        policy's `version` is bumped."

        Design: Difficulty/transitive_cascade/appeal_overturn_to_policy_and_ledger_cascade
        """
        bundle = _cancelled_0820("NV", "P-OV-1", premium_cents=36500)
        appeal = file_appeal_under_review(
            bundle["case"]["id"], bundle["holder"]["id"], grounds_text="Proof of payment attached",
            accept_officer_id="officer-x",
        )
        validate_success(
            api.decide_appeal(
                appeal["id"], decide_payload("OVERTURNED"), make_compliance_officer_headers("officer-y")
            )
        )

        # Effective 2026-08-20 on a 365-day term at 36500 cents: return -13400.
        returns = [
            e for e in fx.policy_ledger(bundle["policy"]["id"])
            if e["entry_kind"] == "RETURN_PRO_RATA"
        ]
        amounts = sorted(e["amount_cents"] for e in returns)
        assert amounts == [-13400, 13400], f"return pair must net to zero, got {amounts}"

        report = fx.find_report(bundle["profile"]["id"], "2026-08")
        assert report["cancellation_count"] == 1
        assert report["rescinded_count"] == 1


class TestOverturnPreservesSlotBudget:
    def _full_chain(self):
        """VT policy: cancel effective 08-15, reinstate 08-16 (used 1),
        cancel again effective 09-01, appeal the second case UNDER_REVIEW."""
        bundle = cancel_policy_effective(
            "VT",
            request_clock="2026-08-01T00:00:00Z",
            scheduled_effective_date="2026-08-15",
            mailed_on_date="2026-08-01",
            premium_cents=36500,
            profile_over={"reinstatement_window_days": 60, "max_reinstatements": 2},
            policy_number="P-VT-1",
        )
        policy_id = bundle["policy"]["id"]
        holder_id = bundle["holder"]["id"]

        fx.set_clock("2026-08-16T00:00:00Z")
        rr = submit_reinstatement(policy_id, bundle["case"]["id"], holder_id)
        approve_reinstatement(rr["id"])
        mid = get_policy(policy_id)
        assert mid["reinstatements_used"] == 1

        case2 = open_cancellation_case(mid, ground_code="NONPAYMENT")
        approve_cancellation(case2["id"], "2026-09-01")
        dispatch_cancellation_notices(case2["id"], "2026-08-16", tracking_prefix="T-VT-2")
        fx.set_clock("2026-09-01T00:00:00Z")
        assert get_policy(policy_id)["status"] == "CANCELLED"

        fx.set_clock("2026-09-05T00:00:00Z")
        appeal = file_appeal_under_review(
            case2["id"], holder_id, grounds_text="Duplicate autopay charge",
            accept_officer_id="officer-vt-a",
        )
        return bundle, case2, appeal

    def test_overturn_restores_coverage_without_consuming_a_slot(self, api):
        """PRD §3.8: "An `OVERTURNED` outcome unwinds an effective
        cancellation: when the linked case is `EFFECTIVE`, the case is moved
        to `RESCINDED`, the policy returns `CANCELLED → ACTIVE` with its
        `reinstatements_used` unchanged, a compensating ledger entry of kind
        `RETURN_PRO_RATA` is posted with a positive amount exactly equal to
        the original negative return entry, the `rescinded_count` for the
        pinned profile and the current clock month is incremented, and the
        policy's `version` is bumped."

        Design: Difficulty/compensating_invariant/overturned_appeal_restores_reinstatement_slot_count
        """
        bundle, case2, appeal = self._full_chain()
        decided = validate_success(
            api.decide_appeal(
                appeal["id"], decide_payload("OVERTURNED"),
                make_compliance_officer_headers("officer-vt-b"),
            )
        )
        assert decided["status"] == "OVERTURNED"

        policy = get_policy(bundle["policy"]["id"])
        assert policy["status"] == "ACTIVE"
        assert policy["reinstatements_used"] == 1, (
            "the earlier reinstatement consumed one slot; the overturn consumes none"
        )

    def test_report_counts_balance_across_months(self, api):
        """PRD §2.10: "The `cancellation_count` counts cancellation cases that
        reached `EFFECTIVE` against policies pinned to that profile whose
        `scheduled_effective_date` falls within the period. The
        `rescinded_count` counts cancellation and nonrenewal cases whose
        rescission falls within the period."

        Design: Difficulty/compensating_invariant/overturned_appeal_restores_reinstatement_slot_count
        """
        bundle, _case2, appeal = self._full_chain()
        validate_success(
            api.decide_appeal(
                appeal["id"], decide_payload("OVERTURNED"),
                make_compliance_officer_headers("officer-vt-b"),
            )
        )

        report_aug = fx.find_report(bundle["profile"]["id"], "2026-08")
        assert report_aug["cancellation_count"] == 1  # first cancellation (08-15)
        report_sep = fx.find_report(bundle["profile"]["id"], "2026-09")
        assert report_sep["cancellation_count"] == 1  # second cancellation (09-01)
        assert report_sep["rescinded_count"] == 1  # overturn rescission (09-05)


class TestReinstatementApprovalGate:
    def test_policy_not_cancelled_blocks_reinstatement_approval(self, api):
        """PRD §3.7: "Approval also re-verifies the policy's position — it
        must still be `CANCELLED` (`ERR_POLICY_NOT_CANCELLED`), and its
        `reinstatements_used` must still be below the pinned profile's
        `max_reinstatements`, since a policy that has exhausted its
        reinstatement slots fails with `ERR_REINSTATEMENT_LIMIT_REACHED`."

        Design: Corner/errors/policy_not_cancelled_blocks_reinstatement_approval
        """
        bundle = _cancelled_0820("VI", "P-VI-1", premium_cents=10000)
        fx.set_clock("2026-08-21T00:00:00Z")
        rr = submit_reinstatement(bundle["policy"]["id"], bundle["case"]["id"], bundle["holder"]["id"])
        assert rr["status"] == "SUBMITTED"

        # An overturn restores the policy to ACTIVE before the approval lands.
        appeal = file_appeal_under_review(
            bundle["case"]["id"], bundle["holder"]["id"], grounds_text="Paid",
            accept_officer_id="officer-vi-a",
        )
        validate_success(
            api.decide_appeal(
                appeal["id"], decide_payload("OVERTURNED"),
                make_compliance_officer_headers("officer-vi-b"),
            )
        )
        assert get_policy(bundle["policy"]["id"])["status"] == "ACTIVE"

        resp = api.approve_reinstatement_request(rr["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_POLICY_NOT_CANCELLED)
        assert fx.get_reinstatement_request(rr["id"])["status"] == "SUBMITTED"
