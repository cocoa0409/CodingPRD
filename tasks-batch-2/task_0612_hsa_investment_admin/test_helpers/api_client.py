"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ───────────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ─── Accountholders ──────────────────────────────────────────────────────
    def create_accountholder(self, payload, headers):
        return self._request("POST", "/hsa/accountholders", payload, headers)

    def get_accountholder(self, accountholder_id, headers):
        return self._request("GET", f"/hsa/accountholders/{accountholder_id}",
                             headers=headers)

    # ─── Employers ───────────────────────────────────────────────────────────
    def create_employer(self, payload, headers):
        return self._request("POST", "/hsa/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/hsa/employers/{employer_id}", headers=headers)

    def patch_employer(self, employer_id, payload, headers):
        return self._request("PATCH", f"/hsa/employers/{employer_id}", payload, headers)

    # ─── Payroll periods ─────────────────────────────────────────────────────
    def create_payroll_period(self, employer_id, payload, headers):
        return self._request("POST", f"/hsa/employers/{employer_id}/payroll-periods",
                             payload, headers)

    def list_payroll_periods(self, employer_id, headers, params=None):
        return self._request("GET", f"/hsa/employers/{employer_id}/payroll-periods",
                             headers=headers, params=params)

    def cancel_payroll_period(self, employer_id, payroll_period_id, headers):
        return self._request(
            "POST",
            f"/hsa/employers/{employer_id}/payroll-periods/{payroll_period_id}/cancel",
            headers=headers)

    # ─── HSA accounts ────────────────────────────────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", "/hsa/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/hsa/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/hsa/accounts", headers=headers, params=params)

    def verify_account(self, account_id, payload, headers):
        return self._request("POST", f"/hsa/accounts/{account_id}/verify",
                             payload, headers)

    def freeze_account(self, account_id, headers):
        return self._request("POST", f"/hsa/accounts/{account_id}/freeze",
                             headers=headers)

    def unfreeze_account(self, account_id, headers):
        return self._request("POST", f"/hsa/accounts/{account_id}/unfreeze",
                             headers=headers)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/hsa/accounts/{account_id}/close",
                             headers=headers)

    def set_limit_variant(self, account_id, payload, headers):
        return self._request("POST", f"/hsa/accounts/{account_id}/limit-variant",
                             payload, headers)

    # ─── Coverage periods ────────────────────────────────────────────────────
    def create_coverage_period(self, account_id, payload, headers):
        return self._request("POST", f"/hsa/accounts/{account_id}/coverage-periods",
                             payload, headers)

    def list_coverage_periods(self, account_id, headers, params=None):
        return self._request("GET", f"/hsa/accounts/{account_id}/coverage-periods",
                             headers=headers, params=params)

    def supersede_coverage_period(self, account_id, coverage_period_id, headers):
        return self._request(
            "POST",
            f"/hsa/accounts/{account_id}/coverage-periods/{coverage_period_id}/supersede",
            headers=headers)

    # ─── Contributions ───────────────────────────────────────────────────────
    def create_contribution(self, account_id, payload, headers):
        return self._request("POST", f"/hsa/accounts/{account_id}/contributions",
                             payload, headers)

    def list_contributions(self, account_id, headers, params=None):
        return self._request("GET", f"/hsa/accounts/{account_id}/contributions",
                             headers=headers, params=params)

    def post_contribution(self, account_id, contribution_id, headers):
        return self._request(
            "POST",
            f"/hsa/accounts/{account_id}/contributions/{contribution_id}/post",
            headers=headers)

    # ─── Sweeps ──────────────────────────────────────────────────────────────
    def create_sweep(self, account_id, payload, headers):
        return self._request("POST", f"/hsa/accounts/{account_id}/sweeps",
                             payload, headers)

    def list_sweeps(self, account_id, headers, params=None):
        return self._request("GET", f"/hsa/accounts/{account_id}/sweeps",
                             headers=headers, params=params)

    def unwind_sweep(self, account_id, sweep_id, headers):
        return self._request(
            "POST", f"/hsa/accounts/{account_id}/sweeps/{sweep_id}/unwind",
            headers=headers)

    # ─── Debit cards ─────────────────────────────────────────────────────────
    def create_card(self, account_id, payload, headers):
        return self._request("POST", f"/hsa/accounts/{account_id}/cards",
                             payload, headers)

    def list_cards(self, account_id, headers, params=None):
        return self._request("GET", f"/hsa/accounts/{account_id}/cards",
                             headers=headers, params=params)

    def activate_card(self, account_id, card_id, headers):
        return self._request(
            "POST", f"/hsa/accounts/{account_id}/cards/{card_id}/activate",
            headers=headers)

    def suspend_card(self, account_id, card_id, headers):
        return self._request(
            "POST", f"/hsa/accounts/{account_id}/cards/{card_id}/suspend",
            headers=headers)

    def close_card(self, account_id, card_id, headers):
        return self._request(
            "POST", f"/hsa/accounts/{account_id}/cards/{card_id}/close",
            headers=headers)

    # ─── Receipts ────────────────────────────────────────────────────────────
    def create_receipt(self, payload, headers):
        return self._request("POST", "/hsa/receipts", payload, headers)

    def get_receipt(self, receipt_id, headers):
        return self._request("GET", f"/hsa/receipts/{receipt_id}", headers=headers)

    def list_receipts(self, headers, params=None):
        return self._request("GET", "/hsa/receipts", headers=headers, params=params)

    # ─── Distributions ───────────────────────────────────────────────────────
    def create_distribution(self, account_id, payload, headers):
        return self._request("POST", f"/hsa/accounts/{account_id}/distributions",
                             payload, headers)

    def list_distributions(self, account_id, headers, params=None):
        return self._request("GET", f"/hsa/accounts/{account_id}/distributions",
                             headers=headers, params=params)

    def clear_distribution(self, account_id, distribution_id, headers):
        return self._request(
            "POST",
            f"/hsa/accounts/{account_id}/distributions/{distribution_id}/clear",
            headers=headers)

    def deny_distribution(self, account_id, distribution_id, headers):
        return self._request(
            "POST",
            f"/hsa/accounts/{account_id}/distributions/{distribution_id}/deny",
            headers=headers)

    def substantiate_distribution(self, account_id, distribution_id, payload, headers):
        return self._request(
            "POST",
            f"/hsa/accounts/{account_id}/distributions/{distribution_id}/substantiate",
            payload, headers)

    def reverse_distribution(self, account_id, distribution_id, headers):
        return self._request(
            "POST",
            f"/hsa/accounts/{account_id}/distributions/{distribution_id}/reverse",
            headers=headers)

    # ─── Excess corrections ──────────────────────────────────────────────────
    def create_correction(self, account_id, payload, headers):
        return self._request("POST", f"/hsa/accounts/{account_id}/corrections",
                             payload, headers)

    def list_corrections(self, account_id, headers, params=None):
        return self._request("GET", f"/hsa/accounts/{account_id}/corrections",
                             headers=headers, params=params)

    def execute_correction(self, account_id, correction_id, headers):
        return self._request(
            "POST",
            f"/hsa/accounts/{account_id}/corrections/{correction_id}/execute",
            headers=headers)

    def reject_correction(self, account_id, correction_id, headers):
        return self._request(
            "POST",
            f"/hsa/accounts/{account_id}/corrections/{correction_id}/reject",
            headers=headers)

    # ─── Tax forms ───────────────────────────────────────────────────────────
    def create_tax_form(self, account_id, payload, headers):
        return self._request("POST", f"/hsa/accounts/{account_id}/tax-forms",
                             payload, headers)

    def list_tax_forms(self, account_id, headers, params=None):
        return self._request("GET", f"/hsa/accounts/{account_id}/tax-forms",
                             headers=headers, params=params)

    def get_tax_form(self, account_id, tax_form_id, headers):
        return self._request("GET",
                             f"/hsa/accounts/{account_id}/tax-forms/{tax_form_id}",
                             headers=headers)


api_client = ApiClient()
