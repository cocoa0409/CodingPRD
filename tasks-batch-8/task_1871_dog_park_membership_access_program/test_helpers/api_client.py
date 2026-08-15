"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving capability, PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/dog-park/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Members
    # ------------------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", "/dog-park/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/dog-park/members/{member_id}",
                             headers=headers)

    def patch_member(self, member_id, payload, headers):
        return self._request("PATCH", f"/dog-park/members/{member_id}",
                             payload, headers)

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/dog-park/members/{member_id}/reinstate",
                             {}, headers)

    def set_steward_status(self, member_id, is_steward, headers):
        return self._request("POST",
                             f"/dog-park/members/{member_id}/steward-status",
                             {"is_steward": is_steward}, headers)

    # ------------------------------------------------------------------
    # Dogs
    # ------------------------------------------------------------------
    def create_dog(self, member_id, payload, headers):
        return self._request("POST", f"/dog-park/members/{member_id}/dogs",
                             payload, headers)

    def list_dogs(self, member_id, headers, params=None):
        return self._request("GET", f"/dog-park/members/{member_id}/dogs",
                             headers=headers, params=params)

    def get_dog(self, dog_id, headers):
        return self._request("GET", f"/dog-park/dogs/{dog_id}", headers=headers)

    def verify_dog(self, dog_id, payload, headers):
        return self._request("POST", f"/dog-park/dogs/{dog_id}/verify",
                             payload, headers)

    def resubmit_dog(self, dog_id, payload, headers):
        return self._request("POST", f"/dog-park/dogs/{dog_id}/resubmit",
                             payload, headers)

    # ------------------------------------------------------------------
    # Memberships
    # ------------------------------------------------------------------
    def purchase_membership(self, member_id, headers):
        return self._request("POST", f"/dog-park/members/{member_id}/memberships",
                             {}, headers)

    def list_memberships(self, member_id, headers, params=None):
        return self._request("GET",
                             f"/dog-park/members/{member_id}/memberships",
                             headers=headers, params=params)

    def renew_membership(self, membership_id, payload, headers):
        return self._request("POST",
                             f"/dog-park/memberships/{membership_id}/renew",
                             payload, headers)

    # ------------------------------------------------------------------
    # Guest passes
    # ------------------------------------------------------------------
    def purchase_guest_pass(self, payload, headers):
        return self._request("POST", "/dog-park/guest-passes", payload, headers)

    def list_guest_passes(self, headers, params=None):
        return self._request("GET", "/dog-park/guest-passes",
                             headers=headers, params=params)

    def get_guest_pass(self, pass_id, headers):
        return self._request("GET", f"/dog-park/guest-passes/{pass_id}",
                             headers=headers)

    def void_guest_pass(self, pass_id, headers):
        return self._request("POST", f"/dog-park/guest-passes/{pass_id}/void",
                             {}, headers)

    # ------------------------------------------------------------------
    # Park areas
    # ------------------------------------------------------------------
    def create_area(self, payload, headers):
        return self._request("POST", "/dog-park/areas", payload, headers)

    def list_areas(self, headers, params=None):
        return self._request("GET", "/dog-park/areas", headers=headers,
                             params=params)

    def get_area(self, area_id, headers):
        return self._request("GET", f"/dog-park/areas/{area_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Area closures
    # ------------------------------------------------------------------
    def create_closure(self, area_id, payload, headers):
        return self._request("POST", f"/dog-park/areas/{area_id}/closures",
                             payload, headers)

    def list_closures(self, area_id, headers, params=None):
        return self._request("GET", f"/dog-park/areas/{area_id}/closures",
                             headers=headers, params=params)

    def cancel_closure(self, closure_id, headers):
        return self._request("POST", f"/dog-park/closures/{closure_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Park visits
    # ------------------------------------------------------------------
    def check_in(self, payload, headers):
        return self._request("POST", "/dog-park/visits/check-in", payload,
                             headers)

    def check_out(self, visit_id, headers):
        return self._request("POST", f"/dog-park/visits/{visit_id}/check-out",
                             {}, headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/dog-park/visits", headers=headers,
                             params=params)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/dog-park/visits/{visit_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Incident reports
    # ------------------------------------------------------------------
    def file_incident_report(self, payload, headers):
        return self._request("POST", "/dog-park/incident-reports", payload,
                             headers)

    def list_incident_reports(self, headers, params=None):
        return self._request("GET", "/dog-park/incident-reports",
                             headers=headers, params=params)

    def get_incident_report(self, report_id, headers):
        return self._request("GET", f"/dog-park/incident-reports/{report_id}",
                             headers=headers)

    def advance_incident_report(self, report_id, payload, headers):
        return self._request("POST",
                             f"/dog-park/incident-reports/{report_id}/advance",
                             payload, headers)

    # ------------------------------------------------------------------
    # Waste stations
    # ------------------------------------------------------------------
    def create_waste_station(self, area_id, payload, headers):
        return self._request("POST",
                             f"/dog-park/areas/{area_id}/waste-stations",
                             payload, headers)

    def list_waste_stations(self, area_id, headers, params=None):
        return self._request("GET",
                             f"/dog-park/areas/{area_id}/waste-stations",
                             headers=headers, params=params)

    def service_waste_station(self, station_id, headers):
        return self._request("POST",
                             f"/dog-park/waste-stations/{station_id}/service",
                             {}, headers)

    # ------------------------------------------------------------------
    # Nightly service run
    # ------------------------------------------------------------------
    def run_nightly_service_run(self, headers):
        return self._request("POST", "/dog-park/service-runs/nightly", {},
                             headers)


api_client = ApiClient()
