"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/complaint-office"


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Products ---
    def create_product(self, payload, headers):
        return self._request("POST", f"{PREFIX}/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"{PREFIX}/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/products", headers=headers, params=params)

    def unfreeze_product(self, product_id, headers):
        return self._request("POST", f"{PREFIX}/products/{product_id}/unfreeze", {}, headers)

    def list_product_complaints(self, product_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/products/{product_id}/complaints",
            headers=headers, params=params,
        )

    def list_product_trend_snapshots(self, product_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/products/{product_id}/trend-snapshots",
            headers=headers, params=params,
        )

    def create_trend_snapshot(self, product_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/products/{product_id}/trend-snapshots", payload, headers,
        )

    # --- Channels ---
    def create_channel(self, payload, headers):
        return self._request("POST", f"{PREFIX}/channels", payload, headers)

    def get_channel(self, channel_id, headers):
        return self._request("GET", f"{PREFIX}/channels/{channel_id}", headers=headers)

    def list_channels(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/channels", headers=headers, params=params)

    # --- Taxonomy ---
    def create_taxonomy_category(self, payload, headers):
        return self._request("POST", f"{PREFIX}/taxonomy-categories", payload, headers)

    def get_taxonomy_category(self, category_id, headers):
        return self._request(
            "GET", f"{PREFIX}/taxonomy-categories/{category_id}", headers=headers,
        )

    def list_taxonomy_categories(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/taxonomy-categories", headers=headers, params=params,
        )

    def retire_taxonomy_category(self, category_id, headers):
        return self._request(
            "POST", f"{PREFIX}/taxonomy-categories/{category_id}/retire", {}, headers,
        )

    # --- Response templates ---
    def create_response_template(self, payload, headers):
        return self._request("POST", f"{PREFIX}/response-templates", payload, headers)

    def get_response_template(self, template_id, headers):
        return self._request(
            "GET", f"{PREFIX}/response-templates/{template_id}", headers=headers,
        )

    def list_response_templates(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/response-templates", headers=headers, params=params,
        )

    def publish_response_template(self, template_id, headers):
        return self._request(
            "POST", f"{PREFIX}/response-templates/{template_id}/publish", {}, headers,
        )

    def retire_response_template(self, template_id, headers):
        return self._request(
            "POST", f"{PREFIX}/response-templates/{template_id}/retire", {}, headers,
        )

    # --- Complaints ---
    def create_complaint(self, payload, headers):
        return self._request("POST", f"{PREFIX}/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"{PREFIX}/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/complaints", headers=headers, params=params)

    def list_complaint_events(self, complaint_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/complaints/{complaint_id}/events",
            headers=headers, params=params,
        )

    def triage_complaint(self, complaint_id, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/triage", {}, headers,
        )

    def start_investigation(self, complaint_id, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/start_investigation", {}, headers,
        )

    def recode_taxonomy(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/taxonomy_recodes", payload, headers,
        )

    def create_rca(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/rcas", payload, headers,
        )

    def draft_response(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/draft_response", payload, headers,
        )

    def submit_for_qa(self, complaint_id, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/submit_for_qa", {}, headers,
        )

    def qa_fail(self, complaint_id, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/qa_fail", {}, headers,
        )

    def resolve_complaint(self, complaint_id, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/resolve", {}, headers,
        )

    def reopen_complaint(self, complaint_id, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/reopen", {}, headers,
        )

    def withdraw_complaint(self, complaint_id, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/withdraw", {}, headers,
        )

    # --- Regulatory referrals ---
    def list_complaint_referrals(self, complaint_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/complaints/{complaint_id}/referrals",
            headers=headers, params=params,
        )

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"{PREFIX}/referrals/{referral_id}", headers=headers)

    def submit_referral_response(self, referral_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/referrals/{referral_id}/submit_response", payload, headers,
        )

    def close_referral(self, referral_id, headers):
        return self._request(
            "POST", f"{PREFIX}/referrals/{referral_id}/close", {}, headers,
        )

    def regulator_reopen_referral(self, referral_id, headers):
        return self._request(
            "POST", f"{PREFIX}/referrals/{referral_id}/regulator_reopen", {}, headers,
        )

    # --- RCAs ---
    def list_complaint_rcas(self, complaint_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/complaints/{complaint_id}/rcas",
            headers=headers, params=params,
        )

    def list_rcas(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rcas", headers=headers, params=params)

    def get_rca(self, rca_id, headers):
        return self._request("GET", f"{PREFIX}/rcas/{rca_id}", headers=headers)

    def complete_rca(self, rca_id, headers):
        return self._request("POST", f"{PREFIX}/rcas/{rca_id}/complete", {}, headers)

    # --- Remediation decisions ---
    def create_remediation_decision(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/remediation_decisions",
            payload, headers,
        )

    def list_complaint_remediation_decisions(self, complaint_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/complaints/{complaint_id}/remediation_decisions",
            headers=headers, params=params,
        )

    def get_remediation_decision(self, decision_id, headers):
        return self._request(
            "GET", f"{PREFIX}/remediation-decisions/{decision_id}", headers=headers,
        )

    def submit_remediation_decision(self, decision_id, headers):
        return self._request(
            "POST", f"{PREFIX}/remediation-decisions/{decision_id}/submit", {}, headers,
        )

    def approve_remediation_decision(self, decision_id, headers):
        return self._request(
            "POST", f"{PREFIX}/remediation-decisions/{decision_id}/approve", {}, headers,
        )

    def reject_remediation_decision(self, decision_id, headers):
        return self._request(
            "POST", f"{PREFIX}/remediation-decisions/{decision_id}/reject", {}, headers,
        )

    def mark_remediation_decision_paid(self, decision_id, headers):
        return self._request(
            "POST", f"{PREFIX}/remediation-decisions/{decision_id}/mark_paid", {}, headers,
        )

    def reverse_remediation_decision(self, decision_id, headers):
        return self._request(
            "POST", f"{PREFIX}/remediation-decisions/{decision_id}/reverse", {}, headers,
        )

    # --- Quality reviews ---
    def claim_quality_review(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/quality-reviews", payload, headers,
        )

    def list_complaint_quality_reviews(self, complaint_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/complaints/{complaint_id}/quality-reviews",
            headers=headers, params=params,
        )

    def get_quality_review(self, review_id, headers):
        return self._request(
            "GET", f"{PREFIX}/quality-reviews/{review_id}", headers=headers,
        )

    def complete_quality_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/quality-reviews/{review_id}/complete", payload, headers,
        )

    def cancel_quality_review(self, review_id, headers):
        return self._request(
            "POST", f"{PREFIX}/quality-reviews/{review_id}/cancel", {}, headers,
        )

    # --- Escalations ---
    def create_escalation(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/escalations", payload, headers,
        )

    def list_complaint_escalations(self, complaint_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/complaints/{complaint_id}/escalations",
            headers=headers, params=params,
        )

    def get_escalation(self, escalation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/escalations/{escalation_id}", headers=headers,
        )

    def acknowledge_escalation(self, escalation_id, headers):
        return self._request(
            "POST", f"{PREFIX}/escalations/{escalation_id}/acknowledge", {}, headers,
        )

    def resolve_escalation(self, escalation_id, headers):
        return self._request(
            "POST", f"{PREFIX}/escalations/{escalation_id}/resolve", {}, headers,
        )

    def dismiss_escalation(self, escalation_id, headers):
        return self._request(
            "POST", f"{PREFIX}/escalations/{escalation_id}/dismiss", {}, headers,
        )


api_client = ApiClient()
