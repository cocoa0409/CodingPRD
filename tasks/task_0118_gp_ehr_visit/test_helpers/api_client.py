"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the inherited _request() handles HTTP
plumbing. Headers are passed explicitly because PRD §2.1 requires both
X-User-ID and X-User-Role on every request (the two test-only
endpoints, /_clock/advance and /_sweep/run, are exempt per PRD §2.9).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Patients — PRD §3.1 / §4.
    # =======================================================================
    def create_patient(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/patients/{patient_id}", headers=headers,
        )

    def patch_patient(self, patient_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/patients/{patient_id}", payload, headers,
        )

    def list_patients(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/patients", headers=headers, params=params,
        )

    def bind_pcp(self, patient_id: str, payload: Dict[str, Any],
                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/patients/{patient_id}/bind-pcp", payload, headers,
        )

    def unbind_pcp(self, patient_id: str, headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/patients/{patient_id}/unbind-pcp",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Providers — PRD §3.2 / §4.
    # =======================================================================
    def create_provider(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/providers", payload, headers)

    def get_provider(self, provider_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/providers/{provider_id}", headers=headers,
        )

    def list_providers(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/providers", headers=headers, params=params,
        )

    # =======================================================================
    # Encounters — PRD §3.3 / §4.
    # =======================================================================
    def create_encounter(self, patient_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/patients/{patient_id}/encounters", payload, headers,
        )

    def get_encounter(self, encounter_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/encounters/{encounter_id}", headers=headers,
        )

    def patch_encounter(self, encounter_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/encounters/{encounter_id}", payload, headers,
        )

    def checkin_encounter(self, encounter_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/encounters/{encounter_id}/check-in",
            payload if payload is not None else {}, headers,
        )

    def complete_encounter(self, encounter_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/encounters/{encounter_id}/complete",
            payload if payload is not None else {}, headers,
        )

    def cancel_encounter(self, encounter_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/encounters/{encounter_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # CPT line items — PRD §3.3 / §4.
    # =======================================================================
    def create_cpt_line_item(self, encounter_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/encounters/{encounter_id}/cpt-line-items",
            payload, headers,
        )

    def delete_cpt_line_item(self, line_item_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/cpt-line-items/{line_item_id}", headers=headers,
        )

    # =======================================================================
    # CPT fee catalog — PRD §3.7 / §4.
    # =======================================================================
    def create_cpt_code(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/cpt-codes", payload, headers)

    def get_cpt_code(self, cpt_code: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/cpt-codes/{cpt_code}", headers=headers,
        )

    # =======================================================================
    # Prescriptions — PRD §3.4 / §4.
    # =======================================================================
    def create_prescription(self, patient_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/patients/{patient_id}/prescriptions", payload, headers,
        )

    def get_prescription(self, prescription_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "GET", f"/prescriptions/{prescription_id}", headers=headers,
        )

    def sign_prescription(self, prescription_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/prescriptions/{prescription_id}/sign",
            payload if payload is not None else {}, headers,
        )

    def transmit_prescription(self, prescription_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/prescriptions/{prescription_id}/transmit",
            payload if payload is not None else {}, headers,
        )

    def dispense_prescription(self, prescription_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/prescriptions/{prescription_id}/dispense",
            payload if payload is not None else {}, headers,
        )

    def cancel_prescription(self, prescription_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/prescriptions/{prescription_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Referrals — PRD §3.5 / §4.
    # =======================================================================
    def create_referral(self, patient_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/patients/{patient_id}/referrals", payload, headers,
        )

    def get_referral(self, referral_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/referrals/{referral_id}", headers=headers,
        )

    def accept_referral(self, referral_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/referrals/{referral_id}/accept",
            payload if payload is not None else {}, headers,
        )

    def reject_referral(self, referral_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/referrals/{referral_id}/reject",
            payload if payload is not None else {}, headers,
        )

    def return_referral_to_pcp(self, referral_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/referrals/{referral_id}/return-to-pcp",
            payload if payload is not None else {}, headers,
        )

    def complete_referral(self, referral_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/referrals/{referral_id}/complete",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Patient portal — PRD §3.6 / §4.
    # =======================================================================
    def create_portal_message(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", "/portal/messages", payload, headers,
        )

    def get_portal_message(self, message_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/portal/messages/{message_id}", headers=headers,
        )

    def mark_portal_message_read(self, message_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/portal-messages/{message_id}/mark-read",
            payload if payload is not None else {}, headers,
        )

    def archive_portal_message(self, message_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/portal-messages/{message_id}/archive",
            payload if payload is not None else {}, headers,
        )

    def triage_portal_message(self, message_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/portal-messages/{message_id}/triage",
            payload if payload is not None else {}, headers,
        )

    def escalate_portal_message(self, message_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/portal-messages/{message_id}/escalate",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # HEDIS — PRD §3.8 / §4.
    # =======================================================================
    def get_hedis_measurements(self, patient_id: str, year: int,
                               headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/hedis/measurements/{patient_id}/{year}",
            headers=headers, params=params,
        )

    def hedis_recompute(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", "/hedis/recompute", payload, headers,
        )

    # =======================================================================
    # Audit — PRD §3.9 / §4.
    # =======================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-logs", headers=headers, params=params,
        )

    # =======================================================================
    # Test-only — PRD §2.9 / §3.9 / §4. Exempt from auth header check.
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Optional[Dict[str, str]] = None):
        return self._request(
            "POST", "/_clock/advance", payload,
            headers if headers is not None else {},
        )

    def sweep_run(self, headers: Optional[Dict[str, str]] = None,
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/run",
            payload if payload is not None else {},
            headers if headers is not None else {},
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
