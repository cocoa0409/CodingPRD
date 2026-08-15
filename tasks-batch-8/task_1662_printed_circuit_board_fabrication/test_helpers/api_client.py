"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/pcb/_clock/set_current_utc", payload, headers)

    # --- customers (PRD §3.1) ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/pcb/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/pcb/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/pcb/customers", headers=headers, params=params)

    # --- fab orders (PRD §3.1, §3.6, §3.9) ---
    def create_fab_order(self, payload, headers):
        return self._request("POST", "/pcb/fab-orders", payload, headers)

    def get_fab_order(self, order_id, headers):
        return self._request("GET", f"/pcb/fab-orders/{order_id}", headers=headers)

    def list_fab_orders(self, headers, params=None):
        return self._request("GET", "/pcb/fab-orders", headers=headers, params=params)

    def submit_dfm(self, order_id, headers, payload=None):
        return self._request("POST", f"/pcb/fab-orders/{order_id}/submit-dfm", payload or {}, headers)

    def dfm_approve(self, order_id, headers):
        return self._request("POST", f"/pcb/fab-orders/{order_id}/dfm-approve", {}, headers)

    def dfm_reject(self, order_id, payload, headers):
        return self._request("POST", f"/pcb/fab-orders/{order_id}/dfm-reject", payload, headers)

    def release_order(self, order_id, headers):
        return self._request("POST", f"/pcb/fab-orders/{order_id}/release", {}, headers)

    def start_production(self, order_id, headers):
        return self._request("POST", f"/pcb/fab-orders/{order_id}/start-production", {}, headers)

    def hold_order(self, order_id, headers):
        return self._request("POST", f"/pcb/fab-orders/{order_id}/hold", {}, headers)

    def unhold_order(self, order_id, headers):
        return self._request("POST", f"/pcb/fab-orders/{order_id}/unhold", {}, headers)

    def complete_fab(self, order_id, headers):
        return self._request("POST", f"/pcb/fab-orders/{order_id}/complete-fab", {}, headers)

    def ship_order(self, order_id, headers):
        return self._request("POST", f"/pcb/fab-orders/{order_id}/ship", {}, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/pcb/fab-orders/{order_id}/cancel", payload, headers)

    def concede_order(self, order_id, payload, headers):
        return self._request("POST", f"/pcb/fab-orders/{order_id}/concede", payload, headers)

    def requalify_order(self, order_id, payload, headers):
        return self._request("POST", f"/pcb/fab-orders/{order_id}/requalify", payload, headers)

    # --- stackups & impedance spec lines (PRD §3.2) ---
    def create_stackup(self, order_id, payload, headers):
        return self._request("POST", f"/pcb/fab-orders/{order_id}/stackups", payload, headers)

    def list_stackups(self, order_id, headers, params=None):
        return self._request("GET", f"/pcb/fab-orders/{order_id}/stackups", headers=headers, params=params)

    def get_stackup(self, stackup_id, headers):
        return self._request("GET", f"/pcb/stackups/{stackup_id}", headers=headers)

    def lock_stackup(self, stackup_id, headers):
        return self._request("POST", f"/pcb/stackups/{stackup_id}/lock", {}, headers)

    def create_spec_line(self, stackup_id, payload, headers):
        return self._request("POST", f"/pcb/stackups/{stackup_id}/spec-lines", payload, headers)

    def list_spec_lines(self, stackup_id, headers, params=None):
        return self._request("GET", f"/pcb/stackups/{stackup_id}/spec-lines", headers=headers, params=params)

    # --- panel arrays (PRD §3.3) ---
    def create_panel_array(self, order_id, payload, headers):
        return self._request("POST", f"/pcb/fab-orders/{order_id}/panel-arrays", payload, headers)

    def list_panel_arrays(self, order_id, headers, params=None):
        return self._request("GET", f"/pcb/fab-orders/{order_id}/panel-arrays", headers=headers, params=params)

    def get_panel_array(self, array_id, headers):
        return self._request("GET", f"/pcb/panel-arrays/{array_id}", headers=headers)

    def release_panel_array(self, array_id, headers):
        return self._request("POST", f"/pcb/panel-arrays/{array_id}/release", {}, headers)

    # --- drill programs (PRD §3.4) ---
    def create_drill_program(self, order_id, payload, headers):
        return self._request("POST", f"/pcb/fab-orders/{order_id}/drill-programs", payload, headers)

    def list_drill_programs(self, order_id, headers, params=None):
        return self._request("GET", f"/pcb/fab-orders/{order_id}/drill-programs", headers=headers, params=params)

    def submit_drill_program(self, program_id, headers):
        return self._request("POST", f"/pcb/drill-programs/{program_id}/submit", {}, headers)

    def approve_drill_program(self, program_id, headers):
        return self._request("POST", f"/pcb/drill-programs/{program_id}/approve", {}, headers)

    def reject_drill_program(self, program_id, payload, headers):
        return self._request("POST", f"/pcb/drill-programs/{program_id}/reject", payload, headers)

    def revise_drill_program(self, program_id, payload, headers):
        return self._request("POST", f"/pcb/drill-programs/{program_id}/revise", payload, headers)

    # --- laminate lots & reservations (PRD §3.5) ---
    def create_laminate_lot(self, payload, headers):
        return self._request("POST", "/pcb/laminate-lots", payload, headers)

    def get_laminate_lot(self, lot_id, headers):
        return self._request("GET", f"/pcb/laminate-lots/{lot_id}", headers=headers)

    def list_laminate_lots(self, headers, params=None):
        return self._request("GET", "/pcb/laminate-lots", headers=headers, params=params)

    def qualify_lot(self, lot_id, headers):
        return self._request("POST", f"/pcb/laminate-lots/{lot_id}/qualify", {}, headers)

    def quarantine_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/pcb/laminate-lots/{lot_id}/quarantine", payload, headers)

    def create_reservation(self, payload, headers):
        return self._request("POST", "/pcb/laminate-reservations", payload, headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/pcb/laminate-reservations", headers=headers, params=params)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/pcb/laminate-reservations/{reservation_id}", headers=headers)

    def release_reservation(self, reservation_id, headers):
        return self._request("POST", f"/pcb/laminate-reservations/{reservation_id}/release", {}, headers)

    # --- impedance coupons, measurements, lab bookings (PRD §3.7) ---
    def create_coupon(self, order_id, payload, headers):
        return self._request("POST", f"/pcb/fab-orders/{order_id}/coupons", payload, headers)

    def list_order_coupons(self, order_id, headers, params=None):
        return self._request("GET", f"/pcb/fab-orders/{order_id}/coupons", headers=headers, params=params)

    def list_coupons(self, headers, params=None):
        return self._request("GET", "/pcb/coupons", headers=headers, params=params)

    def get_coupon(self, coupon_id, headers):
        return self._request("GET", f"/pcb/coupons/{coupon_id}", headers=headers)

    def retest_coupon(self, coupon_id, headers):
        return self._request("POST", f"/pcb/coupons/{coupon_id}/retest", {}, headers)

    def create_measurement(self, coupon_id, payload, headers):
        return self._request("POST", f"/pcb/coupons/{coupon_id}/measurements", payload, headers)

    def list_coupon_measurements(self, coupon_id, headers, params=None):
        return self._request("GET", f"/pcb/coupons/{coupon_id}/measurements", headers=headers, params=params)

    def create_lab_booking(self, payload, headers):
        return self._request("POST", "/pcb/lab-slot-bookings", payload, headers)

    def list_lab_bookings(self, headers, params=None):
        return self._request("GET", "/pcb/lab-slot-bookings", headers=headers, params=params)

    def get_lab_booking(self, booking_id, headers):
        return self._request("GET", f"/pcb/lab-slot-bookings/{booking_id}", headers=headers)

    def cancel_lab_booking(self, booking_id, headers):
        return self._request("POST", f"/pcb/lab-slot-bookings/{booking_id}/cancel", {}, headers)

    def list_booking_measurements(self, booking_id, headers, params=None):
        return self._request("GET", f"/pcb/lab-slot-bookings/{booking_id}/measurements", headers=headers, params=params)

    # --- electrical test (PRD §3.8) ---
    def create_etest_run(self, order_id, payload, headers):
        return self._request("POST", f"/pcb/fab-orders/{order_id}/etest-runs", payload, headers)

    def list_etest_runs(self, order_id, headers, params=None):
        return self._request("GET", f"/pcb/fab-orders/{order_id}/etest-runs", headers=headers, params=params)

    def start_etest_run(self, run_id, headers):
        return self._request("POST", f"/pcb/etest-runs/{run_id}/start", {}, headers)

    def complete_etest_run(self, run_id, payload, headers):
        return self._request("POST", f"/pcb/etest-runs/{run_id}/complete", payload, headers)

    # --- defects & pareto (PRD §3.8) ---
    def create_defect(self, order_id, payload, headers):
        return self._request("POST", f"/pcb/fab-orders/{order_id}/defects", payload, headers)

    def list_order_defects(self, order_id, headers, params=None):
        return self._request("GET", f"/pcb/fab-orders/{order_id}/defects", headers=headers, params=params)

    def list_array_defects(self, array_id, headers, params=None):
        return self._request("GET", f"/pcb/panel-arrays/{array_id}/defects", headers=headers, params=params)

    def get_defect_pareto(self, headers, params=None):
        return self._request("GET", "/pcb/defects/pareto", headers=headers, params=params)

    # --- quick-turn lanes & slot commitments (PRD §3.1, §3.6) ---
    def create_lane(self, payload, headers):
        return self._request("POST", "/pcb/quick-turn-lanes", payload, headers)

    def list_lanes(self, headers, params=None):
        return self._request("GET", "/pcb/quick-turn-lanes", headers=headers, params=params)

    def get_lane(self, lane_id, headers):
        return self._request("GET", f"/pcb/quick-turn-lanes/{lane_id}", headers=headers)

    def list_lane_slots(self, lane_id, headers, params=None):
        return self._request("GET", f"/pcb/quick-turn-lanes/{lane_id}/slots", headers=headers, params=params)

    # --- invoices (PRD §3.9) ---
    def create_final_invoice(self, order_id, payload, headers):
        return self._request("POST", f"/pcb/fab-orders/{order_id}/invoices/final", payload, headers)

    def list_order_invoices(self, order_id, headers, params=None):
        return self._request("GET", f"/pcb/fab-orders/{order_id}/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/pcb/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/pcb/invoices/{invoice_id}/issue", {}, headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/pcb/invoices/{invoice_id}/pay", {}, headers)


api_client = ApiClient()
