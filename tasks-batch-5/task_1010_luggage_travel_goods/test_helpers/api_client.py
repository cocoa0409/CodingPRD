"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (administrative) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- Product ---
    def create_product(self, payload, headers):
        return self._request("POST", "/store/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/store/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/store/products", headers=headers, params=params)

    def airline_fit(self, product_id, airline_id, headers):
        return self._request(
            "GET", f"/store/products/{product_id}/airline-fit",
            headers=headers, params={"airline_id": airline_id},
        )

    def discontinue_product(self, product_id, headers):
        return self._request("POST", f"/store/products/{product_id}/discontinue", {}, headers)

    # --- Airline ---
    def create_airline(self, payload, headers):
        return self._request("POST", "/store/airlines", payload, headers)

    def get_airline(self, airline_id, headers):
        return self._request("GET", f"/store/airlines/{airline_id}", headers=headers)

    def list_airlines(self, headers, params=None):
        return self._request("GET", "/store/airlines", headers=headers, params=params)

    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/store/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/store/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/store/customers", headers=headers, params=params)

    # --- WarrantyRegistration ---
    def create_registration(self, payload, headers):
        return self._request("POST", "/store/warranty-registrations", payload, headers)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/store/warranty-registrations/{registration_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/store/warranty-registrations", headers=headers, params=params)

    def void_registration(self, registration_id, headers):
        return self._request("POST", f"/store/warranty-registrations/{registration_id}/void", {}, headers)

    # --- WarrantyClaim ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/store/warranty-claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/store/warranty-claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/store/warranty-claims", headers=headers, params=params)

    def review_claim(self, claim_id, headers):
        return self._request("POST", f"/store/warranty-claims/{claim_id}/review", {}, headers)

    def request_info_claim(self, claim_id, headers):
        return self._request("POST", f"/store/warranty-claims/{claim_id}/request-info", {}, headers)

    def resubmit_claim(self, claim_id, headers):
        return self._request("POST", f"/store/warranty-claims/{claim_id}/resubmit", {}, headers)

    def resolve_claim(self, claim_id, resolution, headers):
        return self._request("POST", f"/store/warranty-claims/{claim_id}/resolve", {"resolution": resolution}, headers)

    # --- RepairOrder ---
    def create_repair_order(self, payload, headers):
        return self._request("POST", "/store/repair-orders", payload, headers)

    def get_repair_order(self, repair_order_id, headers):
        return self._request("GET", f"/store/repair-orders/{repair_order_id}", headers=headers)

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/store/repair-orders", headers=headers, params=params)

    def quote_repair_order(self, repair_order_id, headers):
        return self._request("POST", f"/store/repair-orders/{repair_order_id}/quote", {}, headers)

    def approve_repair_order(self, repair_order_id, headers):
        return self._request("POST", f"/store/repair-orders/{repair_order_id}/approve", {}, headers)

    def decline_repair_order(self, repair_order_id, headers):
        return self._request("POST", f"/store/repair-orders/{repair_order_id}/decline", {}, headers)

    def schedule_repair_order(self, repair_order_id, payload, headers):
        return self._request("POST", f"/store/repair-orders/{repair_order_id}/schedule", payload, headers)

    def start_repair_order(self, repair_order_id, headers):
        return self._request("POST", f"/store/repair-orders/{repair_order_id}/start", {}, headers)

    def parts_hold_repair_order(self, repair_order_id, headers):
        return self._request("POST", f"/store/repair-orders/{repair_order_id}/parts-hold", {}, headers)

    def resume_repair_order(self, repair_order_id, headers):
        return self._request("POST", f"/store/repair-orders/{repair_order_id}/resume", {}, headers)

    def ready_repair_order(self, repair_order_id, headers):
        return self._request("POST", f"/store/repair-orders/{repair_order_id}/ready", {}, headers)

    def close_repair_order(self, repair_order_id, headers):
        return self._request("POST", f"/store/repair-orders/{repair_order_id}/close", {}, headers)

    # --- RepairLine ---
    def create_repair_line(self, payload, headers):
        return self._request("POST", "/store/repair-lines", payload, headers)

    def get_repair_line(self, repair_line_id, headers):
        return self._request("GET", f"/store/repair-lines/{repair_line_id}", headers=headers)

    def list_repair_lines(self, headers, params=None):
        return self._request("GET", "/store/repair-lines", headers=headers, params=params)

    # --- SalesOrder ---
    def create_sales_order(self, payload, headers):
        return self._request("POST", "/store/sales-orders", payload, headers)

    def get_sales_order(self, sales_order_id, headers):
        return self._request("GET", f"/store/sales-orders/{sales_order_id}", headers=headers)

    def list_sales_orders(self, headers, params=None):
        return self._request("GET", "/store/sales-orders", headers=headers, params=params)

    def capture_sales_order(self, sales_order_id, headers):
        return self._request("POST", f"/store/sales-orders/{sales_order_id}/capture", {}, headers)

    def refund_sales_order(self, sales_order_id, headers):
        return self._request("POST", f"/store/sales-orders/{sales_order_id}/refund", {}, headers)

    def fulfill_sales_order(self, sales_order_id, headers):
        return self._request("POST", f"/store/sales-orders/{sales_order_id}/fulfill", {}, headers)

    def cancel_sales_order(self, sales_order_id, headers):
        return self._request("POST", f"/store/sales-orders/{sales_order_id}/cancel", {}, headers)

    # --- SalesOrderLine ---
    def create_sales_order_line(self, payload, headers):
        return self._request("POST", "/store/sales-order-lines", payload, headers)

    def get_sales_order_line(self, line_id, headers):
        return self._request("GET", f"/store/sales-order-lines/{line_id}", headers=headers)

    def list_sales_order_lines(self, headers, params=None):
        return self._request("GET", "/store/sales-order-lines", headers=headers, params=params)

    def schedule_monogram(self, line_id, payload, headers):
        return self._request("POST", f"/store/sales-order-lines/{line_id}/schedule-monogram", payload, headers)

    def start_monogram(self, line_id, headers):
        return self._request("POST", f"/store/sales-order-lines/{line_id}/start-monogram", {}, headers)

    def complete_monogram(self, line_id, headers):
        return self._request("POST", f"/store/sales-order-lines/{line_id}/complete-monogram", {}, headers)

    # --- TradeIn ---
    def create_trade_in(self, payload, headers):
        return self._request("POST", "/store/trade-ins", payload, headers)

    def get_trade_in(self, trade_in_id, headers):
        return self._request("GET", f"/store/trade-ins/{trade_in_id}", headers=headers)

    def list_trade_ins(self, headers, params=None):
        return self._request("GET", "/store/trade-ins", headers=headers, params=params)

    def accept_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/store/trade-ins/{trade_in_id}/accept", {}, headers)

    def decline_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/store/trade-ins/{trade_in_id}/decline", {}, headers)

    def void_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/store/trade-ins/{trade_in_id}/void", {}, headers)

    # --- SpecialOrder ---
    def create_special_order(self, payload, headers):
        return self._request("POST", "/store/special-orders", payload, headers)

    def get_special_order(self, special_order_id, headers):
        return self._request("GET", f"/store/special-orders/{special_order_id}", headers=headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/store/special-orders", headers=headers, params=params)

    def source_special_order(self, special_order_id, headers):
        return self._request("POST", f"/store/special-orders/{special_order_id}/source", {}, headers)

    def arrive_special_order(self, special_order_id, headers):
        return self._request("POST", f"/store/special-orders/{special_order_id}/arrive", {}, headers)

    def fulfill_special_order(self, special_order_id, headers):
        return self._request("POST", f"/store/special-orders/{special_order_id}/fulfill", {}, headers)

    def cancel_special_order(self, special_order_id, headers):
        return self._request("POST", f"/store/special-orders/{special_order_id}/cancel", {}, headers)

    # --- RecallNotice ---
    def create_recall_notice(self, payload, headers):
        return self._request("POST", "/store/recall-notices", payload, headers)

    def get_recall_notice(self, recall_notice_id, headers):
        return self._request("GET", f"/store/recall-notices/{recall_notice_id}", headers=headers)

    def list_recall_notices(self, headers, params=None):
        return self._request("GET", "/store/recall-notices", headers=headers, params=params)

    def publish_recall_notice(self, recall_notice_id, headers):
        return self._request("POST", f"/store/recall-notices/{recall_notice_id}/publish", {}, headers)

    def close_recall_notice(self, recall_notice_id, headers):
        return self._request("POST", f"/store/recall-notices/{recall_notice_id}/close", {}, headers)

    # --- ServiceBench ---
    def create_service_bench(self, payload, headers):
        return self._request("POST", "/store/service-benches", payload, headers)

    def get_service_bench(self, bench_id, headers):
        return self._request("GET", f"/store/service-benches/{bench_id}", headers=headers)

    def list_service_benches(self, headers, params=None):
        return self._request("GET", "/store/service-benches", headers=headers, params=params)

    # --- MonogramStation ---
    def create_monogram_station(self, payload, headers):
        return self._request("POST", "/store/monogram-stations", payload, headers)

    def get_monogram_station(self, station_id, headers):
        return self._request("GET", f"/store/monogram-stations/{station_id}", headers=headers)

    def list_monogram_stations(self, headers, params=None):
        return self._request("GET", "/store/monogram-stations", headers=headers, params=params)


api_client = ApiClient()
