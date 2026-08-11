"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- students ---
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/students", headers=headers, params=params)

    # --- offense codes & sanction bands ---
    def create_offense_code(self, payload, headers):
        return self._request("POST", "/offense-codes", payload, headers)

    def get_offense_code(self, offense_code_id, headers):
        return self._request("GET", f"/offense-codes/{offense_code_id}", headers=headers)

    def create_sanction_band(self, offense_code_id, payload, headers):
        return self._request(
            "POST", f"/offense-codes/{offense_code_id}/sanction-bands", payload, headers
        )

    def list_sanction_bands(self, offense_code_id, headers):
        return self._request(
            "GET", f"/offense-codes/{offense_code_id}/sanction-bands", headers=headers
        )

    # --- discipline cases ---
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def classify_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/classify", payload, headers)

    def propose_sanction(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/sanction", payload, headers)

    def issue_notice(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/notices", payload, headers)

    def list_notices(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}/notices", headers=headers)

    def confirm_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/confirm", payload, headers)

    def close_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/close", payload, headers)

    def refer_expulsion(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/refer-expulsion", payload, headers)

    # --- conferences ---
    def create_conference(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/conferences", payload, headers)

    def list_conferences(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}/conferences", headers=headers)

    def record_conference_outcome(self, conference_id, payload, headers):
        return self._request(
            "POST", f"/conferences/{conference_id}/outcome", payload, headers
        )

    def reschedule_conference(self, conference_id, payload, headers):
        return self._request(
            "POST", f"/conferences/{conference_id}/reschedule", payload, headers
        )

    # --- appeals ---
    def file_appeal(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/appeals", payload, headers)

    def list_appeals(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}/appeals", headers=headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/decision", payload, headers)

    # --- expulsion hearings & evidence ---
    def create_hearing(self, payload, headers):
        return self._request("POST", "/hearings", payload, headers)

    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"/hearings/{hearing_id}", headers=headers)

    def list_hearings(self, headers, params=None):
        return self._request("GET", "/hearings", headers=headers, params=params)

    def submit_evidence(self, hearing_id, payload, headers):
        return self._request("POST", f"/hearings/{hearing_id}/evidence", payload, headers)

    def list_evidence(self, hearing_id, headers):
        return self._request("GET", f"/hearings/{hearing_id}/evidence", headers=headers)

    def rule_evidence(self, evidence_item_id, payload, headers):
        return self._request(
            "POST", f"/evidence-items/{evidence_item_id}/rule", payload, headers
        )

    def serve_packet(self, hearing_id, payload, headers):
        return self._request("POST", f"/hearings/{hearing_id}/serve-packet", payload, headers)

    def convene_hearing(self, hearing_id, payload, headers):
        return self._request("POST", f"/hearings/{hearing_id}/convene", payload, headers)

    def decide_hearing(self, hearing_id, payload, headers):
        return self._request("POST", f"/hearings/{hearing_id}/decision", payload, headers)

    # --- manifestation determinations ---
    def create_manifestation_determination(self, case_id, payload, headers):
        return self._request(
            "POST", f"/cases/{case_id}/manifestation-determinations", payload, headers
        )

    def list_manifestation_determinations(self, case_id, headers):
        return self._request(
            "GET", f"/cases/{case_id}/manifestation-determinations", headers=headers
        )

    def schedule_manifestation_determination(self, mdr_id, payload, headers):
        return self._request(
            "POST", f"/manifestation-determinations/{mdr_id}/schedule", payload, headers
        )

    def complete_manifestation_determination(self, mdr_id, payload, headers):
        return self._request(
            "POST", f"/manifestation-determinations/{mdr_id}/complete", payload, headers
        )

    # --- alternative education sites & placements ---
    def create_alt_ed_site(self, payload, headers):
        return self._request("POST", "/alt-ed-sites", payload, headers)

    def get_alt_ed_site(self, site_id, headers):
        return self._request("GET", f"/alt-ed-sites/{site_id}", headers=headers)

    def create_placement(self, payload, headers):
        return self._request("POST", "/placements", payload, headers)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"/placements/{placement_id}", headers=headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", "/placements", headers=headers, params=params)

    def activate_placement(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/placements/{placement_id}/activate", payload, headers
        )

    def complete_placement(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/placements/{placement_id}/complete", payload, headers
        )

    # --- re-entry plans ---
    def create_re_entry_plan(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/placements/{placement_id}/re-entry-plans", payload, headers
        )

    def list_re_entry_plans(self, placement_id, headers):
        return self._request(
            "GET", f"/placements/{placement_id}/re-entry-plans", headers=headers
        )

    def activate_re_entry_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/re-entry-plans/{plan_id}/activate", payload, headers
        )

    def record_re_entry_outcome(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/re-entry-plans/{plan_id}/outcome", payload, headers
        )

    # --- expungement ---
    def create_expungement_request(self, payload, headers):
        return self._request("POST", "/expungement-requests", payload, headers)

    def list_expungement_requests(self, student_id, headers):
        return self._request(
            "GET", f"/students/{student_id}/expungement-requests", headers=headers
        )

    def decide_expungement_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/expungement-requests/{request_id}/decision", payload, headers
        )

    # --- reports ---
    def get_disproportionality_report(self, headers, params=None):
        return self._request(
            "GET", "/reports/disproportionality", headers=headers, params=params
        )


api_client = ApiClient()
