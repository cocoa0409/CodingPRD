"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Homeowner ────────────────────────────────────────────────────────
    def create_homeowner(self, payload, headers):
        return self._request("POST", "/homeowners", payload, headers)

    def get_homeowner(self, homeowner_id, headers):
        return self._request("GET", f"/homeowners/{homeowner_id}", headers=headers)

    # ─── Contractor ───────────────────────────────────────────────────────
    def create_contractor(self, payload, headers):
        return self._request("POST", "/contractors", payload, headers)

    def get_contractor(self, contractor_id, headers):
        return self._request("GET", f"/contractors/{contractor_id}", headers=headers)

    def list_contractors(self, headers, params=None):
        return self._request("GET", "/contractors", headers=headers, params=params)

    def qualify_contractor(self, contractor_id, headers):
        return self._request("POST", f"/contractors/{contractor_id}/qualify", {}, headers)

    def suspend_contractor(self, contractor_id, headers):
        return self._request("POST", f"/contractors/{contractor_id}/suspend", {}, headers)

    def revoke_contractor(self, contractor_id, headers):
        return self._request("POST", f"/contractors/{contractor_id}/revoke", {}, headers)

    # ─── Project ──────────────────────────────────────────────────────────
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def create_scope_line_item(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/scope-line-items", payload, headers)

    def list_scope_line_items(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/scope-line-items", headers=headers, params=params)

    def get_scope_line_item(self, scope_line_item_id, headers):
        return self._request("GET", f"/scope-line-items/{scope_line_item_id}", headers=headers)

    def list_scope_line_item_bid_line_items(self, scope_line_item_id, headers, params=None):
        return self._request("GET", f"/scope-line-items/{scope_line_item_id}/bid-line-items", headers=headers, params=params)

    def create_milestone(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/milestones", payload, headers)

    def list_milestones(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/milestones", headers=headers, params=params)

    def get_project_estimate(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}/estimate", headers=headers)

    def open_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/open", {}, headers)

    def get_bid_comparison(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}/bid-comparison", headers=headers)

    def award_project(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/award", payload, headers)

    def cancel_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/cancel", {}, headers)

    def complete_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/complete", {}, headers)

    def rate_contractor(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/rate-contractor", payload, headers)

    # ─── Bid ──────────────────────────────────────────────────────────────
    def create_bid(self, payload, headers):
        return self._request("POST", "/bids", payload, headers)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/bids/{bid_id}", headers=headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/bids", headers=headers, params=params)

    def create_bid_line_item(self, bid_id, payload, headers):
        return self._request("POST", f"/bids/{bid_id}/line-items", payload, headers)

    def list_bid_line_items(self, bid_id, headers, params=None):
        return self._request("GET", f"/bids/{bid_id}/line-items", headers=headers, params=params)

    def submit_bid(self, bid_id, headers):
        return self._request("POST", f"/bids/{bid_id}/submit", {}, headers)

    def revise_bid(self, bid_id, headers):
        return self._request("POST", f"/bids/{bid_id}/revise", {}, headers)

    def withdraw_bid(self, bid_id, headers):
        return self._request("POST", f"/bids/{bid_id}/withdraw", {}, headers)

    # ─── Escrow ───────────────────────────────────────────────────────────
    def get_escrow(self, escrow_id, headers):
        return self._request("GET", f"/escrows/{escrow_id}", headers=headers)

    def list_escrows(self, headers, params=None):
        return self._request("GET", "/escrows", headers=headers, params=params)

    def fund_escrow(self, escrow_id, payload, headers):
        return self._request("POST", f"/escrows/{escrow_id}/fund", payload, headers)

    # ─── Draw ─────────────────────────────────────────────────────────────
    def create_draw(self, payload, headers):
        return self._request("POST", "/draws", payload, headers)

    def get_draw(self, draw_id, headers):
        return self._request("GET", f"/draws/{draw_id}", headers=headers)

    def list_draws(self, headers, params=None):
        return self._request("GET", "/draws", headers=headers, params=params)

    def approve_draw(self, draw_id, headers):
        return self._request("POST", f"/draws/{draw_id}/approve", {}, headers)

    def reject_draw(self, draw_id, headers):
        return self._request("POST", f"/draws/{draw_id}/reject", {}, headers)

    def pay_draw(self, draw_id, headers):
        return self._request("POST", f"/draws/{draw_id}/pay", {}, headers)

    # ─── LienWaiver ───────────────────────────────────────────────────────
    def create_lien_waiver(self, payload, headers):
        return self._request("POST", "/lien-waivers", payload, headers)

    def get_lien_waiver(self, lien_waiver_id, headers):
        return self._request("GET", f"/lien-waivers/{lien_waiver_id}", headers=headers)

    def list_lien_waivers(self, headers, params=None):
        return self._request("GET", "/lien-waivers", headers=headers, params=params)

    # ─── ChangeOrder ──────────────────────────────────────────────────────
    def create_change_order(self, payload, headers):
        return self._request("POST", "/change-orders", payload, headers)

    def get_change_order(self, change_order_id, headers):
        return self._request("GET", f"/change-orders/{change_order_id}", headers=headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/change-orders", headers=headers, params=params)

    def approve_change_order(self, change_order_id, payload, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/approve", payload, headers)

    def reject_change_order(self, change_order_id, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/reject", {}, headers)

    # ─── Dispute ──────────────────────────────────────────────────────────
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers)

    # ─── Test-driving clock ───────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
