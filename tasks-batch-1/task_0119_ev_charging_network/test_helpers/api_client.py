"""API client: one method per endpoint defined in the PRD (§4).

All paths are mounted under the /api prefix. The base _request() method is
inherited from GenericApiClient.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Sites ----
    def create_site(self, payload, headers):
        return self._request("POST", "/api/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/api/sites/{site_id}", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/api/sites", headers=headers, params=params)

    def rebalance_site(self, site_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/rebalance", {}, headers)

    def list_site_load_allocations(self, site_id, headers, params=None):
        return self._request(
            "GET", f"/api/sites/{site_id}/load-allocations", headers=headers, params=params
        )

    def list_site_stalls(self, site_id, headers, params=None):
        return self._request(
            "GET", f"/api/sites/{site_id}/stalls", headers=headers, params=params
        )

    def list_site_tariffs(self, site_id, headers, params=None):
        return self._request(
            "GET", f"/api/sites/{site_id}/tariffs", headers=headers, params=params
        )

    # ---- Stalls ----
    def create_stall(self, payload, headers):
        return self._request("POST", "/api/stalls", payload, headers)

    def get_stall(self, stall_id, headers):
        return self._request("GET", f"/api/stalls/{stall_id}", headers=headers)

    def post_stall_ocpp_status(self, stall_id, payload, headers):
        return self._request("POST", f"/api/stalls/{stall_id}/ocpp-status", payload, headers)

    # ---- Drivers ----
    def create_driver(self, payload, headers):
        return self._request("POST", "/api/drivers", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/api/drivers/{driver_id}", headers=headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/api/drivers", headers=headers, params=params)

    def adjust_wallet(self, driver_id, payload, headers):
        return self._request(
            "POST", f"/api/drivers/{driver_id}/wallet/adjustments", payload, headers
        )

    # ---- eMSP ----
    def create_emsp(self, payload, headers):
        return self._request("POST", "/api/emsps", payload, headers)

    def get_emsp(self, emsp_id, headers):
        return self._request("GET", f"/api/emsps/{emsp_id}", headers=headers)

    # ---- Tariffs ----
    def create_tariff(self, payload, headers):
        return self._request("POST", "/api/tariffs", payload, headers)

    def get_tariff(self, tariff_id, headers):
        return self._request("GET", f"/api/tariffs/{tariff_id}", headers=headers)

    # ---- Reservations ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/api/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/api/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/api/reservations", headers=headers, params=params)

    def confirm_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/api/reservations/{reservation_id}/confirm", {}, headers
        )

    def check_in_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/api/reservations/{reservation_id}/check-in", {}, headers
        )

    def cancel_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/api/reservations/{reservation_id}/cancel", {}, headers
        )

    # ---- Charging Sessions ----
    def create_session(self, payload, headers):
        return self._request("POST", "/api/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/api/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/api/sessions", headers=headers, params=params)

    def create_meter_event(self, session_id, payload, headers):
        return self._request(
            "POST", f"/api/sessions/{session_id}/meter-events", payload, headers
        )

    def list_meter_events(self, session_id, headers, params=None):
        return self._request(
            "GET", f"/api/sessions/{session_id}/meter-events", headers=headers, params=params
        )

    def begin_charging(self, session_id, headers):
        return self._request(
            "POST", f"/api/sessions/{session_id}/begin-charging", {}, headers
        )

    def suspend_session(self, session_id, headers):
        return self._request("POST", f"/api/sessions/{session_id}/suspend", {}, headers)

    def stop_session(self, session_id, headers):
        return self._request("POST", f"/api/sessions/{session_id}/stop", {}, headers)

    def abort_session(self, session_id, headers):
        return self._request("POST", f"/api/sessions/{session_id}/abort", {}, headers)

    def cost_preview(self, session_id, headers):
        return self._request(
            "GET", f"/api/sessions/{session_id}/cost-preview", headers=headers
        )

    # ---- Settlement ----
    def create_settlement_batch(self, payload, headers):
        return self._request("POST", "/api/settlement-batches", payload, headers)

    def get_settlement_batch(self, batch_id, headers):
        return self._request("GET", f"/api/settlement-batches/{batch_id}", headers=headers)

    def list_settlement_batches(self, headers, params=None):
        return self._request(
            "GET", "/api/settlement-batches", headers=headers, params=params
        )

    def add_line_item(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/api/settlement-batches/{batch_id}/line-items", payload, headers
        )

    def list_batch_line_items(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/api/settlement-batches/{batch_id}/line-items",
            headers=headers, params=params,
        )

    def list_settlement_line_items(self, headers, params=None):
        return self._request(
            "GET", "/api/settlement-line-items", headers=headers, params=params
        )

    def get_settlement_line_item(self, line_item_id, headers):
        return self._request(
            "GET", f"/api/settlement-line-items/{line_item_id}", headers=headers
        )

    def lock_batch(self, batch_id, headers):
        return self._request("POST", f"/api/settlement-batches/{batch_id}/lock", {}, headers)

    def settle_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/api/settlement-batches/{batch_id}/settle", payload, headers
        )

    def dispute_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/api/settlement-batches/{batch_id}/dispute", {}, headers
        )

    def reopen_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/api/settlement-batches/{batch_id}/reopen", {}, headers
        )

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
