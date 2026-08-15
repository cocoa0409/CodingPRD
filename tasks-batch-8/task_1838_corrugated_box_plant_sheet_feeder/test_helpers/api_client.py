"""API client: one method per endpoint defined in PRD section 4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD 2.4 / 4) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Customer accounts ---
    def create_customer_account(self, payload, headers):
        return self._request("POST", "/api/customer-accounts", payload, headers)

    def get_customer_account(self, customer_id, headers):
        return self._request(
            "GET", f"/api/customer-accounts/{customer_id}", headers=headers
        )

    # --- Board grades ---
    def create_board_grade(self, payload, headers):
        return self._request("POST", "/api/board-grades", payload, headers)

    def get_board_grade(self, grade_id, headers):
        return self._request("GET", f"/api/board-grades/{grade_id}", headers=headers)

    def discontinue_board_grade(self, grade_id, headers):
        return self._request(
            "POST", f"/api/board-grades/{grade_id}/discontinue", {}, headers
        )

    # --- Box orders ---
    def create_box_order(self, payload, headers):
        return self._request("POST", "/api/box-orders", payload, headers)

    def get_box_order(self, order_id, headers):
        return self._request("GET", f"/api/box-orders/{order_id}", headers=headers)

    def list_box_orders(self, headers, params=None):
        return self._request("GET", "/api/box-orders", headers=headers, params=params)

    def cancel_box_order(self, order_id, headers):
        return self._request("POST", f"/api/box-orders/{order_id}/cancel", {}, headers)

    def mark_sheets_received(self, order_id, headers):
        return self._request(
            "POST", f"/api/box-orders/{order_id}/mark-sheets-received", {}, headers
        )

    def invoice_box_order(self, order_id, headers):
        return self._request("POST", f"/api/box-orders/{order_id}/invoice", {}, headers)

    # --- Price quotes ---
    def create_price_quote(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/box-orders/{order_id}/quotes", payload, headers
        )

    def list_price_quotes(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/api/box-orders/{order_id}/quotes", headers=headers, params=params
        )

    def accept_price_quote(self, quote_id, headers):
        return self._request(
            "POST", f"/api/price-quotes/{quote_id}/accept", {}, headers
        )

    # --- Work shifts ---
    def create_work_shift(self, payload, headers):
        return self._request("POST", "/api/work-shifts", payload, headers)

    def get_work_shift(self, shift_id, headers):
        return self._request("GET", f"/api/work-shifts/{shift_id}", headers=headers)

    def cancel_work_shift(self, shift_id, headers):
        return self._request(
            "POST", f"/api/work-shifts/{shift_id}/cancel", {}, headers
        )

    # --- Corrugator runs ---
    def create_corrugator_run(self, payload, headers):
        return self._request("POST", "/api/corrugator-runs", payload, headers)

    def get_corrugator_run(self, run_id, headers):
        return self._request("GET", f"/api/corrugator-runs/{run_id}", headers=headers)

    def list_corrugator_runs(self, headers, params=None):
        return self._request(
            "GET", "/api/corrugator-runs", headers=headers, params=params
        )

    def attach_order_to_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"/api/corrugator-runs/{run_id}/orders", payload, headers
        )

    def complete_corrugator_run(self, run_id, headers):
        return self._request(
            "POST", f"/api/corrugator-runs/{run_id}/complete", {}, headers
        )

    def cancel_corrugator_run(self, run_id, headers):
        return self._request(
            "POST", f"/api/corrugator-runs/{run_id}/cancel", {}, headers
        )

    # --- Converting bookings ---
    def create_converting_booking(self, payload, headers):
        return self._request("POST", "/api/converting-bookings", payload, headers)

    def get_converting_booking(self, booking_id, headers):
        return self._request(
            "GET", f"/api/converting-bookings/{booking_id}", headers=headers
        )

    def list_converting_bookings(self, headers, params=None):
        return self._request(
            "GET", "/api/converting-bookings", headers=headers, params=params
        )

    def start_converting_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/api/converting-bookings/{booking_id}/start", {}, headers
        )

    def complete_converting_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/api/converting-bookings/{booking_id}/complete", payload, headers
        )

    def cancel_converting_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/api/converting-bookings/{booking_id}/cancel", {}, headers
        )

    # --- Inventory programs ---
    def create_inventory_program(self, payload, headers):
        return self._request("POST", "/api/inventory-programs", payload, headers)

    def get_inventory_program(self, program_id, headers):
        return self._request(
            "GET", f"/api/inventory-programs/{program_id}", headers=headers
        )

    def list_inventory_programs(self, headers, params=None):
        return self._request(
            "GET", "/api/inventory-programs", headers=headers, params=params
        )

    def create_program_receipt(self, program_id, payload, headers):
        return self._request(
            "POST", f"/api/inventory-programs/{program_id}/receipts", payload, headers
        )

    def suspend_inventory_program(self, program_id, headers):
        return self._request(
            "POST", f"/api/inventory-programs/{program_id}/suspend", {}, headers
        )

    def reactivate_inventory_program(self, program_id, headers):
        return self._request(
            "POST", f"/api/inventory-programs/{program_id}/reactivate", {}, headers
        )

    # --- Release orders ---
    def create_release_order(self, program_id, payload, headers):
        return self._request(
            "POST",
            f"/api/inventory-programs/{program_id}/release-orders",
            payload,
            headers,
        )

    def list_release_orders(self, program_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/inventory-programs/{program_id}/release-orders",
            headers=headers,
            params=params,
        )

    def approve_release_order(self, release_id, headers):
        return self._request(
            "POST", f"/api/release-orders/{release_id}/approve", {}, headers
        )

    def ship_release_order(self, release_id, headers):
        return self._request(
            "POST", f"/api/release-orders/{release_id}/ship", {}, headers
        )

    def cancel_release_order(self, release_id, headers):
        return self._request(
            "POST", f"/api/release-orders/{release_id}/cancel", {}, headers
        )

    # --- Quality claims ---
    def create_quality_claim(self, payload, headers):
        return self._request("POST", "/api/quality-claims", payload, headers)

    def list_quality_claims(self, order_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/box-orders/{order_id}/quality-claims",
            headers=headers,
            params=params,
        )

    def start_claim_review(self, claim_id, headers):
        return self._request(
            "POST", f"/api/quality-claims/{claim_id}/start-review", {}, headers
        )

    def resolve_quality_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/api/quality-claims/{claim_id}/resolve", payload, headers
        )


api_client = ApiClient()
