"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Sites ---
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def suspend_site(self, site_id, headers):
        return self._request("POST", f"/sites/{site_id}/suspend", {}, headers)

    def reinstate_site(self, site_id, headers):
        return self._request("POST", f"/sites/{site_id}/reinstate", {}, headers)

    def decommission_site(self, site_id, headers):
        return self._request("POST", f"/sites/{site_id}/decommission", {}, headers)

    # --- Growers ---
    def create_grower(self, payload, headers):
        return self._request("POST", "/growers", payload, headers)

    def list_growers(self, headers, params=None):
        return self._request("GET", "/growers", headers=headers, params=params)

    def get_grower(self, grower_id, headers):
        return self._request("GET", f"/growers/{grower_id}", headers=headers)

    def suspend_grower(self, grower_id, headers):
        return self._request("POST", f"/growers/{grower_id}/suspend", {}, headers)

    def reinstate_grower(self, grower_id, headers):
        return self._request("POST", f"/growers/{grower_id}/reinstate", {}, headers)

    def terminate_grower(self, grower_id, headers):
        return self._request("POST", f"/growers/{grower_id}/terminate", {}, headers)

    # --- Contracts ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/activate", {}, headers)

    def terminate_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/terminate", {}, headers)

    def expire_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/expire", {}, headers)

    # --- Barns ---
    def create_barn(self, payload, headers):
        return self._request("POST", "/barns", payload, headers)

    def list_barns(self, headers, params=None):
        return self._request("GET", "/barns", headers=headers, params=params)

    def get_barn(self, barn_id, headers):
        return self._request("GET", f"/barns/{barn_id}", headers=headers)

    def release_barn(self, barn_id, headers):
        return self._request("POST", f"/barns/{barn_id}/release", {}, headers)

    def mark_barn_out_of_service(self, barn_id, headers):
        return self._request("POST", f"/barns/{barn_id}/mark-out-of-service", {}, headers)

    def return_barn_to_service(self, barn_id, headers):
        return self._request("POST", f"/barns/{barn_id}/return-to-service", {}, headers)

    # --- Pig groups ---
    def create_pig_group(self, payload, headers):
        return self._request("POST", "/pig-groups", payload, headers)

    def list_pig_groups(self, headers, params=None):
        return self._request("GET", "/pig-groups", headers=headers, params=params)

    def get_pig_group(self, group_id, headers):
        return self._request("GET", f"/pig-groups/{group_id}", headers=headers)

    def confirm_placement(self, group_id, payload, headers):
        return self._request(
            "POST", f"/pig-groups/{group_id}/confirm-placement", payload, headers
        )

    def advance_phase(self, group_id, headers):
        return self._request("POST", f"/pig-groups/{group_id}/advance-phase", {}, headers)

    def cancel_pig_group(self, group_id, headers):
        return self._request("POST", f"/pig-groups/{group_id}/cancel", {}, headers)

    def close_out_pig_group(self, group_id, headers):
        return self._request("POST", f"/pig-groups/{group_id}/close-out", {}, headers)

    def get_settlement_preview(self, group_id, headers):
        return self._request(
            "GET", f"/pig-groups/{group_id}/settlement-preview", headers=headers
        )

    # --- Mortality reports (event sub-resource) ---
    def create_mortality_report(self, group_id, payload, headers):
        return self._request(
            "POST", f"/pig-groups/{group_id}/mortality-reports", payload, headers
        )

    def list_mortality_reports(self, group_id, headers, params=None):
        return self._request(
            "GET", f"/pig-groups/{group_id}/mortality-reports",
            headers=headers, params=params,
        )

    # --- Feed orders ---
    def create_feed_order(self, payload, headers):
        return self._request("POST", "/feed-orders", payload, headers)

    def list_feed_orders(self, headers, params=None):
        return self._request("GET", "/feed-orders", headers=headers, params=params)

    def get_feed_order(self, order_id, headers):
        return self._request("GET", f"/feed-orders/{order_id}", headers=headers)

    def schedule_feed_order(self, order_id, payload, headers):
        return self._request("POST", f"/feed-orders/{order_id}/schedule", payload, headers)

    def deliver_feed_order(self, order_id, payload, headers):
        return self._request("POST", f"/feed-orders/{order_id}/deliver", payload, headers)

    def cancel_feed_order(self, order_id, headers):
        return self._request("POST", f"/feed-orders/{order_id}/cancel", {}, headers)

    # --- Packer slots ---
    def create_packer_slot(self, payload, headers):
        return self._request("POST", "/packer-slots", payload, headers)

    def list_packer_slots(self, headers, params=None):
        return self._request("GET", "/packer-slots", headers=headers, params=params)

    def get_packer_slot(self, slot_id, headers):
        return self._request("GET", f"/packer-slots/{slot_id}", headers=headers)

    def close_packer_slot(self, slot_id, headers):
        return self._request("POST", f"/packer-slots/{slot_id}/close", {}, headers)

    # --- Market loads ---
    def create_market_load(self, payload, headers):
        return self._request("POST", "/market-loads", payload, headers)

    def list_market_loads(self, headers, params=None):
        return self._request("GET", "/market-loads", headers=headers, params=params)

    def get_market_load(self, load_id, headers):
        return self._request("GET", f"/market-loads/{load_id}", headers=headers)

    def dispatch_market_load(self, load_id, payload, headers):
        return self._request("POST", f"/market-loads/{load_id}/dispatch", payload, headers)

    def deliver_market_load(self, load_id, payload, headers):
        return self._request("POST", f"/market-loads/{load_id}/deliver", payload, headers)

    def cancel_market_load(self, load_id, headers):
        return self._request("POST", f"/market-loads/{load_id}/cancel", {}, headers)

    # --- Truck washes ---
    def create_truck_wash(self, payload, headers):
        return self._request("POST", "/truck-washes", payload, headers)

    def list_truck_washes(self, headers, params=None):
        return self._request("GET", "/truck-washes", headers=headers, params=params)

    def get_truck_wash(self, wash_id, headers):
        return self._request("GET", f"/truck-washes/{wash_id}", headers=headers)

    def verify_truck_wash(self, wash_id, headers):
        return self._request("POST", f"/truck-washes/{wash_id}/verify", {}, headers)

    def reject_truck_wash(self, wash_id, headers):
        return self._request("POST", f"/truck-washes/{wash_id}/reject", {}, headers)

    # --- Barn washes ---
    def create_barn_wash(self, payload, headers):
        return self._request("POST", "/barn-washes", payload, headers)

    def list_barn_washes(self, headers, params=None):
        return self._request("GET", "/barn-washes", headers=headers, params=params)

    def get_barn_wash(self, wash_id, headers):
        return self._request("GET", f"/barn-washes/{wash_id}", headers=headers)

    def verify_barn_wash(self, wash_id, headers):
        return self._request("POST", f"/barn-washes/{wash_id}/verify", {}, headers)

    def reject_barn_wash(self, wash_id, headers):
        return self._request("POST", f"/barn-washes/{wash_id}/reject", {}, headers)

    # --- Manure plans ---
    def create_manure_plan(self, payload, headers):
        return self._request("POST", "/manure-plans", payload, headers)

    def list_manure_plans(self, headers, params=None):
        return self._request("GET", "/manure-plans", headers=headers, params=params)

    def get_manure_plan(self, plan_id, headers):
        return self._request("GET", f"/manure-plans/{plan_id}", headers=headers)

    def submit_manure_plan(self, plan_id, headers):
        return self._request("POST", f"/manure-plans/{plan_id}/submit", {}, headers)

    def approve_manure_plan(self, plan_id, headers):
        return self._request("POST", f"/manure-plans/{plan_id}/approve", {}, headers)

    def reject_manure_plan(self, plan_id, headers):
        return self._request("POST", f"/manure-plans/{plan_id}/reject", {}, headers)

    def revise_manure_plan(self, plan_id, headers):
        return self._request("POST", f"/manure-plans/{plan_id}/revise", {}, headers)

    # --- Manure applications ---
    def create_manure_application(self, payload, headers):
        return self._request("POST", "/manure-applications", payload, headers)

    def list_manure_applications(self, headers, params=None):
        return self._request("GET", "/manure-applications", headers=headers, params=params)

    def get_manure_application(self, application_id, headers):
        return self._request(
            "GET", f"/manure-applications/{application_id}", headers=headers
        )

    def confirm_manure_application(self, application_id, headers):
        return self._request(
            "POST", f"/manure-applications/{application_id}/confirm", {}, headers
        )

    def void_manure_application(self, application_id, headers):
        return self._request(
            "POST", f"/manure-applications/{application_id}/void", {}, headers
        )

    # --- Maintenance tickets ---
    def create_maintenance_ticket(self, payload, headers):
        return self._request("POST", "/maintenance-tickets", payload, headers)

    def list_maintenance_tickets(self, headers, params=None):
        return self._request(
            "GET", "/maintenance-tickets", headers=headers, params=params
        )

    def get_maintenance_ticket(self, ticket_id, headers):
        return self._request("GET", f"/maintenance-tickets/{ticket_id}", headers=headers)

    def quote_maintenance_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/maintenance-tickets/{ticket_id}/quote", payload, headers
        )

    def approve_maintenance_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/maintenance-tickets/{ticket_id}/approve", {}, headers
        )

    def start_work_maintenance_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/maintenance-tickets/{ticket_id}/start-work", {}, headers
        )

    def complete_maintenance_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/maintenance-tickets/{ticket_id}/complete", {}, headers
        )

    def reject_maintenance_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/maintenance-tickets/{ticket_id}/reject", {}, headers
        )

    def cancel_maintenance_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/maintenance-tickets/{ticket_id}/cancel", {}, headers
        )

    # --- Settlements ---
    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def dispute_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"/settlements/{settlement_id}/dispute", payload, headers
        )

    def refinalize_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"/settlements/{settlement_id}/refinalize", payload, headers
        )

    def approve_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/approve", {}, headers)

    def pay_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/pay", {}, headers)


api_client = ApiClient()
