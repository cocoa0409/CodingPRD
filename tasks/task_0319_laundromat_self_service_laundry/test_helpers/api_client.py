"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Pricing plans -----------------------------------------------------
    def create_pricing_plan(self, payload, headers):
        return self._request("POST", "/pricing-plans", payload, headers)

    def list_pricing_plans(self, headers, params=None):
        return self._request("GET", "/pricing-plans", headers=headers, params=params)

    def get_pricing_plan(self, plan_id, headers):
        return self._request("GET", f"/pricing-plans/{plan_id}", headers=headers)

    def activate_pricing_plan(self, plan_id, headers):
        return self._request("POST", f"/pricing-plans/{plan_id}/activate", {}, headers)

    def retire_pricing_plan(self, plan_id, headers):
        return self._request("POST", f"/pricing-plans/{plan_id}/retire", {}, headers)

    # ---- Machines ----------------------------------------------------------
    def create_machine(self, payload, headers):
        return self._request("POST", "/machines", payload, headers)

    def list_machines(self, headers, params=None):
        return self._request("GET", "/machines", headers=headers, params=params)

    def get_machine(self, machine_id, headers):
        return self._request("GET", f"/machines/{machine_id}", headers=headers)

    def list_machine_vends(self, machine_id, headers, params=None):
        return self._request("GET", f"/machines/{machine_id}/vends", headers=headers, params=params)

    def create_vend(self, machine_id, payload, headers):
        return self._request("POST", f"/machines/{machine_id}/vends", payload, headers)

    def complete_cycle(self, machine_id, headers):
        return self._request("POST", f"/machines/{machine_id}/complete-cycle", {}, headers)

    def clear_machine(self, machine_id, headers):
        return self._request("POST", f"/machines/{machine_id}/clear", {}, headers)

    def declare_fault(self, machine_id, headers):
        return self._request("POST", f"/machines/{machine_id}/declare-fault", {}, headers)

    def take_offline(self, machine_id, headers):
        return self._request("POST", f"/machines/{machine_id}/take-offline", {}, headers)

    def return_to_service(self, machine_id, headers):
        return self._request("POST", f"/machines/{machine_id}/return-to-service", {}, headers)

    # ---- Vends (top-level reads) -------------------------------------------
    def list_vends(self, headers, params=None):
        return self._request("GET", "/vends", headers=headers, params=params)

    def get_vend(self, vend_id, headers):
        return self._request("GET", f"/vends/{vend_id}", headers=headers)

    # ---- Members -----------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def update_member(self, member_id, payload, headers):
        return self._request("PATCH", f"/members/{member_id}", payload, headers)

    def create_reload(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/reloads", payload, headers)

    def list_member_reloads(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/reloads", headers=headers, params=params)

    def list_member_vends(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/vends", headers=headers, params=params)

    def list_member_loyalty_ledger(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/loyalty-ledger", headers=headers, params=params)

    def redeem(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/redeem", {}, headers)

    # ---- Reloads (top-level reads) -----------------------------------------
    def list_reloads(self, headers, params=None):
        return self._request("GET", "/reloads", headers=headers, params=params)

    def get_reload(self, reload_id, headers):
        return self._request("GET", f"/reloads/{reload_id}", headers=headers)

    # ---- Loyalty ledger (top-level reads) ----------------------------------
    def list_loyalty_ledger(self, headers, params=None):
        return self._request("GET", "/loyalty-ledger", headers=headers, params=params)

    def get_loyalty_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/loyalty-ledger/{entry_id}", headers=headers)

    # ---- Shifts ------------------------------------------------------------
    def create_shift(self, payload, headers):
        return self._request("POST", "/shifts", payload, headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/shifts", headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}", headers=headers)

    def begin_reconcile(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/begin-reconcile", {}, headers)

    def close_shift(self, shift_id, payload, headers):
        return self._request("POST", f"/shifts/{shift_id}/close", payload, headers)

    # ---- WDF orders --------------------------------------------------------
    def create_wdf_order(self, payload, headers):
        return self._request("POST", "/wdf-orders", payload, headers)

    def list_wdf_orders(self, headers, params=None):
        return self._request("GET", "/wdf-orders", headers=headers, params=params)

    def get_wdf_order(self, order_id, headers):
        return self._request("GET", f"/wdf-orders/{order_id}", headers=headers)

    def start_wdf_order(self, order_id, headers):
        return self._request("POST", f"/wdf-orders/{order_id}/start", {}, headers)

    def ready_wdf_order(self, order_id, headers):
        return self._request("POST", f"/wdf-orders/{order_id}/ready", {}, headers)

    def pay_wdf_order(self, order_id, payload, headers):
        return self._request("POST", f"/wdf-orders/{order_id}/pay", payload, headers)

    def cancel_wdf_order(self, order_id, headers):
        return self._request("POST", f"/wdf-orders/{order_id}/cancel", {}, headers)

    # ---- Refund claims -----------------------------------------------------
    def create_refund_claim(self, payload, headers):
        return self._request("POST", "/refund-claims", payload, headers)

    def list_refund_claims(self, headers, params=None):
        return self._request("GET", "/refund-claims", headers=headers, params=params)

    def get_refund_claim(self, claim_id, headers):
        return self._request("GET", f"/refund-claims/{claim_id}", headers=headers)

    def approve_refund_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/refund-claims/{claim_id}/approve", payload, headers)

    def deny_refund_claim(self, claim_id, headers):
        return self._request("POST", f"/refund-claims/{claim_id}/deny", {}, headers)

    # ---- Lost & found ------------------------------------------------------
    def create_lost_found(self, payload, headers):
        return self._request("POST", "/lost-found", payload, headers)

    def list_lost_found(self, headers, params=None):
        return self._request("GET", "/lost-found", headers=headers, params=params)

    def get_lost_found(self, item_id, headers):
        return self._request("GET", f"/lost-found/{item_id}", headers=headers)

    def claim_lost_found(self, item_id, payload, headers):
        return self._request("POST", f"/lost-found/{item_id}/claim", payload, headers)

    def dispose_lost_found(self, item_id, headers):
        return self._request("POST", f"/lost-found/{item_id}/dispose", {}, headers)

    # ---- Test-driving clock ------------------------------------------------
    def advance_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/advance", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
