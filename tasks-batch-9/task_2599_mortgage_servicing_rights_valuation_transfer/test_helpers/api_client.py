"""
HTTP client for the mortgage servicing rights transfer API.

One method per documented endpoint. Every method returns the raw
`requests.Response` so a test can assert on the status code as well as on the
body. Business paths carry the `/msr` prefix; the logical-clock control does
not. Auth headers are always explicit, because the selling and acquiring
servicers act under the identifier of their own counterparty row.
"""

from prd_bench_local_runner.testing import GenericApiClient

from .types import ApiResponse, Headers, JsonDict, Params


class ApiClient(GenericApiClient):
    """Typed access to every endpoint of the transfer desk API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_current_utc(self, payload: JsonDict,
                        headers: Headers = None) -> ApiResponse:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Counterparties
    # ------------------------------------------------------------------
    def create_counterparty(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/msr/counterparties", payload, headers)

    def get_counterparty(self, counterparty_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/msr/counterparties/{counterparty_id}",
                             headers=headers)

    def list_counterparties(self, headers: Headers,
                            params: Params = None) -> ApiResponse:
        return self._request("GET", "/msr/counterparties", headers=headers,
                             params=params)

    def suspend_counterparty(self, counterparty_id: str,
                             headers: Headers) -> ApiResponse:
        return self._request("POST", f"/msr/counterparties/{counterparty_id}/suspend",
                             {}, headers)

    def get_risk_score(self, counterparty_id: str, headers: Headers,
                       params: Params = None) -> ApiResponse:
        return self._request("GET",
                             f"/msr/counterparties/{counterparty_id}/risk-score",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Portfolios and loans
    # ------------------------------------------------------------------
    def create_portfolio(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/msr/portfolios", payload, headers)

    def get_portfolio(self, portfolio_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/msr/portfolios/{portfolio_id}", headers=headers)

    def list_portfolios(self, headers: Headers, params: Params = None) -> ApiResponse:
        return self._request("GET", "/msr/portfolios", headers=headers, params=params)

    def create_loan(self, portfolio_id: str, payload: JsonDict,
                    headers: Headers) -> ApiResponse:
        return self._request("POST", f"/msr/portfolios/{portfolio_id}/loans",
                             payload, headers)

    def list_portfolio_loans(self, portfolio_id: str, headers: Headers,
                             params: Params = None) -> ApiResponse:
        return self._request("GET", f"/msr/portfolios/{portfolio_id}/loans",
                             headers=headers, params=params)

    def lock_tape(self, portfolio_id: str, headers: Headers) -> ApiResponse:
        return self._request("POST", f"/msr/portfolios/{portfolio_id}/lock-tape",
                             {}, headers)

    def get_loan(self, loan_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/msr/loans/{loan_id}", headers=headers)

    def list_loan_tape_lines(self, loan_id: str, headers: Headers,
                             params: Params = None) -> ApiResponse:
        return self._request("GET", f"/msr/loans/{loan_id}/tape-lines",
                             headers=headers, params=params)

    def list_loan_notices(self, loan_id: str, headers: Headers,
                          params: Params = None) -> ApiResponse:
        return self._request("GET", f"/msr/loans/{loan_id}/notices",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Assumption sets and rate curves
    # ------------------------------------------------------------------
    def create_assumption_set(self, payload: JsonDict,
                              headers: Headers) -> ApiResponse:
        return self._request("POST", "/msr/assumption-sets", payload, headers)

    def get_assumption_set(self, assumption_set_id: str,
                           headers: Headers) -> ApiResponse:
        return self._request("GET", f"/msr/assumption-sets/{assumption_set_id}",
                             headers=headers)

    def create_rate_curve(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/msr/rate-curves", payload, headers)

    def get_rate_curve(self, rate_curve_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/msr/rate-curves/{rate_curve_id}",
                             headers=headers)

    def list_rate_curves(self, headers: Headers, params: Params = None) -> ApiResponse:
        return self._request("GET", "/msr/rate-curves", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Valuation runs
    # ------------------------------------------------------------------
    def create_valuation_run(self, portfolio_id: str, payload: JsonDict,
                             headers: Headers) -> ApiResponse:
        return self._request("POST", f"/msr/portfolios/{portfolio_id}/valuation-runs",
                             payload, headers)

    def get_valuation_run(self, valuation_run_id: str,
                          headers: Headers) -> ApiResponse:
        return self._request("GET", f"/msr/valuation-runs/{valuation_run_id}",
                             headers=headers)

    def list_valuation_runs(self, headers: Headers,
                            params: Params = None) -> ApiResponse:
        return self._request("GET", "/msr/valuation-runs", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Bid packages and the loan-level tape
    # ------------------------------------------------------------------
    def create_bid_package(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/msr/bid-packages", payload, headers)

    def get_bid_package(self, bid_package_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/msr/bid-packages/{bid_package_id}",
                             headers=headers)

    def list_bid_packages(self, headers: Headers,
                          params: Params = None) -> ApiResponse:
        return self._request("GET", "/msr/bid-packages", headers=headers,
                             params=params)

    def stratify_bid_package(self, bid_package_id: str,
                             headers: Headers) -> ApiResponse:
        return self._request("POST", f"/msr/bid-packages/{bid_package_id}/stratify",
                             {}, headers)

    def list_package_tape_lines(self, bid_package_id: str, headers: Headers,
                                params: Params = None) -> ApiResponse:
        return self._request("GET", f"/msr/bid-packages/{bid_package_id}/tape-lines",
                             headers=headers, params=params)

    def patch_tape_line(self, tape_line_id: str, payload: JsonDict,
                        headers: Headers) -> ApiResponse:
        return self._request("PATCH", f"/msr/tape-lines/{tape_line_id}",
                             payload, headers)

    def get_tape_line(self, tape_line_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/msr/tape-lines/{tape_line_id}", headers=headers)

    def publish_bid_package(self, bid_package_id: str,
                            headers: Headers) -> ApiResponse:
        return self._request("POST", f"/msr/bid-packages/{bid_package_id}/publish",
                             {}, headers)

    # ------------------------------------------------------------------
    # Bids and negotiation
    # ------------------------------------------------------------------
    def create_bid(self, bid_package_id: str, payload: JsonDict,
                   headers: Headers) -> ApiResponse:
        return self._request("POST", f"/msr/bid-packages/{bid_package_id}/bids",
                             payload, headers)

    def get_bid(self, bid_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/msr/bids/{bid_id}", headers=headers)

    def list_bids(self, headers: Headers, params: Params = None) -> ApiResponse:
        return self._request("GET", "/msr/bids", headers=headers, params=params)

    def counter_bid(self, bid_id: str, payload: JsonDict,
                    headers: Headers) -> ApiResponse:
        return self._request("POST", f"/msr/bids/{bid_id}/counter", payload, headers)

    def revise_bid(self, bid_id: str, payload: JsonDict,
                   headers: Headers) -> ApiResponse:
        return self._request("POST", f"/msr/bids/{bid_id}/revise", payload, headers)

    def award_bid_package(self, bid_package_id: str, payload: JsonDict,
                          headers: Headers) -> ApiResponse:
        return self._request("POST", f"/msr/bid-packages/{bid_package_id}/award",
                             payload, headers)

    # ------------------------------------------------------------------
    # Purchase agreements, approvals, settlement and holdback
    # ------------------------------------------------------------------
    def get_purchase_agreement(self, agreement_id: str,
                               headers: Headers) -> ApiResponse:
        return self._request("GET", f"/msr/purchase-agreements/{agreement_id}",
                             headers=headers)

    def list_purchase_agreements(self, headers: Headers,
                                 params: Params = None) -> ApiResponse:
        return self._request("GET", "/msr/purchase-agreements", headers=headers,
                             params=params)

    def create_approval_request(self, agreement_id: str, payload: JsonDict,
                                headers: Headers) -> ApiResponse:
        return self._request(
            "POST", f"/msr/purchase-agreements/{agreement_id}/approval-requests",
            payload, headers)

    def list_approval_requests(self, agreement_id: str, headers: Headers,
                               params: Params = None) -> ApiResponse:
        return self._request(
            "GET", f"/msr/purchase-agreements/{agreement_id}/approval-requests",
            headers=headers, params=params)

    def get_approval_request(self, approval_request_id: str,
                             headers: Headers) -> ApiResponse:
        return self._request("GET", f"/msr/approval-requests/{approval_request_id}",
                             headers=headers)

    def submit_for_approval(self, agreement_id: str,
                            headers: Headers) -> ApiResponse:
        return self._request(
            "POST", f"/msr/purchase-agreements/{agreement_id}/submit-for-approval",
            {}, headers)

    def decide_approval_request(self, approval_request_id: str, payload: JsonDict,
                                headers: Headers) -> ApiResponse:
        return self._request(
            "POST", f"/msr/approval-requests/{approval_request_id}/decide",
            payload, headers)

    def settle_agreement(self, agreement_id: str, payload: JsonDict,
                         headers: Headers) -> ApiResponse:
        return self._request("POST",
                             f"/msr/purchase-agreements/{agreement_id}/settle",
                             payload, headers)

    def create_holdback_release(self, agreement_id: str, payload: JsonDict,
                                headers: Headers) -> ApiResponse:
        return self._request(
            "POST", f"/msr/purchase-agreements/{agreement_id}/holdback-releases",
            payload, headers)

    def create_holdback_clawback(self, agreement_id: str, payload: JsonDict,
                                 headers: Headers) -> ApiResponse:
        return self._request(
            "POST", f"/msr/purchase-agreements/{agreement_id}/holdback-clawbacks",
            payload, headers)

    # ------------------------------------------------------------------
    # Servicing transfers — the three work streams
    # ------------------------------------------------------------------
    def get_servicing_transfer(self, transfer_id: str,
                               headers: Headers) -> ApiResponse:
        return self._request("GET", f"/msr/servicing-transfers/{transfer_id}",
                             headers=headers)

    def list_servicing_transfers(self, headers: Headers,
                                 params: Params = None) -> ApiResponse:
        return self._request("GET", "/msr/servicing-transfers", headers=headers,
                             params=params)

    def map_data(self, transfer_id: str, payload: JsonDict,
                 headers: Headers) -> ApiResponse:
        return self._request("POST",
                             f"/msr/servicing-transfers/{transfer_id}/map-data",
                             payload, headers)

    def map_escrow(self, transfer_id: str, headers: Headers) -> ApiResponse:
        return self._request("POST",
                             f"/msr/servicing-transfers/{transfer_id}/map-escrow",
                             {}, headers)

    def rollback_escrow_mapping(self, transfer_id: str, payload: JsonDict,
                                headers: Headers) -> ApiResponse:
        return self._request(
            "POST",
            f"/msr/servicing-transfers/{transfer_id}/rollback-escrow-mapping",
            payload, headers)

    def reconcile(self, transfer_id: str, headers: Headers) -> ApiResponse:
        return self._request("POST",
                             f"/msr/servicing-transfers/{transfer_id}/reconcile",
                             {}, headers)

    def transfer_pipeline(self, transfer_id: str, headers: Headers) -> ApiResponse:
        return self._request(
            "POST", f"/msr/servicing-transfers/{transfer_id}/transfer-pipeline",
            {}, headers)

    def create_notice(self, transfer_id: str, payload: JsonDict,
                      headers: Headers) -> ApiResponse:
        return self._request("POST",
                             f"/msr/servicing-transfers/{transfer_id}/notices",
                             payload, headers)

    def list_transfer_notices(self, transfer_id: str, headers: Headers,
                              params: Params = None) -> ApiResponse:
        return self._request("GET",
                             f"/msr/servicing-transfers/{transfer_id}/notices",
                             headers=headers, params=params)

    def attest_notices(self, transfer_id: str, headers: Headers) -> ApiResponse:
        return self._request(
            "POST", f"/msr/servicing-transfers/{transfer_id}/attest-notices",
            {}, headers)

    def complete_transfer(self, transfer_id: str, headers: Headers) -> ApiResponse:
        return self._request("POST",
                             f"/msr/servicing-transfers/{transfer_id}/complete",
                             {}, headers)

    # ------------------------------------------------------------------
    # Post-transfer error resolution
    # ------------------------------------------------------------------
    def create_error_case(self, transfer_id: str, payload: JsonDict,
                          headers: Headers) -> ApiResponse:
        return self._request("POST",
                             f"/msr/servicing-transfers/{transfer_id}/error-cases",
                             payload, headers)

    def get_error_case(self, error_case_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/msr/error-cases/{error_case_id}",
                             headers=headers)

    def list_error_cases(self, headers: Headers,
                         params: Params = None) -> ApiResponse:
        return self._request("GET", "/msr/error-cases", headers=headers,
                             params=params)

    def acknowledge_error_case(self, error_case_id: str,
                               headers: Headers) -> ApiResponse:
        return self._request("POST",
                             f"/msr/error-cases/{error_case_id}/acknowledge",
                             {}, headers)

    def resolve_error_case(self, error_case_id: str, payload: JsonDict,
                           headers: Headers) -> ApiResponse:
        return self._request("POST", f"/msr/error-cases/{error_case_id}/resolve",
                             payload, headers)

    def reopen_error_case(self, error_case_id: str, payload: JsonDict,
                          headers: Headers) -> ApiResponse:
        return self._request("POST", f"/msr/error-cases/{error_case_id}/reopen",
                             payload, headers)

    # ------------------------------------------------------------------
    # Hedging
    # ------------------------------------------------------------------
    def create_hedge_position(self, payload: JsonDict,
                              headers: Headers) -> ApiResponse:
        return self._request("POST", "/msr/hedge-positions", payload, headers)

    def get_hedge_position(self, hedge_position_id: str,
                           headers: Headers) -> ApiResponse:
        return self._request("GET", f"/msr/hedge-positions/{hedge_position_id}",
                             headers=headers)

    def list_portfolio_hedge_positions(self, portfolio_id: str, headers: Headers,
                                       params: Params = None) -> ApiResponse:
        return self._request("GET",
                             f"/msr/portfolios/{portfolio_id}/hedge-positions",
                             headers=headers, params=params)

    def get_hedge_effectiveness(self, portfolio_id: str,
                                headers: Headers) -> ApiResponse:
        return self._request("GET",
                             f"/msr/portfolios/{portfolio_id}/hedge-effectiveness",
                             headers=headers)

    def close_hedge_position(self, hedge_position_id: str,
                             headers: Headers) -> ApiResponse:
        return self._request("POST",
                             f"/msr/hedge-positions/{hedge_position_id}/close",
                             {}, headers)


api_client = ApiClient()
