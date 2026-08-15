"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Administrative test-driving capabilities (PRD §2.9, §3.8)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def simulate_vulnerability_feed(self, payload, headers):
        return self._request("POST", "/_vulnerability-feed/simulate", payload, headers)

    def process_next_scan(self, scan_id, headers):
        return self._request(
            "POST", "/_scan-worker/process-next", {"scan_id": scan_id}, headers
        )

    # ------------------------------------------------------------------
    # Products (PRD §3.1)
    # ------------------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/oss-products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/oss-products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/oss-products/{product_id}", headers=headers)

    def unblock_product(self, product_id, payload, headers):
        return self._request(
            "POST", f"/oss-products/{product_id}/unblock", payload, headers
        )

    # ------------------------------------------------------------------
    # Components (PRD §3.2)
    # ------------------------------------------------------------------
    def create_component(self, payload, headers):
        return self._request("POST", "/oss-components", payload, headers)

    def list_components(self, headers, params=None):
        return self._request("GET", "/oss-components", headers=headers, params=params)

    def get_component(self, component_id, headers):
        return self._request("GET", f"/oss-components/{component_id}", headers=headers)

    def override_classification(self, component_id, payload, headers):
        return self._request(
            "POST", f"/oss-components/{component_id}/override-classification",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Dependency scans (PRD §3.3)
    # ------------------------------------------------------------------
    def create_dependency_scan(self, product_id, payload, headers):
        return self._request(
            "POST", f"/oss-products/{product_id}/dependency-scans", payload, headers
        )

    def list_dependency_scans(self, product_id, headers, params=None):
        return self._request(
            "GET", f"/oss-products/{product_id}/dependency-scans",
            headers=headers, params=params,
        )

    def get_dependency_scan(self, product_id, scan_id, headers):
        return self._request(
            "GET", f"/oss-products/{product_id}/dependency-scans/{scan_id}",
            headers=headers,
        )

    def cancel_dependency_scan(self, product_id, scan_id, headers):
        return self._request(
            "POST", f"/oss-products/{product_id}/dependency-scans/{scan_id}/cancel",
            {}, headers,
        )

    # ------------------------------------------------------------------
    # Bills of materials and entries (PRD §3.3)
    # ------------------------------------------------------------------
    def list_boms(self, product_id, headers, params=None):
        return self._request(
            "GET", f"/oss-products/{product_id}/boms", headers=headers, params=params
        )

    def get_bom(self, product_id, bom_id, headers):
        return self._request(
            "GET", f"/oss-products/{product_id}/boms/{bom_id}", headers=headers
        )

    def list_bom_entries(self, product_id, bom_id, headers, params=None):
        return self._request(
            "GET", f"/oss-products/{product_id}/boms/{bom_id}/entries",
            headers=headers, params=params,
        )

    def get_bom_entry(self, product_id, bom_id, entry_id, headers):
        return self._request(
            "GET", f"/oss-products/{product_id}/boms/{bom_id}/entries/{entry_id}",
            headers=headers,
        )

    def generate_notice(self, product_id, bom_id, headers):
        return self._request(
            "POST", f"/oss-products/{product_id}/boms/{bom_id}/generate-notice",
            {}, headers,
        )

    def archive_bom(self, product_id, bom_id, headers):
        return self._request(
            "POST", f"/oss-products/{product_id}/boms/{bom_id}/archive", {}, headers
        )

    # ------------------------------------------------------------------
    # License approval requests (PRD §3.4)
    # ------------------------------------------------------------------
    def list_license_approvals(self, product_id, headers, params=None):
        return self._request(
            "GET", f"/oss-products/{product_id}/license-approvals",
            headers=headers, params=params,
        )

    def get_license_approval(self, product_id, request_id, headers):
        return self._request(
            "GET", f"/oss-products/{product_id}/license-approvals/{request_id}",
            headers=headers,
        )

    def assign_legal(self, product_id, request_id, headers):
        return self._request(
            "POST",
            f"/oss-products/{product_id}/license-approvals/{request_id}/assign-legal",
            {}, headers,
        )

    def legal_decision(self, product_id, request_id, payload, headers):
        return self._request(
            "POST",
            f"/oss-products/{product_id}/license-approvals/{request_id}/legal-decision",
            payload, headers,
        )

    def engineering_decision(self, product_id, request_id, payload, headers):
        return self._request(
            "POST",
            f"/oss-products/{product_id}/license-approvals/{request_id}/engineering-decision",
            payload, headers,
        )

    def withdraw_license_approval(self, product_id, request_id, headers):
        return self._request(
            "POST",
            f"/oss-products/{product_id}/license-approvals/{request_id}/withdraw",
            {}, headers,
        )

    # ------------------------------------------------------------------
    # Obligation tickets (PRD §3.4)
    # ------------------------------------------------------------------
    def list_obligation_tickets(self, product_id, headers, params=None):
        return self._request(
            "GET", f"/oss-products/{product_id}/obligation-tickets",
            headers=headers, params=params,
        )

    def get_obligation_ticket(self, product_id, ticket_id, headers):
        return self._request(
            "GET", f"/oss-products/{product_id}/obligation-tickets/{ticket_id}",
            headers=headers,
        )

    def start_ticket(self, product_id, ticket_id, headers):
        return self._request(
            "POST",
            f"/oss-products/{product_id}/obligation-tickets/{ticket_id}/start",
            {}, headers,
        )

    def fulfill_ticket(self, product_id, ticket_id, payload, headers):
        return self._request(
            "POST",
            f"/oss-products/{product_id}/obligation-tickets/{ticket_id}/fulfill",
            payload, headers,
        )

    def waive_ticket(self, product_id, ticket_id, payload, headers):
        return self._request(
            "POST",
            f"/oss-products/{product_id}/obligation-tickets/{ticket_id}/waive",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Vulnerabilities and findings (PRD §3.5)
    # ------------------------------------------------------------------
    def create_vulnerability(self, payload, headers):
        return self._request("POST", "/oss-vulnerabilities", payload, headers)

    def list_vulnerabilities(self, headers, params=None):
        return self._request(
            "GET", "/oss-vulnerabilities", headers=headers, params=params
        )

    def get_vulnerability(self, vulnerability_id, headers):
        return self._request(
            "GET", f"/oss-vulnerabilities/{vulnerability_id}", headers=headers
        )

    def list_vulnerability_findings(self, product_id, headers, params=None):
        return self._request(
            "GET", f"/oss-products/{product_id}/vulnerability-findings",
            headers=headers, params=params,
        )

    def get_vulnerability_finding(self, product_id, finding_id, headers):
        return self._request(
            "GET", f"/oss-products/{product_id}/vulnerability-findings/{finding_id}",
            headers=headers,
        )

    def confirm_finding(self, product_id, finding_id, headers):
        return self._request(
            "POST",
            f"/oss-products/{product_id}/vulnerability-findings/{finding_id}/confirm",
            {}, headers,
        )

    def mitigate_finding(self, product_id, finding_id, headers):
        return self._request(
            "POST",
            f"/oss-products/{product_id}/vulnerability-findings/{finding_id}/mitigate",
            {}, headers,
        )

    def verify_remediation(self, product_id, finding_id, payload, headers):
        return self._request(
            "POST",
            f"/oss-products/{product_id}/vulnerability-findings/{finding_id}/verify-remediation",
            payload, headers,
        )

    def mark_false_positive(self, product_id, finding_id, headers):
        return self._request(
            "POST",
            f"/oss-products/{product_id}/vulnerability-findings/{finding_id}/mark-false-positive",
            {}, headers,
        )

    def wont_fix_finding(self, product_id, finding_id, payload, headers):
        return self._request(
            "POST",
            f"/oss-products/{product_id}/vulnerability-findings/{finding_id}/wont-fix",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Release gates (PRD §3.7)
    # ------------------------------------------------------------------
    def create_release_gate(self, product_id, payload, headers):
        return self._request(
            "POST", f"/oss-products/{product_id}/release-gates", payload, headers
        )

    def list_release_gates(self, product_id, headers, params=None):
        return self._request(
            "GET", f"/oss-products/{product_id}/release-gates",
            headers=headers, params=params,
        )

    def get_release_gate(self, product_id, gate_id, headers):
        return self._request(
            "GET", f"/oss-products/{product_id}/release-gates/{gate_id}",
            headers=headers,
        )

    def evaluate_release_gate(self, product_id, gate_id, payload, headers):
        return self._request(
            "POST",
            f"/oss-products/{product_id}/release-gates/{gate_id}/evaluate",
            payload, headers,
        )

    def bypass_release_gate(self, product_id, gate_id, payload, headers):
        return self._request(
            "POST", f"/oss-products/{product_id}/release-gates/{gate_id}/bypass",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Remediation plans (PRD §3.6)
    # ------------------------------------------------------------------
    def create_remediation_plan(self, product_id, payload, headers):
        return self._request(
            "POST", f"/oss-products/{product_id}/remediation-plans", payload, headers
        )

    def list_remediation_plans(self, product_id, headers, params=None):
        return self._request(
            "GET", f"/oss-products/{product_id}/remediation-plans",
            headers=headers, params=params,
        )

    def get_remediation_plan(self, product_id, plan_id, headers):
        return self._request(
            "GET", f"/oss-products/{product_id}/remediation-plans/{plan_id}",
            headers=headers,
        )

    def approve_remediation_plan(self, product_id, plan_id, headers):
        return self._request(
            "POST",
            f"/oss-products/{product_id}/remediation-plans/{plan_id}/approve",
            {}, headers,
        )

    def start_remediation_plan(self, product_id, plan_id, headers):
        return self._request(
            "POST", f"/oss-products/{product_id}/remediation-plans/{plan_id}/start",
            {}, headers,
        )

    def complete_remediation_plan(self, product_id, plan_id, payload, headers):
        return self._request(
            "POST",
            f"/oss-products/{product_id}/remediation-plans/{plan_id}/complete",
            payload, headers,
        )

    def reject_remediation_plan(self, product_id, plan_id, headers):
        return self._request(
            "POST", f"/oss-products/{product_id}/remediation-plans/{plan_id}/reject",
            {}, headers,
        )

    def abandon_remediation_plan(self, product_id, plan_id, headers):
        return self._request(
            "POST",
            f"/oss-products/{product_id}/remediation-plans/{plan_id}/abandon",
            {}, headers,
        )

    # ------------------------------------------------------------------
    # Audit engagements (PRD §3.8)
    # ------------------------------------------------------------------
    def create_audit_engagement(self, product_id, payload, headers):
        return self._request(
            "POST", f"/oss-products/{product_id}/audit-engagements", payload, headers
        )

    def list_audit_engagements(self, product_id, headers, params=None):
        return self._request(
            "GET", f"/oss-products/{product_id}/audit-engagements",
            headers=headers, params=params,
        )

    def get_audit_engagement(self, product_id, engagement_id, headers):
        return self._request(
            "GET", f"/oss-products/{product_id}/audit-engagements/{engagement_id}",
            headers=headers,
        )

    def start_scoping(self, product_id, engagement_id, headers):
        return self._request(
            "POST",
            f"/oss-products/{product_id}/audit-engagements/{engagement_id}/start-scoping",
            {}, headers,
        )

    def start_data_collection(self, product_id, engagement_id, headers):
        return self._request(
            "POST",
            f"/oss-products/{product_id}/audit-engagements/{engagement_id}/start-data-collection",
            {}, headers,
        )

    def start_analysis(self, product_id, engagement_id, headers):
        return self._request(
            "POST",
            f"/oss-products/{product_id}/audit-engagements/{engagement_id}/start-analysis",
            {}, headers,
        )

    def draft_report(self, product_id, engagement_id, headers):
        return self._request(
            "POST",
            f"/oss-products/{product_id}/audit-engagements/{engagement_id}/draft-report",
            {}, headers,
        )

    def finalize_report(self, product_id, engagement_id, headers):
        return self._request(
            "POST",
            f"/oss-products/{product_id}/audit-engagements/{engagement_id}/finalize-report",
            {}, headers,
        )

    def cancel_engagement(self, product_id, engagement_id, headers):
        return self._request(
            "POST",
            f"/oss-products/{product_id}/audit-engagements/{engagement_id}/cancel",
            {}, headers,
        )

    # ------------------------------------------------------------------
    # Standalone detail endpoints (PRD §2.6 cross-reference retrieval)
    # ------------------------------------------------------------------
    def get_product_standalone(self, product_id, headers):
        return self._request(
            "GET", f"/oss-products/products/{product_id}", headers=headers
        )

    def get_component_standalone(self, component_id, headers):
        return self._request(
            "GET", f"/oss-products/components/{component_id}", headers=headers
        )

    def get_scan_standalone(self, scan_id, headers):
        return self._request(
            "GET", f"/oss-products/dependency-scans/{scan_id}", headers=headers
        )

    def get_bom_standalone(self, bom_id, headers):
        return self._request("GET", f"/oss-products/boms/{bom_id}", headers=headers)

    def get_bom_entry_standalone(self, entry_id, headers):
        return self._request(
            "GET", f"/oss-products/bom-entries/{entry_id}", headers=headers
        )

    def get_license_approval_standalone(self, request_id, headers):
        return self._request(
            "GET", f"/oss-products/license-approvals/{request_id}", headers=headers
        )

    def get_obligation_ticket_standalone(self, ticket_id, headers):
        return self._request(
            "GET", f"/oss-products/obligation-tickets/{ticket_id}", headers=headers
        )

    def get_finding_standalone(self, finding_id, headers):
        return self._request(
            "GET", f"/oss-products/vulnerability-findings/{finding_id}",
            headers=headers,
        )

    def get_gate_standalone(self, gate_id, headers):
        return self._request(
            "GET", f"/oss-products/release-gates/{gate_id}", headers=headers
        )

    def get_plan_standalone(self, plan_id, headers):
        return self._request(
            "GET", f"/oss-products/remediation-plans/{plan_id}", headers=headers
        )

    def get_engagement_standalone(self, engagement_id, headers):
        return self._request(
            "GET", f"/oss-products/audit-engagements/{engagement_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Flat filtered collection listings (PRD §2.6)
    # ------------------------------------------------------------------
    def list_scans_flat(self, headers, params=None):
        return self._request(
            "GET", "/oss-products/dependency-scans", headers=headers, params=params
        )

    def list_boms_flat(self, headers, params=None):
        return self._request(
            "GET", "/oss-products/boms", headers=headers, params=params
        )

    def list_bom_entries_flat(self, headers, params=None):
        return self._request(
            "GET", "/oss-products/bom-entries", headers=headers, params=params
        )

    def list_license_approvals_flat(self, headers, params=None):
        return self._request(
            "GET", "/oss-products/license-approvals", headers=headers, params=params
        )

    def list_obligation_tickets_flat(self, headers, params=None):
        return self._request(
            "GET", "/oss-products/obligation-tickets", headers=headers, params=params
        )

    def list_vulnerability_findings_flat(self, headers, params=None):
        return self._request(
            "GET", "/oss-products/vulnerability-findings", headers=headers,
            params=params,
        )

    def list_release_gates_flat(self, headers, params=None):
        return self._request(
            "GET", "/oss-products/release-gates", headers=headers, params=params
        )

    def list_remediation_plans_flat(self, headers, params=None):
        return self._request(
            "GET", "/oss-products/remediation-plans", headers=headers, params=params
        )

    def list_audit_engagements_flat(self, headers, params=None):
        return self._request(
            "GET", "/oss-products/audit-engagements", headers=headers, params=params
        )


api_client = ApiClient()
