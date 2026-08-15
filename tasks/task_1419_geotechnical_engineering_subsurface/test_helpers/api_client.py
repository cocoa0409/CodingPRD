"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Client ---
    def create_client(self, payload, headers):
        return self._request("POST", "/geo/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/geo/clients/{client_id}", headers=headers)

    # --- Project ---
    def create_project(self, payload, headers):
        return self._request("POST", "/geo/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/geo/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/geo/projects", headers=headers, params=params)

    def transition_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/geo/projects/{project_id}/transition", payload, headers)

    # --- BoringPlan ---
    def create_boring_plan(self, project_id, payload, headers):
        return self._request(
            "POST", f"/geo/projects/{project_id}/boring-plans", payload, headers)

    def get_boring_plan(self, plan_id, headers):
        return self._request("GET", f"/geo/boring-plans/{plan_id}", headers=headers)

    def list_boring_plans(self, headers, params=None):
        return self._request("GET", "/geo/boring-plans", headers=headers,
                             params=params)

    def transition_boring_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/geo/boring-plans/{plan_id}/transition", payload, headers)

    # --- Subcontractor ---
    def create_subcontractor(self, payload, headers):
        return self._request("POST", "/geo/subcontractors", payload, headers)

    def get_subcontractor(self, subcontractor_id, headers):
        return self._request(
            "GET", f"/geo/subcontractors/{subcontractor_id}", headers=headers)

    def transition_subcontractor(self, subcontractor_id, payload, headers):
        return self._request(
            "POST", f"/geo/subcontractors/{subcontractor_id}/transition",
            payload, headers)

    # --- RigAssignment ---
    def create_rig_assignment(self, boring_id, payload, headers):
        return self._request(
            "POST", f"/geo/borings/{boring_id}/rig-assignments", payload, headers)

    def get_rig_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/geo/rig-assignments/{assignment_id}", headers=headers)

    def list_rig_assignments(self, headers, params=None):
        return self._request("GET", "/geo/rig-assignments", headers=headers,
                             params=params)

    def transition_rig_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/geo/rig-assignments/{assignment_id}/transition",
            payload, headers)

    # --- Boring ---
    def create_boring(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/geo/boring-plans/{plan_id}/borings", payload, headers)

    def get_boring(self, boring_id, headers):
        return self._request("GET", f"/geo/borings/{boring_id}", headers=headers)

    def list_borings(self, headers, params=None):
        return self._request("GET", "/geo/borings", headers=headers, params=params)

    def transition_boring(self, boring_id, payload, headers):
        return self._request(
            "POST", f"/geo/borings/{boring_id}/transition", payload, headers)

    def create_offset_boring(self, boring_id, payload, headers):
        return self._request(
            "POST", f"/geo/borings/{boring_id}/offsets", payload, headers)

    # --- UtilityClearance ---
    def create_clearance(self, boring_id, payload, headers):
        return self._request(
            "POST", f"/geo/borings/{boring_id}/clearances", payload, headers)

    def get_clearance(self, clearance_id, headers):
        return self._request("GET", f"/geo/clearances/{clearance_id}",
                             headers=headers)

    def list_clearances(self, headers, params=None):
        return self._request("GET", "/geo/clearances", headers=headers,
                             params=params)

    def transition_clearance(self, clearance_id, payload, headers):
        return self._request(
            "POST", f"/geo/clearances/{clearance_id}/transition", payload, headers)

    # --- Sample ---
    def create_sample(self, boring_id, payload, headers):
        return self._request(
            "POST", f"/geo/borings/{boring_id}/samples", payload, headers)

    def get_sample(self, sample_id, headers):
        return self._request("GET", f"/geo/samples/{sample_id}", headers=headers)

    def list_samples(self, headers, params=None):
        return self._request("GET", "/geo/samples", headers=headers, params=params)

    def transition_sample(self, sample_id, payload, headers):
        return self._request(
            "POST", f"/geo/samples/{sample_id}/transition", payload, headers)

    # --- LabTestOrder / LabTestResult ---
    def create_lab_test_order(self, project_id, payload, headers):
        return self._request(
            "POST", f"/geo/projects/{project_id}/lab-test-orders", payload, headers)

    def get_lab_test_order(self, order_id, headers):
        return self._request("GET", f"/geo/lab-test-orders/{order_id}",
                             headers=headers)

    def list_lab_test_orders(self, headers, params=None):
        return self._request("GET", "/geo/lab-test-orders", headers=headers,
                             params=params)

    def transition_lab_test_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/geo/lab-test-orders/{order_id}/transition", payload, headers)

    def submit_lab_result(self, order_id, payload, headers):
        return self._request(
            "POST", f"/geo/lab-test-orders/{order_id}/results", payload, headers)

    def get_lab_test_result(self, result_id, headers):
        return self._request("GET", f"/geo/lab-test-results/{result_id}",
                             headers=headers)

    def list_lab_test_results(self, headers, params=None):
        return self._request("GET", "/geo/lab-test-results", headers=headers,
                             params=params)

    # --- FoundationAnalysis ---
    def create_foundation_analysis(self, project_id, payload, headers):
        return self._request(
            "POST", f"/geo/projects/{project_id}/foundation-analyses",
            payload, headers)

    def get_foundation_analysis(self, analysis_id, headers):
        return self._request(
            "GET", f"/geo/foundation-analyses/{analysis_id}", headers=headers)

    def list_foundation_analyses(self, headers, params=None):
        return self._request(
            "GET", "/geo/foundation-analyses", headers=headers, params=params)

    def transition_foundation_analysis(self, analysis_id, payload, headers):
        return self._request(
            "POST", f"/geo/foundation-analyses/{analysis_id}/transition",
            payload, headers)

    # --- Report ---
    def create_report(self, project_id, payload, headers):
        return self._request(
            "POST", f"/geo/projects/{project_id}/reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/geo/reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/geo/reports", headers=headers, params=params)

    def transition_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/geo/reports/{report_id}/transition", payload, headers)

    def issue_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/geo/reports/{report_id}/issue", payload, headers)

    # --- ObservationVisit ---
    def create_observation_visit(self, project_id, payload, headers):
        return self._request(
            "POST", f"/geo/projects/{project_id}/observation-visits",
            payload, headers)

    def get_observation_visit(self, visit_id, headers):
        return self._request(
            "GET", f"/geo/observation-visits/{visit_id}", headers=headers)

    def list_observation_visits(self, headers, params=None):
        return self._request(
            "GET", "/geo/observation-visits", headers=headers, params=params)

    def transition_observation_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/geo/observation-visits/{visit_id}/transition",
            payload, headers)

    # --- ChangedConditionClaim ---
    def create_claim(self, project_id, payload, headers):
        return self._request(
            "POST", f"/geo/projects/{project_id}/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/geo/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/geo/claims", headers=headers, params=params)

    def transition_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/geo/claims/{claim_id}/transition", payload, headers)

    # --- ExplorationAuthorization ---
    def create_exploration_authorization(self, project_id, payload, headers):
        return self._request(
            "POST", f"/geo/projects/{project_id}/exploration-authorizations",
            payload, headers)

    def get_exploration_authorization(self, authorization_id, headers):
        return self._request(
            "GET", f"/geo/exploration-authorizations/{authorization_id}",
            headers=headers)

    def list_exploration_authorizations(self, headers, params=None):
        return self._request(
            "GET", "/geo/exploration-authorizations", headers=headers,
            params=params)

    def transition_exploration_authorization(self, authorization_id, payload,
                                             headers):
        return self._request(
            "POST",
            f"/geo/exploration-authorizations/{authorization_id}/transition",
            payload, headers)

    # --- Logical clock (test-driving capability) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/geo/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
