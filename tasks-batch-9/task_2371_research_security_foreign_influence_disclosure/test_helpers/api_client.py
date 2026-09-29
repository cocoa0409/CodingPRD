"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ #
    # Investigators
    # ------------------------------------------------------------------ #
    def create_investigator(self, payload, headers):
        return self._request("POST", "/investigators", payload, headers)

    def get_investigator(self, investigator_id, headers):
        return self._request("GET", f"/investigators/{investigator_id}", headers=headers)

    def list_investigators(self, headers, params=None):
        return self._request("GET", "/investigators", headers=headers, params=params)

    # ------------------------------------------------------------------ #
    # Foreign organizations
    # ------------------------------------------------------------------ #
    def create_foreign_organization(self, payload, headers):
        return self._request("POST", "/foreign-organizations", payload, headers)

    def get_foreign_organization(self, organization_id, headers):
        return self._request(
            "GET", f"/foreign-organizations/{organization_id}", headers=headers
        )

    def list_foreign_organizations(self, headers, params=None):
        return self._request(
            "GET", "/foreign-organizations", headers=headers, params=params
        )

    def list_subsidiaries(self, organization_id, headers, params=None):
        return self._request(
            "GET",
            f"/foreign-organizations/{organization_id}/subsidiaries",
            headers=headers,
            params=params,
        )

    def designate_organization(self, organization_id, payload, headers):
        return self._request(
            "POST",
            f"/foreign-organizations/{organization_id}/designate",
            payload,
            headers,
        )

    def set_organization_ownership(self, organization_id, payload, headers):
        return self._request(
            "POST",
            f"/foreign-organizations/{organization_id}/ownership",
            payload,
            headers,
        )

    # ------------------------------------------------------------------ #
    # Projects
    # ------------------------------------------------------------------ #
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def set_award_status(self, project_id, payload, headers):
        return self._request(
            "POST", f"/projects/{project_id}/award-status", payload, headers
        )

    def set_security_status(self, project_id, payload, headers):
        return self._request(
            "POST", f"/projects/{project_id}/security-status", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Project personnel
    # ------------------------------------------------------------------ #
    def create_personnel(self, project_id, payload, headers):
        return self._request(
            "POST", f"/projects/{project_id}/personnel", payload, headers
        )

    def get_personnel(self, personnel_id, headers):
        return self._request(
            "GET", f"/project-personnel/{personnel_id}", headers=headers
        )

    def list_personnel(self, headers, params=None):
        return self._request(
            "GET", "/project-personnel", headers=headers, params=params
        )

    def set_personnel_status(self, personnel_id, payload, headers):
        return self._request(
            "POST", f"/project-personnel/{personnel_id}/status", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Disclosures
    # ------------------------------------------------------------------ #
    def create_disclosure(self, payload, headers):
        return self._request("POST", "/disclosures", payload, headers)

    def get_disclosure(self, disclosure_id, headers):
        return self._request("GET", f"/disclosures/{disclosure_id}", headers=headers)

    def list_disclosures(self, headers, params=None):
        return self._request("GET", "/disclosures", headers=headers, params=params)

    def submit_disclosure(self, disclosure_id, headers, payload=None):
        return self._request(
            "POST", f"/disclosures/{disclosure_id}/submit", payload or {}, headers
        )

    def review_disclosure(self, disclosure_id, payload, headers):
        return self._request(
            "POST", f"/disclosures/{disclosure_id}/review", payload, headers
        )

    def plan_disclosure(self, disclosure_id, payload, headers):
        return self._request(
            "POST", f"/disclosures/{disclosure_id}/plan", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Disclosure items
    # ------------------------------------------------------------------ #
    def create_disclosure_item(self, disclosure_id, payload, headers):
        return self._request(
            "POST", f"/disclosures/{disclosure_id}/items", payload, headers
        )

    def get_disclosure_item(self, item_id, headers):
        return self._request("GET", f"/disclosure-items/{item_id}", headers=headers)

    def list_disclosure_items(self, headers, params=None):
        return self._request("GET", "/disclosure-items", headers=headers, params=params)

    def set_disclosure_item_status(self, item_id, payload, headers):
        return self._request(
            "POST", f"/disclosure-items/{item_id}/status", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Support statements
    # ------------------------------------------------------------------ #
    def create_support_statement(self, payload, headers):
        return self._request("POST", "/support-statements", payload, headers)

    def get_support_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/support-statements/{statement_id}", headers=headers
        )

    def list_support_statements(self, headers, params=None):
        return self._request(
            "GET", "/support-statements", headers=headers, params=params
        )

    def reconcile_support_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/support-statements/{statement_id}/reconcile", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Travel registrations
    # ------------------------------------------------------------------ #
    def create_travel_registration(self, payload, headers):
        return self._request("POST", "/travel-registrations", payload, headers)

    def get_travel_registration(self, registration_id, headers):
        return self._request(
            "GET", f"/travel-registrations/{registration_id}", headers=headers
        )

    def list_travel_registrations(self, headers, params=None):
        return self._request(
            "GET", "/travel-registrations", headers=headers, params=params
        )

    def set_travel_status(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/travel-registrations/{registration_id}/status", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Controlled access grants
    # ------------------------------------------------------------------ #
    def create_access_grant(self, payload, headers):
        return self._request("POST", "/controlled-access-grants", payload, headers)

    def get_access_grant(self, grant_id, headers):
        return self._request(
            "GET", f"/controlled-access-grants/{grant_id}", headers=headers
        )

    def list_access_grants(self, headers, params=None):
        return self._request(
            "GET", "/controlled-access-grants", headers=headers, params=params
        )

    def set_access_grant_status(self, grant_id, payload, headers):
        return self._request(
            "POST", f"/controlled-access-grants/{grant_id}/status", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Security incidents
    # ------------------------------------------------------------------ #
    def create_security_incident(self, payload, headers):
        return self._request("POST", "/security-incidents", payload, headers)

    def get_security_incident(self, incident_id, headers):
        return self._request(
            "GET", f"/security-incidents/{incident_id}", headers=headers
        )

    def list_security_incidents(self, headers, params=None):
        return self._request(
            "GET", "/security-incidents", headers=headers, params=params
        )

    def set_incident_status(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/security-incidents/{incident_id}/status", payload, headers
        )

    def notify_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/security-incidents/{incident_id}/notify", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Training assignments
    # ------------------------------------------------------------------ #
    def create_training_assignment(self, payload, headers):
        return self._request("POST", "/training-assignments", payload, headers)

    def get_training_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/training-assignments/{assignment_id}", headers=headers
        )

    def list_training_assignments(self, headers, params=None):
        return self._request(
            "GET", "/training-assignments", headers=headers, params=params
        )

    def complete_training_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/training-assignments/{assignment_id}/complete",
            payload or {},
            headers,
        )

    def waive_training_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/training-assignments/{assignment_id}/waive",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------ #
    # Subawards
    # ------------------------------------------------------------------ #
    def create_subaward(self, payload, headers):
        return self._request("POST", "/subawards", payload, headers)

    def get_subaward(self, subaward_id, headers):
        return self._request("GET", f"/subawards/{subaward_id}", headers=headers)

    def list_subawards(self, headers, params=None):
        return self._request("GET", "/subawards", headers=headers, params=params)

    def screen_subaward(self, subaward_id, payload, headers):
        return self._request(
            "POST", f"/subawards/{subaward_id}/screen", payload, headers
        )

    def set_subaward_status(self, subaward_id, payload, headers):
        return self._request(
            "POST", f"/subawards/{subaward_id}/status", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Logical clock
    # ------------------------------------------------------------------ #
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
