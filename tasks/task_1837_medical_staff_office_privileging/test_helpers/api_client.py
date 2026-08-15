"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/mso/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Specialty criteria
    # ------------------------------------------------------------------
    def create_specialty_criteria(self, payload, headers):
        return self._request("POST", "/mso/specialty-criteria", payload, headers)

    def list_specialty_criteria(self, headers, params=None):
        return self._request("GET", "/mso/specialty-criteria", headers=headers,
                             params=params)

    def get_specialty_criteria(self, criteria_id, headers):
        return self._request("GET", f"/mso/specialty-criteria/{criteria_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Medical staff members
    # ------------------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", "/mso/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/mso/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/mso/members/{member_id}", headers=headers)

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/mso/members/{member_id}/reinstate",
                             {}, headers)

    def get_credential_risk(self, member_id, headers, params=None):
        return self._request("GET", f"/mso/members/{member_id}/credential-risk",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Applications
    # ------------------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/mso/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/mso/applications", headers=headers,
                             params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/mso/applications/{application_id}",
                             headers=headers)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/mso/applications/{application_id}/submit",
                             {}, headers)

    def advance_application_to_committee(self, application_id, headers):
        return self._request(
            "POST", f"/mso/applications/{application_id}/advance-to-committee",
            {}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST",
                             f"/mso/applications/{application_id}/withdraw",
                             {}, headers)

    # ------------------------------------------------------------------
    # Verification items
    # ------------------------------------------------------------------
    def create_verification_item(self, payload, headers):
        return self._request("POST", "/mso/verification-items", payload, headers)

    def list_verification_items(self, headers, params=None):
        return self._request("GET", "/mso/verification-items", headers=headers,
                             params=params)

    def get_verification_item(self, item_id, headers):
        return self._request("GET", f"/mso/verification-items/{item_id}",
                             headers=headers)

    def mark_verification_item_received(self, item_id, headers):
        return self._request(
            "POST", f"/mso/verification-items/{item_id}/mark-received", {}, headers)

    def verify_verification_item(self, item_id, headers):
        return self._request("POST",
                             f"/mso/verification-items/{item_id}/verify",
                             {}, headers)

    def flag_verification_item_discrepancy(self, item_id, discrepancy_note, headers):
        return self._request(
            "POST", f"/mso/verification-items/{item_id}/flag-discrepancy",
            {"discrepancy_note": discrepancy_note}, headers)

    def waive_verification_item(self, item_id, waiver_justification, headers):
        return self._request("POST",
                             f"/mso/verification-items/{item_id}/waive",
                             {"waiver_justification": waiver_justification},
                             headers)

    # ------------------------------------------------------------------
    # Privilege delineations
    # ------------------------------------------------------------------
    def create_delineation(self, payload, headers):
        return self._request("POST", "/mso/delineations", payload, headers)

    def list_delineations(self, headers, params=None):
        return self._request("GET", "/mso/delineations", headers=headers,
                             params=params)

    def get_delineation(self, delineation_id, headers):
        return self._request("GET", f"/mso/delineations/{delineation_id}",
                             headers=headers)

    def evaluate_delineation(self, delineation_id, headers):
        return self._request("POST",
                             f"/mso/delineations/{delineation_id}/evaluate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Privilege grants
    # ------------------------------------------------------------------
    def list_privilege_grants(self, headers, params=None):
        return self._request("GET", "/mso/privilege-grants", headers=headers,
                             params=params)

    def get_privilege_grant(self, grant_id, headers):
        return self._request("GET", f"/mso/privilege-grants/{grant_id}",
                             headers=headers)

    def relinquish_privilege_grant(self, grant_id, headers):
        return self._request("POST",
                             f"/mso/privilege-grants/{grant_id}/relinquish",
                             {}, headers)

    # ------------------------------------------------------------------
    # Performance reviews
    # ------------------------------------------------------------------
    def create_performance_review(self, payload, headers):
        return self._request("POST", "/mso/performance-reviews", payload, headers)

    def list_performance_reviews(self, headers, params=None):
        return self._request("GET", "/mso/performance-reviews", headers=headers,
                             params=params)

    def get_performance_review(self, review_id, headers):
        return self._request("GET", f"/mso/performance-reviews/{review_id}",
                             headers=headers)

    def close_review_collection(self, review_id, headers):
        return self._request(
            "POST", f"/mso/performance-reviews/{review_id}/close-collection",
            {}, headers)

    def compute_review_provisional(self, review_id, headers):
        return self._request(
            "POST", f"/mso/performance-reviews/{review_id}/compute-provisional",
            {}, headers)

    def finalize_performance_review(self, review_id, headers):
        return self._request(
            "POST", f"/mso/performance-reviews/{review_id}/finalize", {}, headers)

    def close_performance_review(self, review_id, headers):
        return self._request(
            "POST", f"/mso/performance-reviews/{review_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Performance metrics
    # ------------------------------------------------------------------
    def create_performance_metric(self, payload, headers):
        return self._request("POST", "/mso/performance-metrics", payload, headers)

    def list_performance_metrics(self, headers, params=None):
        return self._request("GET", "/mso/performance-metrics", headers=headers,
                             params=params)

    def get_performance_metric(self, metric_id, headers):
        return self._request("GET", f"/mso/performance-metrics/{metric_id}",
                             headers=headers)

    def retract_performance_metric(self, metric_id, headers):
        return self._request(
            "POST", f"/mso/performance-metrics/{metric_id}/retract", {}, headers)

    # ------------------------------------------------------------------
    # Expirable credentials
    # ------------------------------------------------------------------
    def create_expirable_credential(self, payload, headers):
        return self._request("POST", "/mso/expirable-credentials", payload, headers)

    def list_expirable_credentials(self, headers, params=None):
        return self._request("GET", "/mso/expirable-credentials", headers=headers,
                             params=params)

    def get_expirable_credential(self, credential_id, headers):
        return self._request("GET", f"/mso/expirable-credentials/{credential_id}",
                             headers=headers)

    def renew_expirable_credential(self, credential_id, payload, headers):
        return self._request(
            "POST", f"/mso/expirable-credentials/{credential_id}/renew",
            payload, headers)

    def revoke_expirable_credential(self, credential_id, headers):
        return self._request(
            "POST", f"/mso/expirable-credentials/{credential_id}/revoke",
            {}, headers)

    # ------------------------------------------------------------------
    # Temporary privileges
    # ------------------------------------------------------------------
    def create_temporary_privilege(self, payload, headers):
        return self._request("POST", "/mso/temporary-privileges", payload, headers)

    def list_temporary_privileges(self, headers, params=None):
        return self._request("GET", "/mso/temporary-privileges", headers=headers,
                             params=params)

    def get_temporary_privilege(self, temp_id, headers):
        return self._request("GET", f"/mso/temporary-privileges/{temp_id}",
                             headers=headers)

    def activate_temporary_privilege(self, temp_id, headers):
        return self._request(
            "POST", f"/mso/temporary-privileges/{temp_id}/activate", {}, headers)

    def terminate_temporary_privilege(self, temp_id, headers):
        return self._request(
            "POST", f"/mso/temporary-privileges/{temp_id}/terminate", {}, headers)

    # ------------------------------------------------------------------
    # Adverse action cases & hearings
    # ------------------------------------------------------------------
    def create_adverse_action_case(self, payload, headers):
        return self._request("POST", "/mso/adverse-action-cases", payload, headers)

    def list_adverse_action_cases(self, headers, params=None):
        return self._request("GET", "/mso/adverse-action-cases", headers=headers,
                             params=params)

    def get_adverse_action_case(self, case_id, headers):
        return self._request("GET", f"/mso/adverse-action-cases/{case_id}",
                             headers=headers)

    def endorse_adverse_action_case(self, case_id, headers):
        return self._request(
            "POST", f"/mso/adverse-action-cases/{case_id}/endorse", {}, headers)

    def withdraw_adverse_action_case(self, case_id, headers):
        return self._request(
            "POST", f"/mso/adverse-action-cases/{case_id}/withdraw", {}, headers)

    def request_hearing(self, case_id, headers):
        return self._request(
            "POST", f"/mso/adverse-action-cases/{case_id}/request-hearing",
            {}, headers)

    def hold_hearing(self, case_id, headers):
        return self._request(
            "POST", f"/mso/adverse-action-cases/{case_id}/hold-hearing",
            {}, headers)

    def decide_adverse_action_case(self, case_id, decision, headers):
        return self._request(
            "POST", f"/mso/adverse-action-cases/{case_id}/decide",
            {"decision": decision}, headers)

    # ------------------------------------------------------------------
    # Hearing panels
    # ------------------------------------------------------------------
    def create_hearing_panel(self, payload, headers):
        return self._request("POST", "/mso/hearing-panels", payload, headers)

    def list_hearing_panels(self, headers, params=None):
        return self._request("GET", "/mso/hearing-panels", headers=headers,
                             params=params)

    def get_hearing_panel(self, panel_id, headers):
        return self._request("GET", f"/mso/hearing-panels/{panel_id}",
                             headers=headers)

    def recuse_hearing_panel(self, panel_id, headers):
        return self._request("POST", f"/mso/hearing-panels/{panel_id}/recuse",
                             {}, headers)

    # ------------------------------------------------------------------
    # NPDB reports
    # ------------------------------------------------------------------
    def create_npdb_report(self, payload, headers):
        return self._request("POST", "/mso/npdb-reports", payload, headers)

    def list_npdb_reports(self, headers, params=None):
        return self._request("GET", "/mso/npdb-reports", headers=headers,
                             params=params)

    def get_npdb_report(self, report_id, headers):
        return self._request("GET", f"/mso/npdb-reports/{report_id}",
                             headers=headers)

    def acknowledge_npdb_report(self, report_id, headers):
        return self._request(
            "POST", f"/mso/npdb-reports/{report_id}/acknowledge", {}, headers)

    def void_npdb_report(self, report_id, correction_report_id, headers):
        return self._request("POST", f"/mso/npdb-reports/{report_id}/void",
                             {"correction_report_id": correction_report_id},
                             headers)

    # ------------------------------------------------------------------
    # Committee agenda items
    # ------------------------------------------------------------------
    def create_agenda_item(self, payload, headers):
        return self._request("POST", "/mso/agenda-items", payload, headers)

    def list_agenda_items(self, headers, params=None):
        return self._request("GET", "/mso/agenda-items", headers=headers,
                             params=params)

    def get_agenda_item(self, item_id, headers):
        return self._request("GET", f"/mso/agenda-items/{item_id}",
                             headers=headers)

    def committee_vote_agenda_item(self, item_id, votes_for, votes_against, headers):
        return self._request(
            "POST", f"/mso/agenda-items/{item_id}/committee-vote",
            {"votes_for": votes_for, "votes_against": votes_against}, headers)

    def defer_agenda_item(self, item_id, headers):
        return self._request("POST", f"/mso/agenda-items/{item_id}/defer",
                             {}, headers)

    def reagenda_agenda_item(self, item_id, headers):
        return self._request("POST", f"/mso/agenda-items/{item_id}/reagenda",
                             {}, headers)

    def mec_endorse_agenda_item(self, item_id, voter_id, headers):
        return self._request("POST",
                             f"/mso/agenda-items/{item_id}/mec-endorse",
                             {"voter_id": voter_id}, headers)

    def board_ratify_agenda_item(self, item_id, headers):
        return self._request("POST",
                             f"/mso/agenda-items/{item_id}/board-ratify",
                             {}, headers)

    def board_decline_agenda_item(self, item_id, headers):
        return self._request("POST",
                             f"/mso/agenda-items/{item_id}/board-decline",
                             {}, headers)


api_client = ApiClient()
