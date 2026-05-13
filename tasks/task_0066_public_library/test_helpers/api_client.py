"""API client for the Public Library API.

One method per endpoint defined in PRD §4. All endpoints are mounted under the
/library URL prefix per PRD §1. Inherits _request from GenericApiClient.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Concrete client; every method returns the raw requests.Response."""

    # ──────────────── Book titles & copies ────────────────

    def create_book_title(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/library/book-titles", payload, headers)

    def list_book_titles(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/library/book-titles", headers=headers, params=params)

    def get_book_title(self, book_title_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/library/book-titles/{book_title_id}", headers=headers
        )

    def create_copy(
        self, book_title_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/library/book-titles/{book_title_id}/copies", payload, headers
        )

    def list_copies(
        self,
        book_title_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/library/book-titles/{book_title_id}/copies",
            headers=headers,
            params=params,
        )

    def weed_copy(
        self, copy_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/library/copies/{copy_id}/weed", payload, headers
        )

    # ──────────────── Readers & cards ────────────────

    def create_reader(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/library/readers", payload, headers)

    def get_reader(self, reader_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/library/readers/{reader_id}", headers=headers)

    def issue_card(
        self, reader_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/library/readers/{reader_id}/cards", payload, headers
        )

    def freeze_card(
        self,
        card_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/library/cards/{card_id}/freeze", payload or {}, headers
        )

    def unfreeze_card(
        self,
        card_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/library/cards/{card_id}/unfreeze", payload or {}, headers
        )

    def reissue_card(
        self, card_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/library/cards/{card_id}/reissue", payload, headers
        )

    def get_quota(
        self,
        card_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET", f"/library/cards/{card_id}/quota", headers=headers, params=params
        )

    def blacklist_reader(
        self, reader_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/library/readers/{reader_id}/blacklist", payload, headers
        )

    def unblacklist_reader(
        self,
        reader_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/library/readers/{reader_id}/unblacklist",
            payload or {},
            headers,
        )

    # ──────────────── Loans (borrow / renew / recall / return) ────────────────

    def create_loan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/library/loans", payload, headers)

    def get_loan(self, loan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/library/loans/{loan_id}", headers=headers)

    def renew_loan(
        self,
        loan_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/library/loans/{loan_id}/renew", payload or {}, headers
        )

    def recall_loan(
        self, loan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/library/loans/{loan_id}/recall", payload, headers
        )

    def return_loan(
        self,
        loan_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/library/loans/{loan_id}/return", payload or {}, headers
        )

    # ──────────────── Reservations ────────────────

    def create_reservation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/library/reservations", payload, headers)

    def get_reservation(self, reservation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/library/reservations/{reservation_id}", headers=headers
        )

    def cancel_reservation(
        self,
        reservation_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "DELETE",
            f"/library/reservations/{reservation_id}",
            payload or {},
            headers,
        )

    # ──────────────── Fines ────────────────

    def get_fine(self, fine_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/library/fines/{fine_id}", headers=headers)

    def pay_fine(
        self, fine_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/library/fines/{fine_id}/pay", payload, headers
        )

    def waive_fine(
        self, fine_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/library/fines/{fine_id}/waive", payload, headers
        )

    # ──────────────── ILL ────────────────

    def create_ill_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/library/ill-requests", payload, headers)

    def approve_ill(
        self,
        ill_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/library/ill-requests/{ill_id}/approve",
            payload or {},
            headers,
        )

    def reject_ill(
        self, ill_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/library/ill-requests/{ill_id}/reject", payload, headers
        )

    def dispatch_ill(
        self, ill_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/library/ill-requests/{ill_id}/dispatch", payload, headers
        )

    def return_received_ill(
        self,
        ill_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/library/ill-requests/{ill_id}/return-received",
            payload or {},
            headers,
        )

    # ──────────────── Acquisition suggestions ────────────────

    def create_suggestion(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", "/library/acquisition-suggestions", payload, headers
        )

    def start_review_suggestion(
        self,
        suggestion_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/library/acquisition-suggestions/{suggestion_id}/start-review",
            payload or {},
            headers,
        )

    def decide_suggestion(
        self,
        suggestion_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/library/acquisition-suggestions/{suggestion_id}/decide",
            payload,
            headers,
        )

    def get_suggestion_stats(self, headers: Dict[str, str]):
        return self._request(
            "GET", "/library/acquisition-suggestions/stats", headers=headers
        )

    # ──────────────── Audit logs ────────────────

    def list_audit_logs(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/library/audit-logs", headers=headers, params=params
        )

    # ──────────────── Test-driving endpoints (Admin-only per PRD §2.12) ────

    def advance_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", "/library/_clock/advance", payload, headers
        )

    def run_sweep(
        self,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", "/library/_sweep/run", payload or {}, headers
        )

    def emit_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", "/library/_events/emit", payload, headers
        )


api_client = ApiClient()
