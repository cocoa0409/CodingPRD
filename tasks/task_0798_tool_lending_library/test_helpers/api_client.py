"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Members ----
    def create_member(self, payload, headers):
        return self._request("POST", "/library/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/library/members/{member_id}", headers=headers)

    # ---- Volunteers ----
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/library/volunteers", payload, headers)

    # ---- Items & Copies ----
    def create_item(self, payload, headers):
        return self._request("POST", "/library/items", payload, headers)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/library/items/{item_id}", headers=headers)

    def add_copy(self, item_id, payload, headers):
        return self._request("POST", f"/library/items/{item_id}/copies", payload, headers)

    def list_copies(self, item_id, headers, params=None):
        return self._request("GET", f"/library/items/{item_id}/copies", headers=headers, params=params)

    def get_copy(self, copy_id, headers):
        return self._request("GET", f"/library/copies/{copy_id}", headers=headers)

    # ---- Reservations ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/library/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/library/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/library/reservations", headers=headers, params=params)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/library/reservations/{reservation_id}/cancel", headers=headers)

    # ---- Loans ----
    def create_loan(self, payload, headers):
        return self._request("POST", "/library/loans", payload, headers)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/library/loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/library/loans", headers=headers, params=params)

    def renew_loan(self, loan_id, headers):
        return self._request("POST", f"/library/loans/{loan_id}/renew", headers=headers)

    def return_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/library/loans/{loan_id}/return", payload, headers)

    # ---- Holds / waitlist ----
    def create_hold(self, payload, headers):
        return self._request("POST", "/library/holds", payload, headers)

    def get_hold(self, hold_id, headers):
        return self._request("GET", f"/library/holds/{hold_id}", headers=headers)

    def list_holds(self, headers, params=None):
        return self._request("GET", "/library/holds", headers=headers, params=params)

    # ---- Fees ----
    def get_fee(self, fee_id, headers):
        return self._request("GET", f"/library/fees/{fee_id}", headers=headers)

    def list_fees(self, headers, params=None):
        return self._request("GET", "/library/fees", headers=headers, params=params)

    def pay_fee(self, fee_id, headers):
        return self._request("POST", f"/library/fees/{fee_id}/pay", headers=headers)

    def waive_fee(self, fee_id, payload, headers):
        return self._request("POST", f"/library/fees/{fee_id}/waive", payload, headers)

    # ---- Donations / intake ----
    def create_donation(self, payload, headers):
        return self._request("POST", "/library/donations", payload, headers)

    def get_donation(self, donation_id, headers):
        return self._request("GET", f"/library/donations/{donation_id}", headers=headers)

    def list_donations(self, headers, params=None):
        return self._request("GET", "/library/donations", headers=headers, params=params)

    def accept_donation(self, donation_id, payload, headers):
        return self._request("POST", f"/library/donations/{donation_id}/accept", payload, headers)

    def reject_donation(self, donation_id, payload, headers):
        return self._request("POST", f"/library/donations/{donation_id}/reject", payload, headers)

    # ---- Maintenance ----
    def create_ticket(self, payload, headers):
        return self._request("POST", "/library/maintenance-tickets", payload, headers)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/library/maintenance-tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/library/maintenance-tickets", headers=headers, params=params)

    def resolve_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/library/maintenance-tickets/{ticket_id}/resolve", payload, headers)

    # ---- Reporting ----
    def get_usage_report(self, headers, params=None):
        return self._request("GET", "/library/reports/usage", headers=headers, params=params)

    # ---- System / clock / ops ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/library/_clock/set_current_utc", payload, headers)

    def ops_run(self, headers):
        return self._request("POST", "/library/_ops/run", None, headers)


api_client = ApiClient()
