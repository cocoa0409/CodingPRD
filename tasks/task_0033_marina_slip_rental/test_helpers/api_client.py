"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Marinas (PRD §3.1) ─────────────────────────────────────────
    def create_marina(self, payload, headers):
        return self._request("POST", "/marinas", payload, headers)

    def list_marinas(self, headers, params=None):
        return self._request("GET", "/marinas", headers=headers, params=params)

    def get_marina(self, marina_id, headers):
        return self._request("GET", f"/marinas/{marina_id}", headers=headers)

    # ─── Slips (PRD §3.1) ───────────────────────────────────────────
    def create_slip(self, marina_id, payload, headers):
        return self._request(
            "POST", f"/marinas/{marina_id}/slips", payload, headers
        )

    def list_slips(self, headers, params=None):
        return self._request("GET", "/slips", headers=headers, params=params)

    def get_slip(self, slip_id, headers):
        return self._request("GET", f"/slips/{slip_id}", headers=headers)

    def decommission_slip(self, slip_id, headers, payload=None):
        return self._request(
            "POST",
            f"/slips/{slip_id}/decommission",
            payload if payload is not None else {},
            headers,
        )

    # ─── Tenants (PRD §3.2, §3.3) ───────────────────────────────────
    def create_tenant(self, payload, headers):
        return self._request("POST", "/tenants", payload, headers)

    def list_tenants(self, headers, params=None):
        return self._request("GET", "/tenants", headers=headers, params=params)

    def get_tenant(self, tenant_id, headers):
        return self._request("GET", f"/tenants/{tenant_id}", headers=headers)

    def apply_liveaboard(self, tenant_id, payload, headers):
        return self._request(
            "POST", f"/tenants/{tenant_id}/liveaboard-applications", payload, headers
        )

    def approve_liveaboard(self, tenant_id, payload, headers):
        return self._request(
            "POST", f"/tenants/{tenant_id}/liveaboard-approve", payload, headers
        )

    def deny_liveaboard(self, tenant_id, headers, payload=None):
        return self._request(
            "POST",
            f"/tenants/{tenant_id}/liveaboard-deny",
            payload if payload is not None else {},
            headers,
        )

    def revoke_liveaboard(self, tenant_id, payload, headers):
        return self._request(
            "POST", f"/tenants/{tenant_id}/liveaboard-revoke", payload, headers
        )

    # ─── Vessels (PRD §3.2) ─────────────────────────────────────────
    def create_vessel(self, payload, headers):
        return self._request("POST", "/vessels", payload, headers)

    def list_vessels(self, headers, params=None):
        return self._request("GET", "/vessels", headers=headers, params=params)

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"/vessels/{vessel_id}", headers=headers)

    # ─── Leases (PRD §3.4, §3.5, §3.8) ──────────────────────────────
    def create_lease(self, payload, headers):
        return self._request("POST", "/leases", payload, headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/leases", headers=headers, params=params)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/leases/{lease_id}", headers=headers)

    def check_in_lease(self, lease_id, headers, payload=None):
        return self._request(
            "POST",
            f"/leases/{lease_id}/check-in",
            payload if payload is not None else {},
            headers,
        )

    def check_out_lease(self, lease_id, headers, payload=None):
        return self._request(
            "POST",
            f"/leases/{lease_id}/check-out",
            payload if payload is not None else {},
            headers,
        )

    def cancel_lease(self, lease_id, headers, payload=None):
        return self._request(
            "POST",
            f"/leases/{lease_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    # ─── Pump-out Requests (PRD §3.6) ───────────────────────────────
    def create_pump_out_request(self, payload, headers):
        return self._request("POST", "/pump-out-requests", payload, headers)

    def list_pump_out_requests(self, headers, params=None):
        return self._request(
            "GET", "/pump-out-requests", headers=headers, params=params
        )

    def get_pump_out_request(self, request_id, headers):
        return self._request(
            "GET", f"/pump-out-requests/{request_id}", headers=headers
        )

    def complete_pump_out_request(self, request_id, headers, payload=None):
        return self._request(
            "POST",
            f"/pump-out-requests/{request_id}/complete",
            payload if payload is not None else {},
            headers,
        )

    def cancel_pump_out_request(self, request_id, headers, payload=None):
        return self._request(
            "POST",
            f"/pump-out-requests/{request_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    # ─── Tow-Assist Events (PRD §3.7) ───────────────────────────────
    def create_tow_assist_event(self, payload, headers):
        return self._request("POST", "/tow-assist-events", payload, headers)

    def list_tow_assist_events(self, headers, params=None):
        return self._request(
            "GET", "/tow-assist-events", headers=headers, params=params
        )

    def get_tow_assist_event(self, event_id, headers):
        return self._request("GET", f"/tow-assist-events/{event_id}", headers=headers)

    # ─── Transfer Waitlist (PRD §3.9) ───────────────────────────────
    def create_transfer_waitlist_entry(self, payload, headers):
        return self._request("POST", "/transfer-waitlist", payload, headers)

    def list_transfer_waitlist(self, headers, params=None):
        return self._request(
            "GET", "/transfer-waitlist", headers=headers, params=params
        )

    def get_transfer_waitlist_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/transfer-waitlist/{entry_id}", headers=headers
        )

    def cancel_transfer_waitlist_entry(self, entry_id, headers, payload=None):
        return self._request(
            "POST",
            f"/transfer-waitlist/{entry_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    def expire_stale_transfer_waitlist(self, headers, payload=None):
        return self._request(
            "POST",
            "/transfer-waitlist/expire-stale",
            payload if payload is not None else {},
            headers,
        )

    # ─── Test-driving clock (PRD §2.10) ─────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
