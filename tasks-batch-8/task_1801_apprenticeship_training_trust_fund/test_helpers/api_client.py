"""API client: one method per endpoint defined in PRD §4."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.11) ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers,
        )

    # --- trust funds ---
    def create_trust_fund(self, payload: Dict, headers: Dict):
        return self._request("POST", "/trust-funds", payload, headers)

    def get_trust_fund(self, fund_id: str, headers: Dict):
        return self._request("GET", f"/trust-funds/{fund_id}", headers=headers)

    def run_ops(self, fund_id: str, headers: Dict):
        return self._request("POST", f"/trust-funds/{fund_id}/run-ops", {}, headers)

    # --- employers ---
    def create_employer(self, payload: Dict, headers: Dict):
        return self._request("POST", "/employers", payload, headers)

    def get_employer(self, employer_id: str, headers: Dict):
        return self._request("GET", f"/employers/{employer_id}", headers=headers)

    def list_employers(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/employers", headers=headers, params=params)

    def update_employer(self, employer_id: str, payload: Dict, headers: Dict):
        return self._request("PATCH", f"/employers/{employer_id}", payload, headers)

    # --- apprentices ---
    def create_apprentice(self, payload: Dict, headers: Dict):
        return self._request("POST", "/apprentices", payload, headers)

    def get_apprentice(self, apprentice_id: str, headers: Dict):
        return self._request("GET", f"/apprentices/{apprentice_id}", headers=headers)

    def list_apprentices(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/apprentices", headers=headers, params=params)

    def indenture_apprentice(self, apprentice_id: str, headers: Dict):
        return self._request(
            "POST", f"/apprentices/{apprentice_id}/indenture", {}, headers,
        )

    def cancel_apprentice(self, apprentice_id: str, headers: Dict):
        return self._request(
            "POST", f"/apprentices/{apprentice_id}/cancel", {}, headers,
        )

    def certify_journeyman(self, apprentice_id: str, headers: Dict):
        return self._request(
            "POST", f"/apprentices/{apprentice_id}/certify-journeyman", {}, headers,
        )

    def submit_registration(self, apprentice_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/apprentices/{apprentice_id}/submit-registration",
            payload, headers,
        )

    def record_registration_decision(self, apprentice_id: str, payload: Dict,
                                     headers: Dict):
        return self._request(
            "POST", f"/apprentices/{apprentice_id}/record-registration-decision",
            payload, headers,
        )

    # --- contribution reports ---
    def create_contribution_report(self, payload: Dict, headers: Dict):
        return self._request("POST", "/contribution-reports", payload, headers)

    def get_contribution_report(self, report_id: str, headers: Dict):
        return self._request(
            "GET", f"/contribution-reports/{report_id}", headers=headers,
        )

    def list_contribution_reports(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/contribution-reports", headers=headers,
                             params=params)

    def submit_report(self, report_id: str, headers: Dict):
        return self._request(
            "POST", f"/contribution-reports/{report_id}/submit", {}, headers,
        )

    def flag_report(self, report_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/contribution-reports/{report_id}/flag", payload, headers,
        )

    def resubmit_report(self, report_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/contribution-reports/{report_id}/resubmit", payload, headers,
        )

    def remit_report(self, report_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/contribution-reports/{report_id}/remit", payload, headers,
        )

    # --- training classes ---
    def create_class(self, payload: Dict, headers: Dict):
        return self._request("POST", "/classes", payload, headers)

    def get_class(self, class_id: str, headers: Dict):
        return self._request("GET", f"/classes/{class_id}", headers=headers)

    def list_classes(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/classes", headers=headers, params=params)

    def complete_class(self, class_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/classes/{class_id}/complete", payload, headers,
        )

    def cancel_class(self, class_id: str, headers: Dict):
        return self._request("POST", f"/classes/{class_id}/cancel", {}, headers)

    # --- class enrollments ---
    def create_enrollment(self, payload: Dict, headers: Dict):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id: str, headers: Dict):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def drop_enrollment(self, enrollment_id: str, headers: Dict):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/drop", {}, headers,
        )

    # --- instructor pay claims ---
    def create_pay_claim(self, payload: Dict, headers: Dict):
        return self._request("POST", "/pay-claims", payload, headers)

    def get_pay_claim(self, claim_id: str, headers: Dict):
        return self._request("GET", f"/pay-claims/{claim_id}", headers=headers)

    def list_pay_claims(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/pay-claims", headers=headers, params=params)

    def approve_pay_claim(self, claim_id: str, headers: Dict):
        return self._request("POST", f"/pay-claims/{claim_id}/approve", {}, headers)

    def reject_pay_claim(self, claim_id: str, headers: Dict):
        return self._request("POST", f"/pay-claims/{claim_id}/reject", {}, headers)

    def pay_claim(self, claim_id: str, headers: Dict):
        return self._request("POST", f"/pay-claims/{claim_id}/pay", {}, headers)

    # --- funding allocations ---
    def create_funding_allocation(self, payload: Dict, headers: Dict):
        return self._request("POST", "/funding-allocations", payload, headers)

    def get_funding_allocation(self, allocation_id: str, headers: Dict):
        return self._request(
            "GET", f"/funding-allocations/{allocation_id}", headers=headers,
        )

    def list_funding_allocations(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/funding-allocations", headers=headers,
                             params=params)

    def approve_funding_allocation(self, allocation_id: str, payload: Dict,
                                   headers: Dict):
        return self._request(
            "POST", f"/funding-allocations/{allocation_id}/approve", payload, headers,
        )

    def reject_funding_allocation(self, allocation_id: str, headers: Dict):
        return self._request(
            "POST", f"/funding-allocations/{allocation_id}/reject", {}, headers,
        )

    def close_funding_allocation(self, allocation_id: str, headers: Dict):
        return self._request(
            "POST", f"/funding-allocations/{allocation_id}/close", {}, headers,
        )

    # --- equipment purchases ---
    def create_equipment_purchase(self, payload: Dict, headers: Dict):
        return self._request("POST", "/equipment-purchases", payload, headers)

    def get_equipment_purchase(self, purchase_id: str, headers: Dict):
        return self._request(
            "GET", f"/equipment-purchases/{purchase_id}", headers=headers,
        )

    def list_equipment_purchases(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/equipment-purchases", headers=headers,
                             params=params)

    def approve_equipment_purchase(self, purchase_id: str, headers: Dict):
        return self._request(
            "POST", f"/equipment-purchases/{purchase_id}/approve", {}, headers,
        )

    def deny_equipment_purchase(self, purchase_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/equipment-purchases/{purchase_id}/deny", payload, headers,
        )

    def cancel_equipment_purchase(self, purchase_id: str, headers: Dict):
        return self._request(
            "POST", f"/equipment-purchases/{purchase_id}/cancel", {}, headers,
        )

    def mark_purchased(self, purchase_id: str, headers: Dict):
        return self._request(
            "POST", f"/equipment-purchases/{purchase_id}/mark-purchased", {}, headers,
        )


api_client = ApiClient()
