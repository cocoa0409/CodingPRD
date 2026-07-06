"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- DrugCatalog ---
    def create_drug(self, payload, headers):
        return self._request("POST", "/drug-catalog", payload, headers)

    def get_drug(self, drug_id, headers):
        return self._request("GET", f"/drug-catalog/{drug_id}", headers=headers)

    def list_drugs(self, headers, params=None):
        return self._request("GET", "/drug-catalog", headers=headers, params=params)

    # --- PayerPlan ---
    def create_payer_plan(self, payload, headers):
        return self._request("POST", "/payer-plans", payload, headers)

    def get_payer_plan(self, plan_id, headers):
        return self._request("GET", f"/payer-plans/{plan_id}", headers=headers)

    # --- Nurse ---
    def create_nurse(self, payload, headers):
        return self._request("POST", "/nurses", payload, headers)

    def get_nurse(self, nurse_id, headers):
        return self._request("GET", f"/nurses/{nurse_id}", headers=headers)

    # --- Pump ---
    def create_pump(self, payload, headers):
        return self._request("POST", "/pumps", payload, headers)

    def get_pump(self, pump_id, headers):
        return self._request("GET", f"/pumps/{pump_id}", headers=headers)

    # --- Patient ---
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    # --- Referral ---
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def accept_referral(self, referral_id, headers):
        return self._request(
            "POST", f"/referrals/{referral_id}/accept", {}, headers
        )

    def reject_referral(self, referral_id, headers):
        return self._request(
            "POST", f"/referrals/{referral_id}/reject", {}, headers
        )

    # --- InfusionOrder ---
    def create_order(self, payload, headers):
        return self._request("POST", "/infusion-orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/infusion-orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request(
            "GET", "/infusion-orders", headers=headers, params=params
        )

    def submit_order(self, order_id, headers):
        return self._request(
            "POST", f"/infusion-orders/{order_id}/submit", {}, headers
        )

    def discontinue_order(self, order_id, headers):
        return self._request(
            "POST", f"/infusion-orders/{order_id}/discontinue", {}, headers
        )

    def complete_order(self, order_id, headers):
        return self._request(
            "POST", f"/infusion-orders/{order_id}/complete", {}, headers
        )

    # --- PriorAuthorization ---
    def create_prior_auth(self, payload, headers):
        return self._request("POST", "/prior-authorizations", payload, headers)

    def get_prior_auth(self, auth_id, headers):
        return self._request(
            "GET", f"/prior-authorizations/{auth_id}", headers=headers
        )

    def list_prior_auths(self, headers, params=None):
        return self._request(
            "GET", "/prior-authorizations", headers=headers, params=params
        )

    def approve_prior_auth(self, auth_id, payload, headers):
        return self._request(
            "POST", f"/prior-authorizations/{auth_id}/approve", payload, headers
        )

    def deny_prior_auth(self, auth_id, headers):
        return self._request(
            "POST", f"/prior-authorizations/{auth_id}/deny", {}, headers
        )

    # --- Compound ---
    def create_compound(self, payload, headers):
        return self._request("POST", "/compounds", payload, headers)

    def get_compound(self, compound_id, headers):
        return self._request("GET", f"/compounds/{compound_id}", headers=headers)

    def list_compounds(self, headers, params=None):
        return self._request("GET", "/compounds", headers=headers, params=params)

    def compound_compound(self, compound_id, headers):
        return self._request(
            "POST", f"/compounds/{compound_id}/compound", {}, headers
        )

    def deliver_compound(self, compound_id, headers):
        return self._request(
            "POST", f"/compounds/{compound_id}/deliver", {}, headers
        )

    # --- SupplyKit ---
    def create_supply_kit(self, payload, headers):
        return self._request("POST", "/supply-kits", payload, headers)

    def get_supply_kit(self, kit_id, headers):
        return self._request("GET", f"/supply-kits/{kit_id}", headers=headers)

    def list_supply_kits(self, headers, params=None):
        return self._request("GET", "/supply-kits", headers=headers, params=params)

    def ship_supply_kit(self, kit_id, headers):
        return self._request(
            "POST", f"/supply-kits/{kit_id}/ship", {}, headers
        )

    # --- NursingVisit ---
    def create_visit(self, payload, headers):
        return self._request("POST", "/nursing-visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/nursing-visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request(
            "GET", "/nursing-visits", headers=headers, params=params
        )

    def complete_visit(self, visit_id, headers):
        return self._request(
            "POST", f"/nursing-visits/{visit_id}/complete", {}, headers
        )

    def miss_visit(self, visit_id, headers):
        return self._request(
            "POST", f"/nursing-visits/{visit_id}/miss", {}, headers
        )

    # --- LabResult ---
    def create_lab_result(self, payload, headers):
        return self._request("POST", "/lab-results", payload, headers)

    def get_lab_result(self, lab_id, headers):
        return self._request("GET", f"/lab-results/{lab_id}", headers=headers)

    def list_lab_results(self, headers, params=None):
        return self._request("GET", "/lab-results", headers=headers, params=params)

    # --- AdverseEvent ---
    def create_adverse_event(self, payload, headers):
        return self._request("POST", "/adverse-events", payload, headers)

    def get_adverse_event(self, event_id, headers):
        return self._request("GET", f"/adverse-events/{event_id}", headers=headers)

    def list_adverse_events(self, headers, params=None):
        return self._request(
            "GET", "/adverse-events", headers=headers, params=params
        )

    def adjudicate_adverse_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/adverse-events/{event_id}/adjudicate", payload, headers
        )

    # --- Claim ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def post_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/post", {}, headers)

    def void_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/void", {}, headers)


api_client = ApiClient()
