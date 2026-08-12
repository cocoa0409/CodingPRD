"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/hazmat/_clock/set_current_utc", payload, headers)

    # --- Carrier ---
    def create_carrier(self, payload, headers):
        return self._request("POST", "/hazmat/carriers", payload, headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", "/hazmat/carriers", headers=headers, params=params)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/hazmat/carriers/{carrier_id}", headers=headers)

    def submit_registration(self, carrier_id, payload, headers):
        return self._request("POST", f"/hazmat/carriers/{carrier_id}/registration/submit", payload, headers)

    def approve_registration(self, carrier_id, payload, headers):
        return self._request("POST", f"/hazmat/carriers/{carrier_id}/registration/approve", payload, headers)

    def suspend_carrier(self, carrier_id, headers):
        return self._request("POST", f"/hazmat/carriers/{carrier_id}/suspend", {}, headers)

    def reinstate_carrier(self, carrier_id, headers):
        return self._request("POST", f"/hazmat/carriers/{carrier_id}/reinstate", {}, headers)

    def pay_carrier(self, carrier_id, payload, headers):
        return self._request("POST", f"/hazmat/carriers/{carrier_id}/payments", payload, headers)

    def list_carrier_invoices(self, carrier_id, headers, params=None):
        return self._request("GET", f"/hazmat/carriers/{carrier_id}/registration-invoices", headers=headers, params=params)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/hazmat/registration-invoices/{invoice_id}/void", {}, headers)

    # --- SecurityPlan ---
    def create_security_plan(self, carrier_id, payload, headers):
        return self._request("POST", f"/hazmat/carriers/{carrier_id}/security-plans", payload, headers)

    def list_security_plans(self, carrier_id, headers, params=None):
        return self._request("GET", f"/hazmat/carriers/{carrier_id}/security-plans", headers=headers, params=params)

    def submit_security_plan(self, plan_id, headers):
        return self._request("POST", f"/hazmat/security-plans/{plan_id}/submit", {}, headers)

    def approve_security_plan(self, plan_id, headers):
        return self._request("POST", f"/hazmat/security-plans/{plan_id}/approve", {}, headers)

    def reject_security_plan(self, plan_id, headers):
        return self._request("POST", f"/hazmat/security-plans/{plan_id}/reject", {}, headers)

    def revise_security_plan(self, plan_id, headers):
        return self._request("POST", f"/hazmat/security-plans/{plan_id}/revise", {}, headers)

    # --- HazmatMaterial (catalog) ---
    def create_material(self, payload, headers):
        return self._request("POST", "/hazmat/hazmat-materials", payload, headers)

    def list_materials(self, headers, params=None):
        return self._request("GET", "/hazmat/hazmat-materials", headers=headers, params=params)

    # --- PackagingSpec (catalog) ---
    def create_packaging_spec(self, payload, headers):
        return self._request("POST", "/hazmat/packaging-specs", payload, headers)

    def list_packaging_specs(self, headers, params=None):
        return self._request("GET", "/hazmat/packaging-specs", headers=headers, params=params)

    def retire_packaging_spec(self, spec_id, headers):
        return self._request("POST", f"/hazmat/packaging-specs/{spec_id}/retire", {}, headers)

    # --- Driver ---
    def create_driver(self, carrier_id, payload, headers):
        return self._request("POST", f"/hazmat/carriers/{carrier_id}/drivers", payload, headers)

    def list_drivers(self, carrier_id, headers, params=None):
        return self._request("GET", f"/hazmat/carriers/{carrier_id}/drivers", headers=headers, params=params)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/hazmat/drivers/{driver_id}", headers=headers)

    def create_training_record(self, driver_id, payload, headers):
        return self._request("POST", f"/hazmat/drivers/{driver_id}/training-records", payload, headers)

    def list_training_records(self, driver_id, headers, params=None):
        return self._request("GET", f"/hazmat/drivers/{driver_id}/training-records", headers=headers, params=params)

    # --- Vehicle ---
    def create_vehicle(self, carrier_id, payload, headers):
        return self._request("POST", f"/hazmat/carriers/{carrier_id}/vehicles", payload, headers)

    def list_vehicles(self, carrier_id, headers, params=None):
        return self._request("GET", f"/hazmat/carriers/{carrier_id}/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/hazmat/vehicles/{vehicle_id}", headers=headers)

    # --- Shipment ---
    def create_shipment(self, carrier_id, payload, headers):
        return self._request("POST", f"/hazmat/carriers/{carrier_id}/shipments", payload, headers)

    def list_carrier_shipments(self, carrier_id, headers, params=None):
        return self._request("GET", f"/hazmat/carriers/{carrier_id}/shipments", headers=headers, params=params)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/hazmat/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/hazmat/shipments/{shipment_id}", headers=headers)

    def amend_shipment(self, shipment_id, payload, headers):
        return self._request("PATCH", f"/hazmat/shipments/{shipment_id}", payload, headers)

    def classify_shipment(self, shipment_id, headers):
        return self._request("POST", f"/hazmat/shipments/{shipment_id}/classify", {}, headers)

    def verify_packaging(self, shipment_id, headers):
        return self._request("POST", f"/hazmat/shipments/{shipment_id}/verify-packaging", {}, headers)

    def document_shipment(self, shipment_id, headers):
        return self._request("POST", f"/hazmat/shipments/{shipment_id}/document", {}, headers)

    def reject_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/hazmat/shipments/{shipment_id}/reject", payload, headers)

    def rework_shipment(self, shipment_id, headers):
        return self._request("POST", f"/hazmat/shipments/{shipment_id}/rework", {}, headers)

    def tender_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/hazmat/shipments/{shipment_id}/tender", payload, headers)

    def cancel_shipment(self, shipment_id, headers):
        return self._request("POST", f"/hazmat/shipments/{shipment_id}/cancel", {}, headers)

    def list_shipment_load_items(self, shipment_id, headers, params=None):
        return self._request("GET", f"/hazmat/shipments/{shipment_id}/load-items", headers=headers, params=params)

    # --- ShippingPaper ---
    def create_shipping_paper(self, shipment_id, payload, headers):
        return self._request("POST", f"/hazmat/shipments/{shipment_id}/shipping-papers", payload, headers)

    def list_shipping_papers(self, shipment_id, headers, params=None):
        return self._request("GET", f"/hazmat/shipments/{shipment_id}/shipping-papers", headers=headers, params=params)

    def certify_shipping_paper(self, paper_id, headers):
        return self._request("POST", f"/hazmat/shipping-papers/{paper_id}/certify", {}, headers)

    def amend_shipping_paper(self, paper_id, payload, headers):
        return self._request("POST", f"/hazmat/shipping-papers/{paper_id}/amend", payload, headers)

    # --- VehicleLoad / LoadItem ---
    def create_load(self, vehicle_id, payload, headers):
        return self._request("POST", f"/hazmat/vehicles/{vehicle_id}/loads", payload, headers)

    def list_loads(self, headers, params=None):
        return self._request("GET", "/hazmat/vehicle-loads", headers=headers, params=params)

    def get_load(self, load_id, headers):
        return self._request("GET", f"/hazmat/vehicle-loads/{load_id}", headers=headers)

    def list_load_items(self, load_id, headers, params=None):
        return self._request("GET", f"/hazmat/vehicle-loads/{load_id}/items", headers=headers, params=params)

    def add_load_item(self, load_id, payload, headers):
        return self._request("POST", f"/hazmat/vehicle-loads/{load_id}/items", payload, headers)

    def remove_load_item(self, load_id, shipment_id, headers):
        return self._request("DELETE", f"/hazmat/vehicle-loads/{load_id}/items/{shipment_id}", headers=headers)

    def seal_load(self, load_id, headers):
        return self._request("POST", f"/hazmat/vehicle-loads/{load_id}/seal", {}, headers)

    def unseal_load(self, load_id, headers):
        return self._request("POST", f"/hazmat/vehicle-loads/{load_id}/unseal", {}, headers)

    def dispatch_load(self, load_id, headers):
        return self._request("POST", f"/hazmat/vehicle-loads/{load_id}/dispatch", {}, headers)

    def arrive_load(self, load_id, headers):
        return self._request("POST", f"/hazmat/vehicle-loads/{load_id}/arrive", {}, headers)

    def void_load(self, load_id, headers):
        return self._request("POST", f"/hazmat/vehicle-loads/{load_id}/void", {}, headers)

    # --- Route ---
    def create_route(self, payload, headers):
        return self._request("POST", "/hazmat/routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/hazmat/routes", headers=headers, params=params)

    # --- IncidentReport ---
    def create_incident_report(self, shipment_id, payload, headers):
        return self._request("POST", f"/hazmat/shipments/{shipment_id}/incident-reports", payload, headers)

    def list_incident_reports(self, headers, params=None):
        return self._request("GET", "/hazmat/incident-reports", headers=headers, params=params)

    def get_incident_report(self, incident_id, headers):
        return self._request("GET", f"/hazmat/incident-reports/{incident_id}", headers=headers)

    def record_phone_report(self, incident_id, headers):
        return self._request("POST", f"/hazmat/incident-reports/{incident_id}/record-phone-report", {}, headers)

    def file_written_report(self, incident_id, headers):
        return self._request("POST", f"/hazmat/incident-reports/{incident_id}/file-written", {}, headers)

    def close_incident_report(self, incident_id, payload, headers):
        return self._request("POST", f"/hazmat/incident-reports/{incident_id}/close", payload, headers)


api_client = ApiClient()
