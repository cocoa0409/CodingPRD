"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Trading partners ---
    def create_trading_partner(self, payload, headers):
        return self._request("POST", "/wholesale/trading-partners", payload, headers)

    def list_trading_partners(self, headers, params=None):
        return self._request("GET", "/wholesale/trading-partners", headers=headers, params=params)

    def get_trading_partner(self, partner_id, headers):
        return self._request("GET", f"/wholesale/trading-partners/{partner_id}", headers=headers)

    # --- State licenses ---
    def create_partner_state_license(self, payload, headers):
        return self._request("POST", "/wholesale/partner-state-licenses", payload, headers)

    def list_partner_state_licenses(self, headers, params=None):
        return self._request("GET", "/wholesale/partner-state-licenses", headers=headers, params=params)

    def get_partner_state_license(self, license_id, headers):
        return self._request("GET", f"/wholesale/partner-state-licenses/{license_id}", headers=headers)

    def suspend_license(self, license_id, headers):
        return self._request("POST", f"/wholesale/partner-state-licenses/{license_id}/suspend", {}, headers)

    def reinstate_license(self, license_id, headers):
        return self._request("POST", f"/wholesale/partner-state-licenses/{license_id}/reinstate", {}, headers)

    def revoke_license(self, license_id, headers):
        return self._request("POST", f"/wholesale/partner-state-licenses/{license_id}/revoke", {}, headers)

    # --- Products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/wholesale/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/wholesale/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/wholesale/products/{product_id}", headers=headers)

    def declare_shortage(self, product_id, headers):
        return self._request("POST", f"/wholesale/products/{product_id}/declare-shortage", {}, headers)

    # --- Allocation policies ---
    def create_allocation_policy(self, payload, headers):
        return self._request("POST", "/wholesale/allocation-policies", payload, headers)

    def list_allocation_policies(self, headers, params=None):
        return self._request("GET", "/wholesale/allocation-policies", headers=headers, params=params)

    def get_allocation_policy(self, policy_id, headers):
        return self._request("GET", f"/wholesale/allocation-policies/{policy_id}", headers=headers)

    def close_allocation_policy(self, policy_id, headers):
        return self._request("POST", f"/wholesale/allocation-policies/{policy_id}/close", {}, headers)

    # --- Serialized cases & units ---
    def create_serialized_case(self, payload, headers):
        return self._request("POST", "/wholesale/serialized-cases", payload, headers)

    def list_serialized_cases(self, headers, params=None):
        return self._request("GET", "/wholesale/serialized-cases", headers=headers, params=params)

    def get_serialized_case(self, case_id, headers):
        return self._request("GET", f"/wholesale/serialized-cases/{case_id}", headers=headers)

    def list_case_units(self, case_id, headers, params=None):
        return self._request("GET", f"/wholesale/serialized-cases/{case_id}/units", headers=headers, params=params)

    def create_serialized_unit(self, payload, headers):
        return self._request("POST", "/wholesale/serialized-units", payload, headers)

    def list_serialized_units(self, headers, params=None):
        return self._request("GET", "/wholesale/serialized-units", headers=headers, params=params)

    def get_serialized_unit(self, unit_id, headers):
        return self._request("GET", f"/wholesale/serialized-units/{unit_id}", headers=headers)

    # --- EPCIS events ---
    def create_epcis_event(self, payload, headers):
        return self._request("POST", "/wholesale/epcis-events", payload, headers)

    def list_epcis_events(self, headers, params=None):
        return self._request("GET", "/wholesale/epcis-events", headers=headers, params=params)

    def get_epcis_event(self, event_id, headers):
        return self._request("GET", f"/wholesale/epcis-events/{event_id}", headers=headers)

    # --- Purchase orders & lines ---
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/wholesale/purchase-orders", payload, headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/wholesale/purchase-orders", headers=headers, params=params)

    def get_purchase_order(self, order_id, headers):
        return self._request("GET", f"/wholesale/purchase-orders/{order_id}", headers=headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/wholesale/purchase-orders/{order_id}/lines", headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/wholesale/purchase-orders/{order_id}/lines", payload, headers)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/wholesale/order-lines/{line_id}", headers=headers)

    def list_all_order_lines(self, headers, params=None):
        return self._request("GET", "/wholesale/order-lines", headers=headers, params=params)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/wholesale/purchase-orders/{order_id}/confirm", {}, headers)

    def allocate_order(self, order_id, payload, headers):
        return self._request("POST", f"/wholesale/purchase-orders/{order_id}/allocate", payload, headers)

    def ship_order(self, order_id, payload, headers):
        return self._request("POST", f"/wholesale/purchase-orders/{order_id}/ship", payload, headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST", f"/wholesale/purchase-orders/{order_id}/deliver", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/wholesale/purchase-orders/{order_id}/cancel", {}, headers)

    def post_payment(self, order_id, payload, headers):
        return self._request("POST", f"/wholesale/purchase-orders/{order_id}/payments", payload, headers)

    # --- Suspect investigations ---
    def create_suspect_investigation(self, payload, headers):
        return self._request("POST", "/wholesale/suspect-investigations", payload, headers)

    def list_suspect_investigations(self, headers, params=None):
        return self._request("GET", "/wholesale/suspect-investigations", headers=headers, params=params)

    def get_suspect_investigation(self, investigation_id, headers):
        return self._request("GET", f"/wholesale/suspect-investigations/{investigation_id}", headers=headers)

    def quarantine_investigation(self, investigation_id, headers):
        return self._request("POST", f"/wholesale/suspect-investigations/{investigation_id}/quarantine", {}, headers)

    def clear_investigation(self, investigation_id, headers):
        return self._request("POST", f"/wholesale/suspect-investigations/{investigation_id}/clear", {}, headers)

    def confirm_illegitimate(self, investigation_id, headers):
        return self._request("POST", f"/wholesale/suspect-investigations/{investigation_id}/confirm-illegitimate", {}, headers)

    def reopen_investigation(self, investigation_id, headers):
        return self._request("POST", f"/wholesale/suspect-investigations/{investigation_id}/reopen", {}, headers)

    # --- Chargeback claims ---
    def create_chargeback_claim(self, payload, headers):
        return self._request("POST", "/wholesale/chargeback-claims", payload, headers)

    def list_chargeback_claims(self, headers, params=None):
        return self._request("GET", "/wholesale/chargeback-claims", headers=headers, params=params)

    def get_chargeback_claim(self, claim_id, headers):
        return self._request("GET", f"/wholesale/chargeback-claims/{claim_id}", headers=headers)

    def validate_chargeback_claim(self, claim_id, headers):
        return self._request("POST", f"/wholesale/chargeback-claims/{claim_id}/validate", {}, headers)

    def settle_chargeback_claim(self, claim_id, headers):
        return self._request("POST", f"/wholesale/chargeback-claims/{claim_id}/settle", {}, headers)

    def deny_chargeback_claim(self, claim_id, headers):
        return self._request("POST", f"/wholesale/chargeback-claims/{claim_id}/deny", {}, headers)

    # --- Return authorizations ---
    def create_return_authorization(self, payload, headers):
        return self._request("POST", "/wholesale/return-authorizations", payload, headers)

    def list_return_authorizations(self, headers, params=None):
        return self._request("GET", "/wholesale/return-authorizations", headers=headers, params=params)

    def get_return_authorization(self, return_id, headers):
        return self._request("GET", f"/wholesale/return-authorizations/{return_id}", headers=headers)

    def receive_return(self, return_id, headers):
        return self._request("POST", f"/wholesale/return-authorizations/{return_id}/receive", {}, headers)

    def credit_return(self, return_id, headers):
        return self._request("POST", f"/wholesale/return-authorizations/{return_id}/credit", {}, headers)

    def reject_return(self, return_id, headers):
        return self._request("POST", f"/wholesale/return-authorizations/{return_id}/reject", {}, headers)

    # --- Test-driving logical clock ---
    def set_logical_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
