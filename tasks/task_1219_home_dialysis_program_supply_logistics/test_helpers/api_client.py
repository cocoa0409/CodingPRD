"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Programs & clock ---
    def create_program(self, payload, headers):
        return self._request("POST", "/api/dialysis-programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/api/dialysis-programs/{program_id}", headers=headers)

    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def list_program_patients(self, program_id, headers, params=None):
        return self._request("GET", f"/api/dialysis-programs/{program_id}/patients",
                             headers=headers, params=params)

    def list_program_machines(self, program_id, headers, params=None):
        return self._request("GET", f"/api/dialysis-programs/{program_id}/dialysis-machines",
                             headers=headers, params=params)

    def list_program_chairs(self, program_id, headers, params=None):
        return self._request("GET", f"/api/dialysis-programs/{program_id}/in-center-chairs",
                             headers=headers, params=params)

    # --- Patients ---
    def create_patient(self, payload, headers):
        return self._request("POST", "/api/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/api/patients/{patient_id}", headers=headers)

    def patch_prescription(self, patient_id, payload, headers):
        return self._request("PATCH", f"/api/patients/{patient_id}/prescription",
                             payload, headers)

    def activate_patient(self, patient_id, headers):
        return self._request("POST", f"/api/patients/{patient_id}/activate",
                             headers=headers)

    def suspend_patient(self, patient_id, payload, headers):
        return self._request("POST", f"/api/patients/{patient_id}/suspend",
                             payload, headers)

    def reinstate_patient(self, patient_id, headers):
        return self._request("POST", f"/api/patients/{patient_id}/reinstate",
                             headers=headers)

    # --- Training ---
    def create_training_attempt(self, payload, headers):
        return self._request("POST", "/api/training-attempts", payload, headers)

    def sign_off_attempt(self, attempt_id, headers):
        return self._request("POST", f"/api/training-attempts/{attempt_id}/sign-off",
                             headers=headers)

    def list_patient_training_attempts(self, patient_id, headers, params=None):
        return self._request("GET", f"/api/patients/{patient_id}/training-attempts",
                             headers=headers, params=params)

    # --- Home assessments ---
    def create_home_assessment(self, payload, headers):
        return self._request("POST", "/api/home-assessments", payload, headers)

    def get_home_assessment(self, assessment_id, headers):
        return self._request("GET", f"/api/home-assessments/{assessment_id}",
                             headers=headers)

    def list_patient_home_assessments(self, patient_id, headers, params=None):
        return self._request("GET", f"/api/patients/{patient_id}/home-assessments",
                             headers=headers, params=params)

    def accept_assessment(self, assessment_id, headers):
        return self._request("POST", f"/api/home-assessments/{assessment_id}/accept",
                             headers=headers)

    def require_remediation(self, assessment_id, headers):
        return self._request(
            "POST", f"/api/home-assessments/{assessment_id}/require-remediation",
            headers=headers)

    def resubmit_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/api/home-assessments/{assessment_id}/resubmit",
                             payload, headers)

    # --- Home modification work orders ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/api/home-modification-work-orders",
                             payload, headers)

    def list_patient_work_orders(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/api/patients/{patient_id}/home-modification-work-orders",
            headers=headers, params=params)

    def list_assessment_work_orders(self, assessment_id, headers, params=None):
        return self._request(
            "GET", f"/api/home-assessments/{assessment_id}/home-modification-work-orders",
            headers=headers, params=params)

    def approve_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/api/home-modification-work-orders/{work_order_id}/approve",
            payload, headers)

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/api/home-modification-work-orders/{work_order_id}/complete",
            payload, headers)

    def inspect_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/api/home-modification-work-orders/{work_order_id}/inspect",
            payload, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request(
            "POST", f"/api/home-modification-work-orders/{work_order_id}/cancel",
            headers=headers)

    # --- Machines & maintenance ---
    def create_machine(self, payload, headers):
        return self._request("POST", "/api/dialysis-machines", payload, headers)

    def get_machine(self, machine_id, headers):
        return self._request("GET", f"/api/dialysis-machines/{machine_id}",
                             headers=headers)

    def assign_machine(self, machine_id, payload, headers):
        return self._request("POST", f"/api/dialysis-machines/{machine_id}/assign",
                             payload, headers)

    def unassign_machine(self, machine_id, headers):
        return self._request("POST", f"/api/dialysis-machines/{machine_id}/unassign",
                             headers=headers)

    def decommission_machine(self, machine_id, headers):
        return self._request("POST",
                             f"/api/dialysis-machines/{machine_id}/decommission",
                             headers=headers)

    def list_machine_events(self, machine_id, headers, params=None):
        return self._request(
            "GET", f"/api/dialysis-machines/{machine_id}/maintenance-events",
            headers=headers, params=params)

    def list_machine_logs(self, machine_id, headers, params=None):
        return self._request("GET",
                             f"/api/dialysis-machines/{machine_id}/treatment-logs",
                             headers=headers, params=params)

    def list_machine_plans(self, machine_id, headers, params=None):
        return self._request(
            "GET", f"/api/dialysis-machines/{machine_id}/emergency-backup-plans",
            headers=headers, params=params)

    def list_patient_machines(self, patient_id, headers, params=None):
        return self._request("GET", f"/api/patients/{patient_id}/dialysis-machines",
                             headers=headers, params=params)

    def create_maintenance_event(self, payload, headers):
        return self._request("POST", "/api/maintenance-events", payload, headers)

    def start_maintenance_event(self, event_id, headers):
        return self._request("POST", f"/api/maintenance-events/{event_id}/start",
                             headers=headers)

    def complete_maintenance_event(self, event_id, headers):
        return self._request("POST", f"/api/maintenance-events/{event_id}/complete",
                             headers=headers)

    def cancel_maintenance_event(self, event_id, headers):
        return self._request("POST", f"/api/maintenance-events/{event_id}/cancel",
                             headers=headers)

    # --- Emergency backup plans ---
    def create_backup_plan(self, payload, headers):
        return self._request("POST", "/api/emergency-backup-plans", payload, headers)

    def drill_backup_plan(self, plan_id, headers):
        return self._request("POST", f"/api/emergency-backup-plans/{plan_id}/drill",
                             headers=headers)

    def list_patient_backup_plans(self, patient_id, headers, params=None):
        return self._request("GET",
                             f"/api/patients/{patient_id}/emergency-backup-plans",
                             headers=headers, params=params)

    # --- Supply orders & delivery ---
    def create_supply_order(self, payload, headers):
        return self._request("POST", "/api/supply-orders", payload, headers)

    def get_supply_order(self, order_id, headers):
        return self._request("GET", f"/api/supply-orders/{order_id}", headers=headers)

    def list_patient_supply_orders(self, patient_id, headers, params=None):
        return self._request("GET", f"/api/patients/{patient_id}/supply-orders",
                             headers=headers, params=params)

    def patch_supply_order(self, order_id, payload, headers):
        return self._request("PATCH", f"/api/supply-orders/{order_id}", payload, headers)

    def submit_supply_order(self, order_id, headers):
        return self._request("POST", f"/api/supply-orders/{order_id}/submit",
                             headers=headers)

    def review_supply_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/supply-orders/{order_id}/review",
                             payload, headers)

    def cancel_supply_order(self, order_id, headers):
        return self._request("POST", f"/api/supply-orders/{order_id}/cancel",
                             headers=headers)

    def close_supply_order(self, order_id, headers):
        return self._request("POST", f"/api/supply-orders/{order_id}/close",
                             headers=headers)

    def create_delivery_appointment(self, payload, headers):
        return self._request("POST", "/api/delivery-appointments", payload, headers)

    def list_order_appointments(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/api/supply-orders/{order_id}/delivery-appointments",
            headers=headers, params=params)

    def complete_delivery_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/api/delivery-appointments/{appointment_id}/complete",
            payload, headers)

    def fail_delivery_appointment(self, appointment_id, payload, headers):
        return self._request("POST",
                             f"/api/delivery-appointments/{appointment_id}/fail",
                             payload, headers)

    def cancel_delivery_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/api/delivery-appointments/{appointment_id}/cancel",
            headers=headers)

    # --- Treatment logs & clinical reviews ---
    def create_treatment_log(self, payload, headers):
        return self._request("POST", "/api/treatment-logs", payload, headers)

    def list_patient_treatment_logs(self, patient_id, headers, params=None):
        return self._request("GET", f"/api/patients/{patient_id}/treatment-logs",
                             headers=headers, params=params)

    def mark_log_reviewed(self, log_id, headers):
        return self._request("POST", f"/api/treatment-logs/{log_id}/mark-reviewed",
                             headers=headers)

    def flag_log(self, log_id, payload, headers):
        return self._request("POST", f"/api/treatment-logs/{log_id}/flag",
                             payload, headers)

    def amend_log(self, log_id, payload, headers):
        return self._request("POST", f"/api/treatment-logs/{log_id}/amend",
                             payload, headers)

    def list_patient_clinical_reviews(self, patient_id, headers, params=None):
        return self._request("GET", f"/api/patients/{patient_id}/clinical-reviews",
                             headers=headers, params=params)

    def sign_off_review(self, review_id, payload, headers):
        return self._request("POST", f"/api/clinical-reviews/{review_id}/sign-off",
                             payload, headers)

    def escalate_review(self, review_id, headers):
        return self._request("POST", f"/api/clinical-reviews/{review_id}/escalate",
                             headers=headers)

    # --- Chairs & backup slots ---
    def create_chair(self, payload, headers):
        return self._request("POST", "/api/in-center-chairs", payload, headers)

    def get_chair(self, chair_id, headers):
        return self._request("GET", f"/api/in-center-chairs/{chair_id}", headers=headers)

    def patch_chair(self, chair_id, payload, headers):
        return self._request("PATCH", f"/api/in-center-chairs/{chair_id}",
                             payload, headers)

    def create_slot_reservation(self, payload, headers):
        return self._request("POST", "/api/backup-slot-reservations", payload, headers)

    def list_patient_slot_reservations(self, patient_id, headers, params=None):
        return self._request("GET",
                             f"/api/patients/{patient_id}/backup-slot-reservations",
                             headers=headers, params=params)

    def list_chair_slot_reservations(self, chair_id, headers, params=None):
        return self._request(
            "GET", f"/api/in-center-chairs/{chair_id}/backup-slot-reservations",
            headers=headers, params=params)

    def cancel_slot_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/api/backup-slot-reservations/{reservation_id}/cancel",
            headers=headers)

    def complete_slot_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/api/backup-slot-reservations/{reservation_id}/complete",
            headers=headers)

    # --- Waste & returns ---
    def create_waste_return_record(self, payload, headers):
        return self._request("POST", "/api/waste-return-records", payload, headers)

    def list_patient_waste_return_records(self, patient_id, headers, params=None):
        return self._request("GET",
                             f"/api/patients/{patient_id}/waste-return-records",
                             headers=headers, params=params)

    def verify_waste_return_record(self, record_id, payload, headers):
        return self._request("POST", f"/api/waste-return-records/{record_id}/verify",
                             payload, headers)

    # --- Transitions ---
    def create_transition_record(self, payload, headers):
        return self._request("POST", "/api/transition-records", payload, headers)

    def get_transition_record(self, record_id, headers):
        return self._request("GET", f"/api/transition-records/{record_id}",
                             headers=headers)

    def list_patient_transition_records(self, patient_id, headers, params=None):
        return self._request("GET", f"/api/patients/{patient_id}/transition-records",
                             headers=headers, params=params)

    def list_transition_reversals(self, record_id, headers):
        return self._request("GET", f"/api/transition-records/{record_id}/reversals",
                             headers=headers)

    def approve_transition(self, record_id, headers):
        return self._request("POST", f"/api/transition-records/{record_id}/approve",
                             headers=headers)

    def deny_transition(self, record_id, headers):
        return self._request("POST", f"/api/transition-records/{record_id}/deny",
                             headers=headers)

    def activate_transition(self, record_id, headers):
        return self._request("POST", f"/api/transition-records/{record_id}/activate",
                             headers=headers)


api_client = ApiClient()
