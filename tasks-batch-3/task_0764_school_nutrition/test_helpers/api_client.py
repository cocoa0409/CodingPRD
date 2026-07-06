"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- SchoolSite ----
    def create_site(self, payload, headers):
        return self._request("POST", "/nutrition/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/nutrition/sites/{site_id}", headers=headers)

    # ---- FoodItem ----
    def create_food_item(self, payload, headers):
        return self._request("POST", "/nutrition/food-items", payload, headers)

    def get_food_item(self, food_item_id, headers):
        return self._request("GET", f"/nutrition/food-items/{food_item_id}", headers=headers)

    # ---- ReimbursementRate ----
    def create_reimbursement_rate(self, payload, headers):
        return self._request("POST", "/nutrition/reimbursement-rates", payload, headers)

    # ---- MenuCycle ----
    def create_menu_cycle(self, payload, headers):
        return self._request("POST", "/nutrition/menu-cycles", payload, headers)

    def get_menu_cycle(self, cycle_id, headers):
        return self._request("GET", f"/nutrition/menu-cycles/{cycle_id}", headers=headers)

    def list_menu_cycles(self, headers, params=None):
        return self._request("GET", "/nutrition/menu-cycles", headers=headers, params=params)

    def submit_menu_cycle(self, cycle_id, headers, payload=None):
        return self._request("POST", f"/nutrition/menu-cycles/{cycle_id}/submit", payload or {}, headers)

    def approve_menu_cycle(self, cycle_id, headers, payload=None):
        return self._request("POST", f"/nutrition/menu-cycles/{cycle_id}/approve", payload or {}, headers)

    def reject_menu_cycle(self, cycle_id, headers, payload=None):
        return self._request("POST", f"/nutrition/menu-cycles/{cycle_id}/reject", payload or {}, headers)

    # ---- InventoryLot ----
    def create_inventory_lot(self, payload, headers):
        return self._request("POST", "/nutrition/inventory-lots", payload, headers)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/nutrition/inventory-lots/{lot_id}", headers=headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/nutrition/inventory-lots", headers=headers, params=params)

    # ---- ProductionRecord ----
    def create_production_record(self, payload, headers):
        return self._request("POST", "/nutrition/production-records", payload, headers)

    def get_production_record(self, record_id, headers):
        return self._request("GET", f"/nutrition/production-records/{record_id}", headers=headers)

    def list_production_records(self, headers, params=None):
        return self._request("GET", "/nutrition/production-records", headers=headers, params=params)

    def prepare_production_record(self, record_id, headers, payload=None):
        return self._request("POST", f"/nutrition/production-records/{record_id}/prepare", payload or {}, headers)

    def cancel_production_record(self, record_id, headers, payload=None):
        return self._request("POST", f"/nutrition/production-records/{record_id}/cancel", payload or {}, headers)

    # ---- Student ----
    def create_student(self, payload, headers):
        return self._request("POST", "/nutrition/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/nutrition/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/nutrition/students", headers=headers, params=params)

    def deposit_student(self, student_id, headers, payload):
        return self._request("POST", f"/nutrition/students/{student_id}/deposit", payload, headers)

    # ---- MealTransaction ----
    def create_meal_transaction(self, payload, headers):
        return self._request("POST", "/nutrition/meal-transactions", payload, headers)

    def get_meal_transaction(self, txn_id, headers):
        return self._request("GET", f"/nutrition/meal-transactions/{txn_id}", headers=headers)

    def list_meal_transactions(self, headers, params=None):
        return self._request("GET", "/nutrition/meal-transactions", headers=headers, params=params)

    def void_meal_transaction(self, txn_id, headers, payload=None):
        return self._request("POST", f"/nutrition/meal-transactions/{txn_id}/void", payload or {}, headers)

    # ---- ReimbursementClaim ----
    def create_reimbursement_claim(self, payload, headers):
        return self._request("POST", "/nutrition/reimbursement-claims", payload, headers)

    def get_reimbursement_claim(self, claim_id, headers):
        return self._request("GET", f"/nutrition/reimbursement-claims/{claim_id}", headers=headers)

    def list_reimbursement_claims(self, headers, params=None):
        return self._request("GET", "/nutrition/reimbursement-claims", headers=headers, params=params)

    def submit_claim(self, claim_id, headers, payload):
        return self._request("POST", f"/nutrition/reimbursement-claims/{claim_id}/submit", payload, headers)

    def recall_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/nutrition/reimbursement-claims/{claim_id}/recall", payload or {}, headers)

    def mark_paid_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/nutrition/reimbursement-claims/{claim_id}/mark-paid", payload or {}, headers)

    # ---- Logical clock (test driving) ----
    def set_clock(self, headers, to_iso8601):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
