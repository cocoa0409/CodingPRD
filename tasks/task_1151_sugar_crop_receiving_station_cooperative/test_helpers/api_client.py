"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Campaign ---
    def create_campaign(self, payload, headers):
        return self._request("POST", "/api/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/api/campaigns/{campaign_id}", headers=headers)

    def close_campaign(self, campaign_id, headers):
        return self._request("POST", f"/api/campaigns/{campaign_id}/close", headers=headers)

    def list_campaign_pools(self, campaign_id, headers):
        return self._request("GET", f"/api/campaigns/{campaign_id}/pools", headers=headers)

    # --- Member ---
    def create_member(self, payload, headers):
        return self._request("POST", "/api/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/api/members/{member_id}", headers=headers)

    def suspend_member(self, member_id, headers):
        return self._request("POST", f"/api/members/{member_id}/suspend", headers=headers)

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/api/members/{member_id}/reinstate", headers=headers)

    # --- Station ---
    def create_station(self, payload, headers):
        return self._request("POST", "/api/stations", payload, headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/api/stations/{station_id}", headers=headers)

    def list_station_piles(self, station_id, headers):
        return self._request("GET", f"/api/stations/{station_id}/piles", headers=headers)

    # --- Pile ---
    def create_pile(self, payload, headers):
        return self._request("POST", "/api/piles", payload, headers)

    def get_pile(self, pile_id, headers):
        return self._request("GET", f"/api/piles/{pile_id}", headers=headers)

    def seal_pile(self, pile_id, headers):
        return self._request("POST", f"/api/piles/{pile_id}/seal", headers=headers)

    def begin_reclaim_pile(self, pile_id, headers):
        return self._request("POST", f"/api/piles/{pile_id}/begin-reclaim", headers=headers)

    def complete_reclaim_pile(self, pile_id, payload, headers):
        return self._request("POST", f"/api/piles/{pile_id}/complete-reclaim", payload, headers)

    def list_pile_loss_events(self, pile_id, headers):
        return self._request("GET", f"/api/piles/{pile_id}/loss-events", headers=headers)

    # --- Booking ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/api/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/api/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/api/bookings", headers=headers, params=params)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/api/bookings/{booking_id}/confirm", headers=headers)

    def reschedule_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/api/bookings/{booking_id}/reschedule", payload, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/api/bookings/{booking_id}/cancel", headers=headers)

    # --- Ticket ---
    def create_ticket(self, payload, headers):
        return self._request("POST", "/api/tickets", payload, headers)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/api/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/api/tickets", headers=headers, params=params)

    def weigh_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/api/tickets/{ticket_id}/weigh", payload, headers)

    def reweigh_ticket(self, ticket_id, headers):
        return self._request("POST", f"/api/tickets/{ticket_id}/reweigh", headers=headers)

    def accept_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/api/tickets/{ticket_id}/accept", payload, headers)

    def reject_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/api/tickets/{ticket_id}/reject", payload, headers)

    def void_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/api/tickets/{ticket_id}/void", payload, headers)

    def credit_ticket(self, ticket_id, headers):
        return self._request("POST", f"/api/tickets/{ticket_id}/credit", headers=headers)

    # --- Sample ---
    def create_sample(self, payload, headers):
        return self._request("POST", "/api/samples", payload, headers)

    def record_sample_result(self, sample_id, payload, headers):
        return self._request("POST", f"/api/samples/{sample_id}/record-result", payload, headers)

    def verify_sample(self, sample_id, headers):
        return self._request("POST", f"/api/samples/{sample_id}/verify", headers=headers)

    def invalidate_sample(self, sample_id, headers):
        return self._request("POST", f"/api/samples/{sample_id}/invalidate", headers=headers)

    def list_ticket_samples(self, ticket_id, headers):
        return self._request("GET", f"/api/tickets/{ticket_id}/samples", headers=headers)

    # --- Pool ---
    def get_pool(self, pool_id, headers):
        return self._request("GET", f"/api/pools/{pool_id}", headers=headers)

    def open_pool_accrual(self, pool_id, payload, headers):
        return self._request("POST", f"/api/pools/{pool_id}/open-accrual", payload, headers)

    def close_pool(self, pool_id, payload, headers):
        return self._request("POST", f"/api/pools/{pool_id}/close", payload, headers)

    def create_pool_installment(self, pool_id, payload, headers):
        return self._request("POST", f"/api/pools/{pool_id}/installments", payload, headers)

    def list_pool_installments(self, pool_id, headers):
        return self._request("GET", f"/api/pools/{pool_id}/installments", headers=headers)

    # --- Installment ---
    def issue_installment(self, installment_id, headers):
        return self._request("POST", f"/api/installments/{installment_id}/issue", headers=headers)

    # --- Loss events ---
    def create_loss_event(self, payload, headers):
        return self._request("POST", "/api/loss-events", payload, headers)

    def confirm_loss_event(self, loss_event_id, headers):
        return self._request("POST", f"/api/loss-events/{loss_event_id}/confirm", headers=headers)

    def allocate_loss_event(self, loss_event_id, headers):
        return self._request("POST", f"/api/loss-events/{loss_event_id}/allocate", headers=headers)

    # --- Pile allocations ---
    def get_pile_allocation(self, allocation_id, headers):
        return self._request("GET", f"/api/pile-allocations/{allocation_id}", headers=headers)

    def list_pile_allocations(self, headers, params=None):
        return self._request("GET", "/api/pile-allocations", headers=headers, params=params)

    # --- Ledger ---
    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/api/ledger-entries/{entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/api/ledger-entries", headers=headers, params=params)

    def reverse_ledger_entry(self, entry_id, headers):
        return self._request("POST", f"/api/ledger-entries/{entry_id}/reverse", headers=headers)

    # --- Settlements ---
    def generate_settlements(self, payload, headers):
        return self._request("POST", "/api/settlements/generate", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/api/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/api/settlements", headers=headers, params=params)

    def issue_settlement(self, settlement_id, headers):
        return self._request("POST", f"/api/settlements/{settlement_id}/issue", headers=headers)

    def dispute_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/api/settlements/{settlement_id}/dispute", payload, headers)

    def revise_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/api/settlements/{settlement_id}/revise", payload, headers)

    def acknowledge_settlement(self, settlement_id, headers):
        return self._request("POST", f"/api/settlements/{settlement_id}/acknowledge", headers=headers)

    def mark_settlement_paid(self, settlement_id, headers):
        return self._request("POST", f"/api/settlements/{settlement_id}/mark-paid", headers=headers)


api_client = ApiClient()
