"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/api/customers", headers=headers, params=params)

    # --- fields ---
    def create_field(self, payload, headers):
        return self._request("POST", "/api/fields", payload, headers)

    def get_field(self, field_id, headers):
        return self._request("GET", f"/api/fields/{field_id}", headers=headers)

    def list_fields(self, headers, params=None):
        return self._request("GET", "/api/fields", headers=headers, params=params)

    # --- products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/api/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/api/products/{product_id}", headers=headers)

    # --- compatibility rules ---
    def create_compatibility_rule(self, payload, headers):
        return self._request("POST", "/api/compatibility-rules", payload, headers)

    def get_compatibility_rule(self, rule_id, headers):
        return self._request("GET", f"/api/compatibility-rules/{rule_id}", headers=headers)

    def list_compatibility_rules(self, headers, params=None):
        return self._request("GET", "/api/compatibility-rules", headers=headers, params=params)

    # --- prescriptions ---
    def create_prescription(self, payload, headers):
        return self._request("POST", "/api/prescriptions", payload, headers)

    def get_prescription(self, prescription_id, headers):
        return self._request("GET", f"/api/prescriptions/{prescription_id}", headers=headers)

    def list_prescriptions(self, headers, params=None):
        return self._request("GET", "/api/prescriptions", headers=headers, params=params)

    def approve_prescription(self, prescription_id, payload, headers):
        return self._request("POST", f"/api/prescriptions/{prescription_id}/approve", payload, headers)

    # --- applicators ---
    def create_applicator(self, payload, headers):
        return self._request("POST", "/api/applicators", payload, headers)

    def get_applicator(self, applicator_id, headers):
        return self._request("GET", f"/api/applicators/{applicator_id}", headers=headers)

    def reinstate_applicator(self, applicator_id, headers):
        return self._request("POST", f"/api/applicators/{applicator_id}/reinstate", headers=headers)

    # --- equipment ---
    def create_equipment(self, payload, headers):
        return self._request("POST", "/api/equipment", payload, headers)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/api/equipment/{equipment_id}", headers=headers)

    # --- calibration records ---
    def create_calibration_record(self, payload, headers):
        return self._request("POST", "/api/calibration-records", payload, headers)

    def get_calibration_record(self, record_id, headers):
        return self._request("GET", f"/api/calibration-records/{record_id}", headers=headers)

    def list_calibration_records(self, headers, params=None):
        return self._request("GET", "/api/calibration-records", headers=headers, params=params)

    # --- weather observations ---
    def create_weather_observation(self, payload, headers):
        return self._request("POST", "/api/weather-observations", payload, headers)

    def list_weather_observations(self, headers, params=None):
        return self._request("GET", "/api/weather-observations", headers=headers, params=params)

    # --- work orders ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/api/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/api/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/api/work-orders", headers=headers, params=params)

    def schedule_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/api/work-orders/{work_order_id}/schedule", payload, headers)

    def reschedule_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/api/work-orders/{work_order_id}/reschedule", payload, headers)

    def start_work_order(self, work_order_id, headers):
        return self._request("POST", f"/api/work-orders/{work_order_id}/start", headers=headers)

    def resume_work_order(self, work_order_id, headers):
        return self._request("POST", f"/api/work-orders/{work_order_id}/resume", headers=headers)

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/api/work-orders/{work_order_id}/complete", payload, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/api/work-orders/{work_order_id}/cancel", headers=headers)

    def close_work_order(self, work_order_id, headers):
        return self._request("POST", f"/api/work-orders/{work_order_id}/close", headers=headers)

    # --- application records ---
    def get_application_record(self, record_id, headers):
        return self._request("GET", f"/api/application-records/{record_id}", headers=headers)

    def list_application_records(self, headers, params=None):
        return self._request("GET", "/api/application-records", headers=headers, params=params)

    def certify_application_record(self, record_id, headers):
        return self._request("POST", f"/api/application-records/{record_id}/certify", headers=headers)

    def return_application_record(self, record_id, payload, headers):
        return self._request("POST", f"/api/application-records/{record_id}/return", payload, headers)

    def resubmit_application_record(self, record_id, payload, headers):
        return self._request("POST", f"/api/application-records/{record_id}/resubmit", payload, headers)

    # --- rinsate records ---
    def create_rinsate_record(self, payload, headers):
        return self._request("POST", "/api/rinsate-records", payload, headers)

    def get_rinsate_record(self, record_id, headers):
        return self._request("GET", f"/api/rinsate-records/{record_id}", headers=headers)

    def list_rinsate_records(self, headers, params=None):
        return self._request("GET", "/api/rinsate-records", headers=headers, params=params)

    # --- drift complaints ---
    def create_drift_complaint(self, payload, headers):
        return self._request("POST", "/api/drift-complaints", payload, headers)

    def get_drift_complaint(self, complaint_id, headers):
        return self._request("GET", f"/api/drift-complaints/{complaint_id}", headers=headers)

    def list_drift_complaints(self, headers, params=None):
        return self._request("GET", "/api/drift-complaints", headers=headers, params=params)

    def open_complaint_investigation(self, complaint_id, headers):
        return self._request("POST", f"/api/drift-complaints/{complaint_id}/open-investigation", headers=headers)

    def substantiate_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/api/drift-complaints/{complaint_id}/substantiate", payload, headers)

    def dismiss_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/api/drift-complaints/{complaint_id}/dismiss", payload, headers)

    # --- invoices ---
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/api/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/issue", headers=headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/pay", headers=headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/void", headers=headers)


api_client = ApiClient()
