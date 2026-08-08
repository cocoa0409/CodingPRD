"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clinicians ----
    def create_clinician(self, payload, headers):
        return self._request("POST", "/clinic/clinicians", payload, headers=headers)

    def get_clinician(self, clinician_id, headers):
        return self._request("GET", f"/clinic/clinicians/{clinician_id}", headers=headers)

    # ---- Pharmacists ----
    def create_pharmacist(self, payload, headers):
        return self._request("POST", "/clinic/pharmacists", payload, headers=headers)

    def get_pharmacist(self, pharmacist_id, headers):
        return self._request("GET", f"/clinic/pharmacists/{pharmacist_id}", headers=headers)

    # ---- Patients ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/clinic/patients", payload, headers=headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/clinic/patients/{patient_id}", headers=headers)

    def get_monitoring_summary(self, patient_id, headers):
        return self._request("GET", f"/clinic/patients/{patient_id}/monitoring-summary", headers=headers)

    # ---- Membership Plans ----
    def create_membership_plan(self, payload, headers):
        return self._request("POST", "/clinic/membership-plans", payload, headers=headers)

    def get_membership_plan(self, plan_id, headers):
        return self._request("GET", f"/clinic/membership-plans/{plan_id}", headers=headers)

    # ---- Memberships ----
    def create_membership(self, payload, headers):
        return self._request("POST", "/clinic/memberships", payload, headers=headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/clinic/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/clinic/memberships", headers=headers, params=params)

    def activate_membership(self, membership_id, headers, payload=None):
        return self._request("POST", f"/clinic/memberships/{membership_id}/activate", payload or {}, headers=headers)

    def record_payment(self, membership_id, payload, headers):
        return self._request("POST", f"/clinic/memberships/{membership_id}/record-payment", payload, headers=headers)

    def change_plan(self, membership_id, payload, headers):
        return self._request("POST", f"/clinic/memberships/{membership_id}/change-plan", payload, headers=headers)

    def cancel_membership(self, membership_id, headers, payload=None):
        return self._request("POST", f"/clinic/memberships/{membership_id}/cancel", payload or {}, headers=headers)

    # ---- Draw Stations ----
    def create_draw_station(self, payload, headers):
        return self._request("POST", "/clinic/draw-stations", payload, headers=headers)

    def get_draw_station(self, station_id, headers):
        return self._request("GET", f"/clinic/draw-stations/{station_id}", headers=headers)

    # ---- Lab Panels ----
    def create_lab_panel(self, payload, headers):
        return self._request("POST", "/clinic/lab-panels", payload, headers=headers)

    def get_lab_panel(self, panel_id, headers):
        return self._request("GET", f"/clinic/lab-panels/{panel_id}", headers=headers)

    def list_lab_panels(self, headers, params=None):
        return self._request("GET", "/clinic/lab-panels", headers=headers, params=params)

    def draw_lab_panel(self, panel_id, headers, payload=None):
        return self._request("POST", f"/clinic/lab-panels/{panel_id}/draw", payload or {}, headers=headers)

    def result_lab_panel(self, panel_id, payload, headers):
        return self._request("POST", f"/clinic/lab-panels/{panel_id}/result", payload, headers=headers)

    def review_lab_panel(self, panel_id, headers, payload=None):
        return self._request("POST", f"/clinic/lab-panels/{panel_id}/review", payload or {}, headers=headers)

    # ---- Lab-Draw Appointments ----
    def create_lab_draw_appointment(self, payload, headers):
        return self._request("POST", "/clinic/lab-draw-appointments", payload, headers=headers)

    def get_lab_draw_appointment(self, appt_id, headers):
        return self._request("GET", f"/clinic/lab-draw-appointments/{appt_id}", headers=headers)

    def list_lab_draw_appointments(self, headers, params=None):
        return self._request("GET", "/clinic/lab-draw-appointments", headers=headers, params=params)

    def complete_lab_draw_appointment(self, appt_id, headers, payload=None):
        return self._request("POST", f"/clinic/lab-draw-appointments/{appt_id}/complete", payload or {}, headers=headers)

    def cancel_lab_draw_appointment(self, appt_id, headers, payload=None):
        return self._request("POST", f"/clinic/lab-draw-appointments/{appt_id}/cancel", payload or {}, headers=headers)

    # ---- Telehealth Visits ----
    def create_telehealth_visit(self, payload, headers):
        return self._request("POST", "/clinic/telehealth-visits", payload, headers=headers)

    def get_telehealth_visit(self, visit_id, headers):
        return self._request("GET", f"/clinic/telehealth-visits/{visit_id}", headers=headers)

    def list_telehealth_visits(self, headers, params=None):
        return self._request("GET", "/clinic/telehealth-visits", headers=headers, params=params)

    def complete_telehealth_visit(self, visit_id, headers, payload=None):
        return self._request("POST", f"/clinic/telehealth-visits/{visit_id}/complete", payload or {}, headers=headers)

    def cancel_telehealth_visit(self, visit_id, headers, payload=None):
        return self._request("POST", f"/clinic/telehealth-visits/{visit_id}/cancel", payload or {}, headers=headers)

    # ---- Treatment Plans ----
    def create_treatment_plan(self, payload, headers):
        return self._request("POST", "/clinic/treatment-plans", payload, headers=headers)

    def get_treatment_plan(self, plan_id, headers):
        return self._request("GET", f"/clinic/treatment-plans/{plan_id}", headers=headers)

    def list_treatment_plans(self, headers, params=None):
        return self._request("GET", "/clinic/treatment-plans", headers=headers, params=params)

    def activate_treatment_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/clinic/treatment-plans/{plan_id}/activate", payload or {}, headers=headers)

    def create_titration(self, plan_id, payload, headers):
        return self._request("POST", f"/clinic/treatment-plans/{plan_id}/titrations", payload, headers=headers)

    def list_titrations(self, plan_id, headers, params=None):
        return self._request("GET", f"/clinic/treatment-plans/{plan_id}/titrations", headers=headers, params=params)

    def confirm_titration(self, plan_id, titration_id, headers, payload=None):
        return self._request(
            "POST",
            f"/clinic/treatment-plans/{plan_id}/titrations/{titration_id}/confirm",
            payload or {},
            headers=headers,
        )

    def suspend_treatment_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/clinic/treatment-plans/{plan_id}/suspend", payload or {}, headers=headers)

    def resume_treatment_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/clinic/treatment-plans/{plan_id}/resume", payload or {}, headers=headers)

    # ---- Prescriptions ----
    def create_prescription(self, payload, headers):
        return self._request("POST", "/clinic/prescriptions", payload, headers=headers)

    def get_prescription(self, prescription_id, headers):
        return self._request("GET", f"/clinic/prescriptions/{prescription_id}", headers=headers)

    def list_prescriptions(self, headers, params=None):
        return self._request("GET", "/clinic/prescriptions", headers=headers, params=params)

    def revoke_prescription(self, prescription_id, headers, payload=None):
        return self._request("POST", f"/clinic/prescriptions/{prescription_id}/revoke", payload or {}, headers=headers)

    # ---- Refill Orders ----
    def create_refill_order(self, payload, headers):
        return self._request("POST", "/clinic/refill-orders", payload, headers=headers)

    def get_refill_order(self, refill_id, headers):
        return self._request("GET", f"/clinic/refill-orders/{refill_id}", headers=headers)

    def list_refill_orders(self, headers, params=None):
        return self._request("GET", "/clinic/refill-orders", headers=headers, params=params)

    def dispense_refill_order(self, refill_id, payload, headers):
        return self._request("POST", f"/clinic/refill-orders/{refill_id}/dispense", payload, headers=headers)

    def cancel_refill_order(self, refill_id, headers, payload=None):
        return self._request("POST", f"/clinic/refill-orders/{refill_id}/cancel", payload or {}, headers=headers)

    def reverse_refill_order(self, refill_id, headers, payload=None):
        return self._request("POST", f"/clinic/refill-orders/{refill_id}/reverse", payload or {}, headers=headers)

    # ---- Adverse Events ----
    def create_adverse_event(self, payload, headers):
        return self._request("POST", "/clinic/adverse-events", payload, headers=headers)

    def get_adverse_event(self, event_id, headers):
        return self._request("GET", f"/clinic/adverse-events/{event_id}", headers=headers)

    def list_adverse_events(self, headers, params=None):
        return self._request("GET", "/clinic/adverse-events", headers=headers, params=params)

    def triage_adverse_event(self, event_id, payload, headers):
        return self._request("POST", f"/clinic/adverse-events/{event_id}/triage", payload, headers=headers)

    def resolve_adverse_event(self, event_id, headers, payload=None):
        return self._request("POST", f"/clinic/adverse-events/{event_id}/resolve", payload or {}, headers=headers)

    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/clinic/_clock/set_current_utc", payload, headers=headers)


api_client = ApiClient()
