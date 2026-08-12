"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # --- Tank ---
    def create_tank(self, payload, headers):
        return self._request("POST", "/tanks", payload, headers)

    def list_tanks(self, headers, params=None):
        return self._request("GET", "/tanks", headers=headers, params=params)

    def get_tank(self, tank_id, headers):
        return self._request("GET", f"/tanks/{tank_id}", headers=headers)

    def enter_tank_maintenance(self, tank_id, headers):
        return self._request("POST", f"/tanks/{tank_id}/enter-maintenance", {}, headers)

    def return_tank_to_service(self, tank_id, headers):
        return self._request("POST", f"/tanks/{tank_id}/return-to-service", {}, headers)

    # --- TerminalResource ---
    def create_terminal_resource(self, payload, headers):
        return self._request("POST", "/terminal-resources", payload, headers)

    def list_terminal_resources(self, headers, params=None):
        return self._request("GET", "/terminal-resources", headers=headers, params=params)

    def get_terminal_resource(self, resource_id, headers):
        return self._request("GET", f"/terminal-resources/{resource_id}", headers=headers)

    def resource_out_of_service(self, resource_id, headers):
        return self._request("POST", f"/terminal-resources/{resource_id}/out-of-service", {}, headers)

    def resource_return_to_service(self, resource_id, headers):
        return self._request("POST", f"/terminal-resources/{resource_id}/return-to-service", {}, headers)

    # --- LeaseAgreement ---
    def create_lease_agreement(self, payload, headers):
        return self._request("POST", "/lease-agreements", payload, headers)

    def list_lease_agreements(self, headers, params=None):
        return self._request("GET", "/lease-agreements", headers=headers, params=params)

    def get_lease_agreement(self, lease_id, headers):
        return self._request("GET", f"/lease-agreements/{lease_id}", headers=headers)

    def activate_lease(self, lease_id, headers):
        return self._request("POST", f"/lease-agreements/{lease_id}/activate", {}, headers)

    def suspend_lease(self, lease_id, headers):
        return self._request("POST", f"/lease-agreements/{lease_id}/suspend", {}, headers)

    def reactivate_lease(self, lease_id, headers):
        return self._request("POST", f"/lease-agreements/{lease_id}/reactivate", {}, headers)

    def terminate_lease(self, lease_id, headers):
        return self._request("POST", f"/lease-agreements/{lease_id}/terminate", {}, headers)

    # --- LeaseAmendment ---
    def create_lease_amendment(self, lease_id, payload, headers):
        return self._request("POST", f"/lease-agreements/{lease_id}/amendments", payload, headers)

    def list_lease_amendments(self, lease_id, headers, params=None):
        return self._request("GET", f"/lease-agreements/{lease_id}/amendments", headers=headers, params=params)

    def approve_amendment(self, amendment_id, headers):
        return self._request("POST", f"/lease-amendments/{amendment_id}/approve", {}, headers)

    def reject_amendment(self, amendment_id, headers):
        return self._request("POST", f"/lease-amendments/{amendment_id}/reject", {}, headers)

    # --- TankAllocation ---
    def create_tank_allocation(self, lease_id, payload, headers):
        return self._request("POST", f"/lease-agreements/{lease_id}/allocations", payload, headers)

    def list_lease_allocations(self, lease_id, headers, params=None):
        return self._request("GET", f"/lease-agreements/{lease_id}/allocations", headers=headers, params=params)

    def list_tank_allocations(self, tank_id, headers, params=None):
        return self._request("GET", f"/tanks/{tank_id}/allocations", headers=headers, params=params)

    def get_tank_allocation(self, allocation_id, headers):
        return self._request("GET", f"/tank-allocations/{allocation_id}", headers=headers)

    def activate_tank_allocation(self, allocation_id, headers):
        return self._request("POST", f"/tank-allocations/{allocation_id}/activate", {}, headers)

    def release_tank_allocation(self, allocation_id, headers):
        return self._request("POST", f"/tank-allocations/{allocation_id}/release", {}, headers)

    # --- Permit ---
    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def approve_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/approve", {}, headers)

    def revoke_permit(self, permit_id, headers, payload=None):
        return self._request("POST", f"/permits/{permit_id}/revoke", payload or {}, headers)

    # --- Movement ---
    def create_movement(self, payload, headers):
        return self._request("POST", "/movements", payload, headers)

    def list_movements(self, headers, params=None):
        return self._request("GET", "/movements", headers=headers, params=params)

    def get_movement(self, movement_id, headers):
        return self._request("GET", f"/movements/{movement_id}", headers=headers)

    def schedule_movement(self, movement_id, payload, headers):
        return self._request("POST", f"/movements/{movement_id}/schedule", payload, headers)

    def arrive_movement(self, movement_id, headers):
        return self._request("POST", f"/movements/{movement_id}/arrive", {}, headers)

    def start_movement(self, movement_id, headers):
        return self._request("POST", f"/movements/{movement_id}/start", {}, headers)

    def complete_movement(self, movement_id, headers):
        return self._request("POST", f"/movements/{movement_id}/complete", {}, headers)

    def cancel_movement(self, movement_id, headers):
        return self._request("POST", f"/movements/{movement_id}/cancel", {}, headers)

    def resume_movement(self, movement_id, headers):
        return self._request("POST", f"/movements/{movement_id}/resume", {}, headers)

    # --- GaugeTicket ---
    def create_gauge_ticket(self, movement_id, payload, headers):
        return self._request("POST", f"/movements/{movement_id}/gauge-tickets", payload, headers)

    def list_gauge_tickets(self, movement_id, headers, params=None):
        return self._request("GET", f"/movements/{movement_id}/gauge-tickets", headers=headers, params=params)

    # --- QualitySample ---
    def create_quality_sample(self, movement_id, payload, headers):
        return self._request("POST", f"/movements/{movement_id}/samples", payload, headers)

    def list_quality_samples(self, movement_id, headers, params=None):
        return self._request("GET", f"/movements/{movement_id}/samples", headers=headers, params=params)

    def get_quality_sample(self, sample_id, headers):
        return self._request("GET", f"/quality-samples/{sample_id}", headers=headers)

    def record_sample_result(self, sample_id, payload, headers):
        return self._request("POST", f"/quality-samples/{sample_id}/record-result", payload, headers)

    def release_sample_retain(self, sample_id, headers):
        return self._request("POST", f"/quality-samples/{sample_id}/release-retain", {}, headers)

    # --- CustodyTransfer ---
    def list_movement_custody_transfers(self, movement_id, headers, params=None):
        return self._request("GET", f"/movements/{movement_id}/custody-transfers", headers=headers, params=params)

    def get_custody_transfer(self, ct_id, headers):
        return self._request("GET", f"/custody-transfers/{ct_id}", headers=headers)

    def certify_custody_transfer(self, ct_id, headers):
        return self._request("POST", f"/custody-transfers/{ct_id}/certify", {}, headers)

    def dispute_custody_transfer(self, ct_id, headers):
        return self._request("POST", f"/custody-transfers/{ct_id}/dispute", {}, headers)

    def resolve_custody_transfer(self, ct_id, headers):
        return self._request("POST", f"/custody-transfers/{ct_id}/resolve", {}, headers)

    def void_custody_transfer(self, ct_id, headers):
        return self._request("POST", f"/custody-transfers/{ct_id}/void", {}, headers)

    # --- MonthlyStatement ---
    def create_monthly_statement(self, lease_id, payload, headers):
        return self._request("POST", f"/lease-agreements/{lease_id}/statements", payload, headers)

    def list_monthly_statements(self, lease_id, headers, params=None):
        return self._request("GET", f"/lease-agreements/{lease_id}/statements", headers=headers, params=params)

    def get_monthly_statement(self, statement_id, headers):
        return self._request("GET", f"/monthly-statements/{statement_id}", headers=headers)

    def close_statement(self, statement_id, headers):
        return self._request("POST", f"/monthly-statements/{statement_id}/close", {}, headers)

    def invoice_statement(self, statement_id, headers):
        return self._request("POST", f"/monthly-statements/{statement_id}/invoice", {}, headers)

    # --- Logical clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
