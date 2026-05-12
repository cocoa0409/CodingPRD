"""ApiClient for the Mental Health Counseling Platform.

One method per endpoint listed in PRD §4. Each method delegates to the
inherited GenericApiClient._request() and returns the raw Response. Tests
pass headers in every call because PRD §2.1 requires X-User-ID / X-User-Role
on every request (except the public counselor catalogue browse).

API prefix is /counseling per PRD §4 paths.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


_PREFIX = "/counseling"


class ApiClient(GenericApiClient):
    # =====================================================================
    # Counselors (PRD §3.1)
    # =====================================================================
    def create_counselor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/counselors", payload, headers)

    def list_counselors(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{_PREFIX}/counselors", headers=headers, params=params)

    def get_counselor(self, counselor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{_PREFIX}/counselors/{counselor_id}", headers=headers)

    def update_counselor(self, counselor_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("PATCH", f"{_PREFIX}/counselors/{counselor_id}", payload, headers)

    def disqualify_counselor(self, counselor_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PREFIX}/counselors/{counselor_id}/disqualify",
            payload or {}, headers,
        )

    # =====================================================================
    # Clients (PRD §3.3)
    # =====================================================================
    def create_client(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/clients", payload, headers)

    def get_client(self, client_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{_PREFIX}/clients/{client_id}", headers=headers)

    def update_client(self, client_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("PATCH", f"{_PREFIX}/clients/{client_id}", payload, headers)

    def credit_package(self, client_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/clients/{client_id}/credit-package", payload, headers
        )

    def get_risk_summary(self, client_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{_PREFIX}/clients/{client_id}/risk-summary", headers=headers,
        )

    # =====================================================================
    # Certification cycles (PRD §3.2)
    # =====================================================================
    def create_certification_cycle(self, counselor_id: str, headers: Dict[str, str],
                                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PREFIX}/counselors/{counselor_id}/certification-cycles",
            payload or {}, headers,
        )

    def submit_certification_cycle(self, cycle_id: str, headers: Dict[str, str],
                                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PREFIX}/certification-cycles/{cycle_id}/submit",
            payload or {}, headers,
        )

    def approve_certification_cycle(self, cycle_id: str, headers: Dict[str, str],
                                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PREFIX}/certification-cycles/{cycle_id}/approve",
            payload or {}, headers,
        )

    def reject_certification_cycle(self, cycle_id: str, headers: Dict[str, str],
                                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PREFIX}/certification-cycles/{cycle_id}/reject",
            payload or {}, headers,
        )

    def list_certification_cycles(self, headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{_PREFIX}/certification-cycles", headers=headers, params=params,
        )

    # =====================================================================
    # Availability slots (PRD §3.4)
    # =====================================================================
    def create_availability_slot(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/availability-slots", payload, headers)

    def list_availability_slots(self, headers: Dict[str, str],
                                 params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{_PREFIX}/availability-slots", headers=headers, params=params,
        )

    def delete_availability_slot(self, slot_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE", f"{_PREFIX}/availability-slots/{slot_id}", headers=headers,
        )

    # =====================================================================
    # Appointments (PRD §3.4–§3.5)
    # =====================================================================
    def create_appointment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/appointments", payload, headers)

    def confirm_appointment(self, appointment_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PREFIX}/appointments/{appointment_id}/confirm",
            payload or {}, headers,
        )

    def get_refund_estimate(self, appointment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{_PREFIX}/appointments/{appointment_id}/refund-estimate",
            headers=headers,
        )

    def cancel_appointment(self, appointment_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PREFIX}/appointments/{appointment_id}/cancel",
            payload or {}, headers,
        )

    def reschedule_appointment(self, appointment_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/appointments/{appointment_id}/reschedule",
            payload, headers,
        )

    def start_appointment(self, appointment_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PREFIX}/appointments/{appointment_id}/start",
            payload or {}, headers,
        )

    def complete_appointment(self, appointment_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PREFIX}/appointments/{appointment_id}/complete",
            payload or {}, headers,
        )

    def list_appointments(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{_PREFIX}/appointments", headers=headers, params=params,
        )

    def get_appointment(self, appointment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{_PREFIX}/appointments/{appointment_id}", headers=headers,
        )

    # =====================================================================
    # Counseling records (encrypted) (PRD §3.6)
    # =====================================================================
    def create_counseling_record(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/counseling-records", payload, headers,
        )

    def get_counseling_record(self, record_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{_PREFIX}/counseling-records/{record_id}", headers=headers,
        )

    def export_counseling_record(self, record_id: str, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/counseling-records/{record_id}/export",
            payload, headers,
        )

    def list_counseling_records(self, headers: Dict[str, str],
                                 params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{_PREFIX}/counseling-records", headers=headers, params=params,
        )

    # =====================================================================
    # Crisis incidents (PRD §3.7)
    # =====================================================================
    def create_crisis_incident(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/crisis-incidents", payload, headers)

    def handover_crisis_incident(self, incident_id: str, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/crisis-incidents/{incident_id}/handover",
            payload, headers,
        )

    def notify_emergency(self, incident_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PREFIX}/crisis-incidents/{incident_id}/notify-emergency",
            payload or {}, headers,
        )

    def schedule_follow_up(self, incident_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PREFIX}/crisis-incidents/{incident_id}/schedule-follow-up",
            payload or {}, headers,
        )

    def resolve_crisis_incident(self, incident_id: str, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/crisis-incidents/{incident_id}/resolve",
            payload, headers,
        )

    def list_crisis_incidents(self, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{_PREFIX}/crisis-incidents", headers=headers, params=params,
        )

    # =====================================================================
    # Supervision & CE (PRD §3.10)
    # =====================================================================
    def create_supervision_session(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/supervision-sessions", payload, headers,
        )

    def approve_supervision_session(self, session_id: str, payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/supervision-sessions/{session_id}/approve",
            payload, headers,
        )

    def reject_supervision_session(self, session_id: str, headers: Dict[str, str],
                                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PREFIX}/supervision-sessions/{session_id}/reject",
            payload or {}, headers,
        )

    def list_supervision_sessions(self, headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{_PREFIX}/supervision-sessions", headers=headers, params=params,
        )

    def create_ce_record(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/ce-records", payload, headers)

    def approve_ce_record(self, record_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PREFIX}/ce-records/{record_id}/approve",
            payload or {}, headers,
        )

    def reject_ce_record(self, record_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PREFIX}/ce-records/{record_id}/reject",
            payload or {}, headers,
        )

    # =====================================================================
    # Settlement & payouts (PRD §3.8–§3.9)
    # =====================================================================
    def list_settlement_ledger(self, headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{_PREFIX}/settlement-ledger", headers=headers, params=params,
        )

    def create_payout(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/payouts", payload, headers)

    def mark_payout_paid(self, payout_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{_PREFIX}/payouts/{payout_id}/mark-paid",
            payload or {}, headers,
        )

    def reverse_payout(self, payout_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/payouts/{payout_id}/reverse",
            payload, headers,
        )

    def list_payouts(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{_PREFIX}/payouts", headers=headers, params=params,
        )

    # =====================================================================
    # Audit log (PRD §3.11)
    # =====================================================================
    def list_audit_log(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{_PREFIX}/audit-log", headers=headers, params=params,
        )

    # =====================================================================
    # Test-driving control endpoints (PRD §3.11)
    # =====================================================================
    def advance_clock(self, to_iso: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/_clock/advance", {"to": to_iso}, headers,
        )

    def sweep_holds(self, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/_sweep/holds", {}, headers)

    def sweep_no_show(self, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/_sweep/no-show", {}, headers)

    def sweep_recert(self, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/_sweep/recert", {}, headers)

    def sweep_retention(self, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/_sweep/retention", {}, headers)

    def sweep_risk(self, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/_sweep/risk", {}, headers)

    def emit_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/_events/emit", payload, headers)

    # =====================================================================
    # Test-only admin capabilities (extension of PRD §3.11
    # "admin-only test-driving capability" precedent).
    # =====================================================================
    def test_reset(self, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/_test/reset", {}, headers)

    def test_activate_counselor(self, counselor_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/_test/activate-counselor",
            {"counselor_id": counselor_id}, headers,
        )


api_client = ApiClient()
