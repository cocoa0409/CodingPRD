"""API client: one method per endpoint the PRD declares (§4).

"Endpoints are mounted at the server root; there is no version or service prefix
in front of the paths below."  Every method returns the raw response so a test can
assert on the HTTP status as well as on the envelope.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # The logical clock (PRD §2.5)
    # ------------------------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------------
    # Courses (PRD §3.1)
    # ------------------------------------------------------------------
    def create_course(self, payload, headers):
        return self._request("POST", "/courses", payload, headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/courses", headers=headers, params=params)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/courses/{course_id}", headers=headers)

    def revise_water_allocation(self, course_id, payload, headers):
        return self._request(
            "PATCH", f"/courses/{course_id}/water-allocation", payload, headers
        )

    def get_water_assessment(self, course_id, headers):
        return self._request(
            "GET", f"/courses/{course_id}/water-assessment", headers=headers
        )

    def list_course_weather_events(self, course_id, headers, params=None):
        return self._request(
            "GET", f"/courses/{course_id}/weather-events", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Turf areas (PRD §3.2)
    # ------------------------------------------------------------------
    def create_turf_area(self, payload, headers):
        return self._request("POST", "/turf-areas", payload, headers)

    def list_turf_areas(self, headers, params=None):
        return self._request("GET", "/turf-areas", headers=headers, params=params)

    def get_turf_area(self, turf_area_id, headers):
        return self._request("GET", f"/turf-areas/{turf_area_id}", headers=headers)

    def list_turf_area_playability_readings(self, turf_area_id, headers, params=None):
        return self._request(
            "GET",
            f"/turf-areas/{turf_area_id}/playability-readings",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Agronomic plans (PRD §3.3)
    # ------------------------------------------------------------------
    def create_plan(self, payload, headers):
        return self._request("POST", "/agronomic-plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/agronomic-plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/agronomic-plans/{plan_id}", headers=headers)

    def submit_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"/agronomic-plans/{plan_id}/submit", payload or {}, headers
        )

    def return_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/agronomic-plans/{plan_id}/return", payload or {}, headers
        )

    def approve_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/agronomic-plans/{plan_id}/approve", payload, headers
        )

    # ------------------------------------------------------------------
    # Plan tasks (PRD §3.3)
    # ------------------------------------------------------------------
    def create_plan_task(self, payload, headers):
        return self._request("POST", "/plan-tasks", payload, headers)

    def list_plan_tasks(self, headers, params=None):
        return self._request("GET", "/plan-tasks", headers=headers, params=params)

    def get_plan_task(self, task_id, headers):
        return self._request("GET", f"/plan-tasks/{task_id}", headers=headers)

    def schedule_plan_task(self, task_id, payload, headers):
        return self._request(
            "POST", f"/plan-tasks/{task_id}/schedule", payload, headers
        )

    # ------------------------------------------------------------------
    # Applicators and product labels (PRD §3.4)
    # ------------------------------------------------------------------
    def create_applicator(self, payload, headers):
        return self._request("POST", "/applicators", payload, headers)

    def list_applicators(self, headers, params=None):
        return self._request("GET", "/applicators", headers=headers, params=params)

    def get_applicator(self, applicator_id, headers):
        return self._request("GET", f"/applicators/{applicator_id}", headers=headers)

    def create_pesticide_product(self, payload, headers):
        return self._request("POST", "/pesticide-products", payload, headers)

    def list_pesticide_products(self, headers, params=None):
        return self._request(
            "GET", "/pesticide-products", headers=headers, params=params
        )

    def get_pesticide_product(self, product_id, headers):
        return self._request(
            "GET", f"/pesticide-products/{product_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Application records (PRD §3.4)
    # ------------------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def verify_application(self, application_id, headers, payload=None):
        return self._request(
            "POST", f"/applications/{application_id}/verify", payload or {}, headers
        )

    def void_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/void", payload, headers
        )

    def release_application_posting(self, application_id, headers, payload=None):
        return self._request(
            "POST",
            f"/applications/{application_id}/release-posting",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Pump stations and irrigation runs (PRD §3.5)
    # ------------------------------------------------------------------
    def create_pump_station(self, payload, headers):
        return self._request("POST", "/pump-stations", payload, headers)

    def list_pump_stations(self, headers, params=None):
        return self._request("GET", "/pump-stations", headers=headers, params=params)

    def get_pump_station(self, pump_station_id, headers):
        return self._request(
            "GET", f"/pump-stations/{pump_station_id}", headers=headers
        )

    def set_pump_station_status(self, pump_station_id, status, headers):
        return self._request(
            "PATCH",
            f"/pump-stations/{pump_station_id}/status",
            {"status": status},
            headers,
        )

    def create_irrigation_run(self, payload, headers):
        return self._request("POST", "/irrigation-runs", payload, headers)

    def list_irrigation_runs(self, headers, params=None):
        return self._request("GET", "/irrigation-runs", headers=headers, params=params)

    def get_irrigation_run(self, run_id, headers):
        return self._request("GET", f"/irrigation-runs/{run_id}", headers=headers)

    def complete_irrigation_run(self, run_id, headers, payload=None):
        return self._request(
            "POST", f"/irrigation-runs/{run_id}/complete", payload or {}, headers
        )

    def reverse_irrigation_run(self, run_id, headers, payload=None):
        return self._request(
            "POST", f"/irrigation-runs/{run_id}/reverse", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Crew maintenance windows (PRD §3.6)
    # ------------------------------------------------------------------
    def create_maintenance_window(self, payload, headers):
        return self._request("POST", "/maintenance-windows", payload, headers)

    def list_maintenance_windows(self, headers, params=None):
        return self._request(
            "GET", "/maintenance-windows", headers=headers, params=params
        )

    def get_maintenance_window(self, window_id, headers):
        return self._request(
            "GET", f"/maintenance-windows/{window_id}", headers=headers
        )

    def start_maintenance_window(self, window_id, headers, payload=None):
        return self._request(
            "POST", f"/maintenance-windows/{window_id}/start", payload or {}, headers
        )

    def complete_maintenance_window(self, window_id, headers, payload=None):
        return self._request(
            "POST", f"/maintenance-windows/{window_id}/complete", payload or {}, headers
        )

    def reschedule_maintenance_window(self, window_id, payload, headers):
        return self._request(
            "POST", f"/maintenance-windows/{window_id}/reschedule", payload, headers
        )

    # ------------------------------------------------------------------
    # Play events and playability readings (PRD §3.7)
    # ------------------------------------------------------------------
    def create_play_event(self, payload, headers):
        return self._request("POST", "/play-events", payload, headers)

    def list_play_events(self, headers, params=None):
        return self._request("GET", "/play-events", headers=headers, params=params)

    def get_play_event(self, event_id, headers):
        return self._request("GET", f"/play-events/{event_id}", headers=headers)

    def certify_conditions(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/play-events/{event_id}/certify-conditions", payload or {}, headers
        )

    def create_playability_reading(self, payload, headers):
        return self._request("POST", "/playability-readings", payload, headers)

    # ------------------------------------------------------------------
    # The equipment fleet (PRD §3.8)
    # ------------------------------------------------------------------
    def create_equipment_unit(self, payload, headers):
        return self._request("POST", "/equipment-units", payload, headers)

    def list_equipment_units(self, headers, params=None):
        return self._request("GET", "/equipment-units", headers=headers, params=params)

    def get_equipment_unit(self, unit_id, headers):
        return self._request("GET", f"/equipment-units/{unit_id}", headers=headers)

    def log_equipment_hours(self, unit_id, hours_added, headers):
        return self._request(
            "POST",
            f"/equipment-units/{unit_id}/log-hours",
            {"hours_added": hours_added},
            headers,
        )

    def service_equipment_unit(self, unit_id, headers, payload=None):
        return self._request(
            "POST", f"/equipment-units/{unit_id}/service", payload or {}, headers
        )

    def retire_equipment_unit(self, unit_id, headers, payload=None):
        return self._request(
            "POST", f"/equipment-units/{unit_id}/retire", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Weather (PRD §3.9)
    # ------------------------------------------------------------------
    def create_weather_event(self, payload, headers):
        return self._request("POST", "/weather-events", payload, headers)

    def clear_weather_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/weather-events/{event_id}/clear", payload or {}, headers
        )


api_client = ApiClient()

