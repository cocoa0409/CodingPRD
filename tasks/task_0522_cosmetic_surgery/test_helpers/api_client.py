"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock -----------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Procedure catalog -------------------------------------------------
    def create_procedure(self, payload, headers):
        return self._request("POST", "/procedures", payload, headers)

    def list_procedures(self, headers, params=None):
        return self._request("GET", "/procedures", headers=headers, params=params)

    def get_procedure(self, procedure_id, headers):
        return self._request("GET", f"/procedures/{procedure_id}", headers=headers)

    def retire_procedure(self, procedure_id, headers):
        return self._request("POST", f"/procedures/{procedure_id}/retire", {}, headers)

    def list_procedure_line_items(self, procedure_id, headers, params=None):
        return self._request("GET", f"/procedures/{procedure_id}/line-items",
                             headers=headers, params=params)

    # ---- Patient -----------------------------------------------------------
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def update_patient(self, patient_id, payload, headers):
        return self._request("PATCH", f"/patients/{patient_id}", payload, headers)

    def issue_clearance(self, patient_id, payload, headers):
        return self._request("POST", f"/patients/{patient_id}/clearances", payload, headers)

    def list_clearances(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/clearances",
                             headers=headers, params=params)

    def list_patient_consultations(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/consultations",
                             headers=headers, params=params)

    def list_patient_quote_packages(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/quote-packages",
                             headers=headers, params=params)

    def list_patient_surgery_bookings(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/surgery-bookings",
                             headers=headers, params=params)

    # ---- Consultation ------------------------------------------------------
    def create_consultation(self, payload, headers):
        return self._request("POST", "/consultations", payload, headers)

    def get_consultation(self, consultation_id, headers):
        return self._request("GET", f"/consultations/{consultation_id}", headers=headers)

    def complete_consultation(self, consultation_id, headers):
        return self._request("POST", f"/consultations/{consultation_id}/complete", {}, headers)

    def close_consultation(self, consultation_id, headers):
        return self._request("POST", f"/consultations/{consultation_id}/close", {}, headers)

    def list_consultation_quote_packages(self, consultation_id, headers, params=None):
        return self._request("GET", f"/consultations/{consultation_id}/quote-packages",
                             headers=headers, params=params)

    # ---- QuotePackage & line items ----------------------------------------
    def create_quote_package(self, payload, headers):
        return self._request("POST", "/quote-packages", payload, headers)

    def get_quote_package(self, quote_id, headers):
        return self._request("GET", f"/quote-packages/{quote_id}", headers=headers)

    def add_line_item(self, quote_id, payload, headers):
        return self._request("POST", f"/quote-packages/{quote_id}/line-items", payload, headers)

    def list_line_items(self, quote_id, headers, params=None):
        return self._request("GET", f"/quote-packages/{quote_id}/line-items",
                             headers=headers, params=params)

    def record_deposit(self, quote_id, payload, headers):
        return self._request("POST", f"/quote-packages/{quote_id}/deposits", payload, headers)

    def present_quote(self, quote_id, headers):
        return self._request("POST", f"/quote-packages/{quote_id}/present", {}, headers)

    def accept_quote(self, quote_id, headers):
        return self._request("POST", f"/quote-packages/{quote_id}/accept", {}, headers)

    def reject_quote(self, quote_id, headers):
        return self._request("POST", f"/quote-packages/{quote_id}/reject", {}, headers)

    def expire_quote(self, quote_id, headers):
        return self._request("POST", f"/quote-packages/{quote_id}/expire", {}, headers)

    # ---- Consent -----------------------------------------------------------
    def create_consent(self, quote_id, payload, headers):
        return self._request("POST", f"/quote-packages/{quote_id}/consents", payload, headers)

    def list_consents(self, quote_id, headers, params=None):
        return self._request("GET", f"/quote-packages/{quote_id}/consents",
                             headers=headers, params=params)

    def revoke_consent(self, consent_id, headers):
        return self._request("POST", f"/consents/{consent_id}/revoke", {}, headers)

    # ---- SurgeryBooking ----------------------------------------------------
    def create_surgery_booking(self, payload, headers):
        return self._request("POST", "/surgery-bookings", payload, headers)

    def get_surgery_booking(self, booking_id, headers):
        return self._request("GET", f"/surgery-bookings/{booking_id}", headers=headers)

    def list_surgery_bookings(self, headers, params=None):
        return self._request("GET", "/surgery-bookings", headers=headers, params=params)

    def complete_surgery_booking(self, booking_id, headers):
        return self._request("POST", f"/surgery-bookings/{booking_id}/complete", {}, headers)

    def cancel_surgery_booking(self, booking_id, headers):
        return self._request("POST", f"/surgery-bookings/{booking_id}/cancel", {}, headers)

    # ---- FinancingApplication ----------------------------------------------
    def submit_financing(self, payload, headers):
        return self._request("POST", "/financing-applications", payload, headers)

    def get_financing(self, financing_id, headers):
        return self._request("GET", f"/financing-applications/{financing_id}", headers=headers)

    def list_financing(self, headers, params=None):
        return self._request("GET", "/financing-applications", headers=headers, params=params)

    def approve_financing(self, financing_id, headers):
        return self._request("POST", f"/financing-applications/{financing_id}/approve", {}, headers)

    def decline_financing(self, financing_id, headers):
        return self._request("POST", f"/financing-applications/{financing_id}/decline", {}, headers)

    # ---- ComplicationCase --------------------------------------------------
    def open_complication_case(self, payload, headers):
        return self._request("POST", "/complication-cases", payload, headers)

    def get_complication_case(self, case_id, headers):
        return self._request("GET", f"/complication-cases/{case_id}", headers=headers)

    def list_complication_cases(self, headers, params=None):
        return self._request("GET", "/complication-cases", headers=headers, params=params)

    def review_complication_case(self, case_id, headers):
        return self._request("POST", f"/complication-cases/{case_id}/review", {}, headers)

    def reopen_complication_case(self, case_id, headers):
        return self._request("POST", f"/complication-cases/{case_id}/reopen", {}, headers)

    def approve_revision(self, case_id, headers):
        return self._request("POST", f"/complication-cases/{case_id}/approve-revision", {}, headers)

    def resolve_complication_case(self, case_id, headers):
        return self._request("POST", f"/complication-cases/{case_id}/resolve", {}, headers)


api_client = ApiClient()
