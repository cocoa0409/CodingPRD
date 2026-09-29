"""
Typed HTTP client for the Prepaid Restaurant Ticketing API.

One method per endpoint of the PRD's endpoint table. Every method returns the
raw ``requests.Response`` so tests can assert on status codes as well as
bodies. Paths carry no version or namespace prefix, exactly as the PRD states:
"Every endpoint below is served under the API root with no version or namespace
prefix."
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per declared endpoint."""

    # ─── restaurants ──────────────────────────────────────────────────────

    def create_restaurant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/restaurants", payload, headers)

    def get_restaurant(self, restaurant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/restaurants/{restaurant_id}", None, headers)

    def list_restaurants(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/restaurants", params, headers)

    def list_restaurant_tables(
        self, restaurant_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/restaurants/{restaurant_id}/tables", params, headers
        )

    def list_restaurant_packages(
        self, restaurant_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/restaurants/{restaurant_id}/experience-packages", params, headers
        )

    def list_restaurant_add_ons(
        self, restaurant_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/restaurants/{restaurant_id}/add-ons", params, headers
        )

    def list_restaurant_services(
        self, restaurant_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/restaurants/{restaurant_id}/services", params, headers
        )

    # ─── tables ───────────────────────────────────────────────────────────

    def create_table(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/tables", payload, headers)

    def get_table(self, table_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/tables/{table_id}", None, headers)

    # ─── experience packages ──────────────────────────────────────────────

    def create_package(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/experience-packages", payload, headers)

    def get_package(self, package_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/experience-packages/{package_id}", None, headers
        )

    # ─── add-ons ──────────────────────────────────────────────────────────

    def create_add_on(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/add-ons", payload, headers)

    def get_add_on(self, add_on_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/add-ons/{add_on_id}", None, headers)

    # ─── guests ───────────────────────────────────────────────────────────

    def create_guest(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/guests", payload, headers)

    def get_guest(self, guest_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/guests/{guest_id}", None, headers)

    def list_guests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/guests", params, headers)

    # ─── services ─────────────────────────────────────────────────────────

    def create_service(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/services", payload, headers)

    def get_service(self, service_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/services/{service_id}", None, headers)

    def list_services(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/services", params, headers)

    def publish_service(
        self, service_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/services/{service_id}/publish", payload or {}, headers
        )

    def set_demand_tier(
        self, service_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/services/{service_id}/demand-tier", payload, headers
        )

    def cancel_service(
        self, service_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/services/{service_id}/cancel", payload or {}, headers
        )

    def release_run(
        self, service_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/services/{service_id}/release-run", payload or {}, headers
        )

    def hold_sweep(
        self, service_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/services/{service_id}/hold-sweep", payload or {}, headers
        )

    # ─── ticket classes ───────────────────────────────────────────────────

    def create_ticket_class(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/ticket-classes", payload, headers)

    def get_ticket_class(self, ticket_class_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/ticket-classes/{ticket_class_id}", None, headers
        )

    def list_ticket_classes(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/ticket-classes", params, headers)

    def price_quote(self, ticket_class_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/ticket-classes/{ticket_class_id}/price-quote", None, headers
        )

    def pause_ticket_class(
        self,
        ticket_class_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ):
        return self._request(
            "POST", f"/ticket-classes/{ticket_class_id}/pause", payload or {}, headers
        )

    def resume_ticket_class(
        self,
        ticket_class_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ):
        return self._request(
            "POST", f"/ticket-classes/{ticket_class_id}/resume", payload or {}, headers
        )

    # ─── reservations ─────────────────────────────────────────────────────

    def create_reservation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/reservations", payload, headers)

    def get_reservation(self, reservation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/reservations/{reservation_id}", None, headers)

    def list_reservations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/reservations", params, headers)

    def list_reservation_dietary_notes(
        self,
        reservation_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET", f"/reservations/{reservation_id}/dietary-notes", params, headers
        )

    def take_payment(
        self, reservation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/reservations/{reservation_id}/payments", payload, headers
        )

    def confirm_reservation(
        self,
        reservation_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ):
        return self._request(
            "POST", f"/reservations/{reservation_id}/confirm", payload or {}, headers
        )

    def append_add_on_line(
        self, reservation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/reservations/{reservation_id}/add-ons", payload, headers
        )

    def create_dietary_note(
        self, reservation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/reservations/{reservation_id}/dietary-notes", payload, headers
        )

    def assign_table(
        self, reservation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/reservations/{reservation_id}/assign-table", payload, headers
        )

    def seat_reservation(
        self,
        reservation_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ):
        return self._request(
            "POST", f"/reservations/{reservation_id}/seat", payload or {}, headers
        )

    def complete_reservation(
        self,
        reservation_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ):
        return self._request(
            "POST", f"/reservations/{reservation_id}/complete", payload or {}, headers
        )

    def declare_no_show(
        self,
        reservation_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ):
        return self._request(
            "POST", f"/reservations/{reservation_id}/no-show", payload or {}, headers
        )

    def cancel_reservation(
        self,
        reservation_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ):
        return self._request(
            "POST", f"/reservations/{reservation_id}/cancel", payload or {}, headers
        )

    def change_name(
        self, reservation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/reservations/{reservation_id}/name-change", payload, headers
        )

    def transfer_reservation(
        self, reservation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/reservations/{reservation_id}/transfer", payload, headers
        )

    # ─── reservation add-on lines ─────────────────────────────────────────

    def get_reservation_add_on(self, line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/reservation-add-ons/{line_id}", None, headers)

    def list_reservation_add_ons(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/reservation-add-ons", params, headers)

    # ─── dietary notes ────────────────────────────────────────────────────

    def get_dietary_note(self, note_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/dietary-notes/{note_id}", None, headers)

    def ack_dietary_note(
        self, note_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/dietary-notes/{note_id}/ack", payload, headers)

    def amend_dietary_note(
        self, note_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/dietary-notes/{note_id}/amend", payload, headers
        )

    # ─── ledger ───────────────────────────────────────────────────────────

    def get_payment_transaction(self, transaction_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/payment-transactions/{transaction_id}", None, headers
        )

    def list_payment_transactions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/payment-transactions", params, headers)

    # ─── waitlist ─────────────────────────────────────────────────────────

    def create_waitlist_entry(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/waitlist-entries", payload, headers)

    def get_waitlist_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/waitlist-entries/{entry_id}", None, headers)

    def list_waitlist_entries(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/waitlist-entries", params, headers)

    def claim_waitlist_entry(
        self, entry_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/waitlist-entries/{entry_id}/claim", payload or {}, headers
        )

    def withdraw_waitlist_entry(
        self, entry_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/waitlist-entries/{entry_id}/withdraw", payload or {}, headers
        )

    # ─── refund exceptions ────────────────────────────────────────────────

    def create_refund_exception(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/refund-exceptions", payload, headers)

    def get_refund_exception(self, exception_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/refund-exceptions/{exception_id}", None, headers
        )

    def list_refund_exceptions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/refund-exceptions", params, headers)

    def decide_refund_exception(
        self, exception_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/refund-exceptions/{exception_id}/decide", payload, headers
        )

    # ─── goodwill credits ─────────────────────────────────────────────────

    def create_goodwill_credit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/goodwill-credits", payload, headers)

    def get_goodwill_credit(self, credit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/goodwill-credits/{credit_id}", None, headers)

    def list_goodwill_credits(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/goodwill-credits", params, headers)

    def redeem_goodwill_credit(
        self, credit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/goodwill-credits/{credit_id}/redemptions", payload, headers
        )

    def revoke_goodwill_credit(
        self, credit_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/goodwill-credits/{credit_id}/revoke", payload or {}, headers
        )

    # ─── logical clock ────────────────────────────────────────────────────

    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )
