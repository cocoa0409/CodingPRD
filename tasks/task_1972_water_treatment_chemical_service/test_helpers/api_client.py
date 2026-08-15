"""API client: one method per endpoint defined in the PRD (all under /wt)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/wt/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- CustomerAccount ---
    def create_account(self, payload, headers):
        return self._request("POST", "/wt/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/wt/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/wt/accounts/{account_id}", headers=headers)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/wt/accounts/{account_id}/suspend", {}, headers)

    def reactivate_account(self, account_id, headers):
        return self._request("POST", f"/wt/accounts/{account_id}/reactivate", {}, headers)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/wt/accounts/{account_id}/close", {}, headers)

    # --- SystemAsset ---
    def create_asset(self, payload, headers):
        return self._request("POST", "/wt/assets", payload, headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/wt/assets", headers=headers, params=params)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/wt/assets/{asset_id}", headers=headers)

    def get_water_savings(self, asset_id, headers):
        return self._request("GET", f"/wt/assets/{asset_id}/water-savings", headers=headers)

    def commission_asset(self, asset_id, headers):
        return self._request("POST", f"/wt/assets/{asset_id}/commission", {}, headers)

    def decommission_asset(self, asset_id, headers):
        return self._request("POST", f"/wt/assets/{asset_id}/decommission", {}, headers)

    # --- ProgramDesign ---
    def create_program_design(self, payload, headers):
        return self._request("POST", "/wt/program-designs", payload, headers)

    def list_program_designs(self, headers, params=None):
        return self._request("GET", "/wt/program-designs", headers=headers, params=params)

    def get_program_design(self, design_id, headers):
        return self._request("GET", f"/wt/program-designs/{design_id}", headers=headers)

    def record_survey(self, design_id, payload, headers):
        return self._request("POST", f"/wt/program-designs/{design_id}/record-survey", payload, headers)

    def draft_design(self, design_id, payload, headers):
        return self._request("POST", f"/wt/program-designs/{design_id}/draft", payload, headers)

    def propose_design(self, design_id, headers):
        return self._request("POST", f"/wt/program-designs/{design_id}/propose", {}, headers)

    def accept_design(self, design_id, payload, headers):
        return self._request("POST", f"/wt/program-designs/{design_id}/accept", payload, headers)

    def request_revision(self, design_id, headers):
        return self._request("POST", f"/wt/program-designs/{design_id}/request-revision", {}, headers)

    def reopen_survey(self, design_id, headers):
        return self._request("POST", f"/wt/program-designs/{design_id}/reopen-survey", {}, headers)

    def withdraw_design(self, design_id, headers):
        return self._request("POST", f"/wt/program-designs/{design_id}/withdraw", {}, headers)

    # --- ChemicalProduct ---
    def create_product(self, payload, headers):
        return self._request("POST", "/wt/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/wt/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/wt/products/{product_id}", headers=headers)

    def delist_product(self, product_id, headers):
        return self._request("POST", f"/wt/products/{product_id}/delist", {}, headers)

    # --- FeedStation ---
    def create_feed_station(self, payload, headers):
        return self._request("POST", "/wt/feed-stations", payload, headers)

    def list_feed_stations(self, headers, params=None):
        return self._request("GET", "/wt/feed-stations", headers=headers, params=params)

    def get_feed_station(self, station_id, headers):
        return self._request("GET", f"/wt/feed-stations/{station_id}", headers=headers)

    def bring_station_online(self, station_id, headers):
        return self._request("POST", f"/wt/feed-stations/{station_id}/bring-online", {}, headers)

    def lockout_station(self, station_id, headers):
        return self._request("POST", f"/wt/feed-stations/{station_id}/lockout", {}, headers)

    # --- TelemetryReading ---
    def post_telemetry(self, station_id, payload, headers):
        return self._request("POST", f"/wt/feed-stations/{station_id}/telemetry", payload, headers)

    def list_telemetry(self, station_id, headers, params=None):
        return self._request("GET", f"/wt/feed-stations/{station_id}/telemetry", headers=headers, params=params)

    # --- TestRoute / RouteStop ---
    def create_test_route(self, payload, headers):
        return self._request("POST", "/wt/test-routes", payload, headers)

    def list_test_routes(self, headers, params=None):
        return self._request("GET", "/wt/test-routes", headers=headers, params=params)

    def get_test_route(self, route_id, headers):
        return self._request("GET", f"/wt/test-routes/{route_id}", headers=headers)

    def add_route_stop(self, route_id, payload, headers):
        return self._request("POST", f"/wt/test-routes/{route_id}/stops", payload, headers)

    def list_route_stops(self, route_id, headers, params=None):
        return self._request("GET", f"/wt/test-routes/{route_id}/stops", headers=headers, params=params)

    def publish_route(self, route_id, headers):
        return self._request("POST", f"/wt/test-routes/{route_id}/publish", {}, headers)

    def cancel_route(self, route_id, headers):
        return self._request("POST", f"/wt/test-routes/{route_id}/cancel", {}, headers)

    def list_stops(self, headers, params=None):
        return self._request("GET", "/wt/route-stops", headers=headers, params=params)

    def get_stop(self, stop_id, headers):
        return self._request("GET", f"/wt/route-stops/{stop_id}", headers=headers)

    def arrive_stop(self, stop_id, headers):
        return self._request("POST", f"/wt/route-stops/{stop_id}/arrive", {}, headers)

    def mark_stop_missed(self, stop_id, headers):
        return self._request("POST", f"/wt/route-stops/{stop_id}/mark-missed", {}, headers)

    # --- WaterTestResult ---
    def record_water_test_result(self, stop_id, payload, headers):
        return self._request("POST", f"/wt/route-stops/{stop_id}/water-test-results", payload, headers)

    def list_results_at_stop(self, stop_id, headers, params=None):
        return self._request("GET", f"/wt/route-stops/{stop_id}/water-test-results", headers=headers, params=params)

    def list_water_test_results(self, headers, params=None):
        return self._request("GET", "/wt/water-test-results", headers=headers, params=params)

    def get_water_test_result(self, result_id, headers):
        return self._request("GET", f"/wt/water-test-results/{result_id}", headers=headers)

    def confirm_water_test_result(self, result_id, payload, headers):
        return self._request("POST", f"/wt/water-test-results/{result_id}/confirm", payload, headers)

    def void_water_test_result(self, result_id, headers):
        return self._request("POST", f"/wt/water-test-results/{result_id}/void", {}, headers)

    # --- CorrectiveAction ---
    def list_corrective_actions(self, headers, params=None):
        return self._request("GET", "/wt/corrective-actions", headers=headers, params=params)

    def get_corrective_action(self, action_id, headers):
        return self._request("GET", f"/wt/corrective-actions/{action_id}", headers=headers)

    def approve_corrective_action(self, action_id, payload, headers):
        return self._request("POST", f"/wt/corrective-actions/{action_id}/approve", payload, headers)

    def apply_corrective_action(self, action_id, headers):
        return self._request("POST", f"/wt/corrective-actions/{action_id}/apply", {}, headers)

    def decline_corrective_action(self, action_id, headers):
        return self._request("POST", f"/wt/corrective-actions/{action_id}/decline", {}, headers)

    # --- CouponRack / CorrosionCoupon ---
    def create_rack(self, payload, headers):
        return self._request("POST", "/wt/racks", payload, headers)

    def list_racks(self, headers, params=None):
        return self._request("GET", "/wt/racks", headers=headers, params=params)

    def get_rack(self, rack_id, headers):
        return self._request("GET", f"/wt/racks/{rack_id}", headers=headers)

    def archive_rack(self, rack_id, headers):
        return self._request("POST", f"/wt/racks/{rack_id}/archive", {}, headers)

    def install_coupon(self, rack_id, payload, headers):
        return self._request("POST", f"/wt/racks/{rack_id}/coupons", payload, headers)

    def list_coupons(self, rack_id, headers, params=None):
        return self._request("GET", f"/wt/racks/{rack_id}/coupons", headers=headers, params=params)

    def remove_coupon(self, coupon_id, payload, headers):
        return self._request("POST", f"/wt/coupons/{coupon_id}/remove", payload, headers)

    # --- LegionellaRiskPlan ---
    def create_legionella_plan(self, payload, headers):
        return self._request("POST", "/wt/legionella-plans", payload, headers)

    def list_legionella_plans(self, headers, params=None):
        return self._request("GET", "/wt/legionella-plans", headers=headers, params=params)

    def get_legionella_plan(self, plan_id, headers):
        return self._request("GET", f"/wt/legionella-plans/{plan_id}", headers=headers)

    def activate_legionella_plan(self, plan_id, headers):
        return self._request("POST", f"/wt/legionella-plans/{plan_id}/activate", {}, headers)

    def validate_legionella_plan(self, plan_id, headers):
        return self._request("POST", f"/wt/legionella-plans/{plan_id}/validate", {}, headers)

    def declare_plan_delinquent(self, plan_id, headers):
        return self._request("POST", f"/wt/legionella-plans/{plan_id}/declare-delinquent", {}, headers)

    def suspend_legionella_plan(self, plan_id, headers):
        return self._request("POST", f"/wt/legionella-plans/{plan_id}/suspend", {}, headers)

    def return_plan_to_draft(self, plan_id, headers):
        return self._request("POST", f"/wt/legionella-plans/{plan_id}/return-to-draft", {}, headers)

    # --- BlowdownEvent ---
    def log_blowdown_event(self, asset_id, payload, headers):
        return self._request("POST", f"/wt/assets/{asset_id}/blowdown-events", payload, headers)

    def list_blowdown_events(self, asset_id, headers, params=None):
        return self._request("GET", f"/wt/assets/{asset_id}/blowdown-events", headers=headers, params=params)

    # --- DeliveryOrder ---
    def create_delivery_order(self, payload, headers):
        return self._request("POST", "/wt/delivery-orders", payload, headers)

    def list_delivery_orders(self, headers, params=None):
        return self._request("GET", "/wt/delivery-orders", headers=headers, params=params)

    def get_delivery_order(self, order_id, headers):
        return self._request("GET", f"/wt/delivery-orders/{order_id}", headers=headers)

    def submit_delivery_order(self, order_id, headers):
        return self._request("POST", f"/wt/delivery-orders/{order_id}/submit", {}, headers)

    def schedule_delivery_order(self, order_id, payload, headers):
        return self._request("POST", f"/wt/delivery-orders/{order_id}/schedule", payload, headers)

    def dispatch_delivery_order(self, order_id, headers):
        return self._request("POST", f"/wt/delivery-orders/{order_id}/dispatch", {}, headers)

    def confirm_delivery(self, order_id, payload, headers):
        return self._request("POST", f"/wt/delivery-orders/{order_id}/confirm-delivery", payload, headers)

    def fail_delivery(self, order_id, headers):
        return self._request("POST", f"/wt/delivery-orders/{order_id}/fail", {}, headers)

    def close_delivery_order(self, order_id, payload, headers):
        return self._request("POST", f"/wt/delivery-orders/{order_id}/close", payload, headers)

    def cancel_delivery_order(self, order_id, headers):
        return self._request("POST", f"/wt/delivery-orders/{order_id}/cancel", {}, headers)

    # --- Invoice ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/wt/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/wt/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/wt/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/wt/invoices/{invoice_id}/issue", {}, headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/wt/invoices/{invoice_id}/pay", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/wt/invoices/{invoice_id}/void", {}, headers)


api_client = ApiClient()

# The per-test-server harness SIGKILLs and restarts the API server on the same
# port before every test. With keep-alive enabled, the session pool can hand a
# test a stale connection to the just-killed previous server generation,
# surfacing as a flaky ECONNRESET on first reuse under parallel load. Force
# connection-per-request so every request lands on the live server.
api_client.session.headers["Connection"] = "close"
