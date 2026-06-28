"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Technician pool ----
    def create_technician(self, payload, headers):
        return self._request("POST", "/restoration/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request(
            "GET", f"/restoration/technicians/{technician_id}", headers=headers
        )

    def list_technicians(self, headers, params=None):
        return self._request(
            "GET", "/restoration/technicians", headers=headers, params=params
        )

    # ---- Equipment unit pool ----
    def create_equipment_unit(self, payload, headers):
        return self._request("POST", "/restoration/equipment-units", payload, headers)

    def get_equipment_unit(self, unit_id, headers):
        return self._request(
            "GET", f"/restoration/equipment-units/{unit_id}", headers=headers
        )

    def list_equipment_units(self, headers, params=None):
        return self._request(
            "GET", "/restoration/equipment-units", headers=headers, params=params
        )

    # ---- Insurance claim ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/restoration/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/restoration/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request(
            "GET", "/restoration/claims", headers=headers, params=params
        )

    # ---- Loss job ----
    def create_job(self, payload, headers):
        return self._request("POST", "/restoration/jobs", payload, headers)

    def get_job(self, job_id, headers):
        return self._request("GET", f"/restoration/jobs/{job_id}", headers=headers)

    def list_jobs(self, headers, params=None):
        return self._request(
            "GET", "/restoration/jobs", headers=headers, params=params
        )

    def dispatch_job(self, job_id, payload, headers):
        return self._request(
            "POST", f"/restoration/jobs/{job_id}/dispatch", payload, headers
        )

    def start_mitigation(self, job_id, headers):
        return self._request(
            "POST", f"/restoration/jobs/{job_id}/start-mitigation", {}, headers
        )

    def begin_monitoring(self, job_id, headers):
        return self._request(
            "POST", f"/restoration/jobs/{job_id}/begin-monitoring", {}, headers
        )

    def reopen_mitigation(self, job_id, headers):
        return self._request(
            "POST", f"/restoration/jobs/{job_id}/reopen-mitigation", {}, headers
        )

    def advance_day(self, job_id, headers):
        return self._request(
            "POST", f"/restoration/jobs/{job_id}/advance-day", {}, headers
        )

    def complete_job(self, job_id, headers):
        return self._request(
            "POST", f"/restoration/jobs/{job_id}/complete", {}, headers
        )

    def cancel_job(self, job_id, headers):
        return self._request(
            "POST", f"/restoration/jobs/{job_id}/cancel", {}, headers
        )

    def get_drying_progress(self, job_id, headers, params=None):
        return self._request(
            "GET",
            f"/restoration/jobs/{job_id}/drying-progress",
            headers=headers,
            params=params,
        )

    def get_billing(self, job_id, headers):
        return self._request(
            "GET", f"/restoration/jobs/{job_id}/billing", headers=headers
        )

    def value_contents(self, job_id, headers):
        return self._request(
            "POST", f"/restoration/jobs/{job_id}/contents/value", {}, headers
        )

    # ---- Drying chamber ----
    def create_chamber(self, payload, headers):
        return self._request("POST", "/restoration/chambers", payload, headers)

    def get_chamber(self, chamber_id, headers):
        return self._request(
            "GET", f"/restoration/chambers/{chamber_id}", headers=headers
        )

    def list_chambers(self, headers, params=None):
        return self._request(
            "GET", "/restoration/chambers", headers=headers, params=params
        )

    def decommission_chamber(self, chamber_id, headers):
        return self._request(
            "POST", f"/restoration/chambers/{chamber_id}/decommission", {}, headers
        )

    def create_reading(self, chamber_id, payload, headers):
        return self._request(
            "POST", f"/restoration/chambers/{chamber_id}/readings", payload, headers
        )

    # ---- Moisture reading ----
    def get_reading(self, reading_id, headers):
        return self._request(
            "GET", f"/restoration/readings/{reading_id}", headers=headers
        )

    def list_readings(self, headers, params=None):
        return self._request(
            "GET", "/restoration/readings", headers=headers, params=params
        )

    # ---- Equipment placement ----
    def create_placement(self, payload, headers):
        return self._request("POST", "/restoration/placements", payload, headers)

    def get_placement(self, placement_id, headers):
        return self._request(
            "GET", f"/restoration/placements/{placement_id}", headers=headers
        )

    def list_placements(self, headers, params=None):
        return self._request(
            "GET", "/restoration/placements", headers=headers, params=params
        )

    def remove_placement(self, placement_id, headers):
        return self._request(
            "POST", f"/restoration/placements/{placement_id}/remove", {}, headers
        )

    # ---- Scope estimate ----
    def create_estimate(self, payload, headers):
        return self._request("POST", "/restoration/estimates", payload, headers)

    def get_estimate(self, estimate_id, headers):
        return self._request(
            "GET", f"/restoration/estimates/{estimate_id}", headers=headers
        )

    def list_estimates(self, headers, params=None):
        return self._request(
            "GET", "/restoration/estimates", headers=headers, params=params
        )

    def approve_estimate(self, estimate_id, headers):
        return self._request(
            "POST", f"/restoration/estimates/{estimate_id}/approve", {}, headers
        )

    # ---- Contents item ----
    def create_contents(self, payload, headers):
        return self._request("POST", "/restoration/contents", payload, headers)

    def get_contents(self, item_id, headers):
        return self._request(
            "GET", f"/restoration/contents/{item_id}", headers=headers
        )

    def list_contents(self, headers, params=None):
        return self._request(
            "GET", "/restoration/contents", headers=headers, params=params
        )

    def store_contents(self, item_id, headers):
        return self._request(
            "POST", f"/restoration/contents/{item_id}/store", {}, headers
        )

    def return_contents(self, item_id, headers):
        return self._request(
            "POST", f"/restoration/contents/{item_id}/return", {}, headers
        )


api_client = ApiClient()
