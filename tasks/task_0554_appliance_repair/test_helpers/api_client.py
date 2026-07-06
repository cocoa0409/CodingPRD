"""API client: one method per endpoint defined in the PRD (§4).

Subclasses the framework GenericApiClient; the inherited _request() handles the
HTTP mechanics and the success/error envelope transport. All paths are flat
top-level collections plus a few action sub-paths under /service-requests.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # --- Appliance ---
    def create_appliance(self, payload, headers):
        return self._request("POST", "/appliances", payload, headers)

    def get_appliance(self, appliance_id, headers):
        return self._request("GET", f"/appliances/{appliance_id}", headers=headers)

    def list_appliances(self, headers, params=None):
        return self._request("GET", "/appliances", headers=headers, params=params)

    # --- WarrantyContract ---
    def create_warranty_contract(self, payload, headers):
        return self._request("POST", "/warranty-contracts", payload, headers)

    def get_warranty_contract(self, contract_id, headers):
        return self._request("GET", f"/warranty-contracts/{contract_id}", headers=headers)

    def list_warranty_contracts(self, headers, params=None):
        return self._request("GET", "/warranty-contracts", headers=headers, params=params)

    # --- Part ---
    def create_part(self, payload, headers):
        return self._request("POST", "/parts", payload, headers)

    # --- Technician ---
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    def update_technician_status(self, technician_id, payload, headers):
        return self._request("POST", f"/technicians/{technician_id}/status", payload, headers)

    # --- TruckStockItem ---
    def create_truck_stock(self, payload, headers):
        return self._request("POST", "/truck-stock", payload, headers)

    def get_truck_stock(self, truck_stock_id, headers):
        return self._request("GET", f"/truck-stock/{truck_stock_id}", headers=headers)

    def list_truck_stock(self, headers, params=None):
        return self._request("GET", "/truck-stock", headers=headers, params=params)

    # --- ServiceZone ---
    def create_service_zone(self, payload, headers):
        return self._request("POST", "/service-zones", payload, headers)

    # --- ServiceRequest ---
    def create_service_request(self, payload, headers):
        return self._request("POST", "/service-requests", payload, headers)

    def get_service_request(self, service_request_id, headers):
        return self._request("GET", f"/service-requests/{service_request_id}", headers=headers)

    def list_service_requests(self, headers, params=None):
        return self._request("GET", "/service-requests", headers=headers, params=params)

    def create_appointment(self, service_request_id, payload, headers):
        return self._request("POST", f"/service-requests/{service_request_id}/appointments", payload, headers)

    def diagnose(self, service_request_id, payload, headers):
        return self._request("POST", f"/service-requests/{service_request_id}/diagnose", payload, headers)

    def revise_estimate(self, service_request_id, payload, headers):
        return self._request("POST", f"/service-requests/{service_request_id}/estimates", payload, headers)

    def complete_service_request(self, service_request_id, payload, headers):
        return self._request("POST", f"/service-requests/{service_request_id}/complete", payload, headers)

    def second_trip(self, service_request_id, payload, headers):
        return self._request("POST", f"/service-requests/{service_request_id}/second-trip", payload, headers)

    def create_payment(self, service_request_id, payload, headers):
        return self._request("POST", f"/service-requests/{service_request_id}/payments", payload, headers)

    # --- Estimate ---
    def get_estimate(self, estimate_id, headers):
        return self._request("GET", f"/estimates/{estimate_id}", headers=headers)

    def list_estimates(self, headers, params=None):
        return self._request("GET", "/estimates", headers=headers, params=params)

    def decide_estimate(self, estimate_id, payload, headers):
        return self._request("POST", f"/estimates/{estimate_id}/decision", payload, headers)

    # --- PartsOrder ---
    def get_parts_order(self, parts_order_id, headers):
        return self._request("GET", f"/parts-orders/{parts_order_id}", headers=headers)

    def list_parts_orders(self, headers, params=None):
        return self._request("GET", "/parts-orders", headers=headers, params=params)

    def update_parts_order_status(self, parts_order_id, payload, headers):
        return self._request("POST", f"/parts-orders/{parts_order_id}/status", payload, headers)

    # --- Payment ---
    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    # --- Appointment ---
    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    # --- RecallNotice ---
    def create_recall(self, payload, headers):
        return self._request("POST", "/recalls", payload, headers)

    def get_recall(self, recall_id, headers):
        return self._request("GET", f"/recalls/{recall_id}", headers=headers)

    def update_recall_status(self, recall_id, payload, headers):
        return self._request("POST", f"/recalls/{recall_id}/status", payload, headers)


api_client = ApiClient()
