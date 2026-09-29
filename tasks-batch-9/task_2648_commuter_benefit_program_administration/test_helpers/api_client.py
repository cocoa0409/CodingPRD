"""Typed API client: one method per endpoint of the commuter benefit service."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class CommuterBenefitApiClient(GenericApiClient):
    """One method per documented endpoint; every method returns the raw response."""

    # ---------------------------------------------------------------- clock ----
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------- employers ---
    def create_employer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/benefits/employers", payload, headers)

    def get_employer(self, employer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/benefits/employers/{employer_id}", None, headers)

    def list_employers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/benefits/employers", params, headers)

    def patch_employer(
        self, employer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/benefits/employers/{employer_id}", payload, headers
        )

    def activate_employer(self, employer_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/benefits/employers/{employer_id}/activate", {}, headers
        )

    def month_close_employer(
        self, employer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/benefits/employers/{employer_id}/month-close", payload, headers
        )

    def create_compliance_assessment(
        self, employer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/benefits/employers/{employer_id}/compliance-assessments",
            payload,
            headers,
        )

    def list_employer_compliance_assessments(
        self, employer_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/benefits/employers/{employer_id}/compliance-assessments",
            params,
            headers,
        )

    def get_compliance_assessment(self, assessment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/benefits/compliance-assessments/{assessment_id}", None, headers
        )

    def list_compliance_assessments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/benefits/compliance-assessments", params, headers
        )

    # ------------------------------------------------------ benefit categories -
    def create_benefit_category(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/benefits/benefit-categories", payload, headers)

    def get_benefit_category(self, category_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/benefits/benefit-categories/{category_id}", None, headers
        )

    def list_benefit_categories(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/benefits/benefit-categories", params, headers)

    def retire_benefit_category(self, category_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/benefits/benefit-categories/{category_id}/retire", {}, headers
        )

    # ------------------------------------------------------------- employees ---
    def create_employee(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/benefits/employees", payload, headers)

    def get_employee(self, employee_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/benefits/employees/{employee_id}", None, headers)

    def list_employees(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/benefits/employees", params, headers)

    def terminate_employee(
        self, employee_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/benefits/employees/{employee_id}/terminate", payload, headers
        )

    # ---------------------------------------------------------- transit media --
    def create_transit_media(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/benefits/transit-media", payload, headers)

    def get_transit_media(self, media_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/benefits/transit-media/{media_id}", None, headers
        )

    def list_transit_media(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/benefits/transit-media", params, headers)

    def discontinue_transit_media(self, media_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/benefits/transit-media/{media_id}/discontinue", {}, headers
        )

    # -------------------------------------------------------- election windows -
    def create_election_window(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/benefits/election-windows", payload, headers)

    def get_election_window(self, window_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/benefits/election-windows/{window_id}", None, headers
        )

    def list_election_windows(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/benefits/election-windows", params, headers)

    def open_election_window(self, window_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/benefits/election-windows/{window_id}/open", {}, headers
        )

    def lock_election_window(self, window_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/benefits/election-windows/{window_id}/lock", {}, headers
        )

    # --------------------------------------------------------- benefit accounts
    def create_benefit_account(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/benefits/benefit-accounts", payload, headers)

    def get_benefit_account(self, account_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/benefits/benefit-accounts/{account_id}", None, headers
        )

    def list_benefit_accounts(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/benefits/benefit-accounts", params, headers)

    def list_account_ledger_entries(
        self, account_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/benefits/benefit-accounts/{account_id}/ledger-entries",
            params,
            headers,
        )

    def get_ledger_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/benefits/ledger-entries/{entry_id}", None, headers
        )

    def list_ledger_entries(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/benefits/ledger-entries", params, headers)

    # -------------------------------------------------------------- elections --
    def create_election(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/benefits/elections", payload, headers)

    def get_election(self, election_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/benefits/elections/{election_id}", None, headers)

    def list_elections(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/benefits/elections", params, headers)

    def patch_election(
        self, election_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/benefits/elections/{election_id}", payload, headers
        )

    def cancel_election(self, election_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/benefits/elections/{election_id}/cancel", {}, headers
        )

    def reverse_election_funding(
        self, election_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/benefits/elections/{election_id}/reverse-funding",
            payload,
            headers,
        )

    # ----------------------------------------------------------- order batches -
    def create_order_batch(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/benefits/order-batches", payload, headers)

    def get_order_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/benefits/order-batches/{batch_id}", None, headers
        )

    def list_order_batches(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/benefits/order-batches", params, headers)

    def seal_order_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/benefits/order-batches/{batch_id}/seal", {}, headers
        )

    def release_order_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/benefits/order-batches/{batch_id}/release", {}, headers
        )

    # ------------------------------------------------------------ media orders -
    def create_media_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/benefits/media-orders", payload, headers)

    def get_media_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/benefits/media-orders/{order_id}", None, headers
        )

    def list_media_orders(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/benefits/media-orders", params, headers)

    def ship_media_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/benefits/media-orders/{order_id}/ship", payload, headers
        )

    def confirm_media_order_delivery(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/benefits/media-orders/{order_id}/confirm-delivery", {}, headers
        )

    def report_media_order_undelivered(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/benefits/media-orders/{order_id}/report-undelivered",
            payload,
            headers,
        )

    def reissue_media_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/benefits/media-orders/{order_id}/reissue", payload, headers
        )

    # -------------------------------------------------------- card transactions
    def create_card_transaction(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/benefits/card-transactions", payload, headers)

    def get_card_transaction(self, transaction_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/benefits/card-transactions/{transaction_id}", None, headers
        )

    def list_card_transactions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/benefits/card-transactions", params, headers)

    def deny_substantiation(
        self, transaction_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/benefits/card-transactions/{transaction_id}/deny-substantiation",
            payload,
            headers,
        )

    def reopen_card_transaction(
        self, transaction_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/benefits/card-transactions/{transaction_id}/reopen",
            payload,
            headers,
        )

    # --------------------------------------------------- substantiation claims -
    def create_substantiation_claim(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", "/benefits/substantiation-claims", payload, headers
        )

    def get_substantiation_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/benefits/substantiation-claims/{claim_id}", None, headers
        )

    def list_substantiation_claims(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/benefits/substantiation-claims", params, headers
        )

    def approve_substantiation_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/benefits/substantiation-claims/{claim_id}/approve",
            {},
            headers,
        )

    def reject_substantiation_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/benefits/substantiation-claims/{claim_id}/reject",
            payload,
            headers,
        )

    # ----------------------------------------------------------- payroll files -
    def create_payroll_file(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/benefits/payroll-files", payload, headers)

    def get_payroll_file(self, file_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/benefits/payroll-files/{file_id}", None, headers
        )

    def list_payroll_files(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/benefits/payroll-files", params, headers)

    def generate_payroll_file(self, file_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/benefits/payroll-files/{file_id}/generate", {}, headers
        )

    def transmit_payroll_file(self, file_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/benefits/payroll-files/{file_id}/transmit", {}, headers
        )

    def acknowledge_payroll_file(
        self, file_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/benefits/payroll-files/{file_id}/acknowledge", payload, headers
        )

    # ------------------------------------------------------------------ raw ----
    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        """Escape hatch for role-matrix probes that iterate over raw paths."""
        return self._request(method, path, payload, headers, params)


ApiClient = CommuterBenefitApiClient
