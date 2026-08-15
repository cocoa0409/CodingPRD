"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/escrow/_clock/set_current_utc", payload, headers)

    # --- Escrow files (PRD §3.1) ---
    def create_file(self, payload, headers):
        return self._request("POST", "/escrow/files", payload, headers)

    def get_file(self, file_id, headers):
        return self._request("GET", f"/escrow/files/{file_id}", headers=headers)

    def list_file_holdbacks(self, file_id, headers, params=None):
        return self._request("GET", f"/escrow/files/{file_id}/holdbacks", headers=headers, params=params)

    # --- Holdbacks (PRD §3.1, §3.2, §3.8) ---
    def create_holdback(self, payload, headers):
        return self._request("POST", "/escrow/holdbacks", payload, headers)

    def get_holdback(self, holdback_id, headers):
        return self._request("GET", f"/escrow/holdbacks/{holdback_id}", headers=headers)

    def submit_holdback(self, holdback_id, headers):
        return self._request("POST", f"/escrow/holdbacks/{holdback_id}/submit", {}, headers)

    def amend_holdback(self, holdback_id, payload, headers):
        return self._request("POST", f"/escrow/holdbacks/{holdback_id}/amend", payload, headers)

    def expire_holdback(self, holdback_id, headers):
        return self._request("POST", f"/escrow/holdbacks/{holdback_id}/expire", {}, headers)

    def close_holdback(self, holdback_id, headers):
        return self._request("POST", f"/escrow/holdbacks/{holdback_id}/close", {}, headers)

    # --- Approvals (PRD §3.2) ---
    def list_approvals(self, holdback_id, headers, params=None):
        return self._request("GET", f"/escrow/holdbacks/{holdback_id}/approvals", headers=headers, params=params)

    def decide_approval(self, approval_id, payload, headers):
        return self._request("POST", f"/escrow/approvals/{approval_id}/decide", payload, headers)

    # --- Bids (PRD §3.3) ---
    def create_bid(self, payload, headers):
        return self._request("POST", "/escrow/bids", payload, headers)

    def list_bids(self, holdback_id, headers, params=None):
        return self._request("GET", f"/escrow/holdbacks/{holdback_id}/bids", headers=headers, params=params)

    def select_bid(self, bid_id, headers):
        return self._request("POST", f"/escrow/bids/{bid_id}/select", {}, headers)

    # --- Work orders (PRD §3.3) ---
    def list_work_orders(self, holdback_id, headers, params=None):
        return self._request("GET", f"/escrow/holdbacks/{holdback_id}/work-orders", headers=headers, params=params)

    def submit_work_order_completion(self, work_order_id, headers):
        return self._request("POST", f"/escrow/work-orders/{work_order_id}/submit-completion", {}, headers)

    # --- Inspections (PRD §3.4) ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/escrow/inspections", payload, headers)

    def list_inspections(self, holdback_id, headers, params=None):
        return self._request("GET", f"/escrow/holdbacks/{holdback_id}/inspections", headers=headers, params=params)

    def report_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/escrow/inspections/{inspection_id}/report", payload, headers)

    # --- Draw requests (PRD §3.5) ---
    def create_draw_request(self, payload, headers):
        return self._request("POST", "/escrow/draw-requests", payload, headers)

    def list_draw_requests(self, holdback_id, headers, params=None):
        return self._request("GET", f"/escrow/holdbacks/{holdback_id}/draw-requests", headers=headers, params=params)

    def approve_draw_request(self, draw_id, headers):
        return self._request("POST", f"/escrow/draw-requests/{draw_id}/approve", {}, headers)

    def pay_draw_request(self, draw_id, headers):
        return self._request("POST", f"/escrow/draw-requests/{draw_id}/pay", {}, headers)

    # --- Extension requests (PRD §3.6) ---
    def create_extension_request(self, payload, headers):
        return self._request("POST", "/escrow/extension-requests", payload, headers)

    def list_extension_requests(self, holdback_id, headers, params=None):
        return self._request("GET", f"/escrow/holdbacks/{holdback_id}/extension-requests", headers=headers, params=params)

    def decide_extension_request(self, extension_id, payload, headers):
        return self._request("POST", f"/escrow/extension-requests/{extension_id}/decide", payload, headers)

    # --- Disputes (PRD §3.7) ---
    def create_dispute(self, payload, headers):
        return self._request("POST", "/escrow/disputes", payload, headers)

    def list_disputes(self, holdback_id, headers, params=None):
        return self._request("GET", f"/escrow/holdbacks/{holdback_id}/disputes", headers=headers, params=params)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/escrow/disputes/{dispute_id}/resolve", payload, headers)

    # --- Shortfall pledges (PRD §3.5) ---
    def list_shortfall_pledges(self, holdback_id, headers, params=None):
        return self._request("GET", f"/escrow/holdbacks/{holdback_id}/shortfall-pledges", headers=headers, params=params)

    def deposit_shortfall_pledge(self, pledge_id, headers):
        return self._request("POST", f"/escrow/shortfall-pledges/{pledge_id}/deposit", {}, headers)

    # --- Trust ledger (PRD §2.7) ---
    def list_ledger_entries(self, holdback_id, headers, params=None):
        return self._request("GET", f"/escrow/holdbacks/{holdback_id}/ledger-entries", headers=headers, params=params)


api_client = ApiClient()
