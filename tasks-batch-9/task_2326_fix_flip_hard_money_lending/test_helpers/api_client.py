"""Typed client covering every endpoint declared in PRD §4.

One method per row of the endpoint table, in table order. Every method takes an
explicit `headers` mapping so that identity is always supplied by the caller,
and returns the raw `requests.Response` for the validators to inspect.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

Headers = Dict[str, str]
Payload = Optional[Dict[str, Any]]
Params = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """Fix-and-flip hard money lending API."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, payload: Payload, headers: Headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---------------------------------------------------------------- borrowers
    def create_borrower(self, payload: Payload, headers: Headers):
        return self._request("POST", "/lending/borrowers", payload, headers)

    def get_borrower(self, borrower_id: str, headers: Headers):
        return self._request("GET", f"/lending/borrowers/{borrower_id}", None, headers)

    def borrower_status_action(
        self, borrower_id: str, payload: Payload, headers: Headers
    ):
        return self._request(
            "POST", f"/lending/borrowers/{borrower_id}/status", payload, headers
        )

    def record_guarantee(self, borrower_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/lending/borrowers/{borrower_id}/guarantee", payload, headers
        )

    # ---------------------------------------------------------------- properties
    def create_property(self, payload: Payload, headers: Headers):
        return self._request("POST", "/lending/properties", payload, headers)

    def get_property(self, property_id: str, headers: Headers):
        return self._request("GET", f"/lending/properties/{property_id}", None, headers)

    def revalue_property(self, property_id: str, payload: Payload, headers: Headers):
        return self._request(
            "PATCH", f"/lending/properties/{property_id}/valuation", payload, headers
        )

    # ---------------------------------------------------------------- applications
    def create_application(self, payload: Payload, headers: Headers):
        return self._request("POST", "/lending/applications", payload, headers)

    def get_application(self, application_id: str, headers: Headers):
        return self._request(
            "GET", f"/lending/applications/{application_id}", None, headers
        )

    def list_applications(self, headers: Headers, params: Params = None):
        return self._request("GET", "/lending/applications", None, headers, params)

    # ---------------------------------------------------------------- scope lines
    def create_rehab_line_item(
        self, application_id: str, payload: Payload, headers: Headers
    ):
        return self._request(
            "POST",
            f"/lending/applications/{application_id}/rehab-line-items",
            payload,
            headers,
        )

    def list_application_rehab_line_items(
        self, application_id: str, headers: Headers, params: Params = None
    ):
        return self._request(
            "GET",
            f"/lending/applications/{application_id}/rehab-line-items",
            None,
            headers,
            params,
        )

    def get_rehab_line_item(self, line_id: str, headers: Headers):
        return self._request(
            "GET", f"/lending/rehab-line-items/{line_id}", None, headers
        )

    def review_rehab_line_item(self, line_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/lending/rehab-line-items/{line_id}/review", payload, headers
        )

    def resubmit_rehab_line_item(self, line_id: str, payload: Payload, headers: Headers):
        return self._request(
            "PATCH", f"/lending/rehab-line-items/{line_id}", payload, headers
        )

    # ---------------------------------------------------------------- origination
    def size_application(self, application_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/lending/applications/{application_id}/size", payload, headers
        )

    def decide_application(
        self, application_id: str, payload: Payload, headers: Headers
    ):
        return self._request(
            "POST", f"/lending/applications/{application_id}/decision", payload, headers
        )

    def close_application(self, application_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/lending/applications/{application_id}/close", payload, headers
        )

    # ---------------------------------------------------------------- contractors
    def create_contractor(self, payload: Payload, headers: Headers):
        return self._request("POST", "/lending/contractors", payload, headers)

    def get_contractor(self, contractor_id: str, headers: Headers):
        return self._request(
            "GET", f"/lending/contractors/{contractor_id}", None, headers
        )

    def list_contractor_rehab_line_items(
        self, contractor_id: str, headers: Headers, params: Params = None
    ):
        return self._request(
            "GET",
            f"/lending/contractors/{contractor_id}/rehab-line-items",
            None,
            headers,
            params,
        )

    def list_contractor_lien_waivers(
        self, contractor_id: str, headers: Headers, params: Params = None
    ):
        return self._request(
            "GET",
            f"/lending/contractors/{contractor_id}/lien-waivers",
            None,
            headers,
            params,
        )

    # ---------------------------------------------------------------- loans
    def get_loan(self, loan_id: str, headers: Headers):
        return self._request("GET", f"/lending/loans/{loan_id}", None, headers)

    def list_loans(self, headers: Headers, params: Params = None):
        return self._request("GET", "/lending/loans", None, headers, params)

    # ---------------------------------------------------------------- draw requests
    def create_draw_request(self, loan_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/lending/loans/{loan_id}/draw-requests", payload, headers
        )

    def list_draw_requests(self, headers: Headers, params: Params = None):
        return self._request("GET", "/lending/draw-requests", None, headers, params)

    def get_draw_request(self, draw_request_id: str, headers: Headers):
        return self._request(
            "GET", f"/lending/draw-requests/{draw_request_id}", None, headers
        )

    def create_inspection_visit(
        self, draw_request_id: str, payload: Payload, headers: Headers
    ):
        return self._request(
            "POST",
            f"/lending/draw-requests/{draw_request_id}/inspection-visits",
            payload,
            headers,
        )

    def list_inspection_visits(
        self, draw_request_id: str, headers: Headers, params: Params = None
    ):
        return self._request(
            "GET",
            f"/lending/draw-requests/{draw_request_id}/inspection-visits",
            None,
            headers,
            params,
        )

    def report_inspection_visit(self, visit_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/lending/inspection-visits/{visit_id}/report", payload, headers
        )

    def photo_verify_draw_request(
        self, draw_request_id: str, payload: Payload, headers: Headers
    ):
        return self._request(
            "POST",
            f"/lending/draw-requests/{draw_request_id}/photo-verification",
            payload,
            headers,
        )

    def review_draw_request(
        self, draw_request_id: str, payload: Payload, headers: Headers
    ):
        return self._request(
            "POST", f"/lending/draw-requests/{draw_request_id}/review", payload, headers
        )

    def fund_draw_request(
        self, draw_request_id: str, payload: Payload, headers: Headers
    ):
        return self._request(
            "POST", f"/lending/draw-requests/{draw_request_id}/fund", payload, headers
        )

    def list_draw_line_items(self, headers: Headers, params: Params = None):
        return self._request("GET", "/lending/draw-line-items", None, headers, params)

    def get_draw_line_item(self, draw_line_item_id: str, headers: Headers):
        return self._request(
            "GET", f"/lending/draw-line-items/{draw_line_item_id}", None, headers
        )

    # ---------------------------------------------------------------- lien waivers
    def create_lien_waiver(self, payload: Payload, headers: Headers):
        return self._request("POST", "/lending/lien-waivers", payload, headers)

    def list_loan_lien_waivers(
        self, loan_id: str, headers: Headers, params: Params = None
    ):
        return self._request(
            "GET", f"/lending/loans/{loan_id}/lien-waivers", None, headers, params
        )

    def dispute_lien_waiver(self, waiver_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/lending/lien-waivers/{waiver_id}/dispute", payload, headers
        )

    # ---------------------------------------------------------------- servicing
    def create_interest_accrual(self, loan_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/lending/loans/{loan_id}/interest-accruals", payload, headers
        )

    def list_interest_periods(
        self, loan_id: str, headers: Headers, params: Params = None
    ):
        return self._request(
            "GET", f"/lending/loans/{loan_id}/interest-periods", None, headers, params
        )

    def list_ledger_entries(self, loan_id: str, headers: Headers, params: Params = None):
        return self._request(
            "GET", f"/lending/loans/{loan_id}/ledger-entries", None, headers, params
        )

    def create_payment(self, loan_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/lending/loans/{loan_id}/payments", payload, headers
        )

    def create_extension(self, loan_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/lending/loans/{loan_id}/extensions", payload, headers
        )

    # ---------------------------------------------------------------- exit monitoring
    def create_exit_milestone(self, loan_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/lending/loans/{loan_id}/exit-milestones", payload, headers
        )

    def list_exit_milestones(
        self, loan_id: str, headers: Headers, params: Params = None
    ):
        return self._request(
            "GET", f"/lending/loans/{loan_id}/exit-milestones", None, headers, params
        )

    # ---------------------------------------------------------------- default / recovery
    def declare_default(self, loan_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/lending/loans/{loan_id}/default-declaration", payload, headers
        )

    def create_foreclosure_case(self, loan_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/lending/loans/{loan_id}/foreclosure-cases", payload, headers
        )

    def list_loan_foreclosure_cases(
        self, loan_id: str, headers: Headers, params: Params = None
    ):
        return self._request(
            "GET", f"/lending/loans/{loan_id}/foreclosure-cases", None, headers, params
        )

    def get_foreclosure_case(self, case_id: str, headers: Headers):
        return self._request(
            "GET", f"/lending/foreclosure-cases/{case_id}", None, headers
        )

    def takeover_foreclosure_case(
        self, case_id: str, payload: Payload, headers: Headers
    ):
        return self._request(
            "POST", f"/lending/foreclosure-cases/{case_id}/takeover", payload, headers
        )

    def set_completion_budget(self, case_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST",
            f"/lending/foreclosure-cases/{case_id}/completion-budget",
            payload,
            headers,
        )

    def dispose_foreclosure_case(
        self, case_id: str, payload: Payload, headers: Headers
    ):
        return self._request(
            "POST", f"/lending/foreclosure-cases/{case_id}/disposition", payload, headers
        )


api_client = ApiClient()
