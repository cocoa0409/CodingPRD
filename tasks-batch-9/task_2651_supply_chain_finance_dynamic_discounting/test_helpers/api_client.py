"""HTTP client for the supply-chain-finance / dynamic-discounting API.

One method per endpoint of the contract. Every method returns the raw
``requests.Response`` so tests can assert on status codes as well as bodies.
"""

from typing import Any, Dict, List, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


def _query(**kwargs: Any) -> Dict[str, Any]:
    """Drop unset (None) query parameters so defaults stay server-side."""
    return {k: v for k, v in kwargs.items() if v is not None}


class ApiClient(GenericApiClient):
    """Endpoint-per-method client."""

    # ─── Buyers ───────────────────────────────────────
    def create_buyer(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/buyers", payload, headers)

    def get_buyer(self, buyer_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/buyers/{buyer_id}", None, headers)

    def list_buyer_programs(
        self,
        buyer_id: str,
        headers: dict,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/buyers/{buyer_id}/programs",
            _query(status=status, limit=limit, offset=offset),
            headers,
        )

    # ─── Buyer programmes ─────────────────────────────
    def create_program(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/buyer-programs", payload, headers)

    def get_program(self, program_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/buyer-programs/{program_id}", None, headers)

    def open_program(self, program_id: str, headers: dict) -> requests.Response:
        return self._request("POST", f"/buyer-programs/{program_id}/open", {}, headers)

    def set_program_status(
        self, program_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/buyer-programs/{program_id}/status", payload, headers
        )

    def get_program_analytics(
        self, program_id: str, headers: dict
    ) -> requests.Response:
        return self._request(
            "GET", f"/buyer-programs/{program_id}/analytics", None, headers
        )

    def list_program_sessions(
        self,
        program_id: str,
        headers: dict,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/buyer-programs/{program_id}/auction-sessions",
            _query(status=status, limit=limit, offset=offset),
            headers,
        )

    def list_program_payable_files(
        self,
        program_id: str,
        headers: dict,
        ingest_status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/buyer-programs/{program_id}/payable-files",
            _query(ingest_status=ingest_status, limit=limit, offset=offset),
            headers,
        )

    # ─── Auction sessions ─────────────────────────────
    def create_session(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/auction-sessions", payload, headers)

    def close_session(
        self, session_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/auction-sessions/{session_id}/close", payload, headers
        )

    # ─── Suppliers ────────────────────────────────────
    def create_supplier(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/suppliers", payload, headers)

    def get_supplier(self, supplier_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/suppliers/{supplier_id}", None, headers)

    def submit_onboarding(self, supplier_id: str, headers: dict) -> requests.Response:
        return self._request(
            "POST", f"/suppliers/{supplier_id}/onboarding/submit", {}, headers
        )

    def adjudicate_idv(
        self, supplier_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/suppliers/{supplier_id}/idv/adjudicate", payload, headers
        )

    def set_sanctions_hold(
        self, supplier_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/suppliers/{supplier_id}/sanctions-hold", payload, headers
        )

    def create_bank_account(
        self, supplier_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/suppliers/{supplier_id}/bank-accounts", payload, headers
        )

    def list_bank_accounts(
        self,
        supplier_id: str,
        headers: dict,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/suppliers/{supplier_id}/bank-accounts",
            _query(status=status, limit=limit, offset=offset),
            headers,
        )

    def confirm_micro_deposit(
        self, bank_account_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/bank-accounts/{bank_account_id}/micro-deposit/confirm",
            payload,
            headers,
        )

    # ─── Approved-payables ingestion ──────────────────
    def create_payable_file(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/payable-files", payload, headers)

    # ─── Invoices ─────────────────────────────────────
    def list_invoices(
        self,
        headers: dict,
        file_id: Optional[str] = None,
        program_id: Optional[str] = None,
        supplier_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            "/invoices",
            _query(
                file_id=file_id,
                program_id=program_id,
                supplier_id=supplier_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def get_invoice(self, invoice_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/invoices/{invoice_id}", None, headers)

    def list_invoice_lines(self, invoice_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/invoices/{invoice_id}/lines", None, headers)

    # ─── Disputes ─────────────────────────────────────
    def create_dispute(
        self, invoice_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/invoices/{invoice_id}/disputes", payload, headers
        )

    def list_invoice_disputes(
        self, invoice_id: str, headers: dict, status: Optional[str] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/invoices/{invoice_id}/disputes", _query(status=status), headers
        )

    def resolve_dispute(
        self, dispute_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/disputes/{dispute_id}/resolve", payload, headers
        )

    # ─── Discount offers ──────────────────────────────
    def create_offer(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/discount-offers", payload, headers)

    def list_offers(
        self,
        headers: dict,
        invoice_id: Optional[str] = None,
        session_id: Optional[str] = None,
        supplier_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            "/discount-offers",
            _query(
                invoice_id=invoice_id,
                session_id=session_id,
                supplier_id=supplier_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def get_offer(self, offer_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/discount-offers/{offer_id}", None, headers)

    def counter_offer(
        self, offer_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/discount-offers/{offer_id}/counter", payload, headers
        )

    def rename_offer(
        self, offer_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/discount-offers/{offer_id}/rename", payload, headers
        )

    def accept_offer(self, offer_id: str, headers: dict) -> requests.Response:
        return self._request(
            "POST", f"/discount-offers/{offer_id}/accept", {}, headers
        )

    # ─── Funders ──────────────────────────────────────
    def create_funder(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/funders", payload, headers)

    def get_funder(self, funder_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/funders/{funder_id}", None, headers)

    def set_funder_participation(
        self, funder_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request("POST", f"/funders/{funder_id}/pause", payload, headers)

    def create_commitment(
        self, funder_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/funders/{funder_id}/commitments", payload, headers
        )

    def list_commitments(
        self,
        funder_id: str,
        headers: dict,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/funders/{funder_id}/commitments",
            _query(status=status, limit=limit, offset=offset),
            headers,
        )

    # ─── Early payments ───────────────────────────────
    def create_early_payment(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/early-payments", payload, headers)

    def list_early_payments(
        self,
        headers: dict,
        offer_id: Optional[str] = None,
        invoice_id: Optional[str] = None,
        funder_id: Optional[str] = None,
        funding_status: Optional[str] = None,
        settlement_status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            "/early-payments",
            _query(
                offer_id=offer_id,
                invoice_id=invoice_id,
                funder_id=funder_id,
                funding_status=funding_status,
                settlement_status=settlement_status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def get_early_payment(self, payment_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/early-payments/{payment_id}", None, headers)

    def execute_early_payment(
        self, payment_id: str, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/early-payments/{payment_id}/execute", {}, headers
        )

    def confirm_settlement(self, payment_id: str, headers: dict) -> requests.Response:
        return self._request(
            "POST", f"/early-payments/{payment_id}/settlement/confirm", {}, headers
        )

    def fail_settlement(
        self, payment_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/early-payments/{payment_id}/settlement/fail", payload, headers
        )

    def classify_accounting(
        self, payment_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/early-payments/{payment_id}/accounting-classification",
            payload,
            headers,
        )

    def list_remittance_advices(
        self, payment_id: str, headers: dict
    ) -> requests.Response:
        return self._request(
            "GET", f"/early-payments/{payment_id}/remittance-advices", None, headers
        )

    # ─── Logical clock (test-driving endpoint) ────────
    def set_clock(self, current_utc: str, headers: dict) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ─── Raw escape hatches for negative shape tests ──
    def raw_post(
        self, path: str, payload: Any, headers: dict
    ) -> requests.Response:
        return self._request("POST", path, payload, headers)

    def raw_get(
        self, path: str, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", path, params, headers)


api_client = ApiClient()
