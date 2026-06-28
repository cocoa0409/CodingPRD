"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- PricingConfig -------------------------------------------------------
    def create_pricing_config(self, payload, headers):
        return self._request("POST", "/pricing-configs", payload, headers)

    def get_pricing_config(self, config_id, headers):
        return self._request("GET", f"/pricing-configs/{config_id}", headers=headers)

    def activate_pricing_config(self, config_id, headers):
        return self._request("POST", f"/pricing-configs/{config_id}/activate", headers=headers)

    # --- Homeowner -----------------------------------------------------------
    def create_homeowner(self, payload, headers):
        return self._request("POST", "/homeowners", payload, headers)

    # --- Home ----------------------------------------------------------------
    def create_home(self, payload, headers):
        return self._request("POST", "/homes", payload, headers)

    def list_homes(self, headers, params=None):
        return self._request("GET", "/homes", headers=headers, params=params)

    def get_home(self, home_id, headers):
        return self._request("GET", f"/homes/{home_id}", headers=headers)

    # --- HvacSystem ----------------------------------------------------------
    def add_system(self, home_id, payload, headers):
        return self._request("POST", f"/homes/{home_id}/systems", payload, headers)

    def list_systems(self, home_id, headers, params=None):
        return self._request("GET", f"/homes/{home_id}/systems", headers=headers, params=params)

    def decommission_system(self, home_id, system_id, headers):
        return self._request("POST", f"/homes/{home_id}/systems/{system_id}/decommission", headers=headers)

    # --- RecurringPlan -------------------------------------------------------
    def create_recurring_plan(self, home_id, payload, headers):
        return self._request("POST", f"/homes/{home_id}/recurring-plans", payload, headers)

    def list_recurring_plans(self, home_id, headers, params=None):
        return self._request("GET", f"/homes/{home_id}/recurring-plans", headers=headers, params=params)

    def acknowledge_reminder(self, plan_id, headers):
        return self._request("POST", f"/recurring-plans/{plan_id}/acknowledge", headers=headers)

    def refresh_reminder(self, plan_id, headers):
        return self._request("POST", f"/recurring-plans/{plan_id}/refresh-reminder", headers=headers)

    def pause_recurring_plan(self, plan_id, headers):
        return self._request("POST", f"/recurring-plans/{plan_id}/pause", headers=headers)

    def resume_recurring_plan(self, plan_id, headers):
        return self._request("POST", f"/recurring-plans/{plan_id}/resume", headers=headers)

    def cancel_recurring_plan(self, plan_id, headers):
        return self._request("POST", f"/recurring-plans/{plan_id}/cancel", headers=headers)

    # --- CrewMember ----------------------------------------------------------
    def create_crew_member(self, payload, headers):
        return self._request("POST", "/crew-members", payload, headers)

    # --- RoutePlan -----------------------------------------------------------
    def create_route_plan(self, payload, headers):
        return self._request("POST", "/route-plans", payload, headers)

    def list_route_plans(self, headers, params=None):
        return self._request("GET", "/route-plans", headers=headers, params=params)

    def get_route_plan(self, route_id, headers):
        return self._request("GET", f"/route-plans/{route_id}", headers=headers)

    def commit_slot(self, route_id, payload, headers):
        return self._request("POST", f"/route-plans/{route_id}/commit", payload, headers)

    def lock_route_plan(self, route_id, headers):
        return self._request("POST", f"/route-plans/{route_id}/lock", headers=headers)

    def close_route_plan(self, route_id, headers):
        return self._request("POST", f"/route-plans/{route_id}/close", headers=headers)

    # --- WorkOrder -----------------------------------------------------------
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def inspect_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/inspect", payload, headers)

    def quote_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/quote", headers=headers)

    def start_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/start", headers=headers)

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/complete", payload, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", headers=headers)

    def list_inspections(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/inspections", headers=headers, params=params)

    # --- UpsellReferral ------------------------------------------------------
    def list_upsell_referrals(self, headers, params=None):
        return self._request("GET", "/upsell-referrals", headers=headers, params=params)

    def get_upsell_referral(self, referral_id, headers):
        return self._request("GET", f"/upsell-referrals/{referral_id}", headers=headers)

    def decline_referral(self, referral_id, headers):
        return self._request("POST", f"/upsell-referrals/{referral_id}/decline", headers=headers)

    def expire_referral(self, referral_id, headers):
        return self._request("POST", f"/upsell-referrals/{referral_id}/expire", headers=headers)

    # --- CallbackTicket ------------------------------------------------------
    def create_callback_ticket(self, payload, headers):
        return self._request("POST", "/callback-tickets", payload, headers)

    def list_callback_tickets(self, headers, params=None):
        return self._request("GET", "/callback-tickets", headers=headers, params=params)

    def get_callback_ticket(self, ticket_id, headers):
        return self._request("GET", f"/callback-tickets/{ticket_id}", headers=headers)

    def resolve_callback_ticket(self, ticket_id, headers):
        return self._request("POST", f"/callback-tickets/{ticket_id}/resolve", headers=headers)

    def reopen_callback_ticket(self, ticket_id, headers):
        return self._request("POST", f"/callback-tickets/{ticket_id}/reopen", headers=headers)

    # --- Logical clock -------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
