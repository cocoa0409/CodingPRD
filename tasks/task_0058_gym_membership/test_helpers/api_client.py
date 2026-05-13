"""API client: one method per endpoint defined in PRD §4.

Each method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Card types (PRD §3.1, §4)
    # =======================================================================
    def create_card_type(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/card-types", payload, headers)

    def list_card_types(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/card-types", headers=headers, params=params,
        )

    def patch_card_type(self, card_type_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/card-types/{card_type_id}", payload, headers,
        )

    # =======================================================================
    # Members (PRD §3.1, §3.3, §3.4)
    # =======================================================================
    def create_member(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/members/{member_id}", headers=headers,
        )

    def patch_member(self, member_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/members/{member_id}", payload, headers,
        )

    def recharge_wallet(self, member_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/members/{member_id}/wallet/recharge",
            payload, headers,
        )

    def wallet_quote(self, member_id: str, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/members/{member_id}/wallet/quote",
            headers=headers, params=params,
        )

    def list_wallet_transactions(self, member_id: str,
                                 headers: Dict[str, str],
                                 params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/members/{member_id}/wallet/transactions",
            headers=headers, params=params,
        )

    # =======================================================================
    # Cards (PRD §3.2, §3.5, §3.6, §3.7)
    # =======================================================================
    def issue_card(self, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request("POST", "/cards", payload, headers)

    def get_card(self, card_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/cards/{card_id}", headers=headers,
        )

    def list_cards(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/cards", headers=headers, params=params,
        )

    def activate_card(self, card_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/cards/{card_id}/activate",
            payload or {}, headers,
        )

    def freeze_card(self, card_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/cards/{card_id}/freeze", payload, headers,
        )

    def unfreeze_card(self, card_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/cards/{card_id}/unfreeze", payload, headers,
        )

    def refund_card(self, card_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/cards/{card_id}/refund",
            payload or {}, headers,
        )

    def get_refund_preview(self, card_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/cards/{card_id}/refund-preview", headers=headers,
        )

    def transfer_card(self, card_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/cards/{card_id}/transfer", payload, headers,
        )

    def get_renewal_quote(self, card_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/cards/{card_id}/renewal-quote", headers=headers,
        )

    def send_reminder(self, card_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/cards/{card_id}/send-reminder", payload, headers,
        )

    # =======================================================================
    # Trainers (PRD §3.8)
    # =======================================================================
    def create_trainer(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/trainers", payload, headers)

    def get_trainer(self, trainer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/trainers/{trainer_id}", headers=headers,
        )

    def patch_trainer(self, trainer_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/trainers/{trainer_id}", payload, headers,
        )

    def create_trainer_slot(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", "/trainer-slots", payload, headers)

    def list_trainer_slots(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/trainer-slots", headers=headers, params=params,
        )

    # =======================================================================
    # PT bookings and packages (PRD §3.8)
    # =======================================================================
    def create_pt_booking(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/pt-bookings", payload, headers)

    def cancel_pt_booking(self, booking_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/pt-bookings/{booking_id}/cancel",
            payload or {}, headers,
        )

    def complete_pt_booking(self, booking_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/pt-bookings/{booking_id}/complete",
            payload or {}, headers,
        )

    def no_show_pt_booking(self, booking_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/pt-bookings/{booking_id}/no-show",
            payload or {}, headers,
        )

    def create_pt_package(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/pt-packages", payload, headers)

    def refund_pt_package(self, package_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/pt-packages/{package_id}/refund",
            payload or {}, headers,
        )

    # =======================================================================
    # Group classes and bookings (PRD §3.9)
    # =======================================================================
    def create_group_class(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/group-classes", payload, headers)

    def patch_group_class(self, class_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/group-classes/{class_id}", payload, headers,
        )

    def cancel_group_class(self, class_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/group-classes/{class_id}/cancel",
            payload or {}, headers,
        )

    def create_group_booking(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST", "/group-bookings", payload, headers)

    def cancel_group_booking(self, booking_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/group-bookings/{booking_id}/cancel",
            payload or {}, headers,
        )

    def check_in_group_booking(self, booking_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/group-bookings/{booking_id}/check-in",
            payload or {}, headers,
        )

    # =======================================================================
    # Access events (PRD §3.10)
    # =======================================================================
    def create_access_event(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", "/access-events", payload, headers)

    # =======================================================================
    # Payouts (PRD §3.11)
    # =======================================================================
    def open_payout(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/payouts", payload, headers)

    def close_payout(self, cycle_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/payouts/{cycle_id}/close",
            payload or {}, headers,
        )

    def list_trainer_commissions(self, trainer_id: str,
                                 headers: Dict[str, str],
                                 params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/trainers/{trainer_id}/commissions",
            headers=headers, params=params,
        )

    # =======================================================================
    # Test-driving endpoints (PRD §3.12, §2.10)
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def run_sweep(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/run", payload or {}, headers,
        )

    def emit_event(self, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request("POST", "/_events/emit", payload, headers)

    def list_audit_log(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-log", headers=headers, params=params,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
