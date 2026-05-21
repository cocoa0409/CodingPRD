"""API client: one method per endpoint defined in the PRD.

Subclass of GenericApiClient — the base `_request()` handles HTTP
plumbing. Endpoints follow PRD §4 verbatim.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ======================================================================
    # Employer — PRD §3.1, §4
    # ======================================================================
    def create_employer(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/employers", payload, headers)

    def get_employer(self, employer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/employers/{employer_id}", headers=headers,
        )

    # ======================================================================
    # Worksite — PRD §3.1, §4
    # ======================================================================
    def create_worksite(self, employer_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/employers/{employer_id}/worksites", payload, headers,
        )

    def patch_worksite(self, worksite_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/worksites/{worksite_id}", payload, headers,
        )

    # ======================================================================
    # Employee — PRD §3.1, §4
    # ======================================================================
    def create_employee(self, employer_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/employers/{employer_id}/employees", payload, headers,
        )

    def get_employee(self, employee_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/employees/{employee_id}", headers=headers,
        )

    def post_hours_snapshot(self, employee_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/employees/{employee_id}/hours-snapshot",
            payload, headers,
        )

    def get_eligibility_snapshot(self, employee_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "GET", f"/employees/{employee_id}/eligibility-snapshot",
            headers=headers,
        )

    def get_quota_balance(self, employee_id: str,
                          headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/employees/{employee_id}/quota-balance",
            headers=headers, params=params,
        )

    # ======================================================================
    # LeaveCase — PRD §3.3, §3.6, §3.10, §3.11, §4
    # ======================================================================
    def create_leave_case(self, employee_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/employees/{employee_id}/leave-cases",
            payload, headers,
        )

    def get_leave_case(self, leave_case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/leave-cases/{leave_case_id}", headers=headers,
        )

    def list_leave_cases(self, employee_id: str,
                         headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/employees/{employee_id}/leave-cases",
            headers=headers, params=params,
        )

    def review_leave_case(self, leave_case_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/leave-cases/{leave_case_id}/review",
            payload, headers,
        )

    def return_leave_case(self, leave_case_id: str,
                          payload: Optional[Dict[str, Any]],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/leave-cases/{leave_case_id}/return",
            payload, headers,
        )

    def restore_job(self, leave_case_id: str,
                    payload: Optional[Dict[str, Any]],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/leave-cases/{leave_case_id}/restore-job",
            payload, headers,
        )

    def cancel_leave_case(self, leave_case_id: str,
                          payload: Optional[Dict[str, Any]],
                          headers: Dict[str, str]):
        """PRD §2.4 routes optimistic-concurrency `version` through the
        request body for all mutating endpoints; PRD §3.11 states
        "Cancellation accepts an optional `version` for optimistic
        concurrency". The shared GenericApiClient._request maps DELETE
        payload onto query params, so we issue this DELETE directly
        with a JSON body to keep the request faithful to PRD §2.4."""
        url = f"{self.base_url}/leave-cases/{leave_case_id}"
        return self.session.request(
            "DELETE", url, headers=headers or {}, json=payload,
        )

    # ======================================================================
    # LeaveInstance — PRD §3.4, §4
    # ======================================================================
    def create_leave_instance(self, leave_case_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/leave-cases/{leave_case_id}/instances",
            payload, headers,
        )

    def void_leave_instance(self, leave_case_id: str, instance_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "DELETE",
            f"/leave-cases/{leave_case_id}/instances/{instance_id}",
            headers=headers,
        )

    # ======================================================================
    # MedicalCertification — PRD §3.5, §4
    # ======================================================================
    def create_certification(self, leave_case_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/leave-cases/{leave_case_id}/certifications",
            payload, headers,
        )

    def review_certification(self, leave_case_id: str, cert_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/leave-cases/{leave_case_id}/certifications/{cert_id}/review",
            payload, headers,
        )

    # ======================================================================
    # PfLClaim — PRD §3.8, §4
    # ======================================================================
    def create_pfl_claim(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", "/pfl-claims", payload, headers,
        )

    def get_pfl_claim(self, pfl_claim_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/pfl-claims/{pfl_claim_id}", headers=headers,
        )

    # ======================================================================
    # BenefitInvoice — PRD §3.9, §4
    # ======================================================================
    def list_benefit_invoices(self, leave_case_id: str,
                              headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/leave-cases/{leave_case_id}/benefit-invoices",
            headers=headers, params=params,
        )

    def pay_benefit_invoice(self, invoice_id: str,
                            payload: Optional[Dict[str, Any]],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/benefit-invoices/{invoice_id}/pay",
            payload, headers,
        )

    # ======================================================================
    # AuditEvent — PRD §2.9, §4
    # ======================================================================
    def list_audit_events(self, leave_case_id: str,
                          headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/leave-cases/{leave_case_id}/audit-events",
            headers=headers, params=params,
        )

    # ======================================================================
    # Test-driving clock — PRD §2.10, §4
    # ======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def health(self, headers: Optional[Dict[str, str]] = None):
        return self._request(
            "GET", "/_health", headers=headers,
        )


# Module-level singleton used by tests + fixtures.
api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
