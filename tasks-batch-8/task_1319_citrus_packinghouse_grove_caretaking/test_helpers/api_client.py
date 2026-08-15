"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint; PRD §2.5)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/packinghouse/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Growers (PRD §3.1)
    # ------------------------------------------------------------------
    def create_grower(self, payload, headers):
        return self._request("POST", "/packinghouse/growers", payload, headers)

    def list_growers(self, headers, params=None):
        return self._request("GET", "/packinghouse/growers", headers=headers, params=params)

    def get_grower(self, grower_id, headers):
        return self._request("GET", f"/packinghouse/growers/{grower_id}", headers=headers)

    def suspend_grower(self, grower_id, headers):
        return self._request("POST", f"/packinghouse/growers/{grower_id}/suspend", {}, headers)

    def reinstate_grower(self, grower_id, headers):
        return self._request("POST", f"/packinghouse/growers/{grower_id}/reinstate", {}, headers)

    def terminate_grower(self, grower_id, headers):
        return self._request("POST", f"/packinghouse/growers/{grower_id}/terminate", {}, headers)

    # ------------------------------------------------------------------
    # Groves (PRD §3.1)
    # ------------------------------------------------------------------
    def create_grove(self, payload, headers):
        return self._request("POST", "/packinghouse/groves", payload, headers)

    def list_groves(self, headers, params=None):
        return self._request("GET", "/packinghouse/groves", headers=headers, params=params)

    def get_grove(self, grove_id, headers):
        return self._request("GET", f"/packinghouse/groves/{grove_id}", headers=headers)

    def retire_grove(self, grove_id, headers):
        return self._request("POST", f"/packinghouse/groves/{grove_id}/retire", {}, headers)

    # ------------------------------------------------------------------
    # Maturity tests (PRD §3.2)
    # ------------------------------------------------------------------
    def create_maturity_test(self, grove_id, payload, headers):
        return self._request("POST", f"/packinghouse/groves/{grove_id}/maturity-tests",
                             payload, headers)

    def list_maturity_tests(self, grove_id, headers, params=None):
        return self._request("GET", f"/packinghouse/groves/{grove_id}/maturity-tests",
                             headers=headers, params=params)

    def get_maturity_test(self, test_id, headers):
        return self._request("GET", f"/packinghouse/maturity-tests/{test_id}", headers=headers)

    # ------------------------------------------------------------------
    # Harvest crews (PRD §3.2)
    # ------------------------------------------------------------------
    def create_crew(self, payload, headers):
        return self._request("POST", "/packinghouse/crews", payload, headers)

    def list_crews(self, headers, params=None):
        return self._request("GET", "/packinghouse/crews", headers=headers, params=params)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/packinghouse/crews/{crew_id}", headers=headers)

    def deactivate_crew(self, crew_id, headers):
        return self._request("POST", f"/packinghouse/crews/{crew_id}/deactivate", {}, headers)

    # ------------------------------------------------------------------
    # Harvest assignments (PRD §3.2)
    # ------------------------------------------------------------------
    def create_assignment(self, payload, headers):
        return self._request("POST", "/packinghouse/harvest-assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/packinghouse/harvest-assignments",
                             headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/packinghouse/harvest-assignments/{assignment_id}",
                             headers=headers)

    def start_assignment(self, assignment_id, headers):
        return self._request("POST", f"/packinghouse/harvest-assignments/{assignment_id}/start",
                             {}, headers)

    def complete_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/packinghouse/harvest-assignments/{assignment_id}/complete",
                             payload, headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"/packinghouse/harvest-assignments/{assignment_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Deliveries (PRD §3.3)
    # ------------------------------------------------------------------
    def create_delivery(self, payload, headers):
        return self._request("POST", "/packinghouse/deliveries", payload, headers)

    def list_deliveries(self, headers, params=None):
        return self._request("GET", "/packinghouse/deliveries", headers=headers, params=params)

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/packinghouse/deliveries/{delivery_id}", headers=headers)

    def hold_delivery(self, delivery_id, headers):
        return self._request("POST", f"/packinghouse/deliveries/{delivery_id}/hold", {}, headers)

    def release_delivery(self, delivery_id, headers):
        return self._request("POST", f"/packinghouse/deliveries/{delivery_id}/release", {}, headers)

    def condemn_delivery(self, delivery_id, headers):
        return self._request("POST", f"/packinghouse/deliveries/{delivery_id}/condemn", {}, headers)

    def close_delivery(self, delivery_id, headers):
        return self._request("POST", f"/packinghouse/deliveries/{delivery_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Degreening rooms (PRD §3.4)
    # ------------------------------------------------------------------
    def create_room(self, payload, headers):
        return self._request("POST", "/packinghouse/degreening-rooms", payload, headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/packinghouse/degreening-rooms",
                             headers=headers, params=params)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/packinghouse/degreening-rooms/{room_id}", headers=headers)

    def enter_maintenance(self, room_id, headers):
        return self._request("POST", f"/packinghouse/degreening-rooms/{room_id}/enter-maintenance",
                             {}, headers)

    def exit_maintenance(self, room_id, headers):
        return self._request("POST", f"/packinghouse/degreening-rooms/{room_id}/exit-maintenance",
                             {}, headers)

    # ------------------------------------------------------------------
    # Degreening sessions (PRD §3.4)
    # ------------------------------------------------------------------
    def create_session(self, payload, headers):
        return self._request("POST", "/packinghouse/degreening-sessions", payload, headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/packinghouse/degreening-sessions",
                             headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/packinghouse/degreening-sessions/{session_id}",
                             headers=headers)

    def release_session(self, session_id, payload, headers):
        return self._request("POST", f"/packinghouse/degreening-sessions/{session_id}/release",
                             payload, headers)

    def abort_session(self, session_id, headers):
        return self._request("POST", f"/packinghouse/degreening-sessions/{session_id}/abort",
                             {}, headers)

    # ------------------------------------------------------------------
    # Sort runs (PRD §3.5)
    # ------------------------------------------------------------------
    def create_sort_run(self, payload, headers):
        return self._request("POST", "/packinghouse/sort-runs", payload, headers)

    def list_sort_runs(self, headers, params=None):
        return self._request("GET", "/packinghouse/sort-runs", headers=headers, params=params)

    def get_sort_run(self, run_id, headers):
        return self._request("GET", f"/packinghouse/sort-runs/{run_id}", headers=headers)

    def verify_sort_run(self, run_id, headers):
        return self._request("POST", f"/packinghouse/sort-runs/{run_id}/verify", {}, headers)

    def post_sort_run(self, run_id, headers):
        return self._request("POST", f"/packinghouse/sort-runs/{run_id}/post", {}, headers)

    def void_sort_run(self, run_id, headers):
        return self._request("POST", f"/packinghouse/sort-runs/{run_id}/void", {}, headers)

    def reverse_sort_run(self, run_id, headers):
        return self._request("POST", f"/packinghouse/sort-runs/{run_id}/reverse", {}, headers)

    # ------------------------------------------------------------------
    # Allocation channels (PRD §3.5)
    # ------------------------------------------------------------------
    def create_channel(self, payload, headers):
        return self._request("POST", "/packinghouse/allocation-channels", payload, headers)

    def list_channels(self, headers, params=None):
        return self._request("GET", "/packinghouse/allocation-channels",
                             headers=headers, params=params)

    def get_channel(self, channel_id, headers):
        return self._request("GET", f"/packinghouse/allocation-channels/{channel_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Pools (PRD §3.6)
    # ------------------------------------------------------------------
    def create_pool(self, payload, headers):
        return self._request("POST", "/packinghouse/pools", payload, headers)

    def list_pools(self, headers, params=None):
        return self._request("GET", "/packinghouse/pools", headers=headers, params=params)

    def get_pool(self, pool_id, headers):
        return self._request("GET", f"/packinghouse/pools/{pool_id}", headers=headers)

    def close_pool_intake(self, pool_id, headers):
        return self._request("POST", f"/packinghouse/pools/{pool_id}/close-intake", {}, headers)

    def set_pool_price(self, pool_id, payload, headers):
        return self._request("POST", f"/packinghouse/pools/{pool_id}/set-price", payload, headers)

    def settle_pool(self, pool_id, headers):
        return self._request("POST", f"/packinghouse/pools/{pool_id}/settle", {}, headers)

    def get_settlement_statements(self, pool_id, headers):
        return self._request("GET", f"/packinghouse/pools/{pool_id}/settlement-statements",
                             headers=headers)

    # ------------------------------------------------------------------
    # Advance payments (PRD §3.6)
    # ------------------------------------------------------------------
    def create_advance(self, payload, headers):
        return self._request("POST", "/packinghouse/advances", payload, headers)

    def list_advances(self, headers, params=None):
        return self._request("GET", "/packinghouse/advances", headers=headers, params=params)

    def get_advance(self, advance_id, headers):
        return self._request("GET", f"/packinghouse/advances/{advance_id}", headers=headers)

    def approve_advance(self, advance_id, headers):
        return self._request("POST", f"/packinghouse/advances/{advance_id}/approve", {}, headers)

    def deny_advance(self, advance_id, headers):
        return self._request("POST", f"/packinghouse/advances/{advance_id}/deny", {}, headers)

    def write_off_advance(self, advance_id, headers):
        return self._request("POST", f"/packinghouse/advances/{advance_id}/write-off", {}, headers)

    # ------------------------------------------------------------------
    # Caretaking service orders (PRD §3.7)
    # ------------------------------------------------------------------
    def create_caretaking_order(self, payload, headers):
        return self._request("POST", "/packinghouse/caretaking-orders", payload, headers)

    def list_caretaking_orders(self, headers, params=None):
        return self._request("GET", "/packinghouse/caretaking-orders",
                             headers=headers, params=params)

    def get_caretaking_order(self, order_id, headers):
        return self._request("GET", f"/packinghouse/caretaking-orders/{order_id}", headers=headers)

    def schedule_caretaking_order(self, order_id, headers):
        return self._request("POST", f"/packinghouse/caretaking-orders/{order_id}/schedule",
                             {}, headers)

    def complete_caretaking_order(self, order_id, headers):
        return self._request("POST", f"/packinghouse/caretaking-orders/{order_id}/complete",
                             {}, headers)

    def cancel_caretaking_order(self, order_id, headers):
        return self._request("POST", f"/packinghouse/caretaking-orders/{order_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Caretaking invoices (PRD §3.7)
    # ------------------------------------------------------------------
    def create_caretaking_invoice(self, payload, headers):
        return self._request("POST", "/packinghouse/caretaking-invoices", payload, headers)

    def list_caretaking_invoices(self, headers, params=None):
        return self._request("GET", "/packinghouse/caretaking-invoices",
                             headers=headers, params=params)

    def get_caretaking_invoice(self, invoice_id, headers):
        return self._request("GET", f"/packinghouse/caretaking-invoices/{invoice_id}",
                             headers=headers)

    def issue_caretaking_invoice(self, invoice_id, headers):
        return self._request("POST", f"/packinghouse/caretaking-invoices/{invoice_id}/issue",
                             {}, headers)

    def pay_caretaking_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/packinghouse/caretaking-invoices/{invoice_id}/payments",
                             payload, headers)

    def dispute_caretaking_invoice(self, invoice_id, headers):
        return self._request("POST", f"/packinghouse/caretaking-invoices/{invoice_id}/dispute",
                             {}, headers)

    def reissue_caretaking_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/packinghouse/caretaking-invoices/{invoice_id}/reissue",
                             payload, headers)

    def void_caretaking_invoice(self, invoice_id, headers):
        return self._request("POST", f"/packinghouse/caretaking-invoices/{invoice_id}/void",
                             {}, headers)

    # ------------------------------------------------------------------
    # Quarantine orders (PRD §3.8)
    # ------------------------------------------------------------------
    def create_quarantine_order(self, payload, headers):
        return self._request("POST", "/packinghouse/quarantine-orders", payload, headers)

    def list_quarantine_orders(self, headers, params=None):
        return self._request("GET", "/packinghouse/quarantine-orders",
                             headers=headers, params=params)

    def get_quarantine_order(self, order_id, headers):
        return self._request("GET", f"/packinghouse/quarantine-orders/{order_id}", headers=headers)

    def release_quarantine_order(self, order_id, payload, headers):
        return self._request("POST", f"/packinghouse/quarantine-orders/{order_id}/release",
                             payload, headers)

    # ------------------------------------------------------------------
    # Export lots (PRD §3.9)
    # ------------------------------------------------------------------
    def create_export_lot(self, payload, headers):
        return self._request("POST", "/packinghouse/export-lots", payload, headers)

    def list_export_lots(self, headers, params=None):
        return self._request("GET", "/packinghouse/export-lots", headers=headers, params=params)

    def get_export_lot(self, lot_id, headers):
        return self._request("GET", f"/packinghouse/export-lots/{lot_id}", headers=headers)

    def request_inspection(self, lot_id, headers):
        return self._request("POST", f"/packinghouse/export-lots/{lot_id}/request-inspection",
                             {}, headers)

    def rework_export_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/packinghouse/export-lots/{lot_id}/rework",
                             payload, headers)

    def divert_export_lot(self, lot_id, headers):
        return self._request("POST", f"/packinghouse/export-lots/{lot_id}/divert", {}, headers)

    def ship_export_lot(self, lot_id, headers):
        return self._request("POST", f"/packinghouse/export-lots/{lot_id}/ship", {}, headers)

    # ------------------------------------------------------------------
    # Phytosanitary certificates (PRD §3.9)
    # ------------------------------------------------------------------
    def create_phyto_certificate(self, lot_id, payload, headers):
        return self._request("POST",
                             f"/packinghouse/export-lots/{lot_id}/phytosanitary-certificates",
                             payload, headers)

    def list_phyto_certificates(self, lot_id, headers, params=None):
        return self._request("GET",
                             f"/packinghouse/export-lots/{lot_id}/phytosanitary-certificates",
                             headers=headers, params=params)

    def get_phyto_certificate(self, certificate_id, headers):
        return self._request("GET",
                             f"/packinghouse/phytosanitary-certificates/{certificate_id}",
                             headers=headers)

    def revoke_phyto_certificate(self, certificate_id, headers):
        return self._request("POST",
                             f"/packinghouse/phytosanitary-certificates/{certificate_id}/revoke",
                             {}, headers)


api_client = ApiClient()
