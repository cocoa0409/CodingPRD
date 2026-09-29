"""Typed HTTP client: one method per endpoint declared by the PRD."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class QualityControlApiClient(GenericApiClient):
    """One method per PRD endpoint, returning the raw response."""

    # -- helpers ----------------------------------------------------------
    def _list(self, path, headers, params):
        return self._request("GET", path, headers=headers, params=params)

    # -- clock ------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Optional[Dict] = None):
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            payload={"current_utc": current_utc},
            headers=headers,
        )

    # -- firms ------------------------------------------------------------
    def create_firm(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/firms", payload=payload, headers=headers)

    def list_firms(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._list("/firms", headers, params)

    def get_firm(self, firm_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/firms/{firm_id}", headers=headers)

    def update_firm(self, firm_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "PATCH", f"/firms/{firm_id}", payload=payload, headers=headers
        )

    def get_quality_management_summary(
        self, firm_id: str, headers: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/firms/{firm_id}/quality-management-summary", headers=headers
        )

    # -- partners ---------------------------------------------------------
    def create_partner(
        self, firm_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/firms/{firm_id}/partners", payload=payload, headers=headers
        )

    def list_partners(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._list("/partners", headers, params)

    def get_partner(self, partner_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/partners/{partner_id}", headers=headers)

    def update_partner(
        self, partner_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "PATCH", f"/partners/{partner_id}", payload=payload, headers=headers
        )

    # -- engagements ------------------------------------------------------
    def create_engagement(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/engagements", payload=payload, headers=headers)

    def list_engagements(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._list("/engagements", headers, params)

    def get_engagement(self, engagement_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/engagements/{engagement_id}", headers=headers)

    def create_workflow_transition(
        self, engagement_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/workflow-transitions",
            payload=payload,
            headers=headers,
        )

    def create_file_transition(
        self, engagement_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/file-transitions",
            payload=payload,
            headers=headers,
        )

    def assign_quality_review(
        self, engagement_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/quality-reviews",
            payload=payload,
            headers=headers,
        )

    # -- engagement quality reviews ---------------------------------------
    def list_quality_reviews(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._list("/quality-reviews", headers, params)

    def get_quality_review(self, eqr_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/quality-reviews/{eqr_id}", headers=headers)

    def create_quality_review_transition(
        self, eqr_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/quality-reviews/{eqr_id}/transitions",
            payload=payload,
            headers=headers,
        )

    # -- quality risks ----------------------------------------------------
    def create_quality_risk(
        self, firm_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/firms/{firm_id}/quality-risks", payload=payload, headers=headers
        )

    def list_quality_risks(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._list("/quality-risks", headers, params)

    def get_quality_risk(self, risk_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/quality-risks/{risk_id}", headers=headers)

    def create_risk_response(
        self, risk_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/quality-risks/{risk_id}/responses",
            payload=payload,
            headers=headers,
        )

    def create_risk_evaluation(
        self, risk_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/quality-risks/{risk_id}/evaluations",
            payload=payload,
            headers=headers,
        )

    # -- risk responses ---------------------------------------------------
    def list_risk_responses(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._list("/risk-responses", headers, params)

    def get_risk_response(self, response_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/risk-responses/{response_id}", headers=headers)

    def create_effectiveness_test(
        self, response_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/risk-responses/{response_id}/effectiveness-tests",
            payload=payload,
            headers=headers,
        )

    # -- internal inspections ---------------------------------------------
    def create_internal_inspection(
        self, firm_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/firms/{firm_id}/internal-inspections",
            payload=payload,
            headers=headers,
        )

    def list_internal_inspections(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._list("/internal-inspections", headers, params)

    def get_internal_inspection(
        self, inspection_id: str, headers: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/internal-inspections/{inspection_id}", headers=headers
        )

    def run_inspection_selector(
        self, inspection_id: str, payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"/internal-inspections/{inspection_id}/selections",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def create_inspection_transition(
        self, inspection_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/internal-inspections/{inspection_id}/transitions",
            payload=payload,
            headers=headers,
        )

    # -- inspection selections --------------------------------------------
    def list_inspection_selections(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._list("/inspection-selections", headers, params)

    def get_inspection_selection(
        self, selection_id: str, headers: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/inspection-selections/{selection_id}", headers=headers
        )

    def create_inspection_finding(
        self, selection_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/inspection-selections/{selection_id}/findings",
            payload=payload,
            headers=headers,
        )

    # -- inspection findings ----------------------------------------------
    def list_inspection_findings(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._list("/inspection-findings", headers, params)

    def get_inspection_finding(self, finding_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"/inspection-findings/{finding_id}", headers=headers
        )

    def classify_finding(
        self, finding_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/inspection-findings/{finding_id}/classification",
            payload=payload,
            headers=headers,
        )

    def create_finding_transition(
        self, finding_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/inspection-findings/{finding_id}/transitions",
            payload=payload,
            headers=headers,
        )

    def create_root_cause_analysis(
        self, finding_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/inspection-findings/{finding_id}/root-cause-analyses",
            payload=payload,
            headers=headers,
        )

    def create_remediation_plan(
        self, finding_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/inspection-findings/{finding_id}/remediation-plans",
            payload=payload,
            headers=headers,
        )

    # -- root cause analyses ----------------------------------------------
    def list_root_cause_analyses(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._list("/root-cause-analyses", headers, params)

    def get_root_cause_analysis(self, rca_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/root-cause-analyses/{rca_id}", headers=headers)

    def create_rca_validation(
        self, rca_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/root-cause-analyses/{rca_id}/validation",
            payload=payload,
            headers=headers,
        )

    # -- remediation plans -------------------------------------------------
    def list_remediation_plans(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._list("/remediation-plans", headers, params)

    def get_remediation_plan(self, plan_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/remediation-plans/{plan_id}", headers=headers)

    def create_remediation_plan_transition(
        self, plan_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/remediation-plans/{plan_id}/transitions",
            payload=payload,
            headers=headers,
        )

    # -- peer reviewers ----------------------------------------------------
    def create_peer_reviewer(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", "/peer-reviewers", payload=payload, headers=headers
        )

    def list_peer_reviewers(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._list("/peer-reviewers", headers, params)

    def get_peer_reviewer(self, reviewer_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/peer-reviewers/{reviewer_id}", headers=headers)

    def update_peer_reviewer(
        self, reviewer_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "PATCH", f"/peer-reviewers/{reviewer_id}", payload=payload, headers=headers
        )

    # -- peer reviews ------------------------------------------------------
    def create_peer_review(
        self, firm_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/firms/{firm_id}/peer-reviews", payload=payload, headers=headers
        )

    def list_peer_reviews(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._list("/peer-reviews", headers, params)

    def get_peer_review(self, peer_review_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/peer-reviews/{peer_review_id}", headers=headers)

    def assign_peer_reviewer(
        self, peer_review_id: str, payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"/peer-reviews/{peer_review_id}/reviewer-assignment",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def set_peer_review_scope(
        self, peer_review_id: str, payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"/peer-reviews/{peer_review_id}/scope",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def create_peer_review_selection(
        self, peer_review_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/peer-reviews/{peer_review_id}/selections",
            payload=payload,
            headers=headers,
        )

    def delete_peer_review_selection(
        self, peer_review_id: str, selection_id: str, headers: Optional[Dict] = None
    ):
        return self._request(
            "DELETE",
            f"/peer-reviews/{peer_review_id}/selections/{selection_id}",
            headers=headers,
        )

    def create_peer_review_transition(
        self, peer_review_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/peer-reviews/{peer_review_id}/transitions",
            payload=payload,
            headers=headers,
        )

    # -- peer review selections -------------------------------------------
    def list_peer_review_selections(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._list("/peer-review-selections", headers, params)

    def get_peer_review_selection(
        self, selection_id: str, headers: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/peer-review-selections/{selection_id}", headers=headers
        )

    def create_selection_disposition(
        self, selection_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/peer-review-selections/{selection_id}/disposition",
            payload=payload,
            headers=headers,
        )

    # -- corrective action plans -------------------------------------------
    def list_corrective_action_plans(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._list("/corrective-action-plans", headers, params)

    def get_corrective_action_plan(self, cap_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"/corrective-action-plans/{cap_id}", headers=headers
        )

    def create_corrective_action_evidence(
        self, cap_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/corrective-action-plans/{cap_id}/evidence",
            payload=payload,
            headers=headers,
        )

    def create_corrective_action_disposition(
        self, cap_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/corrective-action-plans/{cap_id}/disposition",
            payload=payload,
            headers=headers,
        )
