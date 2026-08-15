"""Retainage release: releasability gate, amount cap, pay cascade, conservation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_approved_release,
    create_release,
    get_budget_line,
    get_loan,
    setup_funded_scenario,
    setup_loan_with_lines,
    validate_error,
    validate_success,
)

SERVICER = TEST_USERS["loan_servicer_headers"]


class TestReleaseGates:
    def test_release_before_milestone_rejected(self, api):
        """PRD §3.6: "Withheld retainage is released deliberately, never
        automatically. A release may be requested only once the loan's
        `milestone_reached` is true or an `ACCEPTED` inspection reporting exactly
        100.00 exists for the loan; before either condition holds, the request is
        rejected with `ERR_RETAINAGE_NOT_RELEASABLE` (HTTP 409)."

        Design: Corner/validations/release_before_milestone_rejected
        """
        sc = setup_loan_with_lines()
        resp = api.create_retainage_release(
            {
                "loan_id": sc["loan"]["id"],
                "budget_line_id": sc["lines"]["SITE"]["id"],
                "amount_cents": 1_000,
                "reason": "Too early",
            },
            sc["borrower_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RETAINAGE_NOT_RELEASABLE)

    def test_release_exceeds_retained_rejected(self, api):
        """PRD §3.6: "The requested amount may not exceed the line's currently
        withheld `retained_cents`, checked at creation with
        `ERR_RELEASE_EXCEEDS_RETAINED` (HTTP 422)."

        Design: Corner/validations/release_exceeds_retained_rejected
        """
        sc = setup_funded_scenario()
        line = sc["lines"]["SITE"]
        assert get_budget_line(line["id"])["retained_cents"] == 500_000

        resp = api.create_retainage_release(
            {
                "loan_id": sc["loan"]["id"],
                "budget_line_id": line["id"],
                "amount_cents": 500_001,
                "reason": "One cent too many",
            },
            sc["borrower_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RELEASE_EXCEEDS_RETAINED)


class TestReleasePayCascade:
    def _approved_release(self):
        sc = setup_funded_scenario()
        release = create_approved_release(sc, sc["lines"]["SITE"]["id"], 500_000,
                                          reason="Milestone reduction release")
        return sc, release

    def test_release_pay_cascade_line_transfer(self, api):
        """PRD §3.6: "Payment moves money within the line: `retained_cents` falls
        by the amount and `disbursed_cents` grows by the same amount, with the
        budget line's `version` incrementing."
        PRD §3.6: "The release settles `PAID`, terminal alongside `REJECTED`."

        Design: Difficulty/transitive_cascade/release_pay_cascade
        """
        sc, release = self._approved_release()
        paid = validate_success(api.pay_retainage_release(release["id"], SERVICER),
                                200)
        assert paid["status"] == "PAID"

        line = get_budget_line(sc["lines"]["SITE"]["id"])
        assert line["retained_cents"] == 0
        assert line["disbursed_cents"] == 10_000_000, (
            "9500000 funded + 500000 released"
        )

    def test_release_pay_cascade_loan_aggregates(self, api):
        """PRD §3.6: "On the loan, `retained_cents` and `principal_disbursed_cents`
        are recomputed, `retainage_fully_released` is set true when the loan's
        withheld balance reaches zero after having once been positive, and the
        loan's `version` increments by one."

        Design: Difficulty/transitive_cascade/release_pay_cascade
        """
        sc, release = self._approved_release()
        validate_success(api.pay_retainage_release(release["id"], SERVICER), 200)

        loan = get_loan(sc["loan"]["id"])
        assert loan["retained_cents"] == 0
        assert loan["principal_disbursed_cents"] == 10_000_000
        assert loan["retainage_fully_released"] is True, (
            "Withheld balance reached zero after having been positive"
        )


class TestReleaseCashConservation:
    def test_retainage_release_conserves_line_cash(self, api):
        """PRD §3.6: "Payment moves money within the line: `retained_cents` falls
        by the amount and `disbursed_cents` grows by the same amount".

        Design: Difficulty/compensating_invariant/retainage_release_cash_conservation
        """
        sc = setup_funded_scenario()
        line_id = sc["lines"]["SITE"]["id"]
        before = get_budget_line(line_id)
        assert before["disbursed_cents"] + before["retained_cents"] == 10_000_000, (
            "Before pay: 9500000 disbursed + 500000 retained"
        )

        release = create_approved_release(sc, line_id, 500_000,
                                          reason="Milestone release")
        validate_success(api.pay_retainage_release(release["id"], SERVICER), 200)

        after = get_budget_line(line_id)
        assert after["disbursed_cents"] == 10_000_000
        assert after["retained_cents"] == 0
        assert after["disbursed_cents"] + after["retained_cents"] == 10_000_000, (
            "The release only transfers between the two buckets"
        )

    def test_retainage_release_conserves_loan_cash(self, api):
        """PRD §3.6: "Payment moves money within the line: `retained_cents` falls
        by the amount and `disbursed_cents` grows by the same amount".
        PRD §3.6: "On the loan, `retained_cents` and `principal_disbursed_cents`
        are recomputed".

        Design: Difficulty/compensating_invariant/retainage_release_cash_conservation
        """
        sc = setup_funded_scenario()
        loan_before = get_loan(sc["loan"]["id"])
        assert (loan_before["principal_disbursed_cents"]
                + loan_before["retained_cents"]) == 10_000_000

        release = create_approved_release(sc, sc["lines"]["SITE"]["id"], 500_000)
        validate_success(api.pay_retainage_release(release["id"], SERVICER), 200)

        loan_after = get_loan(sc["loan"]["id"])
        assert loan_after["principal_disbursed_cents"] == 10_000_000
        assert loan_after["retained_cents"] == 0
        assert (loan_after["principal_disbursed_cents"]
                + loan_after["retained_cents"]) == 10_000_000, (
            "Nothing is created or leaked by the transfer at loan level"
        )
