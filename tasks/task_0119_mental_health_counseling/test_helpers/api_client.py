"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the inherited _request() handles HTTP
plumbing. Headers are passed explicitly because PRD §2.1 requires both
X-User-ID and X-User-Role on every request.

PRD §1: "All endpoints are mounted under the URL prefix /practice."
Every path below carries that prefix verbatim.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Therapists — PRD §3.1 / §3.2 / §4.
    # =======================================================================
    def create_therapist(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/practice/therapists", payload, headers)

    def get_therapist(self, therapist_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/practice/therapists/{therapist_id}", headers=headers,
        )

    def list_therapists(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/practice/therapists", headers=headers, params=params,
        )

    def patch_therapist(self, therapist_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/practice/therapists/{therapist_id}", payload, headers,
        )

    def activate_therapist(self, therapist_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/practice/therapists/{therapist_id}/activate",
            payload if payload is not None else {}, headers,
        )

    def suspend_therapist(self, therapist_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/practice/therapists/{therapist_id}/suspend",
            payload if payload is not None else {}, headers,
        )

    def reinstate_therapist(self, therapist_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/practice/therapists/{therapist_id}/reinstate",
            payload if payload is not None else {}, headers,
        )

    def deactivate_therapist(self, therapist_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/practice/therapists/{therapist_id}/deactivate",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # StateLicenses — PRD §3.1 / §4.
    # =======================================================================
    def create_state_license(self, therapist_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/practice/therapists/{therapist_id}/licenses",
            payload, headers,
        )

    def verify_state_license(self, therapist_id: str, license_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/practice/therapists/{therapist_id}/licenses/"
            f"{license_id}/verify",
            payload if payload is not None else {}, headers,
        )

    def revoke_state_license(self, therapist_id: str, license_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/practice/therapists/{therapist_id}/licenses/"
            f"{license_id}/revoke",
            payload if payload is not None else {}, headers,
        )

    def list_state_licenses(self, therapist_id: str,
                            headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/practice/therapists/{therapist_id}/licenses",
            headers=headers, params=params,
        )

    # =======================================================================
    # Supervisors + SupervisionAssignments — PRD §3.3 / §4.
    # =======================================================================
    def create_supervisor(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", "/practice/supervisors", payload, headers,
        )

    def get_supervisor(self, supervisor_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/practice/supervisors/{supervisor_id}", headers=headers,
        )

    def create_supervision_assignment(self, payload: Dict[str, Any],
                                      headers: Dict[str, str]):
        return self._request(
            "POST", "/practice/supervision-assignments", payload, headers,
        )

    def terminate_supervision_assignment(self, assignment_id: str,
                                         headers: Dict[str, str],
                                         payload: Optional[
                                             Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/practice/supervision-assignments/{assignment_id}/terminate",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Patients — PRD §3.4 / §4.
    # =======================================================================
    def create_patient(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/practice/patients", payload, headers)

    def get_patient(self, patient_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/practice/patients/{patient_id}", headers=headers,
        )

    def patch_patient(self, patient_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/practice/patients/{patient_id}", payload, headers,
        )

    # =======================================================================
    # InsurancePlans — PRD §3.5 / §4.
    # =======================================================================
    def create_insurance_plan(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", "/practice/insurance-plans", payload, headers,
        )

    def get_insurance_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/practice/insurance-plans/{plan_id}", headers=headers,
        )

    # =======================================================================
    # Appointments — PRD §3.6 / §4.
    # =======================================================================
    def create_appointment(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", "/practice/appointments", payload, headers,
        )

    def get_appointment(self, appointment_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/practice/appointments/{appointment_id}",
            headers=headers,
        )

    def patch_appointment(self, appointment_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/practice/appointments/{appointment_id}",
            payload, headers,
        )

    def checkin_appointment(self, appointment_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/practice/appointments/{appointment_id}/check-in",
            payload if payload is not None else {}, headers,
        )

    def cancel_appointment(self, appointment_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/practice/appointments/{appointment_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    def mark_no_show_appointment(self, appointment_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[
                                     Dict[str, Any]] = None):
        return self._request(
            "POST", f"/practice/appointments/{appointment_id}/mark-no-show",
            payload if payload is not None else {}, headers,
        )

    def create_session(self, appointment_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/practice/appointments/{appointment_id}/sessions",
            payload, headers,
        )

    def list_appointments(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/practice/appointments", headers=headers, params=params,
        )

    # =======================================================================
    # Sessions — PRD §3.7 / §4.
    # =======================================================================
    def complete_session(self, session_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/practice/sessions/{session_id}/complete",
            payload if payload is not None else {}, headers,
        )

    def void_session(self, session_id: str,
                     headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/practice/sessions/{session_id}/void",
            payload if payload is not None else {}, headers,
        )

    def get_session(self, session_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/practice/sessions/{session_id}", headers=headers,
        )

    # =======================================================================
    # BillingClaims — PRD §3.7 / §3.8 / §4.
    # =======================================================================
    def get_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/practice/claims/{claim_id}", headers=headers,
        )

    def void_claim(self, claim_id: str, headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/practice/claims/{claim_id}/void",
            payload if payload is not None else {}, headers,
        )

    def list_claims(self, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/practice/claims", headers=headers, params=params,
        )

    # =======================================================================
    # CrisisAssessments + SafetyPlans — PRD §3.9 / §4.
    # =======================================================================
    def create_crisis_assessment(self, patient_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/practice/patients/{patient_id}/crisis-assessments",
            payload, headers,
        )

    def list_crisis_assessments(self, patient_id: str,
                                headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/practice/patients/{patient_id}/crisis-assessments",
            headers=headers, params=params,
        )

    def create_safety_plan(self, patient_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/practice/patients/{patient_id}/safety-plans",
            payload, headers,
        )

    def rescind_safety_plan(self, plan_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/practice/safety-plans/{plan_id}/rescind",
            payload if payload is not None else {}, headers,
        )

    def list_safety_plans(self, patient_id: str,
                          headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/practice/patients/{patient_id}/safety-plans",
            headers=headers, params=params,
        )

    # =======================================================================
    # Deterministic clock — PRD §2.8 / §4.
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/practice/_clock/advance", payload, headers,
        )

    def get_clock(self, headers: Dict[str, str]):
        return self._request(
            "GET", "/practice/_clock", headers=headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
