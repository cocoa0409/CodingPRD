"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Carrier ---
    def create_carrier(self, payload, headers):
        return self._request("POST", "/carriers", payload, headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", "/carriers", headers=headers, params=params)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/carriers/{carrier_id}", headers=headers)

    def create_driver(self, carrier_id, payload, headers):
        return self._request("POST", f"/carriers/{carrier_id}/drivers", payload, headers)

    def list_drivers(self, carrier_id, headers, params=None):
        return self._request("GET", f"/carriers/{carrier_id}/drivers", headers=headers, params=params)

    def create_score_snapshot(self, carrier_id, payload, headers):
        return self._request("POST", f"/carriers/{carrier_id}/score-snapshots", payload, headers)

    def list_score_snapshots(self, carrier_id, headers, params=None):
        return self._request("GET", f"/carriers/{carrier_id}/score-snapshots", headers=headers, params=params)

    # --- WeighStation / Bay ---
    def create_station(self, payload, headers):
        return self._request("POST", "/stations", payload, headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    def create_bay(self, station_id, payload, headers):
        return self._request("POST", f"/stations/{station_id}/bays", payload, headers)

    def list_bays(self, station_id, headers, params=None):
        return self._request("GET", f"/stations/{station_id}/bays", headers=headers, params=params)

    # --- Driver / duty logs ---
    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/drivers/{driver_id}", headers=headers)

    def create_duty_log(self, driver_id, payload, headers):
        return self._request("POST", f"/drivers/{driver_id}/duty-logs", payload, headers)

    def list_duty_logs(self, driver_id, headers, params=None):
        return self._request("GET", f"/drivers/{driver_id}/duty-logs", headers=headers, params=params)

    # --- Screening ---
    def create_screening(self, payload, headers):
        return self._request("POST", "/screenings", payload, headers)

    def list_screenings(self, headers, params=None):
        return self._request("GET", "/screenings", headers=headers, params=params)

    def get_screening(self, screening_id, headers):
        return self._request("GET", f"/screenings/{screening_id}", headers=headers)

    # --- Inspection ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def create_violation(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/violations", payload, headers)

    def list_violations(self, inspection_id, headers, params=None):
        return self._request("GET", f"/inspections/{inspection_id}/violations", headers=headers, params=params)

    def finalize_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/finalize", payload, headers)

    def reinspect(self, inspection_id, headers):
        return self._request("POST", f"/inspections/{inspection_id}/reinspect", {}, headers)

    def cancel_inspection(self, inspection_id, headers):
        return self._request("POST", f"/inspections/{inspection_id}/cancel", {}, headers)

    # --- Citation ---
    def create_citation(self, payload, headers):
        return self._request("POST", "/citations", payload, headers)

    def list_citations(self, headers, params=None):
        return self._request("GET", "/citations", headers=headers, params=params)

    def get_citation(self, citation_id, headers):
        return self._request("GET", f"/citations/{citation_id}", headers=headers)

    def contest_citation(self, citation_id, payload, headers):
        return self._request("POST", f"/citations/{citation_id}/contest", payload, headers)

    def adjudicate_citation(self, citation_id, payload, headers):
        return self._request("POST", f"/citations/{citation_id}/adjudicate", payload, headers)

    def settle_citation(self, citation_id, payload, headers):
        return self._request("POST", f"/citations/{citation_id}/settle", payload, headers)


api_client = ApiClient()
