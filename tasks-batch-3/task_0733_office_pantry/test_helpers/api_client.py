"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------- Plans ----------
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/plans", headers=headers, params=params)

    # ---------- Products ----------
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    # ---------- Clients ----------
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def patch_client_headcount(self, client_id, payload, headers):
        return self._request("PATCH", f"/clients/{client_id}/headcount", payload, headers)

    # ---------- Locations ----------
    def create_location(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/locations", payload, headers)

    def list_client_locations(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/locations", headers=headers, params=params)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/locations/{location_id}", headers=headers)

    def list_locations(self, headers, params=None):
        return self._request("GET", "/locations", headers=headers, params=params)

    # ---------- Preferences ----------
    def create_preference(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/preferences", payload, headers)

    def list_preferences(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/preferences", headers=headers, params=params)

    # ---------- ParLevels ----------
    def create_par_level(self, location_id, payload, headers):
        return self._request("POST", f"/locations/{location_id}/par-levels", payload, headers)

    def list_location_par_levels(self, location_id, headers, params=None):
        return self._request("GET", f"/locations/{location_id}/par-levels", headers=headers, params=params)

    def get_par_level(self, par_level_id, headers):
        return self._request("GET", f"/par-levels/{par_level_id}", headers=headers)

    def list_par_levels(self, headers, params=None):
        return self._request("GET", "/par-levels", headers=headers, params=params)

    # ---------- Subscriptions ----------
    def create_subscription(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def activate_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/activate", headers=headers)

    def pause_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/pause", headers=headers)

    def resume_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/resume", headers=headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", headers=headers)

    def list_subscription_rotation_cycles(self, subscription_id, headers, params=None):
        return self._request("GET", f"/subscriptions/{subscription_id}/rotation-cycles", headers=headers, params=params)

    # ---------- RotationCycles ----------
    def get_rotation_cycle(self, rotation_cycle_id, headers):
        return self._request("GET", f"/rotation-cycles/{rotation_cycle_id}", headers=headers)

    def close_rotation_cycle(self, rotation_cycle_id, headers):
        return self._request("POST", f"/rotation-cycles/{rotation_cycle_id}/close", headers=headers)

    def create_delivery(self, rotation_cycle_id, payload, headers):
        return self._request("POST", f"/rotation-cycles/{rotation_cycle_id}/deliveries", payload, headers)

    def list_rotation_cycle_deliveries(self, rotation_cycle_id, headers, params=None):
        return self._request("GET", f"/rotation-cycles/{rotation_cycle_id}/deliveries", headers=headers, params=params)

    # ---------- Deliveries ----------
    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/deliveries/{delivery_id}", headers=headers)

    def list_deliveries(self, headers, params=None):
        return self._request("GET", "/deliveries", headers=headers, params=params)

    def dispatch_delivery(self, delivery_id, headers):
        return self._request("POST", f"/deliveries/{delivery_id}/dispatch", headers=headers)

    def confirm_delivery(self, delivery_id, headers):
        return self._request("POST", f"/deliveries/{delivery_id}/confirm", headers=headers)

    def dispute_delivery(self, delivery_id, payload, headers):
        return self._request("POST", f"/deliveries/{delivery_id}/dispute", payload, headers)

    def resolve_delivery_dispute(self, delivery_id, headers):
        return self._request("POST", f"/deliveries/{delivery_id}/resolve-dispute", headers=headers)

    def finalize_delivery(self, delivery_id, headers):
        return self._request("POST", f"/deliveries/{delivery_id}/finalize", headers=headers)

    def list_delivery_lines_for_delivery(self, delivery_id, headers, params=None):
        return self._request("GET", f"/deliveries/{delivery_id}/lines", headers=headers, params=params)

    # ---------- DeliveryLines ----------
    def patch_delivery_line_actual(self, delivery_line_id, payload, headers):
        return self._request("PATCH", f"/delivery-lines/{delivery_line_id}/actual", payload, headers)

    def get_delivery_line(self, delivery_line_id, headers):
        return self._request("GET", f"/delivery-lines/{delivery_line_id}", headers=headers)

    def list_delivery_lines(self, headers, params=None):
        return self._request("GET", "/delivery-lines", headers=headers, params=params)

    # ---------- Invoices ----------
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_client_invoices(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/invoices", headers=headers, params=params)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", headers=headers)

    def resolve_invoice_dispute(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/resolve-dispute", headers=headers)

    # ---------- Feedback ----------
    def create_feedback(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/feedback", payload, headers)

    def list_client_feedback(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/feedback", headers=headers, params=params)

    def get_client_satisfaction(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/satisfaction", headers=headers, params=params)

    def get_feedback(self, feedback_id, headers):
        return self._request("GET", f"/feedback/{feedback_id}", headers=headers)

    def list_feedback(self, headers, params=None):
        return self._request("GET", "/feedback", headers=headers, params=params)

    # ---------- Test-driving endpoints ----------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def advance_invoice_default(self, headers):
        return self._request("POST", "/_system/advance-invoice-default", headers=headers)


api_client = ApiClient()
