"""Corner queue: capital call assessment math, payment bubble-up, late fee, empty eligible set."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adopted_and_billed_call,
    adopted_capital_call,
    api_client,
    bill_call,
    cast_vote,
    create_and_open_motion,
    create_policy,
    create_shareholder,
    distribution_payload,
    get_capital_call,
    get_physician,
    list_call_assessments,
    list_distributions,
    pay_assessment,
    set_clock,
    set_standing,
    validate_error,
)


class TestCapitalCallAssessmentResidualPenny:
    def test_billing_floors_and_residual_penny(self, api):
        """PRD §3.5: "Each assessment pins `shares_at_billing` from the snapshot and
        computes `assessed_cents` share-weighted: the raw amount is the call's
        `total_amount_cents` multiplied by the shareholder's shares and divided by
        total snapshot shares; each assessment is floored, and the residual pennies go
        one cent each to the largest holders by `shares_held`, ties broken by the
        physician's `created_at` ascending. The call's `assessed_total_cents` is the
        sum of the assessments, and billing moves the call from `APPROVED` to
        `BILLED`."
        5000001 over 1000/1000/500 -> floors 2000000/2000000/1000000, one residual
        penny to A (tie 1000=1000, created first).

        Design: Corner/calculations/capital_call_assessment_residual_penny
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        b = create_shareholder("Dr B", 1000, "2016-01-01T00:00:00Z")
        c = create_shareholder("Dr C", 500, "2025-01-01T00:00:00Z")
        _motion, call = adopted_capital_call(a, 5000001, purpose="Odd cent")
        billed = bill_call(call["id"])
        assert billed["status"] == "BILLED"
        assert billed["assessed_total_cents"] == 5000001, (
            "assessments must sum to the call total with no cent drift"
        )

        assessments, _ = list_call_assessments(call["id"])
        by_physician = {asm["physician_id"]: asm for asm in assessments}
        assert by_physician[a["id"]]["assessed_cents"] == 2000001
        assert by_physician[b["id"]]["assessed_cents"] == 2000000
        assert by_physician[c["id"]]["assessed_cents"] == 1000000
        assert by_physician[a["id"]]["shares_at_billing"] == 1000
        assert by_physician[c["id"]]["shares_at_billing"] == 500


class TestAssessmentPartialPayThenBubbleUp:
    def test_partial_payments_then_bubble_up_collected(self, api):
        """PRD §3.5: "A payment below the remaining `total_due_cents` moves the
        assessment to `PARTIAL`; one that brings `paid_cents` exactly to
        `total_due_cents` moves it to `PAID`"
        PRD §3.5: "Every payment adds the amount to the physician's
        `capital_account_balance_cents` and recomputes the call's `collected_cents` as
        the sum of `paid_cents` across its assessments; when every assessment is `PAID`
        the call bubbles up to `COLLECTED`."

        Design: Corner/state_machines/assessment_partial_pay_then_bubble_up_collected
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        _motion, call, assessments = adopted_and_billed_call(a, 5000000, purpose="Equipment")
        assessment = assessments[0]

        first = pay_assessment(assessment["id"], 2000000)
        assert first["status"] == "PARTIAL"
        assert first["paid_cents"] == 2000000
        assert get_physician(a["id"])["capital_account_balance_cents"] == 2000000

        second = pay_assessment(assessment["id"], 3000000)
        assert second["status"] == "PAID"
        call_after = get_capital_call(call["id"])
        assert call_after["status"] == "COLLECTED", "all assessments PAID bubbles up"
        assert call_after["collected_cents"] == 5000000
        assert get_physician(a["id"])["capital_account_balance_cents"] == 5000000


class TestLateFeeAppliedOnceAndDelinquentPayoff:
    def test_fee_once_and_fee_inclusive_payoff(self, api):
        """PRD §3.5: "An assessment not fully paid once the clock passes its
        `due_date` becomes `DELINQUENT`, and the late fee — `late_fee_cents`, computed
        as `assessed_cents` multiplied by `late_fee_pct` and rounded half-up — is
        applied exactly once; re-sweeps never compound it, so `total_due_cents` becomes
        `assessed_cents` plus the one-time fee. A `DELINQUENT` assessment can still be
        paid, now against the fee-inclusive total."
        5000000 assessed, 1000000 paid pre-due; sweep -> DELINQUENT with 500000 fee;
        second sweep does not compound; payoff of 4500000 reaches 5500000 -> PAID.

        Design: Corner/state_machines/late_fee_applied_once_and_delinquent_payoff
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        _motion, call, assessments = adopted_and_billed_call(
            a, 5000000, due_date="2026-08-10T00:00:00Z", purpose="Tail"
        )
        assessment = assessments[0]
        pay_assessment(assessment["id"], 1000000)

        set_clock("2026-08-11T00:00:00Z")
        after_first, _ = list_call_assessments(call["id"])
        assert after_first[0]["status"] == "DELINQUENT"
        assert after_first[0]["late_fee_cents"] == 500000
        assert after_first[0]["total_due_cents"] == 5500000

        set_clock("2026-08-12T00:00:00Z")
        after_second, _ = list_call_assessments(call["id"])
        assert after_second[0]["late_fee_cents"] == 500000, "re-sweep must not compound"
        assert after_second[0]["status"] == "DELINQUENT"

        paid = pay_assessment(assessment["id"], 4500000)
        assert paid["status"] == "PAID"
        assert paid["paid_cents"] == 5500000


class TestDistributionAdoptionRechecksEmptyEligibleSet:
    def test_close_fails_when_all_shareholders_suspended(self, api):
        """PRD §3.4: "An adopted `DISTRIBUTION` re-checks that at least one eligible
        shareholder exists — `SHAREHOLDER` exactly, not suspended — failing with
        `ERR_NO_ELIGIBLE_RECIPIENTS` (the same check also runs at motion creation)"

        Design: Corner/state_machines/distribution_adoption_rechecks_empty_eligible_set
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        s = create_shareholder("Dr S", 1000, "2014-01-01T00:00:00Z")
        t = create_shareholder("Dr T", 1000, "2015-01-01T00:00:00Z")
        motion = create_and_open_motion(
            "DISTRIBUTION", s, distribution_payload(100000)
        )
        cast_vote(motion["id"], t, "FOR")
        set_standing(s["id"], "SUSPENDED")
        set_standing(t["id"], "SUSPENDED")

        resp = api_client.close_motion(motion["id"], TEST_USERS["board_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_RECIPIENTS)
        distributions, _meta = list_distributions(params={"motion_id": motion["id"]})
        assert distributions == [], "the failed adoption must create no Distribution"
