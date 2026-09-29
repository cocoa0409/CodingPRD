"""Request-payload builders.

Every builder returns a complete, valid payload for one endpoint and accepts
keyword overrides so a test can vary exactly the one field it is exercising.
Field names are the PRD's own names, never abbreviated.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    CAPTURE_SIGNATURE,
    CHANNEL_WEB_CHECKBOX,
    CONTRACT_TIER_STANDARD,
    DOCUMENT_DRIVERS_LICENSE,
    DOCUMENT_PASSPORT,
    DRY_STATUS_WET,
    OUTCOME_REFUSAL,
    PERMISSIBILITY_PERMITTED,
    PROVIDER_STATE_DMV_GATEWAY,
    RESTRICTION_ALCOHOL,
    RESTRICTION_NONE,
    RESTRICTION_TOBACCO_VAPE,
    SCENARIO_UNDERAGE_PRESENTER,
    SEVERITY_MAJOR,
    SIGNAL_CREDIT_BUREAU,
    SIGNAL_GOVERNMENT_ID_DB,
    SIGNAL_MOBILE_CARRIER,
    SIGNAL_WATCHLIST_NEGATIVE,
)

# A monotonic counter so repeated calls inside one test never collide on the
# globally unique `code`, `sku`, `email` and `license_reference` fields.
_counter = itertools.count(1)


def unique_suffix() -> str:
    return f"{next(_counter):04d}"


# ---------------------------------------------------------------------------
# Shared literals used across the suite
# ---------------------------------------------------------------------------
JURISDICTION_CODE_NY = "US-NY"
JURISDICTION_CODE_VT = "US-VT"
JURISDICTION_CODE_KS = "US-KS"
JURISDICTION_CODE_AR = "US-AR"
OFFSET_NEW_YORK = -240
OFFSET_KANSAS = -300

ALCOHOL_WINDOW_START_MINUTE = 600
ALCOHOL_WINDOW_END_MINUTE = 1320
ALCOHOL_MIN_AGE_YEARS = 21
AUGUST_EFFECTIVE_FROM = "2026-08-01"
AUGUST_EFFECTIVE_TO = "2026-08-31"

WINE_SKU = "WINE-A"
WINE_UNITS_PER_ITEM = 1.50
WINE_PRICE_CENTS = 6800
BEER_SKU = "BEER-B"
BEER_UNITS_PER_ITEM = 0.75
BEER_PRICE_CENTS = 3200
SELTZER_SKU = "SELTZ-C"
SELTZER_UNITS_PER_ITEM = 0.05
SELTZER_PRICE_CENTS = 900
GROCERY_SKU = "GROCERY-D"
GROCERY_PRICE_CENTS = 500
CIGAR_SKU = "CIGAR-E"
CIGAR_UNITS_PER_ITEM = 0.20
CIGAR_PRICE_CENTS = 1500

ADULT_DOB = "2000-03-15"
MINOR_DOB = "2007-05-10"

SIGNATURE_HASH = "1" * 64
PHOTO_ID_HASH = "2" * 64
PHOTO_HANDOFF_HASH = "3" * 64
SPARE_HASH = "4" * 64


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock (PRD 2.5)
# ---------------------------------------------------------------------------
def clock_payload(current_utc: str) -> Dict[str, Any]:
    return {"current_utc": current_utc}


# ---------------------------------------------------------------------------
# Jurisdictions (PRD 3.1)
# ---------------------------------------------------------------------------
def jurisdiction_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "code": f"US-N{unique_suffix()}",
            "name": "New York State",
            "dry_status": DRY_STATUS_WET,
            "utc_offset_minutes": OFFSET_NEW_YORK,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Restriction policies (PRD 3.1)
# ---------------------------------------------------------------------------
def restriction_policy_payload(jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "jurisdiction_id": jurisdiction_id,
            "restriction_type": RESTRICTION_ALCOHOL,
            "permissibility": PERMISSIBILITY_PERMITTED,
            "min_age_years": ALCOHOL_MIN_AGE_YEARS,
            "delivery_window_start_minute": ALCOHOL_WINDOW_START_MINUTE,
            "delivery_window_end_minute": ALCOHOL_WINDOW_END_MINUTE,
            "unit_scale_factor": 1.00,
            "max_units_per_order": 6.97,
            "max_units_per_window": 40.00,
            "rolling_window_days": 30,
            "acceptable_document_types": [DOCUMENT_DRIVERS_LICENSE, DOCUMENT_PASSPORT],
            "requires_scan": True,
            "effective_from": AUGUST_EFFECTIVE_FROM,
            "effective_to": AUGUST_EFFECTIVE_TO,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Products (PRD 3.1)
# ---------------------------------------------------------------------------
def product_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "sku": f"SKU-{unique_suffix()}",
            "name": "Table Wine 750ml",
            "restriction_type": RESTRICTION_ALCOHOL,
            "restricted_units_per_item": WINE_UNITS_PER_ITEM,
            "list_price_cents": WINE_PRICE_CENTS,
        },
        overrides,
    )


def wine_product_payload(**overrides: Any) -> Dict[str, Any]:
    return product_payload(
        **_merge(
            {
                "sku": WINE_SKU,
                "name": "Table Wine 750ml",
                "restriction_type": RESTRICTION_ALCOHOL,
                "restricted_units_per_item": WINE_UNITS_PER_ITEM,
                "list_price_cents": WINE_PRICE_CENTS,
            },
            overrides,
        )
    )


def beer_product_payload(**overrides: Any) -> Dict[str, Any]:
    return product_payload(
        **_merge(
            {
                "sku": BEER_SKU,
                "name": "Craft Beer Six Pack",
                "restriction_type": RESTRICTION_ALCOHOL,
                "restricted_units_per_item": BEER_UNITS_PER_ITEM,
                "list_price_cents": BEER_PRICE_CENTS,
            },
            overrides,
        )
    )


def seltzer_product_payload(**overrides: Any) -> Dict[str, Any]:
    return product_payload(
        **_merge(
            {
                "sku": SELTZER_SKU,
                "name": "Hard Seltzer Can",
                "restriction_type": RESTRICTION_ALCOHOL,
                "restricted_units_per_item": SELTZER_UNITS_PER_ITEM,
                "list_price_cents": SELTZER_PRICE_CENTS,
            },
            overrides,
        )
    )


def grocery_product_payload(**overrides: Any) -> Dict[str, Any]:
    return product_payload(
        **_merge(
            {
                "sku": GROCERY_SKU,
                "name": "Pantry Staples Box",
                "restriction_type": RESTRICTION_NONE,
                "restricted_units_per_item": 0,
                "list_price_cents": GROCERY_PRICE_CENTS,
            },
            overrides,
        )
    )


def cigar_product_payload(**overrides: Any) -> Dict[str, Any]:
    return product_payload(
        **_merge(
            {
                "sku": CIGAR_SKU,
                "name": "Cigar Single",
                "restriction_type": RESTRICTION_TOBACCO_VAPE,
                "restricted_units_per_item": CIGAR_UNITS_PER_ITEM,
                "list_price_cents": CIGAR_PRICE_CENTS,
            },
            overrides,
        )
    )


# ---------------------------------------------------------------------------
# Customers (PRD 3.2)
# ---------------------------------------------------------------------------
def customer_payload(jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    suffix = unique_suffix()
    return _merge(
        {
            "full_name": f"Avery Customer {suffix}",
            "email": f"avery.customer.{suffix}@example.com",
            "jurisdiction_id": jurisdiction_id,
        },
        overrides,
    )


def attestation_payload(attested_dob: str = ADULT_DOB, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"attested_dob": attested_dob, "attestation_channel": CHANNEL_WEB_CHECKBOX},
        overrides,
    )


def source_signals(
    government_id_db: bool = True,
    credit_bureau: bool = True,
    mobile_carrier: bool = False,
    watchlist_negative: bool = True,
) -> List[Dict[str, Any]]:
    """The four signal kinds in the fixed order the PRD visits them (PRD 3.2)."""
    return [
        {"source_type": SIGNAL_GOVERNMENT_ID_DB, "matched": government_id_db},
        {"source_type": SIGNAL_CREDIT_BUREAU, "matched": credit_bureau},
        {"source_type": SIGNAL_MOBILE_CARRIER, "matched": mobile_carrier},
        {"source_type": SIGNAL_WATCHLIST_NEGATIVE, "matched": watchlist_negative},
    ]


def identity_check_payload(
    expected_customer_version: int,
    provided_dob: str = ADULT_DOB,
    source_dob: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Identity pre-verification whose signals sum to a MATCH confidence of 0.8500."""
    return _merge(
        {
            "provider": PROVIDER_STATE_DMV_GATEWAY,
            "provided_dob": provided_dob,
            "source_dob": source_dob if source_dob is not None else provided_dob,
            "validity_days": 90,
            "source_signals": source_signals(),
            "expected_customer_version": expected_customer_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Orders and lines (PRD 3.3)
# ---------------------------------------------------------------------------
def order_payload(
    customer_id: str,
    delivery_jurisdiction_id: str,
    delivery_partner_id: str,
    scheduled_delivery_at: str,
    delivery_fee_cents: int = 600,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "customer_id": customer_id,
            "delivery_jurisdiction_id": delivery_jurisdiction_id,
            "delivery_partner_id": delivery_partner_id,
            "scheduled_delivery_at": scheduled_delivery_at,
            "delivery_fee_cents": delivery_fee_cents,
        },
        overrides,
    )


def order_line_payload(product_id: str, quantity: int = 1, **overrides: Any) -> Dict[str, Any]:
    return _merge({"product_id": product_id, "quantity": quantity}, overrides)


def clearance_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def return_settlement_payload(restock_confirmed: bool = True, **overrides: Any) -> Dict[str, Any]:
    return _merge({"restock_confirmed": restock_confirmed}, overrides)


# ---------------------------------------------------------------------------
# Delivery partners (PRD 3.4)
# ---------------------------------------------------------------------------
def delivery_partner_payload(**overrides: Any) -> Dict[str, Any]:
    suffix = unique_suffix()
    return _merge(
        {
            "legal_name": f"Last Mile Logistics {suffix}",
            "contract_tier": CONTRACT_TIER_STANDARD,
            "license_reference": f"NY-DEL-{suffix}",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Couriers and certifications (PRD 3.5)
# ---------------------------------------------------------------------------
def courier_payload(delivery_partner_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "delivery_partner_id": delivery_partner_id,
            "full_name": "Dana Reyes",
            "hired_at": "2026-05-01",
        },
        overrides,
    )


def courier_certification_payload(courier_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "courier_id": courier_id,
            "restriction_type": RESTRICTION_ALCOHOL,
            "training_score": 92,
            "training_completed_at": "2026-07-15",
            "valid_days": 365,
        },
        overrides,
    )


def certification_renewal_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"training_score": 95, "training_completed_at": "2026-08-15", "valid_days": 30},
        overrides,
    )


def certification_revocation_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"revocation_reason": "Falsified training record"}, overrides)


# ---------------------------------------------------------------------------
# Delivery attempts, the id check, captures, handover and refusal (PRD 3.6, 3.7)
# ---------------------------------------------------------------------------
def delivery_attempt_payload(
    order_id: str, courier_id: str, started_at: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"order_id": order_id, "courier_id": courier_id, "started_at": started_at},
        overrides,
    )


def id_check_payload(
    document_type: str = DOCUMENT_DRIVERS_LICENSE,
    document_expires_on: str = "2030-03-15",
    scan_performed: bool = True,
    scanned_dob: str = ADULT_DOB,
    recipient_name: str = "Avery Customer",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "document_type": document_type,
            "document_expires_on": document_expires_on,
            "scan_performed": scan_performed,
            "scanned_dob": scanned_dob,
            "recipient_name": recipient_name,
        },
        overrides,
    )


def capture_payload(
    kind: str = CAPTURE_SIGNATURE,
    content_hash: str = SIGNATURE_HASH,
    captured_at: str = "2026-08-20T18:05:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {"kind": kind, "content_hash": content_hash, "captured_at": captured_at},
        overrides,
    )


def handover_payload(recipient_name: str = "Avery Customer", **overrides: Any) -> Dict[str, Any]:
    return _merge({"recipient_name": recipient_name}, overrides)


def refusal_payload(refusal_reason: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"refusal_reason": refusal_reason}, overrides)


# ---------------------------------------------------------------------------
# Secret-shopper tests (PRD 3.8)
# ---------------------------------------------------------------------------
def secret_shopper_test_payload(
    courier_id: str, order_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "courier_id": courier_id,
            "order_id": order_id,
            "scenario_type": SCENARIO_UNDERAGE_PRESENTER,
            "scheduled_at": "2026-08-20T18:00:00Z",
            "expected_outcome": OUTCOME_REFUSAL,
        },
        overrides,
    )


def shopper_outcome_payload(observed_outcome: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"observed_outcome": observed_outcome}, overrides)


# ---------------------------------------------------------------------------
# Violation cases and corrective action plans (PRD 3.9)
# ---------------------------------------------------------------------------
def violation_case_payload(
    delivery_partner_id: str,
    delivery_attempt_id: Optional[str] = None,
    secret_shopper_test_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "delivery_partner_id": delivery_partner_id,
        "severity": SEVERITY_MAJOR,
        "summary": "Courier handed a restricted order to an unverified recipient.",
    }
    if delivery_attempt_id is not None:
        payload["delivery_attempt_id"] = delivery_attempt_id
    if secret_shopper_test_id is not None:
        payload["secret_shopper_test_id"] = secret_shopper_test_id
    return _merge(payload, overrides)


def request_partner_response_payload(response_due_at: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"response_due_at": response_due_at, "notes": "Please account for the doorstep decision."},
        overrides,
    )


def partner_response_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"partner_response_text": "Courier retrained and route audited."}, overrides
    )


def case_decision_payload(
    decision: str, assessed_severity: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if assessed_severity is not None:
        payload["assessed_severity"] = assessed_severity
    return _merge(payload, overrides)


def case_reopen_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"notes": "New evidence supplied by the partner."}, overrides)


def corrective_action_plan_payload(
    expected_violation_case_version: int,
    due_at: str = "2026-09-30T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "expected_violation_case_version": expected_violation_case_version,
            "remediation_items": ["Retrain courier on document inspection"],
            "due_at": due_at,
        },
        overrides,
    )


def plan_review_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def plan_resubmit_payload(due_at: str = "2026-10-15T00:00:00Z", **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"remediation_items": ["Revised remediation commitment"], "due_at": due_at},
        overrides,
    )


def plan_verify_payload(verification_outcome: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"verification_outcome": verification_outcome}, overrides)
