"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Client ──────────────────────────────────────────────────────────
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    # ─── Contract ────────────────────────────────────────────────────────
    def create_contract(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/contracts", payload, headers)

    def list_client_contracts(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def propose_contract(self, client_id, contract_id, headers):
        return self._request("POST", f"/clients/{client_id}/contracts/{contract_id}/propose", headers=headers)

    def sign_contract(self, client_id, contract_id, headers):
        return self._request("POST", f"/clients/{client_id}/contracts/{contract_id}/sign", headers=headers)

    def activate_contract(self, client_id, contract_id, headers):
        return self._request("POST", f"/clients/{client_id}/contracts/{contract_id}/activate", headers=headers)

    def cancel_contract(self, client_id, contract_id, headers):
        return self._request("POST", f"/clients/{client_id}/contracts/{contract_id}/cancel", headers=headers)

    # ─── DesignProposal ──────────────────────────────────────────────────
    def create_design_proposal(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/design-proposals", payload, headers)

    def list_contract_proposals(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/design-proposals", headers=headers, params=params)

    def get_design_proposal(self, proposal_id, headers):
        return self._request("GET", f"/design-proposals/{proposal_id}", headers=headers)

    def create_line_item(self, proposal_id, payload, headers):
        return self._request("POST", f"/design-proposals/{proposal_id}/line-items", payload, headers)

    def list_line_items(self, proposal_id, headers, params=None):
        return self._request("GET", f"/design-proposals/{proposal_id}/line-items", headers=headers, params=params)

    def submit_proposal(self, proposal_id, headers):
        return self._request("POST", f"/design-proposals/{proposal_id}/submit", headers=headers)

    def accept_proposal(self, proposal_id, payload, headers):
        return self._request("POST", f"/design-proposals/{proposal_id}/accept", payload, headers)

    def reject_proposal(self, proposal_id, headers):
        return self._request("POST", f"/design-proposals/{proposal_id}/reject", headers=headers)

    # ─── InventoryItem ───────────────────────────────────────────────────
    def create_inventory_item(self, payload, headers):
        return self._request("POST", "/inventory-items", payload, headers)

    def get_inventory_item(self, item_id, headers):
        return self._request("GET", f"/inventory-items/{item_id}", headers=headers)

    def list_inventory_items(self, headers, params=None):
        return self._request("GET", "/inventory-items", headers=headers, params=params)

    def list_item_proposal_line_items(self, item_id, headers, params=None):
        return self._request("GET", f"/inventory-items/{item_id}/proposal-line-items", headers=headers, params=params)

    # ─── Crew ────────────────────────────────────────────────────────────
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    def list_crews(self, headers, params=None):
        return self._request("GET", "/crews", headers=headers, params=params)

    # ─── WorkOrder ───────────────────────────────────────────────────────
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, wo_id, headers):
        return self._request("GET", f"/work-orders/{wo_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def create_visit(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/visits", payload, headers)

    def list_visits(self, wo_id, headers, params=None):
        return self._request("GET", f"/work-orders/{wo_id}/visits", headers=headers, params=params)

    def schedule_work_order(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/schedule", payload, headers)

    def dispatch_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/dispatch", headers=headers)

    def complete_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/complete", headers=headers)

    def cancel_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/cancel", headers=headers)

    def invoice_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/invoice", headers=headers)

    def mark_paid_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/mark-paid", headers=headers)

    # ─── Visit ───────────────────────────────────────────────────────────
    def complete_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/complete", payload, headers)

    def skip_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/skip", headers=headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    # ─── StorageBay + StorageLot ─────────────────────────────────────────
    def create_storage_bay(self, payload, headers):
        return self._request("POST", "/storage-bays", payload, headers)

    def get_storage_bay(self, bay_id, headers):
        return self._request("GET", f"/storage-bays/{bay_id}", headers=headers)

    def create_storage_lot(self, payload, headers):
        return self._request("POST", "/storage-lots", payload, headers)

    def get_storage_lot(self, lot_id, headers):
        return self._request("GET", f"/storage-lots/{lot_id}", headers=headers)

    def list_storage_lots(self, headers, params=None):
        return self._request("GET", "/storage-lots", headers=headers, params=params)

    def check_in_storage_lot(self, lot_id, headers):
        return self._request("POST", f"/storage-lots/{lot_id}/check-in", headers=headers)

    def release_storage_lot(self, lot_id, headers):
        return self._request("POST", f"/storage-lots/{lot_id}/release", headers=headers)

    # ─── DamageReport ────────────────────────────────────────────────────
    def create_damage_report(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/damage-reports", payload, headers)

    def list_work_order_damage_reports(self, wo_id, headers, params=None):
        return self._request("GET", f"/work-orders/{wo_id}/damage-reports", headers=headers, params=params)

    def get_damage_report(self, dr_id, headers):
        return self._request("GET", f"/damage-reports/{dr_id}", headers=headers)

    def list_damage_reports(self, headers, params=None):
        return self._request("GET", "/damage-reports", headers=headers, params=params)

    def assess_damage_report(self, dr_id, payload, headers):
        return self._request("POST", f"/damage-reports/{dr_id}/assess", payload, headers)

    def settle_damage_report(self, dr_id, headers):
        return self._request("POST", f"/damage-reports/{dr_id}/settle", headers=headers)

    def void_damage_report(self, dr_id, headers):
        return self._request("POST", f"/damage-reports/{dr_id}/void", headers=headers)

    # ─── RestockOrder ────────────────────────────────────────────────────
    def get_restock_order(self, ro_id, headers):
        return self._request("GET", f"/restock-orders/{ro_id}", headers=headers)

    def list_restock_orders(self, headers, params=None):
        return self._request("GET", "/restock-orders", headers=headers, params=params)

    def fulfill_restock_order(self, ro_id, headers):
        return self._request("POST", f"/restock-orders/{ro_id}/fulfill", headers=headers)

    # ─── RenewalOffer ────────────────────────────────────────────────────
    def create_renewal_offer(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/renewal-offers", payload, headers)

    def list_contract_renewal_offers(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/renewal-offers", headers=headers, params=params)

    def get_renewal_offer(self, offer_id, headers):
        return self._request("GET", f"/renewal-offers/{offer_id}", headers=headers)

    def send_renewal_offer(self, offer_id, headers):
        return self._request("POST", f"/renewal-offers/{offer_id}/send", headers=headers)

    def accept_renewal_offer(self, offer_id, headers):
        return self._request("POST", f"/renewal-offers/{offer_id}/accept", headers=headers)

    def decline_renewal_offer(self, offer_id, headers):
        return self._request("POST", f"/renewal-offers/{offer_id}/decline", headers=headers)

    def expire_renewal_offer(self, offer_id, headers):
        return self._request("POST", f"/renewal-offers/{offer_id}/expire", headers=headers)

    # ─── Logical clock ───────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
