"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Jurisdiction / configuration ----
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/sorna/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/sorna/jurisdictions/{jurisdiction_id}", headers=headers)

    def create_exclusion_zone(self, jurisdiction_id, payload, headers):
        return self._request("POST", f"/sorna/jurisdictions/{jurisdiction_id}/exclusion-zones", payload, headers)

    def list_exclusion_zones(self, jurisdiction_id, headers, params=None):
        return self._request("GET", f"/sorna/jurisdictions/{jurisdiction_id}/exclusion-zones", headers=headers, params=params)

    def get_exclusion_zone(self, zone_id, headers):
        return self._request("GET", f"/sorna/exclusion-zones/{zone_id}", headers=headers)

    def list_jurisdiction_registrants(self, jurisdiction_id, headers, params=None):
        return self._request("GET", f"/sorna/jurisdictions/{jurisdiction_id}/registrants", headers=headers, params=params)

    def list_inbound_travel_notices(self, jurisdiction_id, headers, params=None):
        return self._request("GET", f"/sorna/jurisdictions/{jurisdiction_id}/inbound-travel-notices", headers=headers, params=params)

    def get_compliance_report(self, jurisdiction_id, headers):
        return self._request("GET", f"/sorna/jurisdictions/{jurisdiction_id}/compliance-report", headers=headers)

    # ---- Registrant lifecycle ----
    def create_registrant(self, payload, headers):
        return self._request("POST", "/sorna/registrants", payload, headers)

    def get_registrant(self, registrant_id, headers):
        return self._request("GET", f"/sorna/registrants/{registrant_id}", headers=headers)

    def create_offense(self, registrant_id, payload, headers):
        return self._request("POST", f"/sorna/registrants/{registrant_id}/offenses", payload, headers)

    def list_offenses(self, registrant_id, headers, params=None):
        return self._request("GET", f"/sorna/registrants/{registrant_id}/offenses", headers=headers, params=params)

    def activate_registrant(self, registrant_id, headers):
        return self._request("POST", f"/sorna/registrants/{registrant_id}/activate", {}, headers)

    def create_address(self, registrant_id, payload, headers):
        return self._request("POST", f"/sorna/registrants/{registrant_id}/addresses", payload, headers)

    def list_addresses(self, registrant_id, headers, params=None):
        return self._request("GET", f"/sorna/registrants/{registrant_id}/addresses", headers=headers, params=params)

    # ---- Verification ----
    def create_verification(self, registrant_id, payload, headers):
        return self._request("POST", f"/sorna/registrants/{registrant_id}/verifications", payload, headers)

    def list_verifications(self, registrant_id, headers, params=None):
        return self._request("GET", f"/sorna/registrants/{registrant_id}/verifications", headers=headers, params=params)

    def verification_check(self, registrant_id, headers):
        return self._request("POST", f"/sorna/registrants/{registrant_id}/verification-check", {}, headers)

    # ---- Compliance flags ----
    def create_flag(self, registrant_id, payload, headers):
        return self._request("POST", f"/sorna/registrants/{registrant_id}/flags", payload, headers)

    def list_flags(self, registrant_id, headers, params=None):
        return self._request("GET", f"/sorna/registrants/{registrant_id}/flags", headers=headers, params=params)

    def resolve_flag(self, flag_id, headers):
        return self._request("POST", f"/sorna/compliance-flags/{flag_id}/resolve", {}, headers)

    # ---- Travel / inter-jurisdiction ----
    def create_travel_notice(self, registrant_id, payload, headers):
        return self._request("POST", f"/sorna/registrants/{registrant_id}/travel-notices", payload, headers)

    def list_travel_notices(self, registrant_id, headers, params=None):
        return self._request("GET", f"/sorna/registrants/{registrant_id}/travel-notices", headers=headers, params=params)

    def decide_travel_notice(self, travel_notice_id, payload, headers):
        return self._request("POST", f"/sorna/travel-notices/{travel_notice_id}/decision", payload, headers)

    def cancel_travel_notice(self, travel_notice_id, headers):
        return self._request("POST", f"/sorna/travel-notices/{travel_notice_id}/cancel", {}, headers)

    # ---- Community notification ----
    def create_notification(self, registrant_id, payload, headers):
        return self._request("POST", f"/sorna/registrants/{registrant_id}/notifications", payload, headers)

    def list_notifications(self, registrant_id, headers, params=None):
        return self._request("GET", f"/sorna/registrants/{registrant_id}/notifications", headers=headers, params=params)

    # ---- Petition to deregister ----
    def create_petition(self, registrant_id, payload, headers):
        return self._request("POST", f"/sorna/registrants/{registrant_id}/petitions", payload, headers)

    def list_petitions(self, registrant_id, headers, params=None):
        return self._request("GET", f"/sorna/registrants/{registrant_id}/petitions", headers=headers, params=params)

    def get_petition(self, petition_id, headers):
        return self._request("GET", f"/sorna/petitions/{petition_id}", headers=headers)

    def decide_petition(self, petition_id, payload, headers):
        return self._request("POST", f"/sorna/petitions/{petition_id}/decision", payload, headers)

    # ---- Test-driving ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/sorna/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
