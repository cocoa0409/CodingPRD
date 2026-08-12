"""API client: one method per endpoint defined in the PRD §4 endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Shippers ---
    def create_shipper(self, payload, headers=None):
        return self._request("POST", "/market/shippers", payload, headers)

    def get_shipper(self, shipper_id, headers=None):
        return self._request("GET", f"/market/shippers/{shipper_id}", headers=headers)

    # --- Customers ---
    def create_customer(self, payload, headers=None):
        return self._request("POST", "/market/customers", payload, headers)

    def get_customer(self, customer_id, headers=None):
        return self._request("GET", f"/market/customers/{customer_id}", headers=headers)

    def update_customer(self, customer_id, payload, headers=None):
        return self._request("PATCH", f"/market/customers/{customer_id}", payload, headers)

    def list_customer_sales_orders(self, customer_id, headers=None, params=None):
        return self._request("GET", f"/market/customers/{customer_id}/sales-orders",
                             headers=headers, params=params)

    def list_customer_invoices(self, customer_id, headers=None, params=None):
        return self._request("GET", f"/market/customers/{customer_id}/invoices",
                             headers=headers, params=params)

    # --- Commodities ---
    def create_commodity(self, payload, headers=None):
        return self._request("POST", "/market/commodities", payload, headers)

    def get_commodity(self, commodity_id, headers=None):
        return self._request("GET", f"/market/commodities/{commodity_id}", headers=headers)

    # --- Daily prices ---
    def create_daily_price(self, payload, headers=None):
        return self._request("POST", "/market/daily-prices", payload, headers)

    def get_daily_price(self, price_id, headers=None):
        return self._request("GET", f"/market/daily-prices/{price_id}", headers=headers)

    def list_daily_prices(self, headers=None, params=None):
        return self._request("GET", "/market/daily-prices", headers=headers, params=params)

    # --- Purchase lots ---
    def create_purchase_lot(self, payload, headers=None):
        return self._request("POST", "/market/purchase-lots", payload, headers)

    def list_purchase_lots(self, headers=None, params=None):
        return self._request("GET", "/market/purchase-lots", headers=headers, params=params)

    def get_purchase_lot(self, lot_id, headers=None):
        return self._request("GET", f"/market/purchase-lots/{lot_id}", headers=headers)

    def receive_lot(self, lot_id, headers=None):
        return self._request("POST", f"/market/purchase-lots/{lot_id}/receive", {}, headers)

    def dispute_lot(self, lot_id, payload=None, headers=None):
        return self._request("POST", f"/market/purchase-lots/{lot_id}/dispute",
                             payload or {}, headers)

    def resolve_dispute(self, lot_id, payload, headers=None):
        return self._request("POST", f"/market/purchase-lots/{lot_id}/resolve-dispute",
                             payload, headers)

    def close_lot(self, lot_id, headers=None):
        return self._request("POST", f"/market/purchase-lots/{lot_id}/close", {}, headers)

    # --- Inspections ---
    def create_inspection(self, payload, headers=None):
        return self._request("POST", "/market/inspections", payload, headers)

    def list_lot_inspections(self, lot_id, headers=None):
        return self._request("GET", f"/market/purchase-lots/{lot_id}/inspections",
                             headers=headers)

    def certify_inspection(self, inspection_id, headers=None):
        return self._request("POST", f"/market/inspections/{inspection_id}/certify",
                             {}, headers)

    # --- Temperature readings ---
    def create_temperature_reading(self, payload, headers=None):
        return self._request("POST", "/market/temperature-readings", payload, headers)

    def list_lot_temperature_readings(self, lot_id, headers=None):
        return self._request("GET", f"/market/purchase-lots/{lot_id}/temperature-readings",
                             headers=headers)

    # --- Ripening rooms and bookings ---
    def create_ripening_room(self, payload, headers=None):
        return self._request("POST", "/market/ripening-rooms", payload, headers)

    def get_ripening_room(self, room_id, headers=None):
        return self._request("GET", f"/market/ripening-rooms/{room_id}", headers=headers)

    def list_room_bookings(self, room_id, headers=None):
        return self._request("GET", f"/market/ripening-rooms/{room_id}/ripening-bookings",
                             headers=headers)

    def create_ripening_booking(self, payload, headers=None):
        return self._request("POST", "/market/ripening-bookings", payload, headers)

    def list_lot_bookings(self, lot_id, headers=None):
        return self._request("GET", f"/market/purchase-lots/{lot_id}/ripening-bookings",
                             headers=headers)

    def start_booking(self, booking_id, headers=None):
        return self._request("POST", f"/market/ripening-bookings/{booking_id}/start",
                             {}, headers)

    def complete_booking(self, booking_id, headers=None):
        return self._request("POST", f"/market/ripening-bookings/{booking_id}/complete",
                             {}, headers)

    def cancel_booking(self, booking_id, headers=None):
        return self._request("POST", f"/market/ripening-bookings/{booking_id}/cancel",
                             {}, headers)

    # --- Shrink records and credit memos ---
    def create_shrink_record(self, payload, headers=None):
        return self._request("POST", "/market/shrink-records", payload, headers)

    def list_lot_shrink_records(self, lot_id, headers=None):
        return self._request("GET", f"/market/purchase-lots/{lot_id}/shrink-records",
                             headers=headers)

    def approve_shrink_record(self, shrink_id, headers=None):
        return self._request("POST", f"/market/shrink-records/{shrink_id}/approve",
                             {}, headers)

    def list_lot_credit_memos(self, lot_id, headers=None):
        return self._request("GET", f"/market/purchase-lots/{lot_id}/credit-memos",
                             headers=headers)

    def void_credit_memo(self, memo_id, headers=None):
        return self._request("POST", f"/market/credit-memos/{memo_id}/void", {}, headers)

    # --- Sales orders ---
    def create_sales_order(self, payload, headers=None):
        return self._request("POST", "/market/sales-orders", payload, headers)

    def get_sales_order(self, order_id, headers=None):
        return self._request("GET", f"/market/sales-orders/{order_id}", headers=headers)

    def confirm_order(self, order_id, headers=None):
        return self._request("POST", f"/market/sales-orders/{order_id}/confirm", {}, headers)

    def pick_order(self, order_id, headers=None):
        return self._request("POST", f"/market/sales-orders/{order_id}/pick", {}, headers)

    def deliver_order(self, order_id, headers=None):
        return self._request("POST", f"/market/sales-orders/{order_id}/deliver", {}, headers)

    def cancel_order(self, order_id, headers=None):
        return self._request("POST", f"/market/sales-orders/{order_id}/cancel", {}, headers)

    # --- Invoices and payments ---
    def create_invoice(self, payload, headers=None):
        return self._request("POST", "/market/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers=None):
        return self._request("GET", f"/market/invoices/{invoice_id}", headers=headers)

    def list_order_invoices(self, order_id, headers=None):
        return self._request("GET", f"/market/sales-orders/{order_id}/invoices",
                             headers=headers)

    def create_payment(self, payload, headers=None):
        return self._request("POST", "/market/payments", payload, headers)

    def list_invoice_payments(self, invoice_id, headers=None):
        return self._request("GET", f"/market/invoices/{invoice_id}/payments",
                             headers=headers)

    # --- Labor tickets ---
    def create_labor_ticket(self, payload, headers=None):
        return self._request("POST", "/market/labor-tickets", payload, headers)

    def list_lot_labor_tickets(self, lot_id, headers=None):
        return self._request("GET", f"/market/purchase-lots/{lot_id}/labor-tickets",
                             headers=headers)

    # --- Logical clock and day-close ops run ---
    def set_clock(self, payload, headers=None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_day_close(self, headers=None):
        return self._request("POST", "/market/ops/run-day-close", {}, headers)


api_client = ApiClient()
