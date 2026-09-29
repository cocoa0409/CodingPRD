"""API client: one method per endpoint defined in the PRD."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Long-Term Disaster Recovery Group API."""

    # ------------------------------------------------------------- survivors
    def create_survivor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/survivors", payload, headers)

    def get_survivor(self, survivor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/survivors/{survivor_id}", headers=headers)

    # -------------------------------------------------------- recovery cases
    def create_recovery_case(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/recovery-cases", payload, headers)

    def get_recovery_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/recovery-cases/{case_id}", headers=headers)

    def list_recovery_cases(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/recovery-cases", headers=headers, params=params)

    # ----------------------------------------------------------- damage items
    def create_damage_item(self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/recovery-cases/{case_id}/damage-items", payload, headers)

    def list_damage_items(self, case_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/recovery-cases/{case_id}/damage-items", headers=headers, params=params
        )

    def verify_damage_item(self, damage_item_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/damage-items/{damage_item_id}/verification", payload, headers)

    # ------------------------------------------------------ assistance records
    def create_assistance_record(self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/recovery-cases/{case_id}/assistance-records", payload, headers
        )

    def list_assistance_records(self, case_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/recovery-cases/{case_id}/assistance-records", headers=headers, params=params
        )

    # ------------------------------------------------------------- assessments
    def create_assessment(self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/recovery-cases/{case_id}/assessments", payload, headers)

    def list_assessments(self, case_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/recovery-cases/{case_id}/assessments", headers=headers, params=params
        )

    # -------------------------------------------------------------- dob report
    def get_dob_report(self, case_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/recovery-cases/{case_id}/dob-report", headers=headers, params=params
        )

    # ------------------------------------------------------- closure lifecycle
    def closure_review_case(self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/recovery-cases/{case_id}/closure-review", payload, headers)

    def close_case(self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/recovery-cases/{case_id}/close", payload, headers)

    def reopen_case(self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/recovery-cases/{case_id}/reopen", payload, headers)

    # --------------------------------------------------------------- follow-ups
    def create_follow_up(self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/recovery-cases/{case_id}/follow-ups", payload, headers)

    def list_follow_ups(self, case_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/recovery-cases/{case_id}/follow-ups", headers=headers, params=params
        )

    # ------------------------------------------------------ member organizations
    def create_member_organization(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/member-organizations", payload, headers)

    def get_member_organization(self, member_org_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/member-organizations/{member_org_id}", headers=headers)

    def set_member_organization_status(
        self, member_org_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/member-organizations/{member_org_id}/status", payload, headers
        )

    # ------------------------------------------------------------ table sessions
    def create_table_session(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/table-sessions", payload, headers)

    def get_table_session(self, session_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/table-sessions/{session_id}", headers=headers)

    def open_table_session(self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/table-sessions/{session_id}/open", payload, headers)

    def adjourn_table_session(self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/table-sessions/{session_id}/adjourn", payload, headers)

    # ------------------------------------------------------- case presentations
    def create_case_presentation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/case-presentations", payload, headers)

    def get_case_presentation(self, presentation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/case-presentations/{presentation_id}", headers=headers)

    def list_case_presentations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/case-presentations", headers=headers, params=params)

    def present_case_presentation(
        self, presentation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/case-presentations/{presentation_id}/present", payload, headers
        )

    def deliberate_case_presentation(
        self, presentation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/case-presentations/{presentation_id}/deliberate", payload, headers
        )

    def decide_case_presentation(
        self, presentation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/case-presentations/{presentation_id}/decision", payload, headers
        )

    def requeue_case_presentation(
        self, presentation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/case-presentations/{presentation_id}/requeue", payload, headers
        )

    # ------------------------------------------------------ funding commitments
    def create_funding_commitment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/funding-commitments", payload, headers)

    def get_funding_commitment(self, commitment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/funding-commitments/{commitment_id}", headers=headers)

    def list_funding_commitments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/funding-commitments", headers=headers, params=params)

    def rescind_funding_commitment(
        self, commitment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/funding-commitments/{commitment_id}/rescind", payload, headers
        )

    # ---------------------------------------------------------- funding sources
    def create_funding_source(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/funding-sources", payload, headers)

    def get_funding_source(self, funding_source_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/funding-sources/{funding_source_id}", headers=headers)

    def list_funding_sources(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/funding-sources", headers=headers, params=params)

    # ------------------------------------------------------------ disbursements
    def create_disbursement(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/disbursements", payload, headers)

    def get_disbursement(self, disbursement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/disbursements/{disbursement_id}", headers=headers)

    def list_disbursements(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/disbursements", headers=headers, params=params)

    def resolve_disbursement_dob(
        self, disbursement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/disbursements/{disbursement_id}/dob-resolution", payload, headers
        )

    def approve_disbursement(self, disbursement_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/disbursements/{disbursement_id}/approve", payload, headers)

    def pay_disbursement(self, disbursement_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/disbursements/{disbursement_id}/pay", payload, headers)

    def reverse_disbursement(self, disbursement_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/disbursements/{disbursement_id}/reverse", payload, headers)

    def void_disbursement(self, disbursement_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/disbursements/{disbursement_id}/void", payload, headers)

    # ----------------------------------------------------- construction projects
    def create_construction_project(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/construction-projects", payload, headers)

    def get_construction_project(self, project_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/construction-projects/{project_id}", headers=headers)

    def list_construction_projects(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/construction-projects", headers=headers, params=params)

    def transition_construction_project(
        self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/construction-projects/{project_id}/transition", payload, headers
        )

    def get_skill_fit(self, project_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/construction-projects/{project_id}/skill-fit", headers=headers, params=params
        )

    # --------------------------------------------------------- volunteer groups
    def create_volunteer_group(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/volunteer-groups", payload, headers)

    def get_volunteer_group(self, group_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/volunteer-groups/{group_id}", headers=headers)

    # ---------------------------------------------------- volunteer deployments
    def create_volunteer_deployment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/volunteer-deployments", payload, headers)

    def get_volunteer_deployment(self, deployment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/volunteer-deployments/{deployment_id}", headers=headers)

    def list_volunteer_deployments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/volunteer-deployments", headers=headers, params=params)

    def transition_volunteer_deployment(
        self, deployment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/volunteer-deployments/{deployment_id}/transition", payload, headers
        )

    # ------------------------------------------------------------ lodging sites
    def create_lodging_site(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/lodging-sites", payload, headers)

    def get_lodging_site(self, lodging_site_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/lodging-sites/{lodging_site_id}", headers=headers)

    # ------------------------------------------------------ housing assignments
    def create_housing_assignment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/housing-assignments", payload, headers)

    def get_housing_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/housing-assignments/{assignment_id}", headers=headers)

    def list_housing_assignments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/housing-assignments", headers=headers, params=params)

    def release_housing_assignment(
        self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/housing-assignments/{assignment_id}/release", payload, headers
        )

    # ------------------------------------------------------------ logical clock
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
