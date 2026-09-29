"""API client: one method per endpoint defined in the PRD.

The whole API surface is mounted under `/fit-program`; the single exception is
the logical-clock control endpoint, which is mounted at the root.
"""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/fit-program"


class ApiClient(GenericApiClient):
    """PRD endpoint methods.  Every method returns the raw response so tests can
    assert both status codes and envelope contents."""

    # ------------------------------------------------------------------
    # The logical program clock
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Vendors
    # ------------------------------------------------------------------

    def create_vendor(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/vendors", payload, headers)

    def get_vendor(self, vendor_id: str, headers=None):
        return self._request("GET", f"{PREFIX}/vendors/{vendor_id}", headers=headers)

    # ------------------------------------------------------------------
    # Catalog items
    # ------------------------------------------------------------------

    def create_catalog_item(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/catalog-items", payload, headers)

    def get_catalog_item(self, item_id: str, headers=None):
        return self._request("GET", f"{PREFIX}/catalog-items/{item_id}", headers=headers)

    def list_catalog_items(self, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/catalog-items", headers=headers, params=params
        )

    def list_item(self, item_id: str, headers=None):
        """Put a DRAFT item on the storefront; advances the listing axis only."""
        return self._request(
            "POST", f"{PREFIX}/catalog-items/{item_id}/list", {}, headers
        )

    def delist_item(self, item_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/catalog-items/{item_id}/delist", payload, headers
        )

    def enhance_pdp(self, item_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/catalog-items/{item_id}/pdp-enhancement", payload, headers
        )

    def publish_guidance(self, item_id: str, headers=None):
        return self._request(
            "POST", f"{PREFIX}/catalog-items/{item_id}/publish-guidance", {}, headers
        )

    def get_fit_recommendation(
        self, item_id: str, headers=None, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/catalog-items/{item_id}/fit-recommendation",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Measurement specifications
    # ------------------------------------------------------------------

    def create_measurement_spec(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/measurement-specs", payload, headers)

    def get_measurement_spec(self, spec_id: str, headers=None):
        return self._request(
            "GET", f"{PREFIX}/measurement-specs/{spec_id}", headers=headers
        )

    def list_measurement_specs(self, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/measurement-specs", headers=headers, params=params
        )

    def submit_measurement_spec(self, spec_id: str, headers=None):
        return self._request(
            "POST", f"{PREFIX}/measurement-specs/{spec_id}/submit", {}, headers
        )

    def verify_measurement_spec(self, spec_id: str, headers=None):
        return self._request(
            "POST", f"{PREFIX}/measurement-specs/{spec_id}/verify", {}, headers
        )

    def resubmit_measurement_spec(self, spec_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/measurement-specs/{spec_id}/resubmit", payload, headers
        )

    # ------------------------------------------------------------------
    # Size charts
    # ------------------------------------------------------------------

    def create_size_chart(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/size-charts", payload, headers)

    def get_size_chart(self, chart_id: str, headers=None):
        return self._request("GET", f"{PREFIX}/size-charts/{chart_id}", headers=headers)

    def standardize_size_chart(self, chart_id: str, headers=None):
        return self._request(
            "POST", f"{PREFIX}/size-charts/{chart_id}/standardize", {}, headers
        )

    def retire_size_chart(self, chart_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/size-charts/{chart_id}/retire", payload, headers
        )

    # ------------------------------------------------------------------
    # Size chart mappings
    # ------------------------------------------------------------------

    def create_size_chart_mapping(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/size-chart-mappings", payload, headers)

    def get_size_chart_mapping(self, mapping_id: str, headers=None):
        return self._request(
            "GET", f"{PREFIX}/size-chart-mappings/{mapping_id}", headers=headers
        )

    def list_size_chart_mappings(self, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/size-chart-mappings", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Customer profiles and return policy
    # ------------------------------------------------------------------

    def create_customer_profile(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/customer-profiles", payload, headers)

    def get_customer_profile(self, customer_profile_id: str, headers=None):
        return self._request(
            "GET", f"{PREFIX}/customer-profiles/{customer_profile_id}", headers=headers
        )

    def create_return_policy_override(
        self, customer_profile_id: str, payload: dict, headers=None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/customer-profiles/{customer_profile_id}/return-policy-overrides",
            payload,
            headers,
        )

    def create_return_policy(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/return-policies", payload, headers)

    def get_return_policy(self, policy_id: str, headers=None):
        return self._request(
            "GET", f"{PREFIX}/return-policies/{policy_id}", headers=headers
        )

    def list_return_policies(self, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/return-policies", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Order lines
    # ------------------------------------------------------------------

    def create_order_line(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/order-lines", payload, headers)

    def get_order_line(self, order_line_id: str, headers=None):
        return self._request(
            "GET", f"{PREFIX}/order-lines/{order_line_id}", headers=headers
        )

    def list_order_lines(self, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/order-lines", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Return cases
    # ------------------------------------------------------------------

    def create_return_case(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/return-cases", payload, headers)

    def get_return_case(self, case_id: str, headers=None):
        return self._request("GET", f"{PREFIX}/return-cases/{case_id}", headers=headers)

    def list_return_cases(self, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/return-cases", headers=headers, params=params
        )

    def classify_return_case(self, case_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/return-cases/{case_id}/classify", payload, headers
        )

    def resolve_return_case(self, case_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/return-cases/{case_id}/resolve", payload, headers
        )

    def void_return_case(self, case_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/return-cases/{case_id}/void", payload, headers
        )

    def list_cost_postings(self, case_id: str, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET",
            f"{PREFIX}/return-cases/{case_id}/cost-postings",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Fit feedback
    # ------------------------------------------------------------------

    def create_fit_feedback(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/fit-feedback", payload, headers)

    def get_fit_feedback(self, feedback_id: str, headers=None):
        return self._request(
            "GET", f"{PREFIX}/fit-feedback/{feedback_id}", headers=headers
        )

    def list_fit_feedback(self, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/fit-feedback", headers=headers, params=params
        )

    def retract_fit_feedback(self, feedback_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/fit-feedback/{feedback_id}/retract", payload, headers
        )

    # ------------------------------------------------------------------
    # Interventions and deployments
    # ------------------------------------------------------------------

    def create_intervention(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/interventions", payload, headers)

    def get_intervention(self, intervention_id: str, headers=None):
        return self._request(
            "GET", f"{PREFIX}/interventions/{intervention_id}", headers=headers
        )

    def get_savings_report(
        self, intervention_id: str, headers=None, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/interventions/{intervention_id}/savings-report",
            headers=headers,
            params=params,
        )

    def create_intervention_deployment(self, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/intervention-deployments", payload, headers
        )

    def get_intervention_deployment(self, deployment_id: str, headers=None):
        return self._request(
            "GET", f"{PREFIX}/intervention-deployments/{deployment_id}", headers=headers
        )

    def list_intervention_deployments(self, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/intervention-deployments", headers=headers, params=params
        )

    def terminate_intervention_deployment(
        self, deployment_id: str, payload: dict, headers=None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/intervention-deployments/{deployment_id}/terminate",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # The ops-run checkpoint
    # ------------------------------------------------------------------

    def create_ops_run(self, headers=None):
        return self._request("POST", f"{PREFIX}/ops-runs", {}, headers)


api_client = ApiClient()
