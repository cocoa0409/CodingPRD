"""API client: one method per endpoint defined in the PRD (§4)."""
import time

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Every endpoint of §4, over a connection that survives a server restart.

    This client is session-scoped while the harness replaces the server process
    between tests, so a pooled keep-alive socket left behind by the previous
    server would otherwise make the first request of a test fail at the transport
    layer. Connections are therefore not reused, and a transport failure — which
    means the request was never delivered — is re-issued on a fresh socket.
    """

    def __init__(self, base_url=None):
        super().__init__(base_url)
        self.session.headers["Connection"] = "close"

    def _request(self, method, path, payload=None, headers=None, params=None):
        last = None
        for attempt in range(3):
            try:
                return super()._request(method, path, payload, headers, params)
            except requests.exceptions.ConnectionError as exc:
                last = exc
                self.session.close()
                self.session = requests.Session()
                self.session.headers["Connection"] = "close"
                time.sleep(0.2 * (attempt + 1))
        raise last

    # ---------------------------------------------------------------- clock
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --------------------------------------------------------- transmitters
    def create_transmitter(self, payload, headers):
        return self._request("POST", "/transmitters", payload, headers)

    def get_transmitter(self, transmitter_id, headers):
        return self._request("GET", f"/transmitters/{transmitter_id}", headers=headers)

    def change_transmitter_power_state(self, transmitter_id, payload, headers):
        return self._request(
            "POST", f"/transmitters/{transmitter_id}/power-state", payload, headers
        )

    def list_transmitter_notifications(self, transmitter_id, headers, params=None):
        return self._request(
            "GET", f"/transmitters/{transmitter_id}/notifications",
            headers=headers, params=params,
        )

    # ------------------------------------------- regulatory notifications
    def get_notification(self, notification_id, headers):
        return self._request(
            "GET", f"/regulatory-notifications/{notification_id}", headers=headers
        )

    def file_notification(self, notification_id, payload, headers):
        return self._request(
            "POST", f"/regulatory-notifications/{notification_id}/file", payload, headers
        )

    # ----------------------------------------------------------- multiplexes
    def create_multiplex(self, payload, headers):
        return self._request("POST", "/multiplexes", payload, headers)

    def get_multiplex(self, multiplex_id, headers):
        return self._request("GET", f"/multiplexes/{multiplex_id}", headers=headers)

    def list_multiplexes(self, headers, params=None):
        return self._request("GET", "/multiplexes", headers=headers, params=params)

    def rebalance_multiplex(self, multiplex_id, payload, headers):
        return self._request(
            "POST", f"/multiplexes/{multiplex_id}/rebalance", payload, headers
        )

    # ------------------------------------------------------------ operators
    def create_operator(self, payload, headers):
        return self._request("POST", "/operators", payload, headers)

    def get_operator(self, operator_id, headers):
        return self._request("GET", f"/operators/{operator_id}", headers=headers)

    def update_operator_status(self, operator_id, payload, headers):
        return self._request(
            "POST", f"/operators/{operator_id}/status", payload, headers
        )

    # ------------------------------------------------------------- channels
    def create_channel(self, payload, headers):
        return self._request("POST", "/channels", payload, headers)

    def get_channel(self, channel_id, headers):
        return self._request("GET", f"/channels/{channel_id}", headers=headers)

    def list_channels(self, headers, params=None):
        return self._request("GET", "/channels", headers=headers, params=params)

    def patch_channel_allocation(self, channel_id, payload, headers):
        return self._request(
            "PATCH", f"/channels/{channel_id}/allocation", payload, headers
        )

    def change_channel_air_state(self, channel_id, payload, headers):
        return self._request(
            "POST", f"/channels/{channel_id}/air-state", payload, headers
        )

    def list_channel_playlists(self, channel_id, headers, params=None):
        return self._request(
            "GET", f"/channels/{channel_id}/playlists", headers=headers, params=params
        )

    def list_channel_feed_windows(self, channel_id, headers, params=None):
        return self._request(
            "GET", f"/channels/{channel_id}/feed-windows",
            headers=headers, params=params,
        )

    # --------------------------------------------------------------- assets
    def create_asset(self, payload, headers):
        return self._request("POST", "/assets", payload, headers)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/assets/{asset_id}", headers=headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/assets", headers=headers, params=params)

    def record_asset_delivery(self, asset_id, payload, headers):
        return self._request("POST", f"/assets/{asset_id}/delivery", payload, headers)

    def submit_qc_report(self, asset_id, payload, headers):
        return self._request("POST", f"/assets/{asset_id}/qc-reports", payload, headers)

    def get_qc_report(self, qc_report_id, headers):
        return self._request("GET", f"/qc-reports/{qc_report_id}", headers=headers)

    def list_qc_reports(self, headers, params=None):
        return self._request("GET", "/qc-reports", headers=headers, params=params)

    def sign_qc_waiver(self, asset_id, payload, headers):
        return self._request("POST", f"/assets/{asset_id}/qc-waivers", payload, headers)

    def retract_asset(self, asset_id, payload, headers):
        return self._request("POST", f"/assets/{asset_id}/retract", payload, headers)

    # ------------------------------------------------------------ playlists
    def ingest_playlist(self, payload, headers):
        return self._request("POST", "/playlists", payload, headers)

    def apply_traffic_revision(self, playlist_id, payload, headers):
        return self._request(
            "POST", f"/playlists/{playlist_id}/traffic-revisions", payload, headers
        )

    def get_playlist(self, playlist_id, headers):
        return self._request("GET", f"/playlists/{playlist_id}", headers=headers)

    def change_playlist_state(self, playlist_id, payload, headers):
        return self._request(
            "POST", f"/playlists/{playlist_id}/state", payload, headers
        )

    def list_playlist_items(self, playlist_id, headers, params=None):
        return self._request(
            "GET", f"/playlists/{playlist_id}/items", headers=headers, params=params
        )

    def get_playlist_as_run(self, playlist_id, headers, params=None):
        return self._request(
            "GET", f"/playlists/{playlist_id}/as-run", headers=headers, params=params
        )

    def get_playlist_reconciliation(self, playlist_id, headers, params=None):
        return self._request(
            "GET", f"/playlists/{playlist_id}/reconciliation",
            headers=headers, params=params,
        )

    # ------------------------------------------------------- playlist items
    def get_playlist_item(self, item_id, headers):
        return self._request("GET", f"/playlist-items/{item_id}", headers=headers)

    def list_all_playlist_items(self, headers, params=None):
        return self._request("GET", "/playlist-items", headers=headers, params=params)

    def post_playout_event(self, item_id, payload, headers):
        return self._request(
            "POST", f"/playlist-items/{item_id}/playout-events", payload, headers
        )

    def substitute_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/playlist-items/{item_id}/substitute", payload, headers
        )

    def get_item_as_run(self, item_id, headers, params=None):
        return self._request(
            "GET", f"/playlist-items/{item_id}/as-run", headers=headers, params=params
        )

    # -------------------------------------------------- network feed windows
    def create_feed_window(self, payload, headers):
        return self._request("POST", "/network-feed-windows", payload, headers)

    def get_feed_window(self, window_id, headers):
        return self._request(
            "GET", f"/network-feed-windows/{window_id}", headers=headers
        )

    def join_feed_window(self, window_id, payload, headers):
        return self._request(
            "POST", f"/network-feed-windows/{window_id}/join", payload, headers
        )

    def breakaway_feed_window(self, window_id, payload, headers):
        return self._request(
            "POST", f"/network-feed-windows/{window_id}/breakaway", payload, headers
        )

    # --------------------------------------------------- emergency overrides
    def create_override(self, payload, headers):
        return self._request("POST", "/emergency-overrides", payload, headers)

    def get_override(self, override_id, headers):
        return self._request(
            "GET", f"/emergency-overrides/{override_id}", headers=headers
        )

    def list_overrides(self, headers, params=None):
        return self._request(
            "GET", "/emergency-overrides", headers=headers, params=params
        )

    def activate_override(self, override_id, payload, headers):
        return self._request(
            "POST", f"/emergency-overrides/{override_id}/activate", payload, headers
        )

    def release_override(self, override_id, payload, headers):
        return self._request(
            "POST", f"/emergency-overrides/{override_id}/release", payload, headers
        )

    # ------------------------------------------------------ technical faults
    def report_fault(self, payload, headers):
        return self._request("POST", "/technical-faults", payload, headers)

    def get_fault(self, fault_id, headers):
        return self._request("GET", f"/technical-faults/{fault_id}", headers=headers)

    def list_faults(self, headers, params=None):
        return self._request("GET", "/technical-faults", headers=headers, params=params)

    def change_fault_state(self, fault_id, payload, headers):
        return self._request(
            "POST", f"/technical-faults/{fault_id}/state", payload, headers
        )

    # ---------------------------------------------------------- spot orders
    def create_spot_order(self, payload, headers):
        return self._request("POST", "/spot-orders", payload, headers)

    def get_spot_order(self, order_id, headers):
        return self._request("GET", f"/spot-orders/{order_id}", headers=headers)

    def list_spot_orders(self, headers, params=None):
        return self._request("GET", "/spot-orders", headers=headers, params=params)

    def place_makegood(self, order_id, payload, headers):
        return self._request(
            "POST", f"/spot-orders/{order_id}/makegoods", payload, headers
        )


api_client = ApiClient()
