"""API client: one method per endpoint in PRD §4 (mounted under /band)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- BandProgram ---
    def create_program(self, payload, headers):
        return self._request("POST", "/band/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/band/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/band/programs/{program_id}", headers=headers)

    def patch_program(self, program_id, payload, headers):
        return self._request("PATCH", f"/band/programs/{program_id}", payload, headers)

    def advance_program(self, program_id, payload, headers):
        return self._request("POST", f"/band/programs/{program_id}/advance", payload, headers)

    # --- Student ---
    def create_student(self, payload, headers):
        return self._request("POST", "/band/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/band/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/band/students/{student_id}", headers=headers)

    def enroll_student(self, student_id, headers):
        return self._request("POST", f"/band/students/{student_id}/enroll", {}, headers)

    def suspend_student(self, student_id, headers):
        return self._request("POST", f"/band/students/{student_id}/suspend", {}, headers)

    def reinstate_student(self, student_id, headers):
        return self._request("POST", f"/band/students/{student_id}/reinstate", {}, headers)

    def withdraw_student(self, student_id, headers):
        return self._request("POST", f"/band/students/{student_id}/withdraw", {}, headers)

    def designate_leader(self, student_id, headers):
        return self._request("POST", f"/band/students/{student_id}/designate-leader", {}, headers)

    def get_student_ledger(self, student_id, headers, params=None):
        return self._request("GET", f"/band/students/{student_id}/ledger", headers=headers, params=params)

    # --- Instrument ---
    def create_instrument(self, payload, headers):
        return self._request("POST", "/band/instruments", payload, headers)

    def list_instruments(self, headers, params=None):
        return self._request("GET", "/band/instruments", headers=headers, params=params)

    def get_instrument(self, instrument_id, headers):
        return self._request("GET", f"/band/instruments/{instrument_id}", headers=headers)

    def retire_instrument(self, instrument_id, headers):
        return self._request("POST", f"/band/instruments/{instrument_id}/retire", {}, headers)

    def complete_maintenance(self, instrument_id, payload, headers):
        return self._request("POST", f"/band/instruments/{instrument_id}/complete-maintenance", payload, headers)

    # --- InstrumentAssignment ---
    def create_instrument_assignment(self, payload, headers):
        return self._request("POST", "/band/instrument-assignments", payload, headers)

    def list_instrument_assignments(self, headers, params=None):
        return self._request("GET", "/band/instrument-assignments", headers=headers, params=params)

    def get_instrument_assignment(self, assignment_id, headers):
        return self._request("GET", f"/band/instrument-assignments/{assignment_id}", headers=headers)

    def return_instrument_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/band/instrument-assignments/{assignment_id}/return", payload, headers)

    def renew_instrument_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/band/instrument-assignments/{assignment_id}/renew", payload, headers)

    # --- Uniform ---
    def create_uniform(self, payload, headers):
        return self._request("POST", "/band/uniforms", payload, headers)

    def list_uniforms(self, headers, params=None):
        return self._request("GET", "/band/uniforms", headers=headers, params=params)

    def get_uniform(self, uniform_id, headers):
        return self._request("GET", f"/band/uniforms/{uniform_id}", headers=headers)

    def retire_uniform(self, uniform_id, headers):
        return self._request("POST", f"/band/uniforms/{uniform_id}/retire", {}, headers)

    # --- UniformAssignment ---
    def create_uniform_assignment(self, payload, headers):
        return self._request("POST", "/band/uniform-assignments", payload, headers)

    def list_uniform_assignments(self, headers, params=None):
        return self._request("GET", "/band/uniform-assignments", headers=headers, params=params)

    def get_uniform_assignment(self, assignment_id, headers):
        return self._request("GET", f"/band/uniform-assignments/{assignment_id}", headers=headers)

    def return_uniform_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/band/uniform-assignments/{assignment_id}/return", payload, headers)

    # --- CleaningBatch ---
    def create_cleaning_batch(self, payload, headers):
        return self._request("POST", "/band/cleaning-batches", payload, headers)

    def list_cleaning_batches(self, headers, params=None):
        return self._request("GET", "/band/cleaning-batches", headers=headers, params=params)

    def get_cleaning_batch(self, batch_id, headers):
        return self._request("GET", f"/band/cleaning-batches/{batch_id}", headers=headers)

    def add_cleaning_batch_item(self, batch_id, payload, headers):
        return self._request("POST", f"/band/cleaning-batches/{batch_id}/items", payload, headers)

    def send_cleaning_batch(self, batch_id, headers):
        return self._request("POST", f"/band/cleaning-batches/{batch_id}/send", {}, headers)

    def receive_cleaning_batch(self, batch_id, headers):
        return self._request("POST", f"/band/cleaning-batches/{batch_id}/receive", {}, headers)

    # --- MusicArrangement ---
    def create_arrangement(self, payload, headers):
        return self._request("POST", "/band/arrangements", payload, headers)

    def list_arrangements(self, headers, params=None):
        return self._request("GET", "/band/arrangements", headers=headers, params=params)

    def get_arrangement(self, arrangement_id, headers):
        return self._request("GET", f"/band/arrangements/{arrangement_id}", headers=headers)

    def approve_arrangement(self, arrangement_id, headers):
        return self._request("POST", f"/band/arrangements/{arrangement_id}/approve", {}, headers)

    def reject_arrangement(self, arrangement_id, headers):
        return self._request("POST", f"/band/arrangements/{arrangement_id}/reject", {}, headers)

    def purchase_arrangement(self, arrangement_id, headers):
        return self._request("POST", f"/band/arrangements/{arrangement_id}/purchase", {}, headers)

    # --- Event ---
    def create_event(self, payload, headers):
        return self._request("POST", "/band/events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/band/events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/band/events/{event_id}", headers=headers)

    def weather_watch_event(self, event_id, headers):
        return self._request("POST", f"/band/events/{event_id}/weather-watch", {}, headers)

    def relocate_event_indoor(self, event_id, payload, headers):
        return self._request("POST", f"/band/events/{event_id}/relocate-indoor", payload, headers)

    def postpone_event(self, event_id, payload, headers):
        return self._request("POST", f"/band/events/{event_id}/postpone", payload, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/band/events/{event_id}/cancel", {}, headers)

    def complete_event(self, event_id, headers):
        return self._request("POST", f"/band/events/{event_id}/complete", {}, headers)

    # --- Trip ---
    def create_trip(self, payload, headers):
        return self._request("POST", "/band/trips", payload, headers)

    def list_trips(self, headers, params=None):
        return self._request("GET", "/band/trips", headers=headers, params=params)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/band/trips/{trip_id}", headers=headers)

    def open_trip_roster(self, trip_id, headers):
        return self._request("POST", f"/band/trips/{trip_id}/open-roster", {}, headers)

    def lock_trip_roster(self, trip_id, headers):
        return self._request("POST", f"/band/trips/{trip_id}/lock-roster", {}, headers)

    def finalize_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/band/trips/{trip_id}/finalize", payload, headers)

    def cancel_trip(self, trip_id, headers):
        return self._request("POST", f"/band/trips/{trip_id}/cancel", {}, headers)

    def complete_trip(self, trip_id, headers):
        return self._request("POST", f"/band/trips/{trip_id}/complete", {}, headers)

    # --- TripEnrollment ---
    def create_trip_enrollment(self, payload, headers):
        return self._request("POST", "/band/trip-enrollments", payload, headers)

    def list_trip_enrollments(self, headers, params=None):
        return self._request("GET", "/band/trip-enrollments", headers=headers, params=params)

    def get_trip_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/band/trip-enrollments/{enrollment_id}", headers=headers)

    def confirm_trip_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/band/trip-enrollments/{enrollment_id}/confirm", {}, headers)

    def excuse_trip_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/band/trip-enrollments/{enrollment_id}/excuse", {}, headers)

    def mark_trip_attendance(self, enrollment_id, payload, headers):
        return self._request("POST", f"/band/trip-enrollments/{enrollment_id}/mark-attendance", payload, headers)

    # --- Payment ---
    def create_payment(self, payload, headers):
        return self._request("POST", "/band/payments", payload, headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/band/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/band/payments/{payment_id}", headers=headers)

    # --- Fundraiser ---
    def create_fundraiser(self, payload, headers):
        return self._request("POST", "/band/fundraisers", payload, headers)

    def list_fundraisers(self, headers, params=None):
        return self._request("GET", "/band/fundraisers", headers=headers, params=params)

    def get_fundraiser(self, fundraiser_id, headers):
        return self._request("GET", f"/band/fundraisers/{fundraiser_id}", headers=headers)

    def close_fundraiser(self, fundraiser_id, payload, headers):
        return self._request("POST", f"/band/fundraisers/{fundraiser_id}/close", payload, headers)

    # --- Audition / AuditionEntry / ChairPlacement ---
    def create_audition(self, payload, headers):
        return self._request("POST", "/band/auditions", payload, headers)

    def list_auditions(self, headers, params=None):
        return self._request("GET", "/band/auditions", headers=headers, params=params)

    def get_audition(self, audition_id, headers):
        return self._request("GET", f"/band/auditions/{audition_id}", headers=headers)

    def finalize_audition_scores(self, audition_id, headers):
        return self._request("POST", f"/band/auditions/{audition_id}/finalize-scores", {}, headers)

    def publish_audition_placements(self, audition_id, payload, headers):
        return self._request("POST", f"/band/auditions/{audition_id}/placements", payload, headers)

    def challenge_audition(self, audition_id, payload, headers):
        return self._request("POST", f"/band/auditions/{audition_id}/challenge", payload, headers)

    def create_audition_entry(self, payload, headers):
        return self._request("POST", "/band/audition-entries", payload, headers)

    def list_audition_entries(self, headers, params=None):
        return self._request("GET", "/band/audition-entries", headers=headers, params=params)

    def get_audition_entry(self, entry_id, headers):
        return self._request("GET", f"/band/audition-entries/{entry_id}", headers=headers)

    def submit_judge_scores(self, entry_id, payload, headers):
        return self._request("POST", f"/band/audition-entries/{entry_id}/scores", payload, headers)

    def list_chair_placements(self, headers, params=None):
        return self._request("GET", "/band/chair-placements", headers=headers, params=params)

    def get_chair_placement(self, placement_id, headers):
        return self._request("GET", f"/band/chair-placements/{placement_id}", headers=headers)

    # --- TruckCharter / TruckLoad ---
    def create_truck_charter(self, payload, headers):
        return self._request("POST", "/band/truck-charters", payload, headers)

    def list_truck_charters(self, headers, params=None):
        return self._request("GET", "/band/truck-charters", headers=headers, params=params)

    def get_truck_charter(self, charter_id, headers):
        return self._request("GET", f"/band/truck-charters/{charter_id}", headers=headers)

    def add_truck_load(self, charter_id, payload, headers):
        return self._request("POST", f"/band/truck-charters/{charter_id}/loads", payload, headers)

    def list_truck_loads(self, headers, params=None):
        return self._request("GET", "/band/truck-loads", headers=headers, params=params)

    def get_truck_load(self, load_id, headers):
        return self._request("GET", f"/band/truck-loads/{load_id}", headers=headers)

    def depart_truck_charter(self, charter_id, headers):
        return self._request("POST", f"/band/truck-charters/{charter_id}/depart", {}, headers)

    def return_truck_charter(self, charter_id, headers):
        return self._request("POST", f"/band/truck-charters/{charter_id}/return", {}, headers)

    def cancel_truck_charter(self, charter_id, headers):
        return self._request("POST", f"/band/truck-charters/{charter_id}/cancel", {}, headers)

    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/band/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
