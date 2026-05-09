"""Payload factories — one per write endpoint, input fields only.

Every factory accepts ``**overrides`` so tests can pin a specific field
(e.g. ``photo_urls`` length, ``ask_price_cents``, ``credit_score``) while
the rest of the payload uses sensible PRD-conformant defaults.
"""

import secrets
import uuid
from typing import Any, Dict, List, Optional


# ──────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────


def _unique_id_doc() -> str:
    """Random unique id_document_number for Seller/Buyer (PRD §3.1 says these
    are unique across the platform)."""
    return f"IDDOC-{uuid.uuid4().hex[:12].upper()}"


def _unique_vin() -> str:
    """Random VIN: exactly 17 alphanumeric chars, excluding I/O/Q (PRD §3.1)."""
    alphabet = "0123456789ABCDEFGHJKLMNPRSTUVWXYZ"  # 17 chars after excluding I, O, Q
    return "".join(secrets.choice(alphabet) for _ in range(17))


def _photo_urls(n: int = 6) -> List[str]:
    """Generate ``n`` distinct photo URLs."""
    return [f"https://photos.example.com/{uuid.uuid4().hex}.jpg" for _ in range(n)]


# ──────────────────────────────────────────────────────────
# Seller / Buyer
# ──────────────────────────────────────────────────────────


def create_seller_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: legal_name, id_document_number, phone."""
    payload = {
        "legal_name": "Test Seller " + uuid.uuid4().hex[:6],
        "id_document_number": _unique_id_doc(),
        "phone": "+15551234567",
    }
    payload.update(overrides)
    return payload


def create_buyer_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: legal_name, id_document_number, phone."""
    payload = {
        "legal_name": "Test Buyer " + uuid.uuid4().hex[:6],
        "id_document_number": _unique_id_doc(),
        "phone": "+15557654321",
    }
    payload.update(overrides)
    return payload


# ──────────────────────────────────────────────────────────
# Vehicle / Assessment
# ──────────────────────────────────────────────────────────


def create_vehicle_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: vin, make, model, model_year, declared_mileage_km, color."""
    payload = {
        "vin": _unique_vin(),
        "make": "Toyota",
        "model": "Corolla",
        "model_year": 2018,
        "declared_mileage_km": 100_000,
        "color": "Silver",
    }
    payload.update(overrides)
    return payload


def create_assessment_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: vin_history_records (list of {date,source,event_type,severity})
    and inspector_user_id."""
    payload = {
        "vin_history_records": [
            {
                "date": "2023-04-15",
                "source": "DMV",
                "event_type": "REGISTRATION",
                "severity": "NONE",
            }
        ],
        "inspector_user_id": f"insp-{uuid.uuid4().hex[:8]}",
    }
    payload.update(overrides)
    return payload


def vin_history(
    accidents: int = 0,
    major_accidents: int = 0,
    maintenance: int = 0,
    recalls: int = 0,
    registrations: int = 0,
) -> List[Dict[str, str]]:
    """Build a vin_history_records list with the requested counts.

    Major accidents are produced as ACCIDENT events with severity=MAJOR;
    minor accidents use severity=MINOR. ``accidents`` is the *additional*
    minor-severity accident count (the total ACCIDENT count becomes
    ``accidents + major_accidents`` because major accidents are also counted
    as accidents per PRD §3.1's ``accident_count`` definition).
    """
    items: List[Dict[str, str]] = []
    for i in range(accidents):
        items.append(
            {
                "date": "2022-06-01",
                "source": "DMV",
                "event_type": "ACCIDENT",
                "severity": "MINOR",
            }
        )
    for i in range(major_accidents):
        items.append(
            {
                "date": "2022-06-15",
                "source": "DMV",
                "event_type": "ACCIDENT",
                "severity": "MAJOR",
            }
        )
    for i in range(maintenance):
        items.append(
            {
                "date": "2023-01-10",
                "source": "SHOP",
                "event_type": "MAINTENANCE",
                "severity": "NONE",
            }
        )
    for i in range(recalls):
        items.append(
            {
                "date": "2023-02-20",
                "source": "MFG",
                "event_type": "RECALL",
                "severity": "MINOR",
            }
        )
    for i in range(registrations):
        items.append(
            {
                "date": "2020-08-01",
                "source": "DMV",
                "event_type": "REGISTRATION",
                "severity": "NONE",
            }
        )
    if not items:
        items.append(
            {
                "date": "2020-08-01",
                "source": "DMV",
                "event_type": "REGISTRATION",
                "severity": "NONE",
            }
        )
    return items


def onsite_findings_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: exterior_grade, interior_grade, mechanical_grade (each one of
    A/B/C/D), mileage_km_observed."""
    payload = {
        "exterior_grade": "A",
        "interior_grade": "A",
        "mechanical_grade": "B",
        "mileage_km_observed": 100_000,
    }
    payload.update(overrides)
    return payload


def finalize_payload(onsite: Optional[Dict[str, Any]] = None, **overrides: Any) -> Dict[str, Any]:
    """Wraps onsite_findings into the finalize endpoint body."""
    payload = {"onsite_findings": onsite if onsite is not None else onsite_findings_payload()}
    payload.update(overrides)
    return payload


# ──────────────────────────────────────────────────────────
# Listing
# ──────────────────────────────────────────────────────────


def create_listing_payload(
    vehicle_id: str,
    assessment_report_id: str,
    sale_mode: str = "FIXED_PRICE",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: vehicle_id, assessment_report_id, sale_mode, ask_price_cents,
    reserve_price_cents (AUCTION only), photo_urls, documents_authentic_flag.
    """
    payload: Dict[str, Any] = {
        "vehicle_id": vehicle_id,
        "assessment_report_id": assessment_report_id,
        "sale_mode": sale_mode,
        "ask_price_cents": 2_000_000,
        "photo_urls": _photo_urls(6),
        "documents_authentic_flag": True,
    }
    if sale_mode == "AUCTION":
        # Reserve set just below ask so most reasonable bids will meet it.
        payload["reserve_price_cents"] = overrides.get("reserve_price_cents", 1_000_000)
    else:
        payload["reserve_price_cents"] = None
    payload.update(overrides)
    return payload


# ──────────────────────────────────────────────────────────
# Bid / Reservation
# ──────────────────────────────────────────────────────────


def create_bid_payload(amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.3: amount_cents."""
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_reservation_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.4: body carries no parameters beyond the path's listing id."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


# ──────────────────────────────────────────────────────────
# Purchase Order / Loan
# ──────────────────────────────────────────────────────────


def create_purchase_order_payload(
    listing_id: str, payment_method: str = "FULL_PAYMENT", **overrides: Any
) -> Dict[str, Any]:
    """PRD §3.5: listing_id, payment_method (FULL_PAYMENT default)."""
    payload = {"listing_id": listing_id, "payment_method": payment_method}
    payload.update(overrides)
    return payload


def create_loan_payload(
    lender_code: str = "LENDER_A",
    requested_principal_cents: int = 1_500_000,
    down_payment_ratio_bp: int = 2_000,
    term_months: int = 36,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.6: lender_code, requested_principal_cents, down_payment_ratio_bp,
    term_months."""
    payload = {
        "lender_code": lender_code,
        "requested_principal_cents": requested_principal_cents,
        "down_payment_ratio_bp": down_payment_ratio_bp,
        "term_months": term_months,
    }
    payload.update(overrides)
    return payload


# ──────────────────────────────────────────────────────────
# Transfer / Warranty / Dispute
# ──────────────────────────────────────────────────────────


def upload_doc_payload(doc_type: str, doc_url: Optional[str] = None) -> Dict[str, Any]:
    """PRD §3.7: doc_type, doc_url."""
    return {
        "doc_type": doc_type,
        "doc_url": doc_url or f"https://docs.example.com/{uuid.uuid4().hex}.pdf",
    }


def book_appointment_payload(
    appointment_at: str,
    dmv_office_code: str = "DMV-001",
    license_plate_action: str = "REASSIGN",
    new_plate_number: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7: appointment_at, dmv_office_code, license_plate_action,
    new_plate_number."""
    payload: Dict[str, Any] = {
        "appointment_at": appointment_at,
        "dmv_office_code": dmv_office_code,
        "license_plate_action": license_plate_action,
        "new_plate_number": new_plate_number,
    }
    payload.update(overrides)
    return payload


def warranty_claim_payload(
    component: str = "POWERTRAIN", claimed_amount_cents: int = 100_000, **overrides: Any
) -> Dict[str, Any]:
    """PRD §3.8: component, claimed_amount_cents."""
    payload = {"component": component, "claimed_amount_cents": claimed_amount_cents}
    payload.update(overrides)
    return payload


def dispute_payload(
    complainant_role: str = "BUYER",
    complaint_text: str = "The vehicle does not match the listing.",
    evidence_items: Optional[List[Dict[str, str]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.9: complainant_role, complaint_text, evidence_items?."""
    payload: Dict[str, Any] = {
        "complainant_role": complainant_role,
        "complaint_text": complaint_text,
        "evidence_items": evidence_items if evidence_items is not None else [],
    }
    payload.update(overrides)
    return payload


# ──────────────────────────────────────────────────────────
# External event / Clock
# ──────────────────────────────────────────────────────────


def emit_event_payload(
    source: str,
    event_type: str,
    payload: Dict[str, Any],
    idempotency_key: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §2.10: source, event_type, idempotency_key, payload."""
    body = {
        "source": source,
        "event_type": event_type,
        "idempotency_key": idempotency_key or f"evt-{uuid.uuid4().hex}",
        "payload": payload,
    }
    body.update(overrides)
    return body


def advance_clock_payload(to_iso_8601: str) -> Dict[str, Any]:
    """PRD §4: /_clock/advance accepts to_iso_8601."""
    return {"to_iso_8601": to_iso_8601}
