"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Beach ----
    def create_beach(self, payload, headers):
        return self._request("POST", "/beach-ops/beaches", payload, headers=headers)

    def get_beach(self, beach_id, headers):
        return self._request("GET", f"/beach-ops/beaches/{beach_id}", headers=headers)

    def get_seasonal_report(self, beach_id, headers):
        return self._request("GET", f"/beach-ops/beaches/{beach_id}/seasonal-report", headers=headers)

    # ---- Zone ----
    def create_zone(self, payload, headers):
        return self._request("POST", "/beach-ops/zones", payload, headers=headers)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/beach-ops/zones/{zone_id}", headers=headers)

    def list_zones(self, headers, params=None):
        return self._request("GET", "/beach-ops/zones", headers=headers, params=params)

    def set_zone_flag(self, zone_id, payload, headers):
        return self._request("POST", f"/beach-ops/zones/{zone_id}/flag", payload, headers=headers)

    def post_zone_conditions(self, zone_id, payload, headers):
        return self._request("POST", f"/beach-ops/zones/{zone_id}/conditions", payload, headers=headers)

    def create_advisory(self, zone_id, payload, headers):
        return self._request("POST", f"/beach-ops/zones/{zone_id}/advisories", payload, headers=headers)

    # ---- Tower ----
    def create_tower(self, payload, headers):
        return self._request("POST", "/beach-ops/towers", payload, headers=headers)

    def get_tower(self, tower_id, headers):
        return self._request("GET", f"/beach-ops/towers/{tower_id}", headers=headers)

    def list_towers(self, headers, params=None):
        return self._request("GET", "/beach-ops/towers", headers=headers, params=params)

    def set_tower_status(self, tower_id, payload, headers):
        return self._request("POST", f"/beach-ops/towers/{tower_id}/status", payload, headers=headers)

    # ---- Lifeguard ----
    def create_lifeguard(self, payload, headers):
        return self._request("POST", "/beach-ops/lifeguards", payload, headers=headers)

    def get_lifeguard(self, lifeguard_id, headers):
        return self._request("GET", f"/beach-ops/lifeguards/{lifeguard_id}", headers=headers)

    def list_lifeguards(self, headers, params=None):
        return self._request("GET", "/beach-ops/lifeguards", headers=headers, params=params)

    # ---- Shift ----
    def create_shift(self, payload, headers):
        return self._request("POST", "/beach-ops/shifts", payload, headers=headers)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/beach-ops/shifts/{shift_id}", headers=headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/beach-ops/shifts", headers=headers, params=params)

    def transition_shift(self, shift_id, payload, headers):
        return self._request("POST", f"/beach-ops/shifts/{shift_id}/transitions", payload, headers=headers)

    # ---- Incident ----
    def create_incident(self, payload, headers):
        return self._request("POST", "/beach-ops/incidents", payload, headers=headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/beach-ops/incidents/{incident_id}", headers=headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/beach-ops/incidents", headers=headers, params=params)

    def transition_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/beach-ops/incidents/{incident_id}/transitions", payload, headers=headers)

    # ---- Water-quality samples ----
    def create_sample(self, payload, headers):
        return self._request("POST", "/beach-ops/water-quality-samples", payload, headers=headers)

    def get_sample(self, sample_id, headers):
        return self._request("GET", f"/beach-ops/water-quality-samples/{sample_id}", headers=headers)

    def list_samples(self, headers, params=None):
        return self._request("GET", "/beach-ops/water-quality-samples", headers=headers, params=params)

    # ---- Advisory ----
    def get_advisory(self, advisory_id, headers):
        return self._request("GET", f"/beach-ops/advisories/{advisory_id}", headers=headers)

    def list_advisories(self, headers, params=None):
        return self._request("GET", "/beach-ops/advisories", headers=headers, params=params)

    def lift_advisory(self, advisory_id, payload, headers):
        return self._request("POST", f"/beach-ops/advisories/{advisory_id}/lift", payload, headers=headers)

    # ---- Parking ----
    def create_parking_lot(self, payload, headers):
        return self._request("POST", "/beach-ops/parking-lots", payload, headers=headers)

    def get_parking_lot(self, lot_id, headers):
        return self._request("GET", f"/beach-ops/parking-lots/{lot_id}", headers=headers)

    def list_parking_lots(self, headers, params=None):
        return self._request("GET", "/beach-ops/parking-lots", headers=headers, params=params)

    def create_parking_pass(self, payload, headers):
        return self._request("POST", "/beach-ops/parking-passes", payload, headers=headers)

    def get_parking_pass(self, pass_id, headers):
        return self._request("GET", f"/beach-ops/parking-passes/{pass_id}", headers=headers)

    def list_parking_passes(self, headers, params=None):
        return self._request("GET", "/beach-ops/parking-passes", headers=headers, params=params)

    def revoke_parking_pass(self, pass_id, payload, headers):
        return self._request("POST", f"/beach-ops/parking-passes/{pass_id}/revoke", payload, headers=headers)

    # ---- Test-driving logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)


api_client = ApiClient()
