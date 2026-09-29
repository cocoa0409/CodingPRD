"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint surface of the Livestock Mandatory Price Reporting API."""

    # -- Reporting entities -------------------------------------------------

    def create_reporting_entity(self, payload, headers):
        return self._request("POST", "/reporting-entities", payload, headers)

    def get_reporting_entity(self, entity_id, headers):
        return self._request(
            "GET", f"/reporting-entities/{entity_id}", headers=headers
        )

    def list_reporting_entities(self, headers, params=None):
        return self._request(
            "GET", "/reporting-entities", headers=headers, params=params
        )

    # -- Plants -------------------------------------------------------------

    def create_plant(self, payload, headers):
        return self._request("POST", "/plants", payload, headers)

    def update_plant(self, plant_id, payload, headers):
        return self._request("PATCH", f"/plants/{plant_id}", payload, headers)

    def get_plant(self, plant_id, headers):
        return self._request("GET", f"/plants/{plant_id}", headers=headers)

    def list_plants(self, headers, params=None):
        return self._request("GET", "/plants", headers=headers, params=params)

    # -- Registrations ------------------------------------------------------

    def create_registration(self, payload, headers):
        return self._request("POST", "/registrations", payload, headers)

    def determine_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/determine", {}, headers
        )

    def appeal_registration(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/appeal", payload, headers
        )

    def redetermine_registration(self, registration_id, payload, headers):
        return self._request(
            "POST",
            f"/registrations/{registration_id}/redetermine",
            payload,
            headers,
        )

    def activate_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/activate", {}, headers
        )

    def suspend_registration(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/suspend", payload, headers
        )

    def get_registration(self, registration_id, headers):
        return self._request(
            "GET", f"/registrations/{registration_id}", headers=headers
        )

    def list_registrations(self, headers, params=None):
        return self._request(
            "GET", "/registrations", headers=headers, params=params
        )

    # -- Reporting windows --------------------------------------------------

    def create_reporting_window(self, payload, headers):
        return self._request("POST", "/reporting-windows", payload, headers)

    def lock_reporting_window(self, window_id, headers):
        return self._request(
            "POST", f"/reporting-windows/{window_id}/lock", {}, headers
        )

    def get_reporting_window(self, window_id, headers):
        return self._request(
            "GET", f"/reporting-windows/{window_id}", headers=headers
        )

    def list_reporting_windows(self, headers, params=None):
        return self._request(
            "GET", "/reporting-windows", headers=headers, params=params
        )

    # -- Submissions --------------------------------------------------------

    def create_submission(self, payload, headers):
        return self._request("POST", "/submissions", payload, headers)

    def add_transaction(self, submission_id, payload, headers):
        return self._request(
            "POST", f"/submissions/{submission_id}/transactions", payload, headers
        )

    def add_wholesale_lot(self, submission_id, payload, headers):
        return self._request(
            "POST",
            f"/submissions/{submission_id}/wholesale-lots",
            payload,
            headers,
        )

    def submit_submission(self, submission_id, headers):
        return self._request(
            "POST", f"/submissions/{submission_id}/submit", {}, headers
        )

    def review_submission(self, submission_id, payload, headers):
        return self._request(
            "POST", f"/submissions/{submission_id}/review", payload, headers
        )

    def open_correction(self, submission_id, payload, headers):
        return self._request(
            "POST",
            f"/submissions/{submission_id}/open-correction",
            payload,
            headers,
        )

    def resubmit_submission(self, submission_id, headers):
        return self._request(
            "POST", f"/submissions/{submission_id}/resubmit", {}, headers
        )

    def get_submission(self, submission_id, headers):
        return self._request(
            "GET", f"/submissions/{submission_id}", headers=headers
        )

    def list_submissions(self, headers, params=None):
        return self._request("GET", "/submissions", headers=headers, params=params)

    def list_transactions(self, submission_id, headers, params=None):
        return self._request(
            "GET",
            f"/submissions/{submission_id}/transactions",
            headers=headers,
            params=params,
        )

    def list_wholesale_lots(self, submission_id, headers, params=None):
        return self._request(
            "GET",
            f"/submissions/{submission_id}/wholesale-lots",
            headers=headers,
            params=params,
        )

    # -- Market reports -----------------------------------------------------

    def create_market_report(self, payload, headers):
        return self._request("POST", "/market-reports", payload, headers)

    def compute_market_report(self, report_id, headers):
        return self._request(
            "POST", f"/market-reports/{report_id}/compute", {}, headers
        )

    def disclosure_review_market_report(self, report_id, headers):
        return self._request(
            "POST", f"/market-reports/{report_id}/disclosure-review", {}, headers
        )

    def publish_market_report(self, report_id, headers):
        return self._request(
            "POST", f"/market-reports/{report_id}/publish", {}, headers
        )

    def get_market_report(self, report_id, headers):
        return self._request(
            "GET", f"/market-reports/{report_id}", headers=headers
        )

    def list_market_reports(self, headers, params=None):
        return self._request(
            "GET", "/market-reports", headers=headers, params=params
        )

    # -- Audit cases --------------------------------------------------------

    def create_audit_case(self, payload, headers):
        return self._request("POST", "/audit-cases", payload, headers)

    def start_fieldwork(self, case_id, headers):
        return self._request(
            "POST", f"/audit-cases/{case_id}/start-fieldwork", {}, headers
        )

    def finalize_audit_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/audit-cases/{case_id}/finalize", payload, headers
        )

    def close_audit_case(self, case_id, headers):
        return self._request(
            "POST", f"/audit-cases/{case_id}/close", {}, headers
        )

    def get_audit_case(self, case_id, headers):
        return self._request("GET", f"/audit-cases/{case_id}", headers=headers)

    def list_audit_cases(self, headers, params=None):
        return self._request("GET", "/audit-cases", headers=headers, params=params)

    # -- Penalty assessments ------------------------------------------------

    def create_penalty_assessment(self, payload, headers):
        return self._request("POST", "/penalty-assessments", payload, headers)

    def pay_penalty_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST",
            f"/penalty-assessments/{assessment_id}/pay",
            payload,
            headers,
        )

    def waive_penalty_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST",
            f"/penalty-assessments/{assessment_id}/waive",
            payload,
            headers,
        )

    def get_penalty_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"/penalty-assessments/{assessment_id}", headers=headers
        )

    def list_penalty_assessments(self, headers, params=None):
        return self._request(
            "GET", "/penalty-assessments", headers=headers, params=params
        )

    # -- Methodology changes ------------------------------------------------

    def create_methodology_change(self, payload, headers):
        return self._request("POST", "/methodology-changes", payload, headers)

    def create_public_comment(self, change_id, payload, headers):
        return self._request(
            "POST",
            f"/methodology-changes/{change_id}/comments",
            payload,
            headers,
        )

    def close_comment_period(self, change_id, headers):
        return self._request(
            "POST",
            f"/methodology-changes/{change_id}/close-comment",
            {},
            headers,
        )

    def adopt_methodology_change(self, change_id, headers):
        return self._request(
            "POST", f"/methodology-changes/{change_id}/adopt", {}, headers
        )

    def get_methodology_change(self, change_id, headers):
        return self._request(
            "GET", f"/methodology-changes/{change_id}", headers=headers
        )

    def list_methodology_changes(self, headers, params=None):
        return self._request(
            "GET", "/methodology-changes", headers=headers, params=params
        )

    def list_public_comments(self, change_id, headers, params=None):
        return self._request(
            "GET",
            f"/methodology-changes/{change_id}/comments",
            headers=headers,
            params=params,
        )

    # -- Logical clock ------------------------------------------------------

    def set_clock(self, current_utc, headers):
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )


api_client = ApiClient()
