"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Vehicles ----
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def assign_vehicle(self, vehicle_id, payload, headers):
        return self._request("PATCH", f"/vehicles/{vehicle_id}/assignment", payload, headers)

    def evaluate_replacement(self, vehicle_id, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/replacement-evaluation", headers=headers)

    def create_fuel_log(self, vehicle_id, payload, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/fuel-logs", payload, headers)

    def list_fuel_logs(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/vehicles/{vehicle_id}/fuel-logs", headers=headers, params=params)

    def list_vehicle_disposals(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/vehicles/{vehicle_id}/disposals", headers=headers, params=params)

    def create_disposal(self, vehicle_id, payload, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/disposals", payload, headers)

    # ---- Departments ----
    def create_department(self, payload, headers):
        return self._request("POST", "/departments", payload, headers)

    def get_department(self, department_id, headers):
        return self._request("GET", f"/departments/{department_id}", headers=headers)

    def list_department_vehicles(self, department_id, headers, params=None):
        return self._request("GET", f"/departments/{department_id}/vehicles", headers=headers, params=params)

    def list_department_invoices(self, department_id, headers, params=None):
        return self._request("GET", f"/departments/{department_id}/chargeback-invoices", headers=headers, params=params)

    def create_invoice(self, department_id, payload, headers):
        return self._request("POST", f"/departments/{department_id}/chargeback-invoices", payload, headers)

    # ---- Vehicle Class Policies ----
    def create_vehicle_class_policy(self, payload, headers):
        return self._request("POST", "/vehicle-class-policies", payload, headers)

    def get_vehicle_class_policy(self, policy_id, headers):
        return self._request("GET", f"/vehicle-class-policies/{policy_id}", headers=headers)

    # ---- Reservations ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def confirm_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/confirm", headers=headers)

    def checkout_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/checkout", payload, headers)

    def return_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/return", payload, headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/cancel", headers=headers)

    # ---- Shop Bays ----
    def create_shop_bay(self, payload, headers):
        return self._request("POST", "/shop-bays", payload, headers)

    def get_shop_bay(self, bay_id, headers):
        return self._request("GET", f"/shop-bays/{bay_id}", headers=headers)

    def update_shop_bay(self, bay_id, payload, headers):
        return self._request("PATCH", f"/shop-bays/{bay_id}", payload, headers)

    def list_bay_work_orders(self, bay_id, headers, params=None):
        return self._request("GET", f"/shop-bays/{bay_id}/work-orders", headers=headers, params=params)

    # ---- Work Orders ----
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def start_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/start", headers=headers)

    def hold_parts_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/hold-parts", headers=headers)

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/complete", payload, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", headers=headers)

    # ---- Accident Claims ----
    def create_accident_claim(self, payload, headers):
        return self._request("POST", "/accident-claims", payload, headers)

    def get_accident_claim(self, claim_id, headers):
        return self._request("GET", f"/accident-claims/{claim_id}", headers=headers)

    def list_accident_claims(self, headers, params=None):
        return self._request("GET", "/accident-claims", headers=headers, params=params)

    def investigate_claim(self, claim_id, headers):
        return self._request("POST", f"/accident-claims/{claim_id}/investigate", headers=headers)

    def subrogate_claim(self, claim_id, headers):
        return self._request("POST", f"/accident-claims/{claim_id}/subrogate", headers=headers)

    def record_recovery(self, claim_id, payload, headers):
        return self._request("POST", f"/accident-claims/{claim_id}/record-recovery", payload, headers)

    def dispute_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/accident-claims/{claim_id}/dispute", payload, headers)

    def close_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/accident-claims/{claim_id}/close", payload, headers)

    # ---- Disposals ----
    def get_disposal(self, disposal_id, headers):
        return self._request("GET", f"/disposals/{disposal_id}", headers=headers)

    def open_bidding(self, disposal_id, headers):
        return self._request("POST", f"/disposals/{disposal_id}/open-bidding", headers=headers)

    def sell_disposal(self, disposal_id, payload, headers):
        return self._request("POST", f"/disposals/{disposal_id}/sell", payload, headers)

    def no_sale_disposal(self, disposal_id, headers):
        return self._request("POST", f"/disposals/{disposal_id}/no-sale", headers=headers)

    # ---- Chargeback Invoices ----
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/chargeback-invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/chargeback-invoices/{invoice_id}/issue", headers=headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/chargeback-invoices/{invoice_id}/pay", headers=headers)

    def dispute_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/chargeback-invoices/{invoice_id}/dispute", payload, headers)

    def resolve_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/chargeback-invoices/{invoice_id}/resolve", payload, headers)

    # ---- Server logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
