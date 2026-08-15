"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/midway/_clock/set_current_utc", payload, headers)

    # --- fairs ---
    def create_fair(self, payload, headers):
        return self._request("POST", "/midway/fairs", payload, headers)

    def get_fair(self, fair_id, headers):
        return self._request("GET", f"/midway/fairs/{fair_id}", headers=headers)

    def list_fairs(self, headers, params=None):
        return self._request("GET", "/midway/fairs", headers=headers, params=params)

    def request_permit(self, fair_id, payload, headers):
        return self._request("POST", f"/midway/fairs/{fair_id}/request-permit", payload, headers)

    def begin_teardown(self, fair_id, payload, headers):
        return self._request("POST", f"/midway/fairs/{fair_id}/begin-teardown", payload, headers)

    def archive_fair(self, fair_id, payload, headers):
        return self._request("POST", f"/midway/fairs/{fair_id}/archive", payload, headers)

    # --- rides ---
    def create_ride(self, payload, headers):
        return self._request("POST", "/midway/rides", payload, headers)

    def get_ride(self, ride_id, headers):
        return self._request("GET", f"/midway/rides/{ride_id}", headers=headers)

    def list_rides(self, headers, params=None):
        return self._request("GET", "/midway/rides", headers=headers, params=params)

    def verify_assembly(self, ride_id, payload, headers):
        return self._request("POST", f"/midway/rides/{ride_id}/verify-assembly", payload, headers)

    def dismantle_ride(self, ride_id, payload, headers):
        return self._request("POST", f"/midway/rides/{ride_id}/dismantle", payload, headers)

    def resume_ride(self, ride_id, payload, headers):
        return self._request("POST", f"/midway/rides/{ride_id}/resume", payload, headers)

    # --- inspectors ---
    def create_inspector(self, payload, headers):
        return self._request("POST", "/midway/inspectors", payload, headers)

    def get_inspector(self, inspector_id, headers):
        return self._request("GET", f"/midway/inspectors/{inspector_id}", headers=headers)

    def list_inspectors(self, headers, params=None):
        return self._request("GET", "/midway/inspectors", headers=headers, params=params)

    def deactivate_inspector(self, inspector_id, payload, headers):
        return self._request("POST", f"/midway/inspectors/{inspector_id}/deactivate", payload, headers)

    # --- inspection appointments ---
    def create_appointment(self, payload, headers):
        return self._request("POST", "/midway/inspection-appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/midway/inspection-appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/midway/inspection-appointments", headers=headers, params=params)

    def complete_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/midway/inspection-appointments/{appointment_id}/complete", payload, headers)

    def cancel_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/midway/inspection-appointments/{appointment_id}/cancel", payload, headers)

    # --- permits ---
    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/midway/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/midway/permits", headers=headers, params=params)

    def approve_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/midway/permits/{permit_id}/approve", payload, headers)

    def deny_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/midway/permits/{permit_id}/deny", payload, headers)

    # --- staff ---
    def create_staff(self, payload, headers):
        return self._request("POST", "/midway/staff", payload, headers)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/midway/staff/{staff_id}", headers=headers)

    def list_staff(self, headers, params=None):
        return self._request("GET", "/midway/staff", headers=headers, params=params)

    def release_staff(self, staff_id, payload, headers):
        return self._request("POST", f"/midway/staff/{staff_id}/release", payload, headers)

    # --- operator certifications ---
    def create_certification(self, payload, headers):
        return self._request("POST", "/midway/operator-certifications", payload, headers)

    def get_certification(self, cert_id, headers):
        return self._request("GET", f"/midway/operator-certifications/{cert_id}", headers=headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/midway/operator-certifications", headers=headers, params=params)

    def revoke_certification(self, cert_id, payload, headers):
        return self._request("POST", f"/midway/operator-certifications/{cert_id}/revoke", payload, headers)

    # --- operating days ---
    def create_operating_day(self, payload, headers):
        return self._request("POST", "/midway/operating-days", payload, headers)

    def get_operating_day(self, day_id, headers):
        return self._request("GET", f"/midway/operating-days/{day_id}", headers=headers)

    def list_operating_days(self, headers, params=None):
        return self._request("GET", "/midway/operating-days", headers=headers, params=params)

    def begin_checklists(self, day_id, payload, headers):
        return self._request("POST", f"/midway/operating-days/{day_id}/begin-checklists", payload, headers)

    def open_gates(self, day_id, payload, headers):
        return self._request("POST", f"/midway/operating-days/{day_id}/open-gates", payload, headers)

    def resume_day(self, day_id, payload, headers):
        return self._request("POST", f"/midway/operating-days/{day_id}/resume-day", payload, headers)

    def close_gates(self, day_id, payload, headers):
        return self._request("POST", f"/midway/operating-days/{day_id}/close-gates", payload, headers)

    def reconcile_day(self, day_id, payload, headers):
        return self._request("POST", f"/midway/operating-days/{day_id}/reconcile", payload, headers)

    # --- daily checklists ---
    def create_checklist(self, payload, headers):
        return self._request("POST", "/midway/daily-checklists", payload, headers)

    def get_checklist(self, checklist_id, headers):
        return self._request("GET", f"/midway/daily-checklists/{checklist_id}", headers=headers)

    def list_checklists(self, headers, params=None):
        return self._request("GET", "/midway/daily-checklists", headers=headers, params=params)

    def submit_checklist(self, checklist_id, payload, headers):
        return self._request("POST", f"/midway/daily-checklists/{checklist_id}/submit", payload, headers)

    def countersign_checklist(self, checklist_id, payload, headers):
        return self._request("POST", f"/midway/daily-checklists/{checklist_id}/countersign", payload, headers)

    def reject_checklist(self, checklist_id, payload, headers):
        return self._request("POST", f"/midway/daily-checklists/{checklist_id}/reject", payload, headers)

    # --- ride cycles ---
    def create_cycle(self, payload, headers):
        return self._request("POST", "/midway/ride-cycles", payload, headers)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/midway/ride-cycles/{cycle_id}", headers=headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", "/midway/ride-cycles", headers=headers, params=params)

    def load_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/midway/ride-cycles/{cycle_id}/load", payload, headers)

    def dispatch_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/midway/ride-cycles/{cycle_id}/dispatch", payload, headers)

    def complete_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/midway/ride-cycles/{cycle_id}/complete", payload, headers)

    def abort_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/midway/ride-cycles/{cycle_id}/abort", payload, headers)

    # --- ride redemptions ---
    def create_redemption(self, payload, headers):
        return self._request("POST", "/midway/ride-redemptions", payload, headers)

    def get_redemption(self, redemption_id, headers):
        return self._request("GET", f"/midway/ride-redemptions/{redemption_id}", headers=headers)

    def list_redemptions(self, headers, params=None):
        return self._request("GET", "/midway/ride-redemptions", headers=headers, params=params)

    def void_redemption(self, redemption_id, payload, headers):
        return self._request("POST", f"/midway/ride-redemptions/{redemption_id}/void", payload, headers)

    # --- ticket products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/midway/ticket-products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/midway/ticket-products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/midway/ticket-products", headers=headers, params=params)

    def deactivate_product(self, product_id, payload, headers):
        return self._request("POST", f"/midway/ticket-products/{product_id}/deactivate", payload, headers)

    # --- ticket sales ---
    def create_sale(self, payload, headers):
        return self._request("POST", "/midway/ticket-sales", payload, headers)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/midway/ticket-sales/{sale_id}", headers=headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/midway/ticket-sales", headers=headers, params=params)

    def void_sale(self, sale_id, payload, headers):
        return self._request("POST", f"/midway/ticket-sales/{sale_id}/void", payload, headers)

    # --- weather observations ---
    def create_observation(self, payload, headers):
        return self._request("POST", "/midway/weather-observations", payload, headers)

    def get_observation(self, observation_id, headers):
        return self._request("GET", f"/midway/weather-observations/{observation_id}", headers=headers)

    def list_observations(self, headers, params=None):
        return self._request("GET", "/midway/weather-observations", headers=headers, params=params)

    # --- incident reports ---
    def create_incident(self, payload, headers):
        return self._request("POST", "/midway/incident-reports", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/midway/incident-reports/{incident_id}", headers=headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/midway/incident-reports", headers=headers, params=params)

    def clear_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/midway/incident-reports/{incident_id}/clear", payload, headers)

    def order_shutdown(self, incident_id, payload, headers):
        return self._request("POST", f"/midway/incident-reports/{incident_id}/order-shutdown", payload, headers)

    # --- crew shifts ---
    def create_shift(self, payload, headers):
        return self._request("POST", "/midway/crew-shifts", payload, headers)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/midway/crew-shifts/{shift_id}", headers=headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/midway/crew-shifts", headers=headers, params=params)

    def confirm_shift(self, shift_id, payload, headers):
        return self._request("POST", f"/midway/crew-shifts/{shift_id}/confirm", payload, headers)

    def complete_shift(self, shift_id, payload, headers):
        return self._request("POST", f"/midway/crew-shifts/{shift_id}/complete", payload, headers)

    def no_show_shift(self, shift_id, payload, headers):
        return self._request("POST", f"/midway/crew-shifts/{shift_id}/no-show", payload, headers)

    def cancel_shift(self, shift_id, payload, headers):
        return self._request("POST", f"/midway/crew-shifts/{shift_id}/cancel", payload, headers)


api_client = ApiClient()
