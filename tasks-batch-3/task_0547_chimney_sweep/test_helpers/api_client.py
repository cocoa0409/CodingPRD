"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ---- Chimney ----
    def create_chimney(self, payload, headers):
        return self._request("POST", "/chimneys", payload, headers)

    def get_chimney(self, chimney_id, headers):
        return self._request("GET", f"/chimneys/{chimney_id}", headers=headers)

    def list_chimneys(self, headers, params=None):
        return self._request("GET", "/chimneys", headers=headers, params=params)

    # ---- Technician ----
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    # ---- RouteDay ----
    def create_route_day(self, payload, headers):
        return self._request("POST", "/route-days", payload, headers)

    def get_route_day(self, route_day_id, headers):
        return self._request("GET", f"/route-days/{route_day_id}", headers=headers)

    def list_route_days(self, headers, params=None):
        return self._request("GET", "/route-days", headers=headers, params=params)

    # ---- ServiceJob ----
    def create_service_job(self, payload, headers):
        return self._request("POST", "/service-jobs", payload, headers)

    def get_service_job(self, job_id, headers):
        return self._request("GET", f"/service-jobs/{job_id}", headers=headers)

    def list_service_jobs(self, headers, params=None):
        return self._request("GET", "/service-jobs", headers=headers, params=params)

    def inspect_service_job(self, job_id, payload, headers):
        return self._request("POST", f"/service-jobs/{job_id}/inspect", payload, headers)

    def sweep_service_job(self, job_id, payload, headers):
        return self._request("POST", f"/service-jobs/{job_id}/sweep", payload, headers)

    def safety_check_service_job(self, job_id, payload, headers):
        return self._request("POST", f"/service-jobs/{job_id}/safety-check", payload, headers)

    def list_sweep_logs(self, job_id, headers, params=None):
        return self._request("GET", f"/service-jobs/{job_id}/sweep-logs", headers=headers, params=params)

    def list_safety_checks(self, job_id, headers, params=None):
        return self._request("GET", f"/service-jobs/{job_id}/safety-checks", headers=headers, params=params)

    def complete_service_job(self, job_id, headers):
        return self._request("POST", f"/service-jobs/{job_id}/complete", {}, headers)

    def cancel_service_job(self, job_id, headers):
        return self._request("POST", f"/service-jobs/{job_id}/cancel", {}, headers)

    # ---- Appointment ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def get_appointment(self, appt_id, headers):
        return self._request("GET", f"/appointments/{appt_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def transition_appointment(self, appt_id, payload, headers):
        return self._request("POST", f"/appointments/{appt_id}/transitions", payload, headers)

    # ---- RepairOrder ----
    def create_repair_order(self, payload, headers):
        return self._request("POST", "/repair-orders", payload, headers)

    def get_repair_order(self, ro_id, headers):
        return self._request("GET", f"/repair-orders/{ro_id}", headers=headers)

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/repair-orders", headers=headers, params=params)

    def transition_repair_order(self, ro_id, payload, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/transitions", payload, headers)

    # ---- Warranty ----
    def create_warranty(self, payload, headers):
        return self._request("POST", "/warranties", payload, headers)

    def get_warranty(self, warranty_id, headers):
        return self._request("GET", f"/warranties/{warranty_id}", headers=headers)

    def list_warranties(self, headers, params=None):
        return self._request("GET", "/warranties", headers=headers, params=params)

    def file_claim_warranty(self, warranty_id, payload, headers):
        return self._request("POST", f"/warranties/{warranty_id}/file-claim", payload, headers)

    # ---- ReminderSchedule ----
    def create_reminder_schedule(self, payload, headers):
        return self._request("POST", "/reminder-schedules", payload, headers)

    def get_reminder_schedule(self, reminder_id, headers):
        return self._request("GET", f"/reminder-schedules/{reminder_id}", headers=headers)

    def list_reminder_schedules(self, headers, params=None):
        return self._request("GET", "/reminder-schedules", headers=headers, params=params)

    def acknowledge_reminder_schedule(self, reminder_id, headers):
        return self._request("POST", f"/reminder-schedules/{reminder_id}/acknowledge", {}, headers)

    # ---- Test-driving logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
