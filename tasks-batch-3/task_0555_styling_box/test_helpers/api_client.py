"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Client subscription -----
    def create_client(self, payload, headers=None):
        return self._request("POST", "/clients", payload, headers=headers)

    def get_client(self, client_id, headers=None):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def complete_style_profile(self, client_id, payload, headers=None):
        return self._request("POST", f"/clients/{client_id}/style-profile", payload, headers=headers)

    def get_style_profile(self, client_id, headers=None):
        return self._request("GET", f"/clients/{client_id}/style-profile", headers=headers)

    def pause_client(self, client_id, headers=None):
        return self._request("POST", f"/clients/{client_id}/pause", {}, headers=headers)

    def resume_client(self, client_id, headers=None):
        return self._request("POST", f"/clients/{client_id}/resume", {}, headers=headers)

    def cancel_client(self, client_id, headers=None):
        return self._request("POST", f"/clients/{client_id}/cancel", {}, headers=headers)

    def skip_client(self, client_id, headers=None):
        return self._request("POST", f"/clients/{client_id}/skip", {}, headers=headers)

    # ----- Fix lifecycle -----
    def schedule_fix(self, client_id, payload, headers=None):
        return self._request("POST", f"/clients/{client_id}/fixes", payload, headers=headers)

    def list_client_fixes(self, client_id, headers=None, params=None):
        return self._request("GET", f"/clients/{client_id}/fixes", headers=headers, params=params)

    def get_fix(self, fix_id, headers=None):
        return self._request("GET", f"/fixes/{fix_id}", headers=headers)

    def list_fixes(self, headers=None, params=None):
        return self._request("GET", "/fixes", headers=headers, params=params)

    def assign_fix(self, fix_id, payload, headers=None):
        return self._request("POST", f"/fixes/{fix_id}/assign", payload, headers=headers)

    def add_fix_item(self, fix_id, payload, headers=None):
        return self._request("POST", f"/fixes/{fix_id}/items", payload, headers=headers)

    def list_fix_items(self, fix_id, headers=None, params=None):
        return self._request("GET", f"/fixes/{fix_id}/items", headers=headers, params=params)

    def remove_fix_item(self, fix_id, item_id, headers=None):
        return self._request("POST", f"/fixes/{fix_id}/items/{item_id}/remove", {}, headers=headers)

    def submit_preview(self, fix_id, headers=None):
        return self._request("POST", f"/fixes/{fix_id}/submit-preview", {}, headers=headers)

    def request_changes(self, fix_id, headers=None):
        return self._request("POST", f"/fixes/{fix_id}/request-changes", {}, headers=headers)

    def ship_fix(self, fix_id, headers=None):
        return self._request("POST", f"/fixes/{fix_id}/ship", {}, headers=headers)

    def mark_delivered(self, fix_id, headers=None):
        return self._request("POST", f"/fixes/{fix_id}/mark-delivered", {}, headers=headers)

    def checkout_fix(self, fix_id, payload, headers=None):
        return self._request("POST", f"/fixes/{fix_id}/checkout", payload, headers=headers)

    def list_fix_returns(self, fix_id, headers=None):
        return self._request("GET", f"/fixes/{fix_id}/returns", headers=headers)

    def ship_return(self, fix_id, return_id, headers=None):
        return self._request("POST", f"/fixes/{fix_id}/returns/{return_id}/ship", {}, headers=headers)

    def receive_return(self, fix_id, return_id, headers=None):
        return self._request("POST", f"/fixes/{fix_id}/returns/{return_id}/receive", {}, headers=headers)

    # ----- Holds -----
    def create_hold(self, client_id, payload, headers=None):
        return self._request("POST", f"/clients/{client_id}/holds", payload, headers=headers)

    def list_holds(self, client_id, headers=None, params=None):
        return self._request("GET", f"/clients/{client_id}/holds", headers=headers, params=params)

    # ----- Feedback -----
    def get_feedback(self, feedback_id, headers=None):
        return self._request("GET", f"/feedback/{feedback_id}", headers=headers)

    def list_feedback(self, headers=None, params=None):
        return self._request("GET", "/feedback", headers=headers, params=params)

    # ----- Catalog / inventory -----
    def create_product(self, payload, headers=None):
        return self._request("POST", "/products", payload, headers=headers)

    def get_product(self, product_id, headers=None):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def discontinue_product(self, product_id, headers=None):
        return self._request("POST", f"/products/{product_id}/discontinue", {}, headers=headers)

    def restock_product(self, product_id, payload, headers=None):
        return self._request("POST", f"/products/{product_id}/restock", payload, headers=headers)

    def list_product_fix_items(self, product_id, headers=None, params=None):
        return self._request("GET", f"/products/{product_id}/fix-items", headers=headers, params=params)

    def list_product_purchases(self, product_id, headers=None, params=None):
        return self._request("GET", f"/products/{product_id}/purchases", headers=headers, params=params)

    # ----- Stylists -----
    def create_stylist(self, payload, headers=None):
        return self._request("POST", "/stylists", payload, headers=headers)

    def deactivate_stylist(self, stylist_id, headers=None):
        return self._request("POST", f"/stylists/{stylist_id}/deactivate", {}, headers=headers)

    # ----- Direct-buy purchases -----
    def create_purchase(self, client_id, payload, headers=None):
        return self._request("POST", f"/clients/{client_id}/purchases", payload, headers=headers)

    def list_purchases(self, client_id, headers=None, params=None):
        return self._request("GET", f"/clients/{client_id}/purchases", headers=headers, params=params)

    def cancel_purchase(self, purchase_id, headers=None):
        return self._request("POST", f"/purchases/{purchase_id}/cancel", {}, headers=headers)

    # ----- System / test-driving -----
    def set_clock(self, payload, headers=None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)

    def run_checkout_sweep(self, headers=None):
        return self._request("POST", "/_ops/run-checkout-sweep", {}, headers=headers)


api_client = ApiClient()
