"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Product ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    # ---- InventoryItem ----
    def create_inventory_item(self, payload, headers):
        return self._request("POST", "/inventory-items", payload, headers)

    def list_inventory_items(self, headers, params=None):
        return self._request("GET", "/inventory-items", headers=headers, params=params)

    def get_inventory_item(self, inventory_item_id, headers):
        return self._request("GET", f"/inventory-items/{inventory_item_id}", headers=headers)

    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ---- FootMeasurement ----
    def create_measurement(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/measurements", payload, headers)

    def list_measurements(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/measurements", headers=headers, params=params)

    # ---- Fitter ----
    def create_fitter(self, payload, headers):
        return self._request("POST", "/fitters", payload, headers)

    def get_fitter(self, fitter_id, headers):
        return self._request("GET", f"/fitters/{fitter_id}", headers=headers)

    # ---- GaitLab ----
    def create_gait_lab(self, payload, headers):
        return self._request("POST", "/gait-labs", payload, headers)

    def get_gait_lab(self, gait_lab_id, headers):
        return self._request("GET", f"/gait-labs/{gait_lab_id}", headers=headers)

    # ---- Appointment ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def check_in_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/check-in", {}, headers)

    def complete_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/appointments/{appointment_id}/complete", payload, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/cancel", {}, headers)

    def no_show_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/no-show", {}, headers)

    # ---- Sale ----
    def create_sale(self, payload, headers):
        return self._request("POST", "/sales", payload, headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/sales", headers=headers, params=params)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/sales/{sale_id}", headers=headers)

    def add_sale_line(self, sale_id, payload, headers):
        return self._request("POST", f"/sales/{sale_id}/lines", payload, headers)

    def list_sale_lines(self, headers, params=None):
        return self._request("GET", "/sale-lines", headers=headers, params=params)

    def get_sale_line(self, sale_line_id, headers):
        return self._request("GET", f"/sale-lines/{sale_line_id}", headers=headers)

    def fulfill_sale(self, sale_id, headers):
        return self._request("POST", f"/sales/{sale_id}/fulfill", {}, headers)

    def pay_sale(self, sale_id, payload, headers):
        return self._request("POST", f"/sales/{sale_id}/pay", payload, headers)

    def cancel_sale(self, sale_id, headers):
        return self._request("POST", f"/sales/{sale_id}/cancel", {}, headers)

    # ---- Certification ----
    def create_certification(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/certifications", payload, headers)

    def list_certifications(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/certifications", headers=headers, params=params)

    # ---- MedicareClaim ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/medicare-claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/medicare-claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/medicare-claims/{claim_id}", headers=headers)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/medicare-claims/{claim_id}/submit", {}, headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/medicare-claims/{claim_id}/adjudicate", payload, headers)

    def resubmit_claim(self, claim_id, headers):
        return self._request("POST", f"/medicare-claims/{claim_id}/resubmit", {}, headers)

    def void_claim(self, claim_id, headers):
        return self._request("POST", f"/medicare-claims/{claim_id}/void", {}, headers)

    # ---- ReturnRequest ----
    def create_return(self, payload, headers):
        return self._request("POST", "/returns", payload, headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/returns", headers=headers, params=params)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def approve_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/approve", {}, headers)

    def reject_return(self, return_id, payload, headers):
        return self._request("POST", f"/returns/{return_id}/reject", payload, headers)

    def refund_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/refund", {}, headers)

    def exchange_return(self, return_id, payload, headers):
        return self._request("POST", f"/returns/{return_id}/exchange", payload, headers)

    # ---- SpecialOrder ----
    def create_special_order(self, payload, headers):
        return self._request("POST", "/special-orders", payload, headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/special-orders", headers=headers, params=params)

    def get_special_order(self, special_order_id, headers):
        return self._request("GET", f"/special-orders/{special_order_id}", headers=headers)

    def place_special_order(self, special_order_id, headers):
        return self._request("POST", f"/special-orders/{special_order_id}/place", {}, headers)

    def receive_special_order(self, special_order_id, payload, headers):
        return self._request("POST", f"/special-orders/{special_order_id}/receive", payload, headers)

    def fulfill_special_order(self, special_order_id, headers):
        return self._request("POST", f"/special-orders/{special_order_id}/fulfill", {}, headers)

    def cancel_special_order(self, special_order_id, headers):
        return self._request("POST", f"/special-orders/{special_order_id}/cancel", {}, headers)

    # ---- Recall ----
    def create_recall(self, payload, headers):
        return self._request("POST", "/recalls", payload, headers)

    def list_recalls(self, headers, params=None):
        return self._request("GET", "/recalls", headers=headers, params=params)

    def get_recall(self, recall_id, headers):
        return self._request("GET", f"/recalls/{recall_id}", headers=headers)

    def issue_recall(self, recall_id, headers):
        return self._request("POST", f"/recalls/{recall_id}/issue", {}, headers)

    def close_recall(self, recall_id, headers):
        return self._request("POST", f"/recalls/{recall_id}/close", {}, headers)

    # ---- Loyalty ----
    def create_ledger_entry(self, payload, headers):
        return self._request("POST", "/loyalty-ledger", payload, headers)

    def list_ledger(self, headers, params=None):
        return self._request("GET", "/loyalty-ledger", headers=headers, params=params)

    def get_ledger_entry(self, ledger_entry_id, headers):
        return self._request("GET", f"/loyalty-ledger/{ledger_entry_id}", headers=headers)


api_client = ApiClient()
