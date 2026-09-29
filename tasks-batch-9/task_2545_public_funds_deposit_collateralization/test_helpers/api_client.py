"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Public Funds Collateral API."""

    # ─── Custodians ───────────────────────────────────

    def create_custodian(self, payload, headers):
        return self._request("POST", "/custodians", payload, headers)

    def approve_custodian(self, custodian_id, headers, payload=None):
        return self._request(
            "POST", f"/custodians/{custodian_id}/approve", payload or {}, headers
        )

    def get_custodian(self, custodian_id, headers):
        return self._request("GET", f"/custodians/{custodian_id}", headers=headers)

    # ─── Pooled collateral programs ───────────────────

    def create_pooled_program(self, payload, headers):
        return self._request("POST", "/pooled-programs", payload, headers)

    def get_pooled_program(self, pooled_program_id, headers):
        return self._request(
            "GET", f"/pooled-programs/{pooled_program_id}", headers=headers
        )

    def list_pooled_program_depositories(self, pooled_program_id, headers, params=None):
        return self._request(
            "GET",
            f"/pooled-programs/{pooled_program_id}/depositories",
            headers=headers,
            params=params,
        )

    # ─── Public units ─────────────────────────────────

    def create_public_unit(self, payload, headers):
        return self._request("POST", "/public-units", payload, headers)

    def get_public_unit(self, public_unit_id, headers):
        return self._request("GET", f"/public-units/{public_unit_id}", headers=headers)

    # ─── Depositories ─────────────────────────────────

    def create_depository(self, payload, headers):
        return self._request("POST", "/depositories", payload, headers)

    def get_depository(self, depository_id, headers):
        return self._request("GET", f"/depositories/{depository_id}", headers=headers)

    def list_depositories(self, headers, params=None):
        return self._request("GET", "/depositories", headers=headers, params=params)

    def suspend_depository(self, depository_id, headers, payload=None):
        return self._request(
            "POST", f"/depositories/{depository_id}/suspend", payload or {}, headers
        )

    # ─── Qualification reviews ────────────────────────

    def create_qualification_review(self, depository_id, payload, headers):
        return self._request(
            "POST", f"/depositories/{depository_id}/qualification-reviews", payload, headers
        )

    def list_qualification_reviews(self, depository_id, headers, params=None):
        return self._request(
            "GET",
            f"/depositories/{depository_id}/qualification-reviews",
            headers=headers,
            params=params,
        )

    def attest_qualification_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/qualification-reviews/{review_id}/attest", payload, headers
        )

    def begin_review_qualification_review(self, review_id, headers, payload=None):
        return self._request(
            "POST",
            f"/qualification-reviews/{review_id}/begin-review",
            payload or {},
            headers,
        )

    def return_for_info_qualification_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/qualification-reviews/{review_id}/return-for-info", payload, headers
        )

    def decide_qualification_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/qualification-reviews/{review_id}/decide", payload, headers
        )

    # ─── Deposit accounts ─────────────────────────────

    def create_deposit_account(self, payload, headers):
        return self._request("POST", "/deposit-accounts", payload, headers)

    def get_deposit_account(self, account_id, headers):
        return self._request("GET", f"/deposit-accounts/{account_id}", headers=headers)

    def list_deposit_accounts(self, headers, params=None):
        return self._request("GET", "/deposit-accounts", headers=headers, params=params)

    def create_deposit(self, account_id, payload, headers):
        return self._request(
            "POST", f"/deposit-accounts/{account_id}/deposits", payload, headers
        )

    def create_withdrawal(self, account_id, payload, headers):
        return self._request(
            "POST", f"/deposit-accounts/{account_id}/withdrawals", payload, headers
        )

    def get_coverage_report(self, account_id, headers):
        return self._request(
            "GET", f"/deposit-accounts/{account_id}/coverage-report", headers=headers
        )

    def list_account_runoff_forecasts(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/deposit-accounts/{account_id}/runoff-forecasts",
            headers=headers,
            params=params,
        )

    # ─── Pledge agreements ────────────────────────────

    def create_pledge_agreement(self, payload, headers):
        return self._request("POST", "/pledge-agreements", payload, headers)

    def get_pledge_agreement(self, agreement_id, headers):
        return self._request("GET", f"/pledge-agreements/{agreement_id}", headers=headers)

    def list_pledge_agreements(self, headers, params=None):
        return self._request("GET", "/pledge-agreements", headers=headers, params=params)

    def circulate_pledge_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/pledge-agreements/{agreement_id}/circulate", payload or {}, headers
        )

    def create_signature(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/pledge-agreements/{agreement_id}/signatures", payload, headers
        )

    def request_amendment(self, agreement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/pledge-agreements/{agreement_id}/request-amendment",
            payload or {},
            headers,
        )

    def terminate_pledge_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/pledge-agreements/{agreement_id}/terminate", payload or {}, headers
        )

    def list_agreement_safekeeping_receipts(self, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"/pledge-agreements/{agreement_id}/safekeeping-receipts",
            headers=headers,
            params=params,
        )

    # ─── Collateral assets ────────────────────────────

    def create_collateral_asset(self, payload, headers):
        return self._request("POST", "/collateral-assets", payload, headers)

    def get_collateral_asset(self, asset_id, headers):
        return self._request("GET", f"/collateral-assets/{asset_id}", headers=headers)

    def list_collateral_assets(self, headers, params=None):
        return self._request("GET", "/collateral-assets", headers=headers, params=params)

    def post_price(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/collateral-assets/{asset_id}/prices", payload, headers
        )

    def mark_asset_ineligible(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/collateral-assets/{asset_id}/mark-ineligible", payload, headers
        )

    # ─── Pledge allocations ───────────────────────────

    def create_pledge_allocation(self, payload, headers):
        return self._request("POST", "/pledge-allocations", payload, headers)

    def get_pledge_allocation(self, allocation_id, headers):
        return self._request("GET", f"/pledge-allocations/{allocation_id}", headers=headers)

    def list_pledge_allocations(self, headers, params=None):
        return self._request("GET", "/pledge-allocations", headers=headers, params=params)

    def release_pledge_allocation(self, allocation_id, headers, payload=None):
        return self._request(
            "POST", f"/pledge-allocations/{allocation_id}/release", payload or {}, headers
        )

    # ─── Substitution requests ────────────────────────

    def create_substitution_request(self, payload, headers):
        return self._request("POST", "/substitution-requests", payload, headers)

    def get_substitution_request(self, request_id, headers):
        return self._request(
            "GET", f"/substitution-requests/{request_id}", headers=headers
        )

    def list_substitution_requests(self, headers, params=None):
        return self._request(
            "GET", "/substitution-requests", headers=headers, params=params
        )

    def compliance_approve_substitution(self, request_id, headers, payload=None):
        return self._request(
            "POST",
            f"/substitution-requests/{request_id}/compliance-approve",
            payload or {},
            headers,
        )

    def custodian_ack_substitution(self, request_id, headers, payload=None):
        return self._request(
            "POST",
            f"/substitution-requests/{request_id}/custodian-ack",
            payload or {},
            headers,
        )

    def settle_substitution(self, request_id, headers, payload=None):
        return self._request(
            "POST", f"/substitution-requests/{request_id}/settle", payload or {}, headers
        )

    def reject_substitution(self, request_id, payload, headers):
        return self._request(
            "POST", f"/substitution-requests/{request_id}/reject", payload, headers
        )

    def withdraw_substitution(self, request_id, headers, payload=None):
        return self._request(
            "POST", f"/substitution-requests/{request_id}/withdraw", payload or {}, headers
        )

    # ─── Mark-to-market runs ──────────────────────────

    def create_mtm_run(self, depository_id, payload, headers):
        return self._request(
            "POST", f"/depositories/{depository_id}/mtm-runs", payload, headers
        )

    def list_depository_mtm_runs(self, depository_id, headers, params=None):
        return self._request(
            "GET", f"/depositories/{depository_id}/mtm-runs", headers=headers, params=params
        )

    def get_mtm_run(self, run_id, headers):
        return self._request("GET", f"/mtm-runs/{run_id}", headers=headers)

    # ─── Margin calls ─────────────────────────────────

    def get_margin_call(self, margin_call_id, headers):
        return self._request("GET", f"/margin-calls/{margin_call_id}", headers=headers)

    def list_margin_calls(self, headers, params=None):
        return self._request("GET", "/margin-calls", headers=headers, params=params)

    def cure_margin_call(self, margin_call_id, payload, headers):
        return self._request(
            "POST", f"/margin-calls/{margin_call_id}/cure", payload, headers
        )

    # ─── Safekeeping receipts ─────────────────────────

    def create_safekeeping_receipt(self, payload, headers):
        return self._request("POST", "/safekeeping-receipts", payload, headers)

    def confirm_safekeeping_receipt(self, receipt_id, headers, payload=None):
        return self._request(
            "POST", f"/safekeeping-receipts/{receipt_id}/confirm", payload or {}, headers
        )

    # ─── Runoff forecasts ─────────────────────────────

    def create_runoff_forecast(self, payload, headers):
        return self._request("POST", "/runoff-forecasts", payload, headers)

    def get_runoff_forecast(self, forecast_id, headers):
        return self._request("GET", f"/runoff-forecasts/{forecast_id}", headers=headers)

    # ─── Operational endpoints ────────────────────────

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_daily_cycle(self, headers, payload=None):
        return self._request("POST", "/_ops/run-daily-cycle", payload or {}, headers)


api_client = ApiClient()
