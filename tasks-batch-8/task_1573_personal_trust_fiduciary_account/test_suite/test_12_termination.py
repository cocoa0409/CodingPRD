"""Trust termination gauntlet: final distribution waterfall rounding,
initiator/approver segregation, tax-clearance and close gates (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    make_executive_headers,
    make_officer_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    EXEC,
    OFFICER,
    OPS,
    TAX,
    add_beneficiary,
    advance_case_to_final_accounting_approved,
    create_active_trust,
    create_approved_document,
    create_filing,
    create_trust,
    get_trust,
    post_receipt,
    terminate_trust,
)


class TestFinalDistributionWaterfall:
    def _waterfall_case(self, api):
        """ACTIVE testamentary trust; per_stirpes=false document approved;
        INCOME Irene 10000 bps; REMAINDER A/B/C 3333/3333/3334 bps in that
        creation order; principal 500,000.00 + income 20,000.00; case walked
        to FINAL_ACCOUNTING_APPROVED with reserves 15,000.00 + 4,374.00."""
        trust = create_trust(trust_name="Waterfall Trust", trust_type="TESTAMENTARY",
                             governing_state="TX")
        create_approved_document(trust["id"], per_stirpes=False)
        b_inc = add_beneficiary(trust["id"], full_name="Income Irene",
                                beneficiary_class="INCOME", share_bps=10000,
                                date_of_birth="1950-01-01")
        b_a = add_beneficiary(trust["id"], full_name="Rem A",
                              beneficiary_class="REMAINDER", share_bps=3333,
                              date_of_birth="1980-01-01")
        b_b = add_beneficiary(trust["id"], full_name="Rem B",
                              beneficiary_class="REMAINDER", share_bps=3333,
                              date_of_birth="1981-01-01")
        b_c = add_beneficiary(trust["id"], full_name="Rem C",
                              beneficiary_class="REMAINDER", share_bps=3334,
                              date_of_birth="1982-01-01")
        assert api.submit_for_acceptance(trust["id"], OFFICER).status_code == 200
        assert api.accept_trust(trust["id"], EXEC).status_code == 200
        post_receipt(trust["id"], 50000000, receipt_type="INITIAL_FUNDING",
                     value_date="2026-08-05", description="principal funding")
        post_receipt(trust["id"], 2000000, receipt_type="INTEREST",
                     value_date="2026-09-15", description="income")
        case = advance_case_to_final_accounting_approved(
            trust["id"],
            reserve_taxes_cents=1500000,
            reserve_fees_cents=437400,
            initiator_headers=make_officer_headers("officer_init"),
            approver_headers=make_executive_headers("exec_appr"),
        )
        return trust, case, (b_inc, b_a, b_b, b_c)

    def test_distributable_pools_and_per_line_rounding(self, api):
        """PRD §3.9: "The distributable income is the trust's
        `income_balance_cents` at distribute time, paid to the INCOME class;
        the distributable principal is `principal_balance_cents` minus
        `reserve_taxes_cents` minus `reserve_fees_cents`, paid to the
        REMAINDER class, with the reserves deliberately remaining as principal
        balance." and "Each line's amount is the class pool multiplied by the
        beneficiary's `share_bps` and divided by 10000, rounded half up to
        whole cents — the per-line rounding happens first."

        Design: Difficulty/combinatorial_formula/waterfall_per_line_rounding_remainder
        """
        trust, case, (b_inc, b_a, b_b, b_c) = self._waterfall_case(api)
        distributed = validate_success(api.distribute_case(case["id"], OPS))
        assert distributed["status"] == "DISTRIBUTED"
        assert distributed["distributable_income_cents"] == 2000000
        assert distributed["distributable_principal_cents"] == 48062600

        lines = {l["beneficiary_id"]: l["amount_cents"]
                 for l in distributed["distribution_lines"]}
        assert lines[b_inc["id"]] == 2000000
        assert lines[b_a["id"]] == 16019265
        assert lines[b_b["id"]] == 16019265

    def test_delta_applied_to_largest_share_and_trust_terminates(self, api):
        """PRD §3.9: "The delta between the pool and the sum of the rounded
        lines, which may be negative, is then applied to the line of the
        beneficiary with the largest `share_bps` in that class, ties broken by
        beneficiary `created_at` ascending, never by id." and "The waterfall
        records `distributable_income_cents` and `distributable_principal_cents`
        on the case, appends one DISTRIBUTION ledger row per line —
        income-class lines to the INCOME bucket, remainder-class lines to the
        PRINCIPAL bucket — recomputes the trust's balances, transitions the
        trust TERMINATING → TERMINATED with a version increment, and stamps
        `distributed_at`."

        Design: Difficulty/combinatorial_formula/waterfall_per_line_rounding_remainder
        """
        trust, case, (b_inc, b_a, b_b, b_c) = self._waterfall_case(api)
        distributed = validate_success(api.distribute_case(case["id"], OPS))
        lines = {l["beneficiary_id"]: l["amount_cents"]
                 for l in distributed["distribution_lines"]}
        # per-line rounding gives 16019265+16019265+16024071 = 48062601;
        # delta -1 lands on the largest-share line (C, 3334 bps)
        assert lines[b_c["id"]] == 16024070
        remainder_total = lines[b_a["id"]] + lines[b_b["id"]] + lines[b_c["id"]]
        assert remainder_total == 48062600

        trust_after = get_trust(trust["id"])
        assert trust_after["status"] == "TERMINATED"


class TestTerminationSegregationOfDuties:
    def _case_at_clearance(self, api):
        trust = create_active_trust(trust_name="SoD Term", governing_state="TX")
        post_receipt(trust["id"], 1000000, receipt_type="INITIAL_FUNDING",
                     value_date="2026-08-05", description="funding")
        case = terminate_trust(trust["id"], reason="settlor directed",
                               initiator_headers=make_executive_headers("exec_founder"))
        assert api.reserve_liabilities(
            case["id"], {"reserve_taxes_cents": 100000, "reserve_fees_cents": 100000},
            OFFICER,
        ).status_code == 200
        assert api.record_tax_clearance(case["id"], TAX).status_code == 200
        return case

    def test_initiator_cannot_approve_final_accounting(self, api):
        """PRD §3.9: "A `TrustExecutive` approves the final accounting, moving
        TAX_CLEARANCE_RECEIVED → FINAL_ACCOUNTING_APPROVED, and this is the
        third segregation pairing: the approver's `X-User-ID` must differ from
        `initiated_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`;
        approval records `approved_by_user_id`."

        Design: Corner/validations/sod_termination_initiator_cannot_approve_accounting
        """
        case = self._case_at_clearance(api)
        resp = api.approve_final_accounting(
            case["id"], make_executive_headers("exec_founder")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_another_executive_approves(self, api):
        """PRD §3.9: "A `TrustExecutive` approves the final accounting, moving
        TAX_CLEARANCE_RECEIVED → FINAL_ACCOUNTING_APPROVED, and this is the
        third segregation pairing: the approver's `X-User-ID` must differ from
        `initiated_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`;
        approval records `approved_by_user_id`."

        Design: Corner/validations/sod_termination_initiator_cannot_approve_accounting
        """
        case = self._case_at_clearance(api)
        api.approve_final_accounting(case["id"], make_executive_headers("exec_founder"))
        approved = validate_success(
            api.approve_final_accounting(case["id"], make_executive_headers("exec_second"))
        )
        assert approved["status"] == "FINAL_ACCOUNTING_APPROVED"


class TestTaxClearanceGate:
    def test_unfiled_returns_block_tax_clearance(self, api):
        """PRD §3.9: "A `TaxSpecialist` records tax clearance, moving
        LIABILITIES_RESERVED → TAX_CLEARANCE_RECEIVED, which requires every
        TaxReturnFiling of the trust to be ACCEPTED — any filing short of
        acceptance yields `ERR_UNFILED_TAX_RETURNS`."

        Design: Corner/errors/unfiled_returns_block_tax_clearance
        """
        trust = create_active_trust(trust_name="Clearance Block", governing_state="TX")
        post_receipt(trust["id"], 1000000, receipt_type="INITIAL_FUNDING",
                     value_date="2026-08-05", description="funding")
        create_filing(trust["id"], tax_year=2026)  # stays DATA_COLLECTION
        case = terminate_trust(trust["id"], reason="directed")
        assert api.reserve_liabilities(
            case["id"], {"reserve_taxes_cents": 100000, "reserve_fees_cents": 100000},
            OFFICER,
        ).status_code == 200
        resp = api.record_tax_clearance(case["id"], TAX)
        validate_error(resp, ApiErrorId.ERR_UNFILED_TAX_RETURNS)

    def test_blocked_clearance_leaves_case_liabilities_reserved(self, api):
        """PRD §3.9: "A `TaxSpecialist` records tax clearance, moving
        LIABILITIES_RESERVED → TAX_CLEARANCE_RECEIVED, which requires every
        TaxReturnFiling of the trust to be ACCEPTED — any filing short of
        acceptance yields `ERR_UNFILED_TAX_RETURNS`."

        Design: Corner/errors/unfiled_returns_block_tax_clearance
        """
        trust = create_active_trust(trust_name="Clearance State", governing_state="TX")
        post_receipt(trust["id"], 1000000, receipt_type="INITIAL_FUNDING",
                     value_date="2026-08-05", description="funding")
        create_filing(trust["id"], tax_year=2026)
        case = terminate_trust(trust["id"], reason="directed")
        assert api.reserve_liabilities(
            case["id"], {"reserve_taxes_cents": 100000, "reserve_fees_cents": 100000},
            OFFICER,
        ).status_code == 200
        api.record_tax_clearance(case["id"], TAX)
        current = validate_success(api.get_termination_case(case["id"], OFFICER))
        assert current["status"] == "LIABILITIES_RESERVED"


class TestCloseGate:
    def _distributed_case(self, api):
        """Case DISTRIBUTED: sole INCOME beneficiary; principal 10,000.00 +
        income 2,000.00; reserves 1,000.00 + 1,000.00; no statements or
        filings."""
        ctx_trust = create_trust(trust_name="Close Gate", governing_state="TX")
        create_approved_document(ctx_trust["id"])
        add_beneficiary(ctx_trust["id"], full_name="Ivy",
                        beneficiary_class="INCOME", share_bps=10000,
                        date_of_birth="1955-01-01")
        assert api.submit_for_acceptance(ctx_trust["id"], OFFICER).status_code == 200
        assert api.accept_trust(ctx_trust["id"], EXEC).status_code == 200
        post_receipt(ctx_trust["id"], 1000000, receipt_type="INITIAL_FUNDING",
                     value_date="2026-08-05", description="principal")
        post_receipt(ctx_trust["id"], 200000, receipt_type="INTEREST",
                     value_date="2026-08-06", description="income")
        case = advance_case_to_final_accounting_approved(
            ctx_trust["id"],
            reserve_taxes_cents=100000,
            reserve_fees_cents=100000,
            initiator_headers=make_officer_headers("officer_init"),
            approver_headers=make_executive_headers("exec_other"),
        )
        distributed = validate_success(api.distribute_case(case["id"], OPS))
        assert distributed["status"] == "DISTRIBUTED"
        return ctx_trust, case

    def test_distribute_terminates_trust(self, api):
        """PRD §3.9: "The waterfall records `distributable_income_cents` and
        `distributable_principal_cents` on the case, appends one DISTRIBUTION
        ledger row per line — income-class lines to the INCOME bucket,
        remainder-class lines to the PRINCIPAL bucket — recomputes the trust's
        balances, transitions the trust TERMINATING → TERMINATED with a
        version increment, and stamps `distributed_at`."

        Design: Corner/errors/close_blocked_until_final_statement_acknowledged
        """
        trust, _ = self._distributed_case(api)
        assert get_trust(trust["id"])["status"] == "TERMINATED"

    def test_close_blocked_until_final_statement_acknowledged(self, api):
        """PRD §3.9: "A `TrustOfficer` moves DISTRIBUTED → CLOSED only when
        two conditions hold: the AnnualStatement of the trust for the
        `fiscal_year` containing `distributed_at` is ACKNOWLEDGED, otherwise
        `ERR_FINAL_STATEMENT_NOT_ACKNOWLEDGED`; and the TaxReturnFiling of the
        trust for the `tax_year` containing `distributed_at` is ACCEPTED,
        otherwise `ERR_UNFILED_TAX_RETURNS`."

        Design: Corner/errors/close_blocked_until_final_statement_acknowledged
        """
        trust, case = self._distributed_case(api)
        resp = api.close_case(case["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_FINAL_STATEMENT_NOT_ACKNOWLEDGED)
        current = validate_success(api.get_termination_case(case["id"], OFFICER))
        assert current["status"] == "DISTRIBUTED"
