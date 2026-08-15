"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Providers ---
    def create_provider(self, payload, headers):
        return self._request("POST", "/um/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/um/providers/{provider_id}", headers=headers)

    def create_gold_card_evaluation(self, provider_id, payload, headers):
        return self._request(
            "POST", f"/um/providers/{provider_id}/gold-card-evaluations", payload, headers
        )

    def list_gold_card_evaluations(self, provider_id, headers, params=None):
        return self._request(
            "GET", f"/um/providers/{provider_id}/gold-card-evaluations",
            headers=headers, params=params,
        )

    def list_provider_compliance_events(self, provider_id, headers, params=None):
        return self._request(
            "GET", f"/um/providers/{provider_id}/compliance-events",
            headers=headers, params=params,
        )

    # --- Criteria sets & guideline versions ---
    def create_criteria_set(self, payload, headers):
        return self._request("POST", "/um/criteria-sets", payload, headers)

    def get_criteria_set(self, criteria_set_id, headers):
        return self._request(
            "GET", f"/um/criteria-sets/{criteria_set_id}", headers=headers
        )

    def transition_criteria_set(self, criteria_set_id, payload, headers):
        return self._request(
            "POST", f"/um/criteria-sets/{criteria_set_id}/transition", payload, headers
        )

    def create_guideline_version(self, criteria_set_id, payload, headers):
        return self._request(
            "POST", f"/um/criteria-sets/{criteria_set_id}/guideline-versions",
            payload, headers,
        )

    def get_guideline_version(self, guideline_version_id, headers):
        return self._request(
            "GET", f"/um/guideline-versions/{guideline_version_id}", headers=headers
        )

    def list_guideline_versions(self, headers, params=None):
        return self._request(
            "GET", "/um/guideline-versions", headers=headers, params=params
        )

    def transition_guideline_version(self, guideline_version_id, payload, headers):
        return self._request(
            "POST", f"/um/guideline-versions/{guideline_version_id}/transition",
            payload, headers,
        )

    # --- Prior auth requests ---
    def create_prior_auth_request(self, payload, headers):
        return self._request("POST", "/um/prior-auth-requests", payload, headers)

    def get_prior_auth_request(self, request_id, headers):
        return self._request(
            "GET", f"/um/prior-auth-requests/{request_id}", headers=headers
        )

    def list_prior_auth_requests(self, headers, params=None):
        return self._request(
            "GET", "/um/prior-auth-requests", headers=headers, params=params
        )

    def withdraw_prior_auth_request(self, request_id, headers):
        return self._request(
            "POST", f"/um/prior-auth-requests/{request_id}/withdraw", {}, headers
        )

    def reviewer_decision(self, request_id, payload, headers):
        return self._request(
            "POST", f"/um/prior-auth-requests/{request_id}/reviewer-decision",
            payload, headers,
        )

    def md_decision(self, request_id, payload, headers):
        return self._request(
            "POST", f"/um/prior-auth-requests/{request_id}/md-decision",
            payload, headers,
        )

    def schedule_p2p_conference(self, request_id, payload, headers):
        return self._request(
            "POST", f"/um/prior-auth-requests/{request_id}/peer-to-peer-conferences",
            payload, headers,
        )

    def list_p2p_conferences(self, request_id, headers, params=None):
        return self._request(
            "GET", f"/um/prior-auth-requests/{request_id}/peer-to-peer-conferences",
            headers=headers, params=params,
        )

    def resolve_p2p_conference(self, conference_id, payload, headers):
        return self._request(
            "POST", f"/um/peer-to-peer-conferences/{conference_id}/resolve",
            payload, headers,
        )

    # --- Determinations ---
    def get_determination(self, determination_id, headers):
        return self._request(
            "GET", f"/um/determinations/{determination_id}", headers=headers
        )

    def list_determinations(self, headers, params=None):
        return self._request(
            "GET", "/um/determinations", headers=headers, params=params
        )

    def void_determination(self, determination_id, headers):
        return self._request(
            "POST", f"/um/determinations/{determination_id}/void", {}, headers
        )

    def create_appeal(self, determination_id, payload, headers):
        return self._request(
            "POST", f"/um/determinations/{determination_id}/appeals", payload, headers
        )

    def list_determination_appeals(self, determination_id, headers, params=None):
        return self._request(
            "GET", f"/um/determinations/{determination_id}/appeals",
            headers=headers, params=params,
        )

    def list_determination_audit_findings(self, determination_id, headers, params=None):
        return self._request(
            "GET", f"/um/determinations/{determination_id}/audit-findings",
            headers=headers, params=params,
        )

    # --- Appeals ---
    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/um/appeals/{appeal_id}", headers=headers)

    def begin_appeal_review(self, appeal_id, headers):
        return self._request(
            "POST", f"/um/appeals/{appeal_id}/begin-review", {}, headers
        )

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/um/appeals/{appeal_id}/decide", payload, headers
        )

    def withdraw_appeal(self, appeal_id, headers):
        return self._request("POST", f"/um/appeals/{appeal_id}/withdraw", {}, headers)

    # --- Delegation oversight ---
    def create_delegation_arrangement(self, payload, headers):
        return self._request("POST", "/um/delegation-arrangements", payload, headers)

    def get_delegation_arrangement(self, arrangement_id, headers):
        return self._request(
            "GET", f"/um/delegation-arrangements/{arrangement_id}", headers=headers
        )

    def list_delegation_arrangements(self, headers, params=None):
        return self._request(
            "GET", "/um/delegation-arrangements", headers=headers, params=params
        )

    def create_audit_finding(self, arrangement_id, payload, headers):
        return self._request(
            "POST", f"/um/delegation-arrangements/{arrangement_id}/audit-findings",
            payload, headers,
        )

    def list_arrangement_audit_findings(self, arrangement_id, headers, params=None):
        return self._request(
            "GET", f"/um/delegation-arrangements/{arrangement_id}/audit-findings",
            headers=headers, params=params,
        )

    def transition_audit_finding(self, finding_id, payload, headers):
        return self._request(
            "POST", f"/um/audit-findings/{finding_id}/transition", payload, headers
        )

    # --- Compliance events, metrics, clock ---
    def list_request_compliance_events(self, request_id, headers, params=None):
        return self._request(
            "GET", f"/um/prior-auth-requests/{request_id}/compliance-events",
            headers=headers, params=params,
        )

    def list_compliance_events(self, headers, params=None):
        return self._request(
            "GET", "/um/compliance-events", headers=headers, params=params
        )

    def get_overturn_analysis(self, headers):
        return self._request("GET", "/um/metrics/overturn-analysis", headers=headers)

    def set_current_utc(self, payload, headers):
        return self._request("POST", "/um/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
