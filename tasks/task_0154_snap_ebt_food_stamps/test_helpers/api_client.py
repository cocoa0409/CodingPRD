"""API client: one method per endpoint defined in the SNAP/EBT PRD."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """SNAP/EBT Food Stamps API client."""

    # ------------------------------------------------------------------
    # Household endpoints
    # ------------------------------------------------------------------

    def create_household(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/households", payload, headers)

    def get_household(self, household_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/households/{household_id}", headers=headers)

    def list_households(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/households", headers=headers, params=params)

    def update_household(self, household_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/households/{household_id}", payload, headers)

    # ------------------------------------------------------------------
    # Member endpoints
    # ------------------------------------------------------------------

    def create_member(self, household_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/households/{household_id}/members", payload, headers)

    def get_member(self, household_id: str, member_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/households/{household_id}/members/{member_id}", headers=headers)

    def update_member(self, household_id: str, member_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/households/{household_id}/members/{member_id}", payload, headers)

    def deactivate_member(self, household_id: str, member_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/households/{household_id}/members/{member_id}/deactivate", headers=headers)

    # ------------------------------------------------------------------
    # Application endpoints
    # ------------------------------------------------------------------

    def create_application(self, household_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/households/{household_id}/applications", payload or {}, headers)

    def submit_application(self, household_id: str, app_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/households/{household_id}/applications/{app_id}/submit", headers=headers)

    def schedule_interview(self, household_id: str, app_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/households/{household_id}/applications/{app_id}/schedule-interview", headers=headers)

    def complete_interview(self, household_id: str, app_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/households/{household_id}/applications/{app_id}/complete-interview", headers=headers)

    def return_for_correction(self, household_id: str, app_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/households/{household_id}/applications/{app_id}/return-for-correction", headers=headers)

    def approve_application(self, household_id: str, app_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/households/{household_id}/applications/{app_id}/approve", headers=headers)

    def deny_application(self, household_id: str, app_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/households/{household_id}/applications/{app_id}/deny", payload, headers)

    def close_application(self, household_id: str, app_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/households/{household_id}/applications/{app_id}/close", headers=headers)

    # ------------------------------------------------------------------
    # EBT Card endpoints
    # ------------------------------------------------------------------

    def create_card(self, household_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/households/{household_id}/cards", payload or {}, headers)

    def activate_card(self, household_id: str, card_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/households/{household_id}/cards/{card_id}/activate", headers=headers)

    def suspend_card(self, household_id: str, card_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/households/{household_id}/cards/{card_id}/suspend", headers=headers)

    def resume_card(self, household_id: str, card_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/households/{household_id}/cards/{card_id}/resume", headers=headers)

    def replace_card(self, household_id: str, card_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/households/{household_id}/cards/{card_id}/replace", headers=headers)

    def get_card(self, household_id: str, card_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/households/{household_id}/cards/{card_id}", headers=headers)

    def get_card_ledger(self, household_id: str, card_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/households/{household_id}/cards/{card_id}/ledger", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Transaction endpoints
    # ------------------------------------------------------------------

    def create_transaction(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/transactions", payload, headers)

    def get_transaction(self, tx_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/transactions/{tx_id}", headers=headers)

    def list_transactions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/transactions", headers=headers, params=params)

    def reverse_transaction(self, tx_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/transactions/{tx_id}/reverse", headers=headers)

    # ------------------------------------------------------------------
    # Merchant endpoints
    # ------------------------------------------------------------------

    def create_merchant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/merchants", payload, headers)

    def update_merchant(self, merchant_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/merchants/{merchant_id}", payload, headers)

    def get_merchant(self, merchant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/merchants/{merchant_id}", headers=headers)

    # ------------------------------------------------------------------
    # Fraud Case endpoints
    # ------------------------------------------------------------------

    def create_fraud_case(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/fraud-cases", payload, headers)

    def assign_fraud_case(self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/fraud-cases/{case_id}/assign", payload, headers)

    def substantiate_fraud_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/fraud-cases/{case_id}/substantiate", headers=headers)

    def dismiss_fraud_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/fraud-cases/{case_id}/dismiss", headers=headers)

    def appeal_fraud_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/fraud-cases/{case_id}/appeal", headers=headers)

    def reopen_fraud_investigation(self, case_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/fraud-cases/{case_id}/reopen-investigation", headers=headers)

    def uphold_fraud_appeal(self, case_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/fraud-cases/{case_id}/uphold-appeal", headers=headers)

    def close_fraud_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/fraud-cases/{case_id}/close", headers=headers)

    def list_fraud_cases(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/fraud-cases", headers=headers, params=params)

    def get_fraud_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/fraud-cases/{case_id}", headers=headers)

    # ------------------------------------------------------------------
    # ABAWD Waiver endpoints
    # ------------------------------------------------------------------

    def create_abawd_waiver(self, household_id: str, member_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/households/{household_id}/members/{member_id}/abawd-waivers",
            payload,
            headers,
        )

    def approve_abawd_waiver(self, household_id: str, member_id: str, waiver_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/households/{household_id}/members/{member_id}/abawd-waivers/{waiver_id}/approve",
            headers=headers,
        )

    def reject_abawd_waiver(self, household_id: str, member_id: str, waiver_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/households/{household_id}/members/{member_id}/abawd-waivers/{waiver_id}/reject",
            payload,
            headers,
        )

    def get_abawd_waiver(self, household_id: str, member_id: str, waiver_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/households/{household_id}/members/{member_id}/abawd-waivers/{waiver_id}",
            headers=headers,
        )

    def list_abawd_waivers(self, household_id: str, member_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET",
            f"/households/{household_id}/members/{member_id}/abawd-waivers",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Emergency Allotment endpoints
    # ------------------------------------------------------------------

    def create_emergency_allotment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/emergency-allotments", payload, headers)

    def declare_emergency_allotment(self, ea_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/emergency-allotments/{ea_id}/declare", headers=headers)

    def disburse_emergency_allotment(self, ea_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/emergency-allotments/{ea_id}/disburse", headers=headers)

    def cancel_emergency_allotment(self, ea_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/emergency-allotments/{ea_id}/cancel", headers=headers)

    def get_emergency_allotment(self, ea_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/emergency-allotments/{ea_id}", headers=headers)

    def list_emergency_allotments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/emergency-allotments", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Test-driving endpoints (clock + sweep)
    # ------------------------------------------------------------------

    def advance_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", {"to_iso8601": to_iso8601}, headers)

    def run_sweep(self, headers: Dict[str, str]):
        return self._request("POST", "/_sweep/run", headers=headers)


api_client = ApiClient()
