"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Client ───────────────────────────────────────
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def suspend_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/suspend", {}, headers)

    # ─── Linguist ─────────────────────────────────────
    def create_linguist(self, payload, headers):
        return self._request("POST", "/linguists", payload, headers)

    def get_linguist(self, linguist_id, headers):
        return self._request("GET", f"/linguists/{linguist_id}", headers=headers)

    def deactivate_linguist(self, linguist_id, headers):
        return self._request("POST", f"/linguists/{linguist_id}/deactivate", {}, headers)

    def list_linguist_assignments(self, linguist_id, headers, params=None):
        return self._request("GET", f"/linguists/{linguist_id}/assignments",
                             headers=headers, params=params)

    def list_linguist_payout_ledger(self, linguist_id, headers, params=None):
        return self._request("GET", f"/linguists/{linguist_id}/payout-ledger",
                             headers=headers, params=params)

    # ─── RateCard ─────────────────────────────────────
    def create_rate_card(self, payload, headers):
        return self._request("POST", "/rate-cards", payload, headers)

    def get_rate_card(self, rate_card_id, headers):
        return self._request("GET", f"/rate-cards/{rate_card_id}", headers=headers)

    # ─── Project ──────────────────────────────────────
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def quote_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/quote", {}, headers)

    def approve_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/approve", {}, headers)

    def cancel_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/cancel", {}, headers)

    # ─── ProjectJob ───────────────────────────────────
    def create_job(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/jobs", payload, headers)

    def list_project_jobs(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/jobs",
                             headers=headers, params=params)

    def get_job(self, job_id, headers):
        return self._request("GET", f"/jobs/{job_id}", headers=headers)

    def submit_translation(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/submit-translation", {}, headers)

    def deliver_job(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/deliver", payload, headers)

    def list_job_certificate(self, job_id, headers):
        return self._request("GET", f"/jobs/{job_id}/certificate", headers=headers)

    # ─── Assignment ───────────────────────────────────
    def create_assignment(self, payload, headers):
        return self._request("POST", "/assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_job_assignments(self, job_id, headers, params=None):
        return self._request("GET", f"/jobs/{job_id}/assignments",
                             headers=headers, params=params)

    def list_assignment_payout_ledger(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}/payout-ledger",
                             headers=headers)

    def accept_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/accept", {}, headers)

    def decline_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/decline", {}, headers)

    # ─── QAReport ─────────────────────────────────────
    def create_qa_report(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/qa-reports", payload, headers)

    def get_qa_report(self, qa_report_id, headers):
        return self._request("GET", f"/qa-reports/{qa_report_id}", headers=headers)

    def list_job_qa_reports(self, job_id, headers, params=None):
        return self._request("GET", f"/jobs/{job_id}/qa-reports",
                             headers=headers, params=params)

    def list_assignment_qa_reports(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}/qa-reports",
                             headers=headers)

    # ─── Invoice ──────────────────────────────────────
    def create_invoice(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/invoices", {}, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_project_invoices(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/invoices",
                             headers=headers, params=params)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", payload, headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)

    # ─── Raw helpers for header / not-found probes ─────
    def raw_post(self, path, payload, headers):
        return self._request("POST", path, payload, headers)

    def raw_get(self, path, headers):
        return self._request("GET", path, headers=headers)


api_client = ApiClient()
