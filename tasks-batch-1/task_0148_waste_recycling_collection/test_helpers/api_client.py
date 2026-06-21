"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── ServiceAccount ──────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def activate_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/activate", {}, headers)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/suspend", {}, headers)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/close", {}, headers)

    # ─── Cart ────────────────────────────────────────
    def create_cart(self, payload, headers):
        return self._request("POST", "/carts", payload, headers)

    def get_cart(self, cart_id, headers):
        return self._request("GET", f"/carts/{cart_id}", headers=headers)

    def list_carts(self, headers, params=None):
        return self._request("GET", "/carts", headers=headers, params=params)

    def activate_cart(self, cart_id, headers):
        return self._request("POST", f"/carts/{cart_id}/activate", {}, headers)

    def hold_cart(self, cart_id, headers):
        return self._request("POST", f"/carts/{cart_id}/hold", {}, headers)

    def retire_cart(self, cart_id, headers):
        return self._request("POST", f"/carts/{cart_id}/retire", {}, headers)

    # ─── ServicePlan ─────────────────────────────────
    def create_service_plan(self, payload, headers):
        return self._request("POST", "/service-plans", payload, headers)

    def get_service_plan(self, plan_id, headers):
        return self._request("GET", f"/service-plans/{plan_id}", headers=headers)

    def list_service_plans(self, headers, params=None):
        return self._request("GET", "/service-plans", headers=headers, params=params)

    def activate_service_plan(self, plan_id, headers):
        return self._request("POST", f"/service-plans/{plan_id}/activate", {}, headers)

    def pause_service_plan(self, plan_id, headers):
        return self._request("POST", f"/service-plans/{plan_id}/pause", {}, headers)

    def terminate_service_plan(self, plan_id, headers):
        return self._request("POST", f"/service-plans/{plan_id}/terminate", {}, headers)

    # ─── Route ───────────────────────────────────────
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    def patch_route(self, route_id, payload, headers):
        return self._request("PATCH", f"/routes/{route_id}", payload, headers)

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/dispatch", {}, headers)

    def start_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/start", {}, headers)

    def complete_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/complete", {}, headers)

    def cancel_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/cancel", {}, headers)

    # ─── Stop (nested under Route for create + list) ──
    def create_stop(self, route_id, payload, headers):
        return self._request("POST", f"/routes/{route_id}/stops", payload, headers)

    def list_route_stops(self, route_id, headers, params=None):
        return self._request("GET", f"/routes/{route_id}/stops", headers=headers, params=params)

    def get_stop(self, stop_id, headers):
        return self._request("GET", f"/stops/{stop_id}", headers=headers)

    def list_stops(self, headers, params=None):
        return self._request("GET", "/stops", headers=headers, params=params)

    # ─── Pickup (nested under Stop for create) ────────
    def create_pickup(self, stop_id, payload, headers):
        return self._request("POST", f"/stops/{stop_id}/pickups", payload, headers)

    def get_pickup(self, pickup_id, headers):
        return self._request("GET", f"/pickups/{pickup_id}", headers=headers)

    def list_pickups(self, headers, params=None):
        return self._request("GET", "/pickups", headers=headers, params=params)

    def complete_pickup(self, pickup_id, payload, headers):
        return self._request("POST", f"/pickups/{pickup_id}/complete", payload, headers)

    def miss_pickup(self, pickup_id, payload, headers):
        return self._request("POST", f"/pickups/{pickup_id}/miss", payload, headers)

    def cancel_pickup(self, pickup_id, headers):
        return self._request("POST", f"/pickups/{pickup_id}/cancel", {}, headers)

    def create_weight_ticket(self, pickup_id, payload, headers):
        return self._request("POST", f"/pickups/{pickup_id}/weight-ticket", payload, headers)

    def list_weight_tickets(self, pickup_id, headers, params=None):
        return self._request("GET", f"/pickups/{pickup_id}/weight-ticket", headers=headers, params=params)

    # ─── ContaminationTag ─────────────────────────────
    def create_contamination_tag(self, pickup_id, payload, headers):
        return self._request("POST", f"/pickups/{pickup_id}/contamination-tags", payload, headers)

    def list_contamination_tags(self, pickup_id, headers, params=None):
        return self._request("GET", f"/pickups/{pickup_id}/contamination-tags", headers=headers, params=params)

    def get_contamination_tag(self, tag_id, headers):
        return self._request("GET", f"/contamination-tags/{tag_id}", headers=headers)

    def clear_contamination_tag(self, tag_id, headers):
        return self._request("POST", f"/contamination-tags/{tag_id}/clear", {}, headers)

    # ─── Invoice ──────────────────────────────────────
    def create_invoice(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", {}, headers)

    def dispute_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/dispute", {}, headers)

    def resolve_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/resolve", {}, headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)

    # ─── SpecialPickup ────────────────────────────────
    def create_special_pickup(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/special-pickups", payload, headers)

    def get_special_pickup(self, sp_id, headers):
        return self._request("GET", f"/special-pickups/{sp_id}", headers=headers)

    def list_special_pickups(self, headers, params=None):
        return self._request("GET", "/special-pickups", headers=headers, params=params)

    def approve_special_pickup(self, sp_id, headers):
        return self._request("POST", f"/special-pickups/{sp_id}/approve", {}, headers)

    def reject_special_pickup(self, sp_id, headers):
        return self._request("POST", f"/special-pickups/{sp_id}/reject", {}, headers)

    def schedule_special_pickup(self, sp_id, headers):
        return self._request("POST", f"/special-pickups/{sp_id}/schedule", {}, headers)

    def complete_special_pickup(self, sp_id, headers):
        return self._request("POST", f"/special-pickups/{sp_id}/complete", {}, headers)

    def cancel_special_pickup(self, sp_id, headers):
        return self._request("POST", f"/special-pickups/{sp_id}/cancel", {}, headers)

    # ─── MissedPickupCredit ───────────────────────────
    def get_credit(self, credit_id, headers):
        return self._request("GET", f"/missed-pickup-credits/{credit_id}", headers=headers)

    def list_credits(self, headers, params=None):
        return self._request("GET", "/missed-pickup-credits", headers=headers, params=params)

    def void_credit(self, credit_id, headers):
        return self._request("POST", f"/missed-pickup-credits/{credit_id}/void", {}, headers)

    # ─── DiversionPeriod ──────────────────────────────
    def create_diversion_period(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/diversion-periods", payload, headers)

    def get_diversion_period(self, dp_id, headers):
        return self._request("GET", f"/diversion-periods/{dp_id}", headers=headers)

    def list_diversion_periods(self, headers, params=None):
        return self._request("GET", "/diversion-periods", headers=headers, params=params)

    def finalize_diversion_period(self, dp_id, headers):
        return self._request("POST", f"/diversion-periods/{dp_id}/finalize", {}, headers)


api_client = ApiClient()
