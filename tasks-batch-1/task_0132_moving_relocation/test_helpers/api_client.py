"""API client: one method per endpoint defined in the Moving & Relocation PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Customer ─────────────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ─── MoveJob ──────────────────────────────────────────────────────────────
    def create_move_job(self, payload, headers):
        return self._request("POST", "/move-jobs", payload, headers)

    def get_move_job(self, job_id, headers):
        return self._request("GET", f"/move-jobs/{job_id}", headers=headers)

    def list_move_jobs(self, headers, params=None):
        return self._request("GET", "/move-jobs", headers=headers, params=params)

    def create_payment(self, job_id, payload, headers):
        return self._request("POST", f"/move-jobs/{job_id}/payments", payload, headers)

    def close_move_job(self, job_id, headers):
        return self._request("POST", f"/move-jobs/{job_id}/close", {}, headers)

    def cancel_move_job(self, job_id, headers):
        return self._request("POST", f"/move-jobs/{job_id}/cancel", {}, headers)

    # ─── InventorySurvey + SurveyItem ─────────────────────────────────────────
    def create_survey(self, payload, headers):
        return self._request("POST", "/surveys", payload, headers)

    def get_survey(self, survey_id, headers):
        return self._request("GET", f"/surveys/{survey_id}", headers=headers)

    def list_surveys(self, headers, params=None):
        return self._request("GET", "/surveys", headers=headers, params=params)

    def add_survey_item(self, survey_id, payload, headers):
        return self._request("POST", f"/surveys/{survey_id}/items", payload, headers)

    def list_survey_items(self, survey_id, headers, params=None):
        return self._request("GET", f"/surveys/{survey_id}/items", headers=headers, params=params)

    # ─── PackingOrder ─────────────────────────────────────────────────────────
    def create_packing_order(self, payload, headers):
        return self._request("POST", "/packing-orders", payload, headers)

    def get_packing_order(self, order_id, headers):
        return self._request("GET", f"/packing-orders/{order_id}", headers=headers)

    def list_packing_orders(self, headers, params=None):
        return self._request("GET", "/packing-orders", headers=headers, params=params)

    def update_packing_order(self, order_id, payload, headers):
        return self._request("PATCH", f"/packing-orders/{order_id}", payload, headers)

    # ─── Estimate ─────────────────────────────────────────────────────────────
    def create_estimate(self, payload, headers):
        return self._request("POST", "/estimates", payload, headers)

    def get_estimate(self, estimate_id, headers):
        return self._request("GET", f"/estimates/{estimate_id}", headers=headers)

    def list_estimates(self, headers, params=None):
        return self._request("GET", "/estimates", headers=headers, params=params)

    def revise_estimate(self, estimate_id, payload, headers):
        return self._request("POST", f"/estimates/{estimate_id}/revise", payload, headers)

    def accept_estimate(self, estimate_id, headers):
        return self._request("POST", f"/estimates/{estimate_id}/accept", {}, headers)

    # ─── Truck / Crew ─────────────────────────────────────────────────────────
    def create_truck(self, payload, headers):
        return self._request("POST", "/trucks", payload, headers)

    def get_truck(self, truck_id, headers):
        return self._request("GET", f"/trucks/{truck_id}", headers=headers)

    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    # ─── Dispatch ─────────────────────────────────────────────────────────────
    def create_dispatch(self, payload, headers):
        return self._request("POST", "/dispatches", payload, headers)

    def get_dispatch(self, dispatch_id, headers):
        return self._request("GET", f"/dispatches/{dispatch_id}", headers=headers)

    def list_dispatches(self, headers, params=None):
        return self._request("GET", "/dispatches", headers=headers, params=params)

    def depart_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/dispatches/{dispatch_id}/depart", {}, headers)

    def complete_dispatch(self, dispatch_id, payload, headers):
        return self._request("POST", f"/dispatches/{dispatch_id}/complete", payload, headers)

    def cancel_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/dispatches/{dispatch_id}/cancel", {}, headers)

    # ─── StorageLot ───────────────────────────────────────────────────────────
    def create_storage_lot(self, payload, headers):
        return self._request("POST", "/storage-lots", payload, headers)

    def get_storage_lot(self, lot_id, headers):
        return self._request("GET", f"/storage-lots/{lot_id}", headers=headers)

    def list_storage_lots(self, headers, params=None):
        return self._request("GET", "/storage-lots", headers=headers, params=params)

    def release_storage_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/storage-lots/{lot_id}/release", payload, headers)

    def waive_storage_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/storage-lots/{lot_id}/waive", payload, headers)

    # ─── DamageClaim + ClaimItem ──────────────────────────────────────────────
    def create_damage_claim(self, payload, headers):
        return self._request("POST", "/damage-claims", payload, headers)

    def get_damage_claim(self, claim_id, headers):
        return self._request("GET", f"/damage-claims/{claim_id}", headers=headers)

    def list_damage_claims(self, headers, params=None):
        return self._request("GET", "/damage-claims", headers=headers, params=params)

    def add_claim_item(self, claim_id, payload, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/items", payload, headers)

    def list_claim_items(self, claim_id, headers, params=None):
        return self._request("GET", f"/damage-claims/{claim_id}/items", headers=headers, params=params)

    def approve_damage_claim(self, claim_id, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/approve", {}, headers)

    def deny_damage_claim(self, claim_id, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/deny", {}, headers)

    def reopen_damage_claim(self, claim_id, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/reopen", {}, headers)


api_client = ApiClient()
