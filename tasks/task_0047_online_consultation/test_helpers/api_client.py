"""API client: one method per endpoint defined in PRD §4.

Each method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID / X-User-Role on every call.

Endpoint paths are emitted verbatim with the PRD-declared `/consultation`
prefix.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


PREFIX = "/consultation"


class ApiClient(GenericApiClient):

    # ===================================================================
    # Patient (PRD §3.1, §4)
    # ===================================================================
    def create_patient(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/patients", payload, headers,
        )

    def get_patient(self, patient_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/patients/{patient_id}", headers=headers,
        )

    def patch_patient(self, patient_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "PATCH", f"{PREFIX}/patients/{patient_id}", payload, headers,
        )

    # ===================================================================
    # Doctor (PRD §3.1, §4)
    # ===================================================================
    def create_doctor(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/doctors", payload, headers,
        )

    def get_doctor(self, doctor_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/doctors/{doctor_id}", headers=headers,
        )

    def patch_doctor(self, doctor_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "PATCH", f"{PREFIX}/doctors/{doctor_id}", payload, headers,
        )

    def list_doctors(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{PREFIX}/doctors", headers=headers, params=params,
        )

    # ===================================================================
    # Pharmacist (PRD §3.1, §4)
    # ===================================================================
    def create_pharmacist(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/pharmacists", payload, headers,
        )

    def get_pharmacist(self, pharmacist_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/pharmacists/{pharmacist_id}", headers=headers,
        )

    # ===================================================================
    # DepartmentMapping (PRD §3.1, §4)
    # ===================================================================
    def create_department_mapping(self, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/department-mappings", payload, headers,
        )

    def list_department_mappings(self, headers: Dict[str, str],
                                 params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{PREFIX}/department-mappings",
            headers=headers, params=params,
        )

    # ===================================================================
    # TriageSession (PRD §3.2, §4)
    # ===================================================================
    def create_triage_session(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/triage-sessions", payload, headers,
        )

    def assess_triage_session(self, session_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{PREFIX}/triage-sessions/{session_id}/assess",
            payload or {}, headers,
        )

    def close_triage_session(self, session_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{PREFIX}/triage-sessions/{session_id}/close",
            payload or {}, headers,
        )

    def get_triage_session(self, session_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/triage-sessions/{session_id}",
            headers=headers,
        )

    # ===================================================================
    # Consultation (PRD §3.3 – §3.5, §4)
    # ===================================================================
    def create_consultation(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/consultations", payload, headers,
        )

    def accept_consultation(self, consultation_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/consultations/{consultation_id}/accept",
            payload or {}, headers,
        )

    def start_consultation(self, consultation_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/consultations/{consultation_id}/start",
            payload or {}, headers,
        )

    def quality_report(self, consultation_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/consultations/{consultation_id}/quality-report",
            payload, headers,
        )

    def complete_consultation(self, consultation_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/consultations/{consultation_id}/complete",
            payload or {}, headers,
        )

    def transfer_consultation(self, consultation_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/consultations/{consultation_id}/transfer",
            payload, headers,
        )

    def cancel_consultation(self, consultation_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "DELETE",
            f"{PREFIX}/consultations/{consultation_id}",
            headers=headers,
        )

    def get_consultation(self, consultation_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/consultations/{consultation_id}",
            headers=headers,
        )

    def list_consultations(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{PREFIX}/consultations",
            headers=headers, params=params,
        )

    def add_image_attachment(self, consultation_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/consultations/{consultation_id}/image-attachments",
            payload, headers,
        )

    # ===================================================================
    # Prescription (PRD §3.6, §4)
    # ===================================================================
    def create_prescription(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/prescriptions", payload, headers,
        )

    def submit_prescription(self, prescription_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/prescriptions/{prescription_id}/submit",
            payload or {}, headers,
        )

    def approve_prescription(self, prescription_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/prescriptions/{prescription_id}/approve",
            payload or {}, headers,
        )

    def reject_prescription(self, prescription_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/prescriptions/{prescription_id}/reject",
            payload, headers,
        )

    def revise_prescription(self, prescription_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/prescriptions/{prescription_id}/revise",
            payload or {}, headers,
        )

    def dispatch_prescription(self, prescription_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/prescriptions/{prescription_id}/dispatch",
            payload or {}, headers,
        )

    def get_prescription(self, prescription_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "GET",
            f"{PREFIX}/prescriptions/{prescription_id}",
            headers=headers,
        )

    def list_prescriptions(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{PREFIX}/prescriptions",
            headers=headers, params=params,
        )

    # ===================================================================
    # InsuranceClaim (PRD §3.7, §4)
    # ===================================================================
    def verify_eligibility(self, claim_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/insurance-claims/{claim_id}/verify-eligibility",
            payload, headers,
        )

    def settle_claim(self, claim_id: str,
                     headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/insurance-claims/{claim_id}/settle",
            payload or {}, headers,
        )

    def collect_self_pay(self, claim_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/insurance-claims/{claim_id}/collect-self-pay",
            payload or {}, headers,
        )

    def get_insurance_claim(self, claim_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/insurance-claims/{claim_id}",
            headers=headers,
        )

    # ===================================================================
    # FollowUpTask (PRD §3.8, §4)
    # ===================================================================
    def create_follow_up_task(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/follow-up-tasks", payload, headers,
        )

    def fire_reminder(self, task_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/follow-up-tasks/{task_id}/fire-reminder",
            payload or {}, headers,
        )

    def submit_follow_up_form(self, task_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/follow-up-tasks/{task_id}/submit-form",
            payload, headers,
        )

    def get_follow_up_task(self, task_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/follow-up-tasks/{task_id}",
            headers=headers,
        )

    # ===================================================================
    # Audit (PRD §3.9, §4)
    # ===================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{PREFIX}/audit-logs",
            headers=headers, params=params,
        )

    # ===================================================================
    # Test-driving endpoints (PRD §3.9, §4)
    # ===================================================================
    def advance_clock(self, seconds: int, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/_clock/advance",
            {"seconds": seconds}, headers,
        )

    def emit_event(self, kind: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/_events/emit",
            {"kind": kind, "payload": payload}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client", "PREFIX"]
