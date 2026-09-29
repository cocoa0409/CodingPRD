"""One typed method per endpoint of the clearinghouse API surface.

Every method returns the raw response so the caller decides whether it is a
success, a paginated page or an error. Paths are served exactly as the PRD's
endpoint table gives them, with no version prefix and no leading segment.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient


def _params(**kwargs) -> Dict[str, Any]:
    """Drop unsupplied query parameters so defaults are exercised."""
    return {k: v for k, v in kwargs.items() if v is not None}


class ClearinghouseClient(GenericApiClient):
    """The clearinghouse API under test."""

    # -----------------------------------------------------------------
    # Logical clock (the only endpoint exempt from auth and role checks)
    # -----------------------------------------------------------------

    def set_clock(self, current_utc: str, headers: Optional[Dict] = None
                  ) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"current_utc": current_utc}, headers or {},
        )

    # -----------------------------------------------------------------
    # Manufacturers
    # -----------------------------------------------------------------

    def create_manufacturer(self, payload: Dict, headers: Dict) -> requests.Response:
        return self._request("POST", "/manufacturers", payload, headers)

    def get_manufacturer(self, manufacturer_id: str, headers: Dict
                         ) -> requests.Response:
        return self._request(
            "GET", f"/manufacturers/{manufacturer_id}", None, headers)

    def list_manufacturers(self, headers: Dict, status: Optional[str] = None,
                           limit: Optional[int] = None,
                           offset: Optional[int] = None) -> requests.Response:
        return self._request(
            "GET", "/manufacturers",
            _params(status=status, limit=limit, offset=offset), headers)

    def suspend_manufacturer(self, manufacturer_id: str, payload: Dict,
                             headers: Dict) -> requests.Response:
        return self._request(
            "POST", f"/manufacturers/{manufacturer_id}/suspend", payload, headers)

    # -----------------------------------------------------------------
    # Retailers
    # -----------------------------------------------------------------

    def create_retailer(self, payload: Dict, headers: Dict) -> requests.Response:
        return self._request("POST", "/retailers", payload, headers)

    def get_retailer(self, retailer_id: str, headers: Dict) -> requests.Response:
        return self._request("GET", f"/retailers/{retailer_id}", None, headers)

    def list_retailers(self, headers: Dict, status: Optional[str] = None,
                       handling_fee_tier: Optional[str] = None,
                       limit: Optional[int] = None,
                       offset: Optional[int] = None) -> requests.Response:
        return self._request(
            "GET", "/retailers",
            _params(status=status, handling_fee_tier=handling_fee_tier,
                    limit=limit, offset=offset), headers)

    def suspend_retailer(self, retailer_id: str, payload: Dict,
                         headers: Dict) -> requests.Response:
        return self._request(
            "POST", f"/retailers/{retailer_id}/suspend", payload, headers)

    def reinstate_retailer(self, retailer_id: str, payload: Dict,
                           headers: Dict) -> requests.Response:
        return self._request(
            "POST", f"/retailers/{retailer_id}/reinstate", payload, headers)

    def fraud_rescore(self, retailer_id: str, expected_retailer_version: int,
                      headers: Dict) -> requests.Response:
        return self._request(
            "POST", f"/retailers/{retailer_id}/fraud-rescore",
            {"expected_retailer_version": expected_retailer_version}, headers)

    def fraud_rescore_raw(self, retailer_id: str, payload: Dict,
                          headers: Dict) -> requests.Response:
        return self._request(
            "POST", f"/retailers/{retailer_id}/fraud-rescore", payload, headers)

    # -----------------------------------------------------------------
    # Offers
    # -----------------------------------------------------------------

    def create_offer(self, payload: Dict, headers: Dict) -> requests.Response:
        return self._request("POST", "/offers", payload, headers)

    def get_offer(self, offer_id: str, headers: Dict) -> requests.Response:
        return self._request("GET", f"/offers/{offer_id}", None, headers)

    def list_offers(self, headers: Dict, manufacturer_id: Optional[str] = None,
                    status: Optional[str] = None,
                    digital_enabled: Optional[Any] = None,
                    limit: Optional[int] = None,
                    offset: Optional[int] = None) -> requests.Response:
        return self._request(
            "GET", "/offers",
            _params(manufacturer_id=manufacturer_id, status=status,
                    digital_enabled=digital_enabled, limit=limit,
                    offset=offset), headers)

    def register_offer(self, offer_id: str, headers: Dict) -> requests.Response:
        return self._request("POST", f"/offers/{offer_id}/register", {}, headers)

    def activate_offer(self, offer_id: str, headers: Dict) -> requests.Response:
        return self._request("POST", f"/offers/{offer_id}/activate", {}, headers)

    def withdraw_offer(self, offer_id: str, withdrawn_reason: str,
                       headers: Dict) -> requests.Response:
        return self._request(
            "POST", f"/offers/{offer_id}/withdraw",
            {"withdrawn_reason": withdrawn_reason}, headers)

    # -----------------------------------------------------------------
    # Submissions
    # -----------------------------------------------------------------

    def create_submission(self, payload: Dict, headers: Dict) -> requests.Response:
        return self._request("POST", "/submissions", payload, headers)

    def get_submission(self, submission_id: str, headers: Dict) -> requests.Response:
        return self._request("GET", f"/submissions/{submission_id}", None, headers)

    def list_submissions(self, headers: Dict, retailer_id: Optional[str] = None,
                         intake_status: Optional[str] = None,
                         settlement_status: Optional[str] = None,
                         limit: Optional[int] = None,
                         offset: Optional[int] = None) -> requests.Response:
        return self._request(
            "GET", "/submissions",
            _params(retailer_id=retailer_id, intake_status=intake_status,
                    settlement_status=settlement_status, limit=limit,
                    offset=offset), headers)

    def get_valuation(self, submission_id: str, headers: Dict) -> requests.Response:
        return self._request(
            "GET", f"/submissions/{submission_id}/valuation", None, headers)

    def verify_count(self, submission_id: str, verified_count: int,
                     headers: Dict) -> requests.Response:
        return self._request(
            "POST", f"/submissions/{submission_id}/verify-count",
            {"verified_count": verified_count}, headers)

    def create_lot(self, submission_id: str, payload: Dict,
                   headers: Dict) -> requests.Response:
        return self._request(
            "POST", f"/submissions/{submission_id}/lots", payload, headers)

    # -----------------------------------------------------------------
    # Submission lots
    # -----------------------------------------------------------------

    def get_lot(self, lot_id: str, headers: Dict) -> requests.Response:
        return self._request("GET", f"/submission-lots/{lot_id}", None, headers)

    def list_lots(self, headers: Dict, submission_id: Optional[str] = None,
                  offer_id: Optional[str] = None,
                  manufacturer_id: Optional[str] = None,
                  status: Optional[str] = None, limit: Optional[int] = None,
                  offset: Optional[int] = None) -> requests.Response:
        return self._request(
            "GET", "/submission-lots",
            _params(submission_id=submission_id, offer_id=offer_id,
                    manufacturer_id=manufacturer_id, status=status,
                    limit=limit, offset=offset), headers)

    def capture_items(self, lot_id: str, items: List[Dict],
                      headers: Dict) -> requests.Response:
        return self._request(
            "POST", f"/submission-lots/{lot_id}/items", {"items": items}, headers)

    def finalize_lot(self, lot_id: str, headers: Dict) -> requests.Response:
        return self._request(
            "POST", f"/submission-lots/{lot_id}/finalize", {}, headers)

    # -----------------------------------------------------------------
    # Coupon items
    # -----------------------------------------------------------------

    def get_item(self, item_id: str, headers: Dict) -> requests.Response:
        return self._request("GET", f"/coupon-items/{item_id}", None, headers)

    def list_items(self, headers: Dict, lot_id: Optional[str] = None,
                   status: Optional[str] = None,
                   reject_code: Optional[str] = None,
                   duplicate_of_item_id: Optional[str] = None,
                   matched_purchase_record_id: Optional[str] = None,
                   limit: Optional[int] = None,
                   offset: Optional[int] = None) -> requests.Response:
        return self._request(
            "GET", "/coupon-items",
            _params(lot_id=lot_id, status=status, reject_code=reject_code,
                    duplicate_of_item_id=duplicate_of_item_id,
                    matched_purchase_record_id=matched_purchase_record_id,
                    limit=limit, offset=offset), headers)

    def adjudicate_item(self, item_id: str, headers: Dict) -> requests.Response:
        return self._request(
            "POST", f"/coupon-items/{item_id}/adjudicate", {}, headers)

    # -----------------------------------------------------------------
    # Purchase-data records
    # -----------------------------------------------------------------

    def create_purchase_record(self, payload: Dict,
                               headers: Dict) -> requests.Response:
        return self._request("POST", "/purchase-data-records", payload, headers)

    def get_purchase_record(self, record_id: str,
                            headers: Dict) -> requests.Response:
        return self._request(
            "GET", f"/purchase-data-records/{record_id}", None, headers)

    def list_purchase_records(self, headers: Dict,
                              retailer_id: Optional[str] = None,
                              offer_id: Optional[str] = None,
                              pos_transaction_ref: Optional[str] = None,
                              limit: Optional[int] = None,
                              offset: Optional[int] = None) -> requests.Response:
        return self._request(
            "GET", "/purchase-data-records",
            _params(retailer_id=retailer_id, offer_id=offer_id,
                    pos_transaction_ref=pos_transaction_ref, limit=limit,
                    offset=offset), headers)

    # -----------------------------------------------------------------
    # Settlement statements
    # -----------------------------------------------------------------

    def create_statement(self, payload: Dict, headers: Dict) -> requests.Response:
        return self._request("POST", "/settlement-statements", payload, headers)

    def issue_statement(self, submission_id: str, expected_submission_version: int,
                        headers: Dict,
                        prior_chargeback_offset_cents: Optional[int] = None
                        ) -> requests.Response:
        payload: Dict[str, Any] = {
            "submission_id": submission_id,
            "expected_submission_version": expected_submission_version,
        }
        if prior_chargeback_offset_cents is not None:
            payload["prior_chargeback_offset_cents"] = prior_chargeback_offset_cents
        return self._request("POST", "/settlement-statements", payload, headers)

    def get_statement(self, statement_id: str, headers: Dict) -> requests.Response:
        return self._request(
            "GET", f"/settlement-statements/{statement_id}", None, headers)

    def list_statements(self, headers: Dict, submission_id: Optional[str] = None,
                        retailer_id: Optional[str] = None,
                        manufacturer_invoice_id: Optional[str] = None,
                        status: Optional[str] = None,
                        limit: Optional[int] = None,
                        offset: Optional[int] = None) -> requests.Response:
        return self._request(
            "GET", "/settlement-statements",
            _params(submission_id=submission_id, retailer_id=retailer_id,
                    manufacturer_invoice_id=manufacturer_invoice_id,
                    status=status, limit=limit, offset=offset), headers)

    def schedule_statement(self, statement_id: str,
                           headers: Dict) -> requests.Response:
        return self._request(
            "POST", f"/settlement-statements/{statement_id}/schedule", {}, headers)

    def release_payment(self, statement_id: str, headers: Dict) -> requests.Response:
        return self._request(
            "POST", f"/settlement-statements/{statement_id}/release-payment",
            {}, headers)

    # -----------------------------------------------------------------
    # Manufacturer invoices
    # -----------------------------------------------------------------

    def create_invoice(self, payload: Dict, headers: Dict) -> requests.Response:
        return self._request("POST", "/manufacturer-invoices", payload, headers)

    def get_invoice(self, invoice_id: str, headers: Dict) -> requests.Response:
        return self._request(
            "GET", f"/manufacturer-invoices/{invoice_id}", None, headers)

    def list_invoices(self, headers: Dict, manufacturer_id: Optional[str] = None,
                      status: Optional[str] = None, limit: Optional[int] = None,
                      offset: Optional[int] = None) -> requests.Response:
        return self._request(
            "GET", "/manufacturer-invoices",
            _params(manufacturer_id=manufacturer_id, status=status,
                    limit=limit, offset=offset), headers)

    def fund_invoice(self, invoice_id: str, amount_cents: int,
                     headers: Dict) -> requests.Response:
        return self._request(
            "POST", f"/manufacturer-invoices/{invoice_id}/fund",
            {"amount_cents": amount_cents}, headers)

    def reverse_funding(self, invoice_id: str, reason: str,
                        headers: Dict) -> requests.Response:
        return self._request(
            "POST", f"/manufacturer-invoices/{invoice_id}/reverse-funding",
            {"reason": reason}, headers)

    # -----------------------------------------------------------------
    # Disputes
    # -----------------------------------------------------------------

    def create_dispute(self, payload: Dict, headers: Dict) -> requests.Response:
        return self._request("POST", "/disputes", payload, headers)

    def file_dispute(self, lot_id: str, reason_code: str, narrative: str,
                     headers: Dict) -> requests.Response:
        return self._request(
            "POST", "/disputes",
            {"lot_id": lot_id, "reason_code": reason_code,
             "narrative": narrative}, headers)

    def get_dispute(self, dispute_id: str, headers: Dict) -> requests.Response:
        return self._request("GET", f"/disputes/{dispute_id}", None, headers)

    def list_disputes(self, headers: Dict, lot_id: Optional[str] = None,
                      retailer_id: Optional[str] = None,
                      status: Optional[str] = None, limit: Optional[int] = None,
                      offset: Optional[int] = None) -> requests.Response:
        return self._request(
            "GET", "/disputes",
            _params(lot_id=lot_id, retailer_id=retailer_id, status=status,
                    limit=limit, offset=offset), headers)

    def request_dispute_info(self, dispute_id: str, info_request_note: str,
                             headers: Dict) -> requests.Response:
        return self._request(
            "POST", f"/disputes/{dispute_id}/request-info",
            {"info_request_note": info_request_note}, headers)

    def resubmit_dispute(self, dispute_id: str, narrative: str,
                         headers: Dict) -> requests.Response:
        return self._request(
            "POST", f"/disputes/{dispute_id}/resubmit",
            {"narrative": narrative}, headers)

    def resolve_dispute(self, dispute_id: str, outcome: str,
                        resolution_note: str, headers: Dict) -> requests.Response:
        return self._request(
            "POST", f"/disputes/{dispute_id}/resolve",
            {"outcome": outcome, "resolution_note": resolution_note}, headers)

    # -----------------------------------------------------------------
    # Digital clips and redemption events
    # -----------------------------------------------------------------

    def create_clip(self, offer_id: str, consumer_ref: str,
                    headers: Dict) -> requests.Response:
        return self._request(
            "POST", "/digital-clips",
            {"offer_id": offer_id, "consumer_ref": consumer_ref}, headers)

    def create_clip_raw(self, payload: Dict, headers: Dict) -> requests.Response:
        return self._request("POST", "/digital-clips", payload, headers)

    def get_clip(self, clip_id: str, headers: Dict) -> requests.Response:
        return self._request("GET", f"/digital-clips/{clip_id}", None, headers)

    def list_clips(self, headers: Dict, offer_id: Optional[str] = None,
                   consumer_ref: Optional[str] = None,
                   status: Optional[str] = None,
                   matched_event_id: Optional[str] = None,
                   limit: Optional[int] = None,
                   offset: Optional[int] = None) -> requests.Response:
        return self._request(
            "GET", "/digital-clips",
            _params(offer_id=offer_id, consumer_ref=consumer_ref, status=status,
                    matched_event_id=matched_event_id, limit=limit,
                    offset=offset), headers)

    def create_redemption_event(self, offer_id: str, retailer_id: str,
                                consumer_ref: str,
                                headers: Dict) -> requests.Response:
        return self._request(
            "POST", "/digital-redemption-events",
            {"offer_id": offer_id, "retailer_id": retailer_id,
             "consumer_ref": consumer_ref}, headers)

    def create_redemption_event_raw(self, payload: Dict,
                                    headers: Dict) -> requests.Response:
        return self._request(
            "POST", "/digital-redemption-events", payload, headers)

    def get_redemption_event(self, event_id: str,
                             headers: Dict) -> requests.Response:
        return self._request(
            "GET", f"/digital-redemption-events/{event_id}", None, headers)

    def list_redemption_events(self, headers: Dict,
                               offer_id: Optional[str] = None,
                               retailer_id: Optional[str] = None,
                               consumer_ref: Optional[str] = None,
                               status: Optional[str] = None,
                               matched_clip_id: Optional[str] = None,
                               limit: Optional[int] = None,
                               offset: Optional[int] = None
                               ) -> requests.Response:
        return self._request(
            "GET", "/digital-redemption-events",
            _params(offer_id=offer_id, retailer_id=retailer_id,
                    consumer_ref=consumer_ref, status=status,
                    matched_clip_id=matched_clip_id, limit=limit,
                    offset=offset), headers)
