"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock & health ───────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def health(self, headers=None):
        return self._request("GET", "/_health", headers=headers)

    # ─── StyleService ─────────────────────────────────────────────────────────
    def create_style_service(self, payload, headers):
        return self._request("POST", "/style-services", payload, headers)

    def list_style_services(self, headers, params=None):
        return self._request("GET", "/style-services", headers=headers, params=params)

    def get_style_service(self, service_id, headers):
        return self._request("GET", f"/style-services/{service_id}", headers=headers)

    # ─── AddOn ────────────────────────────────────────────────────────────────
    def create_add_on(self, payload, headers):
        return self._request("POST", "/add-ons", payload, headers)

    def list_add_ons(self, headers, params=None):
        return self._request("GET", "/add-ons", headers=headers, params=params)

    def get_add_on(self, add_on_id, headers):
        return self._request("GET", f"/add-ons/{add_on_id}", headers=headers)

    # ─── MembershipPlan ───────────────────────────────────────────────────────
    def create_membership_plan(self, payload, headers):
        return self._request("POST", "/membership-plans", payload, headers)

    def list_membership_plans(self, headers, params=None):
        return self._request("GET", "/membership-plans", headers=headers, params=params)

    def get_membership_plan(self, plan_id, headers):
        return self._request("GET", f"/membership-plans/{plan_id}", headers=headers)

    # ─── Member ───────────────────────────────────────────────────────────────
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def prepay_member(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/prepay", payload, headers)

    def reinstate_member(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/reinstate", payload, headers)

    # ─── Stylist ──────────────────────────────────────────────────────────────
    def create_stylist(self, payload, headers):
        return self._request("POST", "/stylists", payload, headers)

    def list_stylists(self, headers, params=None):
        return self._request("GET", "/stylists", headers=headers, params=params)

    def get_stylist(self, stylist_id, headers):
        return self._request("GET", f"/stylists/{stylist_id}", headers=headers)

    # ─── Chair ────────────────────────────────────────────────────────────────
    def create_chair(self, payload, headers):
        return self._request("POST", "/chairs", payload, headers)

    def list_chairs(self, headers, params=None):
        return self._request("GET", "/chairs", headers=headers, params=params)

    def get_chair(self, chair_id, headers):
        return self._request("GET", f"/chairs/{chair_id}", headers=headers)

    # ─── EventBlock ───────────────────────────────────────────────────────────
    def create_event_block(self, payload, headers):
        return self._request("POST", "/event-blocks", payload, headers)

    def list_event_blocks(self, headers, params=None):
        return self._request("GET", "/event-blocks", headers=headers, params=params)

    def get_event_block(self, block_id, headers):
        return self._request("GET", f"/event-blocks/{block_id}", headers=headers)

    def list_block_appointments(self, block_id, headers, params=None):
        return self._request("GET", f"/event-blocks/{block_id}/appointments",
                             headers=headers, params=params)

    def deposit_event_block(self, block_id, payload, headers):
        return self._request("POST", f"/event-blocks/{block_id}/deposit", payload, headers)

    def confirm_event_block(self, block_id, payload, headers):
        return self._request("POST", f"/event-blocks/{block_id}/confirm", payload, headers)

    def reopen_event_block(self, block_id, payload, headers):
        return self._request("POST", f"/event-blocks/{block_id}/reopen", payload, headers)

    def close_event_block(self, block_id, payload, headers):
        return self._request("POST", f"/event-blocks/{block_id}/close", payload, headers)

    def cancel_event_block(self, block_id, payload, headers):
        return self._request("POST", f"/event-blocks/{block_id}/cancel", payload, headers)

    # ─── Appointment ──────────────────────────────────────────────────────────
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def attach_add_on(self, appointment_id, payload, headers):
        return self._request("POST", f"/appointments/{appointment_id}/add-ons",
                             payload, headers)

    def list_appointment_add_ons(self, appointment_id, headers, params=None):
        return self._request("GET", f"/appointments/{appointment_id}/add-ons",
                             headers=headers, params=params)

    def list_all_appointment_add_ons(self, headers, params=None):
        return self._request("GET", "/appointment-add-ons", headers=headers, params=params)

    def get_appointment_add_on(self, attachment_id, headers):
        return self._request("GET", f"/appointment-add-ons/{attachment_id}", headers=headers)

    def check_in_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/appointments/{appointment_id}/check-in",
                             payload, headers)

    def start_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/start",
                             {}, headers)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/complete",
                             {}, headers)

    def no_show_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/no-show",
                             {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/cancel",
                             {}, headers)

    def settle_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/appointments/{appointment_id}/settle",
                             payload, headers)

    # ─── Product ──────────────────────────────────────────────────────────────
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def restock_product(self, product_id, payload, headers):
        return self._request("POST", f"/products/{product_id}/restock", payload, headers)

    # ─── RetailSale ───────────────────────────────────────────────────────────
    def create_retail_sale(self, payload, headers):
        return self._request("POST", "/retail-sales", payload, headers)

    def list_retail_sales(self, headers, params=None):
        return self._request("GET", "/retail-sales", headers=headers, params=params)

    def get_retail_sale(self, sale_id, headers):
        return self._request("GET", f"/retail-sales/{sale_id}", headers=headers)

    def void_retail_sale(self, sale_id, headers):
        return self._request("POST", f"/retail-sales/{sale_id}/void", {}, headers)

    # ─── PackagePurchase ──────────────────────────────────────────────────────
    def create_package_purchase(self, payload, headers):
        return self._request("POST", "/package-purchases", payload, headers)

    def list_package_purchases(self, headers, params=None):
        return self._request("GET", "/package-purchases", headers=headers, params=params)

    def get_package_purchase(self, package_id, headers):
        return self._request("GET", f"/package-purchases/{package_id}", headers=headers)

    def refund_package_purchase(self, package_id, payload, headers):
        return self._request("POST", f"/package-purchases/{package_id}/refund",
                             payload, headers)


api_client = ApiClient()
