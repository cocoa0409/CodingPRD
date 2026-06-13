"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- District -----------------------------------------------------------
    def create_district(self, payload, headers):
        return self._request("POST", "/districts", payload, headers)

    def get_district(self, district_id, headers):
        return self._request("GET", f"/districts/{district_id}", headers=headers)

    def advance_service_day(self, district_id, headers):
        return self._request(
            "POST", f"/districts/{district_id}/advance-service-day", {}, headers
        )

    # ---- Route --------------------------------------------------------------
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def change_posture(self, route_id, payload, headers):
        return self._request(
            "POST", f"/routes/{route_id}/posture", payload, headers
        )

    # ---- Stop ---------------------------------------------------------------
    def create_stop(self, payload, headers):
        return self._request("POST", "/stops", payload, headers)

    def list_stops(self, headers, params=None):
        return self._request("GET", "/stops", headers=headers, params=params)

    def get_stop(self, stop_id, headers):
        return self._request("GET", f"/stops/{stop_id}", headers=headers)

    # ---- Student ------------------------------------------------------------
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/students", headers=headers, params=params)

    # ---- RidershipApplication ----------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/ridership-applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"/ridership-applications/{application_id}", headers=headers
        )

    def list_applications(self, headers, params=None):
        return self._request(
            "GET", "/ridership-applications", headers=headers, params=params
        )

    def start_review(self, application_id, headers):
        return self._request(
            "POST",
            f"/ridership-applications/{application_id}/start-review",
            {},
            headers,
        )

    def request_changes(self, application_id, headers):
        return self._request(
            "POST",
            f"/ridership-applications/{application_id}/request-changes",
            {},
            headers,
        )

    def resubmit_application(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/ridership-applications/{application_id}/resubmit",
            payload,
            headers,
        )

    def approve_application(self, application_id, headers):
        return self._request(
            "POST",
            f"/ridership-applications/{application_id}/approve",
            {},
            headers,
        )

    def deny_application(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/ridership-applications/{application_id}/deny",
            payload,
            headers,
        )

    def withdraw_application(self, application_id, headers):
        return self._request(
            "POST",
            f"/ridership-applications/{application_id}/withdraw",
            {},
            headers,
        )

    # ---- Driver -------------------------------------------------------------
    def create_driver(self, payload, headers):
        return self._request("POST", "/drivers", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/drivers/{driver_id}", headers=headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/drivers", headers=headers, params=params)

    # ---- DriverAssignment ---------------------------------------------------
    def create_driver_assignment(self, route_id, payload, headers):
        return self._request(
            "POST", f"/routes/{route_id}/driver-assignments", payload, headers
        )

    def get_driver_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/driver-assignments/{assignment_id}", headers=headers
        )

    def list_driver_assignments(self, headers, params=None):
        return self._request(
            "GET", "/driver-assignments", headers=headers, params=params
        )

    # ---- BusTrip ------------------------------------------------------------
    def create_bus_trip(self, payload, headers):
        return self._request("POST", "/bus-trips", payload, headers)

    def get_bus_trip(self, bus_trip_id, headers):
        return self._request("GET", f"/bus-trips/{bus_trip_id}", headers=headers)

    def list_bus_trips(self, headers, params=None):
        return self._request("GET", "/bus-trips", headers=headers, params=params)

    def gps_ping(self, bus_trip_id, payload, headers):
        return self._request(
            "POST", f"/bus-trips/{bus_trip_id}/gps", payload, headers
        )

    def start_boarding(self, bus_trip_id, headers):
        return self._request(
            "POST", f"/bus-trips/{bus_trip_id}/start-boarding", {}, headers
        )

    def depart_stop(self, bus_trip_id, payload, headers):
        return self._request(
            "POST", f"/bus-trips/{bus_trip_id}/depart-stop", payload, headers
        )

    def raise_incident(self, bus_trip_id, headers):
        return self._request(
            "POST", f"/bus-trips/{bus_trip_id}/raise-incident", {}, headers
        )

    def clear_incident(self, bus_trip_id, headers):
        return self._request(
            "POST", f"/bus-trips/{bus_trip_id}/clear-incident", {}, headers
        )

    def complete_trip(self, bus_trip_id, headers):
        return self._request(
            "POST", f"/bus-trips/{bus_trip_id}/complete", {}, headers
        )

    def cancel_trip(self, bus_trip_id, headers):
        return self._request(
            "POST", f"/bus-trips/{bus_trip_id}/cancel", {}, headers
        )

    # ---- TapEvent -----------------------------------------------------------
    def record_tap(self, bus_trip_id, payload, headers):
        return self._request(
            "POST", f"/bus-trips/{bus_trip_id}/taps", payload, headers
        )

    def get_tap_event(self, tap_event_id, headers):
        return self._request(
            "GET", f"/tap-events/{tap_event_id}", headers=headers
        )

    def list_tap_events(self, headers, params=None):
        return self._request("GET", "/tap-events", headers=headers, params=params)

    # ---- ParentNotification -------------------------------------------------
    def get_parent_notification(self, notification_id, headers):
        return self._request(
            "GET", f"/parent-notifications/{notification_id}", headers=headers
        )

    def list_parent_notifications(self, headers, params=None):
        return self._request(
            "GET", "/parent-notifications", headers=headers, params=params
        )

    # ---- MissedBusReport ----------------------------------------------------
    def create_missed_bus_report(self, payload, headers):
        return self._request("POST", "/missed-bus-reports", payload, headers)

    def get_missed_bus_report(self, report_id, headers):
        return self._request(
            "GET", f"/missed-bus-reports/{report_id}", headers=headers
        )

    def list_missed_bus_reports(self, headers, params=None):
        return self._request(
            "GET", "/missed-bus-reports", headers=headers, params=params
        )

    def acknowledge_report(self, report_id, headers):
        return self._request(
            "POST", f"/missed-bus-reports/{report_id}/acknowledge", {}, headers
        )

    def resolve_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/missed-bus-reports/{report_id}/resolve", payload, headers
        )

    # ---- Test-driving clock -------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
