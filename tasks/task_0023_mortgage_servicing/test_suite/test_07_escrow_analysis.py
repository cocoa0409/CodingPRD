"""Annual escrow analysis: dual variant (actual vs forecast), OCC stale
version, list-by-loan filter."""
from test_helpers import (
    ApiErrorId,
    validate_success,
    validate_error,
    validate_paginated,
    set_clock,
    create_borrower,
    create_loan,
    create_escrow_account,
    post_payment,
    fetch_escrow_account,
    fetch_loan,
    make_loan_servicer_headers,
)


class TestEscrowAnalysisOCC:

    def test_analysis_with_stale_escrow_version_rejected(self, api):
        """PRD §2.8: "A request to run an escrow analysis must carry the
        field expected_escrow_account_version, an integer equal to the
        client's last observed version of the target escrow account. If
        another writer has advanced the escrow account's version since the
        client last read it — for example, by paying out a scheduled
        disbursement that changed the balance — the analysis is rejected
        with ERR_STALE_VERSION and HTTP 412, because the projected
        low-point input would be computed from a stale balance."

        Design: Corner/cross_cutting_complexity_layers/layer_occ_escrow_analysis_stale_version
        """
        set_clock("2025-01-01T00:00:00Z")
        borrower = create_borrower()
        loan = create_loan(
            borrower_id=borrower["id"],
            origination_date="2025-01-01T00:00:00Z",
            original_principal_cents=20000000,
            original_property_value_cents=25000000,
            interest_rate_bps=500,
            term_months=360,
            pmi_monthly_cents=9000,
        )
        escrow = create_escrow_account(
            loan["id"], annual_tax_cents=480000,
            annual_insurance_cents=120000, cushion_months=2,
        )
        post_payment(loan["id"], 5000000, "2025-01-15T00:00:00Z")
        validate_success(api.create_disbursement(
            escrow["id"],
            {"kind": "TAX", "amount_cents": 200000,
             "scheduled_for": "2025-03-01T00:00:00Z"},
            make_loan_servicer_headers(),
        ), expected_status=201)
        # Observe the version BEFORE the disbursement fires.
        esc_observed = fetch_escrow_account(escrow["id"])
        observed_version = esc_observed["version"]
        # Advance past scheduled_for so the disbursement evaluates → version
        # advances on the escrow account.
        set_clock("2025-03-02T00:00:00Z")
        # Run analysis with stale expected version.
        resp = api.run_escrow_analysis(
            escrow["id"],
            {"as_of_date": "2026-01-01T00:00:00Z",
             "variant": "FORECAST_NEXT_12",
             "expected_escrow_account_version": observed_version},
            make_loan_servicer_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestEscrowAnalysisListing:

    def test_list_escrow_analyses_supports_loan_filter(self, api):
        """PRD §2.3: "List endpoints accept two optional query parameters.
        The limit parameter caps the number of items returned in a single
        page; it defaults to 10, with a minimum of 1 and a maximum of 100.
        The offset parameter specifies the number of items to skip and
        defaults to 0."

        Design: Corner/endpoints/ep_escrow_analyses_list_supports_loan_filter
        """
        set_clock("2025-01-01T00:00:00Z")
        borrower = create_borrower()
        loan = create_loan(
            borrower_id=borrower["id"],
            origination_date="2025-01-01T00:00:00Z",
            original_principal_cents=20000000,
            original_property_value_cents=25000000,
            interest_rate_bps=500,
            term_months=360,
            pmi_monthly_cents=9000,
        )
        escrow = create_escrow_account(
            loan["id"], annual_tax_cents=480000,
            annual_insurance_cents=120000, cushion_months=2,
        )
        esc_pre = fetch_escrow_account(escrow["id"])
        validate_success(api.run_escrow_analysis(
            escrow["id"],
            {"as_of_date": "2026-01-01T00:00:00Z",
             "variant": "FORECAST_NEXT_12",
             "expected_escrow_account_version": esc_pre["version"]},
            make_loan_servicer_headers(),
        ), expected_status=201)
        resp = api.list_escrow_analyses(
            make_loan_servicer_headers(), params={"loan_id": loan["id"]},
        )
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert len(data) == 1
