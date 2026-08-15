"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving, PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/roofing/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Branches
    # ------------------------------------------------------------------
    def create_branch(self, payload, headers):
        return self._request("POST", "/roofing/branches", payload, headers)

    def list_branches(self, headers, params=None):
        return self._request("GET", "/roofing/branches", headers=headers, params=params)

    def get_branch(self, branch_id, headers):
        return self._request("GET", f"/roofing/branches/{branch_id}", headers=headers)

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/roofing/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/roofing/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/roofing/products/{product_id}", headers=headers)

    # ------------------------------------------------------------------
    # Inventory lots
    # ------------------------------------------------------------------
    def receive_inventory_lot(self, branch_id, payload, headers):
        return self._request("POST", f"/roofing/branches/{branch_id}/inventory-lots",
                             payload, headers)

    def list_branch_inventory_lots(self, branch_id, headers, params=None):
        return self._request("GET", f"/roofing/branches/{branch_id}/inventory-lots",
                             headers=headers, params=params)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/roofing/inventory-lots/{lot_id}", headers=headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/roofing/inventory-lots", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Contractor accounts
    # ------------------------------------------------------------------
    def create_contractor_account(self, payload, headers):
        return self._request("POST", "/roofing/contractor-accounts", payload, headers)

    def list_contractor_accounts(self, headers, params=None):
        return self._request("GET", "/roofing/contractor-accounts", headers=headers,
                             params=params)

    def get_contractor_account(self, account_id, headers):
        return self._request("GET", f"/roofing/contractor-accounts/{account_id}",
                             headers=headers)

    def get_account_statement(self, account_id, headers):
        return self._request("GET", f"/roofing/contractor-accounts/{account_id}/statement",
                             headers=headers)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/roofing/contractor-accounts/{account_id}/suspend",
                             {}, headers)

    def reinstate_account(self, account_id, headers):
        return self._request("POST",
                             f"/roofing/contractor-accounts/{account_id}/reinstate",
                             {}, headers)

    def post_payment(self, account_id, payload, headers):
        return self._request("POST", f"/roofing/contractor-accounts/{account_id}/payments",
                             payload, headers)

    # ------------------------------------------------------------------
    # Job accounts
    # ------------------------------------------------------------------
    def create_job_account(self, account_id, payload, headers):
        return self._request("POST",
                             f"/roofing/contractor-accounts/{account_id}/job-accounts",
                             payload, headers)

    def list_job_accounts(self, account_id, headers, params=None):
        return self._request("GET",
                             f"/roofing/contractor-accounts/{account_id}/job-accounts",
                             headers=headers, params=params)

    def get_job_account(self, job_account_id, headers):
        return self._request("GET", f"/roofing/job-accounts/{job_account_id}",
                             headers=headers)

    def file_lien_notice(self, job_account_id, lien_notice_amount_cents, headers):
        return self._request("POST",
                             f"/roofing/job-accounts/{job_account_id}/file-lien-notice",
                             {"lien_notice_amount_cents": lien_notice_amount_cents},
                             headers)

    def record_lien(self, job_account_id, headers):
        return self._request("POST", f"/roofing/job-accounts/{job_account_id}/record-lien",
                             {}, headers)

    def release_lien(self, job_account_id, headers):
        return self._request("POST", f"/roofing/job-accounts/{job_account_id}/release-lien",
                             {}, headers)

    # ------------------------------------------------------------------
    # Material takeoffs
    # ------------------------------------------------------------------
    def create_takeoff(self, job_account_id, payload, headers):
        return self._request("POST", f"/roofing/job-accounts/{job_account_id}/takeoffs",
                             payload, headers)

    def list_job_takeoffs(self, job_account_id, headers, params=None):
        return self._request("GET", f"/roofing/job-accounts/{job_account_id}/takeoffs",
                             headers=headers, params=params)

    def list_takeoffs(self, headers, params=None):
        return self._request("GET", "/roofing/takeoffs", headers=headers, params=params)

    def get_takeoff(self, takeoff_id, headers):
        return self._request("GET", f"/roofing/takeoffs/{takeoff_id}", headers=headers)

    def quote_takeoff(self, takeoff_id, headers):
        return self._request("POST", f"/roofing/takeoffs/{takeoff_id}/quote", {}, headers)

    def revise_takeoff(self, takeoff_id, headers):
        return self._request("POST", f"/roofing/takeoffs/{takeoff_id}/revise", {}, headers)

    def convert_takeoff(self, takeoff_id, branch_id, headers):
        return self._request("POST", f"/roofing/takeoffs/{takeoff_id}/convert",
                             {"branch_id": branch_id}, headers)

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------
    def list_orders(self, headers, params=None):
        return self._request("GET", "/roofing/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/roofing/orders/{order_id}", headers=headers)

    def confirm_order(self, order_id, expected_contractor_account_version, headers):
        return self._request("POST", f"/roofing/orders/{order_id}/confirm",
                             {"expected_contractor_account_version":
                              expected_contractor_account_version}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/roofing/orders/{order_id}/cancel", {}, headers)

    def invoice_order(self, order_id, headers):
        return self._request("POST", f"/roofing/orders/{order_id}/invoice", {}, headers)

    def close_order(self, order_id, headers):
        return self._request("POST", f"/roofing/orders/{order_id}/close", {}, headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/roofing/orders/{order_id}/lines",
                             headers=headers, params=params)

    def list_order_lines_all(self, headers, params=None):
        return self._request("GET", "/roofing/order-lines", headers=headers, params=params)

    def get_order_line(self, order_line_id, headers):
        return self._request("GET", f"/roofing/order-lines/{order_line_id}", headers=headers)

    # ------------------------------------------------------------------
    # Delivery slots
    # ------------------------------------------------------------------
    def create_delivery_slot(self, branch_id, payload, headers):
        return self._request("POST", f"/roofing/branches/{branch_id}/delivery-slots",
                             payload, headers)

    def list_delivery_slots(self, branch_id, headers, params=None):
        return self._request("GET", f"/roofing/branches/{branch_id}/delivery-slots",
                             headers=headers, params=params)

    def get_delivery_slot(self, slot_id, headers):
        return self._request("GET", f"/roofing/delivery-slots/{slot_id}", headers=headers)

    # ------------------------------------------------------------------
    # Deliveries
    # ------------------------------------------------------------------
    def schedule_delivery(self, order_id, delivery_slot_id, equipment_type, headers):
        return self._request("POST", f"/roofing/orders/{order_id}/deliveries",
                             {"delivery_slot_id": delivery_slot_id,
                              "equipment_type": equipment_type}, headers)

    def list_order_deliveries(self, order_id, headers, params=None):
        return self._request("GET", f"/roofing/orders/{order_id}/deliveries",
                             headers=headers, params=params)

    def list_deliveries(self, headers, params=None):
        return self._request("GET", "/roofing/deliveries", headers=headers, params=params)

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/roofing/deliveries/{delivery_id}", headers=headers)

    def dispatch_delivery(self, delivery_id, headers):
        return self._request("POST", f"/roofing/deliveries/{delivery_id}/dispatch",
                             {}, headers)

    def complete_delivery(self, delivery_id, headers):
        return self._request("POST", f"/roofing/deliveries/{delivery_id}/complete",
                             {}, headers)

    def fail_delivery(self, delivery_id, headers):
        return self._request("POST", f"/roofing/deliveries/{delivery_id}/fail", {}, headers)

    def reschedule_delivery(self, delivery_id, delivery_slot_id, headers):
        return self._request("POST", f"/roofing/deliveries/{delivery_id}/reschedule",
                             {"delivery_slot_id": delivery_slot_id}, headers)

    def reconfirm_delivery(self, delivery_id, headers):
        return self._request("POST", f"/roofing/deliveries/{delivery_id}/reconfirm",
                             {}, headers)

    def cancel_delivery(self, delivery_id, headers):
        return self._request("POST", f"/roofing/deliveries/{delivery_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Storm surge events
    # ------------------------------------------------------------------
    def create_surge_event(self, branch_id, payload, headers):
        return self._request("POST", f"/roofing/branches/{branch_id}/surge-events",
                             payload, headers)

    def list_surge_events(self, branch_id, headers, params=None):
        return self._request("GET", f"/roofing/branches/{branch_id}/surge-events",
                             headers=headers, params=params)

    def get_surge_event(self, event_id, headers):
        return self._request("GET", f"/roofing/surge-events/{event_id}", headers=headers)

    def close_surge_event(self, event_id, headers):
        return self._request("POST", f"/roofing/surge-events/{event_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Allocations
    # ------------------------------------------------------------------
    def request_allocation(self, event_id, payload, headers):
        return self._request("POST", f"/roofing/surge-events/{event_id}/allocations",
                             payload, headers)

    def list_event_allocations(self, event_id, headers, params=None):
        return self._request("GET", f"/roofing/surge-events/{event_id}/allocations",
                             headers=headers, params=params)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/roofing/allocations", headers=headers, params=params)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/roofing/allocations/{allocation_id}", headers=headers)

    def grant_allocation(self, allocation_id, expected_storm_surge_event_version, headers):
        return self._request("POST", f"/roofing/allocations/{allocation_id}/grant",
                             {"expected_storm_surge_event_version":
                              expected_storm_surge_event_version}, headers)

    def revoke_allocation(self, allocation_id, headers):
        return self._request("POST", f"/roofing/allocations/{allocation_id}/revoke",
                             {}, headers)

    # ------------------------------------------------------------------
    # Returns
    # ------------------------------------------------------------------
    def request_return(self, order_id, payload, headers):
        return self._request("POST", f"/roofing/orders/{order_id}/returns",
                             payload, headers)

    def list_order_returns(self, order_id, headers, params=None):
        return self._request("GET", f"/roofing/orders/{order_id}/returns",
                             headers=headers, params=params)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/roofing/returns", headers=headers, params=params)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/roofing/returns/{return_id}", headers=headers)

    def approve_return(self, return_id, headers):
        return self._request("POST", f"/roofing/returns/{return_id}/approve", {}, headers)

    def receive_return(self, return_id, returned_lot_code, headers):
        return self._request("POST", f"/roofing/returns/{return_id}/receive",
                             {"returned_lot_code": returned_lot_code}, headers)

    def reject_return(self, return_id, headers):
        return self._request("POST", f"/roofing/returns/{return_id}/reject", {}, headers)

    # ------------------------------------------------------------------
    # Damage claims
    # ------------------------------------------------------------------
    def file_damage_claim(self, delivery_id, payload, headers):
        return self._request("POST", f"/roofing/deliveries/{delivery_id}/damage-claims",
                             payload, headers)

    def list_delivery_damage_claims(self, delivery_id, headers, params=None):
        return self._request("GET", f"/roofing/deliveries/{delivery_id}/damage-claims",
                             headers=headers, params=params)

    def get_damage_claim(self, claim_id, headers):
        return self._request("GET", f"/roofing/damage-claims/{claim_id}", headers=headers)

    def start_claim_review(self, claim_id, headers):
        return self._request("POST", f"/roofing/damage-claims/{claim_id}/start-review",
                             {}, headers)

    def approve_claim(self, claim_id, approved_amount_cents, headers):
        return self._request("POST", f"/roofing/damage-claims/{claim_id}/approve",
                             {"approved_amount_cents": approved_amount_cents}, headers)

    def reject_claim(self, claim_id, headers):
        return self._request("POST", f"/roofing/damage-claims/{claim_id}/reject",
                             {}, headers)

    def credit_claim(self, claim_id, headers):
        return self._request("POST", f"/roofing/damage-claims/{claim_id}/credit",
                             {}, headers)

    def dispute_claim(self, claim_id, headers):
        return self._request("POST", f"/roofing/damage-claims/{claim_id}/dispute",
                             {}, headers)

    # ------------------------------------------------------------------
    # Warranty registrations
    # ------------------------------------------------------------------
    def register_warranty(self, order_id, headers):
        return self._request("POST", f"/roofing/orders/{order_id}/warranty-registrations",
                             {}, headers)

    def list_warranty_registrations(self, order_id, headers, params=None):
        return self._request("GET",
                             f"/roofing/orders/{order_id}/warranty-registrations",
                             headers=headers, params=params)


api_client = ApiClient()
