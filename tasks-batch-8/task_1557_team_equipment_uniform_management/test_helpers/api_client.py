"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Players
    # ------------------------------------------------------------------
    def create_player(self, payload, headers):
        return self._request("POST", "/players", payload, headers)

    def get_player(self, player_id, headers):
        return self._request("GET", f"/players/{player_id}", headers=headers)

    def patch_player(self, player_id, payload, headers):
        return self._request("PATCH", f"/players/{player_id}", payload, headers)

    # ------------------------------------------------------------------
    # Inventory pools
    # ------------------------------------------------------------------
    def create_inventory_pool(self, payload, headers):
        return self._request("POST", "/inventory-pools", payload, headers)

    def get_inventory_pool(self, pool_id, headers):
        return self._request("GET", f"/inventory-pools/{pool_id}", headers=headers)

    def list_inventory_pools(self, headers, params=None):
        return self._request("GET", "/inventory-pools", headers=headers, params=params)

    def create_stock_adjustment(self, pool_id, payload, headers):
        return self._request("POST", f"/inventory-pools/{pool_id}/stock-adjustments",
                             payload, headers)

    # ------------------------------------------------------------------
    # Supplier contracts
    # ------------------------------------------------------------------
    def create_supplier_contract(self, payload, headers):
        return self._request("POST", "/supplier-contracts", payload, headers)

    def get_supplier_contract(self, contract_id, headers):
        return self._request("GET", f"/supplier-contracts/{contract_id}", headers=headers)

    def activate_supplier_contract(self, contract_id, headers):
        return self._request("POST", f"/supplier-contracts/{contract_id}/activate",
                             {}, headers)

    def amend_supplier_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/supplier-contracts/{contract_id}/amendments",
                             payload, headers)

    def close_supplier_contract(self, contract_id, headers):
        return self._request("POST", f"/supplier-contracts/{contract_id}/close",
                             {}, headers)

    # ------------------------------------------------------------------
    # Kit orders
    # ------------------------------------------------------------------
    def create_kit_order(self, payload, headers):
        return self._request("POST", "/kit-orders", payload, headers)

    def get_kit_order(self, order_id, headers):
        return self._request("GET", f"/kit-orders/{order_id}", headers=headers)

    def list_kit_orders(self, headers, params=None):
        return self._request("GET", "/kit-orders", headers=headers, params=params)

    def receive_kit_order(self, order_id, payload, headers):
        return self._request("POST", f"/kit-orders/{order_id}/receive", payload, headers)

    def cancel_kit_order(self, order_id, headers):
        return self._request("POST", f"/kit-orders/{order_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Kit assignments
    # ------------------------------------------------------------------
    def create_kit_assignment(self, payload, headers):
        return self._request("POST", "/kit-assignments", payload, headers)

    def get_kit_assignment(self, assignment_id, headers):
        return self._request("GET", f"/kit-assignments/{assignment_id}", headers=headers)

    def list_kit_assignments(self, headers, params=None):
        return self._request("GET", "/kit-assignments", headers=headers, params=params)

    def issue_kit_assignment(self, assignment_id, headers):
        return self._request("POST", f"/kit-assignments/{assignment_id}/issue", {}, headers)

    def release_kit_assignment(self, assignment_id, headers):
        return self._request("POST", f"/kit-assignments/{assignment_id}/release", {}, headers)

    def return_kit_assignment(self, assignment_id, headers):
        return self._request("POST", f"/kit-assignments/{assignment_id}/return", {}, headers)

    # ------------------------------------------------------------------
    # Gear items
    # ------------------------------------------------------------------
    def create_gear_item(self, payload, headers):
        return self._request("POST", "/gear-items", payload, headers)

    def get_gear_item(self, item_id, headers):
        return self._request("GET", f"/gear-items/{item_id}", headers=headers)

    def list_gear_items(self, headers, params=None):
        return self._request("GET", "/gear-items", headers=headers, params=params)

    def issue_gear_item(self, item_id, payload, headers):
        return self._request("POST", f"/gear-items/{item_id}/issue", payload, headers)

    def return_gear_item(self, item_id, headers):
        return self._request("POST", f"/gear-items/{item_id}/return", {}, headers)

    def retire_gear_item(self, item_id, headers):
        return self._request("POST", f"/gear-items/{item_id}/retire", {}, headers)

    # ------------------------------------------------------------------
    # Reconditioning jobs
    # ------------------------------------------------------------------
    def create_reconditioning_job(self, payload, headers):
        return self._request("POST", "/reconditioning-jobs", payload, headers)

    def get_reconditioning_job(self, job_id, headers):
        return self._request("GET", f"/reconditioning-jobs/{job_id}", headers=headers)

    def list_reconditioning_jobs(self, headers, params=None):
        return self._request("GET", "/reconditioning-jobs", headers=headers, params=params)

    def record_reconditioning_result(self, job_id, payload, headers):
        return self._request("POST", f"/reconditioning-jobs/{job_id}/record-result",
                             payload, headers)

    # ------------------------------------------------------------------
    # Game events
    # ------------------------------------------------------------------
    def create_game_event(self, payload, headers):
        return self._request("POST", "/game-events", payload, headers)

    def get_game_event(self, event_id, headers):
        return self._request("GET", f"/game-events/{event_id}", headers=headers)

    def lock_game_event_kit(self, event_id, headers):
        return self._request("POST", f"/game-events/{event_id}/lock-kit", {}, headers)

    def complete_game_event(self, event_id, payload, headers):
        return self._request("POST", f"/game-events/{event_id}/complete", payload, headers)

    def cancel_game_event(self, event_id, headers):
        return self._request("POST", f"/game-events/{event_id}/cancel", {}, headers)

    def advance_laundry(self, event_id, headers):
        return self._request("POST", f"/game-events/{event_id}/laundry-advance", {}, headers)

    def complete_checklist_item(self, event_id, item_ref, payload, headers):
        return self._request(
            "POST", f"/game-events/{event_id}/checklist/{item_ref}/complete",
            payload, headers)

    # ------------------------------------------------------------------
    # Damage claims
    # ------------------------------------------------------------------
    def create_damage_claim(self, payload, headers):
        return self._request("POST", "/damage-claims", payload, headers)

    def get_damage_claim(self, claim_id, headers):
        return self._request("GET", f"/damage-claims/{claim_id}", headers=headers)

    def list_damage_claims(self, headers, params=None):
        return self._request("GET", "/damage-claims", headers=headers, params=params)

    def assess_damage_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/assess", payload, headers)

    def settle_damage_claim(self, claim_id, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/settle", {}, headers)

    def waive_damage_claim(self, claim_id, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/waive", {}, headers)

    def reopen_damage_claim(self, claim_id, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/reopen", {}, headers)

    # ------------------------------------------------------------------
    # Disposition cases
    # ------------------------------------------------------------------
    def create_disposition_case(self, payload, headers):
        return self._request("POST", "/disposition-cases", payload, headers)

    def get_disposition_case(self, case_id, headers):
        return self._request("GET", f"/disposition-cases/{case_id}", headers=headers)

    def approve_disposition_case(self, case_id, headers):
        return self._request("POST", f"/disposition-cases/{case_id}/approve", {}, headers)

    def reject_disposition_case(self, case_id, headers):
        return self._request("POST", f"/disposition-cases/{case_id}/reject", {}, headers)

    def execute_disposition_case(self, case_id, headers):
        return self._request("POST", f"/disposition-cases/{case_id}/execute", {}, headers)


api_client = ApiClient()
