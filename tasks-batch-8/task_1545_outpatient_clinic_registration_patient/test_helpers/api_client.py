"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/patient-access/_clock/set_current_utc", payload, headers)

    # --- Patient ---
    def create_patient(self, payload, headers):
        return self._request("POST", "/patient-access/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patient-access/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patient-access/patients/{patient_id}", headers=headers)

    def complete_registration(self, patient_id, payload, headers):
        return self._request(
            "POST", f"/patient-access/patients/{patient_id}/complete-registration", payload, headers
        )

    def merge_patient(self, patient_id, payload, headers):
        return self._request("POST", f"/patient-access/patients/{patient_id}/merge", payload, headers)

    def deactivate_patient(self, patient_id, headers):
        return self._request(
            "POST", f"/patient-access/patients/{patient_id}/deactivate", {}, headers
        )

    def list_patient_appointments(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/patient-access/patients/{patient_id}/appointments",
            headers=headers, params=params,
        )

    def list_patient_policies(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/patient-access/patients/{patient_id}/insurance-policies",
            headers=headers, params=params,
        )

    def list_patient_referrals(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/patient-access/patients/{patient_id}/referrals",
            headers=headers, params=params,
        )

    def list_patient_flags(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/patient-access/patients/{patient_id}/accommodation-flags",
            headers=headers, params=params,
        )

    def list_patient_authorizations(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/patient-access/patients/{patient_id}/authorizations",
            headers=headers, params=params,
        )

    # --- AccommodationFlag ---
    def create_accommodation_flag(self, patient_id, payload, headers):
        return self._request(
            "POST", f"/patient-access/patients/{patient_id}/accommodation-flags", payload, headers
        )

    def deactivate_accommodation_flag(self, flag_id, headers):
        return self._request(
            "POST", f"/patient-access/accommodation-flags/{flag_id}/deactivate", {}, headers
        )

    # --- InsurancePolicy ---
    def create_insurance_policy(self, payload, headers):
        return self._request("POST", "/patient-access/insurance-policies", payload, headers)

    def get_insurance_policy(self, policy_id, headers):
        return self._request(
            "GET", f"/patient-access/insurance-policies/{policy_id}", headers=headers
        )

    def list_policy_eligibility_checks(self, policy_id, headers, params=None):
        return self._request(
            "GET", f"/patient-access/insurance-policies/{policy_id}/eligibility-checks",
            headers=headers, params=params,
        )

    def list_policy_copay_estimates(self, policy_id, headers, params=None):
        return self._request(
            "GET", f"/patient-access/insurance-policies/{policy_id}/copay-estimates",
            headers=headers, params=params,
        )

    def terminate_policy(self, policy_id, payload, headers):
        return self._request(
            "POST", f"/patient-access/insurance-policies/{policy_id}/terminate", payload, headers
        )

    def void_policy(self, policy_id, headers):
        return self._request(
            "POST", f"/patient-access/insurance-policies/{policy_id}/void", {}, headers
        )

    # --- Referral ---
    def create_referral(self, payload, headers):
        return self._request("POST", "/patient-access/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/patient-access/referrals/{referral_id}", headers=headers)

    def close_referral(self, referral_id, headers):
        return self._request(
            "POST", f"/patient-access/referrals/{referral_id}/close", {}, headers
        )

    # --- Authorization ---
    def create_authorization(self, payload, headers):
        return self._request("POST", "/patient-access/authorizations", payload, headers)

    def get_authorization(self, authorization_id, headers):
        return self._request(
            "GET", f"/patient-access/authorizations/{authorization_id}", headers=headers
        )

    def void_authorization(self, authorization_id, headers):
        return self._request(
            "POST", f"/patient-access/authorizations/{authorization_id}/void", {}, headers
        )

    def list_appointment_authorizations(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/patient-access/appointments/{appointment_id}/authorizations",
            headers=headers, params=params,
        )

    # --- Appointment ---
    def create_appointment(self, payload, headers):
        return self._request("POST", "/patient-access/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"/patient-access/appointments/{appointment_id}", headers=headers
        )

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/patient-access/appointments", headers=headers, params=params)

    def update_appointment(self, appointment_id, payload, headers):
        return self._request(
            "PATCH", f"/patient-access/appointments/{appointment_id}", payload, headers
        )

    def pre_check(self, appointment_id, headers):
        return self._request(
            "POST", f"/patient-access/appointments/{appointment_id}/pre-check", {}, headers
        )

    def revert_precheck(self, appointment_id, headers):
        return self._request(
            "POST", f"/patient-access/appointments/{appointment_id}/revert-precheck", {}, headers
        )

    def mark_ready(self, appointment_id, headers):
        return self._request(
            "POST", f"/patient-access/appointments/{appointment_id}/mark-ready", {}, headers
        )

    def check_in(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/patient-access/appointments/{appointment_id}/check-in", payload, headers
        )

    def complete_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/patient-access/appointments/{appointment_id}/complete", {}, headers
        )

    def cancel_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/patient-access/appointments/{appointment_id}/cancel", payload, headers
        )

    def mark_no_show(self, appointment_id, headers):
        return self._request(
            "POST", f"/patient-access/appointments/{appointment_id}/mark-no-show", {}, headers
        )

    def list_appointment_estimates(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/patient-access/appointments/{appointment_id}/copay-estimates",
            headers=headers, params=params,
        )

    def list_appointment_payments(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/patient-access/appointments/{appointment_id}/payments",
            headers=headers, params=params,
        )

    def list_appointment_tickets(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/patient-access/appointments/{appointment_id}/queue-tickets",
            headers=headers, params=params,
        )

    def list_appointment_eligibility_checks(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/patient-access/appointments/{appointment_id}/eligibility-checks",
            headers=headers, params=params,
        )

    # --- EligibilityCheck ---
    def create_eligibility_check(self, payload, headers):
        return self._request("POST", "/patient-access/eligibility-checks", payload, headers)

    # --- CopayEstimate ---
    def create_copay_estimate(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/patient-access/appointments/{appointment_id}/copay-estimates",
            payload, headers,
        )

    # --- Payment ---
    def create_payment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/patient-access/appointments/{appointment_id}/payments", payload, headers
        )

    def void_payment(self, payment_id, headers):
        return self._request("POST", f"/patient-access/payments/{payment_id}/void", {}, headers)

    # --- Queue ---
    def call_next(self, payload, headers):
        return self._request("POST", "/patient-access/queue-tickets/call-next", payload, headers)

    def skip_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/patient-access/queue-tickets/{ticket_id}/skip", {}, headers
        )

    def list_department_queue(self, department_code, headers, params=None):
        return self._request(
            "GET", f"/patient-access/departments/{department_code}/queue",
            headers=headers, params=params,
        )

    def close_day(self, department_code, payload, headers):
        return self._request(
            "POST", f"/patient-access/departments/{department_code}/close-day", payload, headers
        )


api_client = ApiClient()
