"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving capability) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/air-ambulance/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Bases ---
    def create_base(self, payload, headers):
        return self._request("POST", "/air-ambulance/bases", payload, headers)

    def get_base(self, base_id, headers):
        return self._request("GET", f"/air-ambulance/bases/{base_id}", headers=headers)

    # --- Aircraft ---
    def create_aircraft(self, payload, headers):
        return self._request("POST", "/air-ambulance/aircraft", payload, headers)

    def get_aircraft(self, aircraft_id, headers):
        return self._request("GET", f"/air-ambulance/aircraft/{aircraft_id}", headers=headers)

    def list_aircraft(self, headers, params=None):
        return self._request("GET", "/air-ambulance/aircraft", headers=headers, params=params)

    def update_aircraft(self, aircraft_id, payload, headers):
        return self._request("PUT", f"/air-ambulance/aircraft/{aircraft_id}", payload, headers)

    # --- Crew members ---
    def create_crew_member(self, payload, headers):
        return self._request("POST", "/air-ambulance/crew-members", payload, headers)

    def get_crew_member(self, crew_member_id, headers):
        return self._request("GET", f"/air-ambulance/crew-members/{crew_member_id}", headers=headers)

    def list_crew_members(self, headers, params=None):
        return self._request("GET", "/air-ambulance/crew-members", headers=headers, params=params)

    def update_crew_member(self, crew_member_id, payload, headers):
        return self._request("PUT", f"/air-ambulance/crew-members/{crew_member_id}", payload, headers)

    # --- Crew shifts ---
    def create_crew_shift(self, payload, headers):
        return self._request("POST", "/air-ambulance/crew-shifts", payload, headers)

    def get_crew_shift(self, shift_id, headers):
        return self._request("GET", f"/air-ambulance/crew-shifts/{shift_id}", headers=headers)

    def list_crew_shifts(self, headers, params=None):
        return self._request("GET", "/air-ambulance/crew-shifts", headers=headers, params=params)

    def update_crew_shift(self, shift_id, payload, headers):
        return self._request("PUT", f"/air-ambulance/crew-shifts/{shift_id}", payload, headers)

    # --- Patients ---
    def create_patient(self, payload, headers):
        return self._request("POST", "/air-ambulance/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/air-ambulance/patients/{patient_id}", headers=headers)

    # --- Memberships ---
    def create_membership(self, payload, headers):
        return self._request("POST", "/air-ambulance/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/air-ambulance/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/air-ambulance/memberships", headers=headers, params=params)

    def update_membership(self, membership_id, payload, headers):
        return self._request("PUT", f"/air-ambulance/memberships/{membership_id}", payload, headers)

    # --- Mission requests ---
    def create_mission_request(self, payload, headers):
        return self._request("POST", "/air-ambulance/mission-requests", payload, headers)

    def get_mission_request(self, request_id, headers):
        return self._request("GET", f"/air-ambulance/mission-requests/{request_id}", headers=headers)

    def list_mission_requests(self, headers, params=None):
        return self._request("GET", "/air-ambulance/mission-requests", headers=headers, params=params)

    def triage_mission_request(self, request_id, payload, headers):
        return self._request("POST", f"/air-ambulance/mission-requests/{request_id}/triage", payload, headers)

    def request_info(self, request_id, payload, headers):
        return self._request("POST", f"/air-ambulance/mission-requests/{request_id}/request-info", payload, headers)

    def provide_info(self, request_id, payload, headers):
        return self._request("POST", f"/air-ambulance/mission-requests/{request_id}/provide-info", payload, headers)

    def accept_mission_request(self, request_id, payload, headers):
        return self._request("POST", f"/air-ambulance/mission-requests/{request_id}/accept", payload, headers)

    def decline_mission_request(self, request_id, payload, headers):
        return self._request("POST", f"/air-ambulance/mission-requests/{request_id}/decline", payload, headers)

    # --- Missions ---
    def get_mission(self, mission_id, headers):
        return self._request("GET", f"/air-ambulance/missions/{mission_id}", headers=headers)

    def list_missions(self, headers, params=None):
        return self._request("GET", "/air-ambulance/missions", headers=headers, params=params)

    def advance_mission(self, mission_id, payload, headers):
        return self._request("POST", f"/air-ambulance/missions/{mission_id}/advance", payload, headers)

    def abort_mission(self, mission_id, payload, headers):
        return self._request("POST", f"/air-ambulance/missions/{mission_id}/abort", payload, headers)

    def divert_mission(self, mission_id, payload, headers):
        return self._request("POST", f"/air-ambulance/missions/{mission_id}/divert", payload, headers)

    # --- Weather assessments ---
    def create_weather_assessment(self, payload, headers):
        return self._request("POST", "/air-ambulance/weather-assessments", payload, headers)

    def get_weather_assessment(self, assessment_id, headers):
        return self._request("GET", f"/air-ambulance/weather-assessments/{assessment_id}", headers=headers)

    def list_weather_assessments(self, headers, params=None):
        return self._request("GET", "/air-ambulance/weather-assessments", headers=headers, params=params)

    # --- Crew assignments ---
    def create_crew_assignment(self, payload, headers):
        return self._request("POST", "/air-ambulance/crew-assignments", payload, headers)

    def get_crew_assignment(self, assignment_id, headers):
        return self._request("GET", f"/air-ambulance/crew-assignments/{assignment_id}", headers=headers)

    def list_crew_assignments(self, headers, params=None):
        return self._request("GET", "/air-ambulance/crew-assignments", headers=headers, params=params)

    # --- Ground legs ---
    def create_ground_leg(self, payload, headers):
        return self._request("POST", "/air-ambulance/ground-legs", payload, headers)

    def get_ground_leg(self, leg_id, headers):
        return self._request("GET", f"/air-ambulance/ground-legs/{leg_id}", headers=headers)

    def list_ground_legs(self, headers, params=None):
        return self._request("GET", "/air-ambulance/ground-legs", headers=headers, params=params)

    def update_ground_leg(self, leg_id, payload, headers):
        return self._request("PUT", f"/air-ambulance/ground-legs/{leg_id}", payload, headers)

    # --- Bed reservations ---
    def create_bed_reservation(self, payload, headers):
        return self._request("POST", "/air-ambulance/bed-reservations", payload, headers)

    def get_bed_reservation(self, bed_id, headers):
        return self._request("GET", f"/air-ambulance/bed-reservations/{bed_id}", headers=headers)

    def list_bed_reservations(self, headers, params=None):
        return self._request("GET", "/air-ambulance/bed-reservations", headers=headers, params=params)

    def update_bed_reservation(self, bed_id, payload, headers):
        return self._request("PUT", f"/air-ambulance/bed-reservations/{bed_id}", payload, headers)

    # --- Insurance authorizations ---
    def create_insurance_authorization(self, payload, headers):
        return self._request("POST", "/air-ambulance/insurance-authorizations", payload, headers)

    def get_insurance_authorization(self, auth_id, headers):
        return self._request("GET", f"/air-ambulance/insurance-authorizations/{auth_id}", headers=headers)

    def list_insurance_authorizations(self, headers, params=None):
        return self._request("GET", "/air-ambulance/insurance-authorizations", headers=headers, params=params)

    def update_insurance_authorization(self, auth_id, payload, headers):
        return self._request("PUT", f"/air-ambulance/insurance-authorizations/{auth_id}", payload, headers)

    # --- Invoices ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/air-ambulance/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/air-ambulance/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/air-ambulance/invoices", headers=headers, params=params)

    def finalize_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/air-ambulance/invoices/{invoice_id}/finalize", payload, headers)

    def submit_invoice(self, invoice_id, headers):
        return self._request("POST", f"/air-ambulance/invoices/{invoice_id}/submit", headers=headers)

    def payer_response(self, invoice_id, payload, headers):
        return self._request("POST", f"/air-ambulance/invoices/{invoice_id}/payer-response", payload, headers)

    def appeal_invoice(self, invoice_id, headers):
        return self._request("POST", f"/air-ambulance/invoices/{invoice_id}/appeal", headers=headers)

    def member_writeoff(self, invoice_id, headers):
        return self._request("POST", f"/air-ambulance/invoices/{invoice_id}/member-writeoff", headers=headers)

    # --- Repatriation cases ---
    def create_repatriation_case(self, payload, headers):
        return self._request("POST", "/air-ambulance/repatriation-cases", payload, headers)

    def get_repatriation_case(self, case_id, headers):
        return self._request("GET", f"/air-ambulance/repatriation-cases/{case_id}", headers=headers)

    def list_repatriation_cases(self, headers, params=None):
        return self._request("GET", "/air-ambulance/repatriation-cases", headers=headers, params=params)

    def add_repatriation_document(self, case_id, payload, headers):
        return self._request("POST", f"/air-ambulance/repatriation-cases/{case_id}/documents", payload, headers)

    def verify_repatriation_case(self, case_id, headers):
        return self._request("POST", f"/air-ambulance/repatriation-cases/{case_id}/verify", headers=headers)

    # --- Patient care reports ---
    def create_patient_care_report(self, payload, headers):
        return self._request("POST", "/air-ambulance/patient-care-reports", payload, headers)

    def get_patient_care_report(self, pcr_id, headers):
        return self._request("GET", f"/air-ambulance/patient-care-reports/{pcr_id}", headers=headers)

    def list_patient_care_reports(self, headers, params=None):
        return self._request("GET", "/air-ambulance/patient-care-reports", headers=headers, params=params)

    def submit_patient_care_report(self, pcr_id, headers):
        return self._request("POST", f"/air-ambulance/patient-care-reports/{pcr_id}/submit", headers=headers)

    def qa_review_patient_care_report(self, pcr_id, payload, headers):
        return self._request("POST", f"/air-ambulance/patient-care-reports/{pcr_id}/qa-review", payload, headers)

    def amend_patient_care_report(self, pcr_id, payload, headers):
        return self._request("POST", f"/air-ambulance/patient-care-reports/{pcr_id}/amend", payload, headers)


api_client = ApiClient()
