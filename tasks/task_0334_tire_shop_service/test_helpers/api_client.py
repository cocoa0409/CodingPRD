"""API client: one method per endpoint defined in the Tire Shop & Service PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Customers ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ---- Vehicles ----
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    # ---- Tire catalog ----
    def create_tire_model(self, payload, headers):
        return self._request("POST", "/tire-models", payload, headers)

    def get_tire_model(self, tire_model_id, headers):
        return self._request("GET", f"/tire-models/{tire_model_id}", headers=headers)

    def list_tire_models(self, headers, params=None):
        return self._request("GET", "/tire-models", headers=headers, params=params)

    def restock_tire_model(self, tire_model_id, payload, headers):
        return self._request("POST", f"/tire-models/{tire_model_id}/restock", payload, headers)

    def discontinue_tire_model(self, tire_model_id, headers):
        return self._request("POST", f"/tire-models/{tire_model_id}/discontinue", headers=headers)

    # ---- Fitment ----
    def create_fitment_rule(self, payload, headers):
        return self._request("POST", "/fitment-rules", payload, headers)

    def get_fitment_rule(self, fitment_rule_id, headers):
        return self._request("GET", f"/fitment-rules/{fitment_rule_id}", headers=headers)

    def list_fitment_rules(self, headers, params=None):
        return self._request("GET", "/fitment-rules", headers=headers, params=params)

    # ---- Service bays ----
    def create_service_bay(self, payload, headers):
        return self._request("POST", "/service-bays", payload, headers)

    def get_service_bay(self, bay_id, headers):
        return self._request("GET", f"/service-bays/{bay_id}", headers=headers)

    def list_service_bays(self, headers, params=None):
        return self._request("GET", "/service-bays", headers=headers, params=params)

    def close_service_bay(self, bay_id, payload, headers):
        return self._request("POST", f"/service-bays/{bay_id}/close", payload, headers)

    def reopen_service_bay(self, bay_id, payload, headers):
        return self._request("POST", f"/service-bays/{bay_id}/reopen", payload, headers)

    # ---- Work orders ----
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def add_work_order_line(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/lines", payload, headers)

    def list_work_order_lines(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}/lines", headers=headers)

    def get_work_order_line(self, line_id, headers):
        return self._request("GET", f"/work-order-lines/{line_id}", headers=headers)

    def list_lines(self, headers, params=None):
        return self._request("GET", "/work-order-lines", headers=headers, params=params)

    def approve_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/approve", payload, headers)

    def authorize_payment(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/authorize-payment", headers=headers)

    def capture_payment(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/capture-payment", headers=headers)

    def start_service(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/start-service", headers=headers)

    def complete_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/complete", headers=headers)

    def cancel_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", payload, headers)

    # ---- Road-hazard warranties ----
    def get_road_hazard_warranty(self, warranty_id, headers):
        return self._request("GET", f"/road-hazard-warranties/{warranty_id}", headers=headers)

    def list_road_hazard_warranties(self, headers, params=None):
        return self._request("GET", "/road-hazard-warranties", headers=headers, params=params)

    # ---- Install appointments ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def request_reschedule(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/request-reschedule", headers=headers)

    def confirm_reschedule(self, appointment_id, payload, headers):
        return self._request("POST", f"/appointments/{appointment_id}/confirm-reschedule", payload, headers)

    def check_in_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/check-in", headers=headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/cancel", headers=headers)

    # ---- Special orders ----
    def create_special_order(self, payload, headers):
        return self._request("POST", "/special-orders", payload, headers)

    def get_special_order(self, special_order_id, headers):
        return self._request("GET", f"/special-orders/{special_order_id}", headers=headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/special-orders", headers=headers, params=params)

    def receive_special_order(self, special_order_id, headers):
        return self._request("POST", f"/special-orders/{special_order_id}/receive", headers=headers)

    def cancel_backorder(self, special_order_id, headers):
        return self._request("POST", f"/special-orders/{special_order_id}/cancel-backorder", headers=headers)

    # ---- Mileage warranty claims ----
    def create_mileage_claim(self, payload, headers):
        return self._request("POST", "/mileage-claims", payload, headers)

    def get_mileage_claim(self, claim_id, headers):
        return self._request("GET", f"/mileage-claims/{claim_id}", headers=headers)

    def list_mileage_claims(self, headers, params=None):
        return self._request("GET", "/mileage-claims", headers=headers, params=params)

    def approve_mileage_claim(self, claim_id, headers):
        return self._request("POST", f"/mileage-claims/{claim_id}/approve", headers=headers)

    def reject_mileage_claim(self, claim_id, headers):
        return self._request("POST", f"/mileage-claims/{claim_id}/reject", headers=headers)

    def pay_mileage_claim(self, claim_id, headers):
        return self._request("POST", f"/mileage-claims/{claim_id}/pay", headers=headers)


api_client = ApiClient()
