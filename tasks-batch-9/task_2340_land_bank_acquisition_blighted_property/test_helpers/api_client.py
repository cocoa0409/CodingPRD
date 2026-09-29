"""
HTTP client with exactly one method per declared endpoint.

Every method returns the raw ``requests.Response`` so tests can assert both the
HTTP status and the response envelope. Paths are built from the ``/land-bank``
prefix; the logical-clock endpoint is the only one that sits outside it.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH

Headers = Dict[str, str]
Payload = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """One method per endpoint of the County Land Bank Authority API."""

    # ------------------------------------------------------------------ helpers
    def _p(self, suffix: str) -> str:
        return f"{API_PREFIX}{suffix}"

    # --------------------------------------------------------- property registry
    def create_property(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", self._p("/properties"), payload, headers)

    def get_property(self, property_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", self._p(f"/properties/{property_id}"), None, headers)

    def list_properties(
        self, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request("GET", self._p("/properties"), params, headers)

    def post_code_violation_report(
        self, property_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/properties/{property_id}/code-violation-report"),
            payload,
            headers,
        )

    def post_tax_roll_posting(
        self, property_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/properties/{property_id}/tax-roll-posting"),
            payload,
            headers,
        )

    def set_owner_of_record(
        self, property_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/properties/{property_id}/owner-of-record"),
            payload,
            headers,
        )

    def list_property_for_disposition(
        self, property_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        """POST /properties/{id}/list - move an inventory parcel to LISTED."""
        return self._request(
            "POST", self._p(f"/properties/{property_id}/list"), payload or {}, headers
        )

    def get_price_quote(
        self, property_id: str, program: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET",
            self._p(f"/properties/{property_id}/price-quote"),
            {"program": program},
            headers,
        )

    # ------------------------------------------------------------ title clearing
    def create_title_action(
        self, property_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", self._p(f"/properties/{property_id}/title-actions"), payload, headers
        )

    def list_title_actions(
        self, property_id: str, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/properties/{property_id}/title-actions"), params, headers
        )

    def adjudicate_title_action(
        self, title_action_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/title-actions/{title_action_id}/adjudicate"),
            payload,
            headers,
        )

    # ------------------------------------------------------- community engagement
    def create_reuse_hearing(
        self, property_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/properties/{property_id}/reuse-hearings"),
            payload,
            headers,
        )

    def list_reuse_hearings(
        self, property_id: str, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/properties/{property_id}/reuse-hearings"), params, headers
        )

    # ------------------------------------------------------------ adjacency graph
    def create_parcel_adjacency(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", self._p("/parcel-adjacencies"), payload, headers)

    def list_adjacencies(
        self, property_id: str, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/properties/{property_id}/adjacencies"), params, headers
        )

    # -------------------------------------------------------------------- funding
    def create_funding_source(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", self._p("/funding-sources"), payload, headers)

    def get_funding_source(
        self, funding_source_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/funding-sources/{funding_source_id}"), None, headers
        )

    def list_funding_source_demolition_runs(
        self, funding_source_id: str, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request(
            "GET",
            self._p(f"/funding-sources/{funding_source_id}/demolition-runs"),
            params,
            headers,
        )

    def post_tif_recapture(
        self, funding_source_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/funding-sources/{funding_source_id}/tif-recapture"),
            payload,
            headers,
        )

    # ---------------------------------------------------------------- acquisition
    def create_acquisition_packet(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", self._p("/acquisition-packets"), payload, headers)

    def get_acquisition_packet(
        self, packet_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/acquisition-packets/{packet_id}"), None, headers
        )

    def list_acquisition_packets(
        self, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request("GET", self._p("/acquisition-packets"), params, headers)

    def board_approve_packet(
        self, packet_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/acquisition-packets/{packet_id}/board-approval"),
            payload,
            headers,
        )

    def close_packet(
        self, packet_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", self._p(f"/acquisition-packets/{packet_id}/close"), payload, headers
        )

    def decline_packet(
        self, packet_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/acquisition-packets/{packet_id}/decline"),
            payload,
            headers,
        )

    # ------------------------------------------------------- inventory maintenance
    def create_contractor(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", self._p("/contractors"), payload, headers)

    def create_maintenance_order(
        self, property_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/properties/{property_id}/maintenance-orders"),
            payload,
            headers,
        )

    def get_maintenance_order(
        self, order_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/maintenance-orders/{order_id}"), None, headers
        )

    def list_maintenance_orders(
        self, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request("GET", self._p("/maintenance-orders"), params, headers)

    def complete_maintenance_order(
        self, order_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", self._p(f"/maintenance-orders/{order_id}/complete"), payload, headers
        )

    def cancel_maintenance_order(
        self, order_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", self._p(f"/maintenance-orders/{order_id}/cancel"), payload, headers
        )

    # ------------------------------------------------- demolition prioritization
    def create_demolition_run(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", self._p("/demolition-runs"), payload, headers)

    def execute_demolition_run(
        self, run_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST", self._p(f"/demolition-runs/{run_id}/execute"), payload or {}, headers
        )

    # ------------------------------------------------- applicants and disposition
    def create_applicant(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", self._p("/applicants"), payload, headers)

    def get_applicant(self, applicant_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", self._p(f"/applicants/{applicant_id}"), None, headers
        )

    def create_disposition_application(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", self._p("/disposition-applications"), payload, headers
        )

    def get_disposition_application(
        self, application_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/disposition-applications/{application_id}"), None, headers
        )

    def list_disposition_applications(
        self, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request(
            "GET", self._p("/disposition-applications"), params, headers
        )

    def submit_application(
        self, application_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/disposition-applications/{application_id}/submit"),
            payload or {},
            headers,
        )

    def screen_application(
        self, application_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/disposition-applications/{application_id}/screen"),
            payload or {},
            headers,
        )

    def list_screenings(
        self, application_id: str, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request(
            "GET",
            self._p(f"/disposition-applications/{application_id}/screenings"),
            params,
            headers,
        )

    def request_info(
        self, application_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/disposition-applications/{application_id}/request-info"),
            payload,
            headers,
        )

    def resubmit_application(
        self, application_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/disposition-applications/{application_id}/resubmit"),
            payload or {},
            headers,
        )

    def recommend_application(
        self, application_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/disposition-applications/{application_id}/recommend"),
            payload,
            headers,
        )

    def board_decision(
        self, application_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/disposition-applications/{application_id}/board-decision"),
            payload,
            headers,
        )

    # ----------------------------------------------------- development agreements
    def create_development_agreement(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", self._p("/development-agreements"), payload, headers
        )

    def get_development_agreement(
        self, agreement_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/development-agreements/{agreement_id}"), None, headers
        )

    def list_development_agreements(
        self, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request("GET", self._p("/development-agreements"), params, headers)

    def report_milestone_completions(
        self, agreement_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/development-agreements/{agreement_id}/milestone-completions"),
            payload,
            headers,
        )

    # ------------------------------------------------- operations and summaries
    def run_compliance_sweep(
        self, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST", self._p("/compliance-sweeps"), payload or {}, headers
        )

    def get_inventory_summary(
        self, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request("GET", self._p("/inventory-summary"), params, headers)

    def set_clock(self, to_iso8601: str, headers: Headers) -> requests.Response:
        """Set the server's logical UTC clock."""
        return self._request(
            "POST", CLOCK_PATH, {"to_iso8601": to_iso8601}, headers
        )
