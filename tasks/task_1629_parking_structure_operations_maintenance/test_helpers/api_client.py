"""API client: one method per endpoint defined in the PRD (all under /ops)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (FacilityManager-only test-driving capability)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/ops/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Facilities
    # ------------------------------------------------------------------
    def create_facility(self, payload, headers):
        return self._request("POST", "/ops/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/ops/facilities/{facility_id}", headers=headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/ops/facilities", headers=headers, params=params)

    def transition_posture(self, facility_id, target_posture, headers):
        return self._request("POST", f"/ops/facilities/{facility_id}/transition-posture",
                             {"target_posture": target_posture}, headers)

    def close_of_business(self, facility_id, headers):
        return self._request("POST", f"/ops/facilities/{facility_id}/close-of-business",
                             {}, headers)

    def get_facility_dashboard(self, facility_id, headers):
        return self._request("GET", f"/ops/facilities/{facility_id}/dashboard",
                             headers=headers)

    # ------------------------------------------------------------------
    # Rate schedules
    # ------------------------------------------------------------------
    def create_rate_schedule(self, payload, headers):
        return self._request("POST", "/ops/rate-schedules", payload, headers)

    def get_rate_schedule(self, rate_schedule_id, headers):
        return self._request("GET", f"/ops/rate-schedules/{rate_schedule_id}", headers=headers)

    def list_rate_schedules(self, headers, params=None):
        return self._request("GET", "/ops/rate-schedules", headers=headers, params=params)

    def publish_rate_schedule(self, rate_schedule_id, expected_facility_version, headers):
        return self._request("POST", f"/ops/rate-schedules/{rate_schedule_id}/publish",
                             {"expected_facility_version": expected_facility_version}, headers)

    def retire_rate_schedule(self, rate_schedule_id, headers):
        return self._request("POST", f"/ops/rate-schedules/{rate_schedule_id}/retire",
                             {}, headers)

    # ------------------------------------------------------------------
    # Access devices
    # ------------------------------------------------------------------
    def create_access_device(self, payload, headers):
        return self._request("POST", "/ops/access-devices", payload, headers)

    def get_access_device(self, access_device_id, headers):
        return self._request("GET", f"/ops/access-devices/{access_device_id}", headers=headers)

    def list_access_devices(self, headers, params=None):
        return self._request("GET", "/ops/access-devices", headers=headers, params=params)

    def heartbeat_device(self, access_device_id, headers):
        return self._request("POST", f"/ops/access-devices/{access_device_id}/heartbeat",
                             {}, headers)

    def report_device_fault(self, access_device_id, fault_description, headers):
        return self._request("POST", f"/ops/access-devices/{access_device_id}/report-fault",
                             {"fault_description": fault_description}, headers)

    def decommission_device(self, access_device_id, headers):
        return self._request("POST", f"/ops/access-devices/{access_device_id}/decommission",
                             {}, headers)

    # ------------------------------------------------------------------
    # Parker accounts
    # ------------------------------------------------------------------
    def create_parker_account(self, payload, headers):
        return self._request("POST", "/ops/parker-accounts", payload, headers)

    def get_parker_account(self, parker_account_id, headers):
        return self._request("GET", f"/ops/parker-accounts/{parker_account_id}", headers=headers)

    def list_parker_accounts(self, headers, params=None):
        return self._request("GET", "/ops/parker-accounts", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Monthly agreements
    # ------------------------------------------------------------------
    def create_monthly_agreement(self, payload, headers):
        return self._request("POST", "/ops/monthly-agreements", payload, headers)

    def get_monthly_agreement(self, monthly_agreement_id, headers):
        return self._request("GET", f"/ops/monthly-agreements/{monthly_agreement_id}",
                             headers=headers)

    def list_monthly_agreements(self, headers, params=None):
        return self._request("GET", "/ops/monthly-agreements", headers=headers, params=params)

    def activate_agreement(self, monthly_agreement_id, headers):
        return self._request("POST", f"/ops/monthly-agreements/{monthly_agreement_id}/activate",
                             {}, headers)

    def suspend_agreement(self, monthly_agreement_id, headers):
        return self._request("POST", f"/ops/monthly-agreements/{monthly_agreement_id}/suspend",
                             {}, headers)

    def resume_agreement(self, monthly_agreement_id, headers):
        return self._request("POST", f"/ops/monthly-agreements/{monthly_agreement_id}/resume",
                             {}, headers)

    def terminate_agreement(self, monthly_agreement_id, headers):
        return self._request("POST", f"/ops/monthly-agreements/{monthly_agreement_id}/terminate",
                             {}, headers)

    def amend_agreement(self, monthly_agreement_id, payload, headers):
        return self._request("POST", f"/ops/monthly-agreements/{monthly_agreement_id}/amend",
                             payload, headers)

    def withdraw_agreement(self, monthly_agreement_id, headers):
        return self._request("POST", f"/ops/monthly-agreements/{monthly_agreement_id}/withdraw",
                             {}, headers)

    # ------------------------------------------------------------------
    # Credentials
    # ------------------------------------------------------------------
    def create_credential(self, payload, headers):
        return self._request("POST", "/ops/credentials", payload, headers)

    def get_credential(self, credential_id, headers):
        return self._request("GET", f"/ops/credentials/{credential_id}", headers=headers)

    def list_credentials(self, headers, params=None):
        return self._request("GET", "/ops/credentials", headers=headers, params=params)

    def report_credential_lost(self, credential_id, headers):
        return self._request("POST", f"/ops/credentials/{credential_id}/report-lost",
                             {}, headers)

    def report_credential_found(self, credential_id, headers):
        return self._request("POST", f"/ops/credentials/{credential_id}/report-found",
                             {}, headers)

    def replace_credential(self, credential_id, credential_type, headers):
        return self._request("POST", f"/ops/credentials/{credential_id}/replace",
                             {"credential_type": credential_type}, headers)

    def return_credential(self, credential_id, headers):
        return self._request("POST", f"/ops/credentials/{credential_id}/return", {}, headers)

    def revoke_credential(self, credential_id, headers):
        return self._request("POST", f"/ops/credentials/{credential_id}/revoke", {}, headers)

    # ------------------------------------------------------------------
    # Parking sessions
    # ------------------------------------------------------------------
    def create_parking_session(self, payload, headers):
        return self._request("POST", "/ops/parking-sessions", payload, headers)

    def get_parking_session(self, parking_session_id, headers):
        return self._request("GET", f"/ops/parking-sessions/{parking_session_id}", headers=headers)

    def list_parking_sessions(self, headers, params=None):
        return self._request("GET", "/ops/parking-sessions", headers=headers, params=params)

    def quote_session(self, parking_session_id, headers):
        return self._request("POST", f"/ops/parking-sessions/{parking_session_id}/quote",
                             {}, headers)

    def pay_session(self, parking_session_id, payload, headers):
        return self._request("POST", f"/ops/parking-sessions/{parking_session_id}/pay",
                             payload, headers)

    def comp_session(self, parking_session_id, payload, headers):
        return self._request("POST", f"/ops/parking-sessions/{parking_session_id}/comp",
                             payload, headers)

    def exit_session(self, parking_session_id, headers):
        return self._request("POST", f"/ops/parking-sessions/{parking_session_id}/exit",
                             {}, headers)

    def lost_ticket_session(self, parking_session_id, headers):
        return self._request("POST", f"/ops/parking-sessions/{parking_session_id}/lost-ticket",
                             {}, headers)

    def refund_session(self, parking_session_id, payload, headers):
        return self._request("POST", f"/ops/parking-sessions/{parking_session_id}/refund",
                             payload, headers)

    # ------------------------------------------------------------------
    # Attendant shifts
    # ------------------------------------------------------------------
    def create_shift(self, payload, headers):
        return self._request("POST", "/ops/shifts", payload, headers)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/ops/shifts/{shift_id}", headers=headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/ops/shifts", headers=headers, params=params)

    def close_shift(self, shift_id, payload, headers):
        return self._request("POST", f"/ops/shifts/{shift_id}/close", payload, headers)

    # ------------------------------------------------------------------
    # Reconciliations
    # ------------------------------------------------------------------
    def create_reconciliation(self, payload, headers):
        return self._request("POST", "/ops/reconciliations", payload, headers)

    def get_reconciliation(self, reconciliation_id, headers):
        return self._request("GET", f"/ops/reconciliations/{reconciliation_id}", headers=headers)

    def list_reconciliations(self, headers, params=None):
        return self._request("GET", "/ops/reconciliations", headers=headers, params=params)

    def submit_reconciliation(self, reconciliation_id, headers):
        return self._request("POST", f"/ops/reconciliations/{reconciliation_id}/submit",
                             {}, headers)

    def approve_reconciliation(self, reconciliation_id, payload, headers):
        return self._request("POST", f"/ops/reconciliations/{reconciliation_id}/approve",
                             payload, headers)

    # ------------------------------------------------------------------
    # Structural inspections
    # ------------------------------------------------------------------
    def create_inspection(self, payload, headers):
        return self._request("POST", "/ops/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/ops/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/ops/inspections", headers=headers, params=params)

    def start_inspection(self, inspection_id, headers):
        return self._request("POST", f"/ops/inspections/{inspection_id}/start", {}, headers)

    def report_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/ops/inspections/{inspection_id}/report",
                             payload, headers)

    def cancel_inspection(self, inspection_id, headers):
        return self._request("POST", f"/ops/inspections/{inspection_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Repair projects
    # ------------------------------------------------------------------
    def create_repair_project(self, payload, headers):
        return self._request("POST", "/ops/repair-projects", payload, headers)

    def get_repair_project(self, repair_project_id, headers):
        return self._request("GET", f"/ops/repair-projects/{repair_project_id}", headers=headers)

    def list_repair_projects(self, headers, params=None):
        return self._request("GET", "/ops/repair-projects", headers=headers, params=params)

    def fund_repair_project(self, repair_project_id, amount_cents, headers):
        return self._request("POST", f"/ops/repair-projects/{repair_project_id}/fund",
                             {"amount_cents": amount_cents}, headers)

    def schedule_repair_project(self, repair_project_id, start_at, end_at, headers):
        return self._request("POST", f"/ops/repair-projects/{repair_project_id}/schedule",
                             {"start_at": start_at, "end_at": end_at}, headers)

    def start_repair_project(self, repair_project_id, headers):
        return self._request("POST", f"/ops/repair-projects/{repair_project_id}/start",
                             {}, headers)

    def close_out_repair_project(self, repair_project_id, headers):
        return self._request("POST", f"/ops/repair-projects/{repair_project_id}/close-out",
                             {}, headers)

    def defer_repair_project(self, repair_project_id, reason, headers):
        return self._request("POST", f"/ops/repair-projects/{repair_project_id}/defer",
                             {"reason": reason}, headers)

    def revise_repair_project(self, repair_project_id, payload, headers):
        return self._request("POST", f"/ops/repair-projects/{repair_project_id}/revise",
                             payload, headers)

    def cancel_repair_project(self, repair_project_id, headers):
        return self._request("POST", f"/ops/repair-projects/{repair_project_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Maintenance windows
    # ------------------------------------------------------------------
    def create_maintenance_window(self, payload, headers):
        return self._request("POST", "/ops/maintenance-windows", payload, headers)

    def get_maintenance_window(self, maintenance_window_id, headers):
        return self._request("GET", f"/ops/maintenance-windows/{maintenance_window_id}",
                             headers=headers)

    def list_maintenance_windows(self, headers, params=None):
        return self._request("GET", "/ops/maintenance-windows", headers=headers, params=params)

    def start_maintenance_window(self, maintenance_window_id, headers):
        return self._request("POST", f"/ops/maintenance-windows/{maintenance_window_id}/start",
                             {}, headers)

    def complete_maintenance_window(self, maintenance_window_id, headers):
        return self._request("POST",
                             f"/ops/maintenance-windows/{maintenance_window_id}/complete",
                             {}, headers)

    def cancel_maintenance_window(self, maintenance_window_id, headers):
        return self._request("POST", f"/ops/maintenance-windows/{maintenance_window_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Patrol rounds
    # ------------------------------------------------------------------
    def create_patrol_round(self, payload, headers):
        return self._request("POST", "/ops/patrol-rounds", payload, headers)

    def get_patrol_round(self, patrol_round_id, headers):
        return self._request("GET", f"/ops/patrol-rounds/{patrol_round_id}", headers=headers)

    def list_patrol_rounds(self, headers, params=None):
        return self._request("GET", "/ops/patrol-rounds", headers=headers, params=params)

    def complete_patrol_round(self, patrol_round_id, payload, headers):
        return self._request("POST", f"/ops/patrol-rounds/{patrol_round_id}/complete",
                             payload, headers)

    # ------------------------------------------------------------------
    # Incident reports
    # ------------------------------------------------------------------
    def create_incident(self, payload, headers):
        return self._request("POST", "/ops/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/ops/incidents/{incident_id}", headers=headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/ops/incidents", headers=headers, params=params)

    def investigate_incident(self, incident_id, headers):
        return self._request("POST", f"/ops/incidents/{incident_id}/investigate", {}, headers)

    def resolve_incident(self, incident_id, resolution_note, headers):
        return self._request("POST", f"/ops/incidents/{incident_id}/resolve",
                             {"resolution_note": resolution_note}, headers)

    def close_incident(self, incident_id, headers):
        return self._request("POST", f"/ops/incidents/{incident_id}/close", {}, headers)

    def mark_incident_duplicate(self, incident_id, duplicate_of_incident_id, headers):
        return self._request("POST", f"/ops/incidents/{incident_id}/mark-duplicate",
                             {"duplicate_of_incident_id": duplicate_of_incident_id}, headers)

    # ------------------------------------------------------------------
    # EV chargers
    # ------------------------------------------------------------------
    def create_ev_charger(self, payload, headers):
        return self._request("POST", "/ops/ev-chargers", payload, headers)

    def get_ev_charger(self, ev_charger_id, headers):
        return self._request("GET", f"/ops/ev-chargers/{ev_charger_id}", headers=headers)

    def list_ev_chargers(self, headers, params=None):
        return self._request("GET", "/ops/ev-chargers", headers=headers, params=params)

    def permit_ev_charger(self, ev_charger_id, headers):
        return self._request("POST", f"/ops/ev-chargers/{ev_charger_id}/permit", {}, headers)

    def install_ev_charger(self, ev_charger_id, headers):
        return self._request("POST", f"/ops/ev-chargers/{ev_charger_id}/install", {}, headers)

    def commission_ev_charger(self, ev_charger_id, headers):
        return self._request("POST", f"/ops/ev-chargers/{ev_charger_id}/commission",
                             {}, headers)

    def take_ev_charger_out_of_service(self, ev_charger_id, headers):
        return self._request("POST", f"/ops/ev-chargers/{ev_charger_id}/take-out-of-service",
                             {}, headers)

    def return_ev_charger_to_service(self, ev_charger_id, headers):
        return self._request("POST", f"/ops/ev-chargers/{ev_charger_id}/return-to-service",
                             {}, headers)

    def decommission_ev_charger(self, ev_charger_id, headers):
        return self._request("POST", f"/ops/ev-chargers/{ev_charger_id}/decommission",
                             {}, headers)

    # ------------------------------------------------------------------
    # Charging sessions
    # ------------------------------------------------------------------
    def create_charging_session(self, payload, headers):
        return self._request("POST", "/ops/charging-sessions", payload, headers)

    def get_charging_session(self, charging_session_id, headers):
        return self._request("GET", f"/ops/charging-sessions/{charging_session_id}",
                             headers=headers)

    def list_charging_sessions(self, headers, params=None):
        return self._request("GET", "/ops/charging-sessions", headers=headers, params=params)

    def complete_charging_session(self, charging_session_id, payload, headers):
        return self._request("POST", f"/ops/charging-sessions/{charging_session_id}/complete",
                             payload, headers)

    def fault_charging_session(self, charging_session_id, fault_description, headers):
        return self._request("POST", f"/ops/charging-sessions/{charging_session_id}/fault",
                             {"fault_description": fault_description}, headers)

    # ------------------------------------------------------------------
    # Event bookings
    # ------------------------------------------------------------------
    def create_event_booking(self, payload, headers):
        return self._request("POST", "/ops/event-bookings", payload, headers)

    def get_event_booking(self, event_booking_id, headers):
        return self._request("GET", f"/ops/event-bookings/{event_booking_id}", headers=headers)

    def list_event_bookings(self, headers, params=None):
        return self._request("GET", "/ops/event-bookings", headers=headers, params=params)

    def confirm_event_booking(self, event_booking_id, staffing_assignments, headers):
        return self._request("POST", f"/ops/event-bookings/{event_booking_id}/confirm",
                             {"staffing_assignments": staffing_assignments}, headers)

    def activate_event_booking(self, event_booking_id, headers):
        return self._request("POST", f"/ops/event-bookings/{event_booking_id}/activate",
                             {}, headers)

    def complete_event_booking(self, event_booking_id, headers):
        return self._request("POST", f"/ops/event-bookings/{event_booking_id}/complete",
                             {}, headers)

    def cancel_event_booking(self, event_booking_id, reason, headers):
        return self._request("POST", f"/ops/event-bookings/{event_booking_id}/cancel",
                             {"reason": reason}, headers)


api_client = ApiClient()
