"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def revise_credit_limit(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/customers/{customer_id}/credit-limit-revisions", payload, headers
        )

    def set_credit_status(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/customers/{customer_id}/credit-status", payload, headers
        )

    # --- Release ---
    def create_release(self, payload, headers):
        return self._request("POST", "/releases", payload, headers)

    def list_releases(self, headers, params=None):
        return self._request("GET", "/releases", headers=headers, params=params)

    def get_release(self, release_id, headers):
        return self._request("GET", f"/releases/{release_id}", headers=headers)

    def revise_release_date(self, release_id, payload, headers):
        return self._request(
            "POST", f"/releases/{release_id}/date-revisions", payload, headers
        )

    def get_release_risk(self, release_id, headers):
        return self._request("GET", f"/releases/{release_id}/risk", headers=headers)

    def list_release_delay_notices(self, release_id, headers, params=None):
        return self._request(
            "GET", f"/releases/{release_id}/delay-notices", headers=headers, params=params
        )

    # --- PressOrder ---
    def create_press_order(self, payload, headers):
        return self._request("POST", "/press-orders", payload, headers)

    def list_press_orders(self, headers, params=None):
        return self._request("GET", "/press-orders", headers=headers, params=params)

    def get_press_order(self, order_id, headers):
        return self._request("GET", f"/press-orders/{order_id}", headers=headers)

    def quote_press_order(self, order_id, payload, headers):
        return self._request("POST", f"/press-orders/{order_id}/quotes", payload, headers)

    def confirm_press_order(self, order_id, payload, headers):
        return self._request("POST", f"/press-orders/{order_id}/confirm", payload, headers)

    def start_tooling(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/press-orders/{order_id}/start-tooling", payload or {}, headers
        )

    def commit_schedule(self, order_id, payload, headers):
        return self._request(
            "POST", f"/press-orders/{order_id}/schedule-commits", payload, headers
        )

    def post_production_event(self, order_id, payload, headers):
        return self._request(
            "POST", f"/press-orders/{order_id}/production-events", payload, headers
        )

    def cancel_press_order(self, order_id, payload, headers):
        return self._request("POST", f"/press-orders/{order_id}/cancel", payload, headers)

    def list_order_slots(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/press-orders/{order_id}/slots", headers=headers, params=params
        )

    def list_order_tooling_jobs(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/press-orders/{order_id}/tooling-jobs", headers=headers, params=params
        )

    def list_order_test_pressings(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/press-orders/{order_id}/test-pressings", headers=headers, params=params
        )

    def list_order_print_jobs(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/press-orders/{order_id}/print-jobs", headers=headers, params=params
        )

    def list_order_qc_reports(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/press-orders/{order_id}/qc-reports", headers=headers, params=params
        )

    def list_order_delay_notices(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/press-orders/{order_id}/delay-notices", headers=headers, params=params
        )

    def list_order_inventory_lots(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/press-orders/{order_id}/inventory-lots", headers=headers, params=params
        )

    # --- ToolingJob ---
    def advance_tooling_job(self, job_id, payload, headers):
        return self._request("POST", f"/tooling-jobs/{job_id}/advance", payload, headers)

    # --- TestPressing ---
    def create_test_pressing(self, order_id, payload, headers):
        return self._request(
            "POST", f"/press-orders/{order_id}/test-pressings", payload, headers
        )

    def ship_test_pressing(self, tp_id, headers, payload=None):
        return self._request(
            "POST", f"/test-pressings/{tp_id}/ship", payload or {}, headers
        )

    def review_test_pressing(self, tp_id, payload, headers):
        return self._request("POST", f"/test-pressings/{tp_id}/review", payload, headers)

    # --- PrintJob ---
    def create_print_job(self, order_id, payload, headers):
        return self._request(
            "POST", f"/press-orders/{order_id}/print-jobs", payload, headers
        )

    def advance_print_job(self, job_id, payload, headers):
        return self._request("POST", f"/print-jobs/{job_id}/advance", payload, headers)

    def decide_print_proof(self, job_id, payload, headers):
        return self._request(
            "POST", f"/print-jobs/{job_id}/proof-decision", payload, headers
        )

    # --- PressLine / PressSlot / PlatingBath ---
    def create_press_line(self, payload, headers):
        return self._request("POST", "/press-lines", payload, headers)

    def list_press_lines(self, headers, params=None):
        return self._request("GET", "/press-lines", headers=headers, params=params)

    def get_press_line(self, line_id, headers):
        return self._request("GET", f"/press-lines/{line_id}", headers=headers)

    def list_line_slots(self, line_id, headers, params=None):
        return self._request(
            "GET", f"/press-lines/{line_id}/slots", headers=headers, params=params
        )

    def get_line_backlog(self, line_id, headers):
        return self._request("GET", f"/press-lines/{line_id}/backlog", headers=headers)

    def create_maintenance_window(self, line_id, payload, headers):
        return self._request(
            "POST", f"/press-lines/{line_id}/maintenance-windows", payload, headers
        )

    def create_plating_bath(self, payload, headers):
        return self._request("POST", "/plating-baths", payload, headers)

    def list_plating_baths(self, headers, params=None):
        return self._request("GET", "/plating-baths", headers=headers, params=params)

    def get_plating_bath(self, bath_id, headers):
        return self._request("GET", f"/plating-baths/{bath_id}", headers=headers)

    def list_bath_tooling_jobs(self, bath_id, headers, params=None):
        return self._request(
            "GET", f"/plating-baths/{bath_id}/tooling-jobs", headers=headers, params=params
        )

    # --- QC ---
    def file_qc_report(self, order_id, payload, headers):
        return self._request(
            "POST", f"/press-orders/{order_id}/qc-reports", payload, headers
        )

    def decide_qc_report(self, qc_id, payload, headers):
        return self._request("POST", f"/qc-reports/{qc_id}/decision", payload, headers)

    # --- Inventory ---
    def create_inventory_lot(self, payload, headers):
        return self._request("POST", "/inventory-lots", payload, headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/inventory-lots", headers=headers, params=params)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/inventory-lots/{lot_id}", headers=headers)

    def post_stock_event(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/inventory-lots/{lot_id}/stock-events", payload, headers
        )

    # --- Shipment ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def advance_shipment(self, shipment_id, headers, payload=None):
        return self._request(
            "POST", f"/shipments/{shipment_id}/advance", payload or {}, headers
        )

    def cancel_shipment(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/shipments/{shipment_id}/cancel", payload, headers
        )

    # --- Invoice ---
    def issue_invoice(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/press-orders/{order_id}/invoices", payload or {}, headers
        )

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def post_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/payments", payload, headers)

    def post_credit_memo(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/credit-memos", payload, headers
        )


api_client = ApiClient()
