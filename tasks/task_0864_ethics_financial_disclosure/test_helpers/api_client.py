"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Jurisdiction ----
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/jurisdictions/{jurisdiction_id}", headers=headers)

    # ---- Filer ----
    def create_filer(self, payload, headers):
        return self._request("POST", "/filers", payload, headers)

    def get_filer(self, filer_id, headers):
        return self._request("GET", f"/filers/{filer_id}", headers=headers)

    def list_filers(self, headers, params=None):
        return self._request("GET", "/filers", headers=headers, params=params)

    def set_filer_status(self, filer_id, payload, headers):
        return self._request("PATCH", f"/filers/{filer_id}/status", payload, headers)

    # ---- FilingPeriod ----
    def create_filing_period(self, payload, headers):
        return self._request("POST", "/filing-periods", payload, headers)

    def get_filing_period(self, period_id, headers):
        return self._request("GET", f"/filing-periods/{period_id}", headers=headers)

    def list_filing_periods(self, headers, params=None):
        return self._request("GET", "/filing-periods", headers=headers, params=params)

    # ---- Statement ----
    def create_statement(self, payload, headers):
        return self._request("POST", "/statements", payload, headers)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/statements/{statement_id}", headers=headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/statements", headers=headers, params=params)

    def submit_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/statements/{statement_id}/submit", payload, headers)

    def accept_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/statements/{statement_id}/accept", payload, headers)

    def return_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/statements/{statement_id}/return", payload, headers)

    def publish_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/statements/{statement_id}/publish", payload, headers)

    # ---- GiftReport ----
    def create_gift_report(self, payload, headers):
        return self._request("POST", "/gift-reports", payload, headers)

    def get_gift_report(self, gift_id, headers):
        return self._request("GET", f"/gift-reports/{gift_id}", headers=headers)

    def list_gift_reports(self, headers, params=None):
        return self._request("GET", "/gift-reports", headers=headers, params=params)

    def dispose_gift_report(self, gift_id, payload, headers):
        return self._request("POST", f"/gift-reports/{gift_id}/dispose", payload, headers)

    # ---- RecusalEntry ----
    def create_recusal(self, payload, headers):
        return self._request("POST", "/recusals", payload, headers)

    def get_recusal(self, recusal_id, headers):
        return self._request("GET", f"/recusals/{recusal_id}", headers=headers)

    def list_recusals(self, headers, params=None):
        return self._request("GET", "/recusals", headers=headers, params=params)

    def resolve_recusal(self, recusal_id, payload, headers):
        return self._request("POST", f"/recusals/{recusal_id}/resolve", payload, headers)

    # ---- Penalty ----
    def get_penalty(self, penalty_id, headers):
        return self._request("GET", f"/penalties/{penalty_id}", headers=headers)

    def list_penalties(self, headers, params=None):
        return self._request("GET", "/penalties", headers=headers, params=params)

    def pay_penalty(self, penalty_id, payload, headers):
        return self._request("POST", f"/penalties/{penalty_id}/pay", payload, headers)

    def waive_penalty(self, penalty_id, payload, headers):
        return self._request("POST", f"/penalties/{penalty_id}/waive", payload, headers)

    # ---- Complaint ----
    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def screen_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/screen", payload, headers)

    # ---- Investigation ----
    def open_investigation(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/investigations", payload, headers)

    def get_investigation(self, investigation_id, headers):
        return self._request("GET", f"/investigations/{investigation_id}", headers=headers)

    def list_investigations(self, headers, params=None):
        return self._request("GET", "/investigations", headers=headers, params=params)

    def adjudicate_investigation(self, investigation_id, payload, headers):
        return self._request("POST", f"/investigations/{investigation_id}/adjudicate", payload, headers)

    def reopen_investigation(self, investigation_id, payload, headers):
        return self._request("POST", f"/investigations/{investigation_id}/reopen", payload, headers)

    # ---- TrainingRecord ----
    def create_training_record(self, payload, headers):
        return self._request("POST", "/training-records", payload, headers)

    def get_training_record(self, record_id, headers):
        return self._request("GET", f"/training-records/{record_id}", headers=headers)

    def list_training_records(self, headers, params=None):
        return self._request("GET", "/training-records", headers=headers, params=params)

    def complete_training_record(self, record_id, payload, headers):
        return self._request("POST", f"/training-records/{record_id}/complete", payload, headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
