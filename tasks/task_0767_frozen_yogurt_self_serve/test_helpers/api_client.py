"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers=headers)

    # --- Machine ------------------------------------------------------------
    def create_machine(self, payload, headers):
        return self._request("POST", "/machines", payload, headers=headers)

    def list_machines(self, headers, params=None):
        return self._request("GET", "/machines", headers=headers, params=params)

    def get_machine(self, machine_id, headers):
        return self._request("GET", f"/machines/{machine_id}", headers=headers)

    def start_cleaning(self, machine_id, headers):
        return self._request("POST", f"/machines/{machine_id}/start-cleaning", {}, headers=headers)

    def complete_cleaning(self, machine_id, headers):
        return self._request("POST", f"/machines/{machine_id}/complete-cleaning", {}, headers=headers)

    def refill_mix(self, machine_id, added_oz, headers):
        return self._request("POST", f"/machines/{machine_id}/refill-mix",
                             {"added_oz": added_oz}, headers=headers)

    def check_sanitation(self, machine_id, headers):
        return self._request("POST", f"/machines/{machine_id}/check-sanitation", {}, headers=headers)

    # --- Flavor -------------------------------------------------------------
    def create_flavor(self, payload, headers):
        return self._request("POST", "/flavors", payload, headers=headers)

    def list_flavors(self, headers, params=None):
        return self._request("GET", "/flavors", headers=headers, params=params)

    def get_flavor(self, flavor_id, headers):
        return self._request("GET", f"/flavors/{flavor_id}", headers=headers)

    def rotate_out_flavor(self, flavor_id, headers):
        return self._request("POST", f"/flavors/{flavor_id}/rotate-out", {}, headers=headers)

    # --- Topping ------------------------------------------------------------
    def create_topping(self, payload, headers):
        return self._request("POST", "/toppings", payload, headers=headers)

    def list_toppings(self, headers, params=None):
        return self._request("GET", "/toppings", headers=headers, params=params)

    def get_topping(self, topping_id, headers):
        return self._request("GET", f"/toppings/{topping_id}", headers=headers)

    def restock_topping(self, topping_id, added_units, headers):
        return self._request("POST", f"/toppings/{topping_id}/restock",
                             {"added_units": added_units}, headers=headers)

    def rotate_out_topping(self, topping_id, headers):
        return self._request("POST", f"/toppings/{topping_id}/rotate-out", {}, headers=headers)

    # --- SeasonalPromotion --------------------------------------------------
    def create_promotion(self, payload, headers):
        return self._request("POST", "/seasonal-promotions", payload, headers=headers)

    def list_promotions(self, headers, params=None):
        return self._request("GET", "/seasonal-promotions", headers=headers, params=params)

    # --- LoyaltyAccount -----------------------------------------------------
    def create_loyalty(self, payload, headers):
        return self._request("POST", "/loyalty-accounts", payload, headers=headers)

    def list_loyalty(self, headers, params=None):
        return self._request("GET", "/loyalty-accounts", headers=headers, params=params)

    def get_loyalty(self, loyalty_id, headers):
        return self._request("GET", f"/loyalty-accounts/{loyalty_id}", headers=headers)

    def suspend_loyalty(self, loyalty_id, headers):
        return self._request("POST", f"/loyalty-accounts/{loyalty_id}/suspend", {}, headers=headers)

    # --- RewardVoucher (read only) ------------------------------------------
    def list_vouchers(self, headers, params=None):
        return self._request("GET", "/reward-vouchers", headers=headers, params=params)

    def get_voucher(self, voucher_id, headers):
        return self._request("GET", f"/reward-vouchers/{voucher_id}", headers=headers)

    # --- SaleTicket ---------------------------------------------------------
    def create_ticket(self, payload, headers):
        return self._request("POST", "/sale-tickets", payload, headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/sale-tickets", headers=headers, params=params)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/sale-tickets/{ticket_id}", headers=headers)

    def add_line(self, ticket_id, payload, headers):
        return self._request("POST", f"/sale-tickets/{ticket_id}/lines", payload, headers=headers)

    def list_lines(self, ticket_id, headers, params=None):
        return self._request("GET", f"/sale-tickets/{ticket_id}/lines", headers=headers, params=params)

    def checkout(self, ticket_id, payload, headers):
        return self._request("POST", f"/sale-tickets/{ticket_id}/checkout", payload, headers=headers)

    def void_ticket(self, ticket_id, headers):
        return self._request("POST", f"/sale-tickets/{ticket_id}/void", {}, headers=headers)

    # --- SaleLine (flat reads) ----------------------------------------------
    def list_sale_lines(self, headers, params=None):
        return self._request("GET", "/sale-lines", headers=headers, params=params)

    def get_sale_line(self, line_id, headers):
        return self._request("GET", f"/sale-lines/{line_id}", headers=headers)

    # --- WasteEvent ---------------------------------------------------------
    def create_waste_event(self, payload, headers):
        return self._request("POST", "/waste-events", payload, headers=headers)

    def list_waste_events(self, headers, params=None):
        return self._request("GET", "/waste-events", headers=headers, params=params)

    def get_waste_event(self, waste_id, headers):
        return self._request("GET", f"/waste-events/{waste_id}", headers=headers)

    # --- SanitationLog (read only) ------------------------------------------
    def list_sanitation_logs(self, headers, params=None):
        return self._request("GET", "/sanitation-logs", headers=headers, params=params)

    def get_sanitation_log(self, log_id, headers):
        return self._request("GET", f"/sanitation-logs/{log_id}", headers=headers)

    # --- MaintenanceWindow --------------------------------------------------
    def create_maintenance_window(self, payload, headers):
        return self._request("POST", "/maintenance-windows", payload, headers=headers)

    def list_maintenance_windows(self, headers, params=None):
        return self._request("GET", "/maintenance-windows", headers=headers, params=params)

    def get_maintenance_window(self, window_id, headers):
        return self._request("GET", f"/maintenance-windows/{window_id}", headers=headers)

    def cancel_maintenance_window(self, window_id, headers):
        return self._request("POST", f"/maintenance-windows/{window_id}/cancel", {}, headers=headers)

    # --- CateringResource ---------------------------------------------------
    def create_catering_resource(self, payload, headers):
        return self._request("POST", "/catering-resources", payload, headers=headers)

    def list_catering_resources(self, headers, params=None):
        return self._request("GET", "/catering-resources", headers=headers, params=params)

    # --- CateringOrder ------------------------------------------------------
    def create_catering_order(self, payload, headers):
        return self._request("POST", "/catering-orders", payload, headers=headers)

    def list_catering_orders(self, headers, params=None):
        return self._request("GET", "/catering-orders", headers=headers, params=params)

    def get_catering_order(self, order_id, headers):
        return self._request("GET", f"/catering-orders/{order_id}", headers=headers)

    def quote_catering_order(self, order_id, headers):
        return self._request("POST", f"/catering-orders/{order_id}/quote", {}, headers=headers)

    def confirm_catering_order(self, order_id, deposit_paid_cents, headers):
        return self._request("POST", f"/catering-orders/{order_id}/confirm",
                             {"deposit_paid_cents": deposit_paid_cents}, headers=headers)

    def fulfill_catering_order(self, order_id, headers):
        return self._request("POST", f"/catering-orders/{order_id}/fulfill", {}, headers=headers)

    def cancel_catering_order(self, order_id, headers):
        return self._request("POST", f"/catering-orders/{order_id}/cancel", {}, headers=headers)

    # --- DailyReconciliation ------------------------------------------------
    def create_reconciliation(self, payload, headers):
        return self._request("POST", "/daily-reconciliations", payload, headers=headers)

    def list_reconciliations(self, headers, params=None):
        return self._request("GET", "/daily-reconciliations", headers=headers, params=params)

    def get_reconciliation(self, recon_id, headers):
        return self._request("GET", f"/daily-reconciliations/{recon_id}", headers=headers)

    def close_reconciliation(self, recon_id, counted_cash_cents, headers):
        return self._request("POST", f"/daily-reconciliations/{recon_id}/close",
                             {"counted_cash_cents": counted_cash_cents}, headers=headers)

    def post_adjustment(self, recon_id, payload, headers):
        return self._request("POST", f"/daily-reconciliations/{recon_id}/adjustments",
                             payload, headers=headers)


api_client = ApiClient()
