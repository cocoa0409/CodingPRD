"""HTTP client with one method per endpoint declared in PRD section 4."""

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


class ApiClient(GenericApiClient):
    """Thin per-endpoint wrapper; every method returns the raw response."""

    # --- Administrative clock (PRD 2.4) -------------------------------------

    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", CLOCK_PATH, {"current_utc": current_utc}, headers
        )

    # --- Courses ------------------------------------------------------------

    def create_course(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/courses", payload, headers)

    def get_course(self, course_id, headers):
        return self._request("GET", f"{API_PREFIX}/courses/{course_id}", None, headers)

    def daily_open(self, course_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/courses/{course_id}/daily-open", payload or {}, headers
        )

    def list_course_facilitators(self, course_id, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/courses/{course_id}/facilitators", params, headers
        )

    def list_course_weather_observations(self, course_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/courses/{course_id}/weather-observations",
            params,
            headers,
        )

    # --- Elements -----------------------------------------------------------

    def create_element(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/elements", payload, headers)

    def get_element(self, element_id, headers):
        return self._request("GET", f"{API_PREFIX}/elements/{element_id}", None, headers)

    def list_elements(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/elements", params, headers)

    def return_element_to_service(self, element_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/elements/{element_id}/return-to-service", payload, headers
        )

    def retire_element(self, element_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/elements/{element_id}/retire", payload, headers
        )

    # --- Professional inspections -------------------------------------------

    def create_professional_inspection(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/professional-inspections", payload, headers
        )

    def get_professional_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/professional-inspections/{inspection_id}", None, headers
        )

    def list_professional_inspections(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/professional-inspections", params, headers
        )

    def file_professional_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/professional-inspections/{inspection_id}/file",
            payload,
            headers,
        )

    def dispose_professional_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/professional-inspections/{inspection_id}/dispose",
            payload or {},
            headers,
        )

    # --- Operational inspection logs -----------------------------------------

    def create_operational_log(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/operational-logs", payload, headers)

    def get_operational_log(self, log_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/operational-logs/{log_id}", None, headers
        )

    def list_operational_logs(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/operational-logs", params, headers)

    # --- Facilitators and training -------------------------------------------

    def create_facilitator(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/facilitators", payload, headers)

    def get_facilitator(self, facilitator_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/facilitators/{facilitator_id}", None, headers
        )

    def list_facilitators(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/facilitators", params, headers)

    def list_facilitator_training_records(self, facilitator_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/facilitators/{facilitator_id}/training-records",
            params,
            headers,
        )

    def list_facilitator_block_assignments(self, facilitator_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/facilitators/{facilitator_id}/block-assignments",
            params,
            headers,
        )

    def create_training_record(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/training-records", payload, headers)

    def get_training_record(self, training_record_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/training-records/{training_record_id}", None, headers
        )

    def list_training_records(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/training-records", params, headers)

    # --- Block assignments ---------------------------------------------------

    def get_block_assignment(self, block_assignment_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/block-assignments/{block_assignment_id}", None, headers
        )

    def list_block_assignments(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/block-assignments", params, headers)

    # --- Group clients -------------------------------------------------------

    def create_group_client(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/group-clients", payload, headers)

    def get_group_client(self, group_client_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/group-clients/{group_client_id}", None, headers
        )

    def create_payment(self, group_client_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/group-clients/{group_client_id}/payments", payload, headers
        )

    # --- Bookings ------------------------------------------------------------

    def create_booking(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"{API_PREFIX}/bookings/{booking_id}", None, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/bookings", params, headers)

    def quote_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/bookings/{booking_id}/quote", payload, headers
        )

    def confirm_booking(self, booking_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/bookings/{booking_id}/confirm", payload or {}, headers
        )

    def cancel_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/bookings/{booking_id}/cancel", payload, headers
        )

    # --- Participants --------------------------------------------------------

    def create_participant(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/participants/{participant_id}", None, headers
        )

    def list_participants(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/participants", params, headers)

    def submit_screening_packet(self, participant_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/participants/{participant_id}/screening-packet",
            payload,
            headers,
        )

    def grant_medical_clearance(self, participant_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/participants/{participant_id}/medical-clearance",
            payload or {},
            headers,
        )

    # --- Program blocks ------------------------------------------------------

    def create_program_block(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/program-blocks", payload, headers)

    def get_program_block(self, program_block_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/program-blocks/{program_block_id}", None, headers
        )

    def list_program_blocks(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/program-blocks", params, headers)

    def create_block_assignment(self, program_block_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/program-blocks/{program_block_id}/block-assignments",
            payload,
            headers,
        )

    def list_block_assignments_for_block(self, program_block_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/program-blocks/{program_block_id}/block-assignments",
            params,
            headers,
        )

    def start_program_block(self, program_block_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/program-blocks/{program_block_id}/start", payload or {}, headers
        )

    def complete_program_block(self, program_block_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/program-blocks/{program_block_id}/complete",
            payload or {},
            headers,
        )

    # --- Belay equipment -----------------------------------------------------

    def create_belay_equipment(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/belay-equipment", payload, headers)

    def get_belay_equipment(self, equipment_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/belay-equipment/{equipment_id}", None, headers
        )

    def list_belay_equipment(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/belay-equipment", params, headers)

    def log_equipment_usage(self, equipment_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/belay-equipment/{equipment_id}/log-usage", payload, headers
        )

    # --- Weather observations -------------------------------------------------

    def create_weather_observation(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/weather-observations", payload, headers
        )

    def get_weather_observation(self, observation_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/weather-observations/{observation_id}", None, headers
        )

    def list_weather_observations(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/weather-observations", params, headers)

    # --- Incidents ------------------------------------------------------------

    def create_incident(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"{API_PREFIX}/incidents/{incident_id}", None, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/incidents", params, headers)

    def review_incident(self, incident_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/incidents/{incident_id}/review", payload or {}, headers
        )

    def close_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/incidents/{incident_id}/close", payload or {}, headers
        )
