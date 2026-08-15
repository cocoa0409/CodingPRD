"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/curbside/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- households ---
    def create_household(self, payload, headers):
        return self._request("POST", "/curbside/households", payload, headers)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/curbside/households/{household_id}", headers=headers)

    def list_households(self, headers, params=None):
        return self._request("GET", "/curbside/households", headers=headers, params=params)

    def reinstate_household(self, household_id, headers):
        return self._request(
            "POST", f"/curbside/households/{household_id}/reinstate", {}, headers
        )

    def list_household_allowances(self, household_id, headers):
        return self._request(
            "GET", f"/curbside/households/{household_id}/allowances", headers=headers
        )

    def list_household_pickup_requests(self, household_id, headers):
        return self._request(
            "GET", f"/curbside/households/{household_id}/pickup-requests", headers=headers
        )

    def list_household_dumping_reports(self, household_id, headers):
        return self._request(
            "GET", f"/curbside/households/{household_id}/dumping-reports", headers=headers
        )

    def list_household_fee_assessments(self, household_id, headers):
        return self._request(
            "GET", f"/curbside/households/{household_id}/fee-assessments", headers=headers
        )

    # --- amnesty windows ---
    def create_amnesty_window(self, payload, headers):
        return self._request("POST", "/curbside/amnesty-windows", payload, headers)

    def get_amnesty_window(self, window_id, headers):
        return self._request(
            "GET", f"/curbside/amnesty-windows/{window_id}", headers=headers
        )

    def list_amnesty_windows(self, headers, params=None):
        return self._request("GET", "/curbside/amnesty-windows", headers=headers, params=params)

    def cancel_amnesty_window(self, window_id, headers):
        return self._request(
            "POST", f"/curbside/amnesty-windows/{window_id}/cancel", {}, headers
        )

    # --- route days ---
    def create_route_day(self, payload, headers):
        return self._request("POST", "/curbside/route-days", payload, headers)

    def get_route_day(self, route_day_id, headers):
        return self._request("GET", f"/curbside/route-days/{route_day_id}", headers=headers)

    def list_route_days(self, headers, params=None):
        return self._request("GET", "/curbside/route-days", headers=headers, params=params)

    def dispatch_route_day(self, route_day_id, headers):
        return self._request(
            "POST", f"/curbside/route-days/{route_day_id}/dispatch", {}, headers
        )

    def close_route_day(self, route_day_id, headers):
        return self._request(
            "POST", f"/curbside/route-days/{route_day_id}/close", {}, headers
        )

    def list_route_day_pickup_requests(self, route_day_id, headers):
        return self._request(
            "GET", f"/curbside/route-days/{route_day_id}/pickup-requests", headers=headers
        )

    # --- pickup requests ---
    def create_pickup_request(self, payload, headers):
        return self._request("POST", "/curbside/pickup-requests", payload, headers)

    def get_pickup_request(self, request_id, headers):
        return self._request(
            "GET", f"/curbside/pickup-requests/{request_id}", headers=headers
        )

    def list_pickup_requests(self, headers, params=None):
        return self._request(
            "GET", "/curbside/pickup-requests", headers=headers, params=params
        )

    def add_item(self, request_id, payload, headers):
        return self._request(
            "POST", f"/curbside/pickup-requests/{request_id}/items", payload, headers
        )

    def remove_item(self, request_id, item_id, headers):
        return self._request(
            "DELETE", f"/curbside/pickup-requests/{request_id}/items/{item_id}",
            headers=headers,
        )

    def list_items(self, request_id, headers):
        return self._request(
            "GET", f"/curbside/pickup-requests/{request_id}/items", headers=headers
        )

    def submit_pickup_request(self, request_id, headers):
        return self._request(
            "POST", f"/curbside/pickup-requests/{request_id}/submit", {}, headers
        )

    def schedule_pickup_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/curbside/pickup-requests/{request_id}/schedule", payload, headers
        )

    def cancel_pickup_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/curbside/pickup-requests/{request_id}/cancel", payload, headers
        )

    def complete_pickup_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/curbside/pickup-requests/{request_id}/complete", payload, headers
        )

    def refuse_pickup_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/curbside/pickup-requests/{request_id}/refuse", payload, headers
        )

    def miss_pickup_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/curbside/pickup-requests/{request_id}/miss", payload, headers
        )

    def list_request_fee_assessments(self, request_id, headers):
        return self._request(
            "GET", f"/curbside/pickup-requests/{request_id}/fee-assessments",
            headers=headers,
        )

    def list_request_notifications(self, request_id, headers):
        return self._request(
            "GET", f"/curbside/pickup-requests/{request_id}/notifications", headers=headers
        )

    def list_request_dumping_reports(self, request_id, headers):
        return self._request(
            "GET", f"/curbside/pickup-requests/{request_id}/dumping-reports",
            headers=headers,
        )

    # --- fee assessments ---
    def get_fee_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"/curbside/fee-assessments/{assessment_id}", headers=headers
        )

    def list_fee_assessments(self, headers, params=None):
        return self._request(
            "GET", "/curbside/fee-assessments", headers=headers, params=params
        )

    def settle_fee_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"/curbside/fee-assessments/{assessment_id}/settle", {}, headers
        )

    def waive_fee_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"/curbside/fee-assessments/{assessment_id}/waive", {}, headers
        )

    # --- dumping reports ---
    def create_dumping_report(self, payload, headers):
        return self._request("POST", "/curbside/dumping-reports", payload, headers)

    def get_dumping_report(self, report_id, headers):
        return self._request(
            "GET", f"/curbside/dumping-reports/{report_id}", headers=headers
        )

    def list_dumping_reports(self, headers, params=None):
        return self._request(
            "GET", "/curbside/dumping-reports", headers=headers, params=params
        )

    def determine_dumping_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/curbside/dumping-reports/{report_id}/determine", payload, headers
        )


api_client = ApiClient()
