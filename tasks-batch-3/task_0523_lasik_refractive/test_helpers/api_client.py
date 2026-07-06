"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/refractive"


class ApiClient(GenericApiClient):
    # ---- Packages ----
    def create_package(self, payload, headers):
        return self._request("POST", f"{BASE}/packages", payload, headers)

    def get_package(self, package_id, headers):
        return self._request("GET", f"{BASE}/packages/{package_id}", headers=headers)

    def list_packages(self, headers, params=None):
        return self._request("GET", f"{BASE}/packages", headers=headers, params=params)

    # ---- Suites ----
    def create_suite(self, payload, headers):
        return self._request("POST", f"{BASE}/suites", payload, headers)

    def get_suite(self, suite_id, headers):
        return self._request("GET", f"{BASE}/suites/{suite_id}", headers=headers)

    # ---- Surgeons ----
    def create_surgeon(self, payload, headers):
        return self._request("POST", f"{BASE}/surgeons", payload, headers)

    def get_surgeon(self, surgeon_id, headers):
        return self._request("GET", f"{BASE}/surgeons/{surgeon_id}", headers=headers)

    # ---- Optometrists ----
    def create_optometrist(self, payload, headers):
        return self._request("POST", f"{BASE}/optometrists", payload, headers)

    def get_optometrist(self, optometrist_id, headers):
        return self._request("GET", f"{BASE}/optometrists/{optometrist_id}", headers=headers)

    # ---- Patients ----
    def create_patient(self, payload, headers=None):
        return self._request("POST", f"{BASE}/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"{BASE}/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", f"{BASE}/patients", headers=headers, params=params)

    def list_patient_screenings(self, patient_id, headers):
        return self._request("GET", f"{BASE}/patients/{patient_id}/screenings", headers=headers)

    # ---- Screenings ----
    def create_screening(self, payload, headers):
        return self._request("POST", f"{BASE}/screenings", payload, headers)

    def get_screening(self, screening_id, headers):
        return self._request("GET", f"{BASE}/screenings/{screening_id}", headers=headers)

    def list_screenings(self, headers, params=None):
        return self._request("GET", f"{BASE}/screenings", headers=headers, params=params)

    def submit_screening(self, screening_id, headers):
        return self._request("POST", f"{BASE}/screenings/{screening_id}/submit", {}, headers)

    def adjudicate_screening(self, screening_id, payload, headers):
        return self._request("POST", f"{BASE}/screenings/{screening_id}/adjudicate", payload, headers)

    # ---- Cases ----
    def create_case(self, payload, headers):
        return self._request("POST", f"{BASE}/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"{BASE}/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", f"{BASE}/cases", headers=headers, params=params)

    def create_financing(self, case_id, payload, headers):
        return self._request("POST", f"{BASE}/cases/{case_id}/financing", payload, headers)

    def list_case_financing(self, case_id, headers):
        return self._request("GET", f"{BASE}/cases/{case_id}/financing", headers=headers)

    def create_booking(self, case_id, payload, headers):
        return self._request("POST", f"{BASE}/cases/{case_id}/bookings", payload, headers)

    def list_case_bookings(self, case_id, headers):
        return self._request("GET", f"{BASE}/cases/{case_id}/bookings", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", f"{BASE}/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"{BASE}/bookings/{booking_id}", headers=headers)

    def create_consent(self, case_id, payload, headers):
        return self._request("POST", f"{BASE}/cases/{case_id}/consent", payload, headers)

    def list_case_consent(self, case_id, headers):
        return self._request("GET", f"{BASE}/cases/{case_id}/consent", headers=headers)

    def list_consent_forms(self, headers, params=None):
        return self._request("GET", f"{BASE}/consent-forms", headers=headers, params=params)

    def get_consent_form(self, consent_id, headers):
        return self._request("GET", f"{BASE}/consent-forms/{consent_id}", headers=headers)

    def operate_case(self, case_id, headers):
        return self._request("POST", f"{BASE}/cases/{case_id}/operate", {}, headers)

    def heal_case(self, case_id, payload, headers):
        return self._request("POST", f"{BASE}/cases/{case_id}/heal", payload, headers)

    def cancel_case(self, case_id, payload, headers):
        return self._request("POST", f"{BASE}/cases/{case_id}/cancel", payload, headers)

    # ---- Financing installments ----
    def post_installment(self, financing_id, payload, headers):
        return self._request("POST", f"{BASE}/financing/{financing_id}/installments", payload, headers)

    def get_financing(self, financing_id, headers):
        return self._request("GET", f"{BASE}/financing/{financing_id}", headers=headers)

    # ---- Enhancements ----
    def create_enhancement(self, payload, headers):
        return self._request("POST", f"{BASE}/enhancements", payload, headers)

    def get_enhancement(self, enhancement_id, headers):
        return self._request("GET", f"{BASE}/enhancements/{enhancement_id}", headers=headers)

    def list_enhancements(self, headers, params=None):
        return self._request("GET", f"{BASE}/enhancements", headers=headers, params=params)

    def rescreen_enhancement(self, enhancement_id, payload, headers):
        return self._request("POST", f"{BASE}/enhancements/{enhancement_id}/rescreen", payload, headers)

    def return_enhancement_for_revision(self, enhancement_id, headers):
        return self._request("POST", f"{BASE}/enhancements/{enhancement_id}/return-for-revision", {}, headers)

    def adjudicate_enhancement(self, enhancement_id, payload, headers):
        return self._request("POST", f"{BASE}/enhancements/{enhancement_id}/adjudicate", payload, headers)

    def fulfill_enhancement(self, enhancement_id, headers):
        return self._request("POST", f"{BASE}/enhancements/{enhancement_id}/fulfill", {}, headers)

    # ---- Refund claims ----
    def create_refund_claim(self, payload, headers):
        return self._request("POST", f"{BASE}/refund-claims", payload, headers)

    def get_refund_claim(self, claim_id, headers):
        return self._request("GET", f"{BASE}/refund-claims/{claim_id}", headers=headers)

    def list_refund_claims(self, headers, params=None):
        return self._request("GET", f"{BASE}/refund-claims", headers=headers, params=params)

    def adjudicate_refund_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{BASE}/refund-claims/{claim_id}/adjudicate", payload, headers)

    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{BASE}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
