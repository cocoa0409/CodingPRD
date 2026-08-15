"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Establishments
    # ------------------------------------------------------------------
    def create_establishment(self, payload, headers):
        return self._request("POST", "/establishments", payload, headers)

    def get_establishment(self, establishment_id, headers):
        return self._request("GET", f"/establishments/{establishment_id}",
                             headers=headers)

    def patch_establishment(self, establishment_id, payload, headers):
        return self._request("PATCH", f"/establishments/{establishment_id}",
                             payload, headers)

    # ------------------------------------------------------------------
    # Grease interceptors
    # ------------------------------------------------------------------
    def create_interceptor(self, payload, headers):
        return self._request("POST", "/interceptors", payload, headers)

    def list_interceptors(self, headers, params=None):
        return self._request("GET", "/interceptors", headers=headers, params=params)

    def get_interceptor(self, interceptor_id, headers):
        return self._request("GET", f"/interceptors/{interceptor_id}",
                             headers=headers)

    def approve_interceptor(self, interceptor_id, headers):
        return self._request("POST", f"/interceptors/{interceptor_id}/approve",
                             {}, headers)

    def commission_interceptor(self, interceptor_id, headers):
        return self._request("POST", f"/interceptors/{interceptor_id}/commission",
                             {}, headers)

    # ------------------------------------------------------------------
    # Inspections
    # ------------------------------------------------------------------
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    # ------------------------------------------------------------------
    # Violations
    # ------------------------------------------------------------------
    def list_violations(self, headers, params=None):
        return self._request("GET", "/violations", headers=headers, params=params)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/violations/{violation_id}", headers=headers)

    def escalate_violation(self, violation_id, headers):
        return self._request("POST", f"/violations/{violation_id}/escalate",
                             {}, headers)

    def resolve_violation(self, violation_id, headers):
        return self._request("POST", f"/violations/{violation_id}/resolve",
                             {}, headers)

    def dismiss_violation(self, violation_id, headers):
        return self._request("POST", f"/violations/{violation_id}/dismiss",
                             {}, headers)

    # ------------------------------------------------------------------
    # Pump manifests
    # ------------------------------------------------------------------
    def create_pump_manifest(self, payload, headers):
        return self._request("POST", "/pump-manifests", payload, headers)

    def list_pump_manifests(self, headers, params=None):
        return self._request("GET", "/pump-manifests", headers=headers, params=params)

    def get_pump_manifest(self, manifest_id, headers):
        return self._request("GET", f"/pump-manifests/{manifest_id}",
                             headers=headers)

    def verify_pump_manifest(self, manifest_id, headers):
        return self._request("POST", f"/pump-manifests/{manifest_id}/verify",
                             {}, headers)

    def reject_pump_manifest(self, manifest_id, reason_code, headers):
        return self._request("POST", f"/pump-manifests/{manifest_id}/reject",
                             {"reason_code": reason_code}, headers)

    # ------------------------------------------------------------------
    # Haulers
    # ------------------------------------------------------------------
    def create_hauler(self, payload, headers):
        return self._request("POST", "/haulers", payload, headers)

    def get_hauler(self, hauler_id, headers):
        return self._request("GET", f"/haulers/{hauler_id}", headers=headers)

    def permit_hauler(self, hauler_id, headers):
        return self._request("POST", f"/haulers/{hauler_id}/permit", {}, headers)

    def suspend_hauler(self, hauler_id, headers):
        return self._request("POST", f"/haulers/{hauler_id}/suspend", {}, headers)

    def reinstate_hauler(self, hauler_id, headers):
        return self._request("POST", f"/haulers/{hauler_id}/reinstate", {}, headers)

    def revoke_hauler(self, hauler_id, headers):
        return self._request("POST", f"/haulers/{hauler_id}/revoke", {}, headers)

    # ------------------------------------------------------------------
    # Disposal records
    # ------------------------------------------------------------------
    def create_disposal_record(self, payload, headers):
        return self._request("POST", "/disposal-records", payload, headers)

    def list_disposal_records(self, headers, params=None):
        return self._request("GET", "/disposal-records", headers=headers,
                             params=params)

    def get_disposal_record(self, disposal_record_id, headers):
        return self._request("GET", f"/disposal-records/{disposal_record_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Blockage events and cost recovery
    # ------------------------------------------------------------------
    def create_blockage_event(self, payload, headers):
        return self._request("POST", "/blockage-events", payload, headers)

    def get_blockage_event(self, blockage_id, headers):
        return self._request("GET", f"/blockage-events/{blockage_id}",
                             headers=headers)

    def assess_blockage_event(self, blockage_id, payload, headers):
        return self._request("POST", f"/blockage-events/{blockage_id}/assess",
                             payload, headers)

    def pay_blockage_share(self, blockage_id, establishment_id, headers):
        return self._request("POST", f"/blockage-events/{blockage_id}/pay",
                             {"establishment_id": establishment_id}, headers)

    def close_blockage_event(self, blockage_id, headers):
        return self._request("POST", f"/blockage-events/{blockage_id}/close",
                             {}, headers)

    # ------------------------------------------------------------------
    # Variance requests
    # ------------------------------------------------------------------
    def create_variance_request(self, payload, headers):
        return self._request("POST", "/variance-requests", payload, headers)

    def list_variance_requests(self, headers, params=None):
        return self._request("GET", "/variance-requests", headers=headers,
                             params=params)

    def get_variance_request(self, variance_id, headers):
        return self._request("GET", f"/variance-requests/{variance_id}",
                             headers=headers)

    def request_variance_info(self, variance_id, headers):
        return self._request("POST",
                             f"/variance-requests/{variance_id}/request-info",
                             {}, headers)

    def provide_variance_info(self, variance_id, justification, headers):
        return self._request("POST",
                             f"/variance-requests/{variance_id}/provide-info",
                             {"justification": justification}, headers)

    def approve_variance_request(self, variance_id, expected_establishment_version,
                                 headers):
        return self._request(
            "POST", f"/variance-requests/{variance_id}/approve",
            {"expected_establishment_version": expected_establishment_version},
            headers)

    def deny_variance_request(self, variance_id, headers):
        return self._request("POST", f"/variance-requests/{variance_id}/deny",
                             {}, headers)

    # ------------------------------------------------------------------
    # Education campaigns and outreach events
    # ------------------------------------------------------------------
    def create_campaign(self, payload, headers):
        return self._request("POST", "/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/campaigns/{campaign_id}", headers=headers)

    def create_outreach_event(self, campaign_id, payload, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/events",
                             payload, headers)

    def list_outreach_events(self, headers, params=None):
        return self._request("GET", "/outreach-events", headers=headers,
                             params=params)

    def get_outreach_event(self, event_id, headers):
        return self._request("GET", f"/outreach-events/{event_id}", headers=headers)

    def void_outreach_event(self, event_id, headers):
        return self._request("POST", f"/outreach-events/{event_id}/void",
                             {}, headers)

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------
    def run_sweep(self, headers):
        return self._request("POST", "/sweeps/run", {}, headers)


api_client = ApiClient()
