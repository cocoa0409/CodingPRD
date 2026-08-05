"""API client: one method per endpoint declared by the PRD."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/mobile-dentistry"


class ApiClient(GenericApiClient):
    # ── logical clock ────────────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ── programme periods ────────────────────────────────────────────────────
    def create_program_period(self, payload, headers):
        return self._request("POST", f"{PREFIX}/program-periods", payload, headers)

    def get_program_period(self, period_id, headers):
        return self._request("GET", f"{PREFIX}/program-periods/{period_id}", headers=headers)

    def set_program_period_status(self, period_id, payload, headers):
        return self._request("POST", f"{PREFIX}/program-periods/{period_id}/status", payload, headers)

    # ── sites ────────────────────────────────────────────────────────────────
    def create_site(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"{PREFIX}/sites/{site_id}", headers=headers)

    # ── site holds ───────────────────────────────────────────────────────────
    def create_site_hold(self, payload, headers):
        return self._request("POST", f"{PREFIX}/site-holds", payload, headers)

    def list_site_holds(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/site-holds", headers=headers, params=params)

    def get_site_hold(self, hold_id, headers):
        return self._request("GET", f"{PREFIX}/site-holds/{hold_id}", headers=headers)

    def release_site_hold(self, hold_id, headers):
        return self._request("POST", f"{PREFIX}/site-holds/{hold_id}/release", {}, headers)

    # ── patients ─────────────────────────────────────────────────────────────
    def create_patient(self, payload, headers):
        return self._request("POST", f"{PREFIX}/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"{PREFIX}/patients/{patient_id}", headers=headers)

    # ── consents ─────────────────────────────────────────────────────────────
    def create_consent(self, payload, headers):
        return self._request("POST", f"{PREFIX}/consents", payload, headers)

    def list_consents(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/consents", headers=headers, params=params)

    def get_consent(self, consent_id, headers):
        return self._request("GET", f"{PREFIX}/consents/{consent_id}", headers=headers)

    def verify_consent(self, consent_id, headers):
        return self._request("POST", f"{PREFIX}/consents/{consent_id}/verify", {}, headers)

    def revoke_consent(self, consent_id, payload, headers):
        return self._request("POST", f"{PREFIX}/consents/{consent_id}/revoke", payload, headers)

    def amend_consent_tier(self, consent_id, payload, headers):
        return self._request("POST", f"{PREFIX}/consents/{consent_id}/amend-tier", payload, headers)

    # ── portable units ───────────────────────────────────────────────────────
    def create_portable_unit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/portable-units", payload, headers)

    def get_portable_unit(self, unit_id, headers):
        return self._request("GET", f"{PREFIX}/portable-units/{unit_id}", headers=headers)

    def calibrate_portable_unit(self, unit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/portable-units/{unit_id}/calibrate", payload, headers)

    # ── sterilization loads ──────────────────────────────────────────────────
    def create_sterilization_load(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sterilization-loads", payload, headers)

    def list_sterilization_loads(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sterilization-loads", headers=headers, params=params)

    def get_sterilization_load(self, load_id, headers):
        return self._request("GET", f"{PREFIX}/sterilization-loads/{load_id}", headers=headers)

    def record_spore_result(self, load_id, payload, headers):
        return self._request("POST", f"{PREFIX}/sterilization-loads/{load_id}/spore-result", payload, headers)

    # ── staff members ────────────────────────────────────────────────────────
    def create_staff_member(self, payload, headers):
        return self._request("POST", f"{PREFIX}/staff-members", payload, headers)

    def get_staff_member(self, staff_id, headers):
        return self._request("GET", f"{PREFIX}/staff-members/{staff_id}", headers=headers)

    def update_staff_member(self, staff_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/staff-members/{staff_id}", payload, headers)

    # ── site visits ──────────────────────────────────────────────────────────
    def create_site_visit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/site-visits", payload, headers)

    def list_site_visits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/site-visits", headers=headers, params=params)

    def get_site_visit(self, visit_id, headers):
        return self._request("GET", f"{PREFIX}/site-visits/{visit_id}", headers=headers)

    def reschedule_site_visit(self, visit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/site-visits/{visit_id}/reschedule", payload, headers)

    def start_site_visit(self, visit_id, headers):
        return self._request("POST", f"{PREFIX}/site-visits/{visit_id}/start", {}, headers)

    def complete_site_visit(self, visit_id, headers):
        return self._request("POST", f"{PREFIX}/site-visits/{visit_id}/complete", {}, headers)

    def cancel_site_visit(self, visit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/site-visits/{visit_id}/cancel", payload, headers)

    # ── encounters ───────────────────────────────────────────────────────────
    def create_encounter(self, payload, headers):
        return self._request("POST", f"{PREFIX}/encounters", payload, headers)

    def list_encounters(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/encounters", headers=headers, params=params)

    def get_encounter(self, encounter_id, headers):
        return self._request("GET", f"{PREFIX}/encounters/{encounter_id}", headers=headers)

    def screen_encounter(self, encounter_id, payload, headers):
        return self._request("POST", f"{PREFIX}/encounters/{encounter_id}/screen", payload, headers)

    def exam_encounter(self, encounter_id, payload, headers):
        return self._request("POST", f"{PREFIX}/encounters/{encounter_id}/exam", payload, headers)

    def close_encounter(self, encounter_id, headers):
        return self._request("POST", f"{PREFIX}/encounters/{encounter_id}/close", {}, headers)

    def price_encounter(self, encounter_id, payload, headers):
        return self._request("POST", f"{PREFIX}/encounters/{encounter_id}/price", payload, headers)

    def claim_encounter(self, encounter_id, headers):
        return self._request("POST", f"{PREFIX}/encounters/{encounter_id}/claim", {}, headers)

    def adjudicate_encounter(self, encounter_id, payload, headers):
        return self._request("POST", f"{PREFIX}/encounters/{encounter_id}/adjudicate", payload, headers)

    # ── procedures ───────────────────────────────────────────────────────────
    def create_procedure(self, payload, headers):
        return self._request("POST", f"{PREFIX}/procedures", payload, headers)

    def list_procedures(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/procedures", headers=headers, params=params)

    def get_procedure(self, procedure_id, headers):
        return self._request("GET", f"{PREFIX}/procedures/{procedure_id}", headers=headers)

    def perform_procedure(self, procedure_id, payload, headers):
        return self._request("POST", f"{PREFIX}/procedures/{procedure_id}/perform", payload, headers)

    def void_procedure(self, procedure_id, payload, headers):
        return self._request("POST", f"{PREFIX}/procedures/{procedure_id}/void", payload, headers)

    # ── treatment plans ──────────────────────────────────────────────────────
    def create_treatment_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/treatment-plans", payload, headers)

    def list_treatment_plans(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/treatment-plans", headers=headers, params=params)

    def get_treatment_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/treatment-plans/{plan_id}", headers=headers)

    def activate_treatment_plan(self, plan_id, headers):
        return self._request("POST", f"{PREFIX}/treatment-plans/{plan_id}/activate", {}, headers)

    def record_follow_up_contact(self, plan_id, payload, headers):
        return self._request("POST", f"{PREFIX}/treatment-plans/{plan_id}/follow-up-contact", payload, headers)

    # ── referrals ────────────────────────────────────────────────────────────
    def create_referral(self, payload, headers):
        return self._request("POST", f"{PREFIX}/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"{PREFIX}/referrals/{referral_id}", headers=headers)

    def send_referral(self, referral_id, payload, headers):
        return self._request("POST", f"{PREFIX}/referrals/{referral_id}/send", payload, headers)

    def record_referral_response(self, referral_id, payload, headers):
        return self._request("POST", f"{PREFIX}/referrals/{referral_id}/record-response", payload, headers)

    # ── coverages ────────────────────────────────────────────────────────────
    def create_coverage(self, payload, headers):
        return self._request("POST", f"{PREFIX}/coverages", payload, headers)

    def list_coverages(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/coverages", headers=headers, params=params)

    def get_coverage(self, coverage_id, headers):
        return self._request("GET", f"{PREFIX}/coverages/{coverage_id}", headers=headers)

    def verify_coverage(self, coverage_id, payload, headers):
        return self._request("POST", f"{PREFIX}/coverages/{coverage_id}/verify", payload, headers)

    # ── reports ──────────────────────────────────────────────────────────────
    def create_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/reports", payload, headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"{PREFIX}/reports/{report_id}", headers=headers)

    def generate_report(self, report_id, headers):
        return self._request("POST", f"{PREFIX}/reports/{report_id}/generate", {}, headers)

    def submit_report(self, report_id, payload, headers):
        return self._request("POST", f"{PREFIX}/reports/{report_id}/submit", payload, headers)

    # ── raw helpers ──────────────────────────────────────────────────────────
    def get_raw(self, path, headers=None, params=None):
        """Escape hatch for probes that must send unusual headers (or none)."""
        return self._request("GET", path, headers=headers, params=params)

    def post_raw(self, path, payload=None, headers=None):
        return self._request("POST", path, payload, headers)


api_client = ApiClient()
