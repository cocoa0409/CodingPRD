"""Price-quote closed windows and the state low-carbon credit overlay (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    CM,
    OPS,
    create_account,
    create_credit_report,
    create_price_quote,
    create_state_program,
    get_success_data,
    validate_error,
    validate_success,
    api_client,
)


class TestPriceQuoteClosedWindows:
    def _setup(self, api, epa_id):
        acct = create_account(epa_registration_id=epa_id)
        q1 = create_price_quote(
            acct["id"], d_code="D6", vintage_year=2026, price_cents=150,
            effective_start="2026-08-01T00:00:00Z",
            effective_end="2026-08-10T00:00:00Z",
        )
        return acct, q1

    def test_shared_endpoint_conflicts_under_closed_semantics(self, api):
        """PRD §3.7: "Windows for the same account, D-code, and vintage must not overlap: because the intervals are closed, two quotes that merely share an endpoint already conflict, and any overlap is rejected with `ERR_PRICE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/price_quote_windows_closed_shared_endpoint_conflicts
        """
        acct, _q1 = self._setup(api, "EPA-ACME-16")
        resp = api.create_price_quote(
            {
                "account_id": acct["id"],
                "d_code": "D6",
                "vintage_year": 2026,
                "price_cents": 155,
                "effective_start": "2026-08-10T00:00:00Z",
                "effective_end": "2026-08-20T00:00:00Z",
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_PRICE_WINDOW_OVERLAP)

    def test_strictly_later_start_succeeds(self, api):
        """PRD §3.7: "An `OpsAdmin` records an observed quote with the `account_id`, the `d_code`, the `vintage_year`, the observed `price_cents` per RIN (strictly positive), and a closed effective window from `effective_start` through `effective_end`, both endpoints inclusive — the end may equal the start but never precede it."

        Design: Difficulty/resource_temporal_overlap/price_quote_windows_closed_shared_endpoint_conflicts
        """
        acct, _q1 = self._setup(api, "EPA-ACME-16B")
        resp = api.create_price_quote(
            {
                "account_id": acct["id"],
                "d_code": "D6",
                "vintage_year": 2026,
                "price_cents": 155,
                "effective_start": "2026-08-10T00:00:01Z",
                "effective_end": "2026-08-20T00:00:00Z",
            },
            OPS,
        )
        data = validate_success(resp, expected_status=201)
        assert data["price_cents"] == 155


class TestStateCreditDualVariant:
    def _setup(self, api, epa_id):
        acct = create_account(epa_registration_id=epa_id)
        prog = create_state_program(
            acct["id"], state_code="CA", program_type="LCFS",
            ci_standard_gco2e_mj=90.0, default_ci_gco2e_mj=80.0,
        )
        scr = create_credit_report(prog["id"], period_label="2026-Q3",
                                   fuel_gallons=1234)
        return prog, scr

    def test_verification_recomputes_credits_with_measured_ci(self, api):
        """PRD §3.7: "a `ComplianceManager` verifies the report with a strictly positive `measured_ci_gco2e_mj` (`ERR_INVALID_REQUEST` otherwise), moving it `PROVISIONAL` → `VERIFIED`, recomputing `credits_tons` with the measured CI in place of the default — the same fuel volume yields different credits whenever the measured and default values differ"
        PRD §3.7: "its `credits_tons` are computed on the default pathway: the difference between the program's carbon-intensity standard and the default CI, multiplied by an energy density of 120.0 megajoules per gallon and by the reported gallons, divided by one million, rounded half-up to four decimal places"

        Design: Difficulty/dual_variant_calc/state_credit_provisional_vs_verified_on_credit_report
        """
        prog, scr = self._setup(api, "EPA-ACME-2")
        # Provisional: (90 - 80) * 120.0 * 1234 / 1e6 = 1.4808.
        assert scr["credits_tons"] == 1.4808
        data = get_success_data(
            api.verify_state_credit_report(
                scr["id"], {"measured_ci_gco2e_mj": 75.0}, CM,
            ),
        )
        # Verified: (90 - 75) * 120.0 * 1234 / 1e6 = 2.2212.
        assert data["status"] == "VERIFIED"
        assert data["credits_tons"] == 2.2212
        assert data["credits_tons"] != 1.4808

    def test_program_total_rederived_after_verification(self, api):
        """PRD §3.7: "re-deriving the program's `total_credits_tons` by the delta between the provisional and verified figures"
        PRD §3.7: "The program's `total_credits_tons` is then re-derived as the sum of its reports' credits, rounded half-up to four decimal places after summing."

        Design: Difficulty/dual_variant_calc/state_credit_provisional_vs_verified_on_credit_report
        """
        prog, scr = self._setup(api, "EPA-ACME-2B")
        get_success_data(
            api.verify_state_credit_report(
                scr["id"], {"measured_ci_gco2e_mj": 75.0}, CM,
            ),
        )
        prog_after = validate_success(api.get_state_program(prog["id"], CM))
        assert prog_after["total_credits_tons"] == 2.2212
