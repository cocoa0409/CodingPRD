"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Customers ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customer_vehicles(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/vehicles", headers=headers, params=params)

    def list_customer_work_orders(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/work-orders", headers=headers, params=params)

    # ---- Vehicles ----
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def list_vehicle_work_orders(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/vehicles/{vehicle_id}/work-orders", headers=headers, params=params)

    # ---- Glass parts ----
    def create_glass_part(self, payload, headers):
        return self._request("POST", "/glass-parts", payload, headers)

    def get_glass_part(self, glass_part_id, headers):
        return self._request("GET", f"/glass-parts/{glass_part_id}", headers=headers)

    def list_glass_parts(self, headers, params=None):
        return self._request("GET", "/glass-parts", headers=headers, params=params)

    def restock_glass_part(self, glass_part_id, payload, headers):
        return self._request("PATCH", f"/glass-parts/{glass_part_id}/restock", payload, headers)

    # ---- Technicians ----
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    # ---- Service bays ----
    def create_service_bay(self, payload, headers):
        return self._request("POST", "/service-bays", payload, headers)

    def get_service_bay(self, service_bay_id, headers):
        return self._request("GET", f"/service-bays/{service_bay_id}", headers=headers)

    # ---- Work orders ----
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def create_damage_assessment(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/damage-assessments", payload, headers)

    def list_damage_assessments(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/damage-assessments", headers=headers, params=params)

    def accept_assessment(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/accept-assessment", payload, headers)

    def schedule_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/schedule", payload, headers)

    def start_service(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/start-service", {}, headers)

    def finish_install(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/finish-install", payload, headers)

    def complete_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/complete", {}, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", {}, headers)

    def get_sdat_estimate(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}/sdat-estimate", headers=headers)

    def list_work_order_part_orders(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/part-orders", headers=headers, params=params)

    def list_work_order_payments(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/payments", headers=headers, params=params)

    def list_work_order_appointments(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/appointments", headers=headers, params=params)

    def list_work_order_recalibration_jobs(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/recalibration-jobs", headers=headers, params=params)

    def list_work_order_warranties(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/warranties", headers=headers, params=params)

    # ---- Part orders ----
    def create_part_order(self, payload, headers):
        return self._request("POST", "/part-orders", payload, headers)

    def get_part_order(self, part_order_id, headers):
        return self._request("GET", f"/part-orders/{part_order_id}", headers=headers)

    def list_part_orders(self, headers, params=None):
        return self._request("GET", "/part-orders", headers=headers, params=params)

    def receive_part_order(self, part_order_id, headers):
        return self._request("POST", f"/part-orders/{part_order_id}/receive", {}, headers)

    # ---- Service appointments ----
    def create_service_appointment(self, payload, headers):
        return self._request("POST", "/service-appointments", payload, headers)

    def get_service_appointment(self, appointment_id, headers):
        return self._request("GET", f"/service-appointments/{appointment_id}", headers=headers)

    def list_service_appointments(self, headers, params=None):
        return self._request("GET", "/service-appointments", headers=headers, params=params)

    def check_in_appointment(self, appointment_id, headers):
        return self._request("POST", f"/service-appointments/{appointment_id}/check-in", {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/service-appointments/{appointment_id}/cancel", {}, headers)

    # ---- Recalibration jobs ----
    def create_recalibration_job(self, payload, headers):
        return self._request("POST", "/recalibration-jobs", payload, headers)

    def get_recalibration_job(self, job_id, headers):
        return self._request("GET", f"/recalibration-jobs/{job_id}", headers=headers)

    def list_recalibration_jobs(self, headers, params=None):
        return self._request("GET", "/recalibration-jobs", headers=headers, params=params)

    def pass_recalibration_job(self, job_id, headers):
        return self._request("POST", f"/recalibration-jobs/{job_id}/pass", {}, headers)

    def fail_recalibration_job(self, job_id, headers):
        return self._request("POST", f"/recalibration-jobs/{job_id}/fail", {}, headers)

    def retry_recalibration_job(self, job_id, headers):
        return self._request("POST", f"/recalibration-jobs/{job_id}/retry", {}, headers)

    def cancel_recalibration_job(self, job_id, headers):
        return self._request("POST", f"/recalibration-jobs/{job_id}/cancel", {}, headers)

    # ---- Payments ----
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def refund_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/refund", {}, headers)

    # ---- Warranties ----
    def get_warranty(self, warranty_id, headers):
        return self._request("GET", f"/warranties/{warranty_id}", headers=headers)

    def void_warranty(self, warranty_id, headers):
        return self._request("POST", f"/warranties/{warranty_id}/void", {}, headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
