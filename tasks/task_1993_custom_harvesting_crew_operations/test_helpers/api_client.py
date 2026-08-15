"""API client: one method per endpoint declared in PRD section 4."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Custom Harvesting Crew Operations API."""

    # --- Logical clock ---
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/harvest/_clock/set_current_utc", payload, headers)

    # --- HarvestSeason ---
    def create_season(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/harvest/seasons", payload, headers)

    def list_seasons(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/harvest/seasons", headers=headers, params=params)

    def get_season(self, season_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/harvest/seasons/{season_id}", headers=headers)

    def update_season(self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/harvest/seasons/{season_id}", payload, headers)

    def activate_season(self, season_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/harvest/seasons/{season_id}/activate", {}, headers)

    def open_settlement(self, season_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/harvest/seasons/{season_id}/open-settlement", {}, headers)

    def close_season(self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/harvest/seasons/{season_id}/close", payload, headers)

    # --- CustomerContract ---
    def create_contract(self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/harvest/seasons/{season_id}/contracts", payload, headers)

    def list_contracts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/harvest/contracts", headers=headers, params=params)

    def list_season_contracts(self, season_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/harvest/seasons/{season_id}/contracts", headers=headers, params=params)

    def get_contract(self, contract_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/harvest/contracts/{contract_id}", headers=headers)

    def commit_contract(self, contract_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/harvest/contracts/{contract_id}/commit", {}, headers)

    def cancel_contract(self, contract_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/harvest/contracts/{contract_id}/cancel", {}, headers)

    # --- RouteStop ---
    def create_route_stop(self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/harvest/contracts/{contract_id}/route-stops", payload, headers)

    def list_contract_route_stops(self, contract_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/harvest/contracts/{contract_id}/route-stops", headers=headers, params=params)

    def list_route_stops(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/harvest/route-stops", headers=headers, params=params)

    def get_route_stop(self, stop_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/harvest/route-stops/{stop_id}", headers=headers)

    def update_route_stop(self, stop_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/harvest/route-stops/{stop_id}", payload, headers)

    def depart_route_stop(self, stop_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/harvest/route-stops/{stop_id}/depart", {}, headers)

    def start_cutting(self, stop_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/harvest/route-stops/{stop_id}/start-cutting", {}, headers)

    def pause_weather(self, stop_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/harvest/route-stops/{stop_id}/pause-weather", {}, headers)

    def resume_route_stop(self, stop_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/harvest/route-stops/{stop_id}/resume", {}, headers)

    def complete_route_stop(self, stop_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/harvest/route-stops/{stop_id}/complete", {}, headers)

    def skip_route_stop(self, stop_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/harvest/route-stops/{stop_id}/skip", {}, headers)

    # --- Machine ---
    def create_machine(self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/harvest/seasons/{season_id}/machines", payload, headers)

    def list_season_machines(self, season_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/harvest/seasons/{season_id}/machines", headers=headers, params=params)

    def list_machines(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/harvest/machines", headers=headers, params=params)

    def get_machine(self, machine_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/harvest/machines/{machine_id}", headers=headers)

    def report_breakdown(self, machine_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/harvest/machines/{machine_id}/report-breakdown", {}, headers)

    def dispatch_repair(self, machine_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/harvest/machines/{machine_id}/dispatch-repair", {}, headers)

    def return_to_service(self, machine_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/harvest/machines/{machine_id}/return-to-service", {}, headers)

    # --- CrewMember ---
    def create_crew_member(self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/harvest/seasons/{season_id}/crew-members", payload, headers)

    def list_season_crew_members(self, season_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/harvest/seasons/{season_id}/crew-members", headers=headers, params=params)

    def list_crew_members(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/harvest/crew-members", headers=headers, params=params)

    def get_crew_member(self, crew_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/harvest/crew-members/{crew_id}", headers=headers)

    def activate_crew_member(self, crew_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/harvest/crew-members/{crew_id}/activate", {}, headers)

    def release_crew_member(self, crew_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/harvest/crew-members/{crew_id}/release", {}, headers)

    # --- MachineAssignment ---
    def create_machine_assignment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/harvest/machine-assignments", payload, headers)

    def list_machine_assignments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/harvest/machine-assignments", headers=headers, params=params)

    def get_machine_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/harvest/machine-assignments/{assignment_id}", headers=headers)

    def cancel_machine_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/harvest/machine-assignments/{assignment_id}/cancel", {}, headers)

    # --- DeliveryTicket ---
    def create_delivery_ticket(self, stop_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/harvest/route-stops/{stop_id}/delivery-tickets", payload, headers)

    def list_stop_delivery_tickets(self, stop_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/harvest/route-stops/{stop_id}/delivery-tickets", headers=headers, params=params)

    def list_delivery_tickets(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/harvest/delivery-tickets", headers=headers, params=params)

    def get_delivery_ticket(self, ticket_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/harvest/delivery-tickets/{ticket_id}", headers=headers)

    # --- Settlement ---
    def create_settlement(self, contract_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/harvest/contracts/{contract_id}/settlements", {}, headers)

    def list_contract_settlements(self, contract_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/harvest/contracts/{contract_id}/settlements", headers=headers, params=params)

    def list_settlements(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/harvest/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/harvest/settlements/{settlement_id}", headers=headers)

    def issue_settlement(self, settlement_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/harvest/settlements/{settlement_id}/issue", payload, headers)

    def mark_settlement_paid(self, settlement_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/harvest/settlements/{settlement_id}/mark-paid", {}, headers)

    def dispute_settlement(self, settlement_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/harvest/settlements/{settlement_id}/dispute", {}, headers)

    def resolve_settlement(self, settlement_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/harvest/settlements/{settlement_id}/resolve", payload, headers)

    # --- LodgingSite ---
    def create_lodging_site(self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/harvest/seasons/{season_id}/lodging-sites", payload, headers)

    def list_season_lodging_sites(self, season_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/harvest/seasons/{season_id}/lodging-sites", headers=headers, params=params)

    def list_lodging_sites(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/harvest/lodging-sites", headers=headers, params=params)

    def get_lodging_site(self, site_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/harvest/lodging-sites/{site_id}", headers=headers)

    # --- LodgingReservation ---
    def create_lodging_reservation(self, stop_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/harvest/route-stops/{stop_id}/lodging-reservations", payload, headers)

    def list_stop_lodging_reservations(self, stop_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/harvest/route-stops/{stop_id}/lodging-reservations", headers=headers, params=params)

    def list_lodging_reservations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/harvest/lodging-reservations", headers=headers, params=params)

    def get_lodging_reservation(self, res_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/harvest/lodging-reservations/{res_id}", headers=headers)

    def check_in_reservation(self, res_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/harvest/lodging-reservations/{res_id}/check-in", {}, headers)

    def check_out_reservation(self, res_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/harvest/lodging-reservations/{res_id}/check-out", {}, headers)

    def cancel_reservation(self, res_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/harvest/lodging-reservations/{res_id}/cancel", {}, headers)


api_client = ApiClient()
