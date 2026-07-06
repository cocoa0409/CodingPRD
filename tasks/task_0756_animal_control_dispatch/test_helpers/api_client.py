"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Complaint ----
    def create_complaint(self, payload, headers):
        return self._request("POST", "/dispatch/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/dispatch/complaints/{complaint_id}", headers=headers)

    # ---- Officer ----
    def create_officer(self, payload, headers):
        return self._request("POST", "/dispatch/officers", payload, headers)

    def get_officer(self, officer_id, headers):
        return self._request("GET", f"/dispatch/officers/{officer_id}", headers=headers)

    # ---- Kennel ----
    def create_kennel(self, payload, headers):
        return self._request("POST", "/dispatch/kennels", payload, headers)

    def get_kennel(self, kennel_id, headers):
        return self._request("GET", f"/dispatch/kennels/{kennel_id}", headers=headers)

    # ---- Dispatch ----
    def create_dispatch(self, payload, headers):
        return self._request("POST", "/dispatch/dispatches", payload, headers)

    def get_dispatch(self, dispatch_id, headers):
        return self._request("GET", f"/dispatch/dispatches/{dispatch_id}", headers=headers)

    def list_dispatches(self, headers, params=None):
        return self._request("GET", "/dispatch/dispatches", headers=headers, params=params)

    def accept_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/dispatch/dispatches/{dispatch_id}/accept", {}, headers)

    def clear_dispatch(self, dispatch_id, payload, headers):
        return self._request("POST", f"/dispatch/dispatches/{dispatch_id}/clear", payload, headers)

    # ---- Case ----
    def create_case(self, payload, headers):
        return self._request("POST", "/dispatch/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/dispatch/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/dispatch/cases", headers=headers, params=params)

    def investigate_case(self, case_id, headers):
        return self._request("POST", f"/dispatch/cases/{case_id}/investigate", {}, headers)

    def resolve_case(self, case_id, payload, headers):
        return self._request("POST", f"/dispatch/cases/{case_id}/resolve", payload, headers)

    def close_case(self, case_id, headers):
        return self._request("POST", f"/dispatch/cases/{case_id}/close", {}, headers)

    def add_note(self, case_id, payload, headers):
        return self._request("POST", f"/dispatch/cases/{case_id}/notes", payload, headers)

    def list_notes(self, case_id, headers, params=None):
        return self._request("GET", f"/dispatch/cases/{case_id}/notes", headers=headers, params=params)

    # ---- QuarantineHold ----
    def create_quarantine_hold(self, payload, headers):
        return self._request("POST", "/dispatch/quarantine-holds", payload, headers)

    def get_quarantine_hold(self, hold_id, headers):
        return self._request("GET", f"/dispatch/quarantine-holds/{hold_id}", headers=headers)

    def list_quarantine_holds(self, headers, params=None):
        return self._request("GET", "/dispatch/quarantine-holds", headers=headers, params=params)

    def release_quarantine_hold(self, hold_id, headers):
        return self._request("POST", f"/dispatch/quarantine-holds/{hold_id}/release", {}, headers)

    def escalate_quarantine_hold(self, hold_id, headers):
        return self._request("POST", f"/dispatch/quarantine-holds/{hold_id}/escalate", {}, headers)

    # ---- Impound ----
    def create_impound(self, payload, headers):
        return self._request("POST", "/dispatch/impounds", payload, headers)

    def get_impound(self, impound_id, headers):
        return self._request("GET", f"/dispatch/impounds/{impound_id}", headers=headers)

    def list_impounds(self, headers, params=None):
        return self._request("GET", "/dispatch/impounds", headers=headers, params=params)

    def release_impound(self, impound_id, payload, headers):
        return self._request("POST", f"/dispatch/impounds/{impound_id}/release", payload, headers)

    # ---- Citation ----
    def create_citation(self, payload, headers):
        return self._request("POST", "/dispatch/citations", payload, headers)

    def get_citation(self, citation_id, headers):
        return self._request("GET", f"/dispatch/citations/{citation_id}", headers=headers)

    def list_citations(self, headers, params=None):
        return self._request("GET", "/dispatch/citations", headers=headers, params=params)

    def pay_citation(self, citation_id, headers):
        return self._request("POST", f"/dispatch/citations/{citation_id}/pay", {}, headers)

    def refer_citation_to_court(self, citation_id, headers):
        return self._request("POST", f"/dispatch/citations/{citation_id}/refer-court", {}, headers)

    # ---- RabiesReport ----
    def create_rabies_report(self, payload, headers):
        return self._request("POST", "/dispatch/rabies-reports", payload, headers)

    def get_rabies_report(self, report_id, headers):
        return self._request("GET", f"/dispatch/rabies-reports/{report_id}", headers=headers)

    def list_rabies_reports(self, headers, params=None):
        return self._request("GET", "/dispatch/rabies-reports", headers=headers, params=params)

    def clear_rabies_report(self, report_id, headers):
        return self._request("POST", f"/dispatch/rabies-reports/{report_id}/clear", {}, headers)

    # ---- Reporting ----
    def get_summary(self, headers):
        return self._request("GET", "/dispatch/reports/summary", headers=headers)

    # ---- Test-driving logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
