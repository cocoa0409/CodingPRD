"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/co-living"


class ApiClient(GenericApiClient):
    # ---- logical clock ------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", f"{BASE}/_clock/set_current_utc", payload, headers)

    # ---- hosts --------------------------------------------------------
    def create_host(self, payload, headers):
        return self._request("POST", f"{BASE}/hosts", payload, headers)

    # ---- houses -------------------------------------------------------
    def create_house(self, payload, headers):
        return self._request("POST", f"{BASE}/houses", payload, headers)

    def get_house(self, house_id, headers):
        return self._request("GET", f"{BASE}/houses/{house_id}", headers=headers)

    def list_houses(self, headers, params=None):
        return self._request("GET", f"{BASE}/houses", headers=headers, params=params)

    # ---- rooms --------------------------------------------------------
    def create_room(self, payload, headers):
        return self._request("POST", f"{BASE}/rooms", payload, headers)

    def update_room(self, room_id, payload, headers):
        return self._request("PUT", f"{BASE}/rooms/{room_id}", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"{BASE}/rooms/{room_id}", headers=headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", f"{BASE}/rooms", headers=headers, params=params)

    # ---- members ------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", f"{BASE}/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"{BASE}/members/{member_id}", headers=headers)

    # ---- applications -------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", f"{BASE}/applications", payload, headers)

    def get_application(self, app_id, headers):
        return self._request("GET", f"{BASE}/applications/{app_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", f"{BASE}/applications", headers=headers, params=params)

    def create_screening_report(self, app_id, payload, headers):
        return self._request("POST", f"{BASE}/applications/{app_id}/screening-reports", payload, headers)

    def list_screening_reports(self, app_id, headers, params=None):
        return self._request("GET", f"{BASE}/applications/{app_id}/screening-reports", headers=headers, params=params)

    def decide_application(self, app_id, payload, headers):
        return self._request("POST", f"{BASE}/applications/{app_id}/decision", payload, headers)

    def resubmit_application(self, app_id, payload, headers):
        return self._request("POST", f"{BASE}/applications/{app_id}/resubmit", payload, headers)

    # ---- memberships --------------------------------------------------
    def create_membership(self, payload, headers):
        return self._request("POST", f"{BASE}/memberships", payload, headers)

    def get_membership(self, mem_id, headers):
        return self._request("GET", f"{BASE}/memberships/{mem_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", f"{BASE}/memberships", headers=headers, params=params)

    def move_in(self, mem_id, headers, payload=None):
        return self._request("POST", f"{BASE}/memberships/{mem_id}/move-in", payload or {}, headers)

    def file_notice(self, mem_id, payload, headers):
        return self._request("POST", f"{BASE}/memberships/{mem_id}/notice", payload, headers)

    def move_out(self, mem_id, payload, headers):
        return self._request("POST", f"{BASE}/memberships/{mem_id}/move-out", payload, headers)

    def cancel_membership(self, mem_id, payload, headers):
        return self._request("POST", f"{BASE}/memberships/{mem_id}/cancel", payload or {}, headers)

    # ---- invoices & payments -----------------------------------------
    def create_invoice(self, payload, headers):
        return self._request("POST", f"{BASE}/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"{BASE}/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", f"{BASE}/invoices", headers=headers, params=params)

    def create_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"{BASE}/invoices/{invoice_id}/payments", payload, headers)

    def list_payments(self, invoice_id, headers, params=None):
        return self._request("GET", f"{BASE}/invoices/{invoice_id}/payments", headers=headers, params=params)

    def fee_adjustment(self, invoice_id, payload, headers):
        return self._request("POST", f"{BASE}/invoices/{invoice_id}/fee-adjustment", payload, headers)

    # ---- incidents ----------------------------------------------------
    def create_incident(self, payload, headers):
        return self._request("POST", f"{BASE}/incidents", payload, headers)

    def get_incident(self, inc_id, headers):
        return self._request("GET", f"{BASE}/incidents/{inc_id}", headers=headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", f"{BASE}/incidents", headers=headers, params=params)

    def adjudicate_incident(self, inc_id, payload, headers):
        return self._request("POST", f"{BASE}/incidents/{inc_id}/adjudicate", payload, headers)

    def dispute_incident(self, inc_id, payload, headers):
        return self._request("POST", f"{BASE}/incidents/{inc_id}/dispute", payload, headers)

    # ---- maintenance --------------------------------------------------
    def create_ticket(self, payload, headers):
        return self._request("POST", f"{BASE}/tickets", payload, headers)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"{BASE}/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", f"{BASE}/tickets", headers=headers, params=params)

    def schedule_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"{BASE}/tickets/{ticket_id}/schedule", payload, headers)

    def resolve_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"{BASE}/tickets/{ticket_id}/resolve", payload or {}, headers)

    # ---- payouts ------------------------------------------------------
    def create_payout(self, payload, headers):
        return self._request("POST", f"{BASE}/payouts", payload, headers)

    def project_payout(self, payout_id, headers, payload=None):
        return self._request("POST", f"{BASE}/payouts/{payout_id}/project", payload or {}, headers)

    def release_payout(self, payout_id, headers, payload=None):
        return self._request("POST", f"{BASE}/payouts/{payout_id}/release", payload or {}, headers)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"{BASE}/payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", f"{BASE}/payouts", headers=headers, params=params)


api_client = ApiClient()
