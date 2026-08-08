"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Facility ----
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def list_facility_units(self, facility_id, headers, params=None):
        return self._request("GET", f"/facilities/{facility_id}/units", headers=headers, params=params)

    def create_unit(self, facility_id, payload, headers):
        return self._request("POST", f"/facilities/{facility_id}/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def set_unit_service_status(self, unit_id, payload, headers):
        return self._request("POST", f"/units/{unit_id}/set-service-status", payload, headers)

    # ---- Member ----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_member_vehicles(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/vehicles", headers=headers, params=params)

    def list_member_waitlist(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/waitlist", headers=headers, params=params)

    def record_payment(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/record-payment", payload, headers)

    def refresh_billing(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/refresh-billing", {}, headers)

    # ---- Vehicle ----
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def list_vehicle_coi(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/vehicles/{vehicle_id}/coi", headers=headers, params=params)

    def list_vehicle_inspections(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/vehicles/{vehicle_id}/inspections", headers=headers, params=params)

    def refresh_insurance(self, vehicle_id, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/refresh-insurance", {}, headers)

    def create_coi(self, vehicle_id, payload, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/coi", payload, headers)

    def revoke_coi(self, coi_id, headers):
        return self._request("POST", f"/coi/{coi_id}/revoke", {}, headers)

    # ---- StorageAgreement ----
    def create_agreement(self, payload, headers):
        return self._request("POST", "/storage-agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/storage-agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/storage-agreements", headers=headers, params=params)

    def move_in(self, agreement_id, headers):
        return self._request("POST", f"/storage-agreements/{agreement_id}/move-in", {}, headers)

    def check_out(self, agreement_id, headers):
        return self._request("POST", f"/storage-agreements/{agreement_id}/check-out", {}, headers)

    def check_in(self, agreement_id, headers):
        return self._request("POST", f"/storage-agreements/{agreement_id}/check-in", {}, headers)

    def terminate(self, agreement_id, headers):
        return self._request("POST", f"/storage-agreements/{agreement_id}/terminate", {}, headers)

    def cancel_agreement(self, agreement_id, headers):
        return self._request("POST", f"/storage-agreements/{agreement_id}/cancel", {}, headers)

    # ---- MonitoringSubscription ----
    def create_monitoring(self, agreement_id, payload, headers):
        return self._request("POST", f"/storage-agreements/{agreement_id}/monitoring", payload, headers)

    def list_monitoring(self, agreement_id, headers, params=None):
        return self._request("GET", f"/storage-agreements/{agreement_id}/monitoring", headers=headers, params=params)

    def record_reading(self, monitoring_id, payload, headers):
        return self._request("POST", f"/monitoring/{monitoring_id}/record-reading", payload, headers)

    # ---- ServiceOrder ----
    def create_service_order(self, payload, headers):
        return self._request("POST", "/service-orders", payload, headers)

    def list_service_orders(self, agreement_id, headers, params=None):
        return self._request("GET", f"/storage-agreements/{agreement_id}/service-orders", headers=headers, params=params)

    def get_service_order(self, service_order_id, headers):
        return self._request("GET", f"/service-orders/{service_order_id}", headers=headers)

    def approve_service_order(self, service_order_id, payload, headers):
        return self._request("POST", f"/service-orders/{service_order_id}/approve", payload, headers)

    def reject_service_order(self, service_order_id, headers):
        return self._request("POST", f"/service-orders/{service_order_id}/reject", {}, headers)

    def start_service_order(self, service_order_id, headers):
        return self._request("POST", f"/service-orders/{service_order_id}/start", {}, headers)

    def hold_service_order(self, service_order_id, headers):
        return self._request("POST", f"/service-orders/{service_order_id}/hold", {}, headers)

    def complete_service_order(self, service_order_id, payload, headers):
        return self._request("POST", f"/service-orders/{service_order_id}/complete", payload, headers)

    def cancel_service_order(self, service_order_id, headers):
        return self._request("POST", f"/service-orders/{service_order_id}/cancel", {}, headers)

    # ---- Transporter ----
    def create_transporter(self, payload, headers):
        return self._request("POST", "/transporters", payload, headers)

    def get_transporter(self, transporter_id, headers):
        return self._request("GET", f"/transporters/{transporter_id}", headers=headers)

    # ---- DeliveryJob ----
    def create_delivery_job(self, payload, headers):
        return self._request("POST", "/delivery-jobs", payload, headers)

    def get_delivery_job(self, delivery_job_id, headers):
        return self._request("GET", f"/delivery-jobs/{delivery_job_id}", headers=headers)

    def list_delivery_jobs(self, headers, params=None):
        return self._request("GET", "/delivery-jobs", headers=headers, params=params)

    def dispatch_delivery_job(self, delivery_job_id, headers):
        return self._request("POST", f"/delivery-jobs/{delivery_job_id}/dispatch", {}, headers)

    def return_delivery_job(self, delivery_job_id, headers):
        return self._request("POST", f"/delivery-jobs/{delivery_job_id}/return", {}, headers)

    def cancel_delivery_job(self, delivery_job_id, headers):
        return self._request("POST", f"/delivery-jobs/{delivery_job_id}/cancel", {}, headers)

    # ---- WaitlistEntry ----
    def create_waitlist(self, payload, headers):
        return self._request("POST", "/waitlist", payload, headers)

    def get_waitlist(self, waitlist_id, headers):
        return self._request("GET", f"/waitlist/{waitlist_id}", headers=headers)

    def list_waitlist(self, headers, params=None):
        return self._request("GET", "/waitlist", headers=headers, params=params)

    def claim_waitlist(self, waitlist_id, headers):
        return self._request("POST", f"/waitlist/{waitlist_id}/claim", {}, headers)

    def cancel_waitlist(self, waitlist_id, headers):
        return self._request("POST", f"/waitlist/{waitlist_id}/cancel", {}, headers)

    def refresh_offer(self, waitlist_id, headers):
        return self._request("POST", f"/waitlist/{waitlist_id}/refresh-offer", {}, headers)

    # ---- Inspection ----
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def pass_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/pass", payload, headers)

    def fail_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/fail", payload, headers)

    # ---- Invoice ----
    def generate_invoice(self, payload, headers):
        return self._request("POST", "/invoices/generate", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", {}, headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)

    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
