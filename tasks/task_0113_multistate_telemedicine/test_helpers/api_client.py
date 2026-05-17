"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Every endpoint is mounted under /telemed per PRD §4. Tests
pass headers explicitly because PRD §2.1 requires X-User-Role and
X-User-ID on every request (except the two test-driving utilities).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Physicians & licensure — PRD §4
    # =======================================================================
    def create_physician(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/telemed/physicians", payload, headers)

    def get_physician(self, physician_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/telemed/physicians/{physician_id}", headers=headers,
        )

    def list_physicians(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/telemed/physicians",
            headers=headers, params=params,
        )

    def create_state_license(self, physician_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/telemed/physicians/{physician_id}/licenses",
            payload, headers,
        )

    def list_state_licenses(self, physician_id: str,
                            headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/telemed/physicians/{physician_id}/licenses",
            headers=headers, params=params,
        )

    def revoke_state_license(self, physician_id: str, license_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/telemed/physicians/{physician_id}/licenses/"
            f"{license_id}/revoke",
            {}, headers,
        )

    def get_physician_compliance(self, physician_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "GET", f"/telemed/physicians/{physician_id}/compliance",
            headers=headers,
        )

    # =======================================================================
    # Patients — PRD §4
    # =======================================================================
    def create_patient(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/telemed/patients", payload, headers)

    def get_patient(self, patient_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/telemed/patients/{patient_id}", headers=headers,
        )

    def patch_patient(self, patient_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/telemed/patients/{patient_id}", payload, headers,
        )

    # =======================================================================
    # Consults — PRD §4
    # =======================================================================
    def create_consult(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/telemed/consults", payload, headers)

    def get_consult(self, consult_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/telemed/consults/{consult_id}", headers=headers,
        )

    def list_consults(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/telemed/consults",
            headers=headers, params=params,
        )

    def route_consult(self, consult_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/telemed/consults/{consult_id}/route",
            payload, headers,
        )

    def decline_consult(self, consult_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/telemed/consults/{consult_id}/decline",
            payload, headers,
        )

    def unroute_consult(self, consult_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/telemed/consults/{consult_id}/unroute",
            payload, headers,
        )

    def start_consult(self, consult_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/telemed/consults/{consult_id}/start",
            payload, headers,
        )

    def complete_consult(self, consult_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/telemed/consults/{consult_id}/complete",
            payload, headers,
        )

    def close_consult(self, consult_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/telemed/consults/{consult_id}/close",
            payload, headers,
        )

    # =======================================================================
    # Prescriptions — PRD §4
    # =======================================================================
    def create_prescription(self, consult_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/telemed/consults/{consult_id}/prescriptions",
            payload, headers,
        )

    def patch_prescription(self, prescription_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/telemed/prescriptions/{prescription_id}",
            payload, headers,
        )

    def issue_prescription(self, prescription_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/telemed/prescriptions/{prescription_id}/issue",
            payload, headers,
        )

    def transmit_prescription(self, prescription_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/telemed/prescriptions/{prescription_id}/transmit",
            payload, headers,
        )

    def mark_dispensed_prescription(self, prescription_id: str,
                                    payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/telemed/prescriptions/{prescription_id}/mark-dispensed",
            payload, headers,
        )

    def void_prescription(self, prescription_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/telemed/prescriptions/{prescription_id}/void",
            payload, headers,
        )

    # =======================================================================
    # InsuranceClaim — PRD §4
    # =======================================================================
    def get_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/telemed/claims/{claim_id}", headers=headers,
        )

    def approve_claim(self, claim_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/telemed/claims/{claim_id}/approve",
            payload, headers,
        )

    def deny_claim(self, claim_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/telemed/claims/{claim_id}/deny",
            payload, headers,
        )

    def appeal_claim(self, claim_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/telemed/claims/{claim_id}/appeal",
            payload, headers,
        )

    def mark_paid_claim(self, claim_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/telemed/claims/{claim_id}/mark-paid",
            payload, headers,
        )

    # =======================================================================
    # SelfPayInvoice — PRD §4
    # =======================================================================
    def get_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/telemed/invoices/{invoice_id}", headers=headers,
        )

    def mark_paid_invoice(self, invoice_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/telemed/invoices/{invoice_id}/mark-paid",
            payload, headers,
        )

    # =======================================================================
    # FollowUp — PRD §4
    # =======================================================================
    def get_followup(self, followup_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/telemed/followups/{followup_id}", headers=headers,
        )

    def complete_followup(self, followup_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/telemed/followups/{followup_id}/complete",
            payload, headers,
        )

    def cancel_followup(self, followup_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/telemed/followups/{followup_id}/cancel",
            payload, headers,
        )

    # =======================================================================
    # Test-driving utilities — PRD §2.9, §3.7
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/telemed/_clock/advance", payload, headers,
        )

    def sweep_run(self, headers: Dict[str, str]):
        return self._request(
            "POST", "/telemed/_sweep/run", {}, headers,
        )

    # =======================================================================
    # Audit trail — PRD §2.10
    # =======================================================================
    def list_audit_events(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/telemed/audit-events",
            headers=headers, params=params,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
