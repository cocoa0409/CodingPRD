"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- BikeModel ----
    def create_bike_model(self, payload, headers):
        return self._request("POST", "/bike-models", payload, headers)

    def get_bike_model(self, model_id, headers):
        return self._request("GET", f"/bike-models/{model_id}", headers=headers)

    def list_bike_models(self, headers, params=None):
        return self._request("GET", "/bike-models", headers=headers, params=params)

    def list_model_bikes(self, model_id, headers, params=None):
        return self._request(
            "GET", f"/bike-models/{model_id}/bikes", headers=headers, params=params
        )

    # ---- Bike ----
    def create_bike(self, payload, headers):
        return self._request("POST", "/bikes", payload, headers)

    def get_bike(self, bike_id, headers):
        return self._request("GET", f"/bikes/{bike_id}", headers=headers)

    def list_bikes(self, headers, params=None):
        return self._request("GET", "/bikes", headers=headers, params=params)

    def retire_bike(self, bike_id, headers):
        return self._request("POST", f"/bikes/{bike_id}/retire", headers=headers)

    # ---- Account ----
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/suspend", headers=headers)

    def list_account_rentals(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/accounts/{account_id}/rentals", headers=headers, params=params
        )

    # ---- RentalAgreement ----
    def create_rental(self, payload, headers):
        return self._request("POST", "/rentals", payload, headers)

    def get_rental(self, rental_id, headers):
        return self._request("GET", f"/rentals/{rental_id}", headers=headers)

    def list_rentals(self, headers, params=None):
        return self._request("GET", "/rentals", headers=headers, params=params)

    def activate_rental(self, rental_id, headers):
        return self._request("POST", f"/rentals/{rental_id}/activate", headers=headers)

    def request_return(self, rental_id, payload, headers):
        return self._request(
            "POST", f"/rentals/{rental_id}/request-return", payload, headers
        )

    def inspect_rental(self, rental_id, payload, headers):
        return self._request("POST", f"/rentals/{rental_id}/inspect", payload, headers)

    def cancel_rental(self, rental_id, headers):
        return self._request("POST", f"/rentals/{rental_id}/cancel", headers=headers)

    def advance_cycle(self, rental_id, headers):
        return self._request(
            "POST", f"/rentals/{rental_id}/advance-cycle", headers=headers
        )

    # ---- Delivery ----
    def create_delivery(self, payload, headers):
        return self._request("POST", "/deliveries", payload, headers)

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/deliveries/{delivery_id}", headers=headers)

    def list_deliveries(self, headers, params=None):
        return self._request("GET", "/deliveries", headers=headers, params=params)

    def complete_delivery(self, delivery_id, headers):
        return self._request(
            "POST", f"/deliveries/{delivery_id}/complete", headers=headers
        )

    # ---- ServiceTicket ----
    def create_service_ticket(self, payload, headers):
        return self._request("POST", "/service-tickets", payload, headers)

    def get_service_ticket(self, ticket_id, headers):
        return self._request("GET", f"/service-tickets/{ticket_id}", headers=headers)

    def list_service_tickets(self, headers, params=None):
        return self._request("GET", "/service-tickets", headers=headers, params=params)

    def start_service_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/service-tickets/{ticket_id}/start", headers=headers
        )

    def resolve_service_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/service-tickets/{ticket_id}/resolve", payload, headers
        )

    def reopen_service_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/service-tickets/{ticket_id}/reopen", headers=headers
        )

    def close_service_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/service-tickets/{ticket_id}/close", headers=headers
        )

    # ---- InspectionReport ----
    def get_inspection_report(self, report_id, headers):
        return self._request(
            "GET", f"/inspection-reports/{report_id}", headers=headers
        )

    def list_inspection_reports(self, headers, params=None):
        return self._request(
            "GET", "/inspection-reports", headers=headers, params=params
        )

    # ---- CoverageClaim ----
    def create_coverage_claim(self, payload, headers):
        return self._request("POST", "/coverage-claims", payload, headers)

    def get_coverage_claim(self, claim_id, headers):
        return self._request("GET", f"/coverage-claims/{claim_id}", headers=headers)

    def list_coverage_claims(self, headers, params=None):
        return self._request("GET", "/coverage-claims", headers=headers, params=params)

    def review_coverage_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/coverage-claims/{claim_id}/review", headers=headers
        )

    def approve_coverage_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/coverage-claims/{claim_id}/approve", payload, headers
        )

    def deny_coverage_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/coverage-claims/{claim_id}/deny", headers=headers
        )

    def close_coverage_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/coverage-claims/{claim_id}/close", headers=headers
        )

    # ---- BuyoutOffer ----
    def create_buyout_offer(self, rental_id, payload, headers):
        return self._request(
            "POST", f"/rentals/{rental_id}/buyout-offers", payload, headers
        )

    def get_buyout_offer(self, offer_id, headers):
        return self._request("GET", f"/buyout-offers/{offer_id}", headers=headers)

    def list_rental_buyout_offers(self, rental_id, headers, params=None):
        return self._request(
            "GET", f"/rentals/{rental_id}/buyout-offers", headers=headers, params=params
        )

    def accept_buyout_offer(self, offer_id, headers):
        return self._request(
            "POST", f"/buyout-offers/{offer_id}/accept", headers=headers
        )

    # ---- FleetInvoice ----
    def create_fleet_invoice(self, account_id, payload, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/fleet-invoices", payload, headers
        )

    def get_fleet_invoice(self, invoice_id, headers):
        return self._request("GET", f"/fleet-invoices/{invoice_id}", headers=headers)

    def list_account_fleet_invoices(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/accounts/{account_id}/fleet-invoices",
            headers=headers,
            params=params,
        )

    def pay_fleet_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/fleet-invoices/{invoice_id}/pay", headers=headers
        )


api_client = ApiClient()
