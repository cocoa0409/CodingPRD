"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Boutique ───────────────────────────────────────────────────────
    def create_boutique(self, payload, headers):
        return self._request("POST", "/boutiques", payload, headers)

    def get_boutique(self, boutique_id, headers):
        return self._request("GET", f"/boutiques/{boutique_id}", headers=headers)

    def list_boutiques(self, headers, params=None):
        return self._request("GET", "/boutiques", headers=headers, params=params)

    def advance_clock(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)

    # ─── Customer ───────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_tier_projection(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}/tier-projection", headers=headers)

    def grant_store_credit(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/store-credit-grants", payload, headers)

    # ─── Style + SkuVariant ─────────────────────────────────────────────
    def create_style(self, payload, headers):
        return self._request("POST", "/styles", payload, headers)

    def get_style(self, style_id, headers):
        return self._request("GET", f"/styles/{style_id}", headers=headers)

    def list_styles(self, headers, params=None):
        return self._request("GET", "/styles", headers=headers, params=params)

    def create_sku_variant(self, style_id, payload, headers):
        return self._request("POST", f"/styles/{style_id}/sku-variants", payload, headers)

    def list_sku_variants(self, style_id, headers, params=None):
        return self._request("GET", f"/styles/{style_id}/sku-variants", headers=headers, params=params)

    def get_sku_variant(self, sku_variant_id, headers):
        return self._request("GET", f"/sku-variants/{sku_variant_id}", headers=headers)

    def restock_sku_variant(self, sku_variant_id, payload, headers):
        return self._request("POST", f"/sku-variants/{sku_variant_id}/restock", payload, headers)

    # ─── MarkdownSchedule ───────────────────────────────────────────────
    def create_markdown_schedule(self, payload, headers):
        return self._request("POST", "/markdown-schedules", payload, headers)

    def get_markdown_schedule(self, schedule_id, headers):
        return self._request("GET", f"/markdown-schedules/{schedule_id}", headers=headers)

    def list_markdown_schedules(self, headers, params=None):
        return self._request("GET", "/markdown-schedules", headers=headers, params=params)

    def schedule_markdown(self, schedule_id, headers):
        return self._request("POST", f"/markdown-schedules/{schedule_id}/schedule", {}, headers)

    def unschedule_markdown(self, schedule_id, headers):
        return self._request("POST", f"/markdown-schedules/{schedule_id}/unschedule", {}, headers)

    def activate_markdown(self, schedule_id, headers):
        return self._request("POST", f"/markdown-schedules/{schedule_id}/activate", {}, headers)

    def end_markdown(self, schedule_id, headers):
        return self._request("POST", f"/markdown-schedules/{schedule_id}/end", {}, headers)

    # ─── FittingRoom + FittingRoomHold ──────────────────────────────────
    def create_fitting_room(self, payload, headers):
        return self._request("POST", "/fitting-rooms", payload, headers)

    def get_fitting_room(self, room_id, headers):
        return self._request("GET", f"/fitting-rooms/{room_id}", headers=headers)

    def list_fitting_rooms(self, headers, params=None):
        return self._request("GET", "/fitting-rooms", headers=headers, params=params)

    def create_hold(self, payload, headers):
        return self._request("POST", "/fitting-room-holds", payload, headers)

    def get_hold(self, hold_id, headers):
        return self._request("GET", f"/fitting-room-holds/{hold_id}", headers=headers)

    def list_room_holds(self, room_id, headers, params=None):
        return self._request("GET", f"/fitting-rooms/{room_id}/holds", headers=headers, params=params)

    def list_holds(self, headers, params=None):
        return self._request("GET", "/fitting-room-holds", headers=headers, params=params)

    def extend_hold(self, hold_id, payload, headers):
        return self._request("POST", f"/fitting-room-holds/{hold_id}/extend", payload, headers)

    def convert_hold(self, hold_id, payload, headers):
        return self._request("POST", f"/fitting-room-holds/{hold_id}/convert", payload, headers)

    def release_hold(self, hold_id, headers):
        return self._request("POST", f"/fitting-room-holds/{hold_id}/release", {}, headers)

    # ─── Stylist + StylingAppointment ───────────────────────────────────
    def create_stylist(self, payload, headers):
        return self._request("POST", "/stylists", payload, headers)

    def get_stylist(self, stylist_id, headers):
        return self._request("GET", f"/stylists/{stylist_id}", headers=headers)

    def list_stylists(self, headers, params=None):
        return self._request("GET", "/stylists", headers=headers, params=params)

    def set_stylist_status(self, stylist_id, payload, headers):
        return self._request("POST", f"/stylists/{stylist_id}/status", payload, headers)

    def create_appointment(self, payload, headers):
        return self._request("POST", "/styling-appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/styling-appointments/{appointment_id}", headers=headers)

    def list_stylist_appointments(self, stylist_id, headers, params=None):
        return self._request("GET", f"/stylists/{stylist_id}/appointments", headers=headers, params=params)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/styling-appointments", headers=headers, params=params)

    def confirm_appointment(self, appointment_id, headers):
        return self._request("POST", f"/styling-appointments/{appointment_id}/confirm", {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/styling-appointments/{appointment_id}/cancel", {}, headers)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"/styling-appointments/{appointment_id}/complete", {}, headers)

    def no_show_appointment(self, appointment_id, headers):
        return self._request("POST", f"/styling-appointments/{appointment_id}/no-show", {}, headers)

    # ─── SalesOrder + OrderLine ─────────────────────────────────────────
    def create_sales_order(self, payload, headers):
        return self._request("POST", "/sales-orders", payload, headers)

    def get_sales_order(self, order_id, headers):
        return self._request("GET", f"/sales-orders/{order_id}", headers=headers)

    def list_sales_orders(self, headers, params=None):
        return self._request("GET", "/sales-orders", headers=headers, params=params)

    def create_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/sales-orders/{order_id}/lines", payload, headers)

    def list_order_lines_of_order(self, order_id, headers, params=None):
        return self._request("GET", f"/sales-orders/{order_id}/lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def authorize_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/authorize", {}, headers)

    def capture_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/sales-orders/{order_id}/capture", payload or {}, headers)

    def complete_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/complete", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/cancel", {}, headers)

    # ─── ReturnRequest ──────────────────────────────────────────────────
    def create_return(self, payload, headers):
        return self._request("POST", "/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def list_order_returns(self, order_id, headers, params=None):
        return self._request("GET", f"/sales-orders/{order_id}/returns", headers=headers, params=params)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/returns", headers=headers, params=params)

    def approve_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/approve", {}, headers)

    def reject_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/reject", {}, headers)

    def void_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/void", {}, headers)

    # ─── SpecialOrder ───────────────────────────────────────────────────
    def create_special_order(self, payload, headers):
        return self._request("POST", "/special-orders", payload, headers)

    def get_special_order(self, special_order_id, headers):
        return self._request("GET", f"/special-orders/{special_order_id}", headers=headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/special-orders", headers=headers, params=params)

    def source_special_order(self, special_order_id, headers):
        return self._request("POST", f"/special-orders/{special_order_id}/source", {}, headers)

    def ship_special_order(self, special_order_id, headers):
        return self._request("POST", f"/special-orders/{special_order_id}/ship", {}, headers)

    def deliver_special_order(self, special_order_id, headers):
        return self._request("POST", f"/special-orders/{special_order_id}/deliver", {}, headers)

    def cancel_special_order(self, special_order_id, headers):
        return self._request("POST", f"/special-orders/{special_order_id}/cancel", {}, headers)

    # ─── Lookbook ───────────────────────────────────────────────────────
    def create_lookbook(self, payload, headers):
        return self._request("POST", "/lookbooks", payload, headers)

    def get_lookbook(self, lookbook_id, headers):
        return self._request("GET", f"/lookbooks/{lookbook_id}", headers=headers)

    def list_lookbooks(self, headers, params=None):
        return self._request("GET", "/lookbooks", headers=headers, params=params)

    def patch_lookbook(self, lookbook_id, payload, headers):
        return self._request("PATCH", f"/lookbooks/{lookbook_id}", payload, headers)

    def publish_lookbook(self, lookbook_id, headers):
        return self._request("POST", f"/lookbooks/{lookbook_id}/publish", {}, headers)


api_client = ApiClient()
