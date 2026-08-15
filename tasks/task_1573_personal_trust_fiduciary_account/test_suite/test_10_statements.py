"""Annual statements: fiscal-year window filtering, the
DELIVERED -> DISPUTED -> DRAFT regeneration cycle, and per-year uniqueness
(PRD §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_beneficiary_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    EXEC,
    OFFICER,
    TAX,
    create_active_trust,
    create_filing,
    get_trust,
    post_receipt,
    setup_funded_trust,
)


class TestStatementWindowFiltering:
    def test_out_of_window_receipts_partitioned(self, api):
        """PRD §3.7: "`opening_income_cents` and `opening_principal_cents`
        are the sums of signed ledger amounts, per bucket, whose `value_date`
        falls before the window opens. `receipts_income_cents` and
        `receipts_principal_cents` are the sums of the positive entries, per
        bucket, inside the window." and "`closing_income_cents` and
        `closing_principal_cents` are each the opening figure plus all signed
        entries of that bucket inside the window."

        Design: Corner/calculations/statement_totals_year_window_filtering
        """
        trust = create_active_trust(trust_name="Window Stmt")
        post_receipt(trust["id"], 700000, value_date="2025-12-15", description="prior year")
        post_receipt(trust["id"], 300000, value_date="2026-06-15", description="in year")
        post_receipt(trust["id"], 900000, value_date="2027-01-05", description="next year")

        resp = api.create_annual_statement(
            {"trust_id": trust["id"], "fiscal_year": 2026}, OFFICER
        )
        stmt = validate_success(resp, expected_status=201)
        assert stmt["opening_income_cents"] == 700000
        assert stmt["receipts_income_cents"] == 300000
        assert stmt["closing_income_cents"] == 1000000

    def test_live_balance_includes_all_years(self, api):
        """PRD §2.6: "`income_balance_cents` is the sum of `amount_cents` over
        all of the trust's ledger rows in the INCOME bucket, and
        `principal_balance_cents` is the same sum over the PRINCIPAL bucket."
        PRD §3.7: "The statement window runs from January 1 through December
        31 of the `fiscal_year`, inclusive."

        Design: Corner/calculations/statement_totals_year_window_filtering
        """
        trust = create_active_trust(trust_name="Window Live")
        post_receipt(trust["id"], 700000, value_date="2025-12-15", description="prior year")
        post_receipt(trust["id"], 300000, value_date="2026-06-15", description="in year")
        post_receipt(trust["id"], 900000, value_date="2027-01-05", description="next year")
        after = get_trust(trust["id"])
        assert after["income_balance_cents"] == 1900000


class TestStatementDisputeRegenerate:
    def _delivered_statement(self, api):
        ctx = setup_funded_trust(
            all_beneficiaries=[{"full_name": "Ivy", "beneficiary_class": "INCOME"}],
            trust_name="Cycle Stmt",
        )
        trust = ctx["trust"]
        ben = ctx["beneficiaries"][0]
        assert api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, EXEC).status_code == 200
        post_receipt(trust["id"], 1000000, value_date="2026-08-06", description="interest 1")
        resp = api.create_annual_statement(
            {"trust_id": trust["id"], "fiscal_year": 2026}, OFFICER
        )
        stmt = get_success_data(resp)
        assert api.finalize_statement(stmt["id"], OFFICER).status_code == 200
        assert api.deliver_statement(stmt["id"], OFFICER).status_code == 200
        return trust, ben, stmt

    def test_dispute_within_window_and_disputed_not_superseded(self, api):
        """PRD §2.6: "The staleness rule is global: whenever any workflow
        appends a LedgerEntry, every AnnualStatement of the same trust in
        DRAFT or FINALIZED whose `fiscal_year` window contains the new entry's
        `value_date` automatically transitions to SUPERSEDED. Statements
        already DELIVERED, ACKNOWLEDGED, or DISPUTED are not touched by this
        rule."
        PRD §3.7: "A beneficiary of the trust — again `X-User-ID` must be an
        ACTIVE Beneficiary of the same trust, otherwise
        `ERR_NOT_OWN_RESOURCE` — either acknowledges the statement, DELIVERED
        → ACKNOWLEDGED with `acknowledged_at` stamped, or disputes it within
        the window, DELIVERED → DISPUTED with a `dispute_reason`."

        Design: Corner/state_machines/statement_dispute_regenerate_cycle
        """
        trust, ben, stmt = self._delivered_statement(api)
        disputed = validate_success(
            api.dispute_statement(stmt["id"], {"dispute_reason": "missing receipt"},
                                  make_beneficiary_headers(ben["id"]))
        )
        assert disputed["status"] == "DISPUTED"

        # A later in-year ledger append must NOT supersede the DISPUTED stmt.
        post_receipt(trust["id"], 500000, value_date="2026-09-10", description="interest 2")
        current = validate_success(api.get_annual_statement(stmt["id"], OFFICER))
        assert current["status"] == "DISPUTED"

    def test_regenerate_recomputes_totals_from_current_ledger(self, api):
        """PRD §3.7: "A dispute triggers regeneration: DISPUTED → DRAFT,
        recomputing all totals from the current ledger and clearing
        `delivered_at` and `dispute_reason`; the DELIVERED → DISPUTED → DRAFT
        loop is unbounded."

        Design: Corner/state_machines/statement_dispute_regenerate_cycle
        """
        trust, ben, stmt = self._delivered_statement(api)
        assert api.dispute_statement(stmt["id"], {"dispute_reason": "missing receipt"},
                                     make_beneficiary_headers(ben["id"])).status_code == 200
        post_receipt(trust["id"], 500000, value_date="2026-09-10", description="interest 2")
        regen = validate_success(api.regenerate_statement(stmt["id"], OFFICER))
        assert regen["status"] == "DRAFT"
        assert regen["receipts_income_cents"] == 1500000
        assert regen["closing_income_cents"] == 1500000


class TestPerYearUniqueness:
    def test_duplicate_statement_year_rejected(self, api):
        """PRD §3.7: "At most one non-SUPERSEDED statement may exist per trust
        and fiscal year — a duplicate is rejected with
        `ERR_STATEMENT_YEAR_EXISTS`."

        Design: Corner/errors/duplicate_statement_year_and_tax_year_rejected
        """
        trust = create_active_trust(trust_name="Dup Years")
        resp = api.create_annual_statement(
            {"trust_id": trust["id"], "fiscal_year": 2026}, OFFICER
        )
        assert resp.status_code == 201
        dup = api.create_annual_statement(
            {"trust_id": trust["id"], "fiscal_year": 2026}, OFFICER
        )
        validate_error(dup, ApiErrorId.ERR_STATEMENT_YEAR_EXISTS)

    def test_duplicate_tax_year_rejected(self, api):
        """PRD §3.8: "there is exactly one filing per trust and tax year ever
        — a second open attempt is rejected with `ERR_DUPLICATE_TAX_YEAR`."

        Design: Corner/errors/duplicate_statement_year_and_tax_year_rejected
        """
        trust = create_active_trust(trust_name="Dup Tax Year")
        create_filing(trust["id"], tax_year=2026)
        dup = api.create_tax_filing({"trust_id": trust["id"], "tax_year": 2026}, TAX)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_TAX_YEAR)
