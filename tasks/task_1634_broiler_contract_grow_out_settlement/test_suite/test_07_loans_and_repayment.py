"""Grower loans, OCC on issuance, and the repayment waterfall (PRD §2.7, §3.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_grower_loan,
    create_grower_payload,
    create_loan_payload,
    get_success_data,
    list_loans_for_grower,
    setup_two_loan_grower,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]


class TestLoanTerms:
    def test_recovery_pct_above_50_rejected(self, api, admin_headers):
        """PRD §3.9: "An `IntegratorAdmin` issues a `GrowerLoan` to a grower
        with a `principal_cents` (must be positive), a `recovery_pct` — the
        percentage of each settlement's positive subtotal diverted to
        repayment, which must lie between 1 and 50 inclusive — and a `purpose`
        of `CAPITAL_UPGRADE` or `OPERATING`. A loan whose terms break these
        bounds is rejected with `ERR_LOAN_TERMS_INVALID` (HTTP 422)."

        Design: Corner/validations/loan_terms_out_of_range_rejected
        """
        grower = get_success_data(
            api.create_grower(create_grower_payload(grower_code="G-V4",
                                                    full_name="Valid Four"),
                              admin_headers))

        resp = api.issue_loan(
            grower["id"],
            create_loan_payload(grower["version"], principal_cents=10000,
                                recovery_pct=51, purpose="OPERATING"),
            admin_headers)
        validate_error(resp, ApiErrorId.ERR_LOAN_TERMS_INVALID)


class TestOccStaleGrowerVersionOnLoanIssue:
    def test_stale_grower_version_rejected(self, api, admin_headers):
        """PRD §2.7: "If the grower's current `version` has advanced in the
        meantime (for example because a settlement approval cascade just
        reduced `loan_outstanding_cents`), the loan issuance is rejected with
        `ERR_STALE_GROWER_VERSION` (HTTP 412) and the client must re-read and
        retry."
        PRD §3.9: "A new loan starts in `ISSUED` status with `outstanding_cents`
        equal to its `principal_cents`; its creation recomputes the grower's
        `loan_outstanding_cents` — the sum of `outstanding_cents` over the
        grower's loans in `ISSUED` status — and increments the grower's
        `version`."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_grower_version_on_loan_issue
        """
        grower = get_success_data(
            api.create_grower(create_grower_payload(grower_code="G-OCC2",
                                                    full_name="Occ Two"),
                              admin_headers))
        observed_version = grower["version"]
        first = validate_success(
            api.issue_loan(grower["id"],
                           create_loan_payload(observed_version,
                                               principal_cents=10000,
                                               recovery_pct=10),
                           admin_headers),
            expected_status=201)
        assert_grower_loan(first)

        resp = api.issue_loan(grower["id"],
                              create_loan_payload(observed_version,
                                                  principal_cents=20000,
                                                  recovery_pct=10),
                              admin_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_GROWER_VERSION)

    def test_rejected_loan_has_no_effect_on_outstanding(self, api,
                                                        admin_headers):
        """PRD §2.7: "If the grower's current `version` has advanced in the
        meantime (for example because a settlement approval cascade just
        reduced `loan_outstanding_cents`), the loan issuance is rejected with
        `ERR_STALE_GROWER_VERSION` (HTTP 412) and the client must re-read and
        retry."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_grower_version_on_loan_issue
        """
        grower = get_success_data(
            api.create_grower(create_grower_payload(grower_code="G-OCC2",
                                                    full_name="Occ Two"),
                              admin_headers))
        observed_version = grower["version"]
        get_success_data(
            api.issue_loan(grower["id"],
                           create_loan_payload(observed_version,
                                               principal_cents=10000,
                                               recovery_pct=10),
                           admin_headers))
        validate_error(
            api.issue_loan(grower["id"],
                           create_loan_payload(observed_version,
                                               principal_cents=20000,
                                               recovery_pct=10),
                           admin_headers),
            ApiErrorId.ERR_STALE_GROWER_VERSION)

        after = validate_success(api.get_grower(grower["id"], admin_headers))
        assert after["loan_outstanding_cents"] == 10000, \
            "the rejected write must leave loan_outstanding_cents unchanged"


class TestSettlementApproveLoanWaterfall:
    """Grower holds ISSUED loans 30000 (oldest) + 90000; the locked FINAL
    settlement diverts 46875 to repayment (single-member group: base 300000,
    bonus 12500, subtotal 312500, min(round(312500*0.15), 120000) = 46875)."""

    def test_approve_applies_repayment_oldest_first(self, api, analyst_headers):
        """PRD §3.9: "When a settlement is approved, its `loan_repayment_cents`
        is applied to the grower's loans oldest-first: the `ISSUED` loan with
        the earliest `created_at` absorbs the repayment first, and when its
        `outstanding_cents` reaches zero its status becomes `REPAID` and any
        remainder flows to the next-oldest `ISSUED` loan."

        Design: Difficulty/transitive_cascade/settlement_approve_loan_waterfall_cascade_depth2
        """
        ctx = setup_two_loan_grower()
        settlement = ctx["settlement"]
        assert settlement["loan_repayment_cents"] == 46875

        get_success_data(api.approve_settlement(settlement["id"], analyst_headers))

        loans = list_loans_for_grower(ctx["grower"]["id"])
        assert len(loans) == 2
        # Creation-ascending order: loans[0] is the oldest (30000).
        assert loans[0]["id"] == ctx["loan1"]["id"]
        assert loans[0]["outstanding_cents"] == 0, \
            "the oldest loan absorbs the first 30000 of the 46875 repayment"
        assert loans[0]["status"] == "REPAID"
        assert loans[1]["id"] == ctx["loan2"]["id"]
        assert loans[1]["outstanding_cents"] == 73125, \
            "the remaining 16875 flows to the second loan (90000 - 16875)"
        assert loans[1]["status"] == "ISSUED"

    def test_approve_recomputes_grower_outstanding_and_settles_flock(
            self, api, analyst_headers):
        """PRD §3.9: "The grower's `loan_outstanding_cents` is then
        recomputed."
        PRD §3.10: "Approving a settlement moves it `PENDING` → `APPROVED` and
        fires the domain's largest cascade: the flock transitions `HARVESTED` →
        `SETTLED` and its `performance_score` is computed".

        Design: Difficulty/transitive_cascade/settlement_approve_loan_waterfall_cascade_depth2
        """
        ctx = setup_two_loan_grower()

        approved = validate_success(
            api.approve_settlement(ctx["settlement"]["id"], analyst_headers))
        assert approved["status"] == "APPROVED"
        assert approved["loan_repayment_cents"] == 46875

        grower = validate_success(api.get_grower(ctx["grower"]["id"], ADMIN))
        assert grower["loan_outstanding_cents"] == 73125

        flock = validate_success(api.get_flock(ctx["flock"]["id"], ADMIN))
        assert flock["status"] == "SETTLED"


class TestLoanWaterfallConservesTotalOutstanding:
    def test_total_outstanding_decreases_by_exactly_repayment(
            self, api, analyst_headers):
        """PRD §3.9: "its creation recomputes the grower's
        `loan_outstanding_cents` — the sum of `outstanding_cents` over the
        grower's loans in `ISSUED` status".
        PRD §3.9: "When a settlement is approved, its `loan_repayment_cents` is
        applied to the grower's loans oldest-first: the `ISSUED` loan with the
        earliest `created_at` absorbs the repayment first, and when its
        `outstanding_cents` reaches zero its status becomes `REPAID` and any
        remainder flows to the next-oldest `ISSUED` loan. The grower's
        `loan_outstanding_cents` is then recomputed."

        Design: Difficulty/compensating_invariant/loan_waterfall_conserves_total_outstanding
        """
        ctx = setup_two_loan_grower()
        before = validate_success(api.get_grower(ctx["grower"]["id"], ADMIN))
        assert before["loan_outstanding_cents"] == 120000
        repayment = ctx["settlement"]["loan_repayment_cents"]
        assert repayment == 46875

        get_success_data(api.approve_settlement(ctx["settlement"]["id"],
                                                analyst_headers))

        after = validate_success(api.get_grower(ctx["grower"]["id"], ADMIN))
        assert after["loan_outstanding_cents"] == 120000 - repayment == 73125, \
            ("conserved: total outstanding decreases by exactly the "
             "settlement's loan_repayment_cents")

    def test_denormalized_mirror_matches_sum_over_loans(self, api,
                                                        analyst_headers):
        """PRD §3.9: "its creation recomputes the grower's
        `loan_outstanding_cents` — the sum of `outstanding_cents` over the
        grower's loans in `ISSUED` status".
        PRD §3.9: "When a settlement is approved, its `loan_repayment_cents` is
        applied to the grower's loans oldest-first".

        Design: Difficulty/compensating_invariant/loan_waterfall_conserves_total_outstanding
        """
        ctx = setup_two_loan_grower()
        get_success_data(api.approve_settlement(ctx["settlement"]["id"],
                                                analyst_headers))

        loans = list_loans_for_grower(ctx["grower"]["id"])
        per_loan_sum = sum(loan["outstanding_cents"] for loan in loans)
        grower = validate_success(api.get_grower(ctx["grower"]["id"], ADMIN))
        assert per_loan_sum == 73125
        assert grower["loan_outstanding_cents"] == per_loan_sum, \
            "the denormalized mirror must agree exactly with the loan rows"
