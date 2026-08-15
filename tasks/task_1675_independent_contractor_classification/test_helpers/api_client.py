"""API client: one method per endpoint defined in the PRD (§4 routing summary)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- administration / configuration ---
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/api/jurisdictions", payload, headers)

    def list_jurisdictions(self, headers, params=None):
        return self._request("GET", "/api/jurisdictions", headers=headers, params=params)

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- contractors ---
    def create_contractor(self, payload, headers):
        return self._request("POST", "/api/contractors", payload, headers)

    def list_contractors(self, headers, params=None):
        return self._request("GET", "/api/contractors", headers=headers, params=params)

    def get_contractor(self, contractor_id, headers):
        return self._request("GET", f"/api/contractors/{contractor_id}", headers=headers)

    def verify_contractor(self, contractor_id, payload, headers):
        return self._request(
            "POST", f"/api/contractors/{contractor_id}/verify", payload, headers
        )

    # --- engagements ---
    def create_engagement(self, payload, headers):
        return self._request("POST", "/api/engagements", payload, headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/api/engagements", headers=headers, params=params)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/api/engagements/{engagement_id}", headers=headers)

    def submit_questionnaire(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/api/engagements/{engagement_id}/questionnaire", payload, headers
        )

    def get_questionnaire(self, engagement_id, headers):
        return self._request(
            "GET", f"/api/engagements/{engagement_id}/questionnaire", headers=headers
        )

    def create_determination(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/api/engagements/{engagement_id}/determinations", payload, headers
        )

    def list_determinations(self, engagement_id, headers):
        return self._request(
            "GET", f"/api/engagements/{engagement_id}/determinations", headers=headers
        )

    def submit_review(self, engagement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/api/engagements/{engagement_id}/submit-review",
            payload or {},
            headers,
        )

    def request_info(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/api/engagements/{engagement_id}/request-info", payload, headers
        )

    def submit_approval(self, engagement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/api/engagements/{engagement_id}/submit-approval",
            payload or {},
            headers,
        )

    def approve_engagement(self, engagement_id, headers, payload=None):
        return self._request(
            "POST", f"/api/engagements/{engagement_id}/approve", payload or {}, headers
        )

    def reject_engagement(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/api/engagements/{engagement_id}/reject", payload, headers
        )

    def activate_engagement(self, engagement_id, headers, payload=None):
        return self._request(
            "POST", f"/api/engagements/{engagement_id}/activate", payload or {}, headers
        )

    def suspend_engagement(self, engagement_id, headers, payload=None):
        return self._request(
            "POST", f"/api/engagements/{engagement_id}/suspend", payload or {}, headers
        )

    def reinstate_engagement(self, engagement_id, headers, payload=None):
        return self._request(
            "POST", f"/api/engagements/{engagement_id}/reinstate", payload or {}, headers
        )

    def terminate_engagement(self, engagement_id, headers, payload=None):
        return self._request(
            "POST", f"/api/engagements/{engagement_id}/terminate", payload or {}, headers
        )

    # --- exceptions ---
    def create_exception(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/api/engagements/{engagement_id}/exceptions", payload, headers
        )

    def list_exceptions(self, engagement_id, headers):
        return self._request(
            "GET", f"/api/engagements/{engagement_id}/exceptions", headers=headers
        )

    def revoke_exception(self, exception_id, headers, payload=None):
        return self._request(
            "POST", f"/api/exceptions/{exception_id}/revoke", payload or {}, headers
        )

    # --- contracts & amendments ---
    def create_contract(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/api/engagements/{engagement_id}/contracts", payload, headers
        )

    def list_engagement_contracts(self, engagement_id, headers):
        return self._request(
            "GET", f"/api/engagements/{engagement_id}/contracts", headers=headers
        )

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/api/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/api/contracts", headers=headers, params=params)

    def execute_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST", f"/api/contracts/{contract_id}/execute", payload or {}, headers
        )

    def create_amendment(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/api/contracts/{contract_id}/amendments", payload, headers
        )

    def list_amendments(self, contract_id, headers):
        return self._request(
            "GET", f"/api/contracts/{contract_id}/amendments", headers=headers
        )

    def approve_amendment(self, amendment_id, payload, headers):
        return self._request(
            "POST", f"/api/amendments/{amendment_id}/approve", payload, headers
        )

    # --- monitoring reviews ---
    def create_review(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/api/engagements/{engagement_id}/reviews", payload, headers
        )

    def list_reviews(self, engagement_id, headers):
        return self._request(
            "GET", f"/api/engagements/{engagement_id}/reviews", headers=headers
        )

    def close_review(self, review_id, payload, headers):
        return self._request("POST", f"/api/reviews/{review_id}/close", payload, headers)

    # --- risk audits & remediation ---
    def create_audit(self, payload, headers):
        return self._request("POST", "/api/audits", payload, headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/api/audits", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/api/audits/{audit_id}", headers=headers)

    def finalize_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/api/audits/{audit_id}/finalize", payload, headers)

    def create_remediation_action(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/api/audits/{audit_id}/remediation-actions", payload, headers
        )

    def list_remediation_actions(self, audit_id, headers):
        return self._request(
            "GET", f"/api/audits/{audit_id}/remediation-actions", headers=headers
        )

    def close_remediation_action(self, action_id, payload, headers):
        return self._request(
            "POST", f"/api/remediation-actions/{action_id}/close", payload, headers
        )

    def close_audit(self, audit_id, headers, payload=None):
        return self._request(
            "POST", f"/api/audits/{audit_id}/close", payload or {}, headers
        )

    # --- 1099 filings ---
    def create_filing(self, payload, headers):
        return self._request("POST", "/api/filings", payload, headers)

    def list_filings(self, headers, params=None):
        return self._request("GET", "/api/filings", headers=headers, params=params)

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"/api/filings/{filing_id}", headers=headers)

    def submit_filing(self, filing_id, headers, payload=None):
        return self._request(
            "POST", f"/api/filings/{filing_id}/submit", payload or {}, headers
        )

    def agency_response(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/api/filings/{filing_id}/agency-response", payload, headers
        )

    def correct_filing(self, filing_id, payload, headers):
        return self._request("POST", f"/api/filings/{filing_id}/correct", payload, headers)

    # --- agency inquiries ---
    def create_inquiry(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/api/engagements/{engagement_id}/inquiries", payload, headers
        )

    def list_engagement_inquiries(self, engagement_id, headers):
        return self._request(
            "GET", f"/api/engagements/{engagement_id}/inquiries", headers=headers
        )

    def list_inquiries(self, headers, params=None):
        return self._request("GET", "/api/inquiries", headers=headers, params=params)

    def respond_inquiry(self, inquiry_id, payload, headers):
        return self._request(
            "POST", f"/api/inquiries/{inquiry_id}/respond", payload, headers
        )

    def resolve_inquiry(self, inquiry_id, payload, headers):
        return self._request(
            "POST", f"/api/inquiries/{inquiry_id}/resolve", payload, headers
        )

    # --- conversions ---
    def create_conversion(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/api/engagements/{engagement_id}/conversions", payload, headers
        )

    def list_conversions(self, engagement_id, headers):
        return self._request(
            "GET", f"/api/engagements/{engagement_id}/conversions", headers=headers
        )

    def extend_offer(self, conversion_id, payload, headers):
        return self._request(
            "POST", f"/api/conversions/{conversion_id}/extend-offer", payload, headers
        )

    def record_decision(self, conversion_id, payload, headers):
        return self._request(
            "POST", f"/api/conversions/{conversion_id}/record-decision", payload, headers
        )


api_client = ApiClient()
