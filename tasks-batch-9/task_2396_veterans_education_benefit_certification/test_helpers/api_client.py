"""HTTP client with one method per endpoint of the certification API.

Every collection is mounted at the root path with no version prefix, and the
only nested path is the read-only audit sub-resource of an enrollment
certification. Each method returns the raw response so tests can assert on the
status code as well as on the envelope.
"""

from typing import Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, JsonDict


class VetEdApiClient(GenericApiClient):
    """One method per declared endpoint of the certification service."""

    # ─── Logical clock ────────────────────────────────────────────────
    def set_clock(self, payload: JsonDict, headers: Headers) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Certifying officials ─────────────────────────────────────────
    def create_certifying_official(
        self, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/certifying-officials", payload, headers)

    def get_certifying_official(
        self, official_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/certifying-officials/{official_id}", None, headers
        )

    def list_certifying_officials(
        self, headers: Headers, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/certifying-officials", params, headers)

    def deactivate_certifying_official(
        self, official_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/certifying-officials/{official_id}/deactivate", payload, headers
        )

    # ─── Veteran students ─────────────────────────────────────────────
    def create_veteran_student(
        self, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/veteran-students", payload, headers)

    def get_veteran_student(
        self, student_id: str, headers: Headers
    ) -> requests.Response:
        return self._request("GET", f"/veteran-students/{student_id}", None, headers)

    def list_veteran_students(
        self, headers: Headers, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/veteran-students", params, headers)

    def verify_coe(
        self, student_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/veteran-students/{student_id}/verify-coe", payload, headers
        )

    def expire_coe(
        self, student_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/veteran-students/{student_id}/expire-coe", payload, headers
        )

    def set_account_hold(
        self, student_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/veteran-students/{student_id}/account-holds", payload, headers
        )

    # ─── Academic terms ───────────────────────────────────────────────
    def create_academic_term(
        self, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/academic-terms", payload, headers)

    def get_academic_term(self, term_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/academic-terms/{term_id}", None, headers)

    def list_academic_terms(
        self, headers: Headers, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/academic-terms", params, headers)

    def close_academic_term(
        self, term_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/academic-terms/{term_id}/close", payload, headers
        )

    # ─── Programs ─────────────────────────────────────────────────────
    def create_program(self, payload: JsonDict, headers: Headers) -> requests.Response:
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/programs/{program_id}", None, headers)

    def list_programs(
        self, headers: Headers, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/programs", params, headers)

    # ─── Catalog versions ─────────────────────────────────────────────
    def create_catalog_version(
        self, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/catalog-versions", payload, headers)

    def get_catalog_version(
        self, catalog_version_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/catalog-versions/{catalog_version_id}", None, headers
        )

    def list_catalog_versions(
        self, headers: Headers, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/catalog-versions", params, headers)

    def submit_catalog_version_to_saa(
        self, catalog_version_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/catalog-versions/{catalog_version_id}/submit-to-saa",
            payload,
            headers,
        )

    def record_saa_decision(
        self, catalog_version_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/catalog-versions/{catalog_version_id}/saa-decision",
            payload,
            headers,
        )

    def suspend_catalog_version(
        self, catalog_version_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/catalog-versions/{catalog_version_id}/suspend", payload, headers
        )

    # ─── Yellow Ribbon agreements ─────────────────────────────────────
    def create_yellow_ribbon_agreement(
        self, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/yellow-ribbon-agreements", payload, headers)

    def get_yellow_ribbon_agreement(
        self, agreement_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/yellow-ribbon-agreements/{agreement_id}", None, headers
        )

    def list_yellow_ribbon_agreements(
        self, headers: Headers, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/yellow-ribbon-agreements", params, headers)

    def close_yellow_ribbon_agreement(
        self, agreement_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/yellow-ribbon-agreements/{agreement_id}/close", payload, headers
        )

    # ─── Enrollment certifications ────────────────────────────────────
    def create_enrollment_certification(
        self, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/enrollment-certifications", payload, headers)

    def get_enrollment_certification(
        self, certification_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/enrollment-certifications/{certification_id}", None, headers
        )

    def list_enrollment_certifications(
        self, headers: Headers, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/enrollment-certifications", params, headers)

    def update_enrollment_certification(
        self, certification_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "PATCH", f"/enrollment-certifications/{certification_id}", payload, headers
        )

    def submit_certification(
        self, certification_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/enrollment-certifications/{certification_id}/submit",
            payload,
            headers,
        )

    def return_certification(
        self, certification_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/enrollment-certifications/{certification_id}/return",
            payload,
            headers,
        )

    def certify_certification(
        self, certification_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/enrollment-certifications/{certification_id}/certify",
            payload,
            headers,
        )

    def void_certification(
        self, certification_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/enrollment-certifications/{certification_id}/void",
            payload,
            headers,
        )

    def record_va_payment(
        self, certification_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/enrollment-certifications/{certification_id}/record-va-payment",
            payload,
            headers,
        )

    def list_audit_entries(
        self,
        certification_id: str,
        headers: Headers,
        params: Optional[JsonDict] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/enrollment-certifications/{certification_id}/audit-entries",
            params,
            headers,
        )

    # ─── Tuition and fee reports ──────────────────────────────────────
    def create_tuition_fee_report(
        self, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/tuition-fee-reports", payload, headers)

    def get_tuition_fee_report(
        self, report_id: str, headers: Headers
    ) -> requests.Response:
        return self._request("GET", f"/tuition-fee-reports/{report_id}", None, headers)

    def list_tuition_fee_reports(
        self, headers: Headers, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/tuition-fee-reports", params, headers)

    # ─── Yellow Ribbon awards ─────────────────────────────────────────
    def create_yellow_ribbon_award(
        self, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/yellow-ribbon-awards", payload, headers)

    def get_yellow_ribbon_award(
        self, award_id: str, headers: Headers
    ) -> requests.Response:
        return self._request("GET", f"/yellow-ribbon-awards/{award_id}", None, headers)

    def list_yellow_ribbon_awards(
        self, headers: Headers, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/yellow-ribbon-awards", params, headers)

    def finalize_yellow_ribbon_award(
        self, award_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/yellow-ribbon-awards/{award_id}/finalize", payload, headers
        )

    def reverse_yellow_ribbon_award(
        self, award_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/yellow-ribbon-awards/{award_id}/reverse", payload, headers
        )

    # ─── Enrollment change reports ────────────────────────────────────
    def create_enrollment_change_report(
        self, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/enrollment-change-reports", payload, headers)

    def get_enrollment_change_report(
        self, change_report_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/enrollment-change-reports/{change_report_id}", None, headers
        )

    def list_enrollment_change_reports(
        self, headers: Headers, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/enrollment-change-reports", params, headers)

    def reconcile_change_report(
        self, change_report_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/enrollment-change-reports/{change_report_id}/reconcile",
            payload,
            headers,
        )

    # ─── Benefit debts ────────────────────────────────────────────────
    def get_benefit_debt(self, debt_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/benefit-debts/{debt_id}", None, headers)

    def list_benefit_debts(
        self, headers: Headers, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/benefit-debts", params, headers)

    def notify_benefit_debt(
        self, debt_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/benefit-debts/{debt_id}/notify", payload, headers
        )

    def acknowledge_benefit_debt(
        self, debt_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/benefit-debts/{debt_id}/acknowledge", payload, headers
        )

    def mark_benefit_debt_overdue(
        self, debt_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/benefit-debts/{debt_id}/mark-overdue", payload, headers
        )

    def create_debt_repayment(
        self, debt_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/benefit-debts/{debt_id}/repayments", payload, headers
        )

    def waive_benefit_debt(
        self, debt_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/benefit-debts/{debt_id}/waive", payload, headers
        )

    # ─── Student account charges ──────────────────────────────────────
    def create_student_account_charge(
        self, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/student-account-charges", payload, headers)

    def get_student_account_charge(
        self, charge_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/student-account-charges/{charge_id}", None, headers
        )

    def list_student_account_charges(
        self, headers: Headers, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/student-account-charges", params, headers)


#: One shared client instance; the runner owns the server lifecycle.
api_client = VetEdApiClient()
