"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # --- Logical clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- FiscalYear ---
    def create_fiscal_year(self, payload, headers):
        return self._request("POST", "/coop/fiscal-years", payload, headers)

    def get_fiscal_year(self, fiscal_year_id, headers):
        return self._request("GET", f"/coop/fiscal-years/{fiscal_year_id}", headers=headers)

    def close_fiscal_year(self, fiscal_year_id, headers):
        return self._request("POST", f"/coop/fiscal-years/{fiscal_year_id}/close", {}, headers)

    # --- Member ---
    def create_member(self, payload, headers):
        return self._request("POST", "/coop/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/coop/members/{member_id}", headers=headers)

    def approve_member(self, member_id, headers):
        return self._request("POST", f"/coop/members/{member_id}/approve", {}, headers)

    def equity_contribution(self, member_id, payload, headers):
        return self._request(
            "POST", f"/coop/members/{member_id}/equity-contribution", payload, headers
        )

    def drop_member(self, member_id, headers):
        return self._request("POST", f"/coop/members/{member_id}/drop", {}, headers)

    # --- Vendor ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/coop/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/coop/vendors/{vendor_id}", headers=headers)

    def set_vendor_status(self, vendor_id, payload, headers):
        return self._request(
            "POST", f"/coop/vendors/{vendor_id}/set-status", payload, headers
        )

    # --- Product ---
    def create_product(self, payload, headers):
        return self._request("POST", "/coop/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/coop/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/coop/products/{product_id}", headers=headers)

    def update_product(self, product_id, payload, headers):
        return self._request("PATCH", f"/coop/products/{product_id}", payload, headers)

    def shrink_product(self, product_id, payload, headers):
        return self._request("POST", f"/coop/products/{product_id}/shrink", payload, headers)

    # --- InventoryLot ---
    def create_inventory_lot(self, payload, headers):
        return self._request("POST", "/coop/inventory-lots", payload, headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/coop/inventory-lots", headers=headers, params=params)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/coop/inventory-lots/{lot_id}", headers=headers)

    def post_inventory_lot(self, lot_id, headers):
        return self._request("POST", f"/coop/inventory-lots/{lot_id}/post", {}, headers)

    # --- Register ---
    def create_register(self, payload, headers):
        return self._request("POST", "/coop/registers", payload, headers)

    def get_register(self, register_id, headers):
        return self._request("GET", f"/coop/registers/{register_id}", headers=headers)

    def set_register_open(self, register_id, payload, headers):
        return self._request(
            "POST", f"/coop/registers/{register_id}/set-open", payload, headers
        )

    # --- Sale ---
    def create_sale(self, payload, headers):
        return self._request("POST", "/coop/sales", payload, headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/coop/sales", headers=headers, params=params)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/coop/sales/{sale_id}", headers=headers)

    def add_sale_line(self, sale_id, payload, headers):
        return self._request("POST", f"/coop/sales/{sale_id}/lines", payload, headers)

    def finalize_sale(self, sale_id, headers):
        return self._request("POST", f"/coop/sales/{sale_id}/finalize", {}, headers)

    def pay_sale(self, sale_id, headers):
        return self._request("POST", f"/coop/sales/{sale_id}/pay", {}, headers)

    def refund_sale(self, sale_id, headers):
        return self._request("POST", f"/coop/sales/{sale_id}/refund", {}, headers)

    # --- Promotion ---
    def create_promotion(self, payload, headers):
        return self._request("POST", "/coop/promotions", payload, headers)

    def list_promotions(self, headers, params=None):
        return self._request("GET", "/coop/promotions", headers=headers, params=params)

    def get_promotion(self, promotion_id, headers):
        return self._request("GET", f"/coop/promotions/{promotion_id}", headers=headers)

    # --- WorkingMemberShift ---
    def create_working_shift(self, payload, headers):
        return self._request("POST", "/coop/working-shifts", payload, headers)

    def list_working_shifts(self, headers, params=None):
        return self._request("GET", "/coop/working-shifts", headers=headers, params=params)

    def get_working_shift(self, shift_id, headers):
        return self._request("GET", f"/coop/working-shifts/{shift_id}", headers=headers)

    def complete_working_shift(self, shift_id, headers):
        return self._request("POST", f"/coop/working-shifts/{shift_id}/complete", {}, headers)

    # --- BoardProposal ---
    def create_board_proposal(self, payload, headers):
        return self._request("POST", "/coop/board-proposals", payload, headers)

    def get_board_proposal(self, proposal_id, headers):
        return self._request("GET", f"/coop/board-proposals/{proposal_id}", headers=headers)

    def advance_board_proposal(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"/coop/board-proposals/{proposal_id}/advance", payload, headers
        )

    def cast_board_vote(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"/coop/board-proposals/{proposal_id}/votes", payload, headers
        )

    def tally_board_proposal(self, proposal_id, headers):
        return self._request(
            "POST", f"/coop/board-proposals/{proposal_id}/tally", {}, headers
        )

    # --- PatronageAllocation ---
    def create_patronage_allocation(self, payload, headers):
        return self._request("POST", "/coop/patronage-allocations", payload, headers)

    def list_patronage_allocations(self, headers, params=None):
        return self._request(
            "GET", "/coop/patronage-allocations", headers=headers, params=params
        )

    def get_patronage_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"/coop/patronage-allocations/{allocation_id}", headers=headers
        )

    def finalize_patronage_allocation(self, allocation_id, headers):
        return self._request(
            "POST", f"/coop/patronage-allocations/{allocation_id}/finalize", {}, headers
        )


api_client = ApiClient()
