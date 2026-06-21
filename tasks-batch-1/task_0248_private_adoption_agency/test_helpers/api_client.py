"""API client: one method per endpoint defined in the PRD (Private Adoption Agency API)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Agency ──────────────────────────────────────────────────────────
    def create_agency(self, payload, headers):
        return self._request("POST", "/agencies", payload, headers)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/agencies/{agency_id}", headers=headers)

    def list_agencies(self, headers, params=None):
        return self._request("GET", "/agencies", headers=headers, params=params)

    # ─── Test-driving clock ──────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── AdoptionCase ────────────────────────────────────────────────────
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    # ─── AdoptiveFamily ──────────────────────────────────────────────────
    def create_family(self, payload, headers):
        return self._request("POST", "/families", payload, headers)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/families/{family_id}", headers=headers)

    def list_families(self, headers, params=None):
        return self._request("GET", "/families", headers=headers, params=params)

    # ─── HomeStudy ───────────────────────────────────────────────────────
    def create_home_study(self, payload, headers):
        return self._request("POST", "/home-studies", payload, headers)

    def get_home_study(self, hs_id, headers):
        return self._request("GET", f"/home-studies/{hs_id}", headers=headers)

    def list_home_studies(self, headers, params=None):
        return self._request("GET", "/home-studies", headers=headers, params=params)

    def submit_home_study(self, hs_id, headers):
        return self._request("POST", f"/home-studies/{hs_id}/submit", {}, headers)

    def approve_home_study(self, hs_id, headers):
        return self._request("POST", f"/home-studies/{hs_id}/approve", {}, headers)

    def return_home_study(self, hs_id, headers):
        return self._request("POST", f"/home-studies/{hs_id}/return", {}, headers)

    def resubmit_home_study(self, hs_id, headers):
        return self._request("POST", f"/home-studies/{hs_id}/resubmit", {}, headers)

    def check_expiry_home_study(self, hs_id, headers):
        return self._request("POST", f"/home-studies/{hs_id}/check-expiry", {}, headers)

    # ─── BirthParent ─────────────────────────────────────────────────────
    def create_birth_parent(self, payload, headers):
        return self._request("POST", "/birth-parents", payload, headers)

    def get_birth_parent(self, bp_id, headers):
        return self._request("GET", f"/birth-parents/{bp_id}", headers=headers)

    def list_birth_parents(self, headers, params=None):
        return self._request("GET", "/birth-parents", headers=headers, params=params)

    # ─── CounselingSession ───────────────────────────────────────────────
    def create_counseling_session(self, payload, headers):
        return self._request("POST", "/counseling-sessions", payload, headers)

    def get_counseling_session(self, session_id, headers):
        return self._request("GET", f"/counseling-sessions/{session_id}", headers=headers)

    def list_counseling_sessions(self, headers, params=None):
        return self._request("GET", "/counseling-sessions", headers=headers, params=params)

    def hold_counseling_session(self, session_id, headers):
        return self._request("POST", f"/counseling-sessions/{session_id}/hold", {}, headers)

    def cancel_counseling_session(self, session_id, headers):
        return self._request("POST", f"/counseling-sessions/{session_id}/cancel", {}, headers)

    # ─── Match ───────────────────────────────────────────────────────────
    def create_match(self, payload, headers):
        return self._request("POST", "/matches", payload, headers)

    def get_match(self, match_id, headers):
        return self._request("GET", f"/matches/{match_id}", headers=headers)

    def list_matches(self, headers, params=None):
        return self._request("GET", "/matches", headers=headers, params=params)

    def accept_match(self, match_id, headers):
        return self._request("POST", f"/matches/{match_id}/accept", {}, headers)

    def decline_match(self, match_id, headers):
        return self._request("POST", f"/matches/{match_id}/decline", {}, headers)

    def dissolve_match(self, match_id, headers):
        return self._request("POST", f"/matches/{match_id}/dissolve", {}, headers)

    # ─── ConsentRecord ───────────────────────────────────────────────────
    def create_consent_record(self, payload, headers):
        return self._request("POST", "/consent-records", payload, headers)

    def get_consent_record(self, consent_id, headers):
        return self._request("GET", f"/consent-records/{consent_id}", headers=headers)

    def list_consent_records(self, headers, params=None):
        return self._request("GET", "/consent-records", headers=headers, params=params)

    def sign_consent(self, consent_id, headers):
        return self._request("POST", f"/consent-records/{consent_id}/sign", {}, headers)

    def revoke_consent(self, consent_id, headers):
        return self._request("POST", f"/consent-records/{consent_id}/revoke", {}, headers)

    def finalize_consent(self, consent_id, headers):
        return self._request("POST", f"/consent-records/{consent_id}/finalize-consent", {}, headers)

    # ─── IcpcClearance ───────────────────────────────────────────────────
    def create_icpc_clearance(self, payload, headers):
        return self._request("POST", "/icpc-clearances", payload, headers)

    def get_icpc_clearance(self, icpc_id, headers):
        return self._request("GET", f"/icpc-clearances/{icpc_id}", headers=headers)

    def list_icpc_clearances(self, headers, params=None):
        return self._request("GET", "/icpc-clearances", headers=headers, params=params)

    def submit_icpc(self, icpc_id, headers):
        return self._request("POST", f"/icpc-clearances/{icpc_id}/submit", {}, headers)

    def approve_sending_icpc(self, icpc_id, headers):
        return self._request("POST", f"/icpc-clearances/{icpc_id}/approve-sending", {}, headers)

    def approve_receiving_icpc(self, icpc_id, headers):
        return self._request("POST", f"/icpc-clearances/{icpc_id}/approve-receiving", {}, headers)

    def reject_icpc(self, icpc_id, headers):
        return self._request("POST", f"/icpc-clearances/{icpc_id}/reject", {}, headers)

    def rework_icpc(self, icpc_id, headers):
        return self._request("POST", f"/icpc-clearances/{icpc_id}/rework", {}, headers)

    # ─── Placement ───────────────────────────────────────────────────────
    def create_placement(self, payload, headers):
        return self._request("POST", "/placements", payload, headers)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"/placements/{placement_id}", headers=headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", "/placements", headers=headers, params=params)

    def activate_placement(self, placement_id, headers):
        return self._request("POST", f"/placements/{placement_id}/activate", {}, headers)

    def finalize_placement(self, placement_id, headers):
        return self._request("POST", f"/placements/{placement_id}/finalize", {}, headers)

    def disrupt_placement(self, placement_id, headers):
        return self._request("POST", f"/placements/{placement_id}/disrupt", {}, headers)

    # ─── PostPlacementVisit ──────────────────────────────────────────────
    def create_visit(self, payload, headers):
        return self._request("POST", "/post-placement-visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/post-placement-visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/post-placement-visits", headers=headers, params=params)

    def complete_visit(self, visit_id, headers):
        return self._request("POST", f"/post-placement-visits/{visit_id}/complete", {}, headers)

    def mark_missed_visit(self, visit_id, headers):
        return self._request("POST", f"/post-placement-visits/{visit_id}/mark-missed", {}, headers)

    # ─── ExpenseEntry ────────────────────────────────────────────────────
    def create_expense(self, payload, headers):
        return self._request("POST", "/expense-entries", payload, headers)

    def get_expense(self, expense_id, headers):
        return self._request("GET", f"/expense-entries/{expense_id}", headers=headers)

    def list_expenses(self, headers, params=None):
        return self._request("GET", "/expense-entries", headers=headers, params=params)

    def approve_expense(self, expense_id, headers):
        return self._request("POST", f"/expense-entries/{expense_id}/approve", {}, headers)

    def reject_expense(self, expense_id, headers):
        return self._request("POST", f"/expense-entries/{expense_id}/reject", {}, headers)

    def disburse_expense(self, expense_id, headers):
        return self._request("POST", f"/expense-entries/{expense_id}/disburse", {}, headers)

    # ─── EscrowTransaction ───────────────────────────────────────────────
    def create_escrow_transaction(self, payload, headers):
        return self._request("POST", "/escrow-transactions", payload, headers)

    def get_escrow_transaction(self, txn_id, headers):
        return self._request("GET", f"/escrow-transactions/{txn_id}", headers=headers)

    def list_escrow_transactions(self, headers, params=None):
        return self._request("GET", "/escrow-transactions", headers=headers, params=params)

    # ─── AgencyFeeInvoice ────────────────────────────────────────────────
    def create_invoice(self, payload, headers):
        return self._request("POST", "/agency-fee-invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/agency-fee-invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/agency-fee-invoices", headers=headers, params=params)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/agency-fee-invoices/{invoice_id}/pay", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/agency-fee-invoices/{invoice_id}/void", {}, headers)


api_client = ApiClient()
