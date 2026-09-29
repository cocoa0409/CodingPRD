"""
Typed client for the Theatrical Capitalization & Investor Reporting API.

One method per endpoint the PRD declares, including the logical-clock
capability. Every method returns the raw `requests.Response` so tests can
assert on status codes as well as bodies. Paths are flat: "Every entity in
this system is a peer collection addressed directly at the URL root."
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Theatres ─────────────────────────────────────────────────────────

    def create_theatre(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/theatres", payload, headers)

    def get_theatre(self, theatre_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/theatres/{theatre_id}", headers=headers)

    # ─── Productions ──────────────────────────────────────────────────────

    def create_production(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/productions", payload, headers)

    def get_production(self, production_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/productions/{production_id}", headers=headers)

    def list_productions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/productions", headers=headers, params=params)

    def open_offering(self, production_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/productions/{production_id}/open-offering", {}, headers
        )

    def capitalize(self, production_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/productions/{production_id}/capitalize", {}, headers
        )

    def set_operating_status(
        self, production_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/productions/{production_id}/operating-status", payload, headers
        )

    def convert_royalties_to_pool(self, production_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/productions/{production_id}/convert-royalties-to-pool",
            {},
            headers,
        )

    def approve_budget(self, production_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/productions/{production_id}/approve-budget", {}, headers
        )

    def get_break_even_analysis(self, production_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/productions/{production_id}/break-even-analysis", headers=headers
        )

    def get_recoupment_report(self, production_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/productions/{production_id}/recoupment-report", headers=headers
        )

    # ─── Theatre engagements ──────────────────────────────────────────────

    def create_theatre_engagement(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/theatre-engagements", payload, headers)

    def get_theatre_engagement(self, engagement_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/theatre-engagements/{engagement_id}", headers=headers
        )

    def list_theatre_engagements(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", "/theatre-engagements", headers=headers, params=params
        )

    # ─── Budget lines ─────────────────────────────────────────────────────

    def create_budget_line(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/budget-lines", payload, headers)

    def commit_budget_line(self, budget_line_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/budget-lines/{budget_line_id}/commit", {}, headers
        )

    def get_budget_line(self, budget_line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/budget-lines/{budget_line_id}", headers=headers)

    def list_budget_lines(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/budget-lines", headers=headers, params=params)

    # ─── Operating budgets ────────────────────────────────────────────────

    def create_operating_budget(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/operating-budgets", payload, headers)

    def activate_operating_budget(self, budget_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/operating-budgets/{budget_id}/activate", {}, headers
        )

    def get_operating_budget(self, budget_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/operating-budgets/{budget_id}", headers=headers
        )

    def list_operating_budgets(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", "/operating-budgets", headers=headers, params=params
        )

    # ─── Offering documents ───────────────────────────────────────────────

    def create_offering_document(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/offering-documents", payload, headers)

    def make_offering_document_effective(self, doc_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/offering-documents/{doc_id}/make-effective", {}, headers
        )

    def withdraw_offering_document(
        self, doc_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/offering-documents/{doc_id}/withdraw", payload, headers
        )

    def get_offering_document(self, doc_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/offering-documents/{doc_id}", headers=headers
        )

    def list_offering_documents(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", "/offering-documents", headers=headers, params=params
        )

    # ─── Investors ────────────────────────────────────────────────────────

    def create_investor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/investors", payload, headers)

    def accredit_investor(
        self, investor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/investors/{investor_id}/accredit", payload, headers
        )

    def get_investor(self, investor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/investors/{investor_id}", headers=headers)

    # ─── Subscriptions ────────────────────────────────────────────────────

    def create_subscription(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/subscriptions", payload, headers)

    def return_subscription_for_cure(
        self, subscription_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/return-for-cure", payload, headers
        )

    def resubmit_subscription(
        self, subscription_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/resubmit", payload, headers
        )

    def accept_subscription(self, subscription_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/accept", {}, headers
        )

    def rescind_subscription(
        self, subscription_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/rescind", payload, headers
        )

    def get_subscription(self, subscription_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/subscriptions/{subscription_id}", headers=headers
        )

    def list_subscriptions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    # ─── Capital accounts ─────────────────────────────────────────────────

    def get_investor_account(self, account_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/investor-accounts/{account_id}", headers=headers
        )

    def list_investor_accounts(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", "/investor-accounts", headers=headers, params=params
        )

    # ─── Royalty participants ─────────────────────────────────────────────

    def create_royalty_participant(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/royalty-participants", payload, headers)

    def terminate_royalty_participant(
        self, participant_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/royalty-participants/{participant_id}/terminate", {}, headers
        )

    def reinstate_royalty_participant(
        self, participant_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/royalty-participants/{participant_id}/reinstate", {}, headers
        )

    def get_royalty_participant(self, participant_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/royalty-participants/{participant_id}", headers=headers
        )

    def list_royalty_participants(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", "/royalty-participants", headers=headers, params=params
        )

    # ─── Weekly wraps ─────────────────────────────────────────────────────

    def create_weekly_wrap(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/weekly-wraps", payload, headers)

    def submit_weekly_wrap(self, wrap_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/weekly-wraps/{wrap_id}/submit", {}, headers)

    def certify_weekly_wrap(self, wrap_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/weekly-wraps/{wrap_id}/certify", {}, headers)

    def dispute_weekly_wrap(
        self, wrap_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/weekly-wraps/{wrap_id}/dispute", payload, headers
        )

    def amend_weekly_wrap(
        self, wrap_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/weekly-wraps/{wrap_id}/amend", payload, headers)

    def void_weekly_wrap(
        self, wrap_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/weekly-wraps/{wrap_id}/void", payload, headers)

    def get_weekly_wrap(self, wrap_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/weekly-wraps/{wrap_id}", headers=headers)

    def list_weekly_wraps(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/weekly-wraps", headers=headers, params=params)

    # ─── Royalty allocations (cascade-created only) ────────────────────────

    def get_royalty_allocation(self, allocation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/royalty-allocations/{allocation_id}", headers=headers
        )

    def list_royalty_allocations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", "/royalty-allocations", headers=headers, params=params
        )

    # ─── Subsidiary rights income ─────────────────────────────────────────

    def create_subsidiary_rights_income(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/subsidiary-rights-income", payload, headers)

    def allocate_subsidiary_rights_income(
        self, income_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/subsidiary-rights-income/{income_id}/allocate", {}, headers
        )

    def get_subsidiary_rights_income(self, income_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/subsidiary-rights-income/{income_id}", headers=headers
        )

    def list_subsidiary_rights_income(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", "/subsidiary-rights-income", headers=headers, params=params
        )

    # ─── Investor distributions ───────────────────────────────────────────

    def declare_investor_distribution(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/investor-distributions", payload, headers)

    def pay_investor_distribution(
        self, distribution_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/investor-distributions/{distribution_id}/pay", {}, headers
        )

    def get_investor_distribution(
        self, distribution_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET", f"/investor-distributions/{distribution_id}", headers=headers
        )

    def list_investor_distributions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", "/investor-distributions", headers=headers, params=params
        )

    # ─── Closing notices ──────────────────────────────────────────────────

    def create_closing_notice(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/closing-notices", payload, headers)

    def withdraw_closing_notice(
        self, notice_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/closing-notices/{notice_id}/withdraw", payload, headers
        )

    def settle_closing_notice(
        self, notice_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/closing-notices/{notice_id}/settle", payload, headers
        )

    def get_closing_notice(self, notice_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/closing-notices/{notice_id}", headers=headers)

    def list_closing_notices(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/closing-notices", headers=headers, params=params)

    # ─── The logical UTC clock ────────────────────────────────────────────

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        """Set the logical UTC clock that every date comparison reads."""
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )
