"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient, build_user_headers

# Default headers for pricing (an opaque ShopManager — PRD §4 permits ShopManager
# to price a quote, and a ShopManager's X-User-ID is not ownership-compared).
_DEFAULT_SHOP_MANAGER_HEADERS = build_user_headers("test-shop-manager-1", "ShopManager")


class ApiClient(GenericApiClient):
    # ---- config / catalog ----
    def create_shop_location(self, payload, headers):
        return self._request("POST", "/shop-locations", payload, headers)

    def get_shop_location(self, shop_id, headers):
        return self._request("GET", f"/shop-locations/{shop_id}", headers=headers)

    def create_state_tint_regulation(self, payload, headers):
        return self._request("POST", "/state-tint-regulations", payload, headers)

    def get_state_tint_regulation(self, reg_id, headers):
        return self._request("GET", f"/state-tint-regulations/{reg_id}", headers=headers)

    def create_film_material(self, payload, headers):
        return self._request("POST", "/film-materials", payload, headers)

    def get_film_material(self, material_id, headers):
        return self._request("GET", f"/film-materials/{material_id}", headers=headers)

    def create_service_package(self, payload, headers):
        return self._request("POST", "/service-packages", payload, headers)

    def get_service_package(self, package_id, headers):
        return self._request("GET", f"/service-packages/{package_id}", headers=headers)

    # ---- vehicle / fleet ----
    def create_vehicle_profile(self, payload, headers):
        return self._request("POST", "/vehicle-profiles", payload, headers)

    def get_vehicle_profile(self, vehicle_id, headers):
        return self._request("GET", f"/vehicle-profiles/{vehicle_id}", headers=headers)

    def create_fleet_account(self, payload, headers):
        return self._request("POST", "/fleet-accounts", payload, headers)

    def get_fleet_account(self, fleet_id, headers):
        return self._request("GET", f"/fleet-accounts/{fleet_id}", headers=headers)

    # ---- medical exemptions ----
    def create_medical_exemption(self, payload, headers):
        return self._request("POST", "/medical-exemptions", payload, headers)

    def get_medical_exemption(self, exemption_id, headers):
        return self._request("GET", f"/medical-exemptions/{exemption_id}", headers=headers)

    def approve_medical_exemption(self, exemption_id, headers):
        return self._request("POST", f"/medical-exemptions/{exemption_id}/approve", headers=headers)

    def reject_medical_exemption(self, exemption_id, headers):
        return self._request("POST", f"/medical-exemptions/{exemption_id}/reject", headers=headers)

    def list_medical_exemptions(self, headers, params=None):
        return self._request("GET", "/medical-exemptions", headers=headers, params=params)

    # ---- bays / installers ----
    def create_bay(self, payload, headers):
        return self._request("POST", "/bays", payload, headers)

    def get_bay(self, bay_id, headers):
        return self._request("GET", f"/bays/{bay_id}", headers=headers)

    def list_bays(self, headers, params=None):
        return self._request("GET", "/bays", headers=headers, params=params)

    def create_installer(self, payload, headers):
        return self._request("POST", "/installers", payload, headers)

    def get_installer(self, installer_id, headers):
        return self._request("GET", f"/installers/{installer_id}", headers=headers)

    def list_installers(self, headers, params=None):
        return self._request("GET", "/installers", headers=headers, params=params)

    # ---- quotes ----
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def add_quote_line(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/lines", payload, headers)

    def list_quote_lines_of_quote(self, quote_id, headers, params=None):
        return self._request("GET", f"/quotes/{quote_id}/lines", headers=headers, params=params)

    def remove_quote_line(self, line_id, headers):
        return self._request("DELETE", f"/quote-lines/{line_id}", headers=headers)

    def get_quote_line(self, line_id, headers):
        return self._request("GET", f"/quote-lines/{line_id}", headers=headers)

    def list_quote_lines(self, headers, params=None):
        return self._request("GET", "/quote-lines", headers=headers, params=params)

    def price_quote(self, quote_id, payload, headers=None):
        return self._request("POST", f"/quotes/{quote_id}/price", payload,
                             headers if headers is not None else _DEFAULT_SHOP_MANAGER_HEADERS)

    def accept_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/accept", payload, headers)

    def void_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/void", headers=headers)

    # ---- work orders ----
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def start_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/start", headers=headers)

    def complete_install_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/complete-install", headers=headers)

    def release_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/release", headers=headers)

    def cancel_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", payload, headers)

    def pay_deposit_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/pay-deposit", payload, headers)

    def invoice_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/invoice", headers=headers)

    def settle_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/settle", headers=headers)

    # ---- wrap proofs ----
    def submit_proof(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/proofs", payload, headers)

    def list_proofs(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/proofs", headers=headers, params=params)

    def approve_proof(self, proof_id, headers):
        return self._request("POST", f"/wrap-proofs/{proof_id}/approve", headers=headers)

    def request_changes_proof(self, proof_id, headers):
        return self._request("POST", f"/wrap-proofs/{proof_id}/request-changes", headers=headers)

    def reject_proof(self, proof_id, headers):
        return self._request("POST", f"/wrap-proofs/{proof_id}/reject", headers=headers)

    # ---- callbacks / redo ----
    def create_callback(self, payload, headers):
        return self._request("POST", "/callbacks", payload, headers)

    def get_callback(self, callback_id, headers):
        return self._request("GET", f"/callbacks/{callback_id}", headers=headers)

    def list_callbacks(self, headers, params=None):
        return self._request("GET", "/callbacks", headers=headers, params=params)

    def resolve_callback(self, callback_id, payload, headers):
        return self._request("POST", f"/callbacks/{callback_id}/resolve", payload, headers)

    def close_callback(self, callback_id, headers):
        return self._request("POST", f"/callbacks/{callback_id}/close", headers=headers)

    # ---- test-driving ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
