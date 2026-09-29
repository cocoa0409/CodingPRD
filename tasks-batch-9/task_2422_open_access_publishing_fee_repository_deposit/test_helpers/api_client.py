"""API client: one method per endpoint defined in the PRD.

Every method returns the raw ``requests.Response`` so tests can assert status
codes and envelope contents through the framework validators.  Path segments are
flat: every entity collection is a top-level path segment, and the nested read
paths are read views only.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----------------------------------------------------------- publishers --
    def create_publisher(self, payload: dict, headers: dict):
        return self._request("POST", "/publishers", payload, headers)

    def get_publisher(self, publisher_id: str, headers: dict):
        return self._request("GET", f"/publishers/{publisher_id}", headers=headers)

    def create_screening_run(self, publisher_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/publishers/{publisher_id}/screening-runs", payload, headers
        )

    def list_publisher_journals(
        self, publisher_id: str, headers: dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/publishers/{publisher_id}/journals", headers=headers, params=params
        )

    def list_publisher_agreements(
        self, publisher_id: str, headers: dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/publishers/{publisher_id}/transformative-agreements",
            headers=headers,
            params=params,
        )

    # -------------------------------------------------------------- journals --
    def create_journal(self, payload: dict, headers: dict):
        return self._request("POST", "/journals", payload, headers)

    def get_journal(self, journal_id: str, headers: dict):
        return self._request("GET", f"/journals/{journal_id}", headers=headers)

    def list_journal_coverages(
        self, journal_id: str, headers: dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/journals/{journal_id}/coverages", headers=headers, params=params
        )

    # ------------------------------------------- transformative agreements ---
    def create_transformative_agreement(self, payload: dict, headers: dict):
        return self._request("POST", "/transformative-agreements", payload, headers)

    def get_transformative_agreement(self, agreement_id: str, headers: dict):
        return self._request(
            "GET", f"/transformative-agreements/{agreement_id}", headers=headers
        )

    def activate_transformative_agreement(
        self, agreement_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/transformative-agreements/{agreement_id}/activation",
            payload if payload is not None else {},
            headers,
        )

    def create_agreement_coverage(self, agreement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/transformative-agreements/{agreement_id}/coverages",
            payload,
            headers,
        )

    def list_agreement_coverages(
        self, agreement_id: str, headers: dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/transformative-agreements/{agreement_id}/coverages",
            headers=headers,
            params=params,
        )

    # --------------------------------------------------------------- authors --
    def create_author(self, payload: dict, headers: dict):
        return self._request("POST", "/authors", payload, headers)

    def get_author(self, author_id: str, headers: dict):
        return self._request("GET", f"/authors/{author_id}", headers=headers)

    def list_author_grants(
        self, author_id: str, headers: dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/authors/{author_id}/grants", headers=headers, params=params
        )

    # --------------------------------------------------------------- funders --
    def create_funder(self, payload: dict, headers: dict):
        return self._request("POST", "/funders", payload, headers)

    def get_funder(self, funder_id: str, headers: dict):
        return self._request("GET", f"/funders/{funder_id}", headers=headers)

    def list_funder_grants(
        self, funder_id: str, headers: dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/funders/{funder_id}/grants", headers=headers, params=params
        )

    # ---------------------------------------------------------------- grants --
    def create_grant(self, payload: dict, headers: dict):
        return self._request("POST", "/grants", payload, headers)

    def get_grant(self, grant_id: str, headers: dict):
        return self._request("GET", f"/grants/{grant_id}", headers=headers)

    # ------------------------------------------------------------- apc funds --
    def create_apc_fund(self, payload: dict, headers: dict):
        return self._request("POST", "/apc-funds", payload, headers)

    def get_apc_fund(self, fund_id: str, headers: dict):
        return self._request("GET", f"/apc-funds/{fund_id}", headers=headers)

    def freeze_apc_fund(self, fund_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/apc-funds/{fund_id}/freeze", payload, headers)

    def list_fund_allocations(
        self, fund_id: str, headers: dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/apc-funds/{fund_id}/allocations", headers=headers, params=params
        )

    # -------------------------------------------------------------- articles --
    def create_article(self, payload: dict, headers: dict):
        return self._request("POST", "/articles", payload, headers)

    def list_articles(self, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", "/articles", headers=headers, params=params)

    def get_article(self, article_id: str, headers: dict):
        return self._request("GET", f"/articles/{article_id}", headers=headers)

    def create_eligibility_check(
        self, article_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST", f"/articles/{article_id}/eligibility-checks", payload, headers
        )

    def publish_article(self, article_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/articles/{article_id}/publication", payload, headers
        )

    def list_eligibility_determinations(
        self, headers: dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/eligibility-determinations", headers=headers, params=params
        )

    def get_eligibility_determination(self, determination_id: str, headers: dict):
        return self._request(
            "GET", f"/eligibility-determinations/{determination_id}", headers=headers
        )

    # ---------------------------------------------------------- fund requests --
    def create_fund_request(self, payload: dict, headers: dict):
        return self._request("POST", "/fund-requests", payload, headers)

    def list_article_fund_requests(
        self, article_id: str, headers: dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/articles/{article_id}/fund-requests", headers=headers, params=params
        )

    def get_fund_request(self, request_id: str, headers: dict):
        return self._request("GET", f"/fund-requests/{request_id}", headers=headers)

    def start_fund_request_review(
        self, request_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/fund-requests/{request_id}/start-review",
            payload if payload is not None else {},
            headers,
        )

    def create_fund_request_info_request(
        self, request_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST", f"/fund-requests/{request_id}/info-requests", payload, headers
        )

    def create_fund_request_resubmission(
        self, request_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST", f"/fund-requests/{request_id}/resubmissions", payload, headers
        )

    def decide_fund_request(self, request_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/fund-requests/{request_id}/decision", payload, headers
        )

    def withdraw_fund_request(self, request_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/fund-requests/{request_id}/withdrawal", payload, headers
        )

    def list_fund_request_allocations(
        self, request_id: str, headers: dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/fund-requests/{request_id}/allocations",
            headers=headers,
            params=params,
        )

    # ---------------------------------------------------- publisher invoices --
    def create_publisher_invoice(self, payload: dict, headers: dict):
        return self._request("POST", "/publisher-invoices", payload, headers)

    def list_publisher_invoices(self, headers: dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/publisher-invoices", headers=headers, params=params
        )

    def get_publisher_invoice(self, invoice_id: str, headers: dict):
        return self._request(
            "GET", f"/publisher-invoices/{invoice_id}", headers=headers
        )

    def validate_publisher_invoice(
        self, invoice_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/publisher-invoices/{invoice_id}/validation",
            payload if payload is not None else {},
            headers,
        )

    def approve_publisher_invoice_payment(
        self, invoice_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/publisher-invoices/{invoice_id}/payment-approval",
            payload if payload is not None else {},
            headers,
        )

    def pay_publisher_invoice(self, invoice_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/publisher-invoices/{invoice_id}/payment", payload, headers
        )

    # ------------------------------------------------- repository deposits ---
    def create_repository_deposit(self, payload: dict, headers: dict):
        return self._request("POST", "/repository-deposits", payload, headers)

    def list_article_deposits(
        self, article_id: str, headers: dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/articles/{article_id}/deposits", headers=headers, params=params
        )

    def get_repository_deposit(self, deposit_id: str, headers: dict):
        return self._request(
            "GET", f"/repository-deposits/{deposit_id}", headers=headers
        )

    def submit_repository_deposit(
        self, deposit_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/repository-deposits/{deposit_id}/submission",
            payload if payload is not None else {},
            headers,
        )

    def decide_repository_deposit_curation(
        self, deposit_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"/repository-deposits/{deposit_id}/curation-decision",
            payload,
            headers,
        )

    # -------------------------------------------------- ops and analytics ----
    def create_compliance_sweep(self, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            "/compliance-sweeps",
            payload if payload is not None else {},
            headers,
        )

    def get_annual_spend(self, headers: dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/analytics/annual-spend", headers=headers, params=params
        )

    def set_clock(self, payload: dict, headers: dict):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
