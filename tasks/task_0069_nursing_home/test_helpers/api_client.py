"""API client: one method per endpoint defined in the PRD §4 endpoint table.

Each method delegates to ``GenericApiClient._request`` and returns the raw
Response object. Tests pass headers explicitly because the PRD requires
``X-User-ID`` and ``X-User-Role`` on every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Elders (PRD §3.1, §3.8, §4)
    # =======================================================================
    def create_elder(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/elders", payload, headers)

    def list_elders(self, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/elders", headers=headers, params=params)

    def get_elder(self, elder_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/elders/{elder_id}", headers=headers)

    def update_elder(self, elder_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("PATCH", f"/elders/{elder_id}", payload, headers)

    def deposit(self, elder_id: str, payload: Dict[str, Any],
                headers: Dict[str, str]):
        return self._request("POST", f"/elders/{elder_id}/deposit",
                             payload, headers)

    def admit_elder(self, elder_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", f"/elders/{elder_id}/admit",
                             payload, headers)

    def leave_elder(self, elder_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/elders/{elder_id}/leave",
                             payload or {}, headers)

    def return_elder(self, elder_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/elders/{elder_id}/return",
                             payload or {}, headers)

    def transfer_elder(self, elder_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", f"/elders/{elder_id}/transfer",
                             payload, headers)

    def discharge_elder(self, elder_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/elders/{elder_id}/discharge",
                             payload or {}, headers)

    # =======================================================================
    # Rooms / Beds (PRD §3.8, §4)
    # =======================================================================
    def create_room(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/rooms", payload, headers)

    def list_rooms(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/rooms", headers=headers, params=params)

    def create_bed(self, room_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request("POST", f"/rooms/{room_id}/beds",
                             payload, headers)

    def list_beds(self, headers: Dict[str, str],
                  params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/beds", headers=headers, params=params)

    def maintenance_bed(self, bed_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/beds/{bed_id}/maintenance",
                             payload or {}, headers)

    def maintenance_complete_bed(self, bed_id: str, headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/beds/{bed_id}/maintenance-complete",
                             payload or {}, headers)

    # =======================================================================
    # Waitlist (PRD §3.1, §4)
    # =======================================================================
    def create_waitlist_entry(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", "/waitlist", payload, headers)

    def list_waitlist(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/waitlist", headers=headers,
                             params=params)

    def decline_waitlist(self, entry_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/waitlist/{entry_id}/decline",
                             payload or {}, headers)

    def cancel_waitlist(self, entry_id: str, headers: Dict[str, str]):
        return self._request("DELETE", f"/waitlist/{entry_id}",
                             headers=headers)

    # =======================================================================
    # Care Assessments (PRD §3.2, §4)
    # =======================================================================
    def create_care_assessment(self, elder_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request("POST", f"/elders/{elder_id}/care-assessments",
                             payload, headers)

    def list_care_assessments(self, elder_id: str, headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/elders/{elder_id}/care-assessments",
                             headers=headers, params=params)

    def submit_care_assessment(self, assessment_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/care-assessments/{assessment_id}/submit",
            payload or {}, headers,
        )

    def approve_care_assessment(self, assessment_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/care-assessments/{assessment_id}/approve",
            payload or {}, headers,
        )

    def reject_care_assessment(self, assessment_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/care-assessments/{assessment_id}/reject",
            payload or {}, headers,
        )

    def return_care_assessment(self, assessment_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/care-assessments/{assessment_id}/return-for-revision",
            payload or {}, headers,
        )

    # =======================================================================
    # Care Plans (PRD §3.3, §4)
    # =======================================================================
    def create_care_plan(self, elder_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", f"/elders/{elder_id}/care-plans",
                             payload, headers)

    def get_care_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/care-plans/{plan_id}", headers=headers)

    def activate_care_plan(self, plan_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/care-plans/{plan_id}/activate",
                             payload or {}, headers)

    def flag_review_care_plan(self, plan_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/care-plans/{plan_id}/flag-review",
                             payload or {}, headers)

    def confirm_review_care_plan(self, plan_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/care-plans/{plan_id}/confirm-review",
                             payload or {}, headers)

    def supersede_care_plan(self, plan_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", f"/care-plans/{plan_id}/supersede",
                             payload, headers)

    def create_task_execution(self, plan_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST",
                             f"/care-plans/{plan_id}/task-executions",
                             payload, headers)

    def list_task_executions(self, plan_id: str, headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request("GET",
                             f"/care-plans/{plan_id}/task-executions",
                             headers=headers, params=params)

    # =======================================================================
    # Prescriptions / Medication (PRD §3.4, §3.5, §4)
    # =======================================================================
    def create_prescription(self, elder_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", f"/elders/{elder_id}/prescriptions",
                             payload, headers)

    def get_prescription(self, prescription_id: str,
                         headers: Dict[str, str]):
        return self._request("GET", f"/prescriptions/{prescription_id}",
                             headers=headers)

    def activate_prescription(self, prescription_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/prescriptions/{prescription_id}/activate",
            payload or {}, headers,
        )

    def suspend_prescription(self, prescription_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/prescriptions/{prescription_id}/suspend",
            payload or {}, headers,
        )

    def resume_prescription(self, prescription_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/prescriptions/{prescription_id}/resume",
            payload or {}, headers,
        )

    def discontinue_prescription(self, prescription_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/prescriptions/{prescription_id}/discontinue",
            payload or {}, headers,
        )

    def create_administration(self, prescription_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/prescriptions/{prescription_id}/administrations",
            payload, headers,
        )

    def list_administrations(self, prescription_id: str,
                             headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/prescriptions/{prescription_id}/administrations",
            headers=headers, params=params,
        )

    def create_medication_error(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", "/medication-errors", payload, headers)

    # =======================================================================
    # Visit Reservations / Epidemic (PRD §3.6, §4)
    # =======================================================================
    def create_visit_reservation(self, elder_id: str, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request("POST",
                             f"/elders/{elder_id}/visit-reservations",
                             payload, headers)

    def list_visit_reservations(self, elder_id: str,
                                headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request("GET",
                             f"/elders/{elder_id}/visit-reservations",
                             headers=headers, params=params)

    def check_in_visit(self, reservation_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/visit-reservations/{reservation_id}/check-in",
            payload, headers,
        )

    def check_out_visit(self, reservation_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/visit-reservations/{reservation_id}/check-out",
            payload or {}, headers,
        )

    def cancel_visit(self, reservation_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/visit-reservations/{reservation_id}",
            headers=headers,
        )

    def put_epidemic_config(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("PUT", "/epidemic-config", payload, headers)

    def get_epidemic_config(self, headers: Dict[str, str]):
        return self._request("GET", "/epidemic-config", headers=headers)

    # =======================================================================
    # Billing (PRD §3.7, §4)
    # =======================================================================
    def create_bill(self, elder_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", f"/elders/{elder_id}/bills",
                             payload, headers)

    def list_bills(self, elder_id: str, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/elders/{elder_id}/bills",
                             headers=headers, params=params)

    def get_bill(self, bill_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/bills/{bill_id}", headers=headers)

    def finalize_bill(self, bill_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/bills/{bill_id}/finalize",
                             payload or {}, headers)

    def pay_bill(self, bill_id: str, payload: Dict[str, Any],
                 headers: Dict[str, str]):
        return self._request("POST", f"/bills/{bill_id}/pay",
                             payload, headers)

    def adjust_bill(self, bill_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", f"/bills/{bill_id}/adjust",
                             payload, headers)

    def refund_bill(self, bill_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", f"/bills/{bill_id}/refund",
                             payload, headers)

    # =======================================================================
    # Audit / External Events / Operational (PRD §2.8, §2.10, §2.11, §4)
    # =======================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/audit-logs", headers=headers,
                             params=params)

    def ingest_external_event(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", "/_events/external", payload, headers)

    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def run_sweep(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", "/_sweep/run",
                             payload or {}, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
