"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving infrastructure ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_sweeps(self, headers):
        return self._request("POST", "/_sweeps/run_pending_transitions", {}, headers)

    # --- Staff ---
    def create_staff(self, payload, headers):
        return self._request("POST", "/staff", payload, headers)

    def list_staff(self, headers, params=None):
        return self._request("GET", "/staff", headers=headers, params=params)

    # --- Clients ---
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def suspend_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/suspend", {}, headers)

    def reinstate_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/reinstate", {}, headers)

    def exit_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/exit", {}, headers)

    # --- Intake assessments ---
    def create_assessment(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/assessments", payload, headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/assessments", headers=headers, params=params)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    def submit_assessment(self, client_id, assessment_id, headers):
        return self._request(
            "POST", f"/clients/{client_id}/assessments/{assessment_id}/submit", {}, headers
        )

    def verify_assessment(self, client_id, assessment_id, payload, headers):
        return self._request(
            "POST", f"/clients/{client_id}/assessments/{assessment_id}/verify", payload, headers
        )

    def return_assessment(self, client_id, assessment_id, payload, headers):
        return self._request(
            "POST", f"/clients/{client_id}/assessments/{assessment_id}/return", payload, headers
        )

    def revise_assessment(self, client_id, assessment_id, payload, headers):
        return self._request(
            "POST", f"/clients/{client_id}/assessments/{assessment_id}/revise", payload, headers
        )

    # --- Pantry catalog ---
    def create_pantry_item(self, payload, headers):
        return self._request("POST", "/pantry-items", payload, headers)

    def list_pantry_items(self, headers, params=None):
        return self._request("GET", "/pantry-items", headers=headers, params=params)

    def patch_pantry_item(self, item_id, payload, headers):
        return self._request("PATCH", f"/pantry-items/{item_id}", payload, headers)

    def restock_pantry_item(self, item_id, payload, headers):
        return self._request("POST", f"/pantry-items/{item_id}/restock", payload, headers)

    def discontinue_pantry_item(self, item_id, headers):
        return self._request("POST", f"/pantry-items/{item_id}/discontinue", {}, headers)

    # --- Pantry visits ---
    def check_in_pantry_visit(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/pantry-visits", {}, headers)

    def list_pantry_visits(self, headers, params=None):
        return self._request("GET", "/pantry-visits", headers=headers, params=params)

    def get_pantry_visit(self, visit_id, headers):
        return self._request("GET", f"/pantry-visits/{visit_id}", headers=headers)

    def add_line_item(self, visit_id, payload, headers):
        return self._request("POST", f"/pantry-visits/{visit_id}/line-items", payload, headers)

    def list_visit_line_items(self, headers, params=None):
        return self._request("GET", "/visit-line-items", headers=headers, params=params)

    def get_visit_line_item(self, line_item_id, headers):
        return self._request("GET", f"/visit-line-items/{line_item_id}", headers=headers)

    def checkout_visit(self, visit_id, headers):
        return self._request("POST", f"/pantry-visits/{visit_id}/checkout", {}, headers)

    def void_visit(self, visit_id, headers):
        return self._request("POST", f"/pantry-visits/{visit_id}/void", {}, headers)

    # --- Benefits screenings ---
    def create_screening(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/screenings", payload, headers)

    def list_screenings(self, headers, params=None):
        return self._request("GET", "/screenings", headers=headers, params=params)

    def get_screening(self, screening_id, headers):
        return self._request("GET", f"/screenings/{screening_id}", headers=headers)

    def score_screening(self, screening_id, headers):
        return self._request("POST", f"/screenings/{screening_id}/score", {}, headers)

    def assist_screening(self, screening_id, headers):
        return self._request("POST", f"/screenings/{screening_id}/assist", {}, headers)

    def submit_screening_application(self, screening_id, headers):
        return self._request(
            "POST", f"/screenings/{screening_id}/submit-application", {}, headers
        )

    def determine_screening(self, screening_id, payload, headers):
        return self._request("POST", f"/screenings/{screening_id}/determine", payload, headers)

    def withdraw_screening(self, screening_id, headers):
        return self._request("POST", f"/screenings/{screening_id}/withdraw", {}, headers)

    # --- Grant funds ---
    def create_grant_fund(self, payload, headers):
        return self._request("POST", "/grant-funds", payload, headers)

    def get_grant_fund(self, fund_id, headers):
        return self._request("GET", f"/grant-funds/{fund_id}", headers=headers)

    def close_grant_fund(self, fund_id, headers):
        return self._request("POST", f"/grant-funds/{fund_id}/close", {}, headers)

    # --- Emergency grant applications ---
    def create_grant_application(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/grant-applications", payload, headers)

    def list_grant_applications(self, headers, params=None):
        return self._request("GET", "/grant-applications", headers=headers, params=params)

    def get_grant_application(self, grant_id, headers):
        return self._request("GET", f"/grant-applications/{grant_id}", headers=headers)

    def submit_grant_application(self, grant_id, headers):
        return self._request("POST", f"/grant-applications/{grant_id}/submit", {}, headers)

    def begin_review(self, grant_id, headers):
        return self._request("POST", f"/grant-applications/{grant_id}/begin-review", {}, headers)

    def request_info(self, grant_id, payload, headers):
        return self._request("POST", f"/grant-applications/{grant_id}/request-info", payload, headers)

    def approve_grant(self, grant_id, payload, headers):
        return self._request("POST", f"/grant-applications/{grant_id}/approve", payload, headers)

    def deny_grant(self, grant_id, payload, headers):
        return self._request("POST", f"/grant-applications/{grant_id}/deny", payload, headers)

    def disburse_grant(self, grant_id, headers):
        return self._request("POST", f"/grant-applications/{grant_id}/disburse", {}, headers)

    def withdraw_grant(self, grant_id, headers):
        return self._request("POST", f"/grant-applications/{grant_id}/withdraw", {}, headers)

    # --- Shelter beds & stays ---
    def create_shelter_bed(self, payload, headers):
        return self._request("POST", "/shelter-beds", payload, headers)

    def list_shelter_beds(self, headers, params=None):
        return self._request("GET", "/shelter-beds", headers=headers, params=params)

    def patch_shelter_bed(self, bed_id, payload, headers):
        return self._request("PATCH", f"/shelter-beds/{bed_id}", payload, headers)

    def create_shelter_stay(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/shelter-stays", payload, headers)

    def list_shelter_stays(self, headers, params=None):
        return self._request("GET", "/shelter-stays", headers=headers, params=params)

    def get_shelter_stay(self, stay_id, headers):
        return self._request("GET", f"/shelter-stays/{stay_id}", headers=headers)

    def shelter_stay_check_in(self, stay_id, headers):
        return self._request("POST", f"/shelter-stays/{stay_id}/check-in", {}, headers)

    def shelter_stay_check_out(self, stay_id, headers):
        return self._request("POST", f"/shelter-stays/{stay_id}/check-out", {}, headers)

    def cancel_shelter_stay(self, stay_id, headers):
        return self._request("POST", f"/shelter-stays/{stay_id}/cancel", {}, headers)

    # --- Partner agencies & referrals ---
    def create_partner_agency(self, payload, headers):
        return self._request("POST", "/partner-agencies", payload, headers)

    def list_partner_agencies(self, headers, params=None):
        return self._request("GET", "/partner-agencies", headers=headers, params=params)

    def patch_partner_agency(self, agency_id, payload, headers):
        return self._request("PATCH", f"/partner-agencies/{agency_id}", payload, headers)

    def pause_agency(self, agency_id, headers):
        return self._request("POST", f"/partner-agencies/{agency_id}/pause", {}, headers)

    def resume_agency(self, agency_id, headers):
        return self._request("POST", f"/partner-agencies/{agency_id}/resume", {}, headers)

    def create_referral(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def send_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/send", {}, headers)

    def acknowledge_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/acknowledge", {}, headers)

    def book_appointment(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/book-appointment", payload, headers)

    def record_service(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/record-service", {}, headers)

    def decline_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/decline", payload, headers)

    def withdraw_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/withdraw", {}, headers)

    def resend_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/resend", {}, headers)

    # --- Outreach events & registrations ---
    def create_outreach_event(self, payload, headers):
        return self._request("POST", "/outreach-events", payload, headers)

    def list_outreach_events(self, headers, params=None):
        return self._request("GET", "/outreach-events", headers=headers, params=params)

    def open_event(self, event_id, headers):
        return self._request("POST", f"/outreach-events/{event_id}/open", {}, headers)

    def complete_event(self, event_id, headers):
        return self._request("POST", f"/outreach-events/{event_id}/complete", {}, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/outreach-events/{event_id}/cancel", {}, headers)

    def register_for_event(self, event_id, payload, headers):
        return self._request("POST", f"/outreach-events/{event_id}/registrations", payload, headers)

    def list_event_registrations(self, headers, params=None):
        return self._request("GET", "/event-registrations", headers=headers, params=params)

    def get_event_registration(self, registration_id, headers):
        return self._request("GET", f"/event-registrations/{registration_id}", headers=headers)

    def cancel_registration(self, registration_id, headers):
        return self._request("POST", f"/event-registrations/{registration_id}/cancel", {}, headers)

    def mark_attended(self, registration_id, headers):
        return self._request(
            "POST", f"/event-registrations/{registration_id}/mark-attended", {}, headers
        )

    # --- Reporting ---
    def get_usage_summary(self, headers, params=None):
        return self._request("GET", "/reports/usage-summary", headers=headers, params=params)


api_client = ApiClient()
