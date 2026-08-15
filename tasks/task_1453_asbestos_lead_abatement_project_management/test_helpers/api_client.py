"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving capability) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Projects ---
    def create_project(self, payload, headers):
        return self._request("POST", "/abatement/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/abatement/projects/{project_id}",
                             headers=headers)

    def start_abatement(self, project_id, headers):
        return self._request("POST",
                             f"/abatement/projects/{project_id}/start-abatement",
                             headers=headers)

    def suspend_project(self, project_id, headers):
        return self._request("POST",
                             f"/abatement/projects/{project_id}/suspend",
                             headers=headers)

    def resume_project(self, project_id, headers):
        return self._request("POST",
                             f"/abatement/projects/{project_id}/resume",
                             headers=headers)

    def complete_work(self, project_id, headers):
        return self._request("POST",
                             f"/abatement/projects/{project_id}/complete-work",
                             headers=headers)

    def close_project(self, project_id, headers):
        return self._request("POST",
                             f"/abatement/projects/{project_id}/close",
                             headers=headers)

    # --- Surveys ---
    def create_survey(self, payload, headers):
        return self._request("POST", "/abatement/surveys", payload, headers)

    def get_survey(self, survey_id, headers):
        return self._request("GET", f"/abatement/surveys/{survey_id}",
                             headers=headers)

    def list_project_surveys(self, project_id, headers, params=None):
        return self._request("GET", f"/abatement/projects/{project_id}/surveys",
                             headers=headers, params=params)

    def submit_survey(self, survey_id, headers):
        return self._request("POST", f"/abatement/surveys/{survey_id}/submit",
                             headers=headers)

    def finalize_survey(self, survey_id, headers):
        return self._request("POST", f"/abatement/surveys/{survey_id}/finalize",
                             headers=headers)

    # --- Samples ---
    def create_sample(self, payload, headers):
        return self._request("POST", "/abatement/samples", payload, headers)

    def list_samples(self, survey_id, headers, params=None):
        return self._request("GET", f"/abatement/surveys/{survey_id}/samples",
                             headers=headers, params=params)

    def record_sample_result(self, sample_id, payload, headers):
        return self._request("POST", f"/abatement/samples/{sample_id}/result",
                             payload, headers)

    # --- Workers ---
    def create_worker(self, payload, headers):
        return self._request("POST", "/abatement/workers", payload, headers)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"/abatement/workers/{worker_id}",
                             headers=headers)

    def recertify_worker(self, worker_id, payload, headers):
        return self._request("POST",
                             f"/abatement/workers/{worker_id}/recertify",
                             payload, headers)

    # --- Crew assignments ---
    def create_assignment(self, payload, headers):
        return self._request("POST", "/abatement/assignments", payload, headers)

    def list_project_assignments(self, project_id, headers, params=None):
        return self._request("GET",
                             f"/abatement/projects/{project_id}/assignments",
                             headers=headers, params=params)

    def list_worker_assignments(self, worker_id, headers, params=None):
        return self._request("GET",
                             f"/abatement/workers/{worker_id}/assignments",
                             headers=headers, params=params)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST",
                             f"/abatement/assignments/{assignment_id}/cancel",
                             headers=headers)

    # --- Regulatory notifications ---
    def create_notification(self, payload, headers):
        return self._request("POST", "/abatement/notifications", payload, headers)

    def list_project_notifications(self, project_id, headers, params=None):
        return self._request("GET",
                             f"/abatement/projects/{project_id}/notifications",
                             headers=headers, params=params)

    def acknowledge_notification(self, notification_id, headers):
        return self._request(
            "POST",
            f"/abatement/notifications/{notification_id}/acknowledge",
            headers=headers)

    # --- Containments ---
    def create_containment(self, payload, headers):
        return self._request("POST", "/abatement/containments", payload, headers)

    def list_project_containments(self, project_id, headers, params=None):
        return self._request("GET",
                             f"/abatement/projects/{project_id}/containments",
                             headers=headers, params=params)

    def install_containment(self, containment_id, headers):
        return self._request(
            "POST", f"/abatement/containments/{containment_id}/install",
            headers=headers)

    def verify_containment(self, containment_id, payload, headers):
        return self._request(
            "POST", f"/abatement/containments/{containment_id}/verify",
            payload, headers)

    def revise_containment(self, containment_id, payload, headers):
        return self._request(
            "POST", f"/abatement/containments/{containment_id}/revise",
            payload, headers)

    # --- Air tests ---
    def create_air_test(self, payload, headers):
        return self._request("POST", "/abatement/air-tests", payload, headers)

    def list_project_air_tests(self, project_id, headers, params=None):
        return self._request("GET",
                             f"/abatement/projects/{project_id}/air-tests",
                             headers=headers, params=params)

    def record_air_test_result(self, air_test_id, payload, headers):
        return self._request("POST",
                             f"/abatement/air-tests/{air_test_id}/result",
                             payload, headers)

    # --- Waste manifests ---
    def create_manifest(self, payload, headers):
        return self._request("POST", "/abatement/manifests", payload, headers)

    def list_project_manifests(self, project_id, headers, params=None):
        return self._request("GET",
                             f"/abatement/projects/{project_id}/manifests",
                             headers=headers, params=params)

    def list_facility_manifests(self, facility_id, headers, params=None):
        return self._request("GET",
                             f"/abatement/facilities/{facility_id}/manifests",
                             headers=headers, params=params)

    def seal_manifest(self, manifest_id, headers):
        return self._request("POST", f"/abatement/manifests/{manifest_id}/seal",
                             headers=headers)

    def ship_manifest(self, manifest_id, headers):
        return self._request("POST", f"/abatement/manifests/{manifest_id}/ship",
                             headers=headers)

    def deliver_manifest(self, manifest_id, headers):
        return self._request("POST",
                             f"/abatement/manifests/{manifest_id}/deliver",
                             headers=headers)

    def confirm_manifest(self, manifest_id, headers):
        return self._request("POST",
                             f"/abatement/manifests/{manifest_id}/confirm",
                             headers=headers)

    def reject_manifest(self, manifest_id, payload, headers):
        return self._request("POST",
                             f"/abatement/manifests/{manifest_id}/reject",
                             payload, headers)

    def void_manifest(self, manifest_id, headers):
        return self._request("POST", f"/abatement/manifests/{manifest_id}/void",
                             headers=headers)

    # --- Disposal facilities ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/abatement/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/abatement/facilities/{facility_id}",
                             headers=headers)

    def suspend_facility(self, facility_id, headers):
        return self._request("POST",
                             f"/abatement/facilities/{facility_id}/suspend",
                             headers=headers)

    # --- Relocation units ---
    def create_relocation_unit(self, payload, headers):
        return self._request("POST", "/abatement/relocation-units", payload,
                             headers)

    def get_relocation_unit(self, unit_id, headers):
        return self._request("GET", f"/abatement/relocation-units/{unit_id}",
                             headers=headers)

    # --- Relocation records ---
    def create_relocation(self, payload, headers):
        return self._request("POST", "/abatement/relocations", payload, headers)

    def list_project_relocations(self, project_id, headers, params=None):
        return self._request("GET",
                             f"/abatement/projects/{project_id}/relocations",
                             headers=headers, params=params)

    def list_unit_relocations(self, unit_id, headers, params=None):
        return self._request("GET",
                             f"/abatement/relocation-units/{unit_id}/relocations",
                             headers=headers, params=params)

    def return_relocation(self, relocation_id, headers):
        return self._request("POST",
                             f"/abatement/relocations/{relocation_id}/return",
                             headers=headers)


api_client = ApiClient()
