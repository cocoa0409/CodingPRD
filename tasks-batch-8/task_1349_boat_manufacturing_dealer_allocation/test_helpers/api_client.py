"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Catalog: boat models ---
    def create_boat_model(self, payload, headers):
        return self._request("POST", "/boat-models", payload, headers)

    def list_boat_models(self, headers, params=None):
        return self._request("GET", "/boat-models", headers=headers, params=params)

    def get_boat_model(self, model_id, headers):
        return self._request("GET", f"/boat-models/{model_id}", headers=headers)

    # --- Catalog: option packages ---
    def create_option_package(self, payload, headers):
        return self._request("POST", "/option-packages", payload, headers)

    def list_option_packages(self, headers, params=None):
        return self._request("GET", "/option-packages", headers=headers, params=params)

    def get_option_package(self, option_id, headers):
        return self._request("GET", f"/option-packages/{option_id}", headers=headers)

    # --- Dealers ---
    def create_dealer(self, payload, headers):
        return self._request("POST", "/dealers", payload, headers)

    def list_dealers(self, headers, params=None):
        return self._request("GET", "/dealers", headers=headers, params=params)

    def get_dealer(self, dealer_id, headers):
        return self._request("GET", f"/dealers/{dealer_id}", headers=headers)

    def update_dealer(self, dealer_id, payload, headers):
        return self._request("PATCH", f"/dealers/{dealer_id}", payload, headers)

    def post_curtailment(self, dealer_id, payload, headers):
        return self._request("POST", f"/dealers/{dealer_id}/curtailments", payload, headers)

    # --- Boat show events ---
    def create_boat_show_event(self, payload, headers):
        return self._request("POST", "/boat-show-events", payload, headers)

    def list_boat_show_events(self, headers, params=None):
        return self._request("GET", "/boat-show-events", headers=headers, params=params)

    # --- Production runs ---
    def create_production_run(self, payload, headers):
        return self._request("POST", "/production-runs", payload, headers)

    def list_production_runs(self, headers, params=None):
        return self._request("GET", "/production-runs", headers=headers, params=params)

    def get_production_run(self, run_id, headers):
        return self._request("GET", f"/production-runs/{run_id}", headers=headers)

    def close_production_run(self, run_id, headers):
        return self._request("POST", f"/production-runs/{run_id}/close", {}, headers)

    # --- Build slots ---
    def create_build_slot(self, payload, headers):
        return self._request("POST", "/build-slots", payload, headers)

    def list_build_slots(self, headers, params=None):
        return self._request("GET", "/build-slots", headers=headers, params=params)

    def get_build_slot(self, slot_id, headers):
        return self._request("GET", f"/build-slots/{slot_id}", headers=headers)

    # --- Dealer orders ---
    def create_dealer_order(self, payload, headers):
        return self._request("POST", "/dealer-orders", payload, headers)

    def list_dealer_orders(self, headers, params=None):
        return self._request("GET", "/dealer-orders", headers=headers, params=params)

    def get_dealer_order(self, order_id, headers):
        return self._request("GET", f"/dealer-orders/{order_id}", headers=headers)

    def amend_dealer_order(self, order_id, payload, headers):
        return self._request("PATCH", f"/dealer-orders/{order_id}", payload, headers)

    def confirm_dealer_order(self, order_id, headers):
        return self._request("POST", f"/dealer-orders/{order_id}/confirm", {}, headers)

    def cancel_dealer_order(self, order_id, headers):
        return self._request("POST", f"/dealer-orders/{order_id}/cancel", {}, headers)

    # --- Order option lines ---
    def list_order_option_lines(self, headers, params=None):
        return self._request("GET", "/order-option-lines", headers=headers, params=params)

    def get_order_option_line(self, line_id, headers):
        return self._request("GET", f"/order-option-lines/{line_id}", headers=headers)

    # --- Hulls ---
    def create_hull(self, payload, headers):
        return self._request("POST", "/hulls", payload, headers)

    def list_hulls(self, headers, params=None):
        return self._request("GET", "/hulls", headers=headers, params=params)

    def get_hull(self, hull_id, headers):
        return self._request("GET", f"/hulls/{hull_id}", headers=headers)

    def certify_hull(self, hull_id, headers):
        return self._request("POST", f"/hulls/{hull_id}/certify", {}, headers)

    def deliver_hull(self, hull_id, headers):
        return self._request("POST", f"/hulls/{hull_id}/deliver", {}, headers)

    # --- Floor plan advances ---
    def list_floor_plan_advances(self, headers, params=None):
        return self._request("GET", "/floor-plan-advances", headers=headers, params=params)

    def get_floor_plan_advance(self, advance_id, headers):
        return self._request("GET", f"/floor-plan-advances/{advance_id}", headers=headers)

    # --- Warranty registrations ---
    def create_warranty_registration(self, payload, headers):
        return self._request("POST", "/warranty-registrations", payload, headers)

    def list_warranty_registrations(self, headers, params=None):
        return self._request("GET", "/warranty-registrations", headers=headers, params=params)

    def get_warranty_registration(self, registration_id, headers):
        return self._request("GET", f"/warranty-registrations/{registration_id}", headers=headers)

    # --- Warranty claims ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def approve_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/approve", {}, headers)

    def reject_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/reject", {}, headers)

    # --- Recall campaigns ---
    def create_recall_campaign(self, payload, headers):
        return self._request("POST", "/recall-campaigns", payload, headers)

    def list_recall_campaigns(self, headers, params=None):
        return self._request("GET", "/recall-campaigns", headers=headers, params=params)

    def issue_recall_campaign(self, campaign_id, headers):
        return self._request("POST", f"/recall-campaigns/{campaign_id}/issue", {}, headers)

    # --- Recall notices ---
    def list_recall_notices(self, headers, params=None):
        return self._request("GET", "/recall-notices", headers=headers, params=params)

    def get_recall_notice(self, notice_id, headers):
        return self._request("GET", f"/recall-notices/{notice_id}", headers=headers)

    def remedy_recall_notice(self, notice_id, headers):
        return self._request("POST", f"/recall-notices/{notice_id}/remedy", {}, headers)

    # --- Logical clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
