"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Client ----
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    # ---- Program ----
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/programs", headers=headers, params=params)

    def activate_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/activate", headers=headers)

    def complete_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/complete", headers=headers)

    def drop_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/drop", headers=headers)

    # ---- DedicatedAccount ----
    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    # ---- Debt ----
    def create_debt(self, payload, headers):
        return self._request("POST", "/debts", payload, headers)

    def get_debt(self, debt_id, headers):
        return self._request("GET", f"/debts/{debt_id}", headers=headers)

    def list_debts(self, headers, params=None):
        return self._request("GET", "/debts", headers=headers, params=params)

    # ---- Deposit ----
    def create_deposit(self, payload, headers):
        return self._request("POST", "/deposits", payload, headers)

    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"/deposits/{deposit_id}", headers=headers)

    def list_deposits(self, headers, params=None):
        return self._request("GET", "/deposits", headers=headers, params=params)

    def cure_deposit(self, deposit_id, headers):
        return self._request("POST", f"/deposits/{deposit_id}/cure", headers=headers)

    # ---- Offer ----
    def create_offer(self, payload, headers):
        return self._request("POST", "/offers", payload, headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/offers", headers=headers, params=params)

    def accept_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/offers/{offer_id}/accept", payload, headers)

    def reject_offer(self, offer_id, headers):
        return self._request("POST", f"/offers/{offer_id}/reject", headers=headers)

    # ---- Settlement ----
    def create_settlement(self, payload, headers):
        return self._request("POST", "/settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def complete_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/complete", headers=headers)

    def void_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/void", headers=headers)

    # ---- SettlementFee ----
    def get_fee(self, fee_id, headers):
        return self._request("GET", f"/fees/{fee_id}", headers=headers)

    def list_fees(self, headers, params=None):
        return self._request("GET", "/fees", headers=headers, params=params)

    # ---- Lawsuit ----
    def create_lawsuit(self, payload, headers):
        return self._request("POST", "/lawsuits", payload, headers)

    def get_lawsuit(self, lawsuit_id, headers):
        return self._request("GET", f"/lawsuits/{lawsuit_id}", headers=headers)

    def list_lawsuits(self, headers, params=None):
        return self._request("GET", "/lawsuits", headers=headers, params=params)

    def dismiss_lawsuit(self, lawsuit_id, headers):
        return self._request("POST", f"/lawsuits/{lawsuit_id}/dismiss", headers=headers)

    # ---- TaxEvent ----
    def get_tax_event(self, tax_event_id, headers):
        return self._request("GET", f"/tax-events/{tax_event_id}", headers=headers)

    def list_tax_events(self, headers, params=None):
        return self._request("GET", "/tax-events", headers=headers, params=params)


api_client = ApiClient()
