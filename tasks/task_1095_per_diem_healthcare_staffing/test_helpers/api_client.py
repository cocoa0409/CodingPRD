"""API client: one method per endpoint defined in the PRD.

All paths are mounted under the /staffing prefix. Each method delegates to the
inherited _request() and returns the raw requests.Response so tests can assert
status codes and envelopes.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------- registry / configuration --------------------- #
    def set_clock(self, payload, headers):
        return self._request("POST", "/staffing/_clock/set_current_utc", payload, headers)

    def create_facility(self, payload, headers):
        return self._request("POST", "/staffing/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/staffing/facilities/{facility_id}", headers=headers)

    def create_rate_card(self, facility_id, payload, headers):
        return self._request("POST", f"/staffing/facilities/{facility_id}/rate-cards", payload, headers)

    def list_rate_cards(self, facility_id, headers, params=None):
        return self._request("GET", f"/staffing/facilities/{facility_id}/rate-cards", headers=headers, params=params)

    def create_clinician(self, payload, headers):
        return self._request("POST", "/staffing/clinicians", payload, headers)

    def get_clinician(self, clinician_id, headers):
        return self._request("GET", f"/staffing/clinicians/{clinician_id}", headers=headers)

    def create_credential(self, clinician_id, payload, headers):
        return self._request("POST", f"/staffing/clinicians/{clinician_id}/credentials", payload, headers)

    def list_credentials(self, clinician_id, headers, params=None):
        return self._request("GET", f"/staffing/clinicians/{clinician_id}/credentials", headers=headers, params=params)

    def verify_credential(self, credential_id, payload, headers):
        return self._request("POST", f"/staffing/credentials/{credential_id}/verify", payload, headers)

    def revoke_credential(self, credential_id, payload, headers):
        return self._request("POST", f"/staffing/credentials/{credential_id}/revoke", payload, headers)

    # ---------------------- orders, shifts, claims ----------------------- #
    def create_order(self, payload, headers):
        return self._request("POST", "/staffing/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/staffing/orders/{order_id}", headers=headers)

    def list_facility_orders(self, facility_id, headers, params=None):
        return self._request("GET", f"/staffing/facilities/{facility_id}/orders", headers=headers, params=params)

    def create_shift(self, order_id, payload, headers):
        return self._request("POST", f"/staffing/orders/{order_id}/shifts", payload, headers)

    def list_order_shifts(self, order_id, headers, params=None):
        return self._request("GET", f"/staffing/orders/{order_id}/shifts", headers=headers, params=params)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/staffing/orders/{order_id}/cancel", payload, headers)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/staffing/shifts/{shift_id}", headers=headers)

    def create_claim(self, shift_id, payload, headers):
        return self._request("POST", f"/staffing/shifts/{shift_id}/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/staffing/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/staffing/claims", headers=headers, params=params)

    def withdraw_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/staffing/claims/{claim_id}/withdraw", payload, headers)

    def award_shift(self, shift_id, payload, headers):
        return self._request("POST", f"/staffing/shifts/{shift_id}/award", payload, headers)

    # ---------------------- assignments & attendance --------------------- #
    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/staffing/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/staffing/assignments", headers=headers, params=params)

    def confirm_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/staffing/assignments/{assignment_id}/confirm", payload, headers)

    def cancel_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/staffing/assignments/{assignment_id}/cancel", payload, headers)

    def no_show_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/staffing/assignments/{assignment_id}/no-show", payload, headers)

    # ---------------------- timesheets ----------------------------------- #
    def submit_timesheet(self, assignment_id, payload, headers):
        return self._request("POST", f"/staffing/assignments/{assignment_id}/timesheets", payload, headers)

    def list_assignment_timesheets(self, assignment_id, headers, params=None):
        return self._request("GET", f"/staffing/assignments/{assignment_id}/timesheets", headers=headers, params=params)

    def get_timesheet(self, timesheet_id, headers):
        return self._request("GET", f"/staffing/timesheets/{timesheet_id}", headers=headers)

    def dispute_timesheet(self, timesheet_id, payload, headers):
        return self._request("POST", f"/staffing/timesheets/{timesheet_id}/dispute", payload, headers)

    def resubmit_timesheet(self, timesheet_id, payload, headers):
        return self._request("POST", f"/staffing/timesheets/{timesheet_id}/resubmit", payload, headers)

    def verify_timesheet(self, timesheet_id, payload, headers):
        return self._request("POST", f"/staffing/timesheets/{timesheet_id}/verify", payload, headers)

    # ---------------------- reliability ---------------------------------- #
    def list_clinician_reliability_events(self, clinician_id, headers, params=None):
        return self._request("GET", f"/staffing/clinicians/{clinician_id}/reliability-events", headers=headers, params=params)

    def list_assignment_reliability_events(self, assignment_id, headers, params=None):
        return self._request("GET", f"/staffing/assignments/{assignment_id}/reliability-events", headers=headers, params=params)

    def adjudicate_event(self, event_id, payload, headers):
        return self._request("POST", f"/staffing/reliability-events/{event_id}/adjudicate", payload, headers)

    # ---------------------- billing -------------------------------------- #
    def create_invoice(self, payload, headers):
        return self._request("POST", "/staffing/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/staffing/invoices/{invoice_id}", headers=headers)

    def list_facility_invoices(self, facility_id, headers, params=None):
        return self._request("GET", f"/staffing/facilities/{facility_id}/invoices", headers=headers, params=params)

    def list_invoice_timesheets(self, invoice_id, headers, params=None):
        return self._request("GET", f"/staffing/invoices/{invoice_id}/timesheets", headers=headers, params=params)

    def issue_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/staffing/invoices/{invoice_id}/issue", payload, headers)

    def settle_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/staffing/invoices/{invoice_id}/settle", payload, headers)

    def void_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/staffing/invoices/{invoice_id}/void", payload, headers)


api_client = ApiClient()
