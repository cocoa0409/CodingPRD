"""
One method per declared endpoint.

Every method returns the raw ``requests.Response`` so that tests can assert on
status codes as well as bodies.  List methods take an optional ``params``
dictionary that is forwarded as the query string; the two report reads take
their window and selector as query parameters too.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """HTTP client for the Transit Fare Enforcement & Proof of Payment API."""

    # ── The logical clock ────────────────────────────────────────────
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Fare zones ───────────────────────────────────────────────────
    def create_fare_zone(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/fare-zones", payload, headers)

    def submit_zone_for_signage(self, zone_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/fare-zones/{zone_id}/submit-for-signage", {}, headers)

    def designate_zone(self, zone_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/fare-zones/{zone_id}/designate", {}, headers)

    def suspend_zone(self, zone_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/fare-zones/{zone_id}/suspend", {}, headers)

    def revoke_zone(self, zone_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/fare-zones/{zone_id}/revoke", {}, headers)

    def get_fare_zone(self, zone_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/fare-zones/{zone_id}", None, headers)

    def list_fare_zones(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/fare-zones", params, headers)

    def list_zone_signage_audits(
        self, zone_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/fare-zones/{zone_id}/signage-audits", params, headers)

    # ── Signage audits ───────────────────────────────────────────────
    def create_signage_audit(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/signage-audits", payload, headers)

    # ── Transit lines ────────────────────────────────────────────────
    def create_transit_line(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/transit-lines", payload, headers)

    def get_transit_line(self, line_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/transit-lines/{line_id}", None, headers)

    # ── Zone-line assignments ────────────────────────────────────────
    def create_zone_line_assignment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/zone-line-assignments", payload, headers)

    def get_zone_line_assignment(
        self, assignment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/zone-line-assignments/{assignment_id}", None, headers)

    def list_zone_line_assignments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/zone-line-assignments", params, headers)

    # ── Inspectors ───────────────────────────────────────────────────
    def create_inspector(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/inspectors", payload, headers)

    def get_inspector(self, inspector_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/inspectors/{inspector_id}", None, headers)

    # ── Riders ───────────────────────────────────────────────────────
    def create_rider(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/riders", payload, headers)

    def get_rider(self, rider_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/riders/{rider_id}", None, headers)

    # ── Inspection deployments ───────────────────────────────────────
    def create_inspection_deployment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/inspection-deployments", payload, headers)

    def activate_deployment(self, deployment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection-deployments/{deployment_id}/activate", {}, headers)

    def close_deployment(self, deployment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection-deployments/{deployment_id}/close", {}, headers)

    def void_deployment(self, deployment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection-deployments/{deployment_id}/void", {}, headers)

    def get_deployment(self, deployment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/inspection-deployments/{deployment_id}", None, headers)

    def list_deployments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/inspection-deployments", params, headers)

    # ── Inspection encounters ────────────────────────────────────────
    def create_inspection_encounter(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/inspection-encounters", payload, headers)

    def resolve_encounter(
        self, encounter_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/inspection-encounters/{encounter_id}/resolve", payload, headers
        )

    def get_encounter(self, encounter_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/inspection-encounters/{encounter_id}", None, headers)

    def list_encounters(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/inspection-encounters", params, headers)

    # ── Citations ────────────────────────────────────────────────────
    def create_citation(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/citations", payload, headers)

    def get_citation(self, citation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/citations/{citation_id}", None, headers)

    def list_citations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/citations", params, headers)

    def list_citation_payments(
        self, citation_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/citations/{citation_id}/payments", params, headers)

    def contest_citation(self, citation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/citations/{citation_id}/contest", {}, headers)

    def create_citation_payment(
        self, citation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/citations/{citation_id}/payments", payload, headers)

    def reissue_citation(self, citation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/citations/{citation_id}/reissue", {}, headers)

    # ── Adjudication hearings ────────────────────────────────────────
    def decide_hearing(
        self, hearing_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/adjudication-hearings/{hearing_id}/decide", payload, headers)

    def cancel_hearing(self, hearing_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/adjudication-hearings/{hearing_id}/cancel", {}, headers)

    def get_hearing(self, hearing_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/adjudication-hearings/{hearing_id}", None, headers)

    def list_hearings(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/adjudication-hearings", params, headers)

    # ── Appeals ──────────────────────────────────────────────────────
    def create_appeal(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/appeals", payload, headers)

    def request_appeal_supplement(self, appeal_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/appeals/{appeal_id}/request-supplement", {}, headers)

    def resubmit_appeal(
        self, appeal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/appeals/{appeal_id}/resubmit", payload, headers)

    def decide_appeal(
        self, appeal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/appeals/{appeal_id}/decide", payload, headers)

    def withdraw_appeal(self, appeal_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/appeals/{appeal_id}/withdraw", {}, headers)

    def get_appeal(self, appeal_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/appeals/{appeal_id}", None, headers)

    def list_appeals(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/appeals", params, headers)

    # ── Payment plans ────────────────────────────────────────────────
    def create_payment_plan(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/payment-plans", payload, headers)

    def pay_installment(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/payment-plans/{plan_id}/installments", payload, headers)

    def assess_delinquency(self, plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/payment-plans/{plan_id}/assess-delinquency", {}, headers)

    def get_payment_plan(self, plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/payment-plans/{plan_id}", None, headers)

    def list_payment_plans(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/payment-plans", params, headers)

    def list_plan_payments(
        self, plan_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/payment-plans/{plan_id}/payments", params, headers)

    # ── Community-service assignments ────────────────────────────────
    def create_service_assignment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/community-service-assignments", payload, headers)

    def log_service_hours(
        self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/community-service-assignments/{assignment_id}/log-hours", payload, headers
        )

    def get_service_assignment(
        self, assignment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/community-service-assignments/{assignment_id}", None, headers
        )

    def list_service_assignments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/community-service-assignments", params, headers)

    # ── Analytics ────────────────────────────────────────────────────
    def get_equity_distribution_report(
        self, params: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", "/reports/equity-distribution", params, headers)

    def get_revenue_recovery_report(
        self, params: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", "/reports/revenue-recovery", params, headers)
