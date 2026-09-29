"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------
    def create_project(self, payload, headers):
        return self._request("POST", "/uro/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/uro/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/uro/projects/{project_id}", headers=headers)

    def update_project(self, project_id, payload, headers):
        return self._request("PATCH", f"/uro/projects/{project_id}", payload, headers)

    def close_project(self, project_id, payload, headers):
        return self._request("POST", f"/uro/projects/{project_id}/close", payload, headers)

    def get_clearance_summary(self, project_id, headers):
        return self._request(
            "GET", f"/uro/projects/{project_id}/clearance-summary", headers=headers
        )

    def list_project_joint_trench_slots(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/uro/projects/{project_id}/joint-trench-slots",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Utility owners
    # ------------------------------------------------------------------
    def create_utility_owner(self, payload, headers):
        return self._request("POST", "/uro/utility-owners", payload, headers)

    def list_utility_owners(self, headers, params=None):
        return self._request("GET", "/uro/utility-owners", headers=headers, params=params)

    def get_utility_owner(self, owner_id, headers):
        return self._request("GET", f"/uro/utility-owners/{owner_id}", headers=headers)

    def release_hold(self, owner_id, payload, headers):
        return self._request(
            "POST", f"/uro/utility-owners/{owner_id}/release-hold", payload, headers
        )

    def list_owner_facilities(self, owner_id, headers, params=None):
        return self._request(
            "GET", f"/uro/utility-owners/{owner_id}/facilities", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Facilities and subsurface investigations
    # ------------------------------------------------------------------
    def create_facility(self, payload, headers):
        return self._request("POST", "/uro/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/uro/facilities/{facility_id}", headers=headers)

    def create_investigation(self, payload, headers):
        return self._request("POST", "/uro/investigations", payload, headers)

    def list_investigations(self, headers, params=None):
        return self._request("GET", "/uro/investigations", headers=headers, params=params)

    def get_investigation(self, investigation_id, headers):
        return self._request(
            "GET", f"/uro/investigations/{investigation_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Conflicts
    # ------------------------------------------------------------------
    def create_conflict(self, payload, headers):
        return self._request("POST", "/uro/conflicts", payload, headers)

    def list_conflicts(self, headers, params=None):
        return self._request("GET", "/uro/conflicts", headers=headers, params=params)

    def get_conflict(self, conflict_id, headers):
        return self._request("GET", f"/uro/conflicts/{conflict_id}", headers=headers)

    def set_conflict_resolution(self, conflict_id, payload, headers):
        return self._request(
            "POST", f"/uro/conflicts/{conflict_id}/set-resolution", payload, headers
        )

    def certify_conflict_cleared(self, conflict_id, payload, headers):
        return self._request(
            "POST", f"/uro/conflicts/{conflict_id}/certify-cleared", payload, headers
        )

    def list_conflict_prior_rights(self, conflict_id, headers, params=None):
        return self._request(
            "GET", f"/uro/conflicts/{conflict_id}/prior-rights", headers=headers, params=params
        )

    def list_conflict_relocation_plans(self, conflict_id, headers, params=None):
        return self._request(
            "GET",
            f"/uro/conflicts/{conflict_id}/relocation-plans",
            headers=headers,
            params=params,
        )

    def list_conflict_permits(self, conflict_id, headers, params=None):
        return self._request(
            "GET", f"/uro/conflicts/{conflict_id}/permits", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Prior rights determinations
    # ------------------------------------------------------------------
    def create_prior_rights(self, payload, headers):
        return self._request("POST", "/uro/prior-rights", payload, headers)

    def get_prior_rights(self, determination_id, headers):
        return self._request("GET", f"/uro/prior-rights/{determination_id}", headers=headers)

    def submit_prior_rights_for_review(self, determination_id, headers, payload=None):
        return self._request(
            "POST",
            f"/uro/prior-rights/{determination_id}/submit-for-review",
            payload or {},
            headers,
        )

    def return_prior_rights_for_revision(self, determination_id, payload, headers):
        return self._request(
            "POST",
            f"/uro/prior-rights/{determination_id}/return-for-revision",
            payload,
            headers,
        )

    def revise_prior_rights(self, determination_id, payload, headers):
        return self._request(
            "POST", f"/uro/prior-rights/{determination_id}/revise", payload, headers
        )

    def issue_prior_rights(self, determination_id, headers, payload=None):
        return self._request(
            "POST", f"/uro/prior-rights/{determination_id}/issue", payload or {}, headers
        )

    def appeal_prior_rights(self, determination_id, payload, headers):
        return self._request(
            "POST", f"/uro/prior-rights/{determination_id}/appeal", payload, headers
        )

    # ------------------------------------------------------------------
    # Permit records
    # ------------------------------------------------------------------
    def create_permit(self, payload, headers):
        return self._request("POST", "/uro/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/uro/permits/{permit_id}", headers=headers)

    def decide_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/uro/permits/{permit_id}/decide", payload, headers)

    # ------------------------------------------------------------------
    # Joint trench slots
    # ------------------------------------------------------------------
    def create_joint_trench_slot(self, payload, headers):
        return self._request("POST", "/uro/joint-trench-slots", payload, headers)

    def get_joint_trench_slot(self, slot_id, headers):
        return self._request("GET", f"/uro/joint-trench-slots/{slot_id}", headers=headers)

    # ------------------------------------------------------------------
    # Relocation plans
    # ------------------------------------------------------------------
    def create_relocation_plan(self, payload, headers):
        return self._request("POST", "/uro/relocation-plans", payload, headers)

    def get_relocation_plan(self, plan_id, headers):
        return self._request("GET", f"/uro/relocation-plans/{plan_id}", headers=headers)

    def start_plan_review(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"/uro/relocation-plans/{plan_id}/start-review", payload or {}, headers
        )

    def request_plan_revision(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/uro/relocation-plans/{plan_id}/request-revision", payload, headers
        )

    def resubmit_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/uro/relocation-plans/{plan_id}/resubmit", payload, headers
        )

    def approve_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"/uro/relocation-plans/{plan_id}/approve", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Schedule commitments
    # ------------------------------------------------------------------
    def create_commitment(self, payload, headers):
        return self._request("POST", "/uro/commitments", payload, headers)

    def list_commitments(self, headers, params=None):
        return self._request("GET", "/uro/commitments", headers=headers, params=params)

    def get_commitment(self, commitment_id, headers):
        return self._request("GET", f"/uro/commitments/{commitment_id}", headers=headers)

    def start_commitment_work(self, commitment_id, headers, payload=None):
        return self._request(
            "POST", f"/uro/commitments/{commitment_id}/start-work", payload or {}, headers
        )

    def report_commitment_complete(self, commitment_id, payload, headers):
        return self._request(
            "POST", f"/uro/commitments/{commitment_id}/report-complete", payload, headers
        )

    def cancel_commitment(self, commitment_id, payload, headers):
        return self._request(
            "POST", f"/uro/commitments/{commitment_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Reimbursement agreements
    # ------------------------------------------------------------------
    def create_agreement(self, payload, headers):
        return self._request("POST", "/uro/agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/uro/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/uro/agreements/{agreement_id}", headers=headers)

    def circulate_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/uro/agreements/{agreement_id}/circulate", payload or {}, headers
        )

    def execute_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/uro/agreements/{agreement_id}/execute", payload or {}, headers
        )

    def void_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/uro/agreements/{agreement_id}/void", payload, headers
        )

    def open_final_billing(self, agreement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/uro/agreements/{agreement_id}/open-final-billing",
            payload or {},
            headers,
        )

    def final_settlement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/uro/agreements/{agreement_id}/final-settlement", payload, headers
        )

    def get_settlement_preview(self, agreement_id, headers):
        return self._request(
            "GET", f"/uro/agreements/{agreement_id}/settlement-preview", headers=headers
        )

    def list_agreement_cost_documents(self, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"/uro/agreements/{agreement_id}/cost-documents",
            headers=headers,
            params=params,
        )

    def list_agreement_audit_findings(self, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"/uro/agreements/{agreement_id}/audit-findings",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Cost documents
    # ------------------------------------------------------------------
    def create_cost_document(self, payload, headers):
        return self._request("POST", "/uro/cost-documents", payload, headers)

    def get_cost_document(self, document_id, headers):
        return self._request("GET", f"/uro/cost-documents/{document_id}", headers=headers)

    def review_cost_document(self, document_id, payload, headers):
        return self._request(
            "POST", f"/uro/cost-documents/{document_id}/review", payload, headers
        )

    # ------------------------------------------------------------------
    # Audit findings
    # ------------------------------------------------------------------
    def create_audit_finding(self, payload, headers):
        return self._request("POST", "/uro/audit-findings", payload, headers)

    def get_audit_finding(self, finding_id, headers):
        return self._request("GET", f"/uro/audit-findings/{finding_id}", headers=headers)

    def resolve_audit_finding(self, finding_id, payload, headers):
        return self._request(
            "POST", f"/uro/audit-findings/{finding_id}/resolve", payload, headers
        )

    # ------------------------------------------------------------------
    # Delay claims
    # ------------------------------------------------------------------
    def create_delay_claim(self, payload, headers):
        return self._request("POST", "/uro/delay-claims", payload, headers)

    def list_delay_claims(self, headers, params=None):
        return self._request("GET", "/uro/delay-claims", headers=headers, params=params)

    def get_delay_claim(self, claim_id, headers):
        return self._request("GET", f"/uro/delay-claims/{claim_id}", headers=headers)

    def analyze_delay_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/uro/delay-claims/{claim_id}/analyze", payload, headers
        )

    def allocate_delay_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/uro/delay-claims/{claim_id}/allocate", payload or {}, headers
        )

    def withdraw_delay_allocation(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/uro/delay-claims/{claim_id}/withdraw-allocation", payload, headers
        )

    def deny_delay_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/uro/delay-claims/{claim_id}/deny", payload, headers)

    # ------------------------------------------------------------------
    # Administrative logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
