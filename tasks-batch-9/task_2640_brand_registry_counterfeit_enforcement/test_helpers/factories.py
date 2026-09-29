"""Request payload builders.

Every builder returns a dict with PRD-exact field names and PRD-legal defaults,
and accepts overrides for anything a test needs to control. Monetary values are
integer cents and scores are numeric — never strings.
"""

import itertools
from typing import Any, Dict, Optional

from .constants import (
    AUTHENTICATION_RESULT_COUNTERFEIT,
    CUSTOMS_AUTHORITY_US_CBP,
    DECISION_REMOVED,
    MARKETPLACE_AMZ,
    RESPONSE_KIND_DENIAL,
    SCOPE_SUBMIT_TAKEDOWN,
    SOURCE_KIND_BORDER_SEIZURE,
    SOURCE_KIND_TEST_BUY,
    VIOLATION_TYPE_COUNTERFEIT,
)

_counter = itertools.count(1)


def next_suffix() -> int:
    """Monotonic suffix for references that must be unique within a test."""
    return next(_counter)


def brand_payload(**overrides) -> Dict[str, Any]:
    """A brand with an authorized MSRP of 10000 cents and the default budget."""
    payload: Dict[str, Any] = {
        "name": f"Aurelia Timepieces {next_suffix()}",
        "owner_legal_entity": "Aurelia Holdings SA",
        "home_jurisdiction": "CH",
        "authorized_msrp_cents": 10000,
    }
    payload.update(overrides)
    return payload


def registration_payload(brand_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "brand_id": brand_id,
        "registration_number": f"US-{4000000 + next_suffix()}",
        "jurisdiction": "US",
        "nice_class": 8,
        "registration_date": "2020-03-15",
        "expiry_date": "2034-03-15",
        "principal_register": True,
        "status": "REGISTERED",
    }
    payload.update(overrides)
    return payload


def enrollment_payload(brand_id: str, asserted_registration_id: str,
                       expected_brand_version: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "brand_id": brand_id,
        "asserted_registration_id": asserted_registration_id,
        "marketplace_code": MARKETPLACE_AMZ,
        "requested_nice_class": 8,
        "expected_brand_version": expected_brand_version,
    }
    payload.update(overrides)
    return payload


def representative_payload(enrollment_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "enrollment_id": enrollment_id,
        "authority_scope": SCOPE_SUBMIT_TAKEDOWN,
        "effective_from": "2026-08-01T00:00:00Z",
        "effective_to": "2027-08-01T00:00:00Z",
        "power_of_attorney_ref": f"POA-{next_suffix()}",
    }
    payload.update(overrides)
    return payload


def seller_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "marketplace_code": MARKETPLACE_AMZ,
        "seller_ref": f"A1SELLER{next_suffix()}",
        "legal_name": "Nightmarket Trading Ltd",
        "jurisdiction": "CN",
    }
    payload.update(overrides)
    return payload


def listing_payload(brand_id: str, seller_id: str, **overrides) -> Dict[str, Any]:
    """A listing priced at 3000 cents, which deviates 0.7000 from a 10000 MSRP."""
    payload: Dict[str, Any] = {
        "brand_id": brand_id,
        "seller_id": seller_id,
        "marketplace_code": MARKETPLACE_AMZ,
        "listing_ref": f"B0LISTING{next_suffix()}",
        "title_text": "Aurelia Chronograph Automatic - Sealed",
        "image_hash": f"sha256:{next_suffix():064d}",
        "price_cents": 3000,
        "nice_class": 8,
    }
    payload.update(overrides)
    return payload


def screen_payload(image_match_score: float = 0.92, text_match_score: float = 0.88,
                   **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "image_match_score": image_match_score,
        "text_match_score": text_match_score,
    }
    payload.update(overrides)
    return payload


def claim_payload(brand_id: str, listing_id: str, asserted_registration_id: str,
                  **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "brand_id": brand_id,
        "listing_id": listing_id,
        "asserted_registration_id": asserted_registration_id,
        "claimed_violation_type": VIOLATION_TYPE_COUNTERFEIT,
    }
    payload.update(overrides)
    return payload


def test_buy_payload(purchase_price_cents: int = 4200, shipping_cents: int = 700,
                     lab_fee_cents: int = 0, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "order_ref": f"TB-{next_suffix()}",
        "purchase_price_cents": purchase_price_cents,
        "shipping_cents": shipping_cents,
        "lab_fee_cents": lab_fee_cents,
    }
    payload.update(overrides)
    return payload


# Payload builders, not pytest cases: the `test_buy_` prefix is the PRD's own
# vocabulary for the test-buy programme, so tell pytest not to collect them.
test_buy_payload.__test__ = False


def evidence_package_payload(claim_id: str, expected_claim_version: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "claim_id": claim_id,
        "package_ref": f"PKG-{next_suffix()}",
        "expected_claim_version": expected_claim_version,
    }
    payload.update(overrides)
    return payload


def takedown_payload(enrollment_id: str, claim_id: str, evidence_package_id: str,
                     **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "enrollment_id": enrollment_id,
        "claim_id": claim_id,
        "evidence_package_id": evidence_package_id,
    }
    payload.update(overrides)
    return payload


def marketplace_decision_payload(decision: str = DECISION_REMOVED,
                                 marketplace_case_ref: Optional[str] = None,
                                 **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": decision,
        "marketplace_case_ref": marketplace_case_ref or f"MP-{next_suffix()}",
    }
    payload.update(overrides)
    return payload


def counter_notice_payload(takedown_id: str, seller_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "takedown_id": takedown_id,
        "seller_id": seller_id,
        "sworn_statement_ref": f"CN-SWORN-{next_suffix()}",
    }
    payload.update(overrides)
    return payload


def case_payload(brand_id: str, seller_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"brand_id": brand_id, "seller_id": seller_id}
    payload.update(overrides)
    return payload


def case_response_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "response_ref": f"RESP-{next_suffix()}",
        "response_kind": RESPONSE_KIND_DENIAL,
    }
    payload.update(overrides)
    return payload


def recordation_payload(brand_id: str, registration_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "brand_id": brand_id,
        "registration_id": registration_id,
        "customs_authority_code": CUSTOMS_AUTHORITY_US_CBP,
        "nice_class": 8,
        "recorded_on": "2026-08-01",
        "expires_on": "2027-12-31",
    }
    payload.update(overrides)
    return payload


def border_seizure_investigation_payload(brand_id: str, recordation_id: str,
                                         lot_code: str = "LOT-2026-A", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "brand_id": brand_id,
        "source_kind": SOURCE_KIND_BORDER_SEIZURE,
        "lot_code": lot_code,
        "recordation_id": recordation_id,
        "seizure_ref": f"SZ-{next_suffix()}",
        "port_code": "USLAX",
        "seized_qty": 400,
        "declared_value_cents": 250000,
    }
    payload.update(overrides)
    return payload


def test_buy_investigation_payload(brand_id: str, source_test_buy_id: str,
                                   lot_code: str = "LOT-2026-A", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "brand_id": brand_id,
        "source_kind": SOURCE_KIND_TEST_BUY,
        "lot_code": lot_code,
        "source_test_buy_id": source_test_buy_id,
    }
    payload.update(overrides)
    return payload


test_buy_investigation_payload.__test__ = False


def authenticate_payload(authentication_result: str = AUTHENTICATION_RESULT_COUNTERFEIT,
                         **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "authentication_result": authentication_result,
        "lab_ref": f"LAB-{next_suffix()}",
    }
    payload.update(overrides)
    return payload
