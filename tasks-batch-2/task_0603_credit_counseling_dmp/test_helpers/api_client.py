"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Agency ---
    def create_agency(self, payload, headers):
        return self._request("POST", "/agencies/agencies", payload, headers)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/agencies/agencies/{agency_id}", headers=headers)

    def run_disbursement(self, agency_id, headers, payload=None):
        return self._request(
            "POST", f"/agencies/agencies/{agency_id}/run_disbursement",
            payload if payload is not None else {}, headers,
        )

    # --- DisbursementRun ---
    def get_disbursement_run(self, run_id, headers):
        return self._request("GET", f"/agencies/disbursement-runs/{run_id}", headers=headers)

    def list_disbursement_runs(self, headers, params=None):
        return self._request("GET", "/agencies/disbursement-runs", headers=headers, params=params)

    # --- DisbursementLine ---
    def get_disbursement_line(self, line_id, headers):
        return self._request("GET", f"/agencies/disbursement-lines/{line_id}", headers=headers)

    def list_disbursement_lines(self, headers, params=None):
        return self._request("GET", "/agencies/disbursement-lines", headers=headers, params=params)

    # --- Counselor ---
    def create_counselor(self, payload, headers):
        return self._request("POST", "/agencies/counselors", payload, headers)

    def get_counselor(self, counselor_id, headers):
        return self._request("GET", f"/agencies/counselors/{counselor_id}", headers=headers)

    def list_counselors(self, headers, params=None):
        return self._request("GET", "/agencies/counselors", headers=headers, params=params)

    # --- Creditor ---
    def create_creditor(self, payload, headers):
        return self._request("POST", "/agencies/creditors", payload, headers)

    def get_creditor(self, creditor_id, headers):
        return self._request("GET", f"/agencies/creditors/{creditor_id}", headers=headers)

    def list_creditors(self, headers, params=None):
        return self._request("GET", "/agencies/creditors", headers=headers, params=params)

    # --- Client ---
    def create_client(self, payload, headers):
        return self._request("POST", "/agencies/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/agencies/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/agencies/clients", headers=headers, params=params)

    def activate_client(self, client_id, payload, headers):
        return self._request("POST", f"/agencies/clients/{client_id}/activate", payload, headers)

    def re_age_client(self, client_id, headers, payload=None):
        return self._request(
            "POST", f"/agencies/clients/{client_id}/re_age",
            payload if payload is not None else {}, headers,
        )

    def withdraw_client(self, client_id, headers, payload=None):
        return self._request(
            "POST", f"/agencies/clients/{client_id}/withdraw",
            payload if payload is not None else {}, headers,
        )

    def record_deposit(self, client_id, payload, headers):
        return self._request("POST", f"/agencies/clients/{client_id}/deposits", payload, headers)

    def open_session(self, client_id, payload, headers):
        return self._request("POST", f"/agencies/clients/{client_id}/sessions", payload, headers)

    def create_debt_account(self, client_id, payload, headers):
        return self._request("POST", f"/agencies/clients/{client_id}/debt-accounts", payload, headers)

    def payoff_projection(self, client_id, headers):
        return self._request("GET", f"/agencies/clients/{client_id}/payoff_projection", headers=headers)

    # --- DepositRecord ---
    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"/agencies/deposits/{deposit_id}", headers=headers)

    def list_deposits(self, headers, params=None):
        return self._request("GET", "/agencies/deposits", headers=headers, params=params)

    # --- CounselingSession ---
    def get_session(self, session_id, headers):
        return self._request("GET", f"/agencies/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/agencies/sessions", headers=headers, params=params)

    def request_revision(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"/agencies/sessions/{session_id}/request_revision",
            payload if payload is not None else {}, headers,
        )

    def resume_session(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"/agencies/sessions/{session_id}/resume",
            payload if payload is not None else {}, headers,
        )

    def complete_session(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"/agencies/sessions/{session_id}/complete",
            payload if payload is not None else {}, headers,
        )

    def certify_session(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"/agencies/sessions/{session_id}/certify",
            payload if payload is not None else {}, headers,
        )

    # --- DebtAccount ---
    def get_debt_account(self, debt_account_id, headers):
        return self._request("GET", f"/agencies/debt-accounts/{debt_account_id}", headers=headers)

    def list_debt_accounts(self, headers, params=None):
        return self._request("GET", "/agencies/debt-accounts", headers=headers, params=params)

    def drop_debt_account(self, debt_account_id, headers, payload=None):
        return self._request(
            "POST", f"/agencies/debt-accounts/{debt_account_id}/drop",
            payload if payload is not None else {}, headers,
        )

    def get_savings(self, debt_account_id, headers):
        return self._request("GET", f"/agencies/debt-accounts/{debt_account_id}/savings", headers=headers)

    # --- CreditorProposal ---
    def get_proposal(self, proposal_id, headers):
        return self._request("GET", f"/agencies/proposals/{proposal_id}", headers=headers)

    def list_proposals(self, headers, params=None):
        return self._request("GET", "/agencies/proposals", headers=headers, params=params)

    def counter_proposal(self, proposal_id, payload, headers):
        return self._request("POST", f"/agencies/proposals/{proposal_id}/counter", payload, headers)

    def resubmit_proposal(self, proposal_id, payload, headers):
        return self._request("POST", f"/agencies/proposals/{proposal_id}/resubmit", payload, headers)

    def accept_proposal(self, proposal_id, headers, payload=None):
        return self._request(
            "POST", f"/agencies/proposals/{proposal_id}/accept",
            payload if payload is not None else {}, headers,
        )

    def accept_counter(self, proposal_id, headers, payload=None):
        return self._request(
            "POST", f"/agencies/proposals/{proposal_id}/accept_counter",
            payload if payload is not None else {}, headers,
        )

    def reject_proposal(self, proposal_id, headers, payload=None):
        return self._request(
            "POST", f"/agencies/proposals/{proposal_id}/reject",
            payload if payload is not None else {}, headers,
        )


api_client = ApiClient()
