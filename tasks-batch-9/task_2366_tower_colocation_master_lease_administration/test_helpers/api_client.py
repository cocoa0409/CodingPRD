"""One method per endpoint declared in PRD §4.

Every method returns the raw ``requests.Response`` so tests can assert on the
HTTP status as well as the envelope. Bodies are passed exactly as given, which
lets negative tests send malformed or partial payloads.
"""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


class ApiClient(GenericApiClient):
    """Typed surface over the ``/tower-colo`` API."""

    # ─── Towers ──────────────────────────────────────────────────────────────

    def create_tower(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/towers", payload, headers)

    def list_towers(self, params: Optional[Dict] = None, headers=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/towers", params, headers)

    def get_tower(self, tower_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/towers/{tower_id}", None, headers)

    def get_capacity_summary(self, tower_id: str, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/towers/{tower_id}/capacity-summary", None, headers
        )

    # ─── Landlords ───────────────────────────────────────────────────────────

    def create_landlord(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/landlords", payload, headers)

    # ─── Ground leases ───────────────────────────────────────────────────────

    def create_ground_lease(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/ground-leases", payload, headers)

    def list_ground_leases(self, params: Optional[Dict] = None, headers=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/ground-leases", params, headers)

    def get_ground_lease(self, lease_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/ground-leases/{lease_id}", None, headers)

    def open_ground_lease_renewal(
        self, lease_id: str, payload: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/ground-leases/{lease_id}/open-renewal", payload or {}, headers
        )

    def renew_ground_lease(
        self, lease_id: str, payload: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/ground-leases/{lease_id}/renew", payload or {}, headers
        )

    def buyout_ground_lease(
        self, lease_id: str, payload: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/ground-leases/{lease_id}/buyout", payload or {}, headers
        )

    # ─── Landlord payments ───────────────────────────────────────────────────

    def create_landlord_payment(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/landlord-payments", payload, headers)

    def list_landlord_payments(
        self, lease_id: str, params: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/ground-leases/{lease_id}/landlord-payments", params, headers
        )

    # ─── Tenants ─────────────────────────────────────────────────────────────

    def create_tenant(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/tenants", payload, headers)

    def get_tenant(self, tenant_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/tenants/{tenant_id}", None, headers)

    def create_tenant_payment(
        self, tenant_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/tenants/{tenant_id}/payments", payload, headers
        )

    # ─── Master lease agreements ─────────────────────────────────────────────

    def create_master_lease_agreement(
        self, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/master-lease-agreements", payload, headers)

    def activate_master_lease_agreement(
        self, mla_id: str, payload: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/master-lease-agreements/{mla_id}/activate",
            payload or {},
            headers,
        )

    def reinstate_master_lease_agreement(
        self, mla_id: str, payload: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/master-lease-agreements/{mla_id}/reinstate",
            payload or {},
            headers,
        )

    def list_tenant_master_lease_agreements(
        self, tenant_id: str, params: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/tenants/{tenant_id}/master-lease-agreements", params, headers
        )

    # ─── Colocation applications ─────────────────────────────────────────────

    def create_colocation_application(
        self, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/colocation-applications", payload, headers)

    def list_colocation_applications(
        self, params: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/colocation-applications", params, headers)

    def get_colocation_application(self, app_id: str, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/colocation-applications/{app_id}", None, headers
        )

    def submit_colocation_application(
        self, app_id: str, payload: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/colocation-applications/{app_id}/submit", payload or {}, headers
        )

    def revise_colocation_application(
        self, app_id: str, payload: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/colocation-applications/{app_id}/revise", payload or {}, headers
        )

    def approve_colocation_application(
        self, app_id: str, payload: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/colocation-applications/{app_id}/approve", payload or {}, headers
        )

    def reject_colocation_application(
        self, app_id: str, payload: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/colocation-applications/{app_id}/reject", payload or {}, headers
        )

    def withdraw_colocation_application(
        self, app_id: str, payload: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/colocation-applications/{app_id}/withdraw",
            payload or {},
            headers,
        )

    # ─── Equipment lines ─────────────────────────────────────────────────────

    def create_equipment_line(
        self, app_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/colocation-applications/{app_id}/equipment-lines", payload, headers
        )

    def list_equipment_lines(
        self, params: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/equipment-lines", params, headers)

    def get_equipment_line(self, line_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/equipment-lines/{line_id}", None, headers)

    def delete_equipment_line(self, line_id: str, headers=None) -> requests.Response:
        return self._request("DELETE", f"{API_PREFIX}/equipment-lines/{line_id}", None, headers)

    # ─── Structural analyses ─────────────────────────────────────────────────

    def create_structural_analysis(
        self, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/structural-analyses", payload, headers)

    def issue_quotation(
        self, analysis_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/structural-analyses/{analysis_id}/quotation", payload, headers
        )

    def list_application_structural_analyses(
        self, app_id: str, params: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/colocation-applications/{app_id}/structural-analyses",
            params,
            headers,
        )

    # ─── Site amendments ─────────────────────────────────────────────────────

    def create_site_amendment(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/site-amendments", payload, headers)

    def list_site_amendments(
        self, params: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/site-amendments", params, headers)

    def get_site_amendment(self, amendment_id: str, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/site-amendments/{amendment_id}", None, headers
        )

    def execute_site_amendment(
        self, amendment_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/site-amendments/{amendment_id}/execute", payload, headers
        )

    def void_site_amendment(
        self, amendment_id: str, payload: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/site-amendments/{amendment_id}/void", payload or {}, headers
        )

    def set_site_amendment_billing_status(
        self, amendment_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/site-amendments/{amendment_id}/billing-status", payload, headers
        )

    def give_termination_notice(
        self, amendment_id: str, payload: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/site-amendments/{amendment_id}/termination-notice",
            payload or {},
            headers,
        )

    def complete_decommission(
        self, amendment_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/site-amendments/{amendment_id}/complete-decommission",
            payload,
            headers,
        )

    # ─── Modification projects ───────────────────────────────────────────────

    def create_modification_project(
        self, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/modification-projects", payload, headers)

    def list_modification_projects(
        self, params: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/modification-projects", params, headers)

    def get_modification_project(self, project_id: str, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/modification-projects/{project_id}", None, headers
        )

    def allocate_cost_shares(
        self, project_id: str, payload: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/modification-projects/{project_id}/allocate-cost-shares",
            payload or {},
            headers,
        )

    def reallocate_cost_shares(
        self, project_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/modification-projects/{project_id}/reallocate-cost-shares",
            payload,
            headers,
        )

    def start_construction(
        self, project_id: str, payload: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/modification-projects/{project_id}/start-construction",
            payload or {},
            headers,
        )

    def certify_completion(
        self, project_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/modification-projects/{project_id}/certify-completion",
            payload,
            headers,
        )

    def cancel_modification_project(
        self, project_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/modification-projects/{project_id}/cancel", payload, headers
        )

    # ─── Cost shares ─────────────────────────────────────────────────────────

    def list_cost_shares(self, params: Optional[Dict] = None, headers=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/cost-shares", params, headers)

    def get_cost_share(self, share_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/cost-shares/{share_id}", None, headers)

    def accept_cost_share(
        self, share_id: str, payload: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/cost-shares/{share_id}/accept", payload or {}, headers
        )

    def decline_cost_share(
        self, share_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/cost-shares/{share_id}/decline", payload, headers
        )

    # ─── Equipment audits and findings ───────────────────────────────────────

    def create_equipment_audit(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/equipment-audits", payload, headers)

    def list_tower_equipment_audits(
        self, tower_id: str, params: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/towers/{tower_id}/equipment-audits", params, headers
        )

    def start_equipment_audit(
        self, audit_id: str, payload: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/equipment-audits/{audit_id}/start", payload or {}, headers
        )

    def create_audit_finding(
        self, audit_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/equipment-audits/{audit_id}/findings", payload, headers
        )

    def list_audit_findings(
        self, params: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/audit-findings", params, headers)

    def get_audit_finding(self, finding_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/audit-findings/{finding_id}", None, headers)

    def finalize_equipment_audit(
        self, audit_id: str, payload: Optional[Dict] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/equipment-audits/{audit_id}/finalize", payload or {}, headers
        )

    # ─── Logical clock ───────────────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers)
