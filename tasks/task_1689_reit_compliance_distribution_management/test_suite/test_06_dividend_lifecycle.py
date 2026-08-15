"""Dividend declaration lifecycle: pinned waterfall order, declare-vs-void
branching, state legality, segregation of duties (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    approve_dividend,
    assert_dividend_declaration,
    create_approved_dividend,
    create_declared_dividend,
    create_dividend,
    create_dividend_declaration_payload,
    create_posted_ep_adjustment,
    create_posted_requirement,
    create_reit,
    current_reit_version,
    declare_dividend,
    get_reit,
    make_board_director_headers,
    make_compliance_officer_headers,
    setup_reit_with_ep_balance,
    setup_reit_with_open_quarter,
    validate_error,
    validate_success,
)


class TestPinnedEvaluationOrder:
    """Three-dividend chain over E&P 300000 and a 200000 capital-gain pool
    (PRD §3.6): 250000 -> (250000, 0, 0); 100000 -> (50000, 50000, 0);
    80000 -> (0, 80000, 0)."""

    def _setup_chain(self):
        reit, quarter = setup_reit_with_open_quarter()
        create_posted_ep_adjustment(reit["id"], quarter["id"],
                                    kind="TAXABLE_INCOME",
                                    amount_cents=300_000,
                                    effective_date="2026-01-15")
        req = create_posted_requirement(reit["id"], taxable_year=2026,
                                        taxable_income_cents=1_000_000,
                                        net_capital_gain_cents=200_000)
        return reit, req

    def _chain_through_d2(self):
        reit, req = self._setup_chain()
        d1 = create_declared_dividend(
            reit["id"], taxable_year=2026, amount_cents=250_000,
            declaration_date="2026-03-01", record_date="2026-03-10",
            payable_date="2026-03-20",
        )
        d2 = create_declared_dividend(
            reit["id"], taxable_year=2026, amount_cents=100_000,
            declaration_date="2026-03-02", record_date="2026-03-11",
            payable_date="2026-03-21",
        )
        return reit, req, d1, d2

    def test_first_two_dividends_follow_pinned_order(
            self, api, compliance_officer_headers):
        """PRD §3.6: "The first bucket is ordinary income: `ordinary_cents` is
        the lesser of the dividend's `amount_cents` and the REIT's
        `current_ep_balance_cents` clamped below at zero — a negative E&P
        balance clamps the ordinary bucket to 0."
        PRD §3.6: "The evaluation order is pinned — ordinary first, then
        capital gain, then return of capital — and the E&P balance is debited
        immediately by `ordinary_cents`."

        Design: Difficulty/combinatorial_formula/dividend_characterization_pinned_evaluation_order
        """
        reit, _req, d1, d2 = self._chain_through_d2()
        assert d1["ordinary_cents"] == 250_000
        assert d1["capital_gain_cents"] == 0
        assert d1["return_of_capital_cents"] == 0
        assert d2["ordinary_cents"] == 50_000, (
            "E&P debited to 50000 by D1 clamps D2's ordinary bucket"
        )
        assert d2["capital_gain_cents"] == 50_000
        assert d2["return_of_capital_cents"] == 0

    def test_third_dividend_exhausts_ep_and_draws_pool(
            self, api, compliance_officer_headers):
        """PRD §3.6: "The capital-gain pool is the `net_capital_gain_cents` of
        the `POSTED` requirement minus the sum of `capital_gain_cents` already
        characterized on sibling declarations for the same `(reit_id,
        taxable_year)` that are in `DECLARED` or `PAID` status."
        PRD §3.7: "The declare transition also re-runs this same replay after
        debiting `ordinary_cents`, so the E&P balance is always current after
        a dividend declaration."

        Design: Difficulty/combinatorial_formula/dividend_characterization_pinned_evaluation_order
        """
        reit, _req, _d1, _d2 = self._chain_through_d2()
        d3 = create_declared_dividend(
            reit["id"], taxable_year=2026, amount_cents=80_000,
            declaration_date="2026-03-03", record_date="2026-03-12",
            payable_date="2026-03-22",
        )
        assert d3["ordinary_cents"] == 0
        assert d3["capital_gain_cents"] == 80_000
        assert d3["return_of_capital_cents"] == 0
        assert get_reit(reit["id"])["current_ep_balance_cents"] == 0


class TestBranchingVoidVsDeclare:
    """Two APPROVED dividends of 100000 over E&P 500000 and a POSTED
    requirement (ti 1000000, ncg 0): the DECLARED branch moves the ledger,
    the VOID branch does not."""

    def _setup_two_approved(self):
        reit, quarter = setup_reit_with_open_quarter()
        create_posted_ep_adjustment(reit["id"], quarter["id"],
                                    kind="TAXABLE_INCOME",
                                    amount_cents=500_000,
                                    effective_date="2026-01-15")
        req = create_posted_requirement(reit["id"], taxable_year=2026,
                                        taxable_income_cents=1_000_000,
                                        net_capital_gain_cents=0)
        d1 = create_approved_dividend(
            reit["id"], taxable_year=2026, amount_cents=100_000,
            declaration_date="2026-03-01", record_date="2026-03-10",
            payable_date="2026-03-20",
        )
        d2 = create_approved_dividend(
            reit["id"], taxable_year=2026, amount_cents=100_000,
            declaration_date="2026-03-02", record_date="2026-03-11",
            payable_date="2026-03-21",
        )
        return reit, req, d1, d2

    def test_declare_branch_moves_ep_and_syncs_requirement(
            self, api, compliance_officer_headers):
        """PRD §3.6: "The requirement's `distributed_amount_cents` is
        recomputed as the sum of `amount_cents` over all declarations for the
        year in `DECLARED` or `PAID` status, and its `deficiency_cents` is
        recomputed as the greater of zero or the excess of
        `required_amount_cents` over that distributed total. The REIT's
        `dividend_distribution_deficit_cents` is set to the recomputed
        deficiency of the `POSTED` requirement."

        Design: Difficulty/non_linear_state_machine/dividend_branching_void_vs_declare_side_effects
        """
        reit, req, d1, _d2 = self._setup_two_approved()
        declared = declare_dividend(d1["id"], officer_id="officer-1")
        assert_dividend_declaration(declared)
        assert declared["status"] == "DECLARED"
        assert declared["ordinary_cents"] == 100_000
        assert declared["declared_by_officer_id"] == "officer-1"

        reit_after = get_reit(reit["id"])
        assert reit_after["current_ep_balance_cents"] == 400_000
        assert reit_after["dividend_distribution_deficit_cents"] == 800_000

        req_after = validate_success(
            api.get_distribution_requirement(req["id"],
                                             compliance_officer_headers),
            200,
        )
        assert req_after["distributed_amount_cents"] == 100_000
        assert req_after["deficiency_cents"] == 800_000

    def test_void_branch_has_no_fiscal_side_effects(
            self, api, compliance_officer_headers):
        """PRD §3.6: "Voiding is available while the declaration is in
        `PENDING_APPROVAL` or `APPROVED`; a void request against any other
        status — including a `PAID` declaration — is rejected with
        `ERR_INVALID_STATE`. A voided declaration transitions to `VOID` and
        its `version` increments by one."

        Design: Difficulty/non_linear_state_machine/dividend_branching_void_vs_declare_side_effects
        """
        reit, req, d1, d2 = self._setup_two_approved()
        declare_dividend(d1["id"], officer_id="officer-1")
        ep_before = get_reit(reit["id"])["current_ep_balance_cents"]

        voided = validate_success(
            api.void_dividend_declaration(d2["id"],
                                          compliance_officer_headers),
            200,
        )
        assert voided["status"] == "VOID"

        reit_after = get_reit(reit["id"])
        assert reit_after["current_ep_balance_cents"] == ep_before == 400_000
        req_after = validate_success(
            api.get_distribution_requirement(req["id"],
                                             compliance_officer_headers),
            200,
        )
        assert req_after["distributed_amount_cents"] == 100_000


def test_pay_pending_approval_dividend_returns_invalid_state(
        api, compliance_officer_headers):
    """PRD §3.6: "Payment is the quiet transition. A `ComplianceOfficer` pays
    a declaration that is in `DECLARED`".
    PRD §2.9: "then state-machine legality (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/pay_pending_approval_dividend_returns_invalid_state
    """
    reit = create_reit(legal_name="SM3 REIT")
    dividend = create_dividend(reit["id"], taxable_year=2026,
                               amount_cents=10_000)
    resp = api.pay_dividend_declaration(dividend["id"],
                                        compliance_officer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_paid_dividend_cannot_be_voided(api, compliance_officer_headers):
    """PRD §3.6: "a void request against any other status — including a
    `PAID` declaration — is rejected with `ERR_INVALID_STATE`."
    PRD §3.6: "no E&P change occurs because the allocation already happened
    at declare time, and the requirement's amounts are unchanged."

    Design: Corner/state_machines/paid_dividend_cannot_be_voided
    """
    reit, quarter = setup_reit_with_open_quarter()
    create_posted_ep_adjustment(reit["id"], quarter["id"],
                                kind="TAXABLE_INCOME", amount_cents=300_000,
                                effective_date="2026-01-10")
    create_posted_requirement(reit["id"], taxable_year=2026,
                              taxable_income_cents=500_000,
                              net_capital_gain_cents=0)
    dividend = create_declared_dividend(reit["id"], taxable_year=2026,
                                        amount_cents=100_000)
    paid = validate_success(
        api.pay_dividend_declaration(dividend["id"],
                                     compliance_officer_headers),
        200,
    )
    assert paid["status"] == "PAID"
    assert get_reit(reit["id"])["current_ep_balance_cents"] == 200_000

    resp = api.void_dividend_declaration(dividend["id"],
                                         compliance_officer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_reit(reit["id"])["current_ep_balance_cents"] == 200_000


def test_dividend_record_date_before_declaration_rejected(
        api, compliance_officer_headers):
    """PRD §3.6: "Two date rules apply: `record_date` must not precede
    `declaration_date`, and `payable_date` must not precede `record_date`; a
    violation yields `ERR_INVALID_DATE_RANGE`."

    Design: Corner/validations/dividend_record_date_before_declaration_rejected
    """
    reit = create_reit(legal_name="DT REIT")
    payload = create_dividend_declaration_payload(
        reit["id"], expected_reit_version=current_reit_version(reit["id"]),
        taxable_year=2026, amount_cents=1000, declaration_date="2026-03-10",
        record_date="2026-03-05", payable_date="2026-03-20",
    )
    resp = api.create_dividend_declaration(payload, compliance_officer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)


def test_segregation_of_duties_on_dividend_declare(api):
    """PRD §3.6: "with their own `X-User-ID` different from the declaration's
    `approved_by_director_id` — a same-identifier attempt is rejected with
    `ERR_SEGREGATION_OF_DUTIES`".

    Design: Corner/validations/segregation_of_duties_on_dividend_declare
    """
    reit = create_reit(legal_name="SOD REIT")
    create_posted_requirement(reit["id"], taxable_year=2026,
                              taxable_income_cents=100_000,
                              net_capital_gain_cents=0)
    dividend = create_dividend(reit["id"], taxable_year=2026,
                               amount_cents=10_000)
    approve_dividend(dividend["id"], director_id="dual-hat")
    resp = api.declare_dividend_declaration(
        dividend["id"], make_compliance_officer_headers("dual-hat")
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def test_negative_ep_clamps_ordinary_bucket_to_zero(
        api, compliance_officer_headers):
    """PRD §3.7: "The balance may go negative — that is a legitimate deficit
    E&P position, and it is what clamps the ordinary bucket of dividend
    characterization to zero."
    PRD §3.6: "Whatever remains after both buckets is
    `return_of_capital_cents`."

    Design: Corner/calculations/negative_ep_clamps_ordinary_bucket_to_zero
    """
    reit, quarter = setup_reit_with_open_quarter()
    create_posted_ep_adjustment(reit["id"], quarter["id"], kind="FEDERAL_TAX",
                                amount_cents=100_000,
                                effective_date="2026-01-31")
    create_posted_requirement(reit["id"], taxable_year=2026,
                              taxable_income_cents=0, net_capital_gain_cents=0)
    assert get_reit(reit["id"])["current_ep_balance_cents"] == -100_000

    dividend = create_approved_dividend(reit["id"], taxable_year=2026,
                                        amount_cents=50_000)
    declared = declare_dividend(dividend["id"], officer_id="officer-1")
    assert declared["ordinary_cents"] == 0
    assert declared["capital_gain_cents"] == 0
    assert declared["return_of_capital_cents"] == 50_000
