"""API client: one method per endpoint defined in the PRD.

All paths already carry the `/records-office` prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/records-office"


class ApiClient(GenericApiClient):
    # --- Logical clock and compliance sweep ------------------------------

    def set_current_utc(self, payload, headers):
        return self._request("POST", f"{BASE}/_clock/set_current_utc", payload, headers)

    def run_compliance_sweep(self, headers, payload=None):
        return self._request("POST", f"{BASE}/compliance-sweeps", payload or {}, headers)

    # --- Statutory reference data ---------------------------------------

    def create_state_rule(self, payload, headers):
        return self._request("POST", f"{BASE}/state-rules", payload, headers)

    def list_state_rules(self, headers, params=None):
        return self._request("GET", f"{BASE}/state-rules", headers=headers, params=params)

    def get_state_rule(self, state_code, headers):
        return self._request("GET", f"{BASE}/state-rules/{state_code}", headers=headers)

    def create_district(self, payload, headers):
        return self._request("POST", f"{BASE}/districts", payload, headers)

    def list_districts(self, headers, params=None):
        return self._request("GET", f"{BASE}/districts", headers=headers, params=params)

    def get_district(self, district_id, headers):
        return self._request("GET", f"{BASE}/districts/{district_id}", headers=headers)

    # --- Scheduling resources -------------------------------------------

    def create_inspection_room(self, payload, headers):
        return self._request("POST", f"{BASE}/inspection-rooms", payload, headers)

    def list_inspection_rooms(self, headers, params=None):
        return self._request("GET", f"{BASE}/inspection-rooms", headers=headers, params=params)

    def get_inspection_room(self, room_id, headers):
        return self._request("GET", f"{BASE}/inspection-rooms/{room_id}", headers=headers)

    def update_inspection_room(self, room_id, payload, headers):
        return self._request("PATCH", f"{BASE}/inspection-rooms/{room_id}", payload, headers)

    def create_hearing_officer(self, payload, headers):
        return self._request("POST", f"{BASE}/hearing-officers", payload, headers)

    def list_hearing_officers(self, headers, params=None):
        return self._request("GET", f"{BASE}/hearing-officers", headers=headers, params=params)

    def get_hearing_officer(self, officer_id, headers):
        return self._request("GET", f"{BASE}/hearing-officers/{officer_id}", headers=headers)

    def update_hearing_officer(self, officer_id, payload, headers):
        return self._request("PATCH", f"{BASE}/hearing-officers/{officer_id}", payload, headers)

    # --- Students, directory information, disclosure log ------------------

    def create_student(self, payload, headers):
        return self._request("POST", f"{BASE}/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", f"{BASE}/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"{BASE}/students/{student_id}", headers=headers)

    def update_directory_optout(self, student_id, payload, headers):
        return self._request(
            "PATCH", f"{BASE}/students/{student_id}/directory-optout", payload, headers
        )

    def create_directory_disclosure(self, student_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/students/{student_id}/directory-disclosures", payload, headers
        )

    def list_disclosure_log(self, student_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/students/{student_id}/disclosure-log", headers=headers, params=params
        )

    # --- Withdrawals -----------------------------------------------------

    def create_withdrawal(self, student_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/students/{student_id}/withdrawals", payload, headers
        )

    def list_student_withdrawals(self, student_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/students/{student_id}/withdrawals", headers=headers, params=params
        )

    def get_withdrawal(self, withdrawal_id, headers):
        return self._request("GET", f"{BASE}/withdrawals/{withdrawal_id}", headers=headers)

    def place_withdrawal_hold(self, withdrawal_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/withdrawals/{withdrawal_id}/holds", payload, headers
        )

    def release_withdrawal_hold(self, withdrawal_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/withdrawals/{withdrawal_id}/hold-releases", payload, headers
        )

    def complete_withdrawal(self, withdrawal_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/withdrawals/{withdrawal_id}/complete", payload or {}, headers
        )

    # --- Cumulative files, components, retention schedules ---------------

    def list_student_cumulative_files(self, student_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/students/{student_id}/cumulative-files", headers=headers, params=params
        )

    def get_cumulative_file(self, file_id, headers):
        return self._request("GET", f"{BASE}/cumulative-files/{file_id}", headers=headers)

    def list_file_components(self, file_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/cumulative-files/{file_id}/components", headers=headers, params=params
        )

    def update_file_component(self, file_id, component_id, payload, headers):
        return self._request(
            "PATCH",
            f"{BASE}/cumulative-files/{file_id}/components/{component_id}",
            payload,
            headers,
        )

    def list_file_retention_schedules(self, file_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/cumulative-files/{file_id}/retention-schedules",
            headers=headers,
            params=params,
        )

    # --- Discipline incidents -------------------------------------------

    def create_discipline_incident(self, student_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/students/{student_id}/discipline-incidents", payload, headers
        )

    def list_student_discipline_incidents(self, student_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/students/{student_id}/discipline-incidents",
            headers=headers,
            params=params,
        )

    def get_discipline_incident(self, incident_id, headers):
        return self._request(
            "GET", f"{BASE}/discipline-incidents/{incident_id}", headers=headers
        )

    # --- Inter-district records requests --------------------------------

    def create_records_request(self, payload, headers):
        return self._request("POST", f"{BASE}/records-requests", payload, headers)

    def list_records_requests(self, headers, params=None):
        return self._request("GET", f"{BASE}/records-requests", headers=headers, params=params)

    def get_records_request(self, request_id, headers):
        return self._request("GET", f"{BASE}/records-requests/{request_id}", headers=headers)

    def validate_records_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/records-requests/{request_id}/validate", payload, headers
        )

    def mark_ready_records_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/records-requests/{request_id}/mark-ready", payload, headers
        )

    def release_records_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/records-requests/{request_id}/release", payload, headers
        )

    def deny_records_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/records-requests/{request_id}/deny", payload, headers
        )

    # --- Inspection requests, appointments, fees -------------------------

    def create_inspection_request(self, student_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/students/{student_id}/inspection-requests", payload, headers
        )

    def list_student_inspection_requests(self, student_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/students/{student_id}/inspection-requests",
            headers=headers,
            params=params,
        )

    def get_inspection_request(self, inspection_request_id, headers):
        return self._request(
            "GET", f"{BASE}/inspection-requests/{inspection_request_id}", headers=headers
        )

    def create_review_appointment(self, inspection_request_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/inspection-requests/{inspection_request_id}/appointments",
            payload,
            headers,
        )

    def list_review_appointments(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/review-appointments", headers=headers, params=params
        )

    def get_review_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"{BASE}/review-appointments/{appointment_id}", headers=headers
        )

    def record_attendance(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/review-appointments/{appointment_id}/attendance", payload, headers
        )

    def create_fee_transaction(self, inspection_request_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/inspection-requests/{inspection_request_id}/fee-payments",
            payload,
            headers,
        )

    # --- Amendment challenges, hearings, statements ----------------------

    def create_amendment_request(self, student_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/students/{student_id}/amendment-requests", payload, headers
        )

    def list_amendment_requests(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/amendment-requests", headers=headers, params=params
        )

    def get_amendment_request(self, amendment_request_id, headers):
        return self._request(
            "GET", f"{BASE}/amendment-requests/{amendment_request_id}", headers=headers
        )

    def create_amendment_decision(self, amendment_request_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/amendment-requests/{amendment_request_id}/decisions",
            payload,
            headers,
        )

    def create_hearing_request(self, amendment_request_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/amendment-requests/{amendment_request_id}/hearing-requests",
            payload or {},
            headers,
        )

    def create_hearing_schedule(self, amendment_request_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/amendment-requests/{amendment_request_id}/hearing-schedules",
            payload,
            headers,
        )

    def create_statement_of_disagreement(self, amendment_request_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/amendment-requests/{amendment_request_id}/statements",
            payload,
            headers,
        )

    # --- Legal demands ---------------------------------------------------

    def create_legal_demand(self, student_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/students/{student_id}/legal-demands", payload, headers
        )

    def list_student_legal_demands(self, student_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/students/{student_id}/legal-demands", headers=headers, params=params
        )

    def get_legal_demand(self, demand_id, headers):
        return self._request("GET", f"{BASE}/legal-demands/{demand_id}", headers=headers)

    def create_demand_notification(self, demand_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/legal-demands/{demand_id}/notifications", payload, headers
        )

    def create_demand_production(self, demand_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/legal-demands/{demand_id}/production", payload, headers
        )

    # --- Retention schedules and certified destruction -------------------

    def get_retention_schedule(self, schedule_id, headers):
        return self._request(
            "GET", f"{BASE}/retention-schedules/{schedule_id}", headers=headers
        )

    def execute_destruction(self, schedule_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/retention-schedules/{schedule_id}/destruction", payload, headers
        )


api_client = ApiClient()
