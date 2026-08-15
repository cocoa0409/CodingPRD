"""Form 1041 filings: tentative vs final DNI, pinned evaluation order,
65-day election, preparer/reviewer segregation, unposted-fee gate, and the
amendment cycle (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    make_ops_headers,
    make_tax_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    EXEC,
    TAX,
    create_active_trust,
    create_disbursed_request,
    create_fee,
    create_filing,
    create_posted_fee,
    post_receipt,
    setup_funded_trust,
)

Q3 = {"period_start": "2026-07-01", "period_end": "2026-09-30"}


def _dni_trust(api, name="DNI Trust"):
    """ACTIVE DISCRETIONARY trust funded 2,000,000.00 with INTEREST
    10,000.00 + ORDINARY_DIVIDEND 5,000.00 (both 2026) and a POSTED FINAL Q3
    fee (income portion 2,201.57: the FINAL base per PRD §3.6 is the as-of
    holdings value (none) plus the currently posted cash, 2,015,000.00 ->
    annual 17,612.50 -> quarterly 4,403.13 -> income portion
    round-half-up(2,201.565) = 2,201.57)."""
    ctx = setup_funded_trust(principal_cents=200000000, trust_name=name)
    trust = ctx["trust"]
    post_receipt(trust["id"], 1000000, receipt_type="INTEREST",
                 value_date="2026-09-15", description="interest")
    post_receipt(trust["id"], 500000, receipt_type="ORDINARY_DIVIDEND",
                 value_date="2026-09-20", description="dividend")
    create_posted_fee(trust["id"], variant="FINAL", **Q3)
    return trust


class TestTentativeVsFinalDni:
    def test_tentative_snapshots_entries_posted_so_far(self, api):
        """PRD §3.8: "The tentative variant reads the ledger as posted at
        tentative-computation time; the final variant recomputes at
        preparation time, so receipts posted between the two calls change the
        final figures relative to the tentative ones."
        PRD §3.8: "First, gross income is the sum of the positive INCOME rows
        in the year, counting RECEIPT rows only and excluding ADJUSTMENT
        reversals of fees. Second, income expenses are the absolute sum of the
        FEE rows in the INCOME bucket in the year. Third, distributable net
        income is gross income minus income expenses."

        Design: Difficulty/dual_variant_calc/tax_tentative_vs_final_dni
        """
        trust = _dni_trust(api)
        filing = create_filing(trust["id"], tax_year=2026)
        computed = validate_success(api.compute_tentative(filing["id"], TAX))
        # 1,000,000 + 500,000 gross income - 220,157 income fees
        assert computed["tentative_dni_cents"] == 1279843

    def test_final_dni_includes_late_posted_receipt(self, api):
        """PRD §3.8: "The tentative variant reads the ledger as posted at
        tentative-computation time; the final variant recomputes at
        preparation time, so receipts posted between the two calls change the
        final figures relative to the tentative ones."
        PRD §3.8: "A successful preparation computes `dni_cents`,
        `distribution_deduction_cents`, and `trust_taxable_income_cents` per
        the pinned sequence and records `prepared_by_user_id` from the
        caller."

        Design: Difficulty/dual_variant_calc/tax_tentative_vs_final_dni
        """
        trust = _dni_trust(api)
        filing = create_filing(trust["id"], tax_year=2026)
        computed = validate_success(api.compute_tentative(filing["id"], TAX))
        post_receipt(trust["id"], 500000, receipt_type="INTEREST",
                     value_date="2026-11-15", description="late interest")
        prepared = validate_success(
            api.prepare_filing(filing["id"], {"elected_65day_amount_cents": 0},
                               make_tax_headers("tax_prep"))
        )
        assert prepared["tentative_dni_cents"] == 1279843
        assert prepared["dni_cents"] == 1779843
        assert prepared["dni_cents"] - computed["tentative_dni_cents"] == 500000
        assert prepared["status"] == "PREPARED"
        assert prepared["prepared_by_user_id"] == "tax_prep"


class TestPinnedEvaluationOrder:
    def _trust_with_disbursement(self, api):
        """DNI trust inputs plus one APPROVED-then-DISBURSED 8,000.00
        INCOME_ONLY distribution (value_date inside 2026)."""
        ctx = setup_funded_trust(
            principal_cents=200000000,
            committee_size=5,
            all_beneficiaries=[{"full_name": "Inc Ivy", "beneficiary_class": "INCOME",
                                "share_bps": 10000, "date_of_birth": "1955-05-05"}],
            trust_name="Order Trust",
        )
        trust = ctx["trust"]
        ben = ctx["beneficiaries"][0]
        ids = [m["id"] for m in ctx["members"]]
        post_receipt(trust["id"], 1000000, receipt_type="INTEREST",
                     value_date="2026-09-15", description="interest")
        post_receipt(trust["id"], 500000, receipt_type="ORDINARY_DIVIDEND",
                     value_date="2026-09-20", description="dividend")
        create_posted_fee(trust["id"], variant="FINAL", **Q3)
        create_disbursed_request(trust["id"], ben["id"], ids, amount_cents=800000,
                                 purpose_category="HEALTH")
        return trust

    def test_dni_is_net_of_income_fees_before_deduction(self, api):
        """PRD §3.8: "First, gross income is the sum of the positive INCOME
        rows in the year, counting RECEIPT rows only and excluding ADJUSTMENT
        reversals of fees. Second, income expenses are the absolute sum of the
        FEE rows in the INCOME bucket in the year. Third, distributable net
        income is gross income minus income expenses. Fourth, amounts paid are
        the absolute sum of DISTRIBUTION rows in the year. Fifth, the
        distribution deduction is the lesser of distributable net income and
        the amounts paid plus any `elected_65day_amount_cents` — the amount of
        next-year distributions the fiduciary elects into the tax year under
        the 65-day rule, defaulting to zero. Sixth, the trust's taxable income
        is the distributable net income minus the distribution deduction minus
        the complex-trust exemption of 30,000 cents — three hundred dollars —
        carried on the filing as `exemption_cents`."

        Design: Difficulty/combinatorial_formula/dni_pinned_evaluation_order
        """
        trust = self._trust_with_disbursement(api)
        filing = create_filing(trust["id"], tax_year=2026)
        prepared = validate_success(
            api.prepare_filing(filing["id"], {"elected_65day_amount_cents": 0},
                               make_tax_headers("tax_prep"))
        )
        assert prepared["dni_cents"] == 1279843
        assert prepared["distribution_deduction_cents"] == 800000

    def test_exemption_applied_last_in_pinned_order(self, api):
        """PRD §3.8: "Sixth, the trust's taxable income is the distributable
        net income minus the distribution deduction minus the complex-trust
        exemption of 30,000 cents — three hundred dollars — carried on the
        filing as `exemption_cents`."

        Design: Difficulty/combinatorial_formula/dni_pinned_evaluation_order
        """
        trust = self._trust_with_disbursement(api)
        filing = create_filing(trust["id"], tax_year=2026)
        prepared = validate_success(
            api.prepare_filing(filing["id"], {"elected_65day_amount_cents": 0},
                               make_tax_headers("tax_prep"))
        )
        assert prepared["exemption_cents"] == 30000
        assert prepared["trust_taxable_income_cents"] == 449843


class TestElection65Day:
    def _election_trust(self, api):
        """15,000.00 INTEREST (2026); a 5,000.00 distribution disbursed at
        clock 2026-11-10 and a 1,000.00 distribution disbursed at clock
        2027-02-15."""
        ctx = setup_funded_trust(
            committee_size=3,
            all_beneficiaries=[{"full_name": "Ivy", "beneficiary_class": "INCOME",
                                "share_bps": 10000, "date_of_birth": "1955-01-01"}],
            trust_name="Election Trust", governing_state="NY",
        )
        trust = ctx["trust"]
        ben = ctx["beneficiaries"][0]
        ids = [m["id"] for m in ctx["members"]]
        post_receipt(trust["id"], 1500000, receipt_type="INTEREST",
                     value_date="2026-06-15", description="income")
        assert api.set_clock({"to_iso8601": "2026-11-10T00:00:00Z"}, EXEC).status_code == 200
        create_disbursed_request(trust["id"], ben["id"], ids, amount_cents=500000)
        assert api.set_clock({"to_iso8601": "2027-02-15T00:00:00Z"}, EXEC).status_code == 200
        create_disbursed_request(trust["id"], ben["id"], ids, amount_cents=100000)
        filing = create_filing(trust["id"], tax_year=2026)
        return filing

    def test_election_over_window_sum_rejected(self, api):
        """PRD §3.8: "And the elected amount must not exceed the distributions
        disbursed with a `value_date` between January 1 and March 6 of the
        following tax year, inclusive, otherwise
        `ERR_INVALID_ELECTION_AMOUNT`."

        Design: Corner/calculations/election_65day_amount_and_overflow
        """
        filing = self._election_trust(api)
        resp = api.prepare_filing(filing["id"], {"elected_65day_amount_cents": 100001},
                                  make_tax_headers("tax_a"))
        validate_error(resp, ApiErrorId.ERR_INVALID_ELECTION_AMOUNT)

    def test_elected_amount_raises_distribution_deduction(self, api):
        """PRD §3.8: "Fifth, the distribution deduction is the lesser of
        distributable net income and the amounts paid plus any
        `elected_65day_amount_cents` — the amount of next-year distributions
        the fiduciary elects into the tax year under the 65-day rule,
        defaulting to zero. Sixth, the trust's taxable income is the
        distributable net income minus the distribution deduction minus the
        complex-trust exemption of 30,000 cents — three hundred dollars —
        carried on the filing as `exemption_cents`."

        Design: Corner/calculations/election_65day_amount_and_overflow
        """
        filing = self._election_trust(api)
        api.prepare_filing(filing["id"], {"elected_65day_amount_cents": 100001},
                           make_tax_headers("tax_a"))  # rejected
        prepared = validate_success(
            api.prepare_filing(filing["id"], {"elected_65day_amount_cents": 100000},
                               make_tax_headers("tax_a"))
        )
        assert prepared["dni_cents"] == 1500000
        assert prepared["distribution_deduction_cents"] == 600000
        assert prepared["trust_taxable_income_cents"] == 870000


class TestTaxSegregationOfDuties:
    def _under_review_filing(self, api, preparer="tax_lead"):
        trust = create_active_trust(trust_name="SoD Tax", governing_state="NY")
        post_receipt(trust["id"], 1000000, receipt_type="INTEREST",
                     value_date="2026-09-01", description="income")
        filing = create_filing(trust["id"], tax_year=2026)
        assert api.prepare_filing(filing["id"], {"elected_65day_amount_cents": 0},
                                  make_tax_headers(preparer)).status_code == 200
        assert api.submit_for_review(filing["id"], make_tax_headers(preparer)).status_code == 200
        return filing

    def test_preparer_cannot_approve_own_filing(self, api):
        """PRD §3.8: "Review is segregation-controlled. The preparer submits
        the filing for review (PREPARED → UNDER_REVIEW), and a different
        `TaxSpecialist` approves it (UNDER_REVIEW → FILED): the reviewer's
        `X-User-ID` must differ from `prepared_by_user_id`, otherwise
        `ERR_SEGREGATION_OF_DUTIES`, and approval records
        `reviewed_by_user_id` and stamps `filed_at`."

        Design: Corner/validations/sod_tax_preparer_cannot_review
        """
        filing = self._under_review_filing(api)
        resp = api.approve_review(filing["id"], make_tax_headers("tax_lead"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_peer_reviewer_files_and_is_recorded(self, api):
        """PRD §3.8: "the reviewer's `X-User-ID` must differ from
        `prepared_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`, and
        approval records `reviewed_by_user_id` and stamps `filed_at`."

        Design: Corner/validations/sod_tax_preparer_cannot_review
        """
        filing = self._under_review_filing(api)
        api.approve_review(filing["id"], make_tax_headers("tax_lead"))  # rejected
        filed = validate_success(
            api.approve_review(filing["id"], make_tax_headers("tax_peer"))
        )
        assert filed["status"] == "FILED"
        assert filed["reviewed_by_user_id"] == "tax_peer"


class TestPrepareUnpostedFeeGate:
    def _trust_with_calculated_fee(self, api):
        ctx = setup_funded_trust(principal_cents=200000000, trust_name="Gate Trust",
                                 governing_state="NY")
        trust = ctx["trust"]
        post_receipt(trust["id"], 1000000, receipt_type="INTEREST",
                     value_date="2026-09-10", description="interest")
        fee = create_fee(trust["id"], variant="FINAL", **Q3)
        filing = create_filing(trust["id"], tax_year=2026)
        return trust, fee, filing

    def test_prepare_blocked_by_unposted_fee(self, api):
        """PRD §3.8: "Every FeeAssessment of the trust with variant FINAL, a
        status other than REVERSED, and a period overlapping the tax year must
        be POSTED, otherwise `ERR_UNPOSTED_FEE_ASSESSMENTS`."

        Design: Difficulty/cross_entity_state_dependency/prepare_blocked_by_unposted_fee
        """
        _, _, filing = self._trust_with_calculated_fee(api)
        resp = api.prepare_filing(filing["id"], {"elected_65day_amount_cents": 0},
                                  make_tax_headers("tax_a"))
        validate_error(resp, ApiErrorId.ERR_UNPOSTED_FEE_ASSESSMENTS)

    def test_prepare_succeeds_after_fee_posted(self, api):
        """PRD §3.8: "Every FeeAssessment of the trust with variant FINAL, a
        status other than REVERSED, and a period overlapping the tax year must
        be POSTED, otherwise `ERR_UNPOSTED_FEE_ASSESSMENTS`."
        PRD §3.8: "Sixth, the trust's taxable income is the distributable net
        income minus the distribution deduction minus the complex-trust
        exemption of 30,000 cents — three hundred dollars — carried on the
        filing as `exemption_cents`."

        Design: Difficulty/cross_entity_state_dependency/prepare_blocked_by_unposted_fee
        """
        trust, fee, filing = self._trust_with_calculated_fee(api)
        api.prepare_filing(filing["id"], {"elected_65day_amount_cents": 0},
                           make_tax_headers("tax_a"))  # rejected
        assert api.disclose_fee(fee["id"], make_ops_headers("ops_disc")).status_code == 200
        posted = validate_success(api.post_fee(fee["id"], make_ops_headers("ops_post")))
        assert posted["status"] == "POSTED"

        prepared = validate_success(
            api.prepare_filing(filing["id"], {"elected_65day_amount_cents": 0},
                               make_tax_headers("tax_a"))
        )
        # FINAL fee base = posted cash 201,000,000 (PRD §3.6) -> quarterly
        # 439,375 -> income portion 219,688; DNI = 1,000,000 - 219,688.
        assert prepared["dni_cents"] == 780312
        assert prepared["trust_taxable_income_cents"] == 750312


class TestAmendmentCycle:
    def _filed_filing(self, api):
        trust = create_active_trust(trust_name="Amend Trust", governing_state="NY")
        post_receipt(trust["id"], 1000000, receipt_type="INTEREST",
                     value_date="2026-09-01", description="interest")
        filing = create_filing(trust["id"], tax_year=2026)
        assert api.prepare_filing(filing["id"], {"elected_65day_amount_cents": 0},
                                  make_tax_headers("tax_a")).status_code == 200
        assert api.submit_for_review(filing["id"], make_tax_headers("tax_a")).status_code == 200
        filed = validate_success(
            api.approve_review(filing["id"], make_tax_headers("tax_b"))
        )
        return filing, filed

    def test_filed_then_amendment_returns_to_data_collection(self, api):
        """PRD §3.8: "If the authority instead demands changes, the filing
        moves FILED → AMENDMENT_REQUIRED with a recorded `reason`, and
        beginning the amendment returns it to DATA_COLLECTION, increments
        `amendment_number` by one, and clears both `prepared_by_user_id` and
        `reviewed_by_user_id` so the segregation pairing starts fresh. The
        FILED → AMENDMENT_REQUIRED → DATA_COLLECTION loop is unbounded."

        Design: Difficulty/non_linear_state_machine/tax_filing_amendment_cycle
        """
        filing, filed = self._filed_filing(api)
        assert filed["status"] == "FILED"
        assert filed["prepared_by_user_id"] == "tax_a"
        assert filed["reviewed_by_user_id"] == "tax_b"

        assert api.require_amendment(filing["id"], {"reason": "IRS notice"},
                                     make_tax_headers("tax_b")).status_code == 200
        restarted = validate_success(
            api.begin_amendment(filing["id"], make_tax_headers("tax_a"))
        )
        assert restarted["status"] == "DATA_COLLECTION"
        assert restarted["amendment_number"] == 1

    def test_second_pass_files_again_with_same_dni(self, api):
        """PRD §3.8: "The FILED → AMENDMENT_REQUIRED → DATA_COLLECTION loop
        is unbounded."
        PRD §3.8: "Third, distributable net income is gross income minus
        income expenses."

        Design: Difficulty/non_linear_state_machine/tax_filing_amendment_cycle
        """
        filing, _ = self._filed_filing(api)
        assert api.require_amendment(filing["id"], {"reason": "IRS notice"},
                                     make_tax_headers("tax_b")).status_code == 200
        assert api.begin_amendment(filing["id"], make_tax_headers("tax_a")).status_code == 200
        assert api.prepare_filing(filing["id"], {"elected_65day_amount_cents": 0},
                                  make_tax_headers("tax_a")).status_code == 200
        assert api.submit_for_review(filing["id"], make_tax_headers("tax_a")).status_code == 200
        refiled = validate_success(
            api.approve_review(filing["id"], make_tax_headers("tax_b"))
        )
        assert refiled["status"] == "FILED"
        assert refiled["dni_cents"] == 1000000
