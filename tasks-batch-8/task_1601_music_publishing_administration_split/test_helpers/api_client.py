"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Writers
    # ------------------------------------------------------------------
    def create_writer(self, payload, headers):
        return self._request("POST", "/writers", payload, headers)

    def list_writers(self, headers, params=None):
        return self._request("GET", "/writers", headers=headers, params=params)

    def get_writer(self, writer_id, headers):
        return self._request("GET", f"/writers/{writer_id}", headers=headers)

    def get_earnings_summary(self, writer_id, headers):
        return self._request("GET", f"/writers/{writer_id}/earnings-summary",
                             headers=headers)

    def suspend_writer(self, writer_id, headers):
        return self._request("POST", f"/writers/{writer_id}/suspend", {}, headers)

    def reactivate_writer(self, writer_id, headers):
        return self._request("POST", f"/writers/{writer_id}/reactivate", {}, headers)

    # ------------------------------------------------------------------
    # Works
    # ------------------------------------------------------------------
    def create_work(self, payload, headers):
        return self._request("POST", "/works", payload, headers)

    def list_works(self, headers, params=None):
        return self._request("GET", "/works", headers=headers, params=params)

    def get_work(self, work_id, headers):
        return self._request("GET", f"/works/{work_id}", headers=headers)

    def file_copyright(self, work_id, filing_ref, headers):
        return self._request("POST", f"/works/{work_id}/file-copyright",
                             {"filing_ref": filing_ref}, headers)

    def register_copyright(self, work_id, registration_number, headers):
        return self._request("POST", f"/works/{work_id}/register-copyright",
                             {"registration_number": registration_number}, headers)

    # ------------------------------------------------------------------
    # Societies
    # ------------------------------------------------------------------
    def create_society(self, payload, headers):
        return self._request("POST", "/societies", payload, headers)

    def get_society(self, society_id, headers):
        return self._request("GET", f"/societies/{society_id}", headers=headers)

    # ------------------------------------------------------------------
    # Society registrations
    # ------------------------------------------------------------------
    def create_society_registration(self, payload, headers):
        return self._request("POST", "/society-registrations", payload, headers)

    def list_society_registrations(self, headers, params=None):
        return self._request("GET", "/society-registrations", headers=headers,
                             params=params)

    def get_society_registration(self, registration_id, headers):
        return self._request("GET", f"/society-registrations/{registration_id}",
                             headers=headers)

    def submit_society_registration(self, registration_id, headers):
        return self._request("POST",
                             f"/society-registrations/{registration_id}/submit",
                             {}, headers)

    def acknowledge_society_registration(self, registration_id,
                                         society_work_number, headers):
        return self._request("POST",
                             f"/society-registrations/{registration_id}/acknowledge",
                             {"society_work_number": society_work_number}, headers)

    def register_society_registration(self, registration_id, headers, iswc=None):
        payload = {}
        if iswc is not None:
            payload["iswc"] = iswc
        return self._request("POST",
                             f"/society-registrations/{registration_id}/register",
                             payload, headers)

    def reject_society_registration(self, registration_id, reason, headers):
        return self._request("POST",
                             f"/society-registrations/{registration_id}/reject",
                             {"reason": reason}, headers)

    # ------------------------------------------------------------------
    # Split sets
    # ------------------------------------------------------------------
    def create_split_set(self, payload, headers):
        return self._request("POST", "/split-sets", payload, headers)

    def list_split_sets(self, headers, params=None):
        return self._request("GET", "/split-sets", headers=headers, params=params)

    def get_split_set(self, split_set_id, headers):
        return self._request("GET", f"/split-sets/{split_set_id}", headers=headers)

    def submit_split_set(self, split_set_id, headers):
        return self._request("POST", f"/split-sets/{split_set_id}/submit",
                             {}, headers)

    def revise_split_set(self, split_set_id, lines, headers):
        return self._request("POST", f"/split-sets/{split_set_id}/revise",
                             {"lines": lines}, headers)

    # ------------------------------------------------------------------
    # Split lines
    # ------------------------------------------------------------------
    def list_split_lines(self, headers, params=None):
        return self._request("GET", "/split-lines", headers=headers, params=params)

    def get_split_line(self, split_line_id, headers):
        return self._request("GET", f"/split-lines/{split_line_id}", headers=headers)

    def confirm_split_line(self, split_line_id, headers):
        return self._request("POST", f"/split-lines/{split_line_id}/confirm",
                             {}, headers)

    def reject_split_line(self, split_line_id, reason, headers):
        return self._request("POST", f"/split-lines/{split_line_id}/reject",
                             {"reason": reason}, headers)

    # ------------------------------------------------------------------
    # Sub-publishers
    # ------------------------------------------------------------------
    def create_sub_publisher(self, payload, headers):
        return self._request("POST", "/sub-publishers", payload, headers)

    def get_sub_publisher(self, sub_publisher_id, headers):
        return self._request("GET", f"/sub-publishers/{sub_publisher_id}",
                             headers=headers)

    def suspend_sub_publisher(self, sub_publisher_id, headers):
        return self._request("POST", f"/sub-publishers/{sub_publisher_id}/suspend",
                             {}, headers)

    def reactivate_sub_publisher(self, sub_publisher_id, headers):
        return self._request("POST",
                             f"/sub-publishers/{sub_publisher_id}/reactivate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Sub-publishing agreements
    # ------------------------------------------------------------------
    def create_sub_publishing_agreement(self, payload, headers):
        return self._request("POST", "/sub-publishing-agreements", payload, headers)

    def list_sub_publishing_agreements(self, headers, params=None):
        return self._request("GET", "/sub-publishing-agreements", headers=headers,
                             params=params)

    def get_sub_publishing_agreement(self, agreement_id, headers):
        return self._request("GET", f"/sub-publishing-agreements/{agreement_id}",
                             headers=headers)

    def activate_sub_publishing_agreement(self, agreement_id, headers):
        return self._request("POST",
                             f"/sub-publishing-agreements/{agreement_id}/activate",
                             {}, headers)

    def terminate_sub_publishing_agreement(self, agreement_id, headers):
        return self._request("POST",
                             f"/sub-publishing-agreements/{agreement_id}/terminate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Licensees
    # ------------------------------------------------------------------
    def create_licensee(self, payload, headers):
        return self._request("POST", "/licensees", payload, headers)

    def get_licensee(self, licensee_id, headers):
        return self._request("GET", f"/licensees/{licensee_id}", headers=headers)

    # ------------------------------------------------------------------
    # Royalty statements
    # ------------------------------------------------------------------
    def create_royalty_statement(self, payload, headers):
        return self._request("POST", "/royalty-statements", payload, headers)

    def list_royalty_statements(self, headers, params=None):
        return self._request("GET", "/royalty-statements", headers=headers,
                             params=params)

    def get_royalty_statement(self, statement_id, headers):
        return self._request("GET", f"/royalty-statements/{statement_id}",
                             headers=headers)

    def match_royalty_statement(self, statement_id, headers):
        return self._request("POST", f"/royalty-statements/{statement_id}/match",
                             {}, headers)

    def allocate_royalty_statement(self, statement_id, headers):
        return self._request("POST", f"/royalty-statements/{statement_id}/allocate",
                             {}, headers)

    def finalize_royalty_statement(self, statement_id, headers):
        return self._request("POST", f"/royalty-statements/{statement_id}/finalize",
                             {}, headers)

    def reject_royalty_statement(self, statement_id, reason, headers):
        return self._request("POST", f"/royalty-statements/{statement_id}/reject",
                             {"reason": reason}, headers)

    # ------------------------------------------------------------------
    # Statement lines
    # ------------------------------------------------------------------
    def list_statement_lines(self, headers, params=None):
        return self._request("GET", "/statement-lines", headers=headers,
                             params=params)

    def get_statement_line(self, line_id, headers):
        return self._request("GET", f"/statement-lines/{line_id}", headers=headers)

    def match_statement_line(self, line_id, work_id, headers):
        return self._request("POST", f"/statement-lines/{line_id}/match",
                             {"work_id": work_id}, headers)

    # ------------------------------------------------------------------
    # Allocation lines
    # ------------------------------------------------------------------
    def list_allocation_lines(self, headers, params=None):
        return self._request("GET", "/allocation-lines", headers=headers,
                             params=params)

    def get_allocation_line(self, allocation_line_id, headers):
        return self._request("GET", f"/allocation-lines/{allocation_line_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Advances
    # ------------------------------------------------------------------
    def create_advance(self, payload, headers):
        return self._request("POST", "/advances", payload, headers)

    def list_advances(self, headers, params=None):
        return self._request("GET", "/advances", headers=headers, params=params)

    def get_advance(self, advance_id, headers):
        return self._request("GET", f"/advances/{advance_id}", headers=headers)

    def approve_advance(self, advance_id, headers):
        return self._request("POST", f"/advances/{advance_id}/approve", {}, headers)

    def pay_advance(self, advance_id, headers):
        return self._request("POST", f"/advances/{advance_id}/pay", {}, headers)

    def cancel_advance(self, advance_id, headers):
        return self._request("POST", f"/advances/{advance_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Distribution runs
    # ------------------------------------------------------------------
    def create_distribution_run(self, payload, headers):
        return self._request("POST", "/distribution-runs", payload, headers)

    def list_distribution_runs(self, headers, params=None):
        return self._request("GET", "/distribution-runs", headers=headers,
                             params=params)

    def get_distribution_run(self, run_id, headers):
        return self._request("GET", f"/distribution-runs/{run_id}", headers=headers)

    def calculate_distribution_run(self, run_id, headers):
        return self._request("POST", f"/distribution-runs/{run_id}/calculate",
                             {}, headers)

    def approve_distribution_run(self, run_id, headers):
        return self._request("POST", f"/distribution-runs/{run_id}/approve",
                             {}, headers)

    def pay_distribution_run(self, run_id, headers):
        return self._request("POST", f"/distribution-runs/{run_id}/pay", {}, headers)

    def reopen_distribution_run(self, run_id, headers):
        return self._request("POST", f"/distribution-runs/{run_id}/reopen",
                             {}, headers)

    # ------------------------------------------------------------------
    # Licensee audits
    # ------------------------------------------------------------------
    def create_licensee_audit(self, payload, headers):
        return self._request("POST", "/licensee-audits", payload, headers)

    def list_licensee_audits(self, headers, params=None):
        return self._request("GET", "/licensee-audits", headers=headers,
                             params=params)

    def get_licensee_audit(self, audit_id, headers):
        return self._request("GET", f"/licensee-audits/{audit_id}", headers=headers)

    def begin_fieldwork(self, audit_id, headers):
        return self._request("POST", f"/licensee-audits/{audit_id}/begin-fieldwork",
                             {}, headers)

    def issue_findings(self, audit_id, payload, headers):
        return self._request("POST", f"/licensee-audits/{audit_id}/issue-findings",
                             payload, headers)

    def appeal_audit(self, audit_id, reason, headers):
        return self._request("POST", f"/licensee-audits/{audit_id}/appeal",
                             {"reason": reason}, headers)

    def settle_audit(self, audit_id, settlement_cents, headers):
        return self._request("POST", f"/licensee-audits/{audit_id}/settle",
                             {"settlement_cents": settlement_cents}, headers)

    def close_audit(self, audit_id, headers):
        return self._request("POST", f"/licensee-audits/{audit_id}/close",
                             {}, headers)

    # ------------------------------------------------------------------
    # Termination claims
    # ------------------------------------------------------------------
    def create_termination_claim(self, payload, headers):
        return self._request("POST", "/termination-claims", payload, headers)

    def list_termination_claims(self, headers, params=None):
        return self._request("GET", "/termination-claims", headers=headers,
                             params=params)

    def get_termination_claim(self, claim_id, headers):
        return self._request("GET", f"/termination-claims/{claim_id}",
                             headers=headers)

    def file_notice(self, claim_id, notice_ref, headers):
        return self._request("POST", f"/termination-claims/{claim_id}/file-notice",
                             {"notice_ref": notice_ref}, headers)

    def make_effective(self, claim_id, headers):
        return self._request("POST", f"/termination-claims/{claim_id}/make-effective",
                             {}, headers)

    def reject_termination_claim(self, claim_id, reason, headers):
        return self._request("POST", f"/termination-claims/{claim_id}/reject",
                             {"reason": reason}, headers)


api_client = ApiClient()
