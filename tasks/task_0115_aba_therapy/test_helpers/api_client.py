"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-Role and X-User-ID on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Clock — PRD §2.5
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    # =======================================================================
    # Clinic — PRD §3.1
    # =======================================================================
    def create_clinic(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/clinics", payload, headers)

    def get_clinic(self, clinic_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/clinics/{clinic_id}", headers=headers,
        )

    # =======================================================================
    # Patient — PRD §3.1
    # =======================================================================
    def create_patient(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/patients", payload, headers)

    def list_patients(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/patients", headers=headers, params=params,
        )

    def get_patient(self, patient_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/patients/{patient_id}", headers=headers,
        )

    # =======================================================================
    # Therapist — PRD §3.1
    # =======================================================================
    def create_therapist(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/therapists", payload, headers)

    def get_therapist(self, therapist_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/therapists/{therapist_id}", headers=headers,
        )

    # =======================================================================
    # DiagnosticEvaluation — PRD §3.2
    # =======================================================================
    def create_evaluation(self, patient_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/patients/{patient_id}/evaluations", payload, headers,
        )

    def start_evaluation(self, evaluation_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/evaluations/{evaluation_id}/start", {}, headers,
        )

    def complete_evaluation(self, evaluation_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/evaluations/{evaluation_id}/complete",
            payload, headers,
        )

    def void_evaluation(self, evaluation_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/evaluations/{evaluation_id}/void", {}, headers,
        )

    # =======================================================================
    # TreatmentPlan — PRD §3.3
    # =======================================================================
    def create_treatment_plan(self, patient_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/patients/{patient_id}/treatment-plans",
            payload, headers,
        )

    def activate_treatment_plan(self, plan_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/treatment-plans/{plan_id}/activate", {}, headers,
        )

    def supersede_treatment_plan(self, plan_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/treatment-plans/{plan_id}/supersede",
            payload, headers,
        )

    def list_treatment_plans(self, patient_id: str,
                             headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/patients/{patient_id}/treatment-plans",
            headers=headers, params=params,
        )

    # =======================================================================
    # Authorization — PRD §3.4
    # =======================================================================
    def create_authorization(self, patient_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/patients/{patient_id}/authorizations",
            payload, headers,
        )

    def approve_authorization(self, authorization_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/authorizations/{authorization_id}/approve",
            {}, headers,
        )

    def deny_authorization(self, authorization_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/authorizations/{authorization_id}/deny",
            {}, headers,
        )

    def get_authorization(self, authorization_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET", f"/authorizations/{authorization_id}", headers=headers,
        )

    def get_supervision_ratio(self, authorization_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/authorizations/{authorization_id}/supervision-ratio",
            headers=headers,
        )

    def list_authorization_ledger(self, authorization_id: str,
                                  headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/authorizations/{authorization_id}/ledger",
            headers=headers, params=params,
        )

    # =======================================================================
    # TherapySession — PRD §3.5
    # =======================================================================
    def create_session(self, patient_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/patients/{patient_id}/sessions", payload, headers,
        )

    def start_session(self, session_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/sessions/{session_id}/start", {}, headers,
        )

    def complete_session(self, session_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/sessions/{session_id}/complete", payload, headers,
        )

    def dispute_session(self, session_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/sessions/{session_id}/dispute", payload, headers,
        )

    def resolve_session_dispute(self, session_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/sessions/{session_id}/resolve-dispute", {}, headers,
        )

    def cancel_session(self, session_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/sessions/{session_id}/cancel", {}, headers,
        )

    def list_patient_sessions(self, patient_id: str,
                              headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/patients/{patient_id}/sessions",
            headers=headers, params=params,
        )

    # =======================================================================
    # InsuranceClaim — PRD §3.6
    # =======================================================================
    def create_claim(self, patient_id: str,
                     payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/patients/{patient_id}/claims", payload, headers,
        )

    def submit_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/claims/{claim_id}/submit", {}, headers,
        )

    def adjudicate_claim(self, claim_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/claims/{claim_id}/adjudicate", payload, headers,
        )

    def pay_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/claims/{claim_id}/pay", {}, headers,
        )

    def deny_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/claims/{claim_id}/deny", {}, headers,
        )

    def appeal_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/claims/{claim_id}/appeal", {}, headers,
        )

    def list_patient_claims(self, patient_id: str,
                            headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/patients/{patient_id}/claims",
            headers=headers, params=params,
        )

    def get_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/claims/{claim_id}", headers=headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
