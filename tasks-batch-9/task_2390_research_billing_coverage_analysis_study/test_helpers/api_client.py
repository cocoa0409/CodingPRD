"""API client: one method per endpoint defined in the PRD.

All resources are mounted under the ``/research-billing`` path prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/research-billing"


class ApiClient(GenericApiClient):
    """Research Billing Coverage Analysis API client."""

    # ------------------------------------------------------------------
    # Studies
    # ------------------------------------------------------------------

    def create_study(self, payload, headers):
        return self._request("POST", f"{PREFIX}/studies", payload, headers)

    def list_studies(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/studies", headers=headers, params=params)

    def get_study(self, study_id, headers):
        return self._request("GET", f"{PREFIX}/studies/{study_id}", headers=headers)

    def record_qct_determination(self, study_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/studies/{study_id}/qct-determination", payload, headers
        )

    def build_budget(self, study_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/studies/{study_id}/budget-build", payload, headers
        )

    def execute_budget(self, study_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/studies/{study_id}/budget-execute", payload, headers
        )

    def set_accrual(self, study_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/studies/{study_id}/accrual", payload, headers
        )

    def get_charge_review_summary(self, study_id, headers):
        return self._request(
            "GET", f"{PREFIX}/studies/{study_id}/charge-review-summary", headers=headers
        )

    def list_study_sponsor_invoices(self, study_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/studies/{study_id}/sponsor-invoices",
            headers=headers,
            params=params,
        )

    def list_study_amendments(self, study_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/studies/{study_id}/amendments",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Coverage analyses and items
    # ------------------------------------------------------------------

    def create_coverage_analysis(self, payload, headers):
        return self._request("POST", f"{PREFIX}/coverage-analyses", payload, headers)

    def list_coverage_analyses(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/coverage-analyses", headers=headers, params=params
        )

    def get_coverage_analysis(self, analysis_id, headers):
        return self._request(
            "GET", f"{PREFIX}/coverage-analyses/{analysis_id}", headers=headers
        )

    def list_coverage_analysis_items(self, analysis_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/coverage-analyses/{analysis_id}/items",
            headers=headers,
            params=params,
        )

    def create_coverage_item(self, payload, headers):
        return self._request("POST", f"{PREFIX}/coverage-items", payload, headers)

    def submit_coverage_analysis(self, analysis_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/coverage-analyses/{analysis_id}/submit", payload, headers
        )

    def return_coverage_analysis(self, analysis_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/coverage-analyses/{analysis_id}/return", payload, headers
        )

    def approve_coverage_analysis(self, analysis_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/coverage-analyses/{analysis_id}/approve", payload, headers
        )

    # ------------------------------------------------------------------
    # Study calendars, visits and charge routes
    # ------------------------------------------------------------------

    def create_study_calendar(self, payload, headers):
        return self._request("POST", f"{PREFIX}/study-calendars", payload, headers)

    def list_study_calendars(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/study-calendars", headers=headers, params=params
        )

    def get_study_calendar(self, calendar_id, headers):
        return self._request(
            "GET", f"{PREFIX}/study-calendars/{calendar_id}", headers=headers
        )

    def list_calendar_visits_of_calendar(self, calendar_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/study-calendars/{calendar_id}/visits",
            headers=headers,
            params=params,
        )

    def create_calendar_visit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/calendar-visits", payload, headers)

    def create_visit_charge_route(self, payload, headers):
        return self._request("POST", f"{PREFIX}/visit-charge-routes", payload, headers)

    def list_visit_charge_routes(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/visit-charge-routes", headers=headers, params=params
        )

    def get_visit_charge_route(self, route_id, headers):
        return self._request(
            "GET", f"{PREFIX}/visit-charge-routes/{route_id}", headers=headers
        )

    def publish_study_calendar(self, calendar_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/study-calendars/{calendar_id}/publish", payload, headers
        )

    # ------------------------------------------------------------------
    # Subjects and subject visits
    # ------------------------------------------------------------------

    def create_study_subject(self, payload, headers):
        return self._request("POST", f"{PREFIX}/study-subjects", payload, headers)

    def list_study_subjects(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/study-subjects", headers=headers, params=params
        )

    def get_study_subject(self, subject_id, headers):
        return self._request(
            "GET", f"{PREFIX}/study-subjects/{subject_id}", headers=headers
        )

    def consent_study_subject(self, subject_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/study-subjects/{subject_id}/consent", payload, headers
        )

    def create_subject_visit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/subject-visits", payload, headers)

    def list_subject_visits(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/subject-visits", headers=headers, params=params
        )

    def get_subject_visit(self, subject_visit_id, headers):
        return self._request(
            "GET", f"{PREFIX}/subject-visits/{subject_visit_id}", headers=headers
        )

    def complete_subject_visit(self, subject_visit_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/subject-visits/{subject_visit_id}/complete",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Charges
    # ------------------------------------------------------------------

    def create_charge(self, payload, headers):
        return self._request("POST", f"{PREFIX}/charges", payload, headers)

    def list_charges(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/charges", headers=headers, params=params)

    def get_charge(self, charge_id, headers):
        return self._request("GET", f"{PREFIX}/charges/{charge_id}", headers=headers)

    def review_charge(self, charge_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/charges/{charge_id}/review", payload, headers
        )

    # ------------------------------------------------------------------
    # Sponsor invoices
    # ------------------------------------------------------------------

    def create_sponsor_invoice(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sponsor-invoices", payload, headers)

    def submit_sponsor_invoice(self, invoice_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/sponsor-invoices/{invoice_id}/submit", payload, headers
        )

    def record_remittance(self, invoice_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/sponsor-invoices/{invoice_id}/remittance",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Audit findings
    # ------------------------------------------------------------------

    def create_audit_finding(self, payload, headers):
        return self._request("POST", f"{PREFIX}/audit-findings", payload, headers)

    def list_audit_findings(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/audit-findings", headers=headers, params=params
        )

    def get_audit_finding(self, finding_id, headers):
        return self._request(
            "GET", f"{PREFIX}/audit-findings/{finding_id}", headers=headers
        )

    def respond_audit_finding(self, finding_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/audit-findings/{finding_id}/respond", payload, headers
        )

    def resolve_audit_finding(self, finding_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/audit-findings/{finding_id}/resolve", payload, headers
        )

    # ------------------------------------------------------------------
    # Amendments
    # ------------------------------------------------------------------

    def create_amendment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/amendments", payload, headers)

    def implement_amendment(self, amendment_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/amendments/{amendment_id}/implement", payload, headers
        )

    # ------------------------------------------------------------------
    # Operations and the logical clock
    # ------------------------------------------------------------------

    def run_aging(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_ops/aging-run", payload, headers)

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST",
            f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )


api_client = ApiClient()
