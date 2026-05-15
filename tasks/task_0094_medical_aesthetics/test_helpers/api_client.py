"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles the
HTTP plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Projects (PRD §3.1)
    # =======================================================================
    def create_project(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/aesthetics/projects", payload, headers)

    def patch_project(self, project_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/aesthetics/projects/{project_id}", payload, headers,
        )

    def submit_project(self, project_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/aesthetics/projects/{project_id}/submit", {}, headers,
        )

    def approve_project(self, project_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/aesthetics/projects/{project_id}/approve", {}, headers,
        )

    def reject_project(self, project_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/aesthetics/projects/{project_id}/reject", {}, headers,
        )

    def take_project_off_shelf(self, project_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/aesthetics/projects/{project_id}/take-off-shelf",
            {}, headers,
        )

    def return_project_to_shelf(self, project_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/aesthetics/projects/{project_id}/return-to-shelf",
            {}, headers,
        )

    def get_project(self, project_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/aesthetics/projects/{project_id}", headers=headers,
        )

    def list_projects(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/aesthetics/projects", headers=headers, params=params,
        )

    # =======================================================================
    # ContraindicationRules (PRD §3.1)
    # =======================================================================
    def create_contraindication_rule(self, project_id: str,
                                     payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/aesthetics/projects/{project_id}/contraindication-rules",
            payload, headers,
        )

    def list_contraindication_rules(self, project_id: str,
                                    headers: Dict[str, str],
                                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/aesthetics/projects/{project_id}/contraindication-rules",
            headers=headers, params=params,
        )

    # =======================================================================
    # Consumable SKUs (PRD §3.1)
    # =======================================================================
    def create_consumable_sku(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", "/aesthetics/consumable-skus", payload, headers,
        )

    def list_consumable_skus(self, headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/aesthetics/consumable-skus",
            headers=headers, params=params,
        )

    # =======================================================================
    # Rooms (PRD §3.1)
    # =======================================================================
    def create_room(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/aesthetics/rooms", payload, headers)

    def list_rooms(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/aesthetics/rooms", headers=headers, params=params,
        )

    # =======================================================================
    # Customers (PRD §3.2)
    # =======================================================================
    def create_customer(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", "/aesthetics/customers", payload, headers,
        )

    def patch_customer(self, customer_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/aesthetics/customers/{customer_id}", payload, headers,
        )

    def submit_kyc(self, customer_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/aesthetics/customers/{customer_id}/kyc",
            payload, headers,
        )

    def get_customer(self, customer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/aesthetics/customers/{customer_id}", headers=headers,
        )

    # =======================================================================
    # TreatmentPlans (PRD §3.3)
    # =======================================================================
    def create_plan(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/aesthetics/plans", payload, headers)

    def patch_plan(self, plan_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/aesthetics/plans/{plan_id}", payload, headers,
        )

    def submit_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/aesthetics/plans/{plan_id}/submit", {}, headers,
        )

    def sign_consent(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/aesthetics/plans/{plan_id}/sign-consent",
            {}, headers,
        )

    def approve_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/aesthetics/plans/{plan_id}/approve", {}, headers,
        )

    def countersign_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/aesthetics/plans/{plan_id}/countersign",
            {}, headers,
        )

    def reject_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/aesthetics/plans/{plan_id}/reject", {}, headers,
        )

    def return_plan_to_draft(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/aesthetics/plans/{plan_id}/return-to-draft",
            {}, headers,
        )

    def cancel_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/aesthetics/plans/{plan_id}/cancel", {}, headers,
        )

    def get_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/aesthetics/plans/{plan_id}", headers=headers,
        )

    def list_plans(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/aesthetics/plans", headers=headers, params=params,
        )

    # =======================================================================
    # Appointments (PRD §3.4)
    # =======================================================================
    def create_appointment(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", "/aesthetics/appointments", payload, headers,
        )

    def reschedule_appointment(self, appointment_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/aesthetics/appointments/{appointment_id}/reschedule",
            payload, headers,
        )

    def cancel_appointment(self, appointment_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/aesthetics/appointments/{appointment_id}/cancel",
            {}, headers,
        )

    def check_in_appointment(self, appointment_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/aesthetics/appointments/{appointment_id}/check-in",
            {}, headers,
        )

    def op_record_start(self, appointment_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/aesthetics/appointments/{appointment_id}/op-records/start",
            {}, headers,
        )

    def op_record_key_step(self, appointment_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/aesthetics/appointments/{appointment_id}/op-records/key-step",
            payload, headers,
        )

    def op_record_consumables(self, appointment_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/aesthetics/appointments/{appointment_id}/op-records/consumables",
            payload, headers,
        )

    def op_record_vitals(self, appointment_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/aesthetics/appointments/{appointment_id}/op-records/vitals",
            payload, headers,
        )

    def op_record_incidents(self, appointment_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/aesthetics/appointments/{appointment_id}/op-records/incidents",
            payload, headers,
        )

    def op_record_end(self, appointment_id: str,
                      payload: Optional[Dict[str, Any]],
                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/aesthetics/appointments/{appointment_id}/op-records/end",
            payload if payload is not None else {}, headers,
        )

    def get_appointment(self, appointment_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/aesthetics/appointments/{appointment_id}",
            headers=headers,
        )

    def list_appointments(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/aesthetics/appointments",
            headers=headers, params=params,
        )

    # =======================================================================
    # FollowUps (PRD §3.6)
    # =======================================================================
    def remind_followup(self, followup_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/aesthetics/followups/{followup_id}/remind",
            {}, headers,
        )

    def submit_followup_feedback(self, followup_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/aesthetics/followups/{followup_id}/feedback",
            payload, headers,
        )

    def get_followup(self, followup_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/aesthetics/followups/{followup_id}",
            headers=headers,
        )

    def list_followups(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/aesthetics/followups",
            headers=headers, params=params,
        )

    # =======================================================================
    # AdverseEvents (PRD §3.6)
    # =======================================================================
    def file_adverse_event(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", "/aesthetics/adverse-events", payload, headers,
        )

    def escalate_adverse_event(self, ae_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/aesthetics/adverse-events/{ae_id}/escalate",
            {}, headers,
        )

    def close_adverse_event(self, ae_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/aesthetics/adverse-events/{ae_id}/close",
            {}, headers,
        )

    def list_adverse_events(self, headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/aesthetics/adverse-events",
            headers=headers, params=params,
        )

    # =======================================================================
    # InstallmentPlans (PRD §3.7)
    # =======================================================================
    def create_installment(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", "/aesthetics/installments", payload, headers,
        )

    def activate_installment(self, installment_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/aesthetics/installments/{installment_id}/activate",
            {}, headers,
        )

    def pay_installment(self, installment_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/aesthetics/installments/{installment_id}/payments",
            payload, headers,
        )

    def refund_installment_medical_event(self, installment_id: str,
                                         payload: Dict[str, Any],
                                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/aesthetics/installments/{installment_id}/refund-medical-event",
            payload, headers,
        )

    def get_installment(self, installment_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/aesthetics/installments/{installment_id}",
            headers=headers,
        )

    def list_installments(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/aesthetics/installments",
            headers=headers, params=params,
        )

    # =======================================================================
    # Audit + sync events (PRD §3.8)
    # =======================================================================
    def list_audit_entries(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/aesthetics/audit-entries",
            headers=headers, params=params,
        )

    def list_sync_events(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/aesthetics/sync-events",
            headers=headers, params=params,
        )

    # =======================================================================
    # Test-clock (PRD §2.10)
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
