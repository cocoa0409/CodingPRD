"""API client: one method per endpoint defined in the PRD (§4).

Subclasses the framework GenericApiClient; the base _request() handles
envelopes, headers, and query params. Every method returns the raw
requests.Response so tests can assert both status code and body.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Incident ────────────────────────────────────────────────────
    def create_incident(self, payload, headers):
        return self._request("POST", "/eoc/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/eoc/incidents/{incident_id}", headers=headers)

    def transition_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/eoc/incidents/{incident_id}/transition", payload, headers)

    def get_situation_report(self, incident_id, headers):
        return self._request("GET", f"/eoc/incidents/{incident_id}/situation-report", headers=headers)

    def list_incident_resource_requests(self, incident_id, headers, params=None):
        return self._request("GET", f"/eoc/incidents/{incident_id}/resource-requests", headers=headers, params=params)

    def list_incident_iaps(self, incident_id, headers, params=None):
        return self._request("GET", f"/eoc/incidents/{incident_id}/incident-action-plans", headers=headers, params=params)

    def list_incident_shelters(self, incident_id, headers, params=None):
        return self._request("GET", f"/eoc/incidents/{incident_id}/shelters", headers=headers, params=params)

    def list_incident_damage_assessments(self, incident_id, headers, params=None):
        return self._request("GET", f"/eoc/incidents/{incident_id}/damage-assessments", headers=headers, params=params)

    # ─── Jurisdiction ────────────────────────────────────────────────
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/eoc/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/eoc/jurisdictions/{jurisdiction_id}", headers=headers)

    def list_jurisdiction_resource_pools(self, jurisdiction_id, headers, params=None):
        return self._request("GET", f"/eoc/jurisdictions/{jurisdiction_id}/resource-pools", headers=headers, params=params)

    # ─── ResourcePool ────────────────────────────────────────────────
    def create_resource_pool(self, payload, headers):
        return self._request("POST", "/eoc/resource-pools", payload, headers)

    def get_resource_pool(self, pool_id, headers):
        return self._request("GET", f"/eoc/resource-pools/{pool_id}", headers=headers)

    def list_pool_resource_requests(self, pool_id, headers, params=None):
        return self._request("GET", f"/eoc/resource-pools/{pool_id}/resource-requests", headers=headers, params=params)

    # ─── ResourceRequest (ICS-213RR) ─────────────────────────────────
    def create_resource_request(self, payload, headers):
        return self._request("POST", "/eoc/resource-requests", payload, headers)

    def transition_resource_request(self, request_id, payload, headers):
        return self._request("POST", f"/eoc/resource-requests/{request_id}/transition", payload, headers)

    # ─── IncidentActionPlan ──────────────────────────────────────────
    def create_iap(self, payload, headers):
        return self._request("POST", "/eoc/incident-action-plans", payload, headers)

    def transition_iap(self, iap_id, payload, headers):
        return self._request("POST", f"/eoc/incident-action-plans/{iap_id}/transition", payload, headers)

    # ─── Task (ICS-204) ──────────────────────────────────────────────
    def create_task(self, payload, headers):
        return self._request("POST", "/eoc/tasks", payload, headers)

    def get_task(self, task_id, headers):
        return self._request("GET", f"/eoc/tasks/{task_id}", headers=headers)

    def list_tasks(self, headers, params=None):
        return self._request("GET", "/eoc/tasks", headers=headers, params=params)

    def transition_task(self, task_id, payload, headers):
        return self._request("POST", f"/eoc/tasks/{task_id}/transition", payload, headers)

    # ─── Shelter ─────────────────────────────────────────────────────
    def create_shelter(self, payload, headers):
        return self._request("POST", "/eoc/shelters", payload, headers)

    def transition_shelter(self, shelter_id, payload, headers):
        return self._request("POST", f"/eoc/shelters/{shelter_id}/transition", payload, headers)

    def adjust_shelter_occupancy(self, shelter_id, payload, headers):
        return self._request("POST", f"/eoc/shelters/{shelter_id}/occupancy", payload, headers)

    # ─── MutualAidRequest (EMAC) ─────────────────────────────────────
    def create_mutual_aid_request(self, payload, headers):
        return self._request("POST", "/eoc/mutual-aid-requests", payload, headers)

    def get_mutual_aid_request(self, ma_id, headers):
        return self._request("GET", f"/eoc/mutual-aid-requests/{ma_id}", headers=headers)

    def list_mutual_aid_requests(self, headers, params=None):
        return self._request("GET", "/eoc/mutual-aid-requests", headers=headers, params=params)

    def transition_mutual_aid_request(self, ma_id, payload, headers):
        return self._request("POST", f"/eoc/mutual-aid-requests/{ma_id}/transition", payload, headers)

    # ─── DamageAssessment ────────────────────────────────────────────
    def create_damage_assessment(self, payload, headers):
        return self._request("POST", "/eoc/damage-assessments", payload, headers)

    def transition_damage_assessment(self, da_id, payload, headers):
        return self._request("POST", f"/eoc/damage-assessments/{da_id}/transition", payload, headers)

    # ─── CostRecord (FEMA-PA) ────────────────────────────────────────
    def create_cost_record(self, payload, headers):
        return self._request("POST", "/eoc/cost-records", payload, headers)

    def get_cost_record(self, cost_id, headers):
        return self._request("GET", f"/eoc/cost-records/{cost_id}", headers=headers)

    def list_cost_records(self, headers, params=None):
        return self._request("GET", "/eoc/cost-records", headers=headers, params=params)

    def transition_cost_record(self, cost_id, payload, headers):
        return self._request("POST", f"/eoc/cost-records/{cost_id}/transition", payload, headers)


api_client = ApiClient()
