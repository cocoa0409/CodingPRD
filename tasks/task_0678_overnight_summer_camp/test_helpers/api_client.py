"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------- Test-driving clock ----------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---------- Guardian / auth ----------
    def register_guardian(self, payload, headers):
        return self._request("POST", "/guardians/register", payload, headers)

    def get_guardian(self, guardian_id, headers):
        return self._request("GET", f"/guardians/{guardian_id}", headers=headers)

    # ---------- Camp ----------
    def create_camp(self, payload, headers):
        return self._request("POST", "/camps", payload, headers)

    def get_camp(self, camp_id, headers):
        return self._request("GET", f"/camps/{camp_id}", headers=headers)

    def update_camp(self, camp_id, payload, headers):
        return self._request("PATCH", f"/camps/{camp_id}", payload, headers)

    # ---------- Session ----------
    def create_session(self, camp_id, payload, headers):
        return self._request("POST", f"/camps/{camp_id}/sessions", payload, headers)

    def list_sessions(self, camp_id, headers, params=None):
        return self._request("GET", f"/camps/{camp_id}/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def open_enrollment(self, session_id, payload, headers):
        return self._request("POST", f"/sessions/{session_id}/open-enrollment", payload, headers)

    def start_session(self, session_id, payload, headers):
        return self._request("POST", f"/sessions/{session_id}/start", payload, headers)

    def close_session(self, session_id, payload, headers):
        return self._request("POST", f"/sessions/{session_id}/close", payload, headers)

    def run_intake(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/run-intake", {}, headers)

    # ---------- Cabin ----------
    def create_cabin(self, session_id, payload, headers):
        return self._request("POST", f"/sessions/{session_id}/cabins", payload, headers)

    def list_cabins(self, session_id, headers, params=None):
        return self._request("GET", f"/sessions/{session_id}/cabins", headers=headers, params=params)

    def get_cabin(self, cabin_id, headers):
        return self._request("GET", f"/cabins/{cabin_id}", headers=headers)

    def assign_bunk(self, cabin_id, payload, headers):
        return self._request("POST", f"/cabins/{cabin_id}/assign-bunk", payload, headers)

    # ---------- StaffMember & CabinAssignment ----------
    def create_staff(self, camp_id, payload, headers):
        return self._request("POST", f"/camps/{camp_id}/staff", payload, headers)

    def list_staff(self, camp_id, headers, params=None):
        return self._request("GET", f"/camps/{camp_id}/staff", headers=headers, params=params)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/staff/{staff_id}", headers=headers)

    def create_cabin_assignment(self, payload, headers):
        return self._request("POST", "/cabin-assignments", payload, headers)

    def list_cabin_assignments(self, headers, params=None):
        return self._request("GET", "/cabin-assignments", headers=headers, params=params)

    def get_cabin_assignment(self, assignment_id, headers):
        return self._request("GET", f"/cabin-assignments/{assignment_id}", headers=headers)

    def release_cabin_assignment(self, assignment_id, headers):
        return self._request("POST", f"/cabin-assignments/{assignment_id}/release", {}, headers)

    # ---------- Camper ----------
    def create_camper(self, payload, headers):
        return self._request("POST", "/campers", payload, headers)

    def list_campers(self, headers, params=None):
        return self._request("GET", "/campers", headers=headers, params=params)

    def get_camper(self, camper_id, headers):
        return self._request("GET", f"/campers/{camper_id}", headers=headers)

    # ---------- HealthForm ----------
    def create_health_form(self, payload, headers):
        return self._request("POST", "/health-forms", payload, headers)

    def list_health_forms(self, headers, params=None):
        return self._request("GET", "/health-forms", headers=headers, params=params)

    def get_health_form(self, hf_id, headers):
        return self._request("GET", f"/health-forms/{hf_id}", headers=headers)

    def submit_health_form(self, hf_id, headers):
        return self._request("POST", f"/health-forms/{hf_id}/submit", {}, headers)

    def clear_health_form(self, hf_id, payload, headers):
        return self._request("POST", f"/health-forms/{hf_id}/clear", payload, headers)

    def flag_health_form(self, hf_id, payload, headers):
        return self._request("POST", f"/health-forms/{hf_id}/flag", payload, headers)

    # ---------- Application ----------
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def get_application(self, app_id, headers):
        return self._request("GET", f"/applications/{app_id}", headers=headers)

    def submit_application(self, app_id, headers):
        return self._request("POST", f"/applications/{app_id}/submit", {}, headers)

    def pay_deposit(self, app_id, payload, headers):
        return self._request("POST", f"/applications/{app_id}/pay-deposit", payload, headers)

    def enroll_application(self, app_id, headers):
        return self._request("POST", f"/applications/{app_id}/enroll", {}, headers)

    def withdraw_application(self, app_id, headers):
        return self._request("POST", f"/applications/{app_id}/withdraw", {}, headers)

    def pay_balance(self, app_id, payload, headers):
        return self._request("POST", f"/applications/{app_id}/pay-balance", payload, headers)

    # ---------- FinancialAidAward ----------
    def create_financial_aid(self, payload, headers):
        return self._request("POST", "/financial-aid", payload, headers)

    def list_financial_aid(self, headers, params=None):
        return self._request("GET", "/financial-aid", headers=headers, params=params)

    def get_financial_aid(self, aid_id, headers):
        return self._request("GET", f"/financial-aid/{aid_id}", headers=headers)

    def approve_aid(self, aid_id, payload, headers):
        return self._request("POST", f"/financial-aid/{aid_id}/approve", payload, headers)

    def deny_aid(self, aid_id, headers):
        return self._request("POST", f"/financial-aid/{aid_id}/deny", {}, headers)

    def revoke_aid(self, aid_id, headers):
        return self._request("POST", f"/financial-aid/{aid_id}/revoke", {}, headers)

    # ---------- Payment (reverse-reachability reads) ----------
    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    # ---------- ActivityOffering ----------
    def create_activity(self, session_id, payload, headers):
        return self._request("POST", f"/sessions/{session_id}/activities", payload, headers)

    def list_activities(self, session_id, headers, params=None):
        return self._request("GET", f"/sessions/{session_id}/activities", headers=headers, params=params)

    def get_activity(self, offering_id, headers):
        return self._request("GET", f"/activities/{offering_id}", headers=headers)

    # ---------- ActivityEnrollment ----------
    def create_activity_enrollment(self, payload, headers):
        return self._request("POST", "/activity-enrollments", payload, headers)

    def list_activity_enrollments(self, headers, params=None):
        return self._request("GET", "/activity-enrollments", headers=headers, params=params)

    def get_activity_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/activity-enrollments/{enrollment_id}", headers=headers)

    def drop_activity_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/activity-enrollments/{enrollment_id}/drop", {}, headers)

    # ---------- CanteenAccount & CanteenTransaction ----------
    def create_canteen_account(self, payload, headers):
        return self._request("POST", "/canteen-accounts", payload, headers)

    def list_canteen_accounts(self, headers, params=None):
        return self._request("GET", "/canteen-accounts", headers=headers, params=params)

    def get_canteen_account(self, account_id, headers):
        return self._request("GET", f"/canteen-accounts/{account_id}", headers=headers)

    def create_canteen_transaction(self, account_id, payload, headers):
        return self._request("POST", f"/canteen-accounts/{account_id}/transactions", payload, headers)

    def list_canteen_transactions(self, account_id, headers, params=None):
        return self._request("GET", f"/canteen-accounts/{account_id}/transactions", headers=headers, params=params)


api_client = ApiClient()
