"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Configuration: substances ---
    def create_substance(self, payload, headers):
        return self._request("POST", "/substances", payload, headers=headers)

    def get_substance(self, substance_id, headers):
        return self._request("GET", f"/substances/{substance_id}", headers=headers)

    # --- Configuration: healthcare facilities ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/healthcare-facilities", payload, headers=headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/healthcare-facilities/{facility_id}", headers=headers)

    # --- Configuration: protocols ---
    def create_protocol(self, payload, headers):
        return self._request("POST", "/protocols", payload, headers=headers)

    # --- Configuration: specialists ---
    def create_specialist(self, payload, headers):
        return self._request("POST", "/specialists", payload, headers=headers)

    # --- Exposure cases ---
    def create_case(self, payload, headers):
        return self._request("POST", "/exposure-cases", payload, headers=headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/exposure-cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/exposure-cases", headers=headers, params=params)

    def triage_case(self, case_id, headers):
        return self._request("POST", f"/exposure-cases/{case_id}/triage", {}, headers=headers)

    def close_case(self, case_id, headers):
        return self._request("POST", f"/exposure-cases/{case_id}/close", {}, headers=headers)

    # --- Exposures ---
    def create_exposure(self, case_id, payload, headers):
        return self._request("POST", f"/exposure-cases/{case_id}/exposures", payload, headers=headers)

    def get_exposure(self, exposure_id, headers):
        return self._request("GET", f"/exposures/{exposure_id}", headers=headers)

    def list_exposures(self, headers, params=None):
        return self._request("GET", "/exposures", headers=headers, params=params)

    # --- Risk assessments ---
    def create_risk_assessment(self, case_id, payload, headers):
        return self._request("POST", f"/exposure-cases/{case_id}/risk-assessments", payload, headers=headers)

    def get_risk_assessment(self, assessment_id, headers):
        return self._request("GET", f"/risk-assessments/{assessment_id}", headers=headers)

    def list_risk_assessments(self, headers, params=None):
        return self._request("GET", "/risk-assessments", headers=headers, params=params)

    def finalize_risk_assessment(self, assessment_id, headers):
        return self._request("POST", f"/risk-assessments/{assessment_id}/finalize", {}, headers=headers)

    # --- Dispositions ---
    def create_disposition(self, case_id, payload, headers):
        return self._request("POST", f"/exposure-cases/{case_id}/dispositions", payload, headers=headers)

    def get_disposition(self, disposition_id, headers):
        return self._request("GET", f"/dispositions/{disposition_id}", headers=headers)

    def list_dispositions(self, headers, params=None):
        return self._request("GET", "/dispositions", headers=headers, params=params)

    # --- Follow-up calls ---
    def create_follow_up_call(self, case_id, payload, headers):
        return self._request("POST", f"/exposure-cases/{case_id}/follow-up-calls", payload, headers=headers)

    def get_follow_up_call(self, call_id, headers):
        return self._request("GET", f"/follow-up-calls/{call_id}", headers=headers)

    def list_follow_up_calls(self, headers, params=None):
        return self._request("GET", "/follow-up-calls", headers=headers, params=params)

    def attempt_follow_up_call(self, call_id, headers):
        return self._request("POST", f"/follow-up-calls/{call_id}/attempt", {}, headers=headers)

    def complete_follow_up_call(self, call_id, payload, headers):
        return self._request("POST", f"/follow-up-calls/{call_id}/complete", payload, headers=headers)

    # --- Facility consults ---
    def create_facility_consult(self, payload, headers):
        return self._request("POST", "/facility-consults", payload, headers=headers)

    def get_facility_consult(self, consult_id, headers):
        return self._request("GET", f"/facility-consults/{consult_id}", headers=headers)

    def list_facility_consults(self, headers, params=None):
        return self._request("GET", "/facility-consults", headers=headers, params=params)

    def close_facility_consult(self, consult_id, payload, headers):
        return self._request("POST", f"/facility-consults/{consult_id}/close", payload, headers=headers)

    # --- NPDS reports ---
    def create_npds_report(self, payload, headers):
        return self._request("POST", "/npds-reports", payload, headers=headers)

    def get_npds_report(self, report_id, headers):
        return self._request("GET", f"/npds-reports/{report_id}", headers=headers)

    def list_npds_reports(self, headers, params=None):
        return self._request("GET", "/npds-reports", headers=headers, params=params)

    def retract_npds_report(self, report_id, headers):
        return self._request("POST", f"/npds-reports/{report_id}/retract", {}, headers=headers)

    # --- Case notes ---
    def create_note(self, case_id, payload, headers):
        return self._request("POST", f"/exposure-cases/{case_id}/notes", payload, headers=headers)

    def list_notes(self, case_id, headers, params=None):
        return self._request("GET", f"/exposure-cases/{case_id}/notes", headers=headers, params=params)

    # --- Logical clock control ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers)


api_client = ApiClient()
