"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Ops-run delinquency sweep ---
    def run_delinquency_sweep(self, payload, headers):
        return self._request("POST", "/api/system/sweeps/delinquency", payload, headers)

    # --- Locals ---
    def create_local(self, payload, headers):
        return self._request("POST", "/api/locals", payload, headers)

    def get_local(self, local_id, headers):
        return self._request("GET", f"/api/locals/{local_id}", headers=headers)

    def update_local(self, local_id, payload, headers):
        return self._request("PATCH", f"/api/locals/{local_id}", payload, headers)

    def close_local(self, local_id, headers):
        return self._request("POST", f"/api/locals/{local_id}/close", {}, headers)

    # --- Classifications ---
    def create_classification(self, local_id, payload, headers):
        return self._request("POST", f"/api/locals/{local_id}/classifications", payload, headers)

    def list_classifications(self, local_id, headers, params=None):
        return self._request("GET", f"/api/locals/{local_id}/classifications", headers=headers, params=params)

    # --- Members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/api/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/api/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/api/members/{member_id}", headers=headers)

    def create_payment(self, member_id, payload, headers):
        return self._request("POST", f"/api/members/{member_id}/payments", payload, headers)

    def withdraw_member(self, member_id, headers):
        return self._request("POST", f"/api/members/{member_id}/withdraw", {}, headers)

    def get_reinstatement_quote(self, member_id, headers):
        return self._request("GET", f"/api/members/{member_id}/reinstatement-quote", headers=headers)

    def reinstate_member(self, member_id, payload, headers):
        return self._request("POST", f"/api/members/{member_id}/reinstate", payload, headers)

    def list_member_assessments(self, member_id, headers, params=None):
        return self._request("GET", f"/api/members/{member_id}/assessments", headers=headers, params=params)

    def list_member_ledger(self, member_id, headers, params=None):
        return self._request("GET", f"/api/members/{member_id}/ledger", headers=headers, params=params)

    def list_member_remittance_lines(self, member_id, headers, params=None):
        return self._request("GET", f"/api/members/{member_id}/remittance-lines", headers=headers, params=params)

    # --- Assessment runs ---
    def create_assessment_run(self, payload, headers):
        return self._request("POST", "/api/assessment-runs", payload, headers)

    def list_assessment_runs(self, local_id, headers, params=None):
        return self._request("GET", f"/api/locals/{local_id}/assessment-runs", headers=headers, params=params)

    # --- Employers ---
    def create_employer(self, payload, headers):
        return self._request("POST", "/api/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/api/employers/{employer_id}", headers=headers)

    # --- Remittances and lines ---
    def create_remittance(self, payload, headers):
        return self._request("POST", "/api/remittances", payload, headers)

    def list_remittances(self, headers, params=None):
        return self._request("GET", "/api/remittances", headers=headers, params=params)

    def get_remittance(self, remittance_id, headers):
        return self._request("GET", f"/api/remittances/{remittance_id}", headers=headers)

    def create_remittance_line(self, remittance_id, payload, headers):
        return self._request("POST", f"/api/remittances/{remittance_id}/lines", payload, headers)

    def list_remittance_lines(self, remittance_id, headers, params=None):
        return self._request("GET", f"/api/remittances/{remittance_id}/lines", headers=headers, params=params)

    def reconcile_remittance(self, remittance_id, headers):
        return self._request("POST", f"/api/remittances/{remittance_id}/reconcile", {}, headers)

    def resolve_remittance_dispute(self, remittance_id, payload, headers):
        return self._request("POST", f"/api/remittances/{remittance_id}/resolve-dispute", payload, headers)

    def post_remittance(self, remittance_id, headers):
        return self._request("POST", f"/api/remittances/{remittance_id}/post", {}, headers)

    def void_remittance(self, remittance_id, headers):
        return self._request("POST", f"/api/remittances/{remittance_id}/void", {}, headers)

    # --- Delinquency notices ---
    def create_notice(self, member_id, headers):
        return self._request("POST", f"/api/members/{member_id}/notices", {}, headers)

    def list_notices(self, member_id, headers, params=None):
        return self._request("GET", f"/api/members/{member_id}/notices", headers=headers, params=params)

    def send_notice(self, member_id, notice_id, headers):
        return self._request("POST", f"/api/members/{member_id}/notices/{notice_id}/send", {}, headers)

    # --- Objector cases ---
    def create_objector_case(self, member_id, headers):
        return self._request("POST", f"/api/members/{member_id}/objector-cases", {}, headers)

    def list_objector_cases(self, headers, params=None):
        return self._request("GET", "/api/objector-cases", headers=headers, params=params)

    def get_objector_case(self, case_id, headers):
        return self._request("GET", f"/api/objector-cases/{case_id}", headers=headers)

    def get_rebate_projection(self, case_id, headers):
        return self._request("GET", f"/api/objector-cases/{case_id}/rebate-projection", headers=headers)

    def set_objector_rate(self, case_id, payload, headers):
        return self._request("POST", f"/api/objector-cases/{case_id}/set-rate", payload, headers)

    def issue_rebate(self, case_id, headers):
        return self._request("POST", f"/api/objector-cases/{case_id}/issue-rebate", {}, headers)

    def appeal_objector_case(self, case_id, headers):
        return self._request("POST", f"/api/objector-cases/{case_id}/appeal", {}, headers)

    def close_objector_case(self, case_id, headers):
        return self._request("POST", f"/api/objector-cases/{case_id}/close", {}, headers)

    # --- Member transfers ---
    def create_transfer(self, member_id, payload, headers):
        return self._request("POST", f"/api/members/{member_id}/transfers", payload, headers)

    def list_transfers(self, headers, params=None):
        return self._request("GET", "/api/transfers", headers=headers, params=params)

    def get_transfer(self, transfer_id, headers):
        return self._request("GET", f"/api/transfers/{transfer_id}", headers=headers)

    def certify_transfer(self, transfer_id, headers):
        return self._request("POST", f"/api/transfers/{transfer_id}/certify", {}, headers)

    def accept_transfer(self, transfer_id, headers):
        return self._request("POST", f"/api/transfers/{transfer_id}/accept", {}, headers)

    def reject_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"/api/transfers/{transfer_id}/reject", payload, headers)

    def complete_transfer(self, transfer_id, headers):
        return self._request("POST", f"/api/transfers/{transfer_id}/complete", {}, headers)

    def cancel_transfer(self, transfer_id, headers):
        return self._request("POST", f"/api/transfers/{transfer_id}/cancel", {}, headers)

    # --- Per-capita reports ---
    def create_percapita_report(self, local_id, payload, headers):
        return self._request("POST", f"/api/locals/{local_id}/per-capita-reports", payload, headers)

    def list_percapita_reports(self, local_id, headers, params=None):
        return self._request("GET", f"/api/locals/{local_id}/per-capita-reports", headers=headers, params=params)

    def approve_percapita_report(self, report_id, headers):
        return self._request("POST", f"/api/per-capita-reports/{report_id}/approve", {}, headers)

    def submit_percapita_report(self, report_id, headers):
        return self._request("POST", f"/api/per-capita-reports/{report_id}/submit", {}, headers)

    def mark_percapita_report_paid(self, report_id, headers):
        return self._request("POST", f"/api/per-capita-reports/{report_id}/mark-paid", {}, headers)

    # --- Elections and eligibility ---
    def create_election(self, local_id, payload, headers):
        return self._request("POST", f"/api/locals/{local_id}/elections", payload, headers)

    def list_elections(self, headers, params=None):
        return self._request("GET", "/api/elections", headers=headers, params=params)

    def get_election(self, election_id, headers):
        return self._request("GET", f"/api/elections/{election_id}", headers=headers)

    def open_nominations(self, election_id, headers):
        return self._request("POST", f"/api/elections/{election_id}/open-nominations", {}, headers)

    def freeze_eligibility(self, election_id, headers):
        return self._request("POST", f"/api/elections/{election_id}/freeze-eligibility", {}, headers)

    def conclude_election(self, election_id, headers):
        return self._request("POST", f"/api/elections/{election_id}/conclude", {}, headers)

    def list_election_eligibilities(self, election_id, headers, params=None):
        return self._request("GET", f"/api/elections/{election_id}/eligibilities", headers=headers, params=params)

    def list_member_eligibilities(self, member_id, headers, params=None):
        return self._request("GET", f"/api/members/{member_id}/eligibilities", headers=headers, params=params)


api_client = ApiClient()
