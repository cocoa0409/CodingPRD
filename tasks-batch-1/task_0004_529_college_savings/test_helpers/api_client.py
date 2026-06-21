"""API client: one method per endpoint defined in the PRD."""
from typing import Optional, Dict, Any
import requests
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Donors ---
    def create_donor(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/donors", payload, headers)

    def get_donor(self, donor_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/donors/{donor_id}", headers=headers)

    def list_donors(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/donors", headers=headers, params=params)

    # --- Beneficiaries ---
    def create_beneficiary(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/beneficiaries", payload, headers)

    def get_beneficiary(self, beneficiary_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/beneficiaries/{beneficiary_id}", headers=headers)

    def list_beneficiaries(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/beneficiaries", headers=headers, params=params)

    # --- Accounts ---
    def create_account(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/accounts", headers=headers, params=params)

    def restrict_account(self, account_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/accounts/{account_id}/restrict", {}, headers)

    def release_account(self, account_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/accounts/{account_id}/release", {}, headers)

    def close_account(self, account_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/accounts/{account_id}/close", {}, headers)

    # --- Scheduled Contributions ---
    def create_scheduled_contribution(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/scheduled-contributions", payload, headers)

    def get_scheduled_contribution(self, schedule_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/scheduled-contributions/{schedule_id}", headers=headers)

    def list_scheduled_contributions(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/scheduled-contributions", headers=headers, params=params)

    def pause_scheduled_contribution(self, schedule_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/scheduled-contributions/{schedule_id}/pause", {}, headers)

    def resume_scheduled_contribution(self, schedule_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/scheduled-contributions/{schedule_id}/resume", {}, headers)

    def cancel_scheduled_contribution(self, schedule_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/scheduled-contributions/{schedule_id}/cancel", {}, headers)

    # --- Contributions ---
    def create_contribution(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/contributions", payload, headers)

    def post_contribution(self, contribution_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/contributions/{contribution_id}/post", {}, headers)

    def reverse_contribution(self, contribution_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/contributions/{contribution_id}/reverse", {}, headers)

    def get_contribution(self, contribution_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/contributions/{contribution_id}", headers=headers)

    def list_contributions(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/contributions", headers=headers, params=params)

    # --- Withdrawals ---
    def create_withdrawal(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/withdrawals", payload, headers)

    def submit_withdrawal(self, withdrawal_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/withdrawals/{withdrawal_id}/submit", {}, headers)

    def reject_withdrawal(self, withdrawal_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/withdrawals/{withdrawal_id}/reject", {}, headers)

    def revise_withdrawal(self, withdrawal_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/withdrawals/{withdrawal_id}/revise", {}, headers)

    def approve_withdrawal(self, withdrawal_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/withdrawals/{withdrawal_id}/approve", payload, headers)

    def disburse_withdrawal(self, withdrawal_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/withdrawals/{withdrawal_id}/disburse", {}, headers)

    def get_withdrawal(self, withdrawal_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/withdrawals/{withdrawal_id}", headers=headers)

    def audit_withdrawal(self, withdrawal_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/withdrawals/{withdrawal_id}/audit", headers=headers)

    def list_withdrawals(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/withdrawals", headers=headers, params=params)

    # --- Beneficiary Changes ---
    def create_beneficiary_change(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/beneficiary-changes", payload, headers)

    def approve_beneficiary_change(self, change_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/beneficiary-changes/{change_id}/approve", payload, headers)

    def reject_beneficiary_change(self, change_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/beneficiary-changes/{change_id}/reject", {}, headers)

    def get_beneficiary_change(self, change_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/beneficiary-changes/{change_id}", headers=headers)

    def list_beneficiary_changes(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/beneficiary-changes", headers=headers, params=params)

    # --- State Tax Incentives ---
    def create_state_tax_incentive(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/state-tax-incentives", payload, headers)

    def calculate_state_tax_incentive(self, incentive_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/state-tax-incentives/{incentive_id}/calculate", {}, headers)

    def finalize_state_tax_incentive(self, incentive_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/state-tax-incentives/{incentive_id}/finalize", {}, headers)

    def get_state_tax_incentive(self, incentive_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/state-tax-incentives/{incentive_id}", headers=headers)

    def list_state_tax_incentives(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/state-tax-incentives", headers=headers, params=params)

    # --- Form 1099-Q ---
    def create_form_1099q(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/forms-1099q", payload, headers)

    def issue_form_1099q(self, form_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/forms-1099q/{form_id}/issue", {}, headers)

    def correct_form_1099q(self, form_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/forms-1099q/{form_id}/correct", {}, headers)

    def get_form_1099q(self, form_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/forms-1099q/{form_id}", headers=headers)

    def list_forms_1099q(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/forms-1099q", headers=headers, params=params)

    # --- Test-driving capabilities ---
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def get_clock(self, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", "/_clock", headers=headers)

    def credit_earnings(self, account_id: str, delta_cents: int, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST",
            "/_market/credit_earnings",
            {"account_id": account_id, "delta_cents": delta_cents},
            headers,
        )

    def scheduler_tick(self, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_scheduler/tick", {}, headers)


api_client = ApiClient()
