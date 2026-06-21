"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Practice clock (test driving, §3.1) ----
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set", {"current_utc": current_utc}, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)

    # ---- Provider ----
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/providers", headers=headers, params=params)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    def suspend_provider(self, provider_id, headers):
        return self._request("POST", f"/providers/{provider_id}/suspend", {}, headers)

    # ---- TreatmentRoom ----
    def create_room(self, payload, headers):
        return self._request("POST", "/treatment-rooms", payload, headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/treatment-rooms", headers=headers, params=params)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/treatment-rooms/{room_id}", headers=headers)

    def close_room(self, room_id, headers):
        return self._request("POST", f"/treatment-rooms/{room_id}/close", {}, headers)

    # ---- FeeSchedule ----
    def create_fee_schedule(self, payload, headers):
        return self._request("POST", "/fee-schedules", payload, headers)

    def list_fee_schedules(self, headers, params=None):
        return self._request("GET", "/fee-schedules", headers=headers, params=params)

    # ---- WellnessPlan ----
    def create_wellness_plan(self, payload, headers):
        return self._request("POST", "/wellness-plans", payload, headers)

    def list_wellness_plans(self, headers, params=None):
        return self._request("GET", "/wellness-plans", headers=headers, params=params)

    # ---- Patient ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def post_payment(self, patient_id, payload, headers):
        return self._request("POST", f"/patients/{patient_id}/payments", payload, headers)

    def list_patient_ledger_entries(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/patients/{patient_id}/ledger-entries", headers=headers, params=params
        )

    # ---- InsurancePolicy ----
    def create_insurance_policy(self, patient_id, payload, headers):
        return self._request(
            "POST", f"/patients/{patient_id}/insurance-policies", payload, headers
        )

    def list_patient_policies(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/patients/{patient_id}/insurance-policies", headers=headers, params=params
        )

    def terminate_policy(self, patient_id, policy_id, headers):
        return self._request(
            "POST",
            f"/patients/{patient_id}/insurance-policies/{policy_id}/terminate",
            {},
            headers,
        )

    # ---- ExamRecord ----
    def create_exam(self, patient_id, payload, headers):
        return self._request("POST", f"/patients/{patient_id}/exams", payload, headers)

    def list_patient_exams(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/patients/{patient_id}/exams", headers=headers, params=params
        )

    def finalize_exam(self, patient_id, exam_id, headers):
        return self._request(
            "POST", f"/patients/{patient_id}/exams/{exam_id}/finalize", {}, headers
        )

    # ---- TreatmentPlan + phases + series ----
    def create_treatment_plan(self, patient_id, payload, headers):
        return self._request(
            "POST", f"/patients/{patient_id}/treatment-plans", payload, headers
        )

    def list_patient_treatment_plans(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/patients/{patient_id}/treatment-plans", headers=headers, params=params
        )

    def get_treatment_plan(self, patient_id, plan_id, headers):
        return self._request(
            "GET", f"/patients/{patient_id}/treatment-plans/{plan_id}", headers=headers
        )

    def add_phase(self, patient_id, plan_id, payload, headers):
        return self._request(
            "POST", f"/patients/{patient_id}/treatment-plans/{plan_id}/phases", payload, headers
        )

    def list_phases(self, patient_id, plan_id, headers, params=None):
        return self._request(
            "GET",
            f"/patients/{patient_id}/treatment-plans/{plan_id}/phases",
            headers=headers,
            params=params,
        )

    def activate_plan(self, patient_id, plan_id, payload, headers):
        return self._request(
            "POST",
            f"/patients/{patient_id}/treatment-plans/{plan_id}/activate",
            payload,
            headers,
        )

    def discontinue_plan(self, patient_id, plan_id, headers):
        return self._request(
            "POST",
            f"/patients/{patient_id}/treatment-plans/{plan_id}/discontinue",
            {},
            headers,
        )

    def re_exam_regress(self, patient_id, plan_id, payload, headers):
        return self._request(
            "POST",
            f"/patients/{patient_id}/treatment-plans/{plan_id}/re-exam-regress",
            payload,
            headers,
        )

    def create_series(self, patient_id, plan_id, payload, headers):
        return self._request(
            "POST",
            f"/patients/{patient_id}/treatment-plans/{plan_id}/series",
            payload,
            headers,
        )

    def list_series(self, patient_id, plan_id, headers, params=None):
        return self._request(
            "GET",
            f"/patients/{patient_id}/treatment-plans/{plan_id}/series",
            headers=headers,
            params=params,
        )

    # ---- Appointment ----
    def book_appointment(self, patient_id, payload, headers):
        return self._request("POST", f"/patients/{patient_id}/appointments", payload, headers)

    def list_patient_appointments(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/patients/{patient_id}/appointments", headers=headers, params=params
        )

    def get_appointment(self, patient_id, appt_id, headers):
        return self._request(
            "GET", f"/patients/{patient_id}/appointments/{appt_id}", headers=headers
        )

    def check_in(self, patient_id, appt_id, headers):
        return self._request(
            "POST", f"/patients/{patient_id}/appointments/{appt_id}/check-in", {}, headers
        )

    def create_soap_note(self, patient_id, appt_id, payload, headers):
        return self._request(
            "POST", f"/patients/{patient_id}/appointments/{appt_id}/soap-note", payload, headers
        )

    def list_soap_note(self, patient_id, appt_id, headers, params=None):
        return self._request(
            "GET",
            f"/patients/{patient_id}/appointments/{appt_id}/soap-note",
            headers=headers,
            params=params,
        )

    def sign_soap_note(self, patient_id, appt_id, headers):
        return self._request(
            "POST",
            f"/patients/{patient_id}/appointments/{appt_id}/soap-note/sign",
            {},
            headers,
        )

    def complete_appointment(self, patient_id, appt_id, headers):
        return self._request(
            "POST", f"/patients/{patient_id}/appointments/{appt_id}/complete", {}, headers
        )

    def cancel_appointment(self, patient_id, appt_id, headers):
        return self._request(
            "POST", f"/patients/{patient_id}/appointments/{appt_id}/cancel", {}, headers
        )

    def no_show_appointment(self, patient_id, appt_id, headers):
        return self._request(
            "POST", f"/patients/{patient_id}/appointments/{appt_id}/no-show", {}, headers
        )

    def adjudicate_appointment(self, patient_id, appt_id, headers):
        return self._request(
            "POST", f"/patients/{patient_id}/appointments/{appt_id}/adjudicate", {}, headers
        )

    def write_off_appointment(self, patient_id, appt_id, headers):
        return self._request(
            "POST", f"/patients/{patient_id}/appointments/{appt_id}/write-off", {}, headers
        )

    # ---- Flat cross-aggregate read collections ----
    def search_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def get_appointment_by_id(self, appt_id, headers):
        return self._request("GET", f"/appointments/{appt_id}", headers=headers)

    def search_appointment_series(self, headers, params=None):
        return self._request("GET", "/appointment-series", headers=headers, params=params)

    def get_series_by_id(self, series_id, headers):
        return self._request("GET", f"/appointment-series/{series_id}", headers=headers)

    def search_plan_phases(self, headers, params=None):
        return self._request("GET", "/plan-phases", headers=headers, params=params)

    def get_phase_by_id(self, phase_id, headers):
        return self._request("GET", f"/plan-phases/{phase_id}", headers=headers)

    def search_treatment_plans(self, headers, params=None):
        return self._request("GET", "/treatment-plans", headers=headers, params=params)

    def get_plan_by_id(self, plan_id, headers):
        return self._request("GET", f"/treatment-plans/{plan_id}", headers=headers)

    def search_exams(self, headers, params=None):
        return self._request("GET", "/exams", headers=headers, params=params)

    def get_exam_by_id(self, exam_id, headers):
        return self._request("GET", f"/exams/{exam_id}", headers=headers)

    def search_insurance_policies(self, headers, params=None):
        return self._request("GET", "/insurance-policies", headers=headers, params=params)

    def get_policy_by_id(self, policy_id, headers):
        return self._request("GET", f"/insurance-policies/{policy_id}", headers=headers)

    def search_soap_notes(self, headers, params=None):
        return self._request("GET", "/soap-notes", headers=headers, params=params)

    def get_soap_note_by_id(self, note_id, headers):
        return self._request("GET", f"/soap-notes/{note_id}", headers=headers)

    def search_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    def get_ledger_entry_by_id(self, entry_id, headers):
        return self._request("GET", f"/ledger-entries/{entry_id}", headers=headers)


api_client = ApiClient()
