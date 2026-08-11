"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- RequestingOrg ---
    def create_org(self, payload, headers):
        return self._request("POST", "/orgs", payload, headers)

    def get_org(self, org_id, headers):
        return self._request("GET", f"/orgs/{org_id}", headers=headers)

    def suspend_org(self, org_id, headers):
        return self._request("POST", f"/orgs/{org_id}/suspend", payload={}, headers=headers)

    def reinstate_org(self, org_id, headers):
        return self._request("POST", f"/orgs/{org_id}/reinstate", payload={}, headers=headers)

    def list_org_complaints(self, org_id, headers, params=None):
        return self._request("GET", f"/orgs/{org_id}/complaints", headers=headers, params=params)

    def list_org_credit_memos(self, org_id, headers, params=None):
        return self._request("GET", f"/orgs/{org_id}/credit-memos", headers=headers, params=params)

    # --- RateCard ---
    def create_rate_card(self, payload, headers):
        return self._request("POST", "/rate-cards", payload, headers)

    def get_rate_card(self, card_id, headers):
        return self._request("GET", f"/rate-cards/{card_id}", headers=headers)

    def retire_rate_card(self, card_id, headers):
        return self._request("POST", f"/rate-cards/{card_id}/retire", payload={}, headers=headers)

    # --- Interpreter ---
    def create_interpreter(self, payload, headers):
        return self._request("POST", "/interpreters", payload, headers)

    def get_interpreter(self, interpreter_id, headers):
        return self._request("GET", f"/interpreters/{interpreter_id}", headers=headers)

    def activate_interpreter(self, interpreter_id, headers):
        return self._request("POST", f"/interpreters/{interpreter_id}/activate", payload={}, headers=headers)

    def suspend_interpreter(self, interpreter_id, headers):
        return self._request("POST", f"/interpreters/{interpreter_id}/suspend", payload={}, headers=headers)

    def reinstate_interpreter(self, interpreter_id, headers):
        return self._request("POST", f"/interpreters/{interpreter_id}/reinstate", payload={}, headers=headers)

    def create_certification(self, interpreter_id, payload, headers):
        return self._request("POST", f"/interpreters/{interpreter_id}/certifications", payload, headers)

    def list_certifications(self, interpreter_id, headers, params=None):
        return self._request("GET", f"/interpreters/{interpreter_id}/certifications", headers=headers, params=params)

    def verify_certification(self, interpreter_id, cert_id, headers):
        return self._request(
            "POST",
            f"/interpreters/{interpreter_id}/certifications/{cert_id}/verify",
            payload={},
            headers=headers,
        )

    def create_availability_window(self, interpreter_id, payload, headers):
        return self._request("POST", f"/interpreters/{interpreter_id}/availability-windows", payload, headers)

    def list_availability_windows(self, interpreter_id, headers, params=None):
        return self._request("GET", f"/interpreters/{interpreter_id}/availability-windows", headers=headers, params=params)

    def delete_availability_window(self, interpreter_id, window_id, headers):
        return self._request(
            "DELETE",
            f"/interpreters/{interpreter_id}/availability-windows/{window_id}",
            headers=headers,
        )

    def list_interpreter_strikes(self, interpreter_id, headers, params=None):
        return self._request("GET", f"/interpreters/{interpreter_id}/strikes", headers=headers, params=params)

    def list_interpreter_complaints(self, interpreter_id, headers, params=None):
        return self._request("GET", f"/interpreters/{interpreter_id}/complaints", headers=headers, params=params)

    # --- InterpretingRequest ---
    def create_request(self, payload, headers):
        return self._request("POST", "/requests", payload, headers)

    def list_requests(self, headers, params=None):
        return self._request("GET", "/requests", headers=headers, params=params)

    def get_request(self, request_id, headers):
        return self._request("GET", f"/requests/{request_id}", headers=headers)

    def submit_request(self, request_id, headers):
        return self._request("POST", f"/requests/{request_id}/submit", payload={}, headers=headers)

    def cancel_request(self, request_id, headers, payload=None):
        return self._request("POST", f"/requests/{request_id}/cancel", payload or {}, headers)

    def create_offer(self, request_id, payload, headers):
        return self._request("POST", f"/requests/{request_id}/offers", payload, headers)

    def list_request_offers(self, request_id, headers, params=None):
        return self._request("GET", f"/requests/{request_id}/offers", headers=headers, params=params)

    # --- Assignment ---
    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def accept_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/accept", payload={}, headers=headers)

    def decline_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/decline", payload={}, headers=headers)

    def confirm_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/confirm", payload={}, headers=headers)

    def depart_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/depart", payload={}, headers=headers)

    def check_in_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/check-in", payload={}, headers=headers)

    def check_out_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/check-out", payload, headers)

    def cancel_assignment(self, assignment_id, headers, payload=None):
        return self._request("POST", f"/assignments/{assignment_id}/cancel", payload or {}, headers)

    def mark_no_show(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/mark-no-show", payload={}, headers=headers)

    def list_assignment_encounters(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}/encounters", headers=headers)

    def list_assignment_invoices(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}/invoices", headers=headers)

    def list_assignment_complaints(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}/complaints", headers=headers)

    def list_assignment_strikes(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}/strikes", headers=headers)

    # --- Encounter ---
    def verify_encounter(self, encounter_id, payload, headers):
        return self._request("POST", f"/encounters/{encounter_id}/verify", payload, headers)

    # --- Invoice ---
    def generate_invoice(self, payload, headers):
        return self._request("POST", "/invoices/generate", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", payload={}, headers=headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", payload={}, headers=headers)

    def dispute_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/dispute", payload, headers)

    def resolve_dispute(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/resolve-dispute", payload, headers)

    def record_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/payments", payload, headers)

    # --- Complaint ---
    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def begin_review(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/begin-review", payload={}, headers=headers)

    def adjudicate_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/adjudicate", payload, headers)

    def reopen_complaint(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/reopen", payload={}, headers=headers)

    def list_complaint_credit_memos(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}/credit-memos", headers=headers)

    # --- CreditMemo ---
    def create_credit_memo(self, payload, headers):
        return self._request("POST", "/credit-memos", payload, headers)

    def get_credit_memo(self, memo_id, headers):
        return self._request("GET", f"/credit-memos/{memo_id}", headers=headers)

    def void_credit_memo(self, memo_id, headers):
        return self._request("POST", f"/credit-memos/{memo_id}/void", payload={}, headers=headers)

    # --- StrikeRecord ---
    def create_strike(self, payload, headers):
        return self._request("POST", "/strikes", payload, headers)

    def rescind_strike(self, strike_id, headers):
        return self._request("POST", f"/strikes/{strike_id}/rescind", payload={}, headers=headers)

    # --- ReportingSnapshot ---
    def generate_report(self, payload, headers):
        return self._request("POST", "/reports/generate", payload, headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/reports/{report_id}", headers=headers)


api_client = ApiClient()
