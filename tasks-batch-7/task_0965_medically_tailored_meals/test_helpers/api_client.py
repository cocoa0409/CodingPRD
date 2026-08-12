"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/mtm/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/mtm/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/mtm/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/mtm/members/{member_id}", headers=headers)

    def set_member_status(self, member_id, target_status, headers):
        return self._request("POST", f"/mtm/members/{member_id}/status",
                             {"target_status": target_status}, headers)

    def get_member_summary(self, member_id, headers):
        return self._request("GET", f"/mtm/members/{member_id}/summary", headers=headers)

    # --- referrals ---
    def create_referral(self, payload, headers):
        return self._request("POST", "/mtm/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/mtm/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/mtm/referrals/{referral_id}", headers=headers)

    def decide_referral(self, referral_id, decision, headers):
        return self._request("POST", f"/mtm/referrals/{referral_id}/decision",
                             {"decision": decision}, headers)

    # --- diet prescriptions ---
    def create_prescription(self, payload, headers):
        return self._request("POST", "/mtm/diet-prescriptions", payload, headers)

    def list_prescriptions(self, headers, params=None):
        return self._request("GET", "/mtm/diet-prescriptions", headers=headers, params=params)

    def get_prescription(self, prescription_id, headers):
        return self._request("GET", f"/mtm/diet-prescriptions/{prescription_id}", headers=headers)

    def activate_prescription(self, prescription_id, expected_member_version, headers):
        return self._request("POST", f"/mtm/diet-prescriptions/{prescription_id}/activate",
                             {"expected_member_version": expected_member_version}, headers)

    def revoke_prescription(self, prescription_id, headers):
        return self._request("POST", f"/mtm/diet-prescriptions/{prescription_id}/revoke",
                             {}, headers)

    # --- menu items ---
    def create_menu_item(self, payload, headers):
        return self._request("POST", "/mtm/menu-items", payload, headers)

    def list_menu_items(self, headers, params=None):
        return self._request("GET", "/mtm/menu-items", headers=headers, params=params)

    def get_menu_item(self, menu_item_id, headers):
        return self._request("GET", f"/mtm/menu-items/{menu_item_id}", headers=headers)

    def retire_menu_item(self, menu_item_id, headers):
        return self._request("POST", f"/mtm/menu-items/{menu_item_id}/retire", {}, headers)

    def list_menu_item_cycle_items(self, menu_item_id, headers):
        return self._request("GET", f"/mtm/menu-items/{menu_item_id}/menu-cycle-items",
                             headers=headers)

    # --- menu cycles ---
    def create_menu_cycle(self, payload, headers):
        return self._request("POST", "/mtm/menu-cycles", payload, headers)

    def list_menu_cycles(self, headers, params=None):
        return self._request("GET", "/mtm/menu-cycles", headers=headers, params=params)

    def get_menu_cycle(self, cycle_id, headers):
        return self._request("GET", f"/mtm/menu-cycles/{cycle_id}", headers=headers)

    def list_cycle_items(self, cycle_id, headers):
        return self._request("GET", f"/mtm/menu-cycles/{cycle_id}/items", headers=headers)

    def add_cycle_item(self, cycle_id, payload, headers):
        return self._request("POST", f"/mtm/menu-cycles/{cycle_id}/items", payload, headers)

    def remove_cycle_item(self, cycle_id, item_id, headers):
        return self._request("DELETE", f"/mtm/menu-cycles/{cycle_id}/items/{item_id}",
                             headers=headers)

    def get_cycle_compliance(self, cycle_id, headers):
        return self._request("GET", f"/mtm/menu-cycles/{cycle_id}/compliance", headers=headers)

    def freeze_cycle(self, cycle_id, headers):
        return self._request("POST", f"/mtm/menu-cycles/{cycle_id}/freeze", {}, headers)

    def unfreeze_cycle(self, cycle_id, headers):
        return self._request("POST", f"/mtm/menu-cycles/{cycle_id}/unfreeze", {}, headers)

    def cancel_cycle(self, cycle_id, headers):
        return self._request("POST", f"/mtm/menu-cycles/{cycle_id}/cancel", {}, headers)

    # --- delivery routes ---
    def create_route(self, payload, headers):
        return self._request("POST", "/mtm/delivery-routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/mtm/delivery-routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/mtm/delivery-routes/{route_id}", headers=headers)

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"/mtm/delivery-routes/{route_id}/dispatch", {}, headers)

    def complete_route(self, route_id, headers):
        return self._request("POST", f"/mtm/delivery-routes/{route_id}/complete", {}, headers)

    # --- deliveries ---
    def create_delivery(self, payload, headers):
        return self._request("POST", "/mtm/deliveries", payload, headers)

    def list_deliveries(self, headers, params=None):
        return self._request("GET", "/mtm/deliveries", headers=headers, params=params)

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/mtm/deliveries/{delivery_id}", headers=headers)

    def out_for_delivery(self, delivery_id, headers):
        return self._request("POST", f"/mtm/deliveries/{delivery_id}/out-for-delivery",
                             {}, headers)

    def mark_delivered(self, delivery_id, headers):
        return self._request("POST", f"/mtm/deliveries/{delivery_id}/mark-delivered",
                             {}, headers)

    def mark_failed(self, delivery_id, headers):
        return self._request("POST", f"/mtm/deliveries/{delivery_id}/mark-failed",
                             {}, headers)

    def confirm_receipt(self, delivery_id, headers):
        return self._request("POST", f"/mtm/deliveries/{delivery_id}/confirm-receipt",
                             {}, headers)

    def add_cold_chain_reading(self, delivery_id, payload, headers):
        return self._request("POST", f"/mtm/deliveries/{delivery_id}/cold-chain-readings",
                             payload, headers)

    def list_cold_chain_readings(self, delivery_id, headers):
        return self._request("GET", f"/mtm/deliveries/{delivery_id}/cold-chain-readings",
                             headers=headers)

    # --- reauthorizations ---
    def create_reauthorization(self, payload, headers):
        return self._request("POST", "/mtm/reauthorizations", payload, headers)

    def list_reauthorizations(self, headers, params=None):
        return self._request("GET", "/mtm/reauthorizations", headers=headers, params=params)

    def get_reauthorization(self, authorization_id, headers):
        return self._request("GET", f"/mtm/reauthorizations/{authorization_id}", headers=headers)

    def approve_reauthorization(self, authorization_id, authorization_number, headers):
        return self._request("POST", f"/mtm/reauthorizations/{authorization_id}/approve",
                             {"authorization_number": authorization_number}, headers)

    def deny_reauthorization(self, authorization_id, reason, headers):
        return self._request("POST", f"/mtm/reauthorizations/{authorization_id}/deny",
                             {"reason": reason}, headers)

    # --- outcome assessments ---
    def create_outcome_assessment(self, payload, headers):
        return self._request("POST", "/mtm/outcome-assessments", payload, headers)

    def list_outcome_assessments(self, headers, params=None):
        return self._request("GET", "/mtm/outcome-assessments", headers=headers, params=params)

    def get_outcome_assessment(self, assessment_id, headers):
        return self._request("GET", f"/mtm/outcome-assessments/{assessment_id}", headers=headers)

    # --- claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/mtm/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/mtm/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/mtm/claims/{claim_id}", headers=headers)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/mtm/claims/{claim_id}/submit", {}, headers)

    def remit_claim(self, claim_id, outcome, headers, remitted_amount_cents=None):
        payload = {"outcome": outcome}
        if remitted_amount_cents is not None:
            payload["remitted_amount_cents"] = remitted_amount_cents
        return self._request("POST", f"/mtm/claims/{claim_id}/remit", payload, headers)

    def correct_claim(self, claim_id, headers):
        return self._request("POST", f"/mtm/claims/{claim_id}/correct", {}, headers)

    def void_claim(self, claim_id, headers):
        return self._request("POST", f"/mtm/claims/{claim_id}/void", {}, headers)


api_client = ApiClient()
