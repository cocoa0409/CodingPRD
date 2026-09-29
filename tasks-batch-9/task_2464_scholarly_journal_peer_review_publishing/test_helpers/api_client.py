"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Operational endpoints
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_reminder_sweep(self, payload, headers):
        return self._request("POST", "/_ops/run-reminder-sweep", payload, headers)

    # ------------------------------------------------------------------
    # Journals
    # ------------------------------------------------------------------
    def create_journal(self, payload, headers):
        return self._request("POST", "/journals", payload, headers)

    def update_journal(self, journal_id, payload, headers):
        return self._request("PATCH", f"/journals/{journal_id}", payload, headers)

    def get_journal(self, journal_id, headers):
        return self._request("GET", f"/journals/{journal_id}", headers=headers)

    def list_journals(self, headers, params=None):
        return self._request("GET", "/journals", headers=headers, params=params)

    def get_journal_metrics(self, journal_id, headers):
        return self._request("GET", f"/journals/{journal_id}/metrics", headers=headers)

    # ------------------------------------------------------------------
    # People
    # ------------------------------------------------------------------
    def create_editor(self, payload, headers):
        return self._request("POST", "/editors", payload, headers)

    def get_editor(self, editor_id, headers):
        return self._request("GET", f"/editors/{editor_id}", headers=headers)

    def list_editors(self, headers, params=None):
        return self._request("GET", "/editors", headers=headers, params=params)

    def create_author(self, payload, headers):
        return self._request("POST", "/authors", payload, headers)

    def get_author(self, author_id, headers):
        return self._request("GET", f"/authors/{author_id}", headers=headers)

    def create_reviewer(self, payload, headers):
        return self._request("POST", "/reviewers", payload, headers)

    def get_reviewer(self, reviewer_id, headers):
        return self._request("GET", f"/reviewers/{reviewer_id}", headers=headers)

    def list_reviewers(self, headers, params=None):
        return self._request("GET", "/reviewers", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Manuscripts
    # ------------------------------------------------------------------
    def create_manuscript(self, payload, headers):
        return self._request("POST", "/manuscripts", payload, headers)

    def get_manuscript(self, manuscript_id, headers):
        return self._request("GET", f"/manuscripts/{manuscript_id}", headers=headers)

    def list_manuscripts(self, headers, params=None):
        return self._request("GET", "/manuscripts", headers=headers, params=params)

    def create_integrity_screening(self, manuscript_id, payload, headers):
        return self._request(
            "POST", f"/manuscripts/{manuscript_id}/integrity-screenings", payload, headers
        )

    def list_integrity_screenings(self, manuscript_id, headers, params=None):
        return self._request(
            "GET",
            f"/manuscripts/{manuscript_id}/integrity-screenings",
            headers=headers,
            params=params,
        )

    def change_licensing(self, manuscript_id, payload, headers):
        return self._request(
            "POST", f"/manuscripts/{manuscript_id}/licensing", payload, headers
        )

    def screening_decision(self, manuscript_id, payload, headers):
        return self._request(
            "POST", f"/manuscripts/{manuscript_id}/screening-decision", payload, headers
        )

    def submit_revision(self, manuscript_id, payload, headers):
        return self._request(
            "POST", f"/manuscripts/{manuscript_id}/revisions", payload, headers
        )

    # ------------------------------------------------------------------
    # Editor assignments
    # ------------------------------------------------------------------
    def create_editor_assignment(self, payload, headers):
        return self._request("POST", "/editor-assignments", payload, headers)

    def declare_conflict(self, assignment_id, payload, headers):
        return self._request(
            "POST",
            f"/editor-assignments/{assignment_id}/conflict-declaration",
            payload,
            headers,
        )

    def recuse_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/editor-assignments/{assignment_id}/recusal", payload, headers
        )

    def get_editor_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/editor-assignments/{assignment_id}", headers=headers
        )

    def list_editor_assignments(self, headers, params=None):
        return self._request("GET", "/editor-assignments", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Review invitations and reviews
    # ------------------------------------------------------------------
    def create_review_invitation(self, payload, headers):
        return self._request("POST", "/review-invitations", payload, headers)

    def respond_to_invitation(self, invitation_id, payload, headers):
        return self._request(
            "POST", f"/review-invitations/{invitation_id}/response", payload, headers
        )

    def submit_review(self, invitation_id, payload, headers):
        return self._request(
            "POST", f"/review-invitations/{invitation_id}/reviews", payload, headers
        )

    def withdraw_invitation(self, invitation_id, payload, headers):
        return self._request(
            "POST", f"/review-invitations/{invitation_id}/withdraw", payload, headers
        )

    def get_review_invitation(self, invitation_id, headers):
        return self._request(
            "GET", f"/review-invitations/{invitation_id}", headers=headers
        )

    def list_review_invitations(self, headers, params=None):
        return self._request(
            "GET", "/review-invitations", headers=headers, params=params
        )

    def list_reviews(self, invitation_id, headers, params=None):
        return self._request(
            "GET",
            f"/review-invitations/{invitation_id}/reviews",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Decisions and appeals
    # ------------------------------------------------------------------
    def create_decision(self, manuscript_id, payload, headers):
        return self._request(
            "POST", f"/manuscripts/{manuscript_id}/decisions", payload, headers
        )

    def get_decision(self, decision_id, headers):
        return self._request("GET", f"/decisions/{decision_id}", headers=headers)

    def list_decisions(self, headers, params=None):
        return self._request("GET", "/decisions", headers=headers, params=params)

    def create_appeal(self, payload, headers):
        return self._request("POST", "/appeals", payload, headers)

    def adjudicate_appeal(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/appeals/{appeal_id}/adjudication", payload, headers
        )

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/appeals", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Ethics cases
    # ------------------------------------------------------------------
    def create_ethics_case(self, manuscript_id, payload, headers):
        return self._request(
            "POST", f"/manuscripts/{manuscript_id}/ethics-cases", payload, headers
        )

    def list_manuscript_ethics_cases(self, manuscript_id, headers, params=None):
        return self._request(
            "GET",
            f"/manuscripts/{manuscript_id}/ethics-cases",
            headers=headers,
            params=params,
        )

    def advance_ethics_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/ethics-cases/{case_id}/advance", payload, headers
        )

    def resolve_ethics_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/ethics-cases/{case_id}/resolution", payload, headers
        )

    def get_ethics_case(self, case_id, headers):
        return self._request("GET", f"/ethics-cases/{case_id}", headers=headers)

    # ------------------------------------------------------------------
    # APC invoices
    # ------------------------------------------------------------------
    def create_apc_invoice(self, manuscript_id, payload, headers):
        return self._request(
            "POST", f"/manuscripts/{manuscript_id}/apc-invoices", payload, headers
        )

    def settle_apc_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/apc-invoices/{invoice_id}/settlement", payload, headers
        )

    def get_apc_invoice(self, invoice_id, headers):
        return self._request("GET", f"/apc-invoices/{invoice_id}", headers=headers)

    def list_manuscript_apc_invoices(self, manuscript_id, headers, params=None):
        return self._request(
            "GET",
            f"/manuscripts/{manuscript_id}/apc-invoices",
            headers=headers,
            params=params,
        )

    def get_manuscript_apc_invoice(self, manuscript_id, invoice_id, headers):
        return self._request(
            "GET",
            f"/manuscripts/{manuscript_id}/apc-invoices/{invoice_id}",
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Production jobs
    # ------------------------------------------------------------------
    def book_typeset_slot(self, job_id, payload, headers):
        return self._request(
            "POST", f"/production-jobs/{job_id}/typeset-slot", payload, headers
        )

    def advance_production_content(self, job_id, payload, headers):
        return self._request(
            "POST", f"/production-jobs/{job_id}/content-advance", payload, headers
        )

    def approve_proof(self, job_id, payload, headers):
        return self._request(
            "POST", f"/production-jobs/{job_id}/proof-approval", payload, headers
        )

    def record_archival_deposit(self, job_id, payload, headers):
        return self._request(
            "POST", f"/production-jobs/{job_id}/archival-deposit", payload, headers
        )

    def publish_article(self, job_id, payload, headers):
        return self._request(
            "POST", f"/production-jobs/{job_id}/publication", payload, headers
        )

    def get_production_job(self, job_id, headers):
        return self._request("GET", f"/production-jobs/{job_id}", headers=headers)

    def list_manuscript_production_jobs(self, manuscript_id, headers, params=None):
        return self._request(
            "GET",
            f"/manuscripts/{manuscript_id}/production-jobs",
            headers=headers,
            params=params,
        )


api_client = ApiClient()
