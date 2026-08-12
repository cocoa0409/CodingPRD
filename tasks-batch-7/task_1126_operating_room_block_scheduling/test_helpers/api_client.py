"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- ServiceLine ---
    def create_service_line(self, payload, headers):
        return self._request("POST", "/service-lines", payload, headers)

    def list_service_lines(self, headers, params=None):
        return self._request("GET", "/service-lines", headers=headers, params=params)

    def get_service_line(self, line_id, headers):
        return self._request("GET", f"/service-lines/{line_id}", headers=headers)

    def patch_service_line(self, line_id, payload, headers):
        return self._request("PATCH", f"/service-lines/{line_id}", payload, headers)

    # --- Surgeon ---
    def create_surgeon(self, payload, headers):
        return self._request("POST", "/surgeons", payload, headers)

    def list_surgeons(self, headers, params=None):
        return self._request("GET", "/surgeons", headers=headers, params=params)

    def get_surgeon(self, surgeon_id, headers):
        return self._request("GET", f"/surgeons/{surgeon_id}", headers=headers)

    # --- OperatingRoom ---
    def create_operating_room(self, payload, headers):
        return self._request("POST", "/operating-rooms", payload, headers)

    def list_operating_rooms(self, headers, params=None):
        return self._request("GET", "/operating-rooms", headers=headers, params=params)

    # --- BlockAllocation ---
    def create_block(self, payload, headers):
        return self._request("POST", "/blocks", payload, headers)

    def list_blocks(self, headers, params=None):
        return self._request("GET", "/blocks", headers=headers, params=params)

    def get_block(self, block_id, headers):
        return self._request("GET", f"/blocks/{block_id}", headers=headers)

    def activate_block(self, block_id, headers):
        return self._request("POST", f"/blocks/{block_id}/activate", headers=headers)

    def release_block(self, block_id, headers):
        return self._request("POST", f"/blocks/{block_id}/release", headers=headers)

    def cancel_block(self, block_id, headers):
        return self._request("POST", f"/blocks/{block_id}/cancel", headers=headers)

    # --- CasePosting ---
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def schedule_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/schedule", payload, headers)

    def reschedule_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/reschedule", payload, headers)

    def start_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/start", payload, headers)

    def complete_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/complete", payload, headers)

    def cancel_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/cancel", headers=headers)

    # --- AnesthesiaCoverage ---
    def create_anesthesia_coverage(self, payload, headers):
        return self._request("POST", "/anesthesia-coverages", payload, headers)

    def list_anesthesia_coverages(self, headers, params=None):
        return self._request("GET", "/anesthesia-coverages", headers=headers, params=params)

    def get_anesthesia_coverage(self, coverage_id, headers):
        return self._request("GET", f"/anesthesia-coverages/{coverage_id}", headers=headers)

    def withdraw_anesthesia_coverage(self, coverage_id, headers):
        return self._request(
            "POST", f"/anesthesia-coverages/{coverage_id}/withdraw", headers=headers
        )

    # --- OpenTimeSlot (read-only) ---
    def list_open_time_slots(self, headers, params=None):
        return self._request("GET", "/open-time-slots", headers=headers, params=params)

    def get_open_time_slot(self, slot_id, headers):
        return self._request("GET", f"/open-time-slots/{slot_id}", headers=headers)

    # --- ReallocationRequest ---
    def create_reallocation_request(self, payload, headers):
        return self._request("POST", "/reallocation-requests", payload, headers)

    def list_reallocation_requests(self, headers, params=None):
        return self._request("GET", "/reallocation-requests", headers=headers, params=params)

    def get_reallocation_request(self, request_id, headers):
        return self._request("GET", f"/reallocation-requests/{request_id}", headers=headers)

    def withdraw_reallocation_request(self, request_id, headers):
        return self._request(
            "POST", f"/reallocation-requests/{request_id}/withdraw", headers=headers
        )

    # --- Ops-run checkpoints ---
    def release_sweep(self, headers):
        return self._request("POST", "/ops/release-sweep", None, headers)

    def scoring_run(self, headers):
        return self._request("POST", "/ops/scoring-run", None, headers)

    # --- UtilizationReport (read-only sub-resource) ---
    def list_utilization_reports(self, line_id, headers, params=None):
        return self._request(
            "GET", f"/service-lines/{line_id}/utilization-reports",
            headers=headers, params=params,
        )

    # --- Committee governance ---
    def list_committee_reviews(self, headers, params=None):
        return self._request("GET", "/committee-reviews", headers=headers, params=params)

    def get_committee_review(self, review_id, headers):
        return self._request("GET", f"/committee-reviews/{review_id}", headers=headers)

    def cast_committee_vote(self, review_id, payload, headers):
        return self._request(
            "POST", f"/committee-reviews/{review_id}/votes", payload, headers
        )

    def list_committee_votes(self, review_id, headers, params=None):
        return self._request(
            "GET", f"/committee-reviews/{review_id}/votes", headers=headers, params=params
        )

    def reopen_committee_review(self, review_id, headers):
        return self._request(
            "POST", f"/committee-reviews/{review_id}/reopen", headers=headers
        )

    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
