"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin endpoint layer over the generic request client."""

    # ------------------------------------------------------------- clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---------------------------------------------------------- employers ---
    def create_employer(self, payload, headers):
        return self._request("POST", "/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/employers/{employer_id}", headers=headers)

    # -------------------------------------------------------------- sites ---
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def update_site(self, site_id, payload, headers):
        return self._request("PATCH", f"/sites/{site_id}", payload, headers)

    # ---------------------------------------------------- vendor contracts ---
    def create_vendor_contract(self, payload, headers):
        return self._request("POST", "/vendor-contracts", payload, headers)

    def list_vendor_contracts(self, headers, params=None):
        return self._request("GET", "/vendor-contracts", headers=headers, params=params)

    def get_vendor_contract(self, contract_id, headers):
        return self._request("GET", f"/vendor-contracts/{contract_id}", headers=headers)

    # ---------------------------------------------------------- providers ---
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/providers", headers=headers, params=params)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    def renew_provider_credential(self, provider_id, payload, headers):
        return self._request(
            "POST", f"/providers/{provider_id}/credential-renewal", payload, headers
        )

    def deactivate_provider(self, provider_id, headers, payload=None):
        return self._request(
            "POST", f"/providers/{provider_id}/deactivate", payload or {}, headers
        )

    # ---------------------------------------------------- staffing shifts ---
    def create_staffing_shift(self, payload, headers):
        return self._request("POST", "/staffing-shifts", payload, headers)

    def list_staffing_shifts(self, headers, params=None):
        return self._request("GET", "/staffing-shifts", headers=headers, params=params)

    def get_staffing_shift(self, shift_id, headers):
        return self._request("GET", f"/staffing-shifts/{shift_id}", headers=headers)

    # ------------------------------------------------ eligibility records ---
    def create_eligibility_record(self, payload, headers):
        return self._request("POST", "/eligibility-records", payload, headers)

    def list_eligibility_records(self, headers, params=None):
        return self._request(
            "GET", "/eligibility-records", headers=headers, params=params
        )

    def get_eligibility_record(self, record_id, headers):
        return self._request("GET", f"/eligibility-records/{record_id}", headers=headers)

    def terminate_eligibility_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/eligibility-records/{record_id}/terminate", payload, headers
        )

    # ------------------------------------------------------- participants ---
    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/participants", headers=headers, params=params)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    def terminate_participant(self, participant_id, payload, headers):
        return self._request(
            "POST", f"/participants/{participant_id}/terminate", payload, headers
        )

    def reinstate_participant(self, participant_id, headers, payload=None):
        return self._request(
            "POST", f"/participants/{participant_id}/reinstate", payload or {}, headers
        )

    def record_authorization_decision(self, participant_id, payload, headers):
        return self._request(
            "POST", f"/participants/{participant_id}/authorization", payload, headers
        )

    # -------------------------------------------------------- appointments ---
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def reschedule_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/reschedule", payload, headers
        )

    def cancel_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/cancel", payload, headers
        )

    def check_in_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/appointments/{appointment_id}/check-in", payload or {}, headers
        )

    # -------------------------------------------------------------- visits ---
    def list_visits(self, headers, params=None):
        return self._request("GET", "/visits", headers=headers, params=params)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def start_visit(self, visit_id, headers, payload=None):
        return self._request("POST", f"/visits/{visit_id}/start", payload or {}, headers)

    def complete_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/complete", payload, headers)

    def amend_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/amend", payload, headers)

    def release_visit_disclosure(self, visit_id, headers, payload=None):
        return self._request(
            "POST", f"/visits/{visit_id}/disclosure-release", payload or {}, headers
        )

    def get_employer_disclosure(self, visit_id, headers):
        return self._request(
            "GET", f"/visits/{visit_id}/employer-disclosure", headers=headers
        )

    # -------------------------------------------------- health assessments ---
    def create_health_assessment(self, payload, headers):
        return self._request("POST", "/health-assessments", payload, headers)

    def list_health_assessments(self, headers, params=None):
        return self._request(
            "GET", "/health-assessments", headers=headers, params=params
        )

    def get_health_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"/health-assessments/{assessment_id}", headers=headers
        )

    # ----------------------------------------------------------- referrals ---
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def authorize_referral(self, referral_id, headers, payload=None):
        return self._request(
            "POST", f"/referrals/{referral_id}/authorize", payload or {}, headers
        )

    def decline_referral(self, referral_id, headers, payload=None):
        return self._request(
            "POST", f"/referrals/{referral_id}/decline", payload or {}, headers
        )

    def redirect_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/referrals/{referral_id}/redirect", payload, headers
        )

    def close_referral_loop(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/referrals/{referral_id}/close-loop", payload, headers
        )

    # ----------------------------------------------- alternative standards ---
    def create_alternative_standard(self, payload, headers):
        return self._request("POST", "/alternative-standards", payload, headers)

    def list_alternative_standards(self, headers, params=None):
        return self._request(
            "GET", "/alternative-standards", headers=headers, params=params
        )

    def get_alternative_standard(self, standard_id, headers):
        return self._request(
            "GET", f"/alternative-standards/{standard_id}", headers=headers
        )

    def assign_alternative_standard(self, standard_id, payload, headers):
        return self._request(
            "POST", f"/alternative-standards/{standard_id}/assign", payload, headers
        )

    def complete_alternative_standard(self, standard_id, headers, payload=None):
        return self._request(
            "POST",
            f"/alternative-standards/{standard_id}/complete",
            payload or {},
            headers,
        )

    def deny_alternative_standard(self, standard_id, headers, payload=None):
        return self._request(
            "POST", f"/alternative-standards/{standard_id}/deny", payload or {}, headers
        )

    # ---------------------------------------------------- incentive awards ---
    def create_incentive_award(self, payload, headers):
        return self._request("POST", "/incentive-awards", payload, headers)

    def list_incentive_awards(self, headers, params=None):
        return self._request("GET", "/incentive-awards", headers=headers, params=params)

    def get_incentive_award(self, award_id, headers):
        return self._request("GET", f"/incentive-awards/{award_id}", headers=headers)

    def approve_incentive_award(self, award_id, headers, payload=None):
        return self._request(
            "POST", f"/incentive-awards/{award_id}/approve", payload or {}, headers
        )

    def export_incentive_award(self, award_id, payload, headers):
        return self._request(
            "POST", f"/incentive-awards/{award_id}/export", payload, headers
        )

    def mark_incentive_award_paid(self, award_id, headers, payload=None):
        return self._request(
            "POST", f"/incentive-awards/{award_id}/mark-paid", payload or {}, headers
        )

    def reverse_incentive_award(self, award_id, headers, payload=None):
        return self._request(
            "POST", f"/incentive-awards/{award_id}/reverse", payload or {}, headers
        )

    # --------------------------------------------------- reporting periods ---
    def create_reporting_period(self, payload, headers):
        return self._request("POST", "/reporting-periods", payload, headers)

    def list_reporting_periods(self, headers, params=None):
        return self._request(
            "GET", "/reporting-periods", headers=headers, params=params
        )

    def get_reporting_period(self, period_id, headers):
        return self._request("GET", f"/reporting-periods/{period_id}", headers=headers)

    def finalize_reporting_period(self, period_id, headers, payload=None):
        return self._request(
            "POST", f"/reporting-periods/{period_id}/finalize", payload or {}, headers
        )

    def restate_reporting_period(self, period_id, headers, payload=None):
        return self._request(
            "POST", f"/reporting-periods/{period_id}/restate", payload or {}, headers
        )

    def get_utilization_report(self, period_id, headers):
        return self._request(
            "GET", f"/reporting-periods/{period_id}/utilization-report", headers=headers
        )


api_client = ApiClient()
