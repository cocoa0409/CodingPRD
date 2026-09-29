"""Typed HTTP client: one method per endpoint in the PRD endpoint table.

Every method returns the raw ``requests.Response`` so tests can assert on the
status code as well as the envelope.
"""
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Client for the Retail Co-Tenancy & Exclusive Use Administration API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Shopping centers
    # ------------------------------------------------------------------
    def create_center(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/centers", payload, headers)

    def get_center(
        self, center_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/centers/{center_id}", None, headers)

    def list_centers(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/centers", None, headers, params)

    def compliance_sweep(
        self,
        center_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/centers/{center_id}/compliance-sweep", payload, headers
        )

    # ------------------------------------------------------------------
    # Tenants
    # ------------------------------------------------------------------
    def create_tenant(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/tenants", payload, headers)

    def get_tenant(
        self, tenant_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/tenants/{tenant_id}", None, headers)

    def patch_tenant(
        self,
        tenant_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("PATCH", f"/tenants/{tenant_id}", payload, headers)

    def list_tenant_disputes(
        self,
        tenant_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/tenants/{tenant_id}/use-violation-disputes", None, headers, params
        )

    # ------------------------------------------------------------------
    # Leases
    # ------------------------------------------------------------------
    def create_lease(
        self,
        center_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("POST", f"/centers/{center_id}/leases", payload, headers)

    def get_lease(
        self, lease_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/leases/{lease_id}", None, headers)

    def list_leases(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/leases", None, headers, params)

    def screen_use(
        self,
        lease_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("POST", f"/leases/{lease_id}/screen-use", payload, headers)

    def execute_lease(
        self,
        lease_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("POST", f"/leases/{lease_id}/execute", payload, headers)

    def open_lease(
        self,
        lease_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("POST", f"/leases/{lease_id}/open", payload, headers)

    def go_dark(
        self,
        lease_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("POST", f"/leases/{lease_id}/go-dark", payload, headers)

    def reopen_lease(
        self,
        lease_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("POST", f"/leases/{lease_id}/reopen", payload, headers)

    def terminate_lease(
        self,
        lease_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("POST", f"/leases/{lease_id}/terminate", payload, headers)

    # ------------------------------------------------------------------
    # Co-tenancy conditions
    # ------------------------------------------------------------------
    def create_condition(
        self,
        lease_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/leases/{lease_id}/co-tenancy-conditions", payload, headers
        )

    def get_condition(
        self, condition_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/co-tenancy-conditions/{condition_id}", None, headers
        )

    def list_conditions(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/co-tenancy-conditions", None, headers, params)

    def waive_condition(
        self,
        condition_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/co-tenancy-conditions/{condition_id}/waive", payload, headers
        )

    # ------------------------------------------------------------------
    # Anchor requirements
    # ------------------------------------------------------------------
    def create_anchor_requirement(
        self,
        condition_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/co-tenancy-conditions/{condition_id}/anchor-requirements",
            payload,
            headers,
        )

    def get_anchor_requirement(
        self, requirement_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/anchor-requirements/{requirement_id}", None, headers
        )

    def list_anchor_requirements(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/anchor-requirements", None, headers, params)

    # ------------------------------------------------------------------
    # Exclusive-use clauses
    # ------------------------------------------------------------------
    def create_clause(
        self,
        lease_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/leases/{lease_id}/exclusive-use-clauses", payload, headers
        )

    def get_clause(
        self, clause_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/exclusive-use-clauses/{clause_id}", None, headers
        )

    def list_clauses(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/exclusive-use-clauses", None, headers, params)

    # ------------------------------------------------------------------
    # Radius restrictions
    # ------------------------------------------------------------------
    def create_radius_restriction(
        self,
        lease_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/leases/{lease_id}/radius-restrictions", payload, headers
        )

    def get_radius_restriction(
        self, restriction_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/radius-restrictions/{restriction_id}", None, headers
        )

    def list_radius_restrictions(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/radius-restrictions", None, headers, params)

    def report_radius_violation(
        self,
        restriction_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/radius-restrictions/{restriction_id}/violation-report",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Use-violation notices
    # ------------------------------------------------------------------
    def create_notice(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/use-violation-notices", payload, headers)

    def get_notice(
        self, notice_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/use-violation-notices/{notice_id}", None, headers
        )

    def list_notices(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/use-violation-notices", None, headers, params)

    def list_notice_disputes(
        self,
        notice_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/use-violation-notices/{notice_id}/disputes",
            None,
            headers,
            params,
        )

    def cure_notice(
        self,
        notice_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/use-violation-notices/{notice_id}/cure", payload, headers
        )

    def escalate_notice(
        self,
        notice_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/use-violation-notices/{notice_id}/escalate", payload, headers
        )

    def withdraw_notice(
        self,
        notice_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/use-violation-notices/{notice_id}/withdraw", payload, headers
        )

    def create_dispute(
        self,
        notice_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/use-violation-notices/{notice_id}/disputes", payload, headers
        )

    # ------------------------------------------------------------------
    # Use-violation disputes
    # ------------------------------------------------------------------
    def get_dispute(
        self, dispute_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/use-violation-disputes/{dispute_id}", None, headers
        )

    def list_disputes(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/use-violation-disputes", None, headers, params)

    def adjudicate_dispute(
        self,
        dispute_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/use-violation-disputes/{dispute_id}/adjudicate",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Occupancy measurements
    # ------------------------------------------------------------------
    def create_measurement(
        self,
        center_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/centers/{center_id}/occupancy-measurements", payload, headers
        )

    def get_measurement(
        self, measurement_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/occupancy-measurements/{measurement_id}", None, headers
        )

    def list_measurements(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/occupancy-measurements", None, headers, params)

    def list_center_measurements(
        self,
        center_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/centers/{center_id}/occupancy-measurements",
            None,
            headers,
            params,
        )

    def certify_measurement(
        self,
        measurement_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/occupancy-measurements/{measurement_id}/certify",
            payload,
            headers,
        )

    def supersede_measurement(
        self,
        measurement_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/occupancy-measurements/{measurement_id}/supersede",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Remedy elections
    # ------------------------------------------------------------------
    def create_election(
        self,
        lease_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/leases/{lease_id}/remedy-elections", payload, headers
        )

    def get_election(
        self, election_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/remedy-elections/{election_id}", None, headers)

    def list_elections(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/remedy-elections", None, headers, params)

    def approve_election(
        self,
        election_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/remedy-elections/{election_id}/approve", payload, headers
        )

    def rescind_election(
        self,
        election_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/remedy-elections/{election_id}/rescind", payload, headers
        )

    def consummate_election(
        self,
        election_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/remedy-elections/{election_id}/consummate", payload, headers
        )

    # ------------------------------------------------------------------
    # Estoppel certificates
    # ------------------------------------------------------------------
    def create_certificate(
        self,
        lease_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/leases/{lease_id}/estoppel-certificates", payload, headers
        )

    def get_certificate(
        self, certificate_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/estoppel-certificates/{certificate_id}", None, headers
        )

    def list_certificates(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/estoppel-certificates", None, headers, params)

    def sign_certificate(
        self,
        certificate_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/estoppel-certificates/{certificate_id}/sign", payload, headers
        )

    def accept_certificate(
        self,
        certificate_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/estoppel-certificates/{certificate_id}/accept", payload, headers
        )

    def reject_certificate(
        self,
        certificate_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/estoppel-certificates/{certificate_id}/reject", payload, headers
        )

    # ------------------------------------------------------------------
    # Redevelopment plans
    # ------------------------------------------------------------------
    def create_plan(
        self,
        center_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/centers/{center_id}/redevelopment-plans", payload, headers
        )

    def get_plan(
        self, plan_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/redevelopment-plans/{plan_id}", None, headers)

    def list_plans(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/redevelopment-plans", None, headers, params)

    def record_plan(
        self,
        plan_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/redevelopment-plans/{plan_id}/record", payload, headers
        )

    def abandon_plan(
        self,
        plan_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/redevelopment-plans/{plan_id}/abandon", payload, headers
        )
