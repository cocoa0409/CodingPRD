"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/dme/_clock/set_current_utc", payload, headers)

    # ---- Members ----
    def create_member(self, payload, headers):
        return self._request("POST", "/dme/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/dme/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/dme/members", headers=headers, params=params)

    # ---- Policies ----
    def create_policy(self, payload, headers):
        return self._request("POST", "/dme/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/dme/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/dme/policies", headers=headers, params=params)

    def terminate_policy(self, policy_id, headers):
        return self._request("POST", f"/dme/policies/{policy_id}/terminate", {}, headers)

    # ---- Prescriptions ----
    def create_prescription(self, payload, headers):
        return self._request("POST", "/dme/prescriptions", payload, headers)

    def get_prescription(self, prescription_id, headers):
        return self._request("GET", f"/dme/prescriptions/{prescription_id}", headers=headers)

    def list_prescriptions(self, headers, params=None):
        return self._request("GET", "/dme/prescriptions", headers=headers, params=params)

    def verify_prescription(self, prescription_id, headers):
        return self._request("POST", f"/dme/prescriptions/{prescription_id}/verify", {}, headers)

    def reject_prescription(self, prescription_id, payload, headers):
        return self._request("POST", f"/dme/prescriptions/{prescription_id}/reject", payload, headers)

    def resubmit_prescription(self, prescription_id, headers):
        return self._request("POST", f"/dme/prescriptions/{prescription_id}/resubmit", {}, headers)

    # ---- Catalog ----
    def create_catalog_item(self, payload, headers):
        return self._request("POST", "/dme/catalog-items", payload, headers)

    def get_catalog_item(self, item_id, headers):
        return self._request("GET", f"/dme/catalog-items/{item_id}", headers=headers)

    def list_catalog_items(self, headers, params=None):
        return self._request("GET", "/dme/catalog-items", headers=headers, params=params)

    def list_catalog_item_order_lines(self, item_id, headers, params=None):
        return self._request(
            "GET", f"/dme/catalog-items/{item_id}/order-lines", headers=headers, params=params
        )

    # ---- Pump orders ----
    def create_pump_order(self, payload, headers):
        return self._request("POST", "/dme/pump-orders", payload, headers)

    def get_pump_order(self, order_id, headers):
        return self._request("GET", f"/dme/pump-orders/{order_id}", headers=headers)

    def list_pump_orders(self, headers, params=None):
        return self._request("GET", "/dme/pump-orders", headers=headers, params=params)

    def patch_pump_order(self, order_id, payload, headers):
        return self._request("PATCH", f"/dme/pump-orders/{order_id}", payload, headers)

    def qualify_pump_order(self, order_id, headers):
        return self._request("POST", f"/dme/pump-orders/{order_id}/qualify", {}, headers)

    def cancel_pump_order(self, order_id, headers):
        return self._request("POST", f"/dme/pump-orders/{order_id}/cancel", {}, headers)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/dme/pump-orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/dme/pump-orders/{order_id}/lines", headers=headers, params=params)

    # ---- Prior authorizations ----
    def create_prior_authorization(self, payload, headers):
        return self._request("POST", "/dme/prior-authorizations", payload, headers)

    def get_prior_authorization(self, pa_id, headers):
        return self._request("GET", f"/dme/prior-authorizations/{pa_id}", headers=headers)

    def list_prior_authorizations(self, headers, params=None):
        return self._request("GET", "/dme/prior-authorizations", headers=headers, params=params)

    def payer_decision(self, pa_id, payload, headers):
        return self._request(
            "POST", f"/dme/prior-authorizations/{pa_id}/payer-decision", payload, headers
        )

    def resubmit_prior_authorization(self, pa_id, headers):
        return self._request("POST", f"/dme/prior-authorizations/{pa_id}/resubmit", {}, headers)

    def appeal_prior_authorization(self, pa_id, headers):
        return self._request("POST", f"/dme/prior-authorizations/{pa_id}/appeal", {}, headers)

    # ---- Shipments ----
    def create_shipment(self, payload, headers):
        return self._request("POST", "/dme/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/dme/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/dme/shipments", headers=headers, params=params)

    def advance_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/dme/shipments/{shipment_id}/advance", payload, headers)

    # ---- Claims ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/dme/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/dme/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/dme/claims", headers=headers, params=params)

    def remit_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/dme/claims/{claim_id}/remit", payload, headers)

    def appeal_claim(self, claim_id, headers):
        return self._request("POST", f"/dme/claims/{claim_id}/appeal", {}, headers)

    def void_claim(self, claim_id, headers):
        return self._request("POST", f"/dme/claims/{claim_id}/void", {}, headers)

    # ---- Resupply schedules ----
    def get_resupply_schedule(self, schedule_id, headers):
        return self._request("GET", f"/dme/resupply-schedules/{schedule_id}", headers=headers)

    def list_resupply_schedules(self, headers, params=None):
        return self._request("GET", "/dme/resupply-schedules", headers=headers, params=params)

    def patch_resupply_schedule(self, schedule_id, payload, headers):
        return self._request("PATCH", f"/dme/resupply-schedules/{schedule_id}", payload, headers)

    # ---- Resupply orders ----
    def create_resupply_order(self, payload, headers):
        return self._request("POST", "/dme/resupply-orders", payload, headers)

    def get_resupply_order(self, resupply_order_id, headers):
        return self._request("GET", f"/dme/resupply-orders/{resupply_order_id}", headers=headers)

    def list_resupply_orders(self, headers, params=None):
        return self._request("GET", "/dme/resupply-orders", headers=headers, params=params)

    def cancel_resupply_order(self, resupply_order_id, headers):
        return self._request("POST", f"/dme/resupply-orders/{resupply_order_id}/cancel", {}, headers)

    # ---- Warranty claims ----
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/dme/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/dme/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/dme/warranty-claims", headers=headers, params=params)

    def decide_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/dme/warranty-claims/{claim_id}/decide", payload, headers)

    def reopen_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/dme/warranty-claims/{claim_id}/reopen", {}, headers)

    def resolve_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/dme/warranty-claims/{claim_id}/resolve", {}, headers)


api_client = ApiClient()
