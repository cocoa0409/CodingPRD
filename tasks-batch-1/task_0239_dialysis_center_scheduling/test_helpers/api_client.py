"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
All paths are mounted under the API root.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Clinic ────────────────────────────────────────────────────────────
    def create_clinic(self, payload, headers):
        return self._request("POST", "/clinics", payload, headers)

    def list_clinics(self, headers, params=None):
        return self._request("GET", "/clinics", headers=headers, params=params)

    def get_clinic(self, clinic_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}", headers=headers)

    def suspend_clinic(self, clinic_id, headers, payload=None):
        return self._request("POST", f"/clinics/{clinic_id}/suspend", payload or {}, headers)

    def resume_clinic(self, clinic_id, headers, payload=None):
        return self._request("POST", f"/clinics/{clinic_id}/resume", payload or {}, headers)

    def close_clinic(self, clinic_id, headers, payload=None):
        return self._request("POST", f"/clinics/{clinic_id}/close", payload or {}, headers)

    # ─── Shift ─────────────────────────────────────────────────────────────
    def create_shift(self, payload, headers):
        return self._request("POST", "/shifts", payload, headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/shifts", headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}", headers=headers)

    def retire_shift(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/retire", {}, headers)

    # ─── Machine ───────────────────────────────────────────────────────────
    def create_machine(self, payload, headers):
        return self._request("POST", "/machines", payload, headers)

    def list_machines(self, headers, params=None):
        return self._request("GET", "/machines", headers=headers, params=params)

    def get_machine(self, machine_id, headers):
        return self._request("GET", f"/machines/{machine_id}", headers=headers)

    def start_maintenance(self, machine_id, headers):
        return self._request("POST", f"/machines/{machine_id}/start-maintenance", {}, headers)

    def complete_maintenance(self, machine_id, headers, payload=None):
        return self._request(
            "POST", f"/machines/{machine_id}/complete-maintenance", payload or {}, headers
        )

    def retire_machine(self, machine_id, headers):
        return self._request("POST", f"/machines/{machine_id}/retire", {}, headers)

    # ─── Station ───────────────────────────────────────────────────────────
    def create_station(self, payload, headers):
        return self._request("POST", "/stations", payload, headers)

    def list_stations(self, headers, params=None):
        return self._request("GET", "/stations", headers=headers, params=params)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    def take_station_offline(self, station_id, headers):
        return self._request("POST", f"/stations/{station_id}/take-offline", {}, headers)

    def bring_station_online(self, station_id, headers):
        return self._request("POST", f"/stations/{station_id}/bring-online", {}, headers)

    # ─── Patient ───────────────────────────────────────────────────────────
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def get_adherence(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}/adherence", headers=headers)

    def reactivate_patient(self, patient_id, headers):
        return self._request("POST", f"/patients/{patient_id}/reactivate", {}, headers)

    # ─── NephrologistOrder ─────────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def activate_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/activate", {}, headers)

    def open_revision(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/open-revision", {}, headers)

    def commit_revision(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/commit-revision", payload or {}, headers)

    def revoke_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/revoke", {}, headers)

    # ─── StandingSlot ──────────────────────────────────────────────────────
    def create_standing_slot(self, payload, headers):
        return self._request("POST", "/standing-slots", payload, headers)

    def list_standing_slots(self, headers, params=None):
        return self._request("GET", "/standing-slots", headers=headers, params=params)

    def get_standing_slot(self, slot_id, headers):
        return self._request("GET", f"/standing-slots/{slot_id}", headers=headers)

    def release_standing_slot(self, slot_id, headers):
        return self._request("POST", f"/standing-slots/{slot_id}/release", {}, headers)

    # ─── TreatmentSession ──────────────────────────────────────────────────
    def create_session(self, payload, headers):
        return self._request("POST", "/sessions", payload, headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def check_in_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/check-in", {}, headers)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/complete", {}, headers)

    def mark_missed_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/mark-missed", {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/cancel", {}, headers)

    def bill_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/bill", {}, headers)

    def settle_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/settle", {}, headers)

    def void_billing_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/void-billing", {}, headers)

    # ─── TransportTrip ─────────────────────────────────────────────────────
    def create_transport_trip(self, payload, headers):
        return self._request("POST", "/transport-trips", payload, headers)

    def list_transport_trips(self, headers, params=None):
        return self._request("GET", "/transport-trips", headers=headers, params=params)

    def get_transport_trip(self, trip_id, headers):
        return self._request("GET", f"/transport-trips/{trip_id}", headers=headers)

    def confirm_transport_trip(self, trip_id, headers):
        return self._request("POST", f"/transport-trips/{trip_id}/confirm", {}, headers)

    def complete_transport_trip(self, trip_id, headers):
        return self._request("POST", f"/transport-trips/{trip_id}/complete", {}, headers)

    def cancel_transport_trip(self, trip_id, headers):
        return self._request("POST", f"/transport-trips/{trip_id}/cancel", {}, headers)

    # ─── LabOrder ──────────────────────────────────────────────────────────
    def create_lab_order(self, payload, headers):
        return self._request("POST", "/lab-orders", payload, headers)

    def list_lab_orders(self, headers, params=None):
        return self._request("GET", "/lab-orders", headers=headers, params=params)

    def get_lab_order(self, lab_id, headers):
        return self._request("GET", f"/lab-orders/{lab_id}", headers=headers)

    def collect_lab_order(self, lab_id, headers):
        return self._request("POST", f"/lab-orders/{lab_id}/collect", {}, headers)

    def cancel_lab_order(self, lab_id, headers):
        return self._request("POST", f"/lab-orders/{lab_id}/cancel", {}, headers)

    # ─── MonthlyStatement ──────────────────────────────────────────────────
    def create_statement(self, payload, headers):
        return self._request("POST", "/statements", payload, headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/statements", headers=headers, params=params)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/statements/{statement_id}", headers=headers)

    def pay_statement(self, statement_id, headers):
        return self._request("POST", f"/statements/{statement_id}/pay", {}, headers)

    def cancel_statement(self, statement_id, headers):
        return self._request("POST", f"/statements/{statement_id}/cancel", {}, headers)

    # ─── Test-driving clock ────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
