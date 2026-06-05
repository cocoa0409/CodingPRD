"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving clock (PRD §2.9) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- InsurancePolicy ---
    def create_insurance_policy(self, payload, headers):
        return self._request("POST", "/insurance-policies", payload, headers)

    def get_insurance_policy(self, policy_id, headers):
        return self._request("GET", f"/insurance-policies/{policy_id}", headers=headers)

    def list_policy_dependent_enrollments(self, policy_id, headers, params=None):
        return self._request("GET", f"/insurance-policies/{policy_id}/dependent-enrollments",
                             headers=headers, params=params)

    # --- PreRegistration ---
    def create_registration(self, payload, headers):
        return self._request("POST", "/registrations", payload, headers)

    def get_registration(self, reg_id, headers):
        return self._request("GET", f"/registrations/{reg_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/registrations", headers=headers, params=params)

    def submit_registration(self, reg_id, headers):
        return self._request("POST", f"/registrations/{reg_id}/submit", {}, headers)

    def admit_registration(self, reg_id, headers):
        return self._request("POST", f"/registrations/{reg_id}/admit", {}, headers)

    def cancel_registration(self, reg_id, headers):
        return self._request("POST", f"/registrations/{reg_id}/cancel", {}, headers)

    def close_registration(self, reg_id, headers):
        return self._request("POST", f"/registrations/{reg_id}/close", {}, headers)

    def record_birth(self, reg_id, payload, headers):
        return self._request("POST", f"/registrations/{reg_id}/newborns", payload, headers)

    def list_registration_newborns(self, reg_id, headers, params=None):
        return self._request("GET", f"/registrations/{reg_id}/newborns",
                             headers=headers, params=params)

    # --- Newborn ---
    def get_newborn(self, newborn_id, headers):
        return self._request("GET", f"/newborns/{newborn_id}", headers=headers)

    def patch_newborn(self, newborn_id, payload, headers):
        return self._request("PATCH", f"/newborns/{newborn_id}", payload, headers)

    def room_in(self, newborn_id, headers):
        return self._request("POST", f"/newborns/{newborn_id}/room-in", {}, headers)

    def nicu_escalate(self, newborn_id, payload, headers):
        return self._request("POST", f"/newborns/{newborn_id}/nicu-escalate", payload, headers)

    def step_down(self, newborn_id, headers):
        return self._request("POST", f"/newborns/{newborn_id}/step-down", {}, headers)

    def mark_discharge_ready(self, newborn_id, headers):
        return self._request("POST", f"/newborns/{newborn_id}/mark-discharge-ready", {}, headers)

    def discharge(self, newborn_id, headers):
        return self._request("POST", f"/newborns/{newborn_id}/discharge", {}, headers)

    def list_newborn_audit_events(self, newborn_id, headers, params=None):
        return self._request("GET", f"/newborns/{newborn_id}/audit-events",
                             headers=headers, params=params)

    # --- LactationConsult ---
    def create_lactation_consult(self, payload, headers):
        return self._request("POST", "/lactation-consults", payload, headers)

    def get_lactation_consult(self, consult_id, headers):
        return self._request("GET", f"/lactation-consults/{consult_id}", headers=headers)

    def list_lactation_consults(self, headers, params=None):
        return self._request("GET", "/lactation-consults", headers=headers, params=params)

    def complete_lactation_consult(self, consult_id, payload, headers):
        return self._request("POST", f"/lactation-consults/{consult_id}/complete", payload, headers)

    def cancel_lactation_consult(self, consult_id, headers):
        return self._request("POST", f"/lactation-consults/{consult_id}/cancel", {}, headers)

    # --- NicuBed ---
    def create_nicu_bed(self, payload, headers):
        return self._request("POST", "/nicu-beds", payload, headers)

    def get_nicu_bed(self, bed_id, headers):
        return self._request("GET", f"/nicu-beds/{bed_id}", headers=headers)

    def list_nicu_beds(self, headers, params=None):
        return self._request("GET", "/nicu-beds", headers=headers, params=params)

    def list_bed_nicu_stays(self, bed_id, headers, params=None):
        return self._request("GET", f"/nicu-beds/{bed_id}/nicu-stays",
                             headers=headers, params=params)

    def assign_stay(self, bed_id, payload, headers):
        return self._request("POST", f"/nicu-beds/{bed_id}/assign-stay", payload, headers)

    # --- NicuStay ---
    def get_nicu_stay(self, stay_id, headers):
        return self._request("GET", f"/nicu-stays/{stay_id}", headers=headers)

    def list_nicu_stays(self, headers, params=None):
        return self._request("GET", "/nicu-stays", headers=headers, params=params)

    def cancel_nicu_stay(self, stay_id, headers):
        return self._request("POST", f"/nicu-stays/{stay_id}/cancel", {}, headers)

    # --- DischargeBag ---
    def create_discharge_bag(self, payload, headers):
        return self._request("POST", "/discharge-bags", payload, headers)

    def get_discharge_bag(self, bag_id, headers):
        return self._request("GET", f"/discharge-bags/{bag_id}", headers=headers)

    def list_discharge_bags(self, headers, params=None):
        return self._request("GET", "/discharge-bags", headers=headers, params=params)

    def assemble_discharge_bag(self, bag_id, headers):
        return self._request("POST", f"/discharge-bags/{bag_id}/assemble", {}, headers)

    def issue_discharge_bag(self, bag_id, headers, payload=None):
        return self._request("POST", f"/discharge-bags/{bag_id}/issue", payload or {}, headers)

    def recall_discharge_bag(self, bag_id, headers):
        return self._request("POST", f"/discharge-bags/{bag_id}/recall", {}, headers)

    # --- FollowUpTask ---
    def get_follow_up_task(self, task_id, headers):
        return self._request("GET", f"/follow-up-tasks/{task_id}", headers=headers)

    def list_follow_up_tasks(self, headers, params=None):
        return self._request("GET", "/follow-up-tasks", headers=headers, params=params)

    def record_attempt(self, task_id, headers, payload=None):
        return self._request("POST", f"/follow-up-tasks/{task_id}/record-attempt",
                             payload or {}, headers)

    def complete_follow_up_task(self, task_id, headers):
        return self._request("POST", f"/follow-up-tasks/{task_id}/complete", {}, headers)

    def mark_missed(self, task_id, headers):
        return self._request("POST", f"/follow-up-tasks/{task_id}/mark-missed", {}, headers)

    # --- DependentEnrollment ---
    def create_dependent_enrollment(self, payload, headers):
        return self._request("POST", "/dependent-enrollments", payload, headers)

    def get_dependent_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/dependent-enrollments/{enrollment_id}", headers=headers)

    def list_dependent_enrollments(self, headers, params=None):
        return self._request("GET", "/dependent-enrollments", headers=headers, params=params)

    def approve_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/dependent-enrollments/{enrollment_id}/approve",
                             payload, headers)

    def deny_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/dependent-enrollments/{enrollment_id}/deny", {}, headers)

    def expire_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/dependent-enrollments/{enrollment_id}/expire", {}, headers)

    def terminate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/dependent-enrollments/{enrollment_id}/terminate",
                             {}, headers)

    # --- GovernmentFiling ---
    def create_government_filing(self, payload, headers):
        return self._request("POST", "/government-filings", payload, headers)

    def get_government_filing(self, filing_id, headers):
        return self._request("GET", f"/government-filings/{filing_id}", headers=headers)

    def list_government_filings(self, headers, params=None):
        return self._request("GET", "/government-filings", headers=headers, params=params)

    def submit_filing(self, filing_id, headers):
        return self._request("POST", f"/government-filings/{filing_id}/submit", {}, headers)

    def acknowledge_filing(self, filing_id, payload, headers):
        return self._request("POST", f"/government-filings/{filing_id}/acknowledge",
                             payload, headers)

    def cancel_filing(self, filing_id, headers):
        return self._request("POST", f"/government-filings/{filing_id}/cancel", {}, headers)


api_client = ApiClient()
