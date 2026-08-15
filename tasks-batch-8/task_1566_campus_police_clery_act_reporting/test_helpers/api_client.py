"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- clery geographies ---
    def create_geography(self, payload, headers):
        return self._request("POST", "/clery-geographies", payload, headers)

    def list_geographies(self, headers, params=None):
        return self._request("GET", "/clery-geographies", headers=headers, params=params)

    def get_geography(self, geography_id, headers):
        return self._request("GET", f"/clery-geographies/{geography_id}", headers=headers)

    def update_geography(self, geography_id, payload, headers):
        return self._request("PATCH", f"/clery-geographies/{geography_id}", payload, headers)

    # --- campus security authorities ---
    def create_csa(self, payload, headers):
        return self._request("POST", "/campus-security-authorities", payload, headers)

    def list_csas(self, headers, params=None):
        return self._request("GET", "/campus-security-authorities", headers=headers, params=params)

    def get_csa(self, csa_id, headers):
        return self._request("GET", f"/campus-security-authorities/{csa_id}", headers=headers)

    def create_training_record(self, csa_id, payload, headers):
        return self._request(
            "POST", f"/campus-security-authorities/{csa_id}/training-records", payload, headers
        )

    def list_training_records(self, csa_id, headers):
        return self._request(
            "GET", f"/campus-security-authorities/{csa_id}/training-records", headers=headers
        )

    def deactivate_csa(self, csa_id, headers):
        return self._request(
            "POST", f"/campus-security-authorities/{csa_id}/deactivate", {}, headers
        )

    # --- CSA referral reports ---
    def create_referral(self, payload, headers):
        return self._request("POST", "/csa-referral-reports", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/csa-referral-reports", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/csa-referral-reports/{referral_id}", headers=headers)

    def forward_referral(self, referral_id, headers):
        return self._request("POST", f"/csa-referral-reports/{referral_id}/forward", {}, headers)

    def mark_referral_duplicate(self, referral_id, headers):
        return self._request(
            "POST", f"/csa-referral-reports/{referral_id}/mark-duplicate", {}, headers
        )

    # --- incident reports ---
    def create_incident(self, payload, headers):
        return self._request("POST", "/incident-reports", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/incident-reports", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/incident-reports/{incident_id}", headers=headers)

    def submit_incident(self, incident_id, headers):
        return self._request("POST", f"/incident-reports/{incident_id}/submit", {}, headers)

    def begin_classification(self, incident_id, headers):
        return self._request(
            "POST", f"/incident-reports/{incident_id}/begin-classification", {}, headers
        )

    def classify_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/incident-reports/{incident_id}/classify", payload, headers)

    def begin_reclassification(self, incident_id, headers):
        return self._request(
            "POST", f"/incident-reports/{incident_id}/begin-reclassification", {}, headers
        )

    def unfound_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/incident-reports/{incident_id}/unfound", payload, headers)

    def withdraw_incident(self, incident_id, headers):
        return self._request("POST", f"/incident-reports/{incident_id}/withdraw", {}, headers)

    def list_offense_counts(self, incident_id, headers):
        return self._request(
            "GET", f"/incident-reports/{incident_id}/offense-counts", headers=headers
        )

    def list_incident_alerts(self, incident_id, headers):
        return self._request(
            "GET", f"/incident-reports/{incident_id}/safety-alerts", headers=headers
        )

    def create_safety_alert(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/incident-reports/{incident_id}/safety-alerts", payload, headers
        )

    # --- safety alerts ---
    def get_safety_alert(self, alert_id, headers):
        return self._request("GET", f"/safety-alerts/{alert_id}", headers=headers)

    def decide_alert(self, alert_id, payload, headers):
        return self._request("POST", f"/safety-alerts/{alert_id}/decide", payload, headers)

    def authorize_alert(self, alert_id, headers):
        return self._request("POST", f"/safety-alerts/{alert_id}/authorize", {}, headers)

    def disseminate_alert(self, alert_id, payload, headers):
        return self._request("POST", f"/safety-alerts/{alert_id}/disseminate", payload, headers)

    def close_alert(self, alert_id, headers):
        return self._request("POST", f"/safety-alerts/{alert_id}/close", {}, headers)

    def reopen_alert(self, alert_id, payload, headers):
        return self._request("POST", f"/safety-alerts/{alert_id}/reopen", payload, headers)

    # --- daily crime log ---
    def list_crime_log(self, headers, params=None):
        return self._request("GET", "/daily-crime-log", headers=headers, params=params)

    def get_crime_log_entry(self, entry_id, headers):
        return self._request("GET", f"/daily-crime-log/{entry_id}", headers=headers)

    def update_disposition(self, entry_id, payload, headers):
        return self._request(
            "PATCH", f"/daily-crime-log-entries/{entry_id}/disposition", payload, headers
        )

    def create_inspection_request(self, payload, headers):
        return self._request("POST", "/daily-crime-log/inspection-requests", payload, headers)

    def get_inspection_request(self, request_id, headers):
        return self._request("GET", f"/log-inspection-requests/{request_id}", headers=headers)

    def fulfill_inspection_request(self, request_id, headers):
        return self._request(
            "POST", f"/log-inspection-requests/{request_id}/fulfill", {}, headers
        )

    # --- annual security reports ---
    def create_asr(self, payload, headers):
        return self._request("POST", "/annual-security-reports", payload, headers)

    def list_asrs(self, headers, params=None):
        return self._request("GET", "/annual-security-reports", headers=headers, params=params)

    def get_asr(self, report_id, headers):
        return self._request("GET", f"/annual-security-reports/{report_id}", headers=headers)

    def compile_asr(self, report_id, payload, headers):
        return self._request(
            "POST", f"/annual-security-reports/{report_id}/compile", payload, headers
        )

    def list_statistic_lines(self, report_id, headers, params=None):
        return self._request(
            "GET", f"/annual-security-reports/{report_id}/statistic-lines",
            headers=headers, params=params,
        )

    def submit_asr_review(self, report_id, headers):
        return self._request(
            "POST", f"/annual-security-reports/{report_id}/submit-review", {}, headers
        )

    def publish_asr(self, report_id, headers):
        return self._request("POST", f"/annual-security-reports/{report_id}/publish", {}, headers)

    def begin_asr_amendment(self, report_id, headers):
        return self._request(
            "POST", f"/annual-security-reports/{report_id}/begin-amendment", {}, headers
        )

    def republish_asr(self, report_id, headers):
        return self._request(
            "POST", f"/annual-security-reports/{report_id}/republish", {}, headers
        )

    # --- fire incidents ---
    def create_fire_incident(self, payload, headers):
        return self._request("POST", "/fire-incidents", payload, headers)

    def list_fire_incidents(self, headers, params=None):
        return self._request("GET", "/fire-incidents", headers=headers, params=params)

    def get_fire_incident(self, fire_id, headers):
        return self._request("GET", f"/fire-incidents/{fire_id}", headers=headers)

    def finalize_fire_incident(self, fire_id, payload, headers):
        return self._request("POST", f"/fire-incidents/{fire_id}/finalize", payload, headers)

    def begin_fire_adjustment(self, fire_id, headers):
        return self._request(
            "POST", f"/fire-incidents/{fire_id}/begin-adjustment", {}, headers
        )

    # --- fire safety reports ---
    def create_fire_report(self, payload, headers):
        return self._request("POST", "/fire-safety-reports", payload, headers)

    def list_fire_reports(self, headers, params=None):
        return self._request("GET", "/fire-safety-reports", headers=headers, params=params)

    def get_fire_report(self, report_id, headers):
        return self._request("GET", f"/fire-safety-reports/{report_id}", headers=headers)

    def compile_fire_report(self, report_id, headers):
        return self._request("POST", f"/fire-safety-reports/{report_id}/compile", {}, headers)

    def publish_fire_report(self, report_id, headers):
        return self._request("POST", f"/fire-safety-reports/{report_id}/publish", {}, headers)

    def begin_fire_report_amendment(self, report_id, headers):
        return self._request(
            "POST", f"/fire-safety-reports/{report_id}/begin-amendment", {}, headers
        )

    # --- program reviews & corrective actions ---
    def create_program_review(self, payload, headers):
        return self._request("POST", "/program-reviews", payload, headers)

    def list_program_reviews(self, headers, params=None):
        return self._request("GET", "/program-reviews", headers=headers, params=params)

    def get_program_review(self, review_id, headers):
        return self._request("GET", f"/program-reviews/{review_id}", headers=headers)

    def advance_review(self, review_id, headers):
        return self._request("POST", f"/program-reviews/{review_id}/advance", {}, headers)

    def return_review_for_correction(self, review_id, payload, headers):
        return self._request(
            "POST", f"/program-reviews/{review_id}/return-for-correction", payload, headers
        )

    def create_corrective_action(self, review_id, payload, headers):
        return self._request(
            "POST", f"/program-reviews/{review_id}/corrective-actions", payload, headers
        )

    def list_corrective_actions(self, review_id, headers):
        return self._request(
            "GET", f"/program-reviews/{review_id}/corrective-actions", headers=headers
        )

    def submit_corrective_action(self, action_id, payload, headers):
        return self._request("POST", f"/corrective-actions/{action_id}/submit", payload, headers)

    def verify_corrective_action(self, action_id, headers):
        return self._request("POST", f"/corrective-actions/{action_id}/verify", {}, headers)

    def reject_corrective_action(self, action_id, payload, headers):
        return self._request("POST", f"/corrective-actions/{action_id}/reject", payload, headers)


api_client = ApiClient()
