"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --------------------------------------------------------------- Customer
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def suspend_customer(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/suspend", payload, headers)

    # ---------------------------------------------------------- InventoryItem
    def create_inventory_item(self, payload, headers):
        return self._request("POST", "/inventory-items", payload, headers)

    def list_inventory_items(self, headers, params=None):
        return self._request("GET", "/inventory-items", headers=headers, params=params)

    def get_inventory_item(self, item_id, headers):
        return self._request("GET", f"/inventory-items/{item_id}", headers=headers)

    # --------------------------------------------------------------- Workbench
    def create_workbench(self, payload, headers):
        return self._request("POST", "/workbenches", payload, headers)

    def list_workbenches(self, headers, params=None):
        return self._request("GET", "/workbenches", headers=headers, params=params)

    def get_workbench(self, bench_id, headers):
        return self._request("GET", f"/workbenches/{bench_id}", headers=headers)

    # --------------------------------------------------------------- Appraisal
    def create_appraisal(self, payload, headers):
        return self._request("POST", "/appraisals", payload, headers)

    def list_appraisals(self, headers, params=None):
        return self._request("GET", "/appraisals", headers=headers, params=params)

    def get_appraisal(self, appraisal_id, headers):
        return self._request("GET", f"/appraisals/{appraisal_id}", headers=headers)

    def finalize_appraisal(self, appraisal_id, payload, headers):
        return self._request("POST", f"/appraisals/{appraisal_id}/finalize", payload, headers)

    def void_appraisal(self, appraisal_id, payload, headers):
        return self._request("POST", f"/appraisals/{appraisal_id}/void", payload, headers)

    # -------------------------------------------------------- CustomDesignOrder
    def create_custom_order(self, payload, headers):
        return self._request("POST", "/custom-orders", payload, headers)

    def list_custom_orders(self, headers, params=None):
        return self._request("GET", "/custom-orders", headers=headers, params=params)

    def get_custom_order(self, order_id, headers):
        return self._request("GET", f"/custom-orders/{order_id}", headers=headers)

    def quote_custom_order(self, order_id, payload, headers):
        return self._request("POST", f"/custom-orders/{order_id}/quote", payload, headers)

    def start_design_custom_order(self, order_id, payload, headers):
        return self._request("POST", f"/custom-orders/{order_id}/start-design", payload, headers)

    def submit_review_custom_order(self, order_id, payload, headers):
        return self._request("POST", f"/custom-orders/{order_id}/submit-review", payload, headers)

    def request_revision_custom_order(self, order_id, payload, headers):
        return self._request("POST", f"/custom-orders/{order_id}/request-revision", payload, headers)

    def approve_design_custom_order(self, order_id, payload, headers):
        return self._request("POST", f"/custom-orders/{order_id}/approve-design", payload, headers)

    def start_production_custom_order(self, order_id, payload, headers):
        return self._request("POST", f"/custom-orders/{order_id}/start-production", payload, headers)

    def complete_production_custom_order(self, order_id, payload, headers):
        return self._request("POST", f"/custom-orders/{order_id}/complete-production", payload, headers)

    def complete_custom_order(self, order_id, payload, headers):
        return self._request("POST", f"/custom-orders/{order_id}/complete", payload, headers)

    def cancel_custom_order(self, order_id, payload, headers):
        return self._request("POST", f"/custom-orders/{order_id}/cancel", payload, headers)

    # ------------------------------------------------------------- RepairTicket
    def create_repair_ticket(self, payload, headers):
        return self._request("POST", "/repair-tickets", payload, headers)

    def list_repair_tickets(self, headers, params=None):
        return self._request("GET", "/repair-tickets", headers=headers, params=params)

    def get_repair_ticket(self, ticket_id, headers):
        return self._request("GET", f"/repair-tickets/{ticket_id}", headers=headers)

    def schedule_repair_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/schedule", payload, headers)

    def assess_repair_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/assess", payload, headers)

    def order_parts_repair_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/order-parts", payload, headers)

    def parts_received_repair_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/parts-received", payload, headers)

    def start_repair_repair_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/start-repair", payload, headers)

    def submit_qc_repair_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/submit-qc", payload, headers)

    def pass_qc_repair_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/pass-qc", payload, headers)

    def fail_qc_repair_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/fail-qc", payload, headers)

    def pickup_repair_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/pickup", payload, headers)

    def cancel_repair_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/cancel", payload, headers)

    # -------------------------------------------------------------- LayawayPlan
    def create_layaway_plan(self, payload, headers):
        return self._request("POST", "/layaway-plans", payload, headers)

    def list_layaway_plans(self, headers, params=None):
        return self._request("GET", "/layaway-plans", headers=headers, params=params)

    def get_layaway_plan(self, plan_id, headers):
        return self._request("GET", f"/layaway-plans/{plan_id}", headers=headers)

    def activate_layaway_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/layaway-plans/{plan_id}/activate", payload, headers)

    def fulfill_layaway_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/layaway-plans/{plan_id}/fulfill", payload, headers)

    def cancel_layaway_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/layaway-plans/{plan_id}/cancel", payload, headers)

    # -------------------------------------------------------------- TradeInOffer
    def create_trade_in(self, payload, headers):
        return self._request("POST", "/trade-ins", payload, headers)

    def list_trade_ins(self, headers, params=None):
        return self._request("GET", "/trade-ins", headers=headers, params=params)

    def get_trade_in(self, offer_id, headers):
        return self._request("GET", f"/trade-ins/{offer_id}", headers=headers)

    def accept_trade_in(self, offer_id, payload, headers):
        return self._request("POST", f"/trade-ins/{offer_id}/accept", payload, headers)

    def decline_trade_in(self, offer_id, payload, headers):
        return self._request("POST", f"/trade-ins/{offer_id}/decline", payload, headers)

    # -------------------------------------------------------------- SpecialOrder
    def create_special_order(self, payload, headers):
        return self._request("POST", "/special-orders", payload, headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/special-orders", headers=headers, params=params)

    def get_special_order(self, order_id, headers):
        return self._request("GET", f"/special-orders/{order_id}", headers=headers)

    def place_special_order(self, order_id, payload, headers):
        return self._request("POST", f"/special-orders/{order_id}/place", payload, headers)

    def receive_special_order(self, order_id, payload, headers):
        return self._request("POST", f"/special-orders/{order_id}/receive", payload, headers)

    def deliver_special_order(self, order_id, payload, headers):
        return self._request("POST", f"/special-orders/{order_id}/deliver", payload, headers)

    def cancel_special_order(self, order_id, payload, headers):
        return self._request("POST", f"/special-orders/{order_id}/cancel", payload, headers)

    # ------------------------------------------------------------------ Payment
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    # ------------------------------------------------------------- WarrantyClaim
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def approve_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/approve", payload, headers)

    def reject_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/reject", payload, headers)

    # --------------------------------------------------------- CreditLedgerEntry
    def create_ledger_entry(self, payload, headers):
        return self._request("POST", "/credit-ledger", payload, headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/credit-ledger", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/credit-ledger/{entry_id}", headers=headers)


api_client = ApiClient()
