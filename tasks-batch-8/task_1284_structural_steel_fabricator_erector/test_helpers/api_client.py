"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Job ---
    def create_job(self, payload, headers):
        return self._request("POST", "/jobs", payload, headers)

    def list_jobs(self, headers, params=None):
        return self._request("GET", "/jobs", headers=headers, params=params)

    def get_job(self, job_id, headers):
        return self._request("GET", f"/jobs/{job_id}", headers=headers)

    def award_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/award", headers=headers)

    def start_fabrication(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/start-fabrication",
                             headers=headers)

    def start_erection(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/start-erection",
                             headers=headers)

    # --- ShopDrawing ---
    def create_shop_drawing(self, payload, headers):
        return self._request("POST", "/shop-drawings", payload, headers)

    def list_shop_drawings(self, headers, params=None):
        return self._request("GET", "/shop-drawings", headers=headers, params=params)

    def get_shop_drawing(self, drawing_id, headers):
        return self._request("GET", f"/shop-drawings/{drawing_id}", headers=headers)

    def submit_drawing(self, drawing_id, headers):
        return self._request("POST", f"/shop-drawings/{drawing_id}/submit",
                             headers=headers)

    def decide_drawing(self, drawing_id, payload, headers):
        return self._request("POST", f"/shop-drawings/{drawing_id}/decide",
                             payload, headers)

    def revise_drawing(self, drawing_id, payload, headers):
        return self._request("POST", f"/shop-drawings/{drawing_id}/revise",
                             payload, headers)

    # --- MillOrder ---
    def create_mill_order(self, payload, headers):
        return self._request("POST", "/mill-orders", payload, headers)

    def list_mill_orders(self, headers, params=None):
        return self._request("GET", "/mill-orders", headers=headers, params=params)

    def get_mill_order(self, order_id, headers):
        return self._request("GET", f"/mill-orders/{order_id}", headers=headers)

    def receive_mill_order(self, order_id, payload, headers):
        return self._request("POST", f"/mill-orders/{order_id}/receive",
                             payload, headers)

    # --- ErectionSequence ---
    def create_erection_sequence(self, payload, headers):
        return self._request("POST", "/erection-sequences", payload, headers)

    def list_erection_sequences(self, headers, params=None):
        return self._request("GET", "/erection-sequences",
                             headers=headers, params=params)

    def get_erection_sequence(self, sequence_id, headers):
        return self._request("GET", f"/erection-sequences/{sequence_id}",
                             headers=headers)

    def release_sequence(self, sequence_id, headers):
        return self._request("POST", f"/erection-sequences/{sequence_id}/release",
                             headers=headers)

    # --- Piece ---
    def create_piece(self, payload, headers):
        return self._request("POST", "/pieces", payload, headers)

    def list_pieces(self, headers, params=None):
        return self._request("GET", "/pieces", headers=headers, params=params)

    def get_piece(self, piece_id, headers):
        return self._request("GET", f"/pieces/{piece_id}", headers=headers)

    def start_piece(self, piece_id, headers):
        return self._request("POST", f"/pieces/{piece_id}/start", headers=headers)

    def erect_piece(self, piece_id, headers):
        return self._request("POST", f"/pieces/{piece_id}/erect", headers=headers)

    # --- Welder ---
    def create_welder(self, payload, headers):
        return self._request("POST", "/welders", payload, headers)

    def suspend_welder(self, welder_id, headers):
        return self._request("POST", f"/welders/{welder_id}/suspend",
                             headers=headers)

    # --- Weld ---
    def create_weld(self, payload, headers):
        return self._request("POST", "/welds", payload, headers)

    def list_welds(self, headers, params=None):
        return self._request("GET", "/welds", headers=headers, params=params)

    def get_weld(self, weld_id, headers):
        return self._request("GET", f"/welds/{weld_id}", headers=headers)

    def repair_weld(self, weld_id, headers):
        return self._request("POST", f"/welds/{weld_id}/repair", headers=headers)

    # --- Inspection ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def submit_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/submit",
                             payload, headers)

    def void_inspection(self, inspection_id, headers):
        return self._request("POST", f"/inspections/{inspection_id}/void",
                             headers=headers)

    # --- ShippingLoad ---
    def create_shipping_load(self, payload, headers):
        return self._request("POST", "/shipping-loads", payload, headers)

    def list_shipping_loads(self, headers, params=None):
        return self._request("GET", "/shipping-loads", headers=headers, params=params)

    def get_shipping_load(self, load_id, headers):
        return self._request("GET", f"/shipping-loads/{load_id}", headers=headers)

    def list_load_lines(self, load_id, headers):
        return self._request("GET", f"/shipping-loads/{load_id}/lines",
                             headers=headers)

    def add_load_line(self, load_id, payload, headers):
        return self._request("POST", f"/shipping-loads/{load_id}/lines",
                             payload, headers)

    def remove_load_line(self, load_id, piece_id, headers):
        return self._request("DELETE",
                             f"/shipping-loads/{load_id}/lines/{piece_id}",
                             headers=headers)

    def ship_load(self, load_id, headers):
        return self._request("POST", f"/shipping-loads/{load_id}/ship",
                             headers=headers)

    # --- FieldFix ---
    def create_field_fix(self, payload, headers):
        return self._request("POST", "/field-fixes", payload, headers)

    def list_field_fixes(self, headers, params=None):
        return self._request("GET", "/field-fixes", headers=headers, params=params)

    def get_field_fix(self, fix_id, headers):
        return self._request("GET", f"/field-fixes/{fix_id}", headers=headers)

    def approve_field_fix(self, fix_id, headers):
        return self._request("POST", f"/field-fixes/{fix_id}/approve",
                             headers=headers)

    def resolve_field_fix(self, fix_id, headers):
        return self._request("POST", f"/field-fixes/{fix_id}/resolve",
                             headers=headers)

    # --- Backcharge ---
    def list_backcharges(self, headers, params=None):
        return self._request("GET", "/backcharges", headers=headers, params=params)

    def get_backcharge(self, backcharge_id, headers):
        return self._request("GET", f"/backcharges/{backcharge_id}", headers=headers)

    def respond_backcharge(self, backcharge_id, payload, headers):
        return self._request("POST", f"/backcharges/{backcharge_id}/respond",
                             payload, headers)

    def settle_backcharge(self, backcharge_id, payload, headers):
        return self._request("POST", f"/backcharges/{backcharge_id}/settle",
                             payload, headers)

    # --- ProgressBilling ---
    def create_progress_billing(self, payload, headers):
        return self._request("POST", "/progress-billings", payload, headers)

    def list_progress_billings(self, headers, params=None):
        return self._request("GET", "/progress-billings",
                             headers=headers, params=params)

    def get_progress_billing(self, billing_id, headers):
        return self._request("GET", f"/progress-billings/{billing_id}",
                             headers=headers)

    def submit_billing(self, billing_id, headers):
        return self._request("POST", f"/progress-billings/{billing_id}/submit",
                             headers=headers)

    def approve_billing(self, billing_id, headers):
        return self._request("POST", f"/progress-billings/{billing_id}/approve",
                             headers=headers)

    def pay_billing(self, billing_id, headers):
        return self._request("POST", f"/progress-billings/{billing_id}/pay",
                             headers=headers)

    def void_billing(self, billing_id, headers):
        return self._request("POST", f"/progress-billings/{billing_id}/void",
                             headers=headers)


api_client = ApiClient()
# The per-test-server isolation SIGKILLs and respawns the server between tests
# on the same port. A pooled keep-alive connection from the killed server then
# surfaces as ConnectionResetError(104) on the next test's first request.
# Sending Connection: close makes Werkzeug close each socket after its
# response, so urllib3 never reuses a dead pooled connection.
api_client.session.headers["Connection"] = "close"
