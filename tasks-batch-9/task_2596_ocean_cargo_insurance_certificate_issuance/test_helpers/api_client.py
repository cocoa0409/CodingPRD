"""
HTTP client for the Ocean Cargo Insurance API.

One method per documented endpoint. Every method returns the raw
`requests.Response` so tests can assert on status codes as well as bodies.
Collection reads take their filters through `params`; writes take a JSON
`payload`. Auth headers are always explicit — the caller decides which role
and which user identity is acting.
"""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

from .types import ApiResponse, Headers, JsonDict, Params


class ApiClient(GenericApiClient):
    """Typed access to every endpoint of the Ocean Cargo Insurance API."""

    # ------------------------------------------------------------------
    # Open cover (OpenPolicy)
    # ------------------------------------------------------------------
    def create_open_policy(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/open-policies", payload, headers)

    def get_open_policy(self, policy_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/open-policies/{policy_id}", None, headers)

    def activate_open_policy(self, policy_id: str, headers: Headers,
                             payload: Optional[JsonDict] = None) -> ApiResponse:
        return self._request("POST", f"/open-policies/{policy_id}/activate",
                             payload or {}, headers)

    def reinstate_war_cover(self, policy_id: str, payload: JsonDict,
                            headers: Headers) -> ApiResponse:
        return self._request("POST", f"/open-policies/{policy_id}/reinstate-war-cover",
                             payload, headers)

    def run_transit_sweep(self, policy_id: str, headers: Headers,
                          payload: Optional[JsonDict] = None) -> ApiResponse:
        return self._request("POST", f"/open-policies/{policy_id}/run-transit-sweep",
                             payload or {}, headers)

    # ------------------------------------------------------------------
    # Commodity classes
    # ------------------------------------------------------------------
    def create_commodity_class(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/commodity-classes", payload, headers)

    def list_commodity_classes(self, headers: Headers, params: Params = None) -> ApiResponse:
        return self._request("GET", "/commodity-classes", params, headers)

    # ------------------------------------------------------------------
    # Vessels
    # ------------------------------------------------------------------
    def create_vessel(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/vessels", payload, headers)

    def get_vessel(self, vessel_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/vessels/{vessel_id}", None, headers)

    def review_vessel_classification(self, vessel_id: str, headers: Headers,
                                     payload: Optional[JsonDict] = None) -> ApiResponse:
        return self._request("POST", f"/vessels/{vessel_id}/classification-review",
                             payload or {}, headers)

    # ------------------------------------------------------------------
    # Ports
    # ------------------------------------------------------------------
    def create_port(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/ports", payload, headers)

    def get_port(self, port_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/ports/{port_id}", None, headers)

    def list_ports(self, headers: Headers, params: Params = None) -> ApiResponse:
        return self._request("GET", "/ports", params, headers)

    def set_port_war_risk_tier(self, port_id: str, payload: JsonDict,
                               headers: Headers) -> ApiResponse:
        return self._request("POST", f"/ports/{port_id}/war-risk-tier", payload, headers)

    def list_port_surveyors(self, port_id: str, headers: Headers,
                            params: Params = None) -> ApiResponse:
        return self._request("GET", f"/ports/{port_id}/surveyors", params, headers)

    # ------------------------------------------------------------------
    # Surveyors
    # ------------------------------------------------------------------
    def create_surveyor(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/surveyors", payload, headers)

    def get_surveyor(self, surveyor_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/surveyors/{surveyor_id}", None, headers)

    def suspend_surveyor(self, surveyor_id: str, headers: Headers,
                         payload: Optional[JsonDict] = None) -> ApiResponse:
        return self._request("POST", f"/surveyors/{surveyor_id}/suspend",
                             payload or {}, headers)

    # ------------------------------------------------------------------
    # Certificates
    # ------------------------------------------------------------------
    def create_certificate(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/certificates", payload, headers)

    def get_certificate(self, certificate_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/certificates/{certificate_id}", None, headers)

    def list_certificates(self, headers: Headers, params: Params = None) -> ApiResponse:
        return self._request("GET", "/certificates", params, headers)

    def issue_certificate(self, certificate_id: str, payload: JsonDict,
                          headers: Headers) -> ApiResponse:
        return self._request("POST", f"/certificates/{certificate_id}/issue",
                             payload, headers)

    def endorse_certificate(self, certificate_id: str, payload: JsonDict,
                            headers: Headers) -> ApiResponse:
        return self._request("POST", f"/certificates/{certificate_id}/endorse",
                             payload, headers)

    def cancel_certificate(self, certificate_id: str, headers: Headers,
                           payload: Optional[JsonDict] = None) -> ApiResponse:
        return self._request("POST", f"/certificates/{certificate_id}/cancel",
                             payload or {}, headers)

    def confirm_delivery(self, certificate_id: str, headers: Headers,
                         payload: Optional[JsonDict] = None) -> ApiResponse:
        return self._request("POST", f"/certificates/{certificate_id}/confirm-delivery",
                             payload or {}, headers)

    # ------------------------------------------------------------------
    # Accumulation ledger
    # ------------------------------------------------------------------
    def list_accumulation_entries(self, headers: Headers,
                                  params: Params = None) -> ApiResponse:
        return self._request("GET", "/accumulation-entries", params, headers)

    def get_accumulation_entry(self, entry_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/accumulation-entries/{entry_id}", None, headers)

    # ------------------------------------------------------------------
    # Premium declarations
    # ------------------------------------------------------------------
    def create_premium_declaration(self, payload: JsonDict,
                                   headers: Headers) -> ApiResponse:
        return self._request("POST", "/premium-declarations", payload, headers)

    def get_premium_declaration(self, declaration_id: str,
                                headers: Headers) -> ApiResponse:
        return self._request("GET", f"/premium-declarations/{declaration_id}",
                             None, headers)

    def list_premium_declarations(self, headers: Headers,
                                  params: Params = None) -> ApiResponse:
        return self._request("GET", "/premium-declarations", params, headers)

    def submit_premium_declaration(self, declaration_id: str, payload: JsonDict,
                                   headers: Headers) -> ApiResponse:
        return self._request("POST", f"/premium-declarations/{declaration_id}/submit",
                             payload, headers)

    def start_declaration_audit(self, declaration_id: str, headers: Headers,
                                payload: Optional[JsonDict] = None) -> ApiResponse:
        return self._request("POST",
                             f"/premium-declarations/{declaration_id}/start-audit",
                             payload or {}, headers)

    def finish_declaration_audit(self, declaration_id: str, headers: Headers,
                                 payload: Optional[JsonDict] = None) -> ApiResponse:
        return self._request("POST",
                             f"/premium-declarations/{declaration_id}/finish-audit",
                             payload or {}, headers)

    # ------------------------------------------------------------------
    # Claim files and their evidence log
    # ------------------------------------------------------------------
    def create_claim_file(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/claim-files", payload, headers)

    def get_claim_file(self, claim_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/claim-files/{claim_id}", None, headers)

    def list_claim_files(self, headers: Headers, params: Params = None) -> ApiResponse:
        return self._request("GET", "/claim-files", params, headers)

    def add_claim_document(self, claim_id: str, payload: JsonDict,
                           headers: Headers) -> ApiResponse:
        return self._request("POST", f"/claim-files/{claim_id}/documents",
                             payload, headers)

    def list_claim_documents(self, claim_id: str, headers: Headers,
                             params: Params = None) -> ApiResponse:
        return self._request("GET", f"/claim-files/{claim_id}/documents",
                             params, headers)

    def adjust_claim_file(self, claim_id: str, headers: Headers,
                          payload: Optional[JsonDict] = None) -> ApiResponse:
        return self._request("POST", f"/claim-files/{claim_id}/adjust",
                             payload or {}, headers)

    def settle_claim_file(self, claim_id: str, headers: Headers,
                          payload: Optional[JsonDict] = None) -> ApiResponse:
        return self._request("POST", f"/claim-files/{claim_id}/settle",
                             payload or {}, headers)

    def send_subrogation_notice(self, claim_id: str, payload: JsonDict,
                                headers: Headers) -> ApiResponse:
        return self._request("POST", f"/claim-files/{claim_id}/subrogation-notice",
                             payload, headers)

    def record_subrogation_recovery(self, claim_id: str, payload: JsonDict,
                                    headers: Headers) -> ApiResponse:
        return self._request("POST", f"/claim-files/{claim_id}/subrogation-recovery",
                             payload, headers)

    # ------------------------------------------------------------------
    # Survey orders
    # ------------------------------------------------------------------
    def create_survey_order(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/survey-orders", payload, headers)

    def get_survey_order(self, order_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/survey-orders/{order_id}", None, headers)

    def list_survey_orders(self, headers: Headers, params: Params = None) -> ApiResponse:
        return self._request("GET", "/survey-orders", params, headers)

    def file_survey_report(self, order_id: str, payload: JsonDict,
                           headers: Headers) -> ApiResponse:
        return self._request("POST", f"/survey-orders/{order_id}/file-report",
                             payload, headers)

    def cancel_survey_order(self, order_id: str, headers: Headers,
                            payload: Optional[JsonDict] = None) -> ApiResponse:
        return self._request("POST", f"/survey-orders/{order_id}/cancel",
                             payload or {}, headers)

    # ------------------------------------------------------------------
    # General average
    # ------------------------------------------------------------------
    def create_ga_event(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/ga-events", payload, headers)

    def get_ga_event(self, ga_event_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/ga-events/{ga_event_id}", None, headers)

    def list_ga_events(self, headers: Headers, params: Params = None) -> ApiResponse:
        return self._request("GET", "/ga-events", params, headers)

    def issue_ga_security_calls(self, ga_event_id: str, headers: Headers,
                                payload: Optional[JsonDict] = None) -> ApiResponse:
        return self._request("POST", f"/ga-events/{ga_event_id}/issue-security-calls",
                             payload or {}, headers)

    def list_ga_security_postings(self, headers: Headers,
                                  params: Params = None) -> ApiResponse:
        return self._request("GET", "/ga-security-postings", params, headers)

    def get_ga_security_posting(self, posting_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/ga-security-postings/{posting_id}", None, headers)

    def post_ga_security(self, posting_id: str, payload: JsonDict,
                         headers: Headers) -> ApiResponse:
        return self._request("POST", f"/ga-security-postings/{posting_id}/post",
                             payload, headers)

    def finalize_ga_adjustment(self, ga_event_id: str, headers: Headers,
                               payload: Optional[JsonDict] = None) -> ApiResponse:
        return self._request("POST", f"/ga-events/{ga_event_id}/finalize-adjustment",
                             payload or {}, headers)

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_current_utc(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)
