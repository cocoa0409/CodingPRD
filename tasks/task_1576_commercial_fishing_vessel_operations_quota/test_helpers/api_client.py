"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- vessels ---
    def create_vessel(self, payload, headers):
        return self._request("POST", "/vessels", payload, headers)

    def list_vessels(self, headers, params=None):
        return self._request("GET", "/vessels", headers=headers, params=params)

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"/vessels/{vessel_id}", headers=headers)

    def activate_vessel(self, vessel_id, headers):
        return self._request("POST", f"/vessels/{vessel_id}/activate", headers=headers)

    def reinstate_vessel(self, vessel_id, headers):
        return self._request("POST", f"/vessels/{vessel_id}/reinstate", headers=headers)

    def decommission_vessel(self, vessel_id, headers):
        return self._request("POST", f"/vessels/{vessel_id}/decommission", headers=headers)

    # --- permits ---
    def create_permit(self, vessel_id, payload, headers):
        return self._request("POST", f"/vessels/{vessel_id}/permits", payload, headers)

    def list_permits(self, vessel_id, headers, params=None):
        return self._request("GET", f"/vessels/{vessel_id}/permits", headers=headers, params=params)

    def revoke_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/revoke", headers=headers)

    # --- quota share holdings ---
    def create_quota_holding(self, vessel_id, payload, headers):
        return self._request("POST", f"/vessels/{vessel_id}/quota-holdings", payload, headers)

    def list_quota_holdings(self, vessel_id, headers, params=None):
        return self._request("GET", f"/vessels/{vessel_id}/quota-holdings", headers=headers, params=params)

    def get_quota_holding(self, holding_id, headers):
        return self._request("GET", f"/quota-holdings/{holding_id}", headers=headers)

    def get_quota_holding_availability(self, holding_id, headers):
        return self._request("GET", f"/quota-holdings/{holding_id}/availability", headers=headers)

    # --- season openings ---
    def create_season_opening(self, payload, headers):
        return self._request("POST", "/season-openings", payload, headers)

    def list_season_openings(self, headers, params=None):
        return self._request("GET", "/season-openings", headers=headers, params=params)

    def get_season_opening(self, opening_id, headers):
        return self._request("GET", f"/season-openings/{opening_id}", headers=headers)

    def close_opening_early(self, opening_id, headers):
        return self._request("POST", f"/season-openings/{opening_id}/close-early", headers=headers)

    # --- fishing trips ---
    def create_fishing_trip(self, payload, headers):
        return self._request("POST", "/fishing-trips", payload, headers)

    def list_fishing_trips(self, headers, params=None):
        return self._request("GET", "/fishing-trips", headers=headers, params=params)

    def get_fishing_trip(self, trip_id, headers):
        return self._request("GET", f"/fishing-trips/{trip_id}", headers=headers)

    def patch_fishing_trip(self, trip_id, payload, headers):
        return self._request("PATCH", f"/fishing-trips/{trip_id}", payload, headers)

    def depart_trip(self, trip_id, headers):
        return self._request("POST", f"/fishing-trips/{trip_id}/depart", headers=headers)

    def return_trip(self, trip_id, headers):
        return self._request("POST", f"/fishing-trips/{trip_id}/return", headers=headers)

    def cancel_trip(self, trip_id, headers):
        return self._request("POST", f"/fishing-trips/{trip_id}/cancel", headers=headers)

    # --- catch reports ---
    def create_catch_report(self, trip_id, payload, headers):
        return self._request("POST", f"/fishing-trips/{trip_id}/catch-reports", payload, headers)

    def list_catch_reports(self, trip_id, headers, params=None):
        return self._request("GET", f"/fishing-trips/{trip_id}/catch-reports", headers=headers, params=params)

    # --- landing declarations ---
    def create_landing_declaration(self, trip_id, payload, headers):
        return self._request("POST", f"/fishing-trips/{trip_id}/landing-declarations", payload, headers)

    def list_landing_declarations(self, trip_id, headers, params=None):
        return self._request("GET", f"/fishing-trips/{trip_id}/landing-declarations", headers=headers, params=params)

    def get_landing_declaration(self, declaration_id, headers):
        return self._request("GET", f"/landing-declarations/{declaration_id}", headers=headers)

    def submit_landing_declaration(self, declaration_id, headers):
        return self._request("POST", f"/landing-declarations/{declaration_id}/submit", headers=headers)

    def verify_landing_declaration(self, declaration_id, headers):
        return self._request("POST", f"/landing-declarations/{declaration_id}/verify", headers=headers)

    def amend_landing_declaration(self, declaration_id, payload, headers):
        return self._request("POST", f"/landing-declarations/{declaration_id}/amend", payload, headers)

    def finalize_landing_declaration(self, declaration_id, headers):
        return self._request("POST", f"/landing-declarations/{declaration_id}/finalize", headers=headers)

    # --- quota transfers ---
    def create_quota_transfer(self, payload, headers):
        return self._request("POST", "/quota-transfers", payload, headers)

    def list_quota_transfers(self, headers, params=None):
        return self._request("GET", "/quota-transfers", headers=headers, params=params)

    def get_quota_transfer(self, transfer_id, headers):
        return self._request("GET", f"/quota-transfers/{transfer_id}", headers=headers)

    def counter_quota_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"/quota-transfers/{transfer_id}/counter", payload, headers)

    def accept_quota_transfer(self, transfer_id, headers):
        return self._request("POST", f"/quota-transfers/{transfer_id}/accept", headers=headers)

    def decline_quota_transfer(self, transfer_id, headers):
        return self._request("POST", f"/quota-transfers/{transfer_id}/decline", headers=headers)

    def withdraw_quota_transfer(self, transfer_id, headers):
        return self._request("POST", f"/quota-transfers/{transfer_id}/withdraw", headers=headers)

    def settle_quota_transfer(self, transfer_id, headers):
        return self._request("POST", f"/quota-transfers/{transfer_id}/settle", headers=headers)

    # --- observer registry ---
    def create_observer(self, payload, headers):
        return self._request("POST", "/observers", payload, headers)

    def list_observers(self, headers, params=None):
        return self._request("GET", "/observers", headers=headers, params=params)

    def get_observer(self, observer_id, headers):
        return self._request("GET", f"/observers/{observer_id}", headers=headers)

    # --- observer assignments ---
    def list_observer_assignments(self, headers, params=None):
        return self._request("GET", "/observer-assignments", headers=headers, params=params)

    def get_observer_assignment(self, assignment_id, headers):
        return self._request("GET", f"/observer-assignments/{assignment_id}", headers=headers)

    def assign_observer(self, assignment_id, payload, headers):
        return self._request("POST", f"/observer-assignments/{assignment_id}/assign", payload, headers)

    def confirm_observer_assignment(self, assignment_id, headers):
        return self._request("POST", f"/observer-assignments/{assignment_id}/confirm", headers=headers)

    def debrief_observer_assignment(self, assignment_id, headers):
        return self._request("POST", f"/observer-assignments/{assignment_id}/debrief", headers=headers)

    def release_observer_assignment(self, assignment_id, headers):
        return self._request("POST", f"/observer-assignments/{assignment_id}/release", headers=headers)

    def waive_observer_assignment(self, assignment_id, headers):
        return self._request("POST", f"/observer-assignments/{assignment_id}/waive", headers=headers)

    # --- crew share contracts ---
    def create_crew_contract(self, vessel_id, payload, headers):
        return self._request("POST", f"/vessels/{vessel_id}/crew-contracts", payload, headers)

    def list_crew_contracts(self, vessel_id, headers, params=None):
        return self._request("GET", f"/vessels/{vessel_id}/crew-contracts", headers=headers, params=params)

    def deactivate_crew_contract(self, contract_id, headers):
        return self._request("POST", f"/crew-contracts/{contract_id}/deactivate", headers=headers)

    # --- expense records ---
    def create_expense(self, trip_id, payload, headers):
        return self._request("POST", f"/fishing-trips/{trip_id}/expenses", payload, headers)

    def list_expenses(self, trip_id, headers, params=None):
        return self._request("GET", f"/fishing-trips/{trip_id}/expenses", headers=headers, params=params)

    def verify_expense(self, expense_id, headers):
        return self._request("POST", f"/expenses/{expense_id}/verify", headers=headers)

    def reject_expense(self, expense_id, headers):
        return self._request("POST", f"/expenses/{expense_id}/reject", headers=headers)

    # --- trip settlements ---
    def create_trip_settlement(self, trip_id, payload, headers):
        return self._request("POST", f"/fishing-trips/{trip_id}/settlement", payload, headers)

    def get_trip_settlement_of_trip(self, trip_id, headers):
        return self._request("GET", f"/fishing-trips/{trip_id}/settlement", headers=headers)

    def get_trip_settlement(self, settlement_id, headers):
        return self._request("GET", f"/trip-settlements/{settlement_id}", headers=headers)

    def calculate_settlement(self, settlement_id, headers):
        return self._request("POST", f"/trip-settlements/{settlement_id}/calculate", headers=headers)

    def recalculate_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/trip-settlements/{settlement_id}/recalculate", payload, headers)

    def approve_settlement(self, settlement_id, headers):
        return self._request("POST", f"/trip-settlements/{settlement_id}/approve", headers=headers)

    def dispute_settlement(self, settlement_id, headers):
        return self._request("POST", f"/trip-settlements/{settlement_id}/dispute", headers=headers)

    def pay_settlement(self, settlement_id, headers):
        return self._request("POST", f"/trip-settlements/{settlement_id}/pay", headers=headers)

    # --- gear assets / events ---
    def create_gear_asset(self, vessel_id, payload, headers):
        return self._request("POST", f"/vessels/{vessel_id}/gear-assets", payload, headers)

    def list_gear_assets(self, vessel_id, headers, params=None):
        return self._request("GET", f"/vessels/{vessel_id}/gear-assets", headers=headers, params=params)

    def get_gear_asset(self, asset_id, headers):
        return self._request("GET", f"/gear-assets/{asset_id}", headers=headers)

    def create_gear_event(self, asset_id, payload, headers):
        return self._request("POST", f"/gear-assets/{asset_id}/events", payload, headers)

    def list_gear_events(self, asset_id, headers, params=None):
        return self._request("GET", f"/gear-assets/{asset_id}/events", headers=headers, params=params)

    def list_trip_gear_events(self, trip_id, headers, params=None):
        return self._request("GET", f"/fishing-trips/{trip_id}/gear-events", headers=headers, params=params)

    # --- VMS pings ---
    def create_vms_ping(self, vessel_id, payload, headers):
        return self._request("POST", f"/vessels/{vessel_id}/vms-pings", payload, headers)

    def list_vms_pings(self, vessel_id, headers, params=None):
        return self._request("GET", f"/vessels/{vessel_id}/vms-pings", headers=headers, params=params)

    # --- compliance violations ---
    def create_violation(self, payload, headers):
        return self._request("POST", "/violations", payload, headers)

    def list_violations(self, headers, params=None):
        return self._request("GET", "/violations", headers=headers, params=params)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/violations/{violation_id}", headers=headers)

    def adjudicate_violation(self, violation_id, headers):
        return self._request("POST", f"/violations/{violation_id}/adjudicate", headers=headers)

    def dismiss_violation(self, violation_id, headers):
        return self._request("POST", f"/violations/{violation_id}/dismiss", headers=headers)

    def appeal_violation(self, violation_id, headers):
        return self._request("POST", f"/violations/{violation_id}/appeal", headers=headers)

    def reverse_violation(self, violation_id, headers):
        return self._request("POST", f"/violations/{violation_id}/reverse", headers=headers)

    def uphold_violation(self, violation_id, headers):
        return self._request("POST", f"/violations/{violation_id}/uphold", headers=headers)


api_client = ApiClient()
