"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- publisher accounts ----------------
    def create_publisher_account(self, payload, headers):
        return self._request("POST", "/publisher-accounts", payload, headers)

    def list_publisher_accounts(self, headers, params=None):
        return self._request("GET", "/publisher-accounts", headers=headers, params=params)

    def get_publisher_account(self, account_id, headers):
        return self._request("GET", f"/publisher-accounts/{account_id}", headers=headers)

    def renew_membership(self, account_id, payload, headers):
        return self._request(
            "POST", f"/publisher-accounts/{account_id}/membership-renewal", payload, headers
        )

    def enforce_account(self, account_id, payload, headers):
        return self._request(
            "POST", f"/publisher-accounts/{account_id}/enforcement", payload, headers
        )

    def get_standing(self, account_id, headers):
        return self._request("GET", f"/publisher-accounts/{account_id}/standing", headers=headers)

    # ---------------- signing credentials ----------------
    def create_signing_credential(self, payload, headers):
        return self._request("POST", "/signing-credentials", payload, headers)

    def list_signing_credentials(self, headers, params=None):
        return self._request("GET", "/signing-credentials", headers=headers, params=params)

    def get_signing_credential(self, credential_id, headers):
        return self._request("GET", f"/signing-credentials/{credential_id}", headers=headers)

    def activate_signing_credential(self, credential_id, headers, payload=None):
        return self._request(
            "POST", f"/signing-credentials/{credential_id}/activate", payload or {}, headers
        )

    def report_credential_compromise(self, credential_id, payload, headers):
        return self._request(
            "POST", f"/signing-credentials/{credential_id}/report-compromise", payload, headers
        )

    def revoke_signing_credential(self, credential_id, headers, payload=None):
        return self._request(
            "POST", f"/signing-credentials/{credential_id}/revoke", payload or {}, headers
        )

    # ---------------- app records ----------------
    def create_app_record(self, payload, headers):
        return self._request("POST", "/app-records", payload, headers)

    def list_app_records(self, headers, params=None):
        return self._request("GET", "/app-records", headers=headers, params=params)

    def get_app_record(self, app_record_id, headers):
        return self._request("GET", f"/app-records/{app_record_id}", headers=headers)

    def drive_listing(self, app_record_id, payload, headers):
        return self._request("PATCH", f"/app-records/{app_record_id}/listing", payload, headers)

    def get_compliance_summary(self, app_record_id, headers):
        return self._request(
            "GET", f"/app-records/{app_record_id}/compliance-summary", headers=headers
        )

    def get_commerce_settlement(self, app_record_id, headers, params=None):
        return self._request(
            "GET", f"/app-records/{app_record_id}/commerce-settlement", headers=headers, params=params
        )

    # ---------------- guideline rules ----------------
    def create_guideline_rule(self, payload, headers):
        return self._request("POST", "/guideline-rules", payload, headers)

    def list_guideline_rules(self, headers, params=None):
        return self._request("GET", "/guideline-rules", headers=headers, params=params)

    def get_guideline_rule(self, rule_id, headers):
        return self._request("GET", f"/guideline-rules/{rule_id}", headers=headers)

    def publish_guideline_rule(self, rule_id, headers, payload=None):
        return self._request(
            "POST", f"/guideline-rules/{rule_id}/publish", payload or {}, headers
        )

    # ---------------- feature mappings ----------------
    def create_feature_mapping(self, payload, headers):
        return self._request("POST", "/feature-mappings", payload, headers)

    def list_feature_mappings(self, headers, params=None):
        return self._request("GET", "/feature-mappings", headers=headers, params=params)

    def get_feature_mapping(self, mapping_id, headers):
        return self._request("GET", f"/feature-mappings/{mapping_id}", headers=headers)

    def self_review_mapping(self, mapping_id, payload, headers):
        return self._request(
            "POST", f"/feature-mappings/{mapping_id}/self-review", payload, headers
        )

    def waive_mapping(self, mapping_id, payload, headers):
        return self._request("POST", f"/feature-mappings/{mapping_id}/waive", payload, headers)

    # ---------------- submissions ----------------
    def create_submission(self, payload, headers):
        return self._request("POST", "/submissions", payload, headers)

    def list_submissions(self, headers, params=None):
        return self._request("GET", "/submissions", headers=headers, params=params)

    def get_submission(self, submission_id, headers):
        return self._request("GET", f"/submissions/{submission_id}", headers=headers)

    def set_age_rating(self, submission_id, payload, headers):
        return self._request("PUT", f"/submissions/{submission_id}/age-rating", payload, headers)

    def set_privacy_declaration(self, submission_id, payload, headers):
        return self._request(
            "PUT", f"/submissions/{submission_id}/privacy-declaration", payload, headers
        )

    def pre_review_check(self, submission_id, headers, payload=None):
        return self._request(
            "POST", f"/submissions/{submission_id}/pre-review-check", payload or {}, headers
        )

    def queue_submission(self, submission_id, headers, payload=None):
        return self._request(
            "POST", f"/submissions/{submission_id}/queue", payload or {}, headers
        )

    def withdraw_submission(self, submission_id, headers, payload=None):
        return self._request(
            "POST", f"/submissions/{submission_id}/withdraw", payload or {}, headers
        )

    def claim_submission(self, submission_id, headers, payload=None):
        return self._request(
            "POST", f"/submissions/{submission_id}/claim", payload or {}, headers
        )

    def decide_submission(self, submission_id, payload, headers):
        return self._request("POST", f"/submissions/{submission_id}/decision", payload, headers)

    def return_submission_to_draft(self, submission_id, headers, payload=None):
        return self._request(
            "POST", f"/submissions/{submission_id}/return-to-draft", payload or {}, headers
        )

    def list_submission_metadata_locales(self, submission_id, headers, params=None):
        return self._request(
            "GET", f"/submissions/{submission_id}/metadata-locales", headers=headers, params=params
        )

    # ---------------- metadata locales ----------------
    def create_metadata_locale(self, payload, headers):
        return self._request("POST", "/metadata-locales", payload, headers)

    def list_metadata_locales(self, headers, params=None):
        return self._request("GET", "/metadata-locales", headers=headers, params=params)

    def get_metadata_locale(self, locale_id, headers):
        return self._request("GET", f"/metadata-locales/{locale_id}", headers=headers)

    # ---------------- behavior findings ----------------
    def create_behavior_finding(self, payload, headers):
        return self._request("POST", "/behavior-findings", payload, headers)

    def list_behavior_findings(self, headers, params=None):
        return self._request("GET", "/behavior-findings", headers=headers, params=params)

    def get_behavior_finding(self, finding_id, headers):
        return self._request("GET", f"/behavior-findings/{finding_id}", headers=headers)

    def triage_behavior_finding(self, finding_id, payload, headers):
        return self._request("POST", f"/behavior-findings/{finding_id}/triage", payload, headers)

    # ---------------- rejection reasons ----------------
    def list_rejection_reasons(self, headers, params=None):
        return self._request("GET", "/rejection-reasons", headers=headers, params=params)

    def get_rejection_reason(self, reason_id, headers):
        return self._request("GET", f"/rejection-reasons/{reason_id}", headers=headers)

    def respond_to_rejection_reason(self, reason_id, payload, headers):
        return self._request("POST", f"/rejection-reasons/{reason_id}/response", payload, headers)

    # ---------------- appeal requests ----------------
    def create_appeal_request(self, payload, headers):
        return self._request("POST", "/appeal-requests", payload, headers)

    def list_appeal_requests(self, headers, params=None):
        return self._request("GET", "/appeal-requests", headers=headers, params=params)

    def get_appeal_request(self, appeal_id, headers):
        return self._request("GET", f"/appeal-requests/{appeal_id}", headers=headers)

    def board_review_appeal(self, appeal_id, headers, payload=None):
        return self._request(
            "POST", f"/appeal-requests/{appeal_id}/board-review", payload or {}, headers
        )

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeal-requests/{appeal_id}/decide", payload, headers)

    def withdraw_appeal(self, appeal_id, headers, payload=None):
        return self._request(
            "POST", f"/appeal-requests/{appeal_id}/withdraw", payload or {}, headers
        )

    # ---------------- expedite requests ----------------
    def create_expedite_request(self, payload, headers):
        return self._request("POST", "/expedite-requests", payload, headers)

    def list_expedite_requests(self, headers, params=None):
        return self._request("GET", "/expedite-requests", headers=headers, params=params)

    def get_expedite_request(self, expedite_id, headers):
        return self._request("GET", f"/expedite-requests/{expedite_id}", headers=headers)

    def decide_expedite_request(self, expedite_id, payload, headers):
        return self._request("POST", f"/expedite-requests/{expedite_id}/decide", payload, headers)

    # ---------------- review capacity windows ----------------
    def create_review_capacity_window(self, payload, headers):
        return self._request("POST", "/review-capacity-windows", payload, headers)

    def list_review_capacity_windows(self, headers, params=None):
        return self._request("GET", "/review-capacity-windows", headers=headers, params=params)

    def get_review_capacity_window(self, window_id, headers):
        return self._request("GET", f"/review-capacity-windows/{window_id}", headers=headers)

    def close_review_capacity_window(self, window_id, headers, payload=None):
        return self._request(
            "POST", f"/review-capacity-windows/{window_id}/close", payload or {}, headers
        )

    # ---------------- rollout plans ----------------
    def create_rollout_plan(self, payload, headers):
        return self._request("POST", "/rollout-plans", payload, headers)

    def list_rollout_plans(self, headers, params=None):
        return self._request("GET", "/rollout-plans", headers=headers, params=params)

    def get_rollout_plan(self, plan_id, headers):
        return self._request("GET", f"/rollout-plans/{plan_id}", headers=headers)

    def start_rollout_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/rollout-plans/{plan_id}/start", payload or {}, headers)

    def advance_rollout_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/rollout-plans/{plan_id}/advance", payload, headers)

    def hold_rollout_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/rollout-plans/{plan_id}/hold", payload, headers)

    def rollback_rollout_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/rollout-plans/{plan_id}/rollback", payload, headers)

    # ---------------- commerce items ----------------
    def create_commerce_item(self, payload, headers):
        return self._request("POST", "/commerce-items", payload, headers)

    def list_commerce_items(self, headers, params=None):
        return self._request("GET", "/commerce-items", headers=headers, params=params)

    def get_commerce_item(self, item_id, headers):
        return self._request("GET", f"/commerce-items/{item_id}", headers=headers)

    def submit_commerce_item(self, item_id, headers, payload=None):
        return self._request("POST", f"/commerce-items/{item_id}/submit", payload or {}, headers)

    def review_commerce_item(self, item_id, payload, headers):
        return self._request("POST", f"/commerce-items/{item_id}/review", payload, headers)

    def report_commerce_revenue(self, item_id, payload, headers):
        return self._request(
            "POST", f"/commerce-items/{item_id}/report-revenue", payload, headers
        )

    # ---------------- impact assessments ----------------
    def list_impact_assessments(self, headers, params=None):
        return self._request("GET", "/impact-assessments", headers=headers, params=params)

    def get_impact_assessment(self, assessment_id, headers):
        return self._request("GET", f"/impact-assessments/{assessment_id}", headers=headers)

    def assess_impact(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/impact-assessments/{assessment_id}/assess", payload, headers
        )

    # ---------------- logical clock ----------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
