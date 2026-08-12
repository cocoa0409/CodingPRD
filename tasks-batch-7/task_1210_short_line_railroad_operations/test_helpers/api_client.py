"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/rail/_clock/set_current_utc", payload, headers)

    # --- Customers (PRD §3.1) ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/rail/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/rail/customers", params, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/rail/customers/{customer_id}", headers=headers)

    def update_customer(self, customer_id, payload, headers):
        return self._request("PATCH", f"/rail/customers/{customer_id}", payload, headers)

    # --- Industry sidings (PRD §3.1) ---
    def create_siding(self, payload, headers):
        return self._request("POST", "/rail/industry-sidings", payload, headers)

    def list_sidings(self, headers, params=None):
        return self._request("GET", "/rail/industry-sidings", params, headers)

    def get_siding(self, siding_id, headers):
        return self._request("GET", f"/rail/industry-sidings/{siding_id}", headers=headers)

    def renew_siding_agreement(self, siding_id, payload, headers):
        return self._request("POST", f"/rail/industry-sidings/{siding_id}/renew-agreement", payload, headers)

    def suspend_siding(self, siding_id, headers):
        return self._request("POST", f"/rail/industry-sidings/{siding_id}/suspend", {}, headers)

    # --- Car orders (PRD §3.1, §3.2) ---
    def create_car_order(self, payload, headers):
        return self._request("POST", "/rail/car-orders", payload, headers)

    def list_car_orders(self, headers, params=None):
        return self._request("GET", "/rail/car-orders", params, headers)

    def get_car_order(self, order_id, headers):
        return self._request("GET", f"/rail/car-orders/{order_id}", headers=headers)

    def patch_car_order(self, order_id, payload, headers):
        return self._request("PATCH", f"/rail/car-orders/{order_id}", payload, headers)

    def accept_car_order(self, order_id, headers):
        return self._request("POST", f"/rail/car-orders/{order_id}/accept", {}, headers)

    def furnish_car_order(self, order_id, payload, headers):
        return self._request("POST", f"/rail/car-orders/{order_id}/furnish", payload, headers)

    def release_car_order(self, order_id, headers):
        return self._request("POST", f"/rail/car-orders/{order_id}/release", {}, headers)

    def cancel_car_order(self, order_id, headers):
        return self._request("POST", f"/rail/car-orders/{order_id}/cancel", {}, headers)

    def get_car_order_demurrage(self, order_id, headers):
        return self._request("GET", f"/rail/car-orders/{order_id}/demurrage", headers=headers)

    # --- Railcars (PRD §3.3) ---
    def create_railcar(self, payload, headers):
        return self._request("POST", "/rail/railcars", payload, headers)

    def list_railcars(self, headers, params=None):
        return self._request("GET", "/rail/railcars", params, headers)

    def get_railcar(self, railcar_id, headers):
        return self._request("GET", f"/rail/railcars/{railcar_id}", headers=headers)

    def bad_order_railcar(self, railcar_id, headers):
        return self._request("POST", f"/rail/railcars/{railcar_id}/bad-order", {}, headers)

    def return_railcar_to_service(self, railcar_id, headers):
        return self._request("POST", f"/rail/railcars/{railcar_id}/return-to-service", {}, headers)

    # --- Crew members (PRD §3.7) ---
    def create_crew_member(self, payload, headers):
        return self._request("POST", "/rail/crew-members", payload, headers)

    def list_crew_members(self, headers, params=None):
        return self._request("GET", "/rail/crew-members", params, headers)

    def get_crew_member(self, member_id, headers):
        return self._request("GET", f"/rail/crew-members/{member_id}", headers=headers)

    def adjust_crew_member_hos(self, member_id, payload, headers):
        return self._request("POST", f"/rail/crew-members/{member_id}/adjust-hos", payload, headers)

    # --- Crew calls (PRD §3.7) ---
    def create_crew_call(self, payload, headers):
        return self._request("POST", "/rail/crew-calls", payload, headers)

    def list_crew_calls(self, headers, params=None):
        return self._request("GET", "/rail/crew-calls", params, headers)

    def get_crew_call(self, call_id, headers):
        return self._request("GET", f"/rail/crew-calls/{call_id}", headers=headers)

    def respond_crew_call(self, call_id, payload, headers):
        return self._request("POST", f"/rail/crew-calls/{call_id}/respond", payload, headers)

    def report_crew_call_on_duty(self, call_id, headers):
        return self._request("POST", f"/rail/crew-calls/{call_id}/report-on-duty", {}, headers)

    def relieve_crew_call(self, call_id, headers):
        return self._request("POST", f"/rail/crew-calls/{call_id}/relieve", {}, headers)

    # --- Switch jobs (PRD §3.4) ---
    def create_switch_job(self, payload, headers):
        return self._request("POST", "/rail/switch-jobs", payload, headers)

    def list_switch_jobs(self, headers, params=None):
        return self._request("GET", "/rail/switch-jobs", params, headers)

    def get_switch_job(self, job_id, headers):
        return self._request("GET", f"/rail/switch-jobs/{job_id}", headers=headers)

    def assign_switch_job(self, job_id, payload, headers):
        return self._request("POST", f"/rail/switch-jobs/{job_id}/assign", payload, headers)

    def complete_switch_job(self, job_id, headers):
        return self._request("POST", f"/rail/switch-jobs/{job_id}/complete", {}, headers)

    def annul_switch_job(self, job_id, headers):
        return self._request("POST", f"/rail/switch-jobs/{job_id}/annul", {}, headers)

    # --- Train movements (PRD §3.4) ---
    def create_train_movement(self, payload, headers):
        return self._request("POST", "/rail/train-movements", payload, headers)

    def list_train_movements(self, headers, params=None):
        return self._request("GET", "/rail/train-movements", params, headers)

    def get_train_movement(self, movement_id, headers):
        return self._request("GET", f"/rail/train-movements/{movement_id}", headers=headers)

    def ready_train_movement(self, movement_id, headers):
        return self._request("POST", f"/rail/train-movements/{movement_id}/ready", {}, headers)

    def depart_train_movement(self, movement_id, headers):
        return self._request("POST", f"/rail/train-movements/{movement_id}/depart", {}, headers)

    def hold_train_movement(self, movement_id, headers):
        return self._request("POST", f"/rail/train-movements/{movement_id}/hold", {}, headers)

    def resume_train_movement(self, movement_id, headers):
        return self._request("POST", f"/rail/train-movements/{movement_id}/resume", {}, headers)

    def arrive_train_movement(self, movement_id, headers):
        return self._request("POST", f"/rail/train-movements/{movement_id}/arrive", {}, headers)

    def settle_train_movement(self, movement_id, headers):
        return self._request("POST", f"/rail/train-movements/{movement_id}/settle", {}, headers)

    # --- Interchange events (PRD §3.3) ---
    def create_interchange_event(self, payload, headers):
        return self._request("POST", "/rail/interchange-events", payload, headers)

    def list_interchange_events(self, headers, params=None):
        return self._request("GET", "/rail/interchange-events", params, headers)

    def get_interchange_event(self, event_id, headers):
        return self._request("GET", f"/rail/interchange-events/{event_id}", headers=headers)

    def confirm_interchange_event(self, event_id, headers):
        return self._request("POST", f"/rail/interchange-events/{event_id}/confirm", {}, headers)

    def dispute_interchange_event(self, event_id, headers):
        return self._request("POST", f"/rail/interchange-events/{event_id}/dispute", {}, headers)

    def resolve_interchange_event(self, event_id, headers):
        return self._request("POST", f"/rail/interchange-events/{event_id}/resolve", {}, headers)

    # --- Car hire statements (PRD §3.3) ---
    def list_car_hire_statements(self, headers, params=None):
        return self._request("GET", "/rail/car-hire-statements", params, headers)

    def get_car_hire_statement(self, statement_id, headers):
        return self._request("GET", f"/rail/car-hire-statements/{statement_id}", headers=headers)

    def close_car_hire_statement(self, statement_id, headers):
        return self._request("POST", f"/rail/car-hire-statements/{statement_id}/close", {}, headers)

    def settle_car_hire_statement(self, statement_id, headers):
        return self._request("POST", f"/rail/car-hire-statements/{statement_id}/settle", {}, headers)

    def dispute_car_hire_statement(self, statement_id, headers):
        return self._request("POST", f"/rail/car-hire-statements/{statement_id}/dispute", {}, headers)

    def reopen_car_hire_statement(self, statement_id, headers):
        return self._request("POST", f"/rail/car-hire-statements/{statement_id}/reopen", {}, headers)

    # --- Waybills (PRD §3.5) ---
    def create_waybill(self, payload, headers):
        return self._request("POST", "/rail/waybills", payload, headers)

    def list_waybills(self, headers, params=None):
        return self._request("GET", "/rail/waybills", params, headers)

    def get_waybill(self, waybill_id, headers):
        return self._request("GET", f"/rail/waybills/{waybill_id}", headers=headers)

    def rate_waybill(self, waybill_id, headers):
        return self._request("POST", f"/rail/waybills/{waybill_id}/rate", {}, headers)

    # --- Revenue divisions (PRD §3.5) ---
    def create_revenue_division(self, payload, headers):
        return self._request("POST", "/rail/revenue-divisions", payload, headers)

    def list_revenue_divisions(self, headers, params=None):
        return self._request("GET", "/rail/revenue-divisions", params, headers)

    def get_revenue_division(self, division_id, headers):
        return self._request("GET", f"/rail/revenue-divisions/{division_id}", headers=headers)

    def agree_revenue_division(self, division_id, headers):
        return self._request("POST", f"/rail/revenue-divisions/{division_id}/agree", {}, headers)

    def dispute_revenue_division(self, division_id, headers):
        return self._request("POST", f"/rail/revenue-divisions/{division_id}/dispute", {}, headers)

    def settle_revenue_division(self, division_id, headers):
        return self._request("POST", f"/rail/revenue-divisions/{division_id}/settle", {}, headers)

    # --- Track segments (PRD §3.6) ---
    def create_track_segment(self, payload, headers):
        return self._request("POST", "/rail/track-segments", payload, headers)

    def list_track_segments(self, headers, params=None):
        return self._request("GET", "/rail/track-segments", params, headers)

    def get_track_segment(self, segment_id, headers):
        return self._request("GET", f"/rail/track-segments/{segment_id}", headers=headers)

    def change_track_segment_class(self, segment_id, payload, headers):
        return self._request("POST", f"/rail/track-segments/{segment_id}/change-class", payload, headers)

    # --- Track inspections (PRD §3.6) ---
    def create_track_inspection(self, payload, headers):
        return self._request("POST", "/rail/track-inspections", payload, headers)

    def list_track_inspections(self, headers, params=None):
        return self._request("GET", "/rail/track-inspections", params, headers)

    def get_track_inspection(self, inspection_id, headers):
        return self._request("GET", f"/rail/track-inspections/{inspection_id}", headers=headers)

    def file_track_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/rail/track-inspections/{inspection_id}/file", payload, headers)

    def remediate_track_inspection(self, inspection_id, headers):
        return self._request("POST", f"/rail/track-inspections/{inspection_id}/remediate", {}, headers)

    def waive_track_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/rail/track-inspections/{inspection_id}/waive", payload, headers)

    # --- Incidents (PRD §3.8) ---
    def create_incident(self, payload, headers):
        return self._request("POST", "/rail/incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/rail/incidents", params, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/rail/incidents/{incident_id}", headers=headers)

    def investigate_incident(self, incident_id, headers):
        return self._request("POST", f"/rail/incidents/{incident_id}/investigate", {}, headers)

    def file_incident_fra_report(self, incident_id, headers):
        return self._request("POST", f"/rail/incidents/{incident_id}/file-fra-report", {}, headers)

    def close_incident(self, incident_id, headers):
        return self._request("POST", f"/rail/incidents/{incident_id}/close", {}, headers)

    def reopen_incident(self, incident_id, headers):
        return self._request("POST", f"/rail/incidents/{incident_id}/reopen", {}, headers)

    # --- Grant projects and milestones (PRD §3.9) ---
    def create_grant_project(self, payload, headers):
        return self._request("POST", "/rail/grant-projects", payload, headers)

    def list_grant_projects(self, headers, params=None):
        return self._request("GET", "/rail/grant-projects", params, headers)

    def get_grant_project(self, project_id, headers):
        return self._request("GET", f"/rail/grant-projects/{project_id}", headers=headers)

    def activate_grant_project(self, project_id, headers):
        return self._request("POST", f"/rail/grant-projects/{project_id}/activate", {}, headers)

    def suspend_grant_project(self, project_id, headers):
        return self._request("POST", f"/rail/grant-projects/{project_id}/suspend", {}, headers)

    def resume_grant_project(self, project_id, headers):
        return self._request("POST", f"/rail/grant-projects/{project_id}/resume", {}, headers)

    def create_grant_milestone(self, project_id, payload, headers):
        return self._request("POST", f"/rail/grant-projects/{project_id}/milestones", payload, headers)

    def list_grant_milestones(self, headers, params=None):
        return self._request("GET", "/rail/grant-milestones", params, headers)

    def get_grant_milestone(self, milestone_id, headers):
        return self._request("GET", f"/rail/grant-milestones/{milestone_id}", headers=headers)

    def submit_grant_milestone(self, milestone_id, payload, headers):
        return self._request("POST", f"/rail/grant-milestones/{milestone_id}/submit", payload, headers)

    def approve_grant_milestone(self, milestone_id, headers):
        return self._request("POST", f"/rail/grant-milestones/{milestone_id}/approve", {}, headers)

    def reject_grant_milestone(self, milestone_id, headers):
        return self._request("POST", f"/rail/grant-milestones/{milestone_id}/reject", {}, headers)

    def pay_grant_milestone(self, milestone_id, headers):
        return self._request("POST", f"/rail/grant-milestones/{milestone_id}/pay", {}, headers)


api_client = ApiClient()
