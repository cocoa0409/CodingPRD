"""API client: one method per endpoint defined in the MSP Managed IT PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Client ---
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def offboard_client(self, client_id, headers, payload=None):
        return self._request(
            "POST", f"/clients/{client_id}/offboard", payload or {}, headers,
        )

    # --- Site ---
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/sites", headers=headers, params=params)

    # --- Technician ---
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    # --- Contract ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def activate_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST", f"/contracts/{contract_id}/activate", payload or {}, headers,
        )

    def terminate_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST", f"/contracts/{contract_id}/terminate", payload or {}, headers,
        )

    def create_seat_adjustment(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/seat-adjustments", payload, headers,
        )

    def list_seat_adjustments(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/contracts/{contract_id}/seat-adjustments",
            headers=headers, params=params,
        )

    def create_invoice(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/invoices", payload, headers,
        )

    def list_invoices(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/contracts/{contract_id}/invoices",
            headers=headers, params=params,
        )

    # --- Asset ---
    def create_asset(self, payload, headers):
        return self._request("POST", "/assets", payload, headers)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/assets/{asset_id}", headers=headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/assets", headers=headers, params=params)

    def assign_contract_to_asset(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/assets/{asset_id}/assign-contract", payload, headers,
        )

    def unassign_contract_from_asset(self, asset_id, headers, payload=None):
        return self._request(
            "POST", f"/assets/{asset_id}/unassign-contract",
            payload or {}, headers,
        )

    def create_patch_job(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/assets/{asset_id}/patch-jobs", payload, headers,
        )

    def list_patch_jobs(self, asset_id, headers, params=None):
        return self._request(
            "GET", f"/assets/{asset_id}/patch-jobs",
            headers=headers, params=params,
        )

    # --- PatchJob ---
    def start_patch_job(self, patch_job_id, headers, payload=None):
        return self._request(
            "POST", f"/patch-jobs/{patch_job_id}/start",
            payload or {}, headers,
        )

    def report_patch_job(self, patch_job_id, payload, headers):
        return self._request(
            "POST", f"/patch-jobs/{patch_job_id}/report", payload, headers,
        )

    # --- Ticket ---
    def create_ticket(self, payload, headers):
        return self._request("POST", "/tickets", payload, headers)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/tickets", headers=headers, params=params)

    def assign_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/tickets/{ticket_id}/assign", payload, headers,
        )

    def resolve_ticket(self, ticket_id, headers, payload=None):
        return self._request(
            "POST", f"/tickets/{ticket_id}/resolve",
            payload or {}, headers,
        )

    def reopen_ticket(self, ticket_id, headers, payload=None):
        return self._request(
            "POST", f"/tickets/{ticket_id}/reopen",
            payload or {}, headers,
        )

    def create_dispatch(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/tickets/{ticket_id}/dispatches", payload, headers,
        )

    # --- Dispatch ---
    def get_dispatch(self, dispatch_id, headers):
        return self._request(
            "GET", f"/dispatches/{dispatch_id}", headers=headers,
        )

    def list_dispatches(self, headers, params=None):
        return self._request(
            "GET", "/dispatches", headers=headers, params=params,
        )

    def arrive_dispatch(self, dispatch_id, headers, payload=None):
        return self._request(
            "POST", f"/dispatches/{dispatch_id}/arrive",
            payload or {}, headers,
        )

    def complete_dispatch(self, dispatch_id, payload, headers):
        return self._request(
            "POST", f"/dispatches/{dispatch_id}/complete", payload, headers,
        )

    def cancel_dispatch(self, dispatch_id, headers, payload=None):
        return self._request(
            "POST", f"/dispatches/{dispatch_id}/cancel",
            payload or {}, headers,
        )

    # --- Quote ---
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def send_quote(self, quote_id, headers, payload=None):
        return self._request(
            "POST", f"/quotes/{quote_id}/send", payload or {}, headers,
        )

    def accept_quote(self, quote_id, headers, payload=None):
        return self._request(
            "POST", f"/quotes/{quote_id}/accept", payload or {}, headers,
        )

    def request_quote_revision(self, quote_id, headers, payload=None):
        return self._request(
            "POST", f"/quotes/{quote_id}/request-revision",
            payload or {}, headers,
        )

    # --- ProcurementOrder ---
    def create_procurement_order(self, payload, headers):
        return self._request("POST", "/procurement-orders", payload, headers)

    def get_procurement_order(self, order_id, headers):
        return self._request(
            "GET", f"/procurement-orders/{order_id}", headers=headers,
        )

    def list_procurement_orders(self, headers, params=None):
        return self._request(
            "GET", "/procurement-orders", headers=headers, params=params,
        )

    def place_procurement_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/procurement-orders/{order_id}/place",
            payload or {}, headers,
        )

    def cancel_procurement_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/procurement-orders/{order_id}/cancel",
            payload or {}, headers,
        )


api_client = ApiClient()
