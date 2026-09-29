"""API client: one method per endpoint defined in the PRD."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/plan"


class ApiClient(GenericApiClient):
    """Typed wrapper over every endpoint of the Assigned Risk Automobile Plan API."""

    # ------------------------------------------------------------------
    # Carriers
    # ------------------------------------------------------------------
    def create_carrier(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/carriers", payload, headers)

    def list_carriers(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/carriers", headers=headers, params=params)

    def get_carrier(self, carrier_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/carriers/{carrier_id}", headers=headers)

    def file_carrier_exit_notice(self, carrier_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/carriers/{carrier_id}/exit-notice", payload, headers)

    def file_carrier_licensing_amendment(self, carrier_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/carriers/{carrier_id}/licensing-amendment", payload, headers)

    # ------------------------------------------------------------------
    # Producers
    # ------------------------------------------------------------------
    def create_producer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/producers", payload, headers)

    def get_producer(self, producer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/producers/{producer_id}", headers=headers)

    # ------------------------------------------------------------------
    # Applicants and vehicles
    # ------------------------------------------------------------------
    def create_applicant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/applicants", payload, headers)

    def get_applicant(self, applicant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/applicants/{applicant_id}", headers=headers)

    def create_vehicle(self, applicant_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/applicants/{applicant_id}/vehicles", payload, headers)

    def list_vehicles(self, applicant_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/applicants/{applicant_id}/vehicles", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Applications
    # ------------------------------------------------------------------
    def create_application(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/applications", payload, headers)

    def list_applications(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/applications", headers=headers, params=params)

    def get_application(self, application_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/applications/{application_id}", headers=headers)

    def create_market_rejection(self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/applications/{application_id}/market-rejections", payload, headers)

    def list_market_rejections(self, application_id: str, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/applications/{application_id}/market-rejections",
                             headers=headers, params=params)

    def record_deposit(self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/applications/{application_id}/deposit", payload, headers)

    def record_mvr_verification(self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/applications/{application_id}/mvr-verification", payload, headers)

    def decide_certification(self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/applications/{application_id}/certification", payload, headers)

    def return_application_for_cure(self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/applications/{application_id}/cure-return", payload, headers)

    def resubmit_application(self, application_id: str, payload: Optional[Dict[str, Any]],
                             headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/applications/{application_id}/resubmission", payload, headers)

    # ------------------------------------------------------------------
    # Plan periods and assignment cycles
    # ------------------------------------------------------------------
    def create_plan_period(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/plan-periods", payload, headers)

    def get_plan_period(self, plan_period_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/plan-periods/{plan_period_id}", headers=headers)

    def close_plan_period(self, plan_period_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/plan-periods/{plan_period_id}/closure", headers=headers)

    def create_assignment_cycle(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/assignment-cycles", payload, headers)

    def list_assignment_cycles(self, plan_period_id: str, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/plan-periods/{plan_period_id}/assignment-cycles",
                             headers=headers, params=params)

    def get_assignment_cycle(self, cycle_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/assignment-cycles/{cycle_id}", headers=headers)

    def run_assignment_cycle(self, cycle_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/assignment-cycles/{cycle_id}/run", headers=headers)

    # ------------------------------------------------------------------
    # Assignments
    # ------------------------------------------------------------------
    def list_assignments(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/assignments/{assignment_id}", headers=headers)

    def accept_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/assignments/{assignment_id}/acceptance", headers=headers)

    def rescind_assignment(self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/assignments/{assignment_id}/rescission", payload, headers)

    # ------------------------------------------------------------------
    # Policies
    # ------------------------------------------------------------------
    def create_policy(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/policies", payload, headers)

    def list_policies(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/policies", headers=headers, params=params)

    def get_policy(self, policy_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/policies/{policy_id}", headers=headers)

    def reclassify_policy(self, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/policies/{policy_id}/reclassification", payload, headers)

    def cancel_policy(self, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/policies/{policy_id}/cancellation", payload, headers)

    def serve_non_renewal_notice(self, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/policies/{policy_id}/non-renewal-notice", payload, headers)

    def exit_policy_to_voluntary(self, policy_id: str, payload: Optional[Dict[str, Any]],
                                 headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/policies/{policy_id}/voluntary-exit", payload, headers)

    # ------------------------------------------------------------------
    # Claims
    # ------------------------------------------------------------------
    def create_claim(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/claims", payload, headers)

    def list_claims(self, policy_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/policies/{policy_id}/claims", headers=headers, params=params)

    def get_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}", headers=headers)

    def acknowledge_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/acknowledgement", headers=headers)

    def close_claim(self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/closure", payload, headers)

    # ------------------------------------------------------------------
    # Complaints
    # ------------------------------------------------------------------
    def create_complaint(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/complaints", payload, headers)

    def list_complaints(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/complaints/{complaint_id}", headers=headers)

    def record_complaint_findings(self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/complaints/{complaint_id}/findings", payload, headers)

    def resolve_complaint(self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/complaints/{complaint_id}/resolution", payload, headers)

    # ------------------------------------------------------------------
    # Quota reconciliations
    # ------------------------------------------------------------------
    def create_quota_reconciliation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/quota-reconciliations", payload, headers)

    def list_quota_reconciliations(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/quota-reconciliations", headers=headers, params=params)

    def get_quota_reconciliation(self, reconciliation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/quota-reconciliations/{reconciliation_id}", headers=headers)

    # ------------------------------------------------------------------
    # Logical plan clock
    # ------------------------------------------------------------------
    def set_current_utc(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
