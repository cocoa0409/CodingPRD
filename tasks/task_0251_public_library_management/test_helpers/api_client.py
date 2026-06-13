"""API client: one method per endpoint defined in the PRD (§4).

Subclasses GenericApiClient; the base _request() handles the envelope.
All paths live under the flat /library namespace.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Test clock ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/library/_clock/set", {"to_iso8601": to_iso8601}, headers)

    # ---------------- Branch ----------------
    def create_branch(self, payload, headers):
        return self._request("POST", "/library/branches", payload, headers)

    def get_branch(self, branch_id, headers):
        return self._request("GET", f"/library/branches/{branch_id}", headers=headers)

    def list_branches(self, headers, params=None):
        return self._request("GET", "/library/branches", headers=headers, params=params)

    # ---------------- Patron ----------------
    def create_patron(self, payload, headers):
        return self._request("POST", "/library/patrons", payload, headers)

    def get_patron(self, patron_id, headers):
        return self._request("GET", f"/library/patrons/{patron_id}", headers=headers)

    def list_patrons(self, headers, params=None):
        return self._request("GET", "/library/patrons", headers=headers, params=params)

    def set_card_status(self, patron_id, card_status, headers):
        return self._request("POST", f"/library/patrons/{patron_id}/set-card-status",
                             {"card_status": card_status}, headers)

    def get_account_summary(self, patron_id, headers):
        return self._request("GET", f"/library/patrons/{patron_id}/account-summary", headers=headers)

    # ---------------- Title ----------------
    def create_title(self, payload, headers):
        return self._request("POST", "/library/titles", payload, headers)

    def get_title(self, title_id, headers):
        return self._request("GET", f"/library/titles/{title_id}", headers=headers)

    def list_titles(self, headers, params=None):
        return self._request("GET", "/library/titles", headers=headers, params=params)

    def withdraw_title(self, title_id, headers):
        return self._request("POST", f"/library/titles/{title_id}/withdraw", headers=headers)

    # ---------------- Copy ----------------
    def create_copy(self, payload, headers):
        return self._request("POST", "/library/copies", payload, headers)

    def get_copy(self, copy_id, headers):
        return self._request("GET", f"/library/copies/{copy_id}", headers=headers)

    def list_copies(self, headers, params=None):
        return self._request("GET", "/library/copies", headers=headers, params=params)

    # ---------------- Loan ----------------
    def create_loan(self, payload, headers):
        return self._request("POST", "/library/loans", payload, headers)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/library/loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/library/loans", headers=headers, params=params)

    def fine_estimate(self, loan_id, headers, params=None):
        return self._request("GET", f"/library/loans/{loan_id}/fine-estimate",
                             headers=headers, params=params)

    def renew_loan(self, loan_id, headers):
        return self._request("POST", f"/library/loans/{loan_id}/renew", headers=headers)

    def refresh_overdue(self, loan_id, headers):
        return self._request("POST", f"/library/loans/{loan_id}/refresh-overdue", headers=headers)

    def checkin_loan(self, loan_id, headers):
        return self._request("POST", f"/library/loans/{loan_id}/checkin", headers=headers)

    def declare_lost(self, loan_id, headers, payload=None):
        return self._request("POST", f"/library/loans/{loan_id}/declare-lost",
                             payload if payload is not None else {}, headers)

    # ---------------- Hold ----------------
    def create_hold(self, payload, headers):
        return self._request("POST", "/library/holds", payload, headers)

    def get_hold(self, hold_id, headers):
        return self._request("GET", f"/library/holds/{hold_id}", headers=headers)

    def list_holds(self, headers, params=None):
        return self._request("GET", "/library/holds", headers=headers, params=params)

    def checkout_hold(self, hold_id, headers):
        return self._request("POST", f"/library/holds/{hold_id}/checkout", headers=headers)

    def expire_ready_hold(self, hold_id, headers):
        return self._request("POST", f"/library/holds/{hold_id}/expire-ready", headers=headers)

    def cancel_hold(self, hold_id, headers):
        return self._request("POST", f"/library/holds/{hold_id}/cancel", headers=headers)

    # ---------------- BookableResource ----------------
    def create_resource(self, payload, headers):
        return self._request("POST", "/library/resources", payload, headers)

    def get_resource(self, resource_id, headers):
        return self._request("GET", f"/library/resources/{resource_id}", headers=headers)

    def list_resources(self, headers, params=None):
        return self._request("GET", "/library/resources", headers=headers, params=params)

    def set_service_status(self, resource_id, status, headers):
        return self._request("POST", f"/library/resources/{resource_id}/set-service-status",
                             {"status": status}, headers)

    # ---------------- Reservation ----------------
    def create_reservation(self, payload, headers):
        return self._request("POST", "/library/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/library/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/library/reservations", headers=headers, params=params)

    def confirm_reservation(self, reservation_id, headers):
        return self._request("POST", f"/library/reservations/{reservation_id}/confirm", headers=headers)

    def checkin_reservation(self, reservation_id, headers):
        return self._request("POST", f"/library/reservations/{reservation_id}/checkin", headers=headers)

    def complete_reservation(self, reservation_id, headers):
        return self._request("POST", f"/library/reservations/{reservation_id}/complete", headers=headers)

    def no_show_reservation(self, reservation_id, headers):
        return self._request("POST", f"/library/reservations/{reservation_id}/no-show", headers=headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/library/reservations/{reservation_id}/cancel", headers=headers)

    # ---------------- IllRequest ----------------
    def create_ill_request(self, payload, headers):
        return self._request("POST", "/library/ill-requests", payload, headers)

    def get_ill_request(self, ill_id, headers):
        return self._request("GET", f"/library/ill-requests/{ill_id}", headers=headers)

    def list_ill_requests(self, headers, params=None):
        return self._request("GET", "/library/ill-requests", headers=headers, params=params)

    def transition_ill(self, ill_id, action, headers):
        return self._request("POST", f"/library/ill-requests/{ill_id}/transition",
                             {"action": action}, headers)

    # ---------------- LicensePool / EbookLoan ----------------
    def create_license_pool(self, payload, headers):
        return self._request("POST", "/library/license-pools", payload, headers)

    def get_license_pool(self, pool_id, headers):
        return self._request("GET", f"/library/license-pools/{pool_id}", headers=headers)

    def list_license_pools(self, headers, params=None):
        return self._request("GET", "/library/license-pools", headers=headers, params=params)

    def run_expiry(self, pool_id, headers):
        return self._request("POST", f"/library/license-pools/{pool_id}/run-expiry", headers=headers)

    def create_ebook_loan(self, payload, headers):
        return self._request("POST", "/library/ebook-loans", payload, headers)

    def get_ebook_loan(self, ebook_loan_id, headers):
        return self._request("GET", f"/library/ebook-loans/{ebook_loan_id}", headers=headers)

    def list_ebook_loans(self, headers, params=None):
        return self._request("GET", "/library/ebook-loans", headers=headers, params=params)

    def return_ebook_loan(self, ebook_loan_id, headers):
        return self._request("POST", f"/library/ebook-loans/{ebook_loan_id}/return", headers=headers)

    # ---------------- Fine ----------------
    def get_fine(self, fine_id, headers):
        return self._request("GET", f"/library/fines/{fine_id}", headers=headers)

    def list_fines(self, headers, params=None):
        return self._request("GET", "/library/fines", headers=headers, params=params)

    def pay_fine(self, fine_id, headers):
        return self._request("POST", f"/library/fines/{fine_id}/pay", headers=headers)

    def waive_fine(self, fine_id, headers):
        return self._request("POST", f"/library/fines/{fine_id}/waive", headers=headers)


api_client = ApiClient()
