"""One method per endpoint of PRD §4.

Every method returns the raw ``requests.Response`` so tests can assert status
codes as well as bodies.  ``headers`` is always explicit — there is no implicit
acting operator, because PRD §2.1 scopes several operations by identity.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """HTTP surface of the Inclusive Access Course Material Billing API."""

    # ── Logical clock (PRD §2.4) ────────────────────────────────────────────

    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Academic terms (PRD §3.1) ───────────────────────────────────────────

    def create_term(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/terms", payload, headers)

    def get_term(self, term_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/terms/{term_id}", None, headers)

    def list_terms(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/terms", None, headers, params)

    def open_term(self, term_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request("POST", f"/terms/{term_id}/open", payload, headers)

    def lock_term_billing(self, term_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request("POST", f"/terms/{term_id}/lock-billing", payload, headers)

    def list_term_sections(self, term_id: str, headers: Dict[str, str],
                           params: Optional[Dict] = None):
        return self._request("GET", f"/terms/{term_id}/sections", None, headers, params)

    def list_term_disclosure_reports(self, term_id: str, headers: Dict[str, str],
                                     params: Optional[Dict] = None):
        return self._request(
            "GET", f"/terms/{term_id}/disclosure-reports", None, headers, params
        )

    # ── Students (PRD §3.4) ─────────────────────────────────────────────────

    def create_student(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/students", payload, headers)

    def get_student(self, student_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/students/{student_id}", None, headers)

    def list_students(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/students", None, headers, params)

    def list_student_enrollments(self, student_id: str, headers: Dict[str, str],
                                params: Optional[Dict] = None):
        return self._request(
            "GET", f"/students/{student_id}/enrollments", None, headers, params
        )

    def list_student_charges(self, student_id: str, headers: Dict[str, str],
                             params: Optional[Dict] = None):
        return self._request(
            "GET", f"/students/{student_id}/charges", None, headers, params
        )

    def list_student_ledger_entries(self, student_id: str, headers: Dict[str, str],
                                    params: Optional[Dict] = None):
        return self._request(
            "GET", f"/students/{student_id}/ledger-entries", None, headers, params
        )

    # ── Publisher agreements (PRD §3.2) ─────────────────────────────────────

    def create_agreement(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/agreements", payload, headers)

    def get_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/agreements/{agreement_id}", None, headers)

    def list_agreements(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/agreements", None, headers, params)

    def activate_agreement(self, agreement_id: str, headers: Dict[str, str],
                           payload: Any = None):
        return self._request(
            "POST", f"/agreements/{agreement_id}/activate", payload, headers
        )

    def suspend_agreement(self, agreement_id: str, payload: Any,
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/agreements/{agreement_id}/suspend", payload, headers
        )

    def list_agreement_titles(self, agreement_id: str, headers: Dict[str, str],
                              params: Optional[Dict] = None):
        return self._request(
            "GET", f"/agreements/{agreement_id}/titles", None, headers, params
        )

    def list_agreement_reconciliation_runs(self, agreement_id: str,
                                           headers: Dict[str, str],
                                           params: Optional[Dict] = None):
        return self._request(
            "GET", f"/agreements/{agreement_id}/reconciliation-runs",
            None, headers, params,
        )

    # ── Titles and pricing tiers (PRD §3.2) ─────────────────────────────────

    def create_title(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/titles", payload, headers)

    def get_title(self, title_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/titles/{title_id}", None, headers)

    def list_titles(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/titles", None, headers, params)

    def withdraw_title(self, title_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request("POST", f"/titles/{title_id}/withdraw", payload, headers)

    def create_pricing_tier(self, title_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/titles/{title_id}/pricing-tiers", payload, headers
        )

    def list_title_pricing_tiers(self, title_id: str, headers: Dict[str, str],
                                 params: Optional[Dict] = None):
        return self._request(
            "GET", f"/titles/{title_id}/pricing-tiers", None, headers, params
        )

    def get_pricing_tier(self, tier_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/pricing-tiers/{tier_id}", None, headers)

    def list_pricing_tiers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/pricing-tiers", None, headers, params)

    # ── Course sections (PRD §3.4, §3.5) ────────────────────────────────────

    def create_section(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/sections", payload, headers)

    def get_section(self, section_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/sections/{section_id}", None, headers)

    def list_sections(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/sections", None, headers, params)

    def flag_section_inclusive_access(self, section_id: str, headers: Dict[str, str],
                                      payload: Any = None):
        return self._request(
            "POST", f"/sections/{section_id}/flag-inclusive-access", payload, headers
        )

    def list_section_adoptions(self, section_id: str, headers: Dict[str, str],
                               params: Optional[Dict] = None):
        return self._request(
            "GET", f"/sections/{section_id}/adoptions", None, headers, params
        )

    def list_section_enrollments(self, section_id: str, headers: Dict[str, str],
                                 params: Optional[Dict] = None):
        return self._request(
            "GET", f"/sections/{section_id}/enrollments", None, headers, params
        )

    def get_section_billing_summary(self, section_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/sections/{section_id}/billing-summary", None, headers
        )

    def post_section_charges(self, section_id: str, headers: Dict[str, str],
                             payload: Any = None):
        return self._request(
            "POST", f"/sections/{section_id}/post-charges", payload, headers
        )

    # ── Adoptions (PRD §3.3) ────────────────────────────────────────────────

    def create_adoption(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/adoptions", payload, headers)

    def get_adoption(self, adoption_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/adoptions/{adoption_id}", None, headers)

    def list_adoptions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/adoptions", None, headers, params)

    def submit_adoption(self, adoption_id: str, headers: Dict[str, str],
                        payload: Any = None):
        return self._request(
            "POST", f"/adoptions/{adoption_id}/submit", payload, headers
        )

    def request_adoption_change(self, adoption_id: str, payload: Any,
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/adoptions/{adoption_id}/request-change", payload, headers
        )

    def approve_adoption(self, adoption_id: str, headers: Dict[str, str],
                         payload: Any = None):
        return self._request(
            "POST", f"/adoptions/{adoption_id}/approve", payload, headers
        )

    def withdraw_adoption(self, adoption_id: str, headers: Dict[str, str],
                          payload: Any = None):
        return self._request(
            "POST", f"/adoptions/{adoption_id}/withdraw", payload, headers
        )

    # ── Enrollments (PRD §3.4, §3.7) ────────────────────────────────────────

    def create_enrollment(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/enrollments/{enrollment_id}", None, headers)

    def list_enrollments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/enrollments", None, headers, params)

    def drop_enrollment(self, enrollment_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/drop", payload, headers
        )

    def list_enrollment_charges(self, enrollment_id: str, headers: Dict[str, str],
                                params: Optional[Dict] = None):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}/charges", None, headers, params
        )

    def post_enrollment_charge(self, enrollment_id: str, headers: Dict[str, str],
                               payload: Any = None):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/post-charge", payload, headers
        )

    # ── Charges and ledger (PRD §3.5) ───────────────────────────────────────

    def get_charge(self, charge_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/charges/{charge_id}", None, headers)

    def list_charges(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/charges", None, headers, params)

    def list_charge_ledger_entries(self, charge_id: str, headers: Dict[str, str],
                                   params: Optional[Dict] = None):
        return self._request(
            "GET", f"/charges/{charge_id}/ledger-entries", None, headers, params
        )

    def list_charge_opt_out_requests(self, charge_id: str, headers: Dict[str, str],
                                     params: Optional[Dict] = None):
        return self._request(
            "GET", f"/charges/{charge_id}/opt-out-requests", None, headers, params
        )

    def get_ledger_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/ledger-entries/{entry_id}", None, headers)

    def list_ledger_entries(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/ledger-entries", None, headers, params)

    # ── Opt-out lifecycle (PRD §3.6) ────────────────────────────────────────

    def create_opt_out_request(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/opt-out-requests", payload, headers)

    def get_opt_out_request(self, request_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/opt-out-requests/{request_id}", None, headers)

    def list_opt_out_requests(self, headers: Dict[str, str],
                              params: Optional[Dict] = None):
        return self._request("GET", "/opt-out-requests", None, headers, params)

    def grant_opt_out_request(self, request_id: str, headers: Dict[str, str],
                              payload: Any = None):
        return self._request(
            "POST", f"/opt-out-requests/{request_id}/grant", payload, headers
        )

    def deny_opt_out_request(self, request_id: str, payload: Any,
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/opt-out-requests/{request_id}/deny", payload, headers
        )

    def rescind_opt_out_request(self, request_id: str, headers: Dict[str, str],
                                payload: Any = None):
        return self._request(
            "POST", f"/opt-out-requests/{request_id}/rescind", payload, headers
        )

    def resubmit_opt_out_request(self, request_id: str, payload: Any,
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/opt-out-requests/{request_id}/resubmit", payload, headers
        )

    # ── Reconciliation and settlement (PRD §3.8) ────────────────────────────

    def create_reconciliation_run(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/reconciliation-runs", payload, headers)

    def get_reconciliation_run(self, run_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/reconciliation-runs/{run_id}", None, headers)

    def list_reconciliation_runs(self, headers: Dict[str, str],
                                 params: Optional[Dict] = None):
        return self._request("GET", "/reconciliation-runs", None, headers, params)

    def dispute_reconciliation_run(self, run_id: str, payload: Any,
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/reconciliation-runs/{run_id}/dispute", payload, headers
        )

    def settle_reconciliation_run(self, run_id: str, headers: Dict[str, str],
                                  payload: Any = None):
        return self._request(
            "POST", f"/reconciliation-runs/{run_id}/settle", payload, headers
        )

    # ── Disclosure compliance (PRD §3.9) ────────────────────────────────────

    def create_disclosure_report(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/disclosure-reports", payload, headers)

    def get_disclosure_report(self, report_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/disclosure-reports/{report_id}", None, headers)

    def list_disclosure_reports(self, headers: Dict[str, str],
                                params: Optional[Dict] = None):
        return self._request("GET", "/disclosure-reports", None, headers, params)

    def certify_disclosure_report(self, report_id: str, headers: Dict[str, str],
                                  payload: Any = None):
        return self._request(
            "POST", f"/disclosure-reports/{report_id}/certify", payload, headers
        )

    def amend_disclosure_report(self, report_id: str, payload: Any,
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/disclosure-reports/{report_id}/amend", payload, headers
        )


api_client = ApiClient()
