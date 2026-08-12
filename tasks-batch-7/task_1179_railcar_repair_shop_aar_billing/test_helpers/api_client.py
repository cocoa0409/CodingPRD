"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Shop & configuration ---
    def create_shop(self, payload, headers):
        return self._request("POST", "/shops", payload, headers)

    def get_shop(self, shop_id, headers):
        return self._request("GET", f"/shops/{shop_id}", headers=headers)

    def sweep_shop(self, shop_id, headers):
        return self._request("POST", f"/shops/{shop_id}/sweep", {}, headers)

    def create_car_owner(self, payload, headers):
        return self._request("POST", "/car-owners", payload, headers)

    def list_car_owners(self, headers, params=None):
        return self._request("GET", "/car-owners", headers=headers, params=params)

    def get_car_owner(self, owner_id, headers):
        return self._request("GET", f"/car-owners/{owner_id}", headers=headers)

    def create_handling_line(self, payload, headers):
        return self._request("POST", "/handling-lines", payload, headers)

    def list_handling_lines(self, headers, params=None):
        return self._request("GET", "/handling-lines", headers=headers, params=params)

    def get_handling_line(self, line_id, headers):
        return self._request("GET", f"/handling-lines/{line_id}", headers=headers)

    # --- Price master ---
    def create_price_master_entry(self, payload, headers):
        return self._request("POST", "/price-master-entries", payload, headers)

    def list_price_master_entries(self, headers, params=None):
        return self._request("GET", "/price-master-entries", headers=headers, params=params)

    def get_price_master_entry(self, entry_id, headers):
        return self._request("GET", f"/price-master-entries/{entry_id}", headers=headers)

    # --- Parts ---
    def create_part(self, payload, headers):
        return self._request("POST", "/parts", payload, headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", "/parts", headers=headers, params=params)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/parts/{part_id}", headers=headers)

    def adjust_part(self, part_id, payload, headers):
        return self._request("POST", f"/parts/{part_id}/adjust", payload, headers)

    # --- Wheelsets ---
    def create_wheelset(self, payload, headers):
        return self._request("POST", "/wheelsets", payload, headers)

    def list_wheelsets(self, headers, params=None):
        return self._request("GET", "/wheelsets", headers=headers, params=params)

    def get_wheelset(self, wheelset_id, headers):
        return self._request("GET", f"/wheelsets/{wheelset_id}", headers=headers)

    def mount_wheelset(self, wheelset_id, payload, headers):
        return self._request("POST", f"/wheelsets/{wheelset_id}/mount", payload, headers)

    def remove_wheelset(self, wheelset_id, headers):
        return self._request("POST", f"/wheelsets/{wheelset_id}/remove", {}, headers)

    def evaluate_wheelset(self, wheelset_id, payload, headers):
        return self._request("POST", f"/wheelsets/{wheelset_id}/evaluate", payload, headers)

    # --- Shop slots ---
    def create_shop_slot(self, payload, headers):
        return self._request("POST", "/shop-slots", payload, headers)

    def list_shop_slots(self, headers, params=None):
        return self._request("GET", "/shop-slots", headers=headers, params=params)

    def get_shop_slot(self, slot_id, headers):
        return self._request("GET", f"/shop-slots/{slot_id}", headers=headers)

    def block_shop_slot(self, slot_id, headers):
        return self._request("POST", f"/shop-slots/{slot_id}/block", {}, headers)

    # --- Railcars ---
    def create_railcar(self, payload, headers):
        return self._request("POST", "/railcars", payload, headers)

    def list_railcars(self, headers, params=None):
        return self._request("GET", "/railcars", headers=headers, params=params)

    def get_railcar(self, railcar_id, headers):
        return self._request("GET", f"/railcars/{railcar_id}", headers=headers)

    def depart_railcar(self, railcar_id, headers):
        return self._request("POST", f"/railcars/{railcar_id}/depart", {}, headers)

    def get_dwell_summary(self, railcar_id, headers):
        return self._request("GET", f"/railcars/{railcar_id}/dwell-summary", headers=headers)

    # --- Inspections & defects ---
    def create_inspection(self, railcar_id, headers):
        return self._request("POST", f"/railcars/{railcar_id}/inspections", {}, headers)

    def list_inspections(self, railcar_id, headers):
        return self._request("GET", f"/railcars/{railcar_id}/inspections", headers=headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def create_defect(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/defects", payload, headers)

    def list_defects(self, inspection_id, headers, params=None):
        return self._request("GET", f"/inspections/{inspection_id}/defects", headers=headers, params=params)

    def decline_defect(self, inspection_id, defect_id, headers):
        return self._request("POST", f"/inspections/{inspection_id}/defects/{defect_id}/decline", {}, headers)

    def complete_inspection(self, inspection_id, headers):
        return self._request("POST", f"/inspections/{inspection_id}/complete", {}, headers)

    def reopen_inspection(self, inspection_id, headers):
        return self._request("POST", f"/inspections/{inspection_id}/reopen", {}, headers)

    # --- Work orders & repair lines ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def get_work_order(self, wo_id, headers):
        return self._request("GET", f"/work-orders/{wo_id}", headers=headers)

    def add_repair_line(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/lines", payload, headers)

    def list_repair_lines_of_work_order(self, wo_id, headers):
        return self._request("GET", f"/work-orders/{wo_id}/lines", headers=headers)

    def get_repair_line(self, line_id, headers):
        return self._request("GET", f"/repair-lines/{line_id}", headers=headers)

    def list_repair_lines(self, headers, params=None):
        return self._request("GET", "/repair-lines", headers=headers, params=params)

    def submit_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/submit", {}, headers)

    def authorize_work_order(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/authorize", payload, headers)

    def reject_work_order(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/reject", payload, headers)

    def revise_estimate(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/revise-estimate", payload, headers)

    def assign_slot(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/assign-slot", payload, headers)

    def dispatch_work_order(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/dispatch", payload, headers)

    def start_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/start", {}, headers)

    def complete_work_order(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/complete", payload, headers)

    def qa_review_work_order(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/qa-review", payload, headers)

    def cancel_work_order(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/cancel", payload, headers)

    # --- Billing repair cards ---
    def create_billing_repair_card(self, payload, headers):
        return self._request("POST", "/billing-repair-cards", payload, headers)

    def list_billing_repair_cards(self, headers, params=None):
        return self._request("GET", "/billing-repair-cards", headers=headers, params=params)

    def get_billing_repair_card(self, brc_id, headers):
        return self._request("GET", f"/billing-repair-cards/{brc_id}", headers=headers)

    def list_brc_lines_of_card(self, brc_id, headers):
        return self._request("GET", f"/billing-repair-cards/{brc_id}/lines", headers=headers)

    def get_brc_line(self, brc_line_id, headers):
        return self._request("GET", f"/brc-lines/{brc_line_id}", headers=headers)

    def list_brc_lines(self, headers, params=None):
        return self._request("GET", "/brc-lines", headers=headers, params=params)

    def submit_billing_repair_card(self, brc_id, headers):
        return self._request("POST", f"/billing-repair-cards/{brc_id}/submit", {}, headers)

    def accept_billing_repair_card(self, brc_id, headers):
        return self._request("POST", f"/billing-repair-cards/{brc_id}/accept", {}, headers)

    def withdraw_billing_repair_card(self, brc_id, headers):
        return self._request("POST", f"/billing-repair-cards/{brc_id}/withdraw", {}, headers)

    def settle_billing_repair_card(self, brc_id, headers):
        return self._request("POST", f"/billing-repair-cards/{brc_id}/settle", {}, headers)

    # --- Counter-bills ---
    def create_counter_bill(self, brc_id, payload, headers):
        return self._request("POST", f"/billing-repair-cards/{brc_id}/counter-bills", payload, headers)

    def list_counter_bills(self, brc_id, headers, params=None):
        return self._request("GET", f"/billing-repair-cards/{brc_id}/counter-bills", headers=headers, params=params)

    def get_counter_bill(self, cb_id, headers):
        return self._request("GET", f"/counter-bills/{cb_id}", headers=headers)

    def accept_counter_bill(self, cb_id, headers):
        return self._request("POST", f"/counter-bills/{cb_id}/accept", {}, headers)

    def rebut_counter_bill(self, cb_id, payload, headers):
        return self._request("POST", f"/counter-bills/{cb_id}/rebut", payload, headers)

    def revise_counter_bill(self, cb_id, payload, headers):
        return self._request("POST", f"/counter-bills/{cb_id}/revise", payload, headers)

    def withdraw_counter_bill(self, cb_id, headers):
        return self._request("POST", f"/counter-bills/{cb_id}/withdraw", {}, headers)

    # --- Warranty claims ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def validate_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/validate", {}, headers)

    def honor_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/honor", {}, headers)

    def deny_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/deny", payload, headers)

    def appeal_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/appeal", payload, headers)


api_client = ApiClient()
