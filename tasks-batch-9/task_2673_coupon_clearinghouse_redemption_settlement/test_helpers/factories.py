"""Request-body builders for every write endpoint.

Each builder emits only the fields the PRD names for that endpoint, with
monetary values as plain integers of whole cents and dates as bare calendar
date strings. Optional fields are omitted unless the caller supplies them, so
a builder called with no overrides exercises the declared defaults.
"""

from __future__ import annotations

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    CANONICAL_EXPIRATION_DATE,
    CANONICAL_FACE_VALUE_CENTS,
    CANONICAL_GRACE_DAYS,
    CANONICAL_HANDLING_FEE_CENTS,
    CANONICAL_INSTRUCTIONS,
    PREFIX_A,
)
from .types import BarcodeFamily, Channel

_prefix_counter = itertools.count(1)
_code_counter = itertools.count(1)
_pos_counter = itertools.count(1)
_serial_counter = itertools.count(1)


def unique_prefix() -> str:
    """A six-digit GS1 company prefix no other issuer in this test holds."""
    return f"{900000 + next(_prefix_counter):06d}"


def unique_offer_code(stem: str = "OFFER") -> str:
    return f"{stem}-{next(_code_counter):04d}"


def unique_pos_ref(stem: str = "POS") -> str:
    return f"{stem}-{next(_pos_counter):04d}"


def unique_serial(stem: str = "SER") -> str:
    return f"{stem}-{next(_serial_counter):04d}"


def _drop_none(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not None}


# ---------------------------------------------------------------------------
# Manufacturers and retailers
# ---------------------------------------------------------------------------

def manufacturer_payload(legal_name: str = "Northbrook Foods Incorporated",
                         gs1_company_prefix: str = PREFIX_A,
                         handling_fee_policy: Optional[str] = None,
                         dispute_window_days: Optional[int] = None
                         ) -> Dict[str, Any]:
    """Onboard a coupon issuer. Both commercial terms are optional."""
    return _drop_none({
        "legal_name": legal_name,
        "gs1_company_prefix": gs1_company_prefix,
        "handling_fee_policy": handling_fee_policy,
        "dispute_window_days": dispute_window_days,
    })


def retailer_payload(legal_name: str = "Harborline Markets LLC",
                     channel_capability: Optional[str] = None,
                     payment_terms: Optional[str] = None,
                     base_fee_tier: Optional[str] = None,
                     fraud_scoring_mode: Optional[str] = None
                     ) -> Dict[str, Any]:
    """Onboard a submitting retailer. All four commercial settings default."""
    return _drop_none({
        "legal_name": legal_name,
        "channel_capability": channel_capability,
        "payment_terms": payment_terms,
        "base_fee_tier": base_fee_tier,
        "fraud_scoring_mode": fraud_scoring_mode,
    })


def suspend_payload(reason: str = "Unfunded invoices past ninety days"
                    ) -> Dict[str, str]:
    return {"reason": reason}


def reinstate_payload(reason: str = "Remediation plan accepted by the committee"
                      ) -> Dict[str, str]:
    return {"reason": reason}


# ---------------------------------------------------------------------------
# Offers
# ---------------------------------------------------------------------------

def offer_payload(manufacturer_id: str, offer_code: str = "SOUP50",
                  face_value_cents: int = CANONICAL_FACE_VALUE_CENTS,
                  handling_fee_cents: int = CANONICAL_HANDLING_FEE_CENTS,
                  expiration_date: str = CANONICAL_EXPIRATION_DATE,
                  redemption_instructions: str = CANONICAL_INSTRUCTIONS,
                  barcode_family: str = BarcodeFamily.GS1_DATABAR,
                  max_redemptions: int = 1000,
                  purchase_requirement_units: Optional[int] = None,
                  redemption_grace_days: Optional[int] = None,
                  digital_enabled: Optional[bool] = None,
                  clip_validity_days: Optional[int] = None
                  ) -> Dict[str, Any]:
    """Create a coupon design. The last four inputs are the optional terms."""
    payload: Dict[str, Any] = {
        "manufacturer_id": manufacturer_id,
        "offer_code": offer_code,
        "face_value_cents": face_value_cents,
        "handling_fee_cents": handling_fee_cents,
        "expiration_date": expiration_date,
        "redemption_instructions": redemption_instructions,
        "barcode_family": barcode_family,
        "max_redemptions": max_redemptions,
    }
    optional = {
        "purchase_requirement_units": purchase_requirement_units,
        "redemption_grace_days": redemption_grace_days,
        "digital_enabled": digital_enabled,
        "clip_validity_days": clip_validity_days,
    }
    payload.update({k: v for k, v in optional.items() if v is not None})
    return payload


def canonical_offer_payload(manufacturer_id: str, **overrides) -> Dict[str, Any]:
    """The offer most fixtures use: face 50, fee 7, grace 30, one unit."""
    base = offer_payload(
        manufacturer_id,
        redemption_grace_days=CANONICAL_GRACE_DAYS,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Submissions and lots
# ---------------------------------------------------------------------------

def submission_payload(retailer_id: str, declared_count: int,
                       postmark_window_start: str, postmark_window_end: str,
                       channel: str = Channel.MAIL) -> Dict[str, Any]:
    """Open a submission. Both postmark bounds are required on either channel."""
    return {
        "retailer_id": retailer_id,
        "channel": channel,
        "declared_count": declared_count,
        "postmark_window_start": postmark_window_start,
        "postmark_window_end": postmark_window_end,
    }


def lot_payload(offer_id: str, manufacturer_id: str,
                counted_qty: int) -> Dict[str, Any]:
    """Sort one manufacturer-and-offer bucket out of a verified submission."""
    return {
        "offer_id": offer_id,
        "manufacturer_id": manufacturer_id,
        "counted_qty": counted_qty,
    }


def item_payload(scanned_barcode: str, image_uri: str, redeemed_at: str,
                 serial_number: Optional[str] = None,
                 pos_transaction_ref: Optional[str] = None,
                 claimed_units: Optional[int] = None) -> Dict[str, Any]:
    """One element of the bulk image-capture array."""
    payload: Dict[str, Any] = {
        "scanned_barcode": scanned_barcode,
        "image_uri": image_uri,
        "redeemed_at": redeemed_at,
    }
    optional = {
        "serial_number": serial_number,
        "pos_transaction_ref": pos_transaction_ref,
        "claimed_units": claimed_units,
    }
    payload.update({k: v for k, v in optional.items() if v is not None})
    return payload


def item_batch(count: int, scanned_barcode: str, redeemed_at: str,
               pos_transaction_ref: Optional[str] = None,
               claimed_units: Optional[int] = None,
               serial_numbers: Optional[List[Optional[str]]] = None,
               uri_stem: str = "s3://coupon-images/") -> List[Dict[str, Any]]:
    """A batch of `count` identical coupons with distinct image locations."""
    batch: List[Dict[str, Any]] = []
    for index in range(count):
        serial = serial_numbers[index] if serial_numbers else None
        batch.append(item_payload(
            scanned_barcode=scanned_barcode,
            image_uri=f"{uri_stem}{index + 1}.jpg",
            redeemed_at=redeemed_at,
            serial_number=serial,
            pos_transaction_ref=pos_transaction_ref,
            claimed_units=claimed_units,
        ))
    return batch


def purchase_record_payload(retailer_id: str, offer_id: str,
                            pos_transaction_ref: str, transaction_date: str,
                            qualifying_units: int) -> Dict[str, Any]:
    """Ingest one point-of-sale basket."""
    return {
        "retailer_id": retailer_id,
        "offer_id": offer_id,
        "pos_transaction_ref": pos_transaction_ref,
        "transaction_date": transaction_date,
        "qualifying_units": qualifying_units,
    }


# ---------------------------------------------------------------------------
# Settlement, invoicing and disputes
# ---------------------------------------------------------------------------

def statement_payload(submission_id: str, expected_submission_version: int,
                      prior_chargeback_offset_cents: Optional[int] = None
                      ) -> Dict[str, Any]:
    """Issue a settlement statement over a closed submission."""
    payload: Dict[str, Any] = {
        "submission_id": submission_id,
        "expected_submission_version": expected_submission_version,
    }
    if prior_chargeback_offset_cents is not None:
        payload["prior_chargeback_offset_cents"] = prior_chargeback_offset_cents
    return payload


def invoice_payload(manufacturer_id: str, billing_period_start: str,
                    billing_period_end: str,
                    statement_ids: List[str]) -> Dict[str, Any]:
    """Bill a batch of statements onto one issuer for a closed period."""
    return {
        "manufacturer_id": manufacturer_id,
        "billing_period_start": billing_period_start,
        "billing_period_end": billing_period_end,
        "statement_ids": statement_ids,
    }


def dispute_payload(lot_id: str, reason_code: str = "IMAGE_QUALITY",
                    narrative: str = "Rescan shows a clean barcode on every coupon."
                    ) -> Dict[str, Any]:
    """File an appeal against a rejected lot."""
    return {
        "lot_id": lot_id,
        "reason_code": reason_code,
        "narrative": narrative,
    }


def clip_payload(offer_id: str, consumer_ref: str) -> Dict[str, str]:
    return {"offer_id": offer_id, "consumer_ref": consumer_ref}


def redemption_event_payload(offer_id: str, retailer_id: str,
                             consumer_ref: str) -> Dict[str, str]:
    return {
        "offer_id": offer_id,
        "retailer_id": retailer_id,
        "consumer_ref": consumer_ref,
    }
