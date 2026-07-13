"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- Fare products / agencies / passengers ---
    def create_fare_product(self, payload, headers):
        return self._request("POST", "/fare-products", payload, headers)

    def create_agency(self, payload, headers):
        return self._request("POST", "/agencies", payload, headers)

    def create_passenger(self, payload, headers):
        return self._request("POST", "/passengers", payload, headers)

    def get_passenger(self, passenger_id, headers):
        return self._request("GET", f"/passengers/{passenger_id}", headers=headers)

    # --- Reduced-fare applications ---
    def create_application(self, payload, headers):
        return self._request("POST", "/reduced-fare-applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/reduced-fare-applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/reduced-fare-applications", headers=headers, params=params)

    def approve_application(self, application_id, headers):
        return self._request("POST", f"/reduced-fare-applications/{application_id}/approve", {}, headers)

    def reject_application(self, application_id, payload, headers):
        return self._request("POST", f"/reduced-fare-applications/{application_id}/reject", payload, headers)

    # --- Tickets ---
    def create_ticket(self, payload, headers):
        return self._request("POST", "/tickets", payload, headers)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/tickets", headers=headers, params=params)

    def activate_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/activate", {}, headers)

    def validate_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/validate", {}, headers)

    def exchange_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/tickets/{ticket_id}/exchange", payload, headers)

    # --- Inspections ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    # --- Upgrades ---
    def create_upgrade(self, payload, headers):
        return self._request("POST", "/upgrades", payload, headers)

    def get_upgrade(self, upgrade_id, headers):
        return self._request("GET", f"/upgrades/{upgrade_id}", headers=headers)

    def list_upgrades(self, headers, params=None):
        return self._request("GET", "/upgrades", headers=headers, params=params)

    # --- Citations ---
    def create_citation(self, payload, headers):
        return self._request("POST", "/citations", payload, headers)

    def get_citation(self, citation_id, headers):
        return self._request("GET", f"/citations/{citation_id}", headers=headers)

    def list_citations(self, headers, params=None):
        return self._request("GET", "/citations", headers=headers, params=params)

    def pay_citation(self, citation_id, headers):
        return self._request("POST", f"/citations/{citation_id}/pay", {}, headers)

    def contest_citation(self, citation_id, payload, headers):
        return self._request("POST", f"/citations/{citation_id}/contest", payload, headers)

    def resolve_citation(self, citation_id, payload, headers):
        return self._request("POST", f"/citations/{citation_id}/resolve", payload, headers)

    # --- Refund requests ---
    def create_refund_request(self, payload, headers):
        return self._request("POST", "/refund-requests", payload, headers)

    def get_refund_request(self, refund_id, headers):
        return self._request("GET", f"/refund-requests/{refund_id}", headers=headers)

    def list_refund_requests(self, headers, params=None):
        return self._request("GET", "/refund-requests", headers=headers, params=params)

    def approve_refund(self, refund_id, headers):
        return self._request("POST", f"/refund-requests/{refund_id}/approve", {}, headers)

    def deny_refund(self, refund_id, payload, headers):
        return self._request("POST", f"/refund-requests/{refund_id}/deny", payload, headers)

    # --- Service disruptions / credits ---
    def create_disruption(self, payload, headers):
        return self._request("POST", "/service-disruptions", payload, headers)

    def create_service_credit(self, payload, headers):
        return self._request("POST", "/service-credits", payload, headers)

    def get_service_credit(self, credit_id, headers):
        return self._request("GET", f"/service-credits/{credit_id}", headers=headers)

    def list_service_credits(self, headers, params=None):
        return self._request("GET", "/service-credits", headers=headers, params=params)

    def void_service_credit(self, credit_id, payload, headers):
        return self._request("POST", f"/service-credits/{credit_id}/void", payload, headers)


api_client = ApiClient()
