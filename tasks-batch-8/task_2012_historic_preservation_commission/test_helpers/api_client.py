"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving capability, PRD §2.5)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/preservation/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ------------------------------------------------------------------
    # Districts & guideline sets
    # ------------------------------------------------------------------
    def create_district(self, payload, headers):
        return self._request("POST", "/preservation/districts", payload, headers)

    def list_districts(self, headers, params=None):
        return self._request("GET", "/preservation/districts", headers=headers, params=params)

    def get_district(self, district_id, headers):
        return self._request("GET", f"/preservation/districts/{district_id}", headers=headers)

    def update_district(self, district_id, payload, headers):
        return self._request("PATCH", f"/preservation/districts/{district_id}", payload, headers)

    def list_district_properties(self, district_id, headers, params=None):
        return self._request(
            "GET", f"/preservation/districts/{district_id}/properties",
            headers=headers, params=params,
        )

    def create_guideline_set(self, district_id, payload, headers):
        return self._request(
            "POST", f"/preservation/districts/{district_id}/guideline-sets", payload, headers
        )

    def list_guideline_sets(self, district_id, headers, params=None):
        return self._request(
            "GET", f"/preservation/districts/{district_id}/guideline-sets",
            headers=headers, params=params,
        )

    def adopt_guideline_set(self, guideline_set_id, headers):
        return self._request(
            "POST", f"/preservation/guideline-sets/{guideline_set_id}/adopt", {}, headers
        )

    # ------------------------------------------------------------------
    # Owners & properties
    # ------------------------------------------------------------------
    def create_owner(self, payload, headers):
        return self._request("POST", "/preservation/owners", payload, headers)

    def create_property(self, payload, headers):
        return self._request("POST", "/preservation/properties", payload, headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/preservation/properties", headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/preservation/properties/{property_id}", headers=headers)

    def reclassify_property(self, property_id, payload, headers):
        return self._request(
            "POST", f"/preservation/properties/{property_id}/reclassify", payload, headers
        )

    # ------------------------------------------------------------------
    # Commission meetings
    # ------------------------------------------------------------------
    def create_meeting(self, payload, headers):
        return self._request("POST", "/preservation/meetings", payload, headers)

    def list_meetings(self, headers, params=None):
        return self._request("GET", "/preservation/meetings", headers=headers, params=params)

    def get_meeting(self, meeting_id, headers):
        return self._request("GET", f"/preservation/meetings/{meeting_id}", headers=headers)

    # ------------------------------------------------------------------
    # Applications (Certificate of Appropriateness)
    # ------------------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/preservation/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/preservation/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"/preservation/applications/{application_id}", headers=headers
        )

    def begin_review(self, application_id, headers):
        return self._request(
            "POST", f"/preservation/applications/{application_id}/begin-review", {}, headers
        )

    def return_incomplete(self, application_id, payload, headers):
        return self._request(
            "POST", f"/preservation/applications/{application_id}/return-incomplete",
            payload, headers,
        )

    def resubmit_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/preservation/applications/{application_id}/resubmit", payload, headers
        )

    def accept_completeness(self, application_id, payload, headers):
        return self._request(
            "POST", f"/preservation/applications/{application_id}/accept-completeness",
            payload, headers,
        )

    def decide_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/preservation/applications/{application_id}/decide", payload, headers
        )

    def withdraw_application(self, application_id, headers):
        return self._request(
            "POST", f"/preservation/applications/{application_id}/withdraw", {}, headers
        )

    def finalize_denial(self, application_id, headers):
        return self._request(
            "POST", f"/preservation/applications/{application_id}/finalize-denial", {}, headers
        )

    def record_fee_payment(self, application_id, payload, headers):
        return self._request(
            "POST", f"/preservation/applications/{application_id}/fee-payments",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Hearings & public comment
    # ------------------------------------------------------------------
    def create_hearing(self, payload, headers):
        return self._request("POST", "/preservation/hearings", payload, headers)

    def list_hearings(self, headers, params=None):
        return self._request("GET", "/preservation/hearings", headers=headers, params=params)

    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"/preservation/hearings/{hearing_id}", headers=headers)

    def open_hearing(self, hearing_id, headers):
        return self._request(
            "POST", f"/preservation/hearings/{hearing_id}/open", {}, headers
        )

    def continue_hearing(self, hearing_id, headers):
        return self._request(
            "POST", f"/preservation/hearings/{hearing_id}/continue", {}, headers
        )

    def reschedule_hearing(self, hearing_id, payload, headers):
        return self._request(
            "POST", f"/preservation/hearings/{hearing_id}/reschedule", payload, headers
        )

    def create_comment(self, hearing_id, payload, headers):
        return self._request(
            "POST", f"/preservation/hearings/{hearing_id}/comments", payload, headers
        )

    def list_comments(self, hearing_id, headers, params=None):
        return self._request(
            "GET", f"/preservation/hearings/{hearing_id}/comments",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Appeals
    # ------------------------------------------------------------------
    def create_appeal(self, payload, headers):
        return self._request("POST", "/preservation/appeals", payload, headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/preservation/appeals", headers=headers, params=params)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/preservation/appeals/{appeal_id}", headers=headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/preservation/appeals/{appeal_id}/decide", payload, headers
        )

    def withdraw_appeal(self, appeal_id, headers):
        return self._request(
            "POST", f"/preservation/appeals/{appeal_id}/withdraw", {}, headers
        )

    # ------------------------------------------------------------------
    # Violations
    # ------------------------------------------------------------------
    def create_violation(self, payload, headers):
        return self._request("POST", "/preservation/violations", payload, headers)

    def list_violations(self, headers, params=None):
        return self._request("GET", "/preservation/violations", headers=headers, params=params)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/preservation/violations/{violation_id}", headers=headers)

    def issue_notice(self, violation_id, headers):
        return self._request(
            "POST", f"/preservation/violations/{violation_id}/issue-notice", {}, headers
        )

    def verify_compliance(self, violation_id, headers):
        return self._request(
            "POST", f"/preservation/violations/{violation_id}/verify-compliance", {}, headers
        )

    def refer_court(self, violation_id, headers):
        return self._request(
            "POST", f"/preservation/violations/{violation_id}/refer-court", {}, headers
        )

    def close_violation(self, violation_id, headers):
        return self._request(
            "POST", f"/preservation/violations/{violation_id}/close", {}, headers
        )

    # ------------------------------------------------------------------
    # Demolition delays & hardship reviews
    # ------------------------------------------------------------------
    def list_demolition_delays(self, headers, params=None):
        return self._request(
            "GET", "/preservation/demolition-delays", headers=headers, params=params
        )

    def get_demolition_delay(self, delay_id, headers):
        return self._request(
            "GET", f"/preservation/demolition-delays/{delay_id}", headers=headers
        )

    def postpone_delay(self, delay_id, headers):
        return self._request(
            "POST", f"/preservation/demolition-delays/{delay_id}/postpone", {}, headers
        )

    def create_hardship_review(self, payload, headers):
        return self._request("POST", "/preservation/hardship-reviews", payload, headers)

    def list_hardship_reviews(self, headers, params=None):
        return self._request(
            "GET", "/preservation/hardship-reviews", headers=headers, params=params
        )

    def get_hardship_review(self, hardship_review_id, headers):
        return self._request(
            "GET", f"/preservation/hardship-reviews/{hardship_review_id}", headers=headers
        )

    def hear_hardship_review(self, hardship_review_id, headers):
        return self._request(
            "POST", f"/preservation/hardship-reviews/{hardship_review_id}/hear", {}, headers
        )

    def decide_hardship_review(self, hardship_review_id, payload, headers):
        return self._request(
            "POST", f"/preservation/hardship-reviews/{hardship_review_id}/decide",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Certificates
    # ------------------------------------------------------------------
    def create_certificate(self, payload, headers):
        return self._request("POST", "/preservation/certificates", payload, headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/preservation/certificates", headers=headers, params=params)

    def get_certificate(self, certificate_id, headers):
        return self._request(
            "GET", f"/preservation/certificates/{certificate_id}", headers=headers
        )

    def verify_conditions(self, certificate_id, payload, headers):
        return self._request(
            "POST", f"/preservation/certificates/{certificate_id}/verify-conditions",
            payload, headers,
        )

    def complete_certificate(self, certificate_id, payload, headers):
        return self._request(
            "POST", f"/preservation/certificates/{certificate_id}/complete", payload, headers
        )

    def expire_certificate(self, certificate_id, headers):
        return self._request(
            "POST", f"/preservation/certificates/{certificate_id}/expire", {}, headers
        )


api_client = ApiClient()
