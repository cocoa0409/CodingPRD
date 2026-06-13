"""API client: one method per endpoint defined in the Rent-To-Own Home PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Landlord ----
    def create_landlord(self, payload, headers):
        return self._request("POST", "/landlords", payload, headers)

    def get_landlord(self, landlord_id, headers):
        return self._request("GET", f"/landlords/{landlord_id}", headers=headers)

    # ---- Tenant ----
    def create_tenant(self, payload, headers):
        return self._request("POST", "/tenants", payload, headers)

    def get_tenant(self, tenant_id, headers):
        return self._request("GET", f"/tenants/{tenant_id}", headers=headers)

    # ---- Property ----
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    # ---- Agreement ----
    def create_agreement(self, payload, headers):
        return self._request("POST", "/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/agreements", headers=headers, params=params)

    def activate_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/agreements/{agreement_id}/activate", payload, headers)

    def default_agreement(self, agreement_id, headers):
        return self._request("POST", f"/agreements/{agreement_id}/default", {}, headers)

    def expire_agreement(self, agreement_id, headers):
        return self._request("POST", f"/agreements/{agreement_id}/expire", {}, headers)

    # ---- RentPayment ----
    def create_rent_payment(self, agreement_id, payload, headers):
        return self._request("POST", f"/agreements/{agreement_id}/rent-payments", payload, headers)

    def get_rent_payment(self, payment_id, headers):
        return self._request("GET", f"/rent-payments/{payment_id}", headers=headers)

    def list_rent_payments(self, headers, params=None):
        return self._request("GET", "/rent-payments", headers=headers, params=params)

    def record_rent_payment(self, payment_id, payload, headers):
        return self._request("POST", f"/rent-payments/{payment_id}/record", payload, headers)

    def cure_rent_payment(self, payment_id, headers):
        return self._request("POST", f"/rent-payments/{payment_id}/cure", {}, headers)

    def forfeit_rent_payment(self, payment_id, headers):
        return self._request("POST", f"/rent-payments/{payment_id}/forfeit", {}, headers)

    # ---- MaintenanceTicket ----
    def create_maintenance_ticket(self, agreement_id, payload, headers):
        return self._request("POST", f"/agreements/{agreement_id}/maintenance-tickets", payload, headers)

    def get_maintenance_ticket(self, ticket_id, headers):
        return self._request("GET", f"/maintenance-tickets/{ticket_id}", headers=headers)

    def list_maintenance_tickets(self, headers, params=None):
        return self._request("GET", "/maintenance-tickets", headers=headers, params=params)

    def approve_maintenance_ticket(self, ticket_id, headers):
        return self._request("POST", f"/maintenance-tickets/{ticket_id}/approve", {}, headers)

    def reject_maintenance_ticket(self, ticket_id, headers):
        return self._request("POST", f"/maintenance-tickets/{ticket_id}/reject", {}, headers)

    def resolve_maintenance_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/maintenance-tickets/{ticket_id}/resolve", payload, headers)

    # ---- OptionExercise ----
    def create_option_exercise(self, agreement_id, payload, headers):
        return self._request("POST", f"/agreements/{agreement_id}/option-exercises", payload, headers)

    def get_option_exercise(self, exercise_id, headers):
        return self._request("GET", f"/option-exercises/{exercise_id}", headers=headers)

    def list_option_exercises(self, headers, params=None):
        return self._request("GET", "/option-exercises", headers=headers, params=params)

    # ---- Mortgage ----
    def create_mortgage(self, agreement_id, payload, headers):
        return self._request("POST", f"/agreements/{agreement_id}/mortgage", payload, headers)

    def get_mortgage(self, mortgage_id, headers):
        return self._request("GET", f"/mortgages/{mortgage_id}", headers=headers)

    def list_mortgages(self, headers, params=None):
        return self._request("GET", "/mortgages", headers=headers, params=params)

    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
