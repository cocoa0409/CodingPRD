"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles the
HTTP plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Lots (PRD §3.1)
    # =======================================================================
    def create_lot(self, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request("POST", "/lots", payload, headers)

    def get_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def list_lots(self, headers: Dict[str, str],
                  params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/lots", headers=headers, params=params)

    def announce_lot(self, lot_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/lots/{lot_id}/announce", payload or {}, headers,
        )

    def add_inspection_window(self, lot_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/lots/{lot_id}/inspection-windows", payload, headers,
        )

    def withdraw_lot(self, lot_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/lots/{lot_id}/withdraw", payload or {}, headers,
        )

    # =======================================================================
    # Bidder accounts (PRD §3.2)
    # =======================================================================
    def create_bidder_account(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", "/bidder-accounts", payload, headers)

    def get_bidder_account(self, account_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/bidder-accounts/{account_id}", headers=headers,
        )

    def clear_bidder_account(self, account_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/bidder-accounts/{account_id}/clear", payload, headers,
        )

    # =======================================================================
    # Auctions (PRD §3.5)
    # =======================================================================
    def get_auction(self, auction_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/auctions/{auction_id}", headers=headers,
        )

    def open_auction(self, auction_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/auctions/{auction_id}/open", payload or {}, headers,
        )

    def cancel_auction(self, auction_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/auctions/{auction_id}/cancel", payload, headers,
        )

    def list_auction_bids(self, auction_id: str, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/auctions/{auction_id}/bids",
            headers=headers, params=params,
        )

    def system_rollback(self, auction_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/auctions/{auction_id}/system-rollback",
            payload, headers,
        )

    # =======================================================================
    # Deposits (PRD §3.4, §3.10)
    # =======================================================================
    def create_deposit(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/deposits", payload, headers)

    def pay_deposit(self, deposit_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/deposits/{deposit_id}/pay", payload or {}, headers,
        )

    def raise_deposit_dispute(self, deposit_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/deposits/{deposit_id}/raise-dispute",
            payload or {}, headers,
        )

    def resolve_deposit_dispute(self, deposit_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/deposits/{deposit_id}/resolve-dispute",
            payload or {}, headers,
        )

    # =======================================================================
    # Bids (PRD §3.5)
    # =======================================================================
    def create_bid(self, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request("POST", "/bids", payload, headers)

    # =======================================================================
    # Confirmations (PRD §3.8)
    # =======================================================================
    def create_confirmation(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", "/confirmations", payload, headers)

    def issue_confirmation(self, confirmation_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/confirmations/{confirmation_id}/issue",
            payload or {}, headers,
        )

    def fail_confirmation(self, confirmation_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/confirmations/{confirmation_id}/fail",
            payload, headers,
        )

    def seal_confirmation(self, confirmation_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/confirmations/{confirmation_id}/seal",
            payload or {}, headers,
        )

    # =======================================================================
    # Payments (PRD §3.9)
    # =======================================================================
    def get_payment(self, payment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/payments/{payment_id}", headers=headers,
        )

    def settle_payment(self, payment_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/payments/{payment_id}/settle", payload, headers,
        )

    def extend_payment(self, payment_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/payments/{payment_id}/extend", payload, headers,
        )

    def forfeit_payment(self, payment_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/payments/{payment_id}/forfeit", payload or {}, headers,
        )

    # =======================================================================
    # Transfer orders (PRD §3.11)
    # =======================================================================
    def create_transfer_order(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", "/transfer-orders", payload, headers)

    def notify_agency(self, transfer_order_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/transfer-orders/{transfer_order_id}/notify-agency",
            payload or {}, headers,
        )

    def complete_handover(self, transfer_order_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/transfer-orders/{transfer_order_id}/complete-handover",
            payload or {}, headers,
        )

    def confirm_transfer_completion(self, transfer_order_id: str,
                                    headers: Dict[str, str],
                                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/transfer-orders/{transfer_order_id}/confirm-completion",
            payload or {}, headers,
        )

    def block_transfer(self, transfer_order_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/transfer-orders/{transfer_order_id}/block",
            payload, headers,
        )

    # =======================================================================
    # Audit events (PRD §3.12)
    # =======================================================================
    def list_audit_events(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-events", headers=headers, params=params,
        )

    # =======================================================================
    # Test-driving endpoints (PRD §3.5, §3.10, §3.12)
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def sweep_refunds(self, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/refunds", payload or {}, headers,
        )

    def events_emit(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/_events/emit", payload, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
