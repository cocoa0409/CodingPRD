"""API client: one method per endpoint defined in the Ready Mix Dispatch PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", payload, headers)

    # --- Plants ---
    def create_plant(self, payload, headers):
        return self._request("POST", "/v1/plants", payload, headers)

    def get_plant(self, plant_id, headers):
        return self._request("GET", f"/v1/plants/{plant_id}", headers=headers)

    # --- Mix designs ---
    def create_mix_design(self, payload, headers):
        return self._request("POST", "/v1/mix-designs", payload, headers)

    def get_mix_design(self, mix_design_id, headers):
        return self._request("GET", f"/v1/mix-designs/{mix_design_id}", headers=headers)

    def list_mix_designs(self, headers, params=None):
        return self._request("GET", "/v1/mix-designs", headers=headers, params=params)

    def activate_mix_design(self, mix_design_id, headers):
        return self._request(
            "POST", f"/v1/mix-designs/{mix_design_id}/activate", headers=headers
        )

    def retire_mix_design(self, mix_design_id, headers):
        return self._request(
            "POST", f"/v1/mix-designs/{mix_design_id}/retire", headers=headers
        )

    # --- Price lists ---
    def create_price_list(self, payload, headers):
        return self._request("POST", "/v1/price-lists", payload, headers)

    def get_price_list(self, price_list_id, headers):
        return self._request("GET", f"/v1/price-lists/{price_list_id}", headers=headers)

    def list_price_lists(self, headers, params=None):
        return self._request("GET", "/v1/price-lists", headers=headers, params=params)

    # --- Cement price indices ---
    def create_cement_price_index(self, payload, headers):
        return self._request("POST", "/v1/cement-price-indices", payload, headers)

    def get_cement_price_index(self, index_id, headers):
        return self._request(
            "GET", f"/v1/cement-price-indices/{index_id}", headers=headers
        )

    def list_cement_price_indices(self, headers, params=None):
        return self._request(
            "GET", "/v1/cement-price-indices", headers=headers, params=params
        )

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/v1/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/v1/customers/{customer_id}", headers=headers)

    def credit_review(self, customer_id, headers):
        return self._request(
            "POST", f"/v1/customers/{customer_id}/credit-review", {}, headers
        )

    # --- Trucks ---
    def create_truck(self, payload, headers):
        return self._request("POST", "/v1/trucks", payload, headers)

    def get_truck(self, truck_id, headers):
        return self._request("GET", f"/v1/trucks/{truck_id}", headers=headers)

    def list_trucks(self, headers, params=None):
        return self._request("GET", "/v1/trucks", headers=headers, params=params)

    def truck_out_of_service(self, truck_id, headers):
        return self._request(
            "POST", f"/v1/trucks/{truck_id}/out-of-service", {}, headers
        )

    def truck_return_to_service(self, truck_id, headers):
        return self._request(
            "POST", f"/v1/trucks/{truck_id}/return-to-service", {}, headers
        )

    # --- Orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/v1/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/v1/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/v1/orders", headers=headers, params=params)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/v1/orders/{order_id}/confirm", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/v1/orders/{order_id}/cancel", {}, headers)

    # --- Loads ---
    def schedule_load(self, order_id, payload, headers):
        return self._request("POST", f"/v1/orders/{order_id}/loads", payload, headers)

    def get_load(self, load_id, headers):
        return self._request("GET", f"/v1/loads/{load_id}", headers=headers)

    def list_loads(self, headers, params=None):
        return self._request("GET", "/v1/loads", headers=headers, params=params)

    def batch_load(self, load_id, payload, headers):
        return self._request("POST", f"/v1/loads/{load_id}/batch", payload, headers)

    def depart_load(self, load_id, headers):
        return self._request("POST", f"/v1/loads/{load_id}/depart", {}, headers)

    def arrive_load(self, load_id, headers):
        return self._request("POST", f"/v1/loads/{load_id}/arrive", {}, headers)

    def start_pour_load(self, load_id, headers):
        return self._request("POST", f"/v1/loads/{load_id}/start-pour", {}, headers)

    def complete_load(self, load_id, payload, headers):
        return self._request("POST", f"/v1/loads/{load_id}/complete", payload, headers)

    def cancel_load(self, load_id, headers):
        return self._request("POST", f"/v1/loads/{load_id}/cancel", {}, headers)

    def return_load(self, load_id, payload, headers):
        return self._request("POST", f"/v1/loads/{load_id}/return", payload, headers)

    def washout_load(self, load_id, payload, headers):
        return self._request("POST", f"/v1/loads/{load_id}/washout", payload, headers)

    # --- Water additions ---
    def add_water(self, load_id, payload, headers):
        return self._request(
            "POST", f"/v1/loads/{load_id}/water-additions", payload, headers
        )

    def list_water_additions(self, load_id, headers, params=None):
        return self._request(
            "GET", f"/v1/loads/{load_id}/water-additions", headers=headers, params=params
        )

    # --- Batch ticket ---
    def get_batch_ticket(self, load_id, headers):
        return self._request(
            "GET", f"/v1/loads/{load_id}/batch-ticket", headers=headers
        )

    # --- Cylinder sets ---
    def create_cylinder_set(self, load_id, payload, headers):
        return self._request(
            "POST", f"/v1/loads/{load_id}/cylinder-sets", payload, headers
        )

    def get_cylinder_set(self, cylinder_set_id, headers):
        return self._request(
            "GET", f"/v1/cylinder-sets/{cylinder_set_id}", headers=headers
        )

    def list_cylinder_sets(self, load_id, headers, params=None):
        return self._request(
            "GET", f"/v1/loads/{load_id}/cylinder-sets", headers=headers, params=params
        )

    def record_break(self, cylinder_set_id, payload, headers):
        return self._request(
            "POST", f"/v1/cylinder-sets/{cylinder_set_id}/breaks", payload, headers
        )

    def certify_cylinder_set(self, cylinder_set_id, headers):
        return self._request(
            "POST", f"/v1/cylinder-sets/{cylinder_set_id}/certify", {}, headers
        )

    # --- Return record ---
    def get_return_record(self, load_id, headers):
        return self._request(
            "GET", f"/v1/loads/{load_id}/return-record", headers=headers
        )

    # --- Invoices ---
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/v1/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/v1/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/v1/invoices/{invoice_id}/issue", {}, headers)

    def dispute_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/v1/invoices/{invoice_id}/dispute", payload, headers
        )

    def adjust_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/v1/invoices/{invoice_id}/adjust", payload, headers
        )

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/v1/invoices/{invoice_id}/pay", payload, headers)


api_client = ApiClient()
