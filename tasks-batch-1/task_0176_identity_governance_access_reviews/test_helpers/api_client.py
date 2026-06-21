"""API client: one method per endpoint defined in the Identity Governance
PRD (§4). The base _request() method is inherited from the framework's
GenericApiClient.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- entitlements ----
    def create_entitlement(self, payload, headers):
        return self._request("POST", "/entitlements", payload, headers)

    def get_entitlement(self, entitlement_id, headers):
        return self._request("GET", f"/entitlements/{entitlement_id}", headers=headers)

    def list_entitlements(self, headers, params=None):
        return self._request("GET", "/entitlements", headers=headers, params=params)

    def archive_entitlement(self, entitlement_id, headers):
        return self._request("POST", f"/entitlements/{entitlement_id}/archive", {}, headers)

    # ---- roles ----
    def create_role(self, payload, headers):
        return self._request("POST", "/roles", payload, headers)

    def get_role(self, role_id, headers):
        return self._request("GET", f"/roles/{role_id}", headers=headers)

    def list_roles(self, headers, params=None):
        return self._request("GET", "/roles", headers=headers, params=params)

    def retire_role(self, role_id, headers):
        return self._request("POST", f"/roles/{role_id}/retire", {}, headers)

    # ---- sod-policies ----
    def create_sod_policy(self, payload, headers):
        return self._request("POST", "/sod-policies", payload, headers)

    def get_sod_policy(self, policy_id, headers):
        return self._request("GET", f"/sod-policies/{policy_id}", headers=headers)

    def list_sod_policies(self, headers, params=None):
        return self._request("GET", "/sod-policies", headers=headers, params=params)

    # ---- identities ----
    def create_identity(self, payload, headers):
        return self._request("POST", "/identities", payload, headers)

    def get_identity(self, identity_id, headers):
        return self._request("GET", f"/identities/{identity_id}", headers=headers)

    def list_identities(self, headers, params=None):
        return self._request("GET", "/identities", headers=headers, params=params)

    def create_grant(self, identity_id, payload, headers):
        return self._request("POST", f"/identities/{identity_id}/grants", payload, headers)

    def disable_identity(self, identity_id, payload, headers):
        return self._request("POST", f"/identities/{identity_id}/disable", payload, headers)

    def enable_identity(self, identity_id, payload, headers):
        return self._request("POST", f"/identities/{identity_id}/enable", payload, headers)

    def deprovision_identity(self, identity_id, headers):
        return self._request("POST", f"/identities/{identity_id}/deprovision", {}, headers)

    def list_identity_grants(self, identity_id, headers, params=None):
        return self._request("GET", f"/identities/{identity_id}/grants", headers=headers, params=params)

    def list_identity_audit_events(self, identity_id, headers, params=None):
        return self._request("GET", f"/identities/{identity_id}/audit-events", headers=headers, params=params)

    # ---- access-requests ----
    def create_access_request(self, payload, headers):
        return self._request("POST", "/access-requests", payload, headers)

    def get_access_request(self, request_id, headers):
        return self._request("GET", f"/access-requests/{request_id}", headers=headers)

    def list_access_requests(self, headers, params=None):
        return self._request("GET", "/access-requests", headers=headers, params=params)

    def submit_access_request(self, request_id, headers):
        return self._request("POST", f"/access-requests/{request_id}/submit", {}, headers)

    def return_access_request(self, request_id, headers):
        return self._request("POST", f"/access-requests/{request_id}/return", {}, headers)

    def approve_access_request(self, request_id, payload, headers):
        return self._request("POST", f"/access-requests/{request_id}/approve", payload, headers)

    def reject_access_request(self, request_id, headers):
        return self._request("POST", f"/access-requests/{request_id}/reject", {}, headers)

    # ---- grants ----
    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/grants/{grant_id}", headers=headers)

    def list_grants(self, headers, params=None):
        return self._request("GET", "/grants", headers=headers, params=params)

    def revoke_grant(self, grant_id, headers):
        return self._request("POST", f"/grants/{grant_id}/revoke", {}, headers)

    # ---- certification-campaigns ----
    def create_campaign(self, payload, headers):
        return self._request("POST", "/certification-campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/certification-campaigns/{campaign_id}", headers=headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/certification-campaigns", headers=headers, params=params)

    def launch_campaign(self, campaign_id, headers):
        return self._request("POST", f"/certification-campaigns/{campaign_id}/launch", {}, headers)

    def close_campaign(self, campaign_id, headers):
        return self._request("POST", f"/certification-campaigns/{campaign_id}/close", {}, headers)

    def list_campaign_items(self, campaign_id, headers, params=None):
        return self._request("GET", f"/certification-campaigns/{campaign_id}/items", headers=headers, params=params)

    # ---- certification-items ----
    def get_certification_item(self, item_id, headers):
        return self._request("GET", f"/certification-items/{item_id}", headers=headers)

    def list_certification_items(self, headers, params=None):
        return self._request("GET", "/certification-items", headers=headers, params=params)

    def certify_item(self, item_id, headers):
        return self._request("POST", f"/certification-items/{item_id}/certify", {}, headers)

    def revoke_item(self, item_id, headers):
        return self._request("POST", f"/certification-items/{item_id}/revoke", {}, headers)

    # ---- audit-events ----
    def get_audit_event(self, event_id, headers):
        return self._request("GET", f"/audit-events/{event_id}", headers=headers)

    def list_audit_events(self, headers, params=None):
        return self._request("GET", "/audit-events", headers=headers, params=params)

    # ---- test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
