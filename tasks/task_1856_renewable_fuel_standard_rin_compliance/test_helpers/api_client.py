"""API client: one method per endpoint defined in the PRD (§4)."""
import requests.adapters
from urllib3.util.retry import Retry

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        # Transport resilience only — no assertion semantics change. The
        # harness SIGKILL-restarts the dev server before every test
        # (per-test-server isolation) and the stability sweep runs 8 rounds
        # concurrently; Werkzeug's dev server closes each connection after
        # its response ("Connection: close"), and under that churn a fresh
        # connection can be reset before the server answers
        # (RemoteDisconnected / ECONNRESET). Retry covers only such
        # transport-level drops: urllib3 gates read-retries by
        # allowed_methods, so mutating POSTs are never silently re-issued,
        # and status codes are never retried (status_forcelist empty).
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=0.05,
            allowed_methods=frozenset({"GET", "HEAD", "OPTIONS", "TRACE"}),
            status_forcelist=(),
            raise_on_status=False,
        )
        adapter = requests.adapters.HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- ComplianceAccount ---
    def create_compliance_account(self, payload, headers):
        return self._request("POST", "/rfs/compliance-accounts", payload, headers)

    def get_compliance_account(self, account_id, headers):
        return self._request("GET", f"/rfs/compliance-accounts/{account_id}", headers=headers)

    def get_account_position(self, account_id, headers):
        return self._request("GET", f"/rfs/compliance-accounts/{account_id}/position", headers=headers)

    def get_account_exposure(self, account_id, headers):
        return self._request("GET", f"/rfs/compliance-accounts/{account_id}/exposure", headers=headers)

    def purge_records(self, account_id, headers):
        return self._request("POST", f"/rfs/compliance-accounts/{account_id}/purge-records", headers=headers)

    # --- ObligationYear ---
    def create_obligation_year(self, payload, headers):
        return self._request("POST", "/rfs/obligation-years", payload, headers)

    def get_obligation_year(self, year_id, headers):
        return self._request("GET", f"/rfs/obligation-years/{year_id}", headers=headers)

    def list_obligation_years(self, headers, params=None):
        return self._request("GET", "/rfs/obligation-years", headers=headers, params=params)

    def close_volume(self, year_id, payload, headers):
        return self._request("POST", f"/rfs/obligation-years/{year_id}/close-volume", payload, headers)

    def finalize_year(self, year_id, headers):
        return self._request("POST", f"/rfs/obligation-years/{year_id}/finalize", headers=headers)

    # --- Vendor ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/rfs/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/rfs/vendors/{vendor_id}", headers=headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/rfs/vendors", headers=headers, params=params)

    def record_diligence(self, vendor_id, payload, headers):
        return self._request("POST", f"/rfs/vendors/{vendor_id}/diligence", payload, headers)

    # --- RINLot & BlendingRecord ---
    def create_rin_lot(self, payload, headers):
        return self._request("POST", "/rfs/rin-lots", payload, headers)

    def get_rin_lot(self, lot_id, headers):
        return self._request("GET", f"/rfs/rin-lots/{lot_id}", headers=headers)

    def list_rin_lots(self, headers, params=None):
        return self._request("GET", "/rfs/rin-lots", headers=headers, params=params)

    def create_separation(self, lot_id, payload, headers):
        return self._request("POST", f"/rfs/rin-lots/{lot_id}/separations", payload, headers)

    def get_blending_record(self, record_id, headers):
        return self._request("GET", f"/rfs/blending-records/{record_id}", headers=headers)

    def list_blending_records(self, headers, params=None):
        return self._request("GET", "/rfs/blending-records", headers=headers, params=params)

    # --- RINTrade ---
    def create_rin_trade(self, payload, headers):
        return self._request("POST", "/rfs/rin-trades", payload, headers)

    def get_rin_trade(self, trade_id, headers):
        return self._request("GET", f"/rfs/rin-trades/{trade_id}", headers=headers)

    def list_rin_trades(self, headers, params=None):
        return self._request("GET", "/rfs/rin-trades", headers=headers, params=params)

    def pay_trade(self, trade_id, headers):
        return self._request("POST", f"/rfs/rin-trades/{trade_id}/pay", headers=headers)

    def deliver_trade(self, trade_id, headers):
        return self._request("POST", f"/rfs/rin-trades/{trade_id}/deliver", headers=headers)

    def verify_trade(self, trade_id, headers):
        return self._request("POST", f"/rfs/rin-trades/{trade_id}/verify", headers=headers)

    def cancel_trade(self, trade_id, headers):
        return self._request("POST", f"/rfs/rin-trades/{trade_id}/cancel", headers=headers)

    def invalidate_trade(self, trade_id, headers):
        return self._request("POST", f"/rfs/rin-trades/{trade_id}/invalidate", headers=headers)

    # --- RetirementBatch ---
    def create_retirement_batch(self, payload, headers):
        return self._request("POST", "/rfs/retirement-batches", payload, headers)

    def get_retirement_batch(self, batch_id, headers):
        return self._request("GET", f"/rfs/retirement-batches/{batch_id}", headers=headers)

    def list_retirement_batches(self, headers, params=None):
        return self._request("GET", "/rfs/retirement-batches", headers=headers, params=params)

    def submit_retirement_batch(self, batch_id, headers):
        return self._request("POST", f"/rfs/retirement-batches/{batch_id}/submit", headers=headers)

    def decide_retirement_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/rfs/retirement-batches/{batch_id}/decide", payload, headers)

    # --- ComplianceReport ---
    def create_compliance_report(self, payload, headers):
        return self._request("POST", "/rfs/compliance-reports", payload, headers)

    def get_compliance_report(self, report_id, headers):
        return self._request("GET", f"/rfs/compliance-reports/{report_id}", headers=headers)

    def list_compliance_reports(self, headers, params=None):
        return self._request("GET", "/rfs/compliance-reports", headers=headers, params=params)

    def submit_compliance_report(self, report_id, headers):
        return self._request("POST", f"/rfs/compliance-reports/{report_id}/submit", headers=headers)

    def decide_compliance_report(self, report_id, payload, headers):
        return self._request("POST", f"/rfs/compliance-reports/{report_id}/decide", payload, headers)

    def reopen_compliance_report(self, report_id, headers):
        return self._request("POST", f"/rfs/compliance-reports/{report_id}/reopen", headers=headers)

    # --- AttestEngagement ---
    def create_attest_engagement(self, payload, headers):
        return self._request("POST", "/rfs/attest-engagements", payload, headers)

    def get_attest_engagement(self, engagement_id, headers):
        return self._request("GET", f"/rfs/attest-engagements/{engagement_id}", headers=headers)

    def list_attest_engagements(self, headers, params=None):
        return self._request("GET", "/rfs/attest-engagements", headers=headers, params=params)

    def begin_fieldwork(self, engagement_id, headers):
        return self._request("POST", f"/rfs/attest-engagements/{engagement_id}/begin-fieldwork", headers=headers)

    def issue_findings(self, engagement_id, payload, headers):
        return self._request("POST", f"/rfs/attest-engagements/{engagement_id}/issue-findings", payload, headers)

    def remediate_engagement(self, engagement_id, headers):
        return self._request("POST", f"/rfs/attest-engagements/{engagement_id}/remediate", headers=headers)

    def close_engagement(self, engagement_id, headers):
        return self._request("POST", f"/rfs/attest-engagements/{engagement_id}/close", headers=headers)

    # --- StateProgram / StateCreditReport ---
    def create_state_program(self, payload, headers):
        return self._request("POST", "/rfs/state-programs", payload, headers)

    def get_state_program(self, program_id, headers):
        return self._request("GET", f"/rfs/state-programs/{program_id}", headers=headers)

    def list_state_programs(self, headers, params=None):
        return self._request("GET", "/rfs/state-programs", headers=headers, params=params)

    def create_state_credit_report(self, payload, headers):
        return self._request("POST", "/rfs/state-credit-reports", payload, headers)

    def get_state_credit_report(self, report_id, headers):
        return self._request("GET", f"/rfs/state-credit-reports/{report_id}", headers=headers)

    def list_state_credit_reports(self, headers, params=None):
        return self._request("GET", "/rfs/state-credit-reports", headers=headers, params=params)

    def verify_state_credit_report(self, report_id, payload, headers):
        return self._request("POST", f"/rfs/state-credit-reports/{report_id}/verify", payload, headers)

    # --- PriceQuote ---
    def create_price_quote(self, payload, headers):
        return self._request("POST", "/rfs/price-quotes", payload, headers)

    def get_price_quote(self, quote_id, headers):
        return self._request("GET", f"/rfs/price-quotes/{quote_id}", headers=headers)

    def list_price_quotes(self, headers, params=None):
        return self._request("GET", "/rfs/price-quotes", headers=headers, params=params)


api_client = ApiClient()
