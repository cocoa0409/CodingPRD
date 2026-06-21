"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def list_customer_loans(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/loans", headers=headers, params=params)

    def list_customer_leases(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/leases", headers=headers, params=params)

    # ---- Vehicle ----
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    # ---- RateCard ----
    def create_rate_card(self, payload, headers):
        return self._request("POST", "/rate-cards", payload, headers)

    def activate_rate_card(self, rate_card_id, headers):
        return self._request("POST", f"/rate-cards/{rate_card_id}/activate", headers=headers)

    def get_rate_card(self, rate_card_id, headers):
        return self._request("GET", f"/rate-cards/{rate_card_id}", headers=headers)

    def list_rate_cards(self, headers, params=None):
        return self._request("GET", "/rate-cards", headers=headers, params=params)

    # ---- Loan ----
    def create_loan(self, payload, headers):
        return self._request("POST", "/loans", payload, headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/loans", headers=headers, params=params)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/loans/{loan_id}", headers=headers)

    def get_payoff_quote(self, loan_id, headers):
        return self._request("GET", f"/loans/{loan_id}/payoff-quote", headers=headers)

    def list_loan_payments(self, loan_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/payments", headers=headers, params=params)

    def record_payment(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/payments", payload, headers)

    def miss_payment(self, loan_id, headers):
        return self._request("POST", f"/loans/{loan_id}/miss-payment", headers=headers)

    def declare_default(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/default", payload, headers)

    def payoff_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/payoff", payload, headers)

    # ---- Lease ----
    def create_lease(self, payload, headers):
        return self._request("POST", "/leases", payload, headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/leases", headers=headers, params=params)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/leases/{lease_id}", headers=headers)

    def mature_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/mature", headers=headers)

    def list_lease_settlements(self, lease_id, headers, params=None):
        return self._request("GET", f"/leases/{lease_id}/settlements", headers=headers, params=params)

    # ---- LeaseEndSettlement ----
    def create_settlement(self, payload, headers):
        return self._request("POST", "/lease-end-settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/lease-end-settlements/{settlement_id}", headers=headers)


api_client = ApiClient()
