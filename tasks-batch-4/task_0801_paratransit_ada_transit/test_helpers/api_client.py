"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Service zones ---
    def create_service_zone(self, payload, headers):
        return self._request("POST", "/service-zones", payload, headers)

    # --- Riders ---
    def create_rider(self, payload, headers):
        return self._request("POST", "/riders", payload, headers)

    def get_rider(self, rider_id, headers):
        return self._request("GET", f"/riders/{rider_id}", headers=headers)

    # --- Eligibility applications ---
    def create_application(self, payload, headers):
        return self._request("POST", "/eligibility-applications", payload, headers)

    def get_application(self, app_id, headers):
        return self._request("GET", f"/eligibility-applications/{app_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/eligibility-applications", headers=headers, params=params)

    def certify_application(self, app_id, headers):
        return self._request("POST", f"/eligibility-applications/{app_id}/certify", {}, headers)

    def deny_application(self, app_id, headers):
        return self._request("POST", f"/eligibility-applications/{app_id}/deny", {}, headers)

    def appeal_application(self, app_id, headers):
        return self._request("POST", f"/eligibility-applications/{app_id}/appeal", {}, headers)

    # --- Functional assessments ---
    def create_assessment(self, payload, headers):
        return self._request("POST", "/functional-assessments", payload, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/functional-assessments/{assessment_id}", headers=headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/functional-assessments", headers=headers, params=params)

    def complete_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/functional-assessments/{assessment_id}/complete", payload, headers)

    # --- Trip reservations ---
    def create_trip(self, payload, headers):
        return self._request("POST", "/trip-reservations", payload, headers)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/trip-reservations/{trip_id}", headers=headers)

    def list_trips(self, headers, params=None):
        return self._request("GET", "/trip-reservations", headers=headers, params=params)

    def offer_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/trip-reservations/{trip_id}/offer", payload, headers)

    def counter_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/trip-reservations/{trip_id}/counter", payload, headers)

    def accept_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/trip-reservations/{trip_id}/accept", payload, headers)

    def cancel_trip(self, trip_id, headers):
        return self._request("POST", f"/trip-reservations/{trip_id}/cancel", {}, headers)

    def pickup_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/trip-reservations/{trip_id}/pickup", payload, headers)

    def dropoff_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/trip-reservations/{trip_id}/dropoff", payload, headers)

    def no_show_trip(self, trip_id, headers):
        return self._request("POST", f"/trip-reservations/{trip_id}/no-show", {}, headers)

    def list_offers(self, trip_id, headers, params=None):
        return self._request("GET", f"/trip-reservations/{trip_id}/offers", headers=headers, params=params)

    # --- Subscription trips ---
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscription-trips", payload, headers)

    def get_subscription(self, sub_id, headers):
        return self._request("GET", f"/subscription-trips/{sub_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscription-trips", headers=headers, params=params)

    def instantiate_subscription(self, sub_id, payload, headers):
        return self._request("POST", f"/subscription-trips/{sub_id}/instantiate", payload, headers)

    # --- Vehicle runs ---
    def create_run(self, payload, headers):
        return self._request("POST", "/vehicle-runs", payload, headers)

    def get_run(self, run_id, headers):
        return self._request("GET", f"/vehicle-runs/{run_id}", headers=headers)

    def list_runs(self, headers, params=None):
        return self._request("GET", "/vehicle-runs", headers=headers, params=params)

    def get_manifest(self, run_id, headers, params=None):
        return self._request("GET", f"/vehicle-runs/{run_id}/manifest", headers=headers, params=params)

    def open_run(self, run_id, headers):
        return self._request("POST", f"/vehicle-runs/{run_id}/open", {}, headers)

    def dispatch_run(self, run_id, headers):
        return self._request("POST", f"/vehicle-runs/{run_id}/dispatch", {}, headers)

    # --- Penalty events ---
    def get_penalty(self, penalty_id, headers):
        return self._request("GET", f"/penalty-events/{penalty_id}", headers=headers)

    def list_penalties(self, headers, params=None):
        return self._request("GET", "/penalty-events", headers=headers, params=params)

    def waive_penalty(self, penalty_id, headers):
        return self._request("POST", f"/penalty-events/{penalty_id}/waive", {}, headers)

    # --- Reports ---
    def on_time_performance(self, headers, params=None):
        return self._request("GET", "/reports/on-time-performance", headers=headers, params=params)


api_client = ApiClient()
