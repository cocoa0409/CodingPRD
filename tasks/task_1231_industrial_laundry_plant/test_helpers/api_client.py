"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        # The runner SIGKILLs and reboots the server before every test
        # (per-test-server isolation). A keep-alive pool would hold dead
        # connections across reboots and surface as ECONNRESET mid-test;
        # close per request instead so every request opens a fresh socket.
        self.session.headers["Connection"] = "close"

    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Plant ---
    def create_plant(self, payload, headers):
        return self._request("POST", "/plants", payload, headers)

    def get_plant(self, plant_id, headers):
        return self._request("GET", f"/plants/{plant_id}", headers=headers)

    # --- LinenCategory ---
    def create_linen_category(self, plant_id, payload, headers):
        return self._request("POST", f"/plants/{plant_id}/linen-categories", payload, headers)

    def list_linen_categories(self, plant_id, headers, params=None):
        return self._request("GET", f"/plants/{plant_id}/linen-categories", headers=headers, params=params)

    def get_linen_category(self, category_id, headers):
        return self._request("GET", f"/linen-categories/{category_id}", headers=headers)

    def list_category_par_levels(self, category_id, headers, params=None):
        return self._request("GET", f"/linen-categories/{category_id}/par-levels", headers=headers, params=params)

    def list_category_sort_items(self, category_id, headers, params=None):
        return self._request("GET", f"/linen-categories/{category_id}/sort-items", headers=headers, params=params)

    def list_category_wash_loads(self, category_id, headers, params=None):
        return self._request("GET", f"/linen-categories/{category_id}/wash-loads", headers=headers, params=params)

    def list_category_garments(self, category_id, headers, params=None):
        return self._request("GET", f"/linen-categories/{category_id}/garments", headers=headers, params=params)

    def list_category_deliveries(self, category_id, headers, params=None):
        return self._request("GET", f"/linen-categories/{category_id}/deliveries", headers=headers, params=params)

    # --- Customer ---
    def create_customer(self, plant_id, payload, headers):
        return self._request("POST", f"/plants/{plant_id}/customers", payload, headers)

    def list_customers(self, plant_id, headers, params=None):
        return self._request("GET", f"/plants/{plant_id}/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/suspend", headers=headers)

    def resume_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/resume", headers=headers)

    def list_customer_stops(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/stops", headers=headers, params=params)

    def list_customer_garments(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/garments", headers=headers, params=params)

    # --- CustomerParLevel ---
    def upsert_par_level(self, customer_id, category_id, payload, headers):
        return self._request("PUT", f"/customers/{customer_id}/par-levels/{category_id}", payload, headers)

    def list_par_levels(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/par-levels", headers=headers, params=params)

    # --- Route ---
    def create_route(self, plant_id, payload, headers):
        return self._request("POST", f"/plants/{plant_id}/routes", payload, headers)

    def list_routes(self, plant_id, headers, params=None):
        return self._request("GET", f"/plants/{plant_id}/routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/dispatch", headers=headers)

    def complete_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/complete", headers=headers)

    def reconcile_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/reconcile", headers=headers)

    # --- RouteStop ---
    def create_stop(self, route_id, payload, headers):
        return self._request("POST", f"/routes/{route_id}/stops", payload, headers)

    def list_stops(self, route_id, headers, params=None):
        return self._request("GET", f"/routes/{route_id}/stops", headers=headers, params=params)

    def get_stop(self, stop_id, headers):
        return self._request("GET", f"/stops/{stop_id}", headers=headers)

    def arrive_stop(self, stop_id, headers):
        return self._request("POST", f"/stops/{stop_id}/arrive", headers=headers)

    def pickup_stop(self, stop_id, payload, headers):
        return self._request("POST", f"/stops/{stop_id}/pickup", payload, headers)

    # --- SoiledCart ---
    def list_carts(self, stop_id, headers, params=None):
        return self._request("GET", f"/stops/{stop_id}/carts", headers=headers, params=params)

    def get_cart(self, cart_id, headers):
        return self._request("GET", f"/carts/{cart_id}", headers=headers)

    def receive_cart(self, cart_id, headers):
        return self._request("POST", f"/carts/{cart_id}/receive", headers=headers)

    def void_cart(self, cart_id, headers):
        return self._request("POST", f"/carts/{cart_id}/void", headers=headers)

    # --- SortBatch / SortItem ---
    def create_sort_batch(self, payload, headers):
        return self._request("POST", "/sort-batches", payload, headers)

    def get_sort_batch(self, batch_id, headers):
        return self._request("GET", f"/sort-batches/{batch_id}", headers=headers)

    def list_plant_sort_batches(self, plant_id, headers, params=None):
        return self._request("GET", f"/plants/{plant_id}/sort-batches", headers=headers, params=params)

    def list_stop_sort_batches(self, stop_id, headers, params=None):
        return self._request("GET", f"/stops/{stop_id}/sort-batches", headers=headers, params=params)

    def list_sort_items(self, batch_id, headers, params=None):
        return self._request("GET", f"/sort-batches/{batch_id}/items", headers=headers, params=params)

    def create_sort_item(self, batch_id, payload, headers):
        return self._request("POST", f"/sort-batches/{batch_id}/items", payload, headers)

    def lock_sort_batch(self, batch_id, headers):
        return self._request("POST", f"/sort-batches/{batch_id}/lock", headers=headers)

    def unlock_sort_batch(self, batch_id, headers):
        return self._request("POST", f"/sort-batches/{batch_id}/unlock", headers=headers)

    def post_sort_batch(self, batch_id, headers):
        return self._request("POST", f"/sort-batches/{batch_id}/post", headers=headers)

    def void_sort_batch(self, batch_id, headers):
        return self._request("POST", f"/sort-batches/{batch_id}/void", headers=headers)

    # --- WashLoad ---
    def create_wash_load(self, payload, headers):
        return self._request("POST", "/wash-loads", payload, headers)

    def get_wash_load(self, load_id, headers):
        return self._request("GET", f"/wash-loads/{load_id}", headers=headers)

    def list_plant_wash_loads(self, plant_id, headers, params=None):
        return self._request("GET", f"/plants/{plant_id}/wash-loads", headers=headers, params=params)

    def list_batch_wash_loads(self, batch_id, headers, params=None):
        return self._request("GET", f"/sort-batches/{batch_id}/wash-loads", headers=headers, params=params)

    def start_wash_load(self, load_id, headers):
        return self._request("POST", f"/wash-loads/{load_id}/start", headers=headers)

    def finish_cycle_wash_load(self, load_id, headers):
        return self._request("POST", f"/wash-loads/{load_id}/finish-cycle", headers=headers)

    def record_test_wash_load(self, load_id, payload, headers):
        return self._request("POST", f"/wash-loads/{load_id}/record-test", payload, headers)

    def bypass_test_wash_load(self, load_id, headers):
        return self._request("POST", f"/wash-loads/{load_id}/bypass-test", headers=headers)

    def request_rewash_wash_load(self, load_id, headers):
        return self._request("POST", f"/wash-loads/{load_id}/request-rewash", headers=headers)

    def unload_wash_load(self, load_id, headers):
        return self._request("POST", f"/wash-loads/{load_id}/unload", headers=headers)

    def cancel_wash_load(self, load_id, headers):
        return self._request("POST", f"/wash-loads/{load_id}/cancel", headers=headers)

    # --- FinishRun ---
    def create_finish_run(self, payload, headers):
        return self._request("POST", "/finish-runs", payload, headers)

    def get_finish_run(self, run_id, headers):
        return self._request("GET", f"/finish-runs/{run_id}", headers=headers)

    def list_plant_finish_runs(self, plant_id, headers, params=None):
        return self._request("GET", f"/plants/{plant_id}/finish-runs", headers=headers, params=params)

    def list_load_finish_runs(self, load_id, headers, params=None):
        return self._request("GET", f"/wash-loads/{load_id}/finish-runs", headers=headers, params=params)

    def tally_finish_run(self, run_id, payload, headers):
        return self._request("POST", f"/finish-runs/{run_id}/tally", payload, headers)

    def post_finish_run(self, run_id, headers):
        return self._request("POST", f"/finish-runs/{run_id}/post", headers=headers)

    def void_finish_run(self, run_id, headers):
        return self._request("POST", f"/finish-runs/{run_id}/void", headers=headers)

    # --- Garment ---
    def register_garment(self, payload, headers):
        return self._request("POST", "/garments/register", payload, headers)

    def get_garment(self, garment_id, headers):
        return self._request("GET", f"/garments/{garment_id}", headers=headers)

    def load_out_garment(self, garment_id, headers):
        return self._request("POST", f"/garments/{garment_id}/load-out", headers=headers)

    def mark_lost_garment(self, garment_id, headers):
        return self._request("POST", f"/garments/{garment_id}/mark-lost", headers=headers)

    def list_garments(self, headers, params=None):
        return self._request("GET", "/garments", headers=headers, params=params)

    # --- Delivery ---
    def create_delivery(self, stop_id, payload, headers):
        return self._request("POST", f"/stops/{stop_id}/deliveries", payload, headers)

    def list_deliveries(self, stop_id, headers, params=None):
        return self._request("GET", f"/stops/{stop_id}/deliveries", headers=headers, params=params)

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/deliveries/{delivery_id}", headers=headers)

    def mark_delivered(self, delivery_id, payload, headers):
        return self._request("POST", f"/deliveries/{delivery_id}/mark-delivered", payload, headers)

    def confirm_delivery(self, delivery_id, headers):
        return self._request("POST", f"/deliveries/{delivery_id}/confirm", headers=headers)

    def file_dispute(self, delivery_id, payload, headers):
        return self._request("POST", f"/deliveries/{delivery_id}/disputes", payload, headers)

    # --- Discrepancy ---
    def list_disputes(self, delivery_id, headers, params=None):
        return self._request("GET", f"/deliveries/{delivery_id}/disputes", headers=headers, params=params)

    def get_discrepancy(self, discrepancy_id, headers):
        return self._request("GET", f"/discrepancies/{discrepancy_id}", headers=headers)

    def start_review_discrepancy(self, discrepancy_id, headers):
        return self._request("POST", f"/discrepancies/{discrepancy_id}/start-review", headers=headers)

    def approve_discrepancy(self, discrepancy_id, payload, headers):
        return self._request("POST", f"/discrepancies/{discrepancy_id}/approve", payload, headers)

    def reject_discrepancy(self, discrepancy_id, headers):
        return self._request("POST", f"/discrepancies/{discrepancy_id}/reject", headers=headers)

    def apply_credit_discrepancy(self, discrepancy_id, payload, headers):
        return self._request("POST", f"/discrepancies/{discrepancy_id}/apply-credit", payload, headers)

    # --- Invoice ---
    def generate_invoice(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/invoices/generate", payload, headers)

    def list_invoices(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", payload, headers)

    def mark_paid_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/mark-paid", headers=headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", headers=headers)

    def billing_preview(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/billing-preview", headers=headers, params=params)

    # --- UtilityReading ---
    def create_utility_reading(self, plant_id, payload, headers):
        return self._request("POST", f"/plants/{plant_id}/utility-readings", payload, headers)

    def list_utility_readings(self, plant_id, headers, params=None):
        return self._request("GET", f"/plants/{plant_id}/utility-readings", headers=headers, params=params)

    def get_utility_reading(self, reading_id, headers):
        return self._request("GET", f"/utility-readings/{reading_id}", headers=headers)

    # --- global filtered lists ---
    def list_sort_items_global(self, headers, params=None):
        return self._request("GET", "/sort-items", headers=headers, params=params)


api_client = ApiClient()
