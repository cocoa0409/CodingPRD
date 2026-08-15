"""API client: one method per endpoint defined in PRD §4."""
import time
from typing import Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

# Transient transport failures (connection reset / broken mid-response) can
# occur under per-test-server isolation when a freshly restarted server dies
# to an external SIGTERM before it serves its first requests. Every test builds
# its own state from scratch through this client, and a request that never
# reached a live server has no side effects (storage is in-memory and per
# boot), so retrying against the recovered server is safe.
_TRANSIENT_RETRIES = 6
_TRANSIENT_BACKOFF_S = 0.25


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        attempt = 0
        while True:
            try:
                return super()._request(
                    method, path, payload=payload, headers=headers, params=params,
                )
            except (requests.ConnectionError, requests.ChunkedEncodingError):
                attempt += 1
                if attempt > _TRANSIENT_RETRIES:
                    raise
                time.sleep(_TRANSIENT_BACKOFF_S * attempt)
    # --- house clock ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- artists ---
    def create_artist(self, payload: Dict, headers: Dict):
        return self._request("POST", "/artists", payload, headers)

    def get_artist(self, artist_id: str, headers: Dict):
        return self._request("GET", f"/artists/{artist_id}", headers=headers)

    def list_artists(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/artists", headers=headers, params=params)

    # --- booking agents ---
    def create_booking_agent(self, payload: Dict, headers: Dict):
        return self._request("POST", "/booking-agents", payload, headers)

    def get_booking_agent(self, agent_id: str, headers: Dict):
        return self._request("GET", f"/booking-agents/{agent_id}", headers=headers)

    # --- shows ---
    def create_show(self, payload: Dict, headers: Dict):
        return self._request("POST", "/shows", payload, headers)

    def get_show(self, show_id: str, headers: Dict):
        return self._request("GET", f"/shows/{show_id}", headers=headers)

    def list_shows(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/shows", headers=headers, params=params)

    # --- date holds ---
    def get_date_hold(self, hold_id: str, headers: Dict):
        return self._request("GET", f"/date-holds/{hold_id}", headers=headers)

    def list_date_holds(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/date-holds", headers=headers, params=params)

    def create_date_hold(self, show_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/shows/{show_id}/date-holds", payload, headers)

    def list_show_date_holds(self, show_id: str, headers: Dict,
                             params: Optional[Dict] = None):
        return self._request(
            "GET", f"/shows/{show_id}/date-holds", headers=headers, params=params,
        )

    def get_show_date_hold(self, show_id: str, hold_id: str, headers: Dict):
        return self._request(
            "GET", f"/shows/{show_id}/date-holds/{hold_id}", headers=headers,
        )

    def challenge_date_hold(self, show_id: str, hold_id: str, payload: Dict,
                            headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/date-holds/{hold_id}/challenge",
            payload, headers,
        )

    def confirm_date_hold(self, show_id: str, hold_id: str, payload: Dict,
                          headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/date-holds/{hold_id}/confirm",
            payload, headers,
        )

    def release_date_hold(self, show_id: str, hold_id: str, headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/date-holds/{hold_id}/release", {}, headers,
        )

    # --- offers ---
    def get_offer(self, offer_id: str, headers: Dict):
        return self._request("GET", f"/offers/{offer_id}", headers=headers)

    def list_offers(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/offers", headers=headers, params=params)

    def create_offer(self, show_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/shows/{show_id}/offers", payload, headers)

    def list_show_offers(self, show_id: str, headers: Dict,
                         params: Optional[Dict] = None):
        return self._request(
            "GET", f"/shows/{show_id}/offers", headers=headers, params=params,
        )

    def get_show_offer(self, show_id: str, offer_id: str, headers: Dict):
        return self._request(
            "GET", f"/shows/{show_id}/offers/{offer_id}", headers=headers,
        )

    def counter_offer(self, show_id: str, offer_id: str, payload: Dict,
                      headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/offers/{offer_id}/counter", payload, headers,
        )

    def accept_offer(self, show_id: str, offer_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/offers/{offer_id}/accept", payload, headers,
        )

    def reject_offer(self, show_id: str, offer_id: str, headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/offers/{offer_id}/reject", {}, headers,
        )

    def withdraw_offer(self, show_id: str, offer_id: str, headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/offers/{offer_id}/withdraw", {}, headers,
        )

    # --- deals ---
    def get_show_deal(self, show_id: str, headers: Dict):
        return self._request("GET", f"/shows/{show_id}/deal", headers=headers)

    def get_deal(self, deal_id: str, headers: Dict):
        return self._request("GET", f"/deals/{deal_id}", headers=headers)

    def list_deals(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/deals", headers=headers, params=params)

    # --- ticket tiers ---
    def create_ticket_tier(self, show_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/shows/{show_id}/ticket-tiers", payload, headers)

    def list_ticket_tiers(self, show_id: str, headers: Dict,
                          params: Optional[Dict] = None):
        return self._request(
            "GET", f"/shows/{show_id}/ticket-tiers", headers=headers, params=params,
        )

    def get_ticket_tier(self, show_id: str, tier_id: str, headers: Dict):
        return self._request(
            "GET", f"/shows/{show_id}/ticket-tiers/{tier_id}", headers=headers,
        )

    # --- on-sale ---
    def place_on_sale(self, show_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/shows/{show_id}/on-sale", payload, headers)

    # --- ticket sales ---
    def get_ticket_sale(self, sale_id: str, headers: Dict):
        return self._request("GET", f"/ticket-sales/{sale_id}", headers=headers)

    def list_ticket_sales(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/ticket-sales", headers=headers, params=params)

    def create_ticket_sale(self, show_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/shows/{show_id}/ticket-sales", payload, headers)

    def list_show_ticket_sales(self, show_id: str, headers: Dict,
                               params: Optional[Dict] = None):
        return self._request(
            "GET", f"/shows/{show_id}/ticket-sales", headers=headers, params=params,
        )

    def get_show_ticket_sale(self, show_id: str, sale_id: str, headers: Dict):
        return self._request(
            "GET", f"/shows/{show_id}/ticket-sales/{sale_id}", headers=headers,
        )

    def refund_ticket_sale(self, show_id: str, sale_id: str, headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/ticket-sales/{sale_id}/refund", {}, headers,
        )

    # --- advance checklist ---
    def get_advance_checklist(self, checklist_id: str, headers: Dict):
        return self._request(
            "GET", f"/advance-checklists/{checklist_id}", headers=headers,
        )

    def list_advance_checklists(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/advance-checklists", headers=headers, params=params,
        )

    def get_show_advance(self, show_id: str, headers: Dict):
        return self._request("GET", f"/shows/{show_id}/advance", headers=headers)

    def complete_advance_item(self, show_id: str, item_name: str, headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/advance/items/{item_name}/complete",
            {}, headers,
        )

    def uncomplete_advance_item(self, show_id: str, item_name: str, headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/advance/items/{item_name}/uncomplete",
            {}, headers,
        )

    def complete_advance(self, show_id: str, headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/advance/complete", {}, headers,
        )

    # --- support acts ---
    def create_support_act(self, show_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/shows/{show_id}/support-acts", payload, headers)

    def list_support_acts(self, show_id: str, headers: Dict,
                          params: Optional[Dict] = None):
        return self._request(
            "GET", f"/shows/{show_id}/support-acts", headers=headers, params=params,
        )

    def get_support_act(self, show_id: str, support_act_id: str, headers: Dict):
        return self._request(
            "GET", f"/shows/{show_id}/support-acts/{support_act_id}", headers=headers,
        )

    def buyout_support_act(self, show_id: str, support_act_id: str, headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/support-acts/{support_act_id}/buyout",
            {}, headers,
        )

    def mark_support_act_performed(self, show_id: str, support_act_id: str,
                                   headers: Dict):
        return self._request(
            "POST",
            f"/shows/{show_id}/support-acts/{support_act_id}/mark-performed",
            {}, headers,
        )

    # --- expense receipts ---
    def create_expense_receipt(self, show_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/expense-receipts", payload, headers,
        )

    def list_expense_receipts(self, show_id: str, headers: Dict,
                              params: Optional[Dict] = None):
        return self._request(
            "GET", f"/shows/{show_id}/expense-receipts", headers=headers,
            params=params,
        )

    def get_expense_receipt(self, show_id: str, receipt_id: str, headers: Dict):
        return self._request(
            "GET", f"/shows/{show_id}/expense-receipts/{receipt_id}", headers=headers,
        )

    def approve_expense_receipt(self, show_id: str, receipt_id: str, headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/expense-receipts/{receipt_id}/approve",
            {}, headers,
        )

    def reject_expense_receipt(self, show_id: str, receipt_id: str, payload: Dict,
                               headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/expense-receipts/{receipt_id}/reject",
            payload, headers,
        )

    # --- ancillary revenues ---
    def create_ancillary_revenue(self, show_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/ancillary-revenues", payload, headers,
        )

    def list_ancillary_revenues(self, show_id: str, headers: Dict,
                                params: Optional[Dict] = None):
        return self._request(
            "GET", f"/shows/{show_id}/ancillary-revenues", headers=headers,
            params=params,
        )

    # --- settlement ---
    def get_settlement(self, settlement_id: str, headers: Dict):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def create_settlement(self, show_id: str, headers: Dict):
        return self._request("POST", f"/shows/{show_id}/settlement", {}, headers)

    def get_show_settlement(self, show_id: str, headers: Dict):
        return self._request("GET", f"/shows/{show_id}/settlement", headers=headers)

    def submit_settlement(self, show_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/settlement/submit", payload, headers,
        )

    def approve_settlement(self, show_id: str, headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/settlement/approve", {}, headers,
        )

    def dispute_settlement(self, show_id: str, headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/settlement/dispute", {}, headers,
        )

    def return_settlement_to_draft(self, show_id: str, headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/settlement/return-to-draft", {}, headers,
        )

    # --- wire transfers ---
    def get_wire_transfer(self, wire_id: str, headers: Dict):
        return self._request("GET", f"/wire-transfers/{wire_id}", headers=headers)

    def list_wire_transfers(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/wire-transfers", headers=headers, params=params,
        )

    def create_wire_transfer(self, show_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/wire-transfers", payload, headers,
        )

    def list_show_wire_transfers(self, show_id: str, headers: Dict,
                                 params: Optional[Dict] = None):
        return self._request(
            "GET", f"/shows/{show_id}/wire-transfers", headers=headers,
            params=params,
        )

    def get_show_wire_transfer(self, show_id: str, wire_id: str, headers: Dict):
        return self._request(
            "GET", f"/shows/{show_id}/wire-transfers/{wire_id}", headers=headers,
        )

    def complete_wire_transfer(self, show_id: str, wire_id: str, headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/wire-transfers/{wire_id}/complete",
            {}, headers,
        )

    def fail_wire_transfer(self, show_id: str, wire_id: str, payload: Dict,
                           headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/wire-transfers/{wire_id}/fail",
            payload, headers,
        )

    def retry_wire_transfer(self, show_id: str, wire_id: str, headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/wire-transfers/{wire_id}/retry", {}, headers,
        )

    def mark_wire_transfer_returned(self, show_id: str, wire_id: str, headers: Dict):
        return self._request(
            "POST", f"/shows/{show_id}/wire-transfers/{wire_id}/mark-returned",
            {}, headers,
        )

    # --- cancellation & postpone ---
    def cancel_show(self, show_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/shows/{show_id}/cancel", payload, headers)

    def list_cancellation_events(self, show_id: str, headers: Dict,
                                 params: Optional[Dict] = None):
        return self._request(
            "GET", f"/shows/{show_id}/cancellation-events", headers=headers,
            params=params,
        )

    def postpone_show(self, show_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/shows/{show_id}/postpone", payload, headers)


api_client = ApiClient()
