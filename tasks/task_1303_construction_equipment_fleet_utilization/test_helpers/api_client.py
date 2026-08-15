"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        # The per-test-server isolation kills (SIGKILL) and respawns the server
        # before every test. A pooled keep-alive connection can then be reused
        # against a dead socket and surface as a rare ConnectionResetError.
        # Connection: close forces a fresh TCP connection per request.
        self.session.headers["Connection"] = "close"


    # --- Clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/fleet/_clock/set_current_utc", payload, headers)

    # --- EquipmentClass ---
    def create_equipment_class(self, payload, headers):
        return self._request("POST", "/fleet/equipment-classes", payload, headers)

    def get_equipment_class(self, class_id, headers):
        return self._request("GET", f"/fleet/equipment-classes/{class_id}", headers=headers)

    def list_equipment_classes(self, headers, params=None):
        return self._request("GET", "/fleet/equipment-classes", headers=headers, params=params)

    # --- Equipment ---
    def create_equipment(self, payload, headers):
        return self._request("POST", "/fleet/equipment", payload, headers)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/fleet/equipment/{equipment_id}", headers=headers)

    def list_equipment(self, headers, params=None):
        return self._request("GET", "/fleet/equipment", headers=headers, params=params)

    def mark_down_equipment(self, equipment_id, headers):
        return self._request("POST", f"/fleet/equipment/{equipment_id}/mark-down", headers=headers)

    def dispose_equipment(self, equipment_id, payload, headers):
        return self._request("POST", f"/fleet/equipment/{equipment_id}/dispose", payload, headers)

    def get_redeployment_score(self, equipment_id, headers):
        return self._request("GET", f"/fleet/equipment/{equipment_id}/redeployment-score", headers=headers)

    def get_fuel_summary(self, equipment_id, headers, params=None):
        return self._request("GET", f"/fleet/equipment/{equipment_id}/fuel-summary",
                             headers=headers, params=params)

    # --- Telematics ---
    def create_reading(self, equipment_id, payload, headers):
        return self._request("POST", f"/fleet/equipment/{equipment_id}/readings", payload, headers)

    def void_reading(self, reading_id, payload, headers):
        return self._request("POST", f"/fleet/readings/{reading_id}/void", payload, headers)

    def list_equipment_readings(self, equipment_id, headers, params=None):
        return self._request("GET", f"/fleet/equipment/{equipment_id}/readings",
                             headers=headers, params=params)

    # --- Equipment sub-resource listings ---
    def list_equipment_assignments(self, equipment_id, headers, params=None):
        return self._request("GET", f"/fleet/equipment/{equipment_id}/assignments",
                             headers=headers, params=params)

    def list_equipment_work_orders(self, equipment_id, headers, params=None):
        return self._request("GET", f"/fleet/equipment/{equipment_id}/work-orders",
                             headers=headers, params=params)

    def list_equipment_damage_reports(self, equipment_id, headers, params=None):
        return self._request("GET", f"/fleet/equipment/{equipment_id}/damage-reports",
                             headers=headers, params=params)

    def list_equipment_transport_jobs(self, equipment_id, headers, params=None):
        return self._request("GET", f"/fleet/equipment/{equipment_id}/transport-jobs",
                             headers=headers, params=params)

    # --- Project ---
    def create_project(self, payload, headers):
        return self._request("POST", "/fleet/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/fleet/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/fleet/projects", headers=headers, params=params)

    def suspend_project(self, project_id, headers):
        return self._request("POST", f"/fleet/projects/{project_id}/suspend", headers=headers)

    def resume_project(self, project_id, headers):
        return self._request("POST", f"/fleet/projects/{project_id}/resume", headers=headers)

    def close_project(self, project_id, headers):
        return self._request("POST", f"/fleet/projects/{project_id}/close", headers=headers)

    def list_project_assignments(self, project_id, headers, params=None):
        return self._request("GET", f"/fleet/projects/{project_id}/assignments",
                             headers=headers, params=params)

    def list_project_damage_reports(self, project_id, headers, params=None):
        return self._request("GET", f"/fleet/projects/{project_id}/damage-reports",
                             headers=headers, params=params)

    def list_project_charges(self, project_id, headers, params=None):
        return self._request("GET", f"/fleet/projects/{project_id}/charges",
                             headers=headers, params=params)

    def list_project_transport_jobs(self, project_id, headers, params=None):
        return self._request("GET", f"/fleet/projects/{project_id}/transport-jobs",
                             headers=headers, params=params)

    def list_project_mechanics(self, project_id, headers, params=None):
        return self._request("GET", f"/fleet/projects/{project_id}/mechanics",
                             headers=headers, params=params)

    # --- Assignment ---
    def create_assignment(self, payload, headers):
        return self._request("POST", "/fleet/assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/fleet/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/fleet/assignments", headers=headers, params=params)

    def activate_assignment(self, assignment_id, headers):
        return self._request("POST", f"/fleet/assignments/{assignment_id}/activate", headers=headers)

    def close_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/fleet/assignments/{assignment_id}/close", payload, headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"/fleet/assignments/{assignment_id}/cancel", headers=headers)

    def list_assignment_charges(self, assignment_id, headers, params=None):
        return self._request("GET", f"/fleet/assignments/{assignment_id}/charges",
                             headers=headers, params=params)

    # --- WorkOrder ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/fleet/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/fleet/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/fleet/work-orders", headers=headers, params=params)

    def dispatch_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/fleet/work-orders/{work_order_id}/dispatch",
                             payload, headers)

    def start_work_order(self, work_order_id, headers):
        return self._request("POST", f"/fleet/work-orders/{work_order_id}/start", headers=headers)

    def complete_work_order(self, work_order_id, headers):
        return self._request("POST", f"/fleet/work-orders/{work_order_id}/complete", headers=headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/fleet/work-orders/{work_order_id}/cancel", headers=headers)

    # --- Mechanic ---
    def create_mechanic(self, payload, headers):
        return self._request("POST", "/fleet/mechanics", payload, headers)

    def get_mechanic(self, mechanic_id, headers):
        return self._request("GET", f"/fleet/mechanics/{mechanic_id}", headers=headers)

    def list_mechanics(self, headers, params=None):
        return self._request("GET", "/fleet/mechanics", headers=headers, params=params)

    def off_duty_mechanic(self, mechanic_id, headers):
        return self._request("POST", f"/fleet/mechanics/{mechanic_id}/off-duty", headers=headers)

    def on_duty_mechanic(self, mechanic_id, headers):
        return self._request("POST", f"/fleet/mechanics/{mechanic_id}/on-duty", headers=headers)

    # --- Lowboy ---
    def create_lowboy(self, payload, headers):
        return self._request("POST", "/fleet/lowboys", payload, headers)

    def get_lowboy(self, lowboy_id, headers):
        return self._request("GET", f"/fleet/lowboys/{lowboy_id}", headers=headers)

    def list_lowboys(self, headers, params=None):
        return self._request("GET", "/fleet/lowboys", headers=headers, params=params)

    def out_of_service_lowboy(self, lowboy_id, headers):
        return self._request("POST", f"/fleet/lowboys/{lowboy_id}/out-of-service", headers=headers)

    def return_to_service_lowboy(self, lowboy_id, headers):
        return self._request("POST", f"/fleet/lowboys/{lowboy_id}/return-to-service", headers=headers)

    def list_lowboy_transport_jobs(self, lowboy_id, headers, params=None):
        return self._request("GET", f"/fleet/lowboys/{lowboy_id}/transport-jobs",
                             headers=headers, params=params)

    # --- TransportJob ---
    def create_transport_job(self, payload, headers):
        return self._request("POST", "/fleet/transport-jobs", payload, headers)

    def get_transport_job(self, transport_job_id, headers):
        return self._request("GET", f"/fleet/transport-jobs/{transport_job_id}", headers=headers)

    def list_transport_jobs(self, headers, params=None):
        return self._request("GET", "/fleet/transport-jobs", headers=headers, params=params)

    def depart_transport_job(self, transport_job_id, headers):
        return self._request("POST", f"/fleet/transport-jobs/{transport_job_id}/depart",
                             headers=headers)

    def deliver_transport_job(self, transport_job_id, headers):
        return self._request("POST", f"/fleet/transport-jobs/{transport_job_id}/deliver",
                             headers=headers)

    def cancel_transport_job(self, transport_job_id, headers):
        return self._request("POST", f"/fleet/transport-jobs/{transport_job_id}/cancel",
                             headers=headers)

    # --- DamageReport ---
    def create_damage_report(self, payload, headers):
        return self._request("POST", "/fleet/damage-reports", payload, headers)

    def get_damage_report(self, damage_report_id, headers):
        return self._request("GET", f"/fleet/damage-reports/{damage_report_id}", headers=headers)

    def list_damage_reports(self, headers, params=None):
        return self._request("GET", "/fleet/damage-reports", headers=headers, params=params)

    def assess_damage_report(self, damage_report_id, headers):
        return self._request("POST", f"/fleet/damage-reports/{damage_report_id}/assess",
                             headers=headers)

    def dispute_damage_report(self, damage_report_id, payload, headers):
        return self._request("POST", f"/fleet/damage-reports/{damage_report_id}/dispute",
                             payload, headers)

    def reassess_damage_report(self, damage_report_id, payload, headers):
        return self._request("POST", f"/fleet/damage-reports/{damage_report_id}/reassess",
                             payload, headers)

    def confirm_damage_report(self, damage_report_id, headers):
        return self._request("POST", f"/fleet/damage-reports/{damage_report_id}/confirm",
                             headers=headers)

    def void_damage_report(self, damage_report_id, headers):
        return self._request("POST", f"/fleet/damage-reports/{damage_report_id}/void",
                             headers=headers)


api_client = ApiClient()
