"""Payload factories for the Public Library API.

One factory per mutation endpoint, emitting EXACTLY the PRD-declared input field
set. All factories accept **overrides so tests can pin specific values and let
the rest take stable defaults.

Names match PRD prose: e.g. PRD §3.1 names the body field `marc_control_number`,
not `marc_id`; PRD §3.6 names the fine-pay body field `pay_cents`, not `amount_cents`.
"""

import secrets
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────


def _unique_suffix() -> str:
    """Return an 8-hex-character random suffix used to defeat uniqueness collisions
    across tests that share a single server process."""
    return secrets.token_hex(4)


def _unique_marc() -> str:
    """MARC control numbers must be 8-20 chars and globally unique (PRD §3.1)."""
    # 12 hex chars = 12 length, inside the 8-20 window.
    return f"MARC{_unique_suffix()}"


def _unique_isbn() -> str:
    """Generate a 13-digit ISBN-like string (PRD §3.1 requires exactly 13 digits)."""
    # 13 digits — use a fixed prefix to stay deterministic in shape.
    return "978" + "".join(str((int(c, 16) % 10)) for c in _unique_suffix() + "00")[:10]


def _unique_barcode() -> str:
    """Copy barcodes must be globally unique (PRD §3.1)."""
    return f"BC-{_unique_suffix()}"


def _unique_national_id_hash() -> str:
    """64-char SHA-256 hex (PRD §3.2)."""
    return secrets.token_hex(32)


def _current_year() -> int:
    """Used so publication_year stays within [1450, current_year] (PRD §3.1)."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).year


# ─────────────────────────────────────────────────────────────
# BookTitle / Copy (PRD §3.1)
# ─────────────────────────────────────────────────────────────


def create_book_title_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for POST /library/book-titles (PRD §3.1)."""
    payload: Dict[str, Any] = {
        "marc_control_number": _unique_marc(),
        "isbn": TEST_DEFAULTS["ISBN_VALID"],
        "title": TEST_DEFAULTS["BOOK_TITLE"],
        "author": TEST_DEFAULTS["BOOK_AUTHOR"],
        "publisher": TEST_DEFAULTS["BOOK_PUBLISHER"],
        "publication_year": 2020,
        "classification_scheme": "DEWEY",
        "classification_code": TEST_DEFAULTS["CLASSIFICATION_CODE"],
        "subject_category": "GENERAL",
        "acquisition_source": "PURCHASE",
    }
    payload.update(overrides)
    return payload


def create_copy_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for POST /library/book-titles/{id}/copies (PRD §3.1)."""
    payload: Dict[str, Any] = {
        "barcode": _unique_barcode(),
        "location_code": TEST_DEFAULTS["LOCATION_CODE"],
        "acquisition_source": "PURCHASE",
        "acquired_at": TEST_DEFAULTS["COPY_ACQUIRED_AT"],
    }
    payload.update(overrides)
    return payload


def weed_copy_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for POST /library/copies/{id}/weed (PRD §3.1)."""
    payload: Dict[str, Any] = {"weeding_reason": "DAMAGED"}
    payload.update(overrides)
    return payload


# ─────────────────────────────────────────────────────────────
# Reader / Card (PRD §3.2)
# ─────────────────────────────────────────────────────────────


def create_reader_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for POST /library/readers (PRD §3.2)."""
    payload: Dict[str, Any] = {
        "national_id_hash": _unique_national_id_hash(),
        "full_name": TEST_DEFAULTS["READER_FULL_NAME"],
    }
    payload.update(overrides)
    return payload


def issue_card_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for POST /library/readers/{id}/cards (PRD §3.2)."""
    payload: Dict[str, Any] = {
        "card_type": "REGULAR",
        "valid_from": TEST_DEFAULTS["CARD_VALID_FROM"],
        "valid_until": TEST_DEFAULTS["CARD_VALID_UNTIL_FAR_FUTURE"],
    }
    payload.update(overrides)
    return payload


def reissue_card_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for POST /library/cards/{id}/reissue (PRD §3.2)."""
    payload: Dict[str, Any] = {
        "card_type": "REGULAR",
        "valid_from": TEST_DEFAULTS["CARD_VALID_FROM"],
        "valid_until": TEST_DEFAULTS["CARD_VALID_UNTIL_FAR_FUTURE"],
    }
    payload.update(overrides)
    return payload


def blacklist_reader_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for POST /library/readers/{id}/blacklist (PRD §3.2)."""
    payload: Dict[str, Any] = {"reason": "Test-driven blacklist"}
    payload.update(overrides)
    return payload


# ─────────────────────────────────────────────────────────────
# Loans (PRD §3.3-§3.4)
# ─────────────────────────────────────────────────────────────


def create_loan_payload(
    copy_id: str,
    card_id: str,
    *,
    channel: str = "COUNTER",
    reservation_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /library/loans (PRD §3.3)."""
    payload: Dict[str, Any] = {
        "copy_id": copy_id,
        "card_id": card_id,
        "channel": channel,
    }
    if reservation_id is not None:
        payload["reservation_id"] = reservation_id
    payload.update(overrides)
    return payload


def recall_loan_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for POST /library/loans/{id}/recall (PRD §3.4)."""
    payload: Dict[str, Any] = {"reason": "test recall"}
    payload.update(overrides)
    return payload


def return_loan_payload(
    *, returned_at: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """Body for POST /library/loans/{id}/return (PRD §3.4)."""
    payload: Dict[str, Any] = {}
    if returned_at is not None:
        payload["returned_at"] = returned_at
    payload.update(overrides)
    return payload


# ─────────────────────────────────────────────────────────────
# Reservations (PRD §3.5)
# ─────────────────────────────────────────────────────────────


def create_reservation_payload(
    book_title_id: str,
    card_id: str,
    *,
    channel: str = "ONLINE",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /library/reservations (PRD §3.5)."""
    payload: Dict[str, Any] = {
        "book_title_id": book_title_id,
        "card_id": card_id,
        "channel": channel,
    }
    payload.update(overrides)
    return payload


# ─────────────────────────────────────────────────────────────
# Fines (PRD §3.6)
# ─────────────────────────────────────────────────────────────


def waive_fine_payload(
    waive_cents: int, *, reason: str = "HOLIDAY", **overrides: Any
) -> Dict[str, Any]:
    """Body for POST /library/fines/{id}/waive (PRD §3.6)."""
    payload: Dict[str, Any] = {"waive_cents": waive_cents, "reason": reason}
    payload.update(overrides)
    return payload


def pay_fine_payload(
    pay_cents: int,
    *,
    idempotency_key: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /library/fines/{id}/pay (PRD §3.6)."""
    payload: Dict[str, Any] = {
        "pay_cents": pay_cents,
        "idempotency_key": idempotency_key,
    }
    payload.update(overrides)
    return payload


# ─────────────────────────────────────────────────────────────
# ILL (PRD §3.7)
# ─────────────────────────────────────────────────────────────


def create_ill_request_payload(
    card_id: str,
    *,
    partner_library_code: str = "PL_A",
    target_marc_control_number: str,
    shipping_cost_cents: int = 1000,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /library/ill-requests (PRD §3.7)."""
    payload: Dict[str, Any] = {
        "card_id": card_id,
        "partner_library_code": partner_library_code,
        "target_marc_control_number": target_marc_control_number,
        "shipping_cost_cents": shipping_cost_cents,
    }
    payload.update(overrides)
    return payload


def reject_ill_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for POST /library/ill-requests/{id}/reject (PRD §3.7)."""
    payload: Dict[str, Any] = {"reason": "Test reject"}
    payload.update(overrides)
    return payload


def dispatch_ill_payload(copy_id: str, **overrides: Any) -> Dict[str, Any]:
    """Body for POST /library/ill-requests/{id}/dispatch (PRD §3.7)."""
    payload: Dict[str, Any] = {"copy_id": copy_id}
    payload.update(overrides)
    return payload


# ─────────────────────────────────────────────────────────────
# Acquisition suggestions (PRD §3.8)
# ─────────────────────────────────────────────────────────────


def create_suggestion_payload(
    card_id: str,
    *,
    suggested_isbn: str = "9781234567897",
    suggested_title: str = "Suggested Title",
    rationale: str = "Useful for the collection",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /library/acquisition-suggestions (PRD §3.8)."""
    payload: Dict[str, Any] = {
        "card_id": card_id,
        "suggested_isbn": suggested_isbn,
        "suggested_title": suggested_title,
        "rationale": rationale,
    }
    payload.update(overrides)
    return payload


def decide_suggestion_payload(
    decision: str,
    *,
    review_notes: Optional[str] = None,
    new_book_title: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /library/acquisition-suggestions/{id}/decide (PRD §3.8)."""
    payload: Dict[str, Any] = {"decision": decision}
    if review_notes is not None:
        payload["review_notes"] = review_notes
    if new_book_title is not None:
        payload["new_book_title"] = new_book_title
    payload.update(overrides)
    return payload


def acquire_new_book_title_payload(suggested_isbn: str, **overrides: Any) -> Dict[str, Any]:
    """Body fragment for the `new_book_title` field on an ACQUIRE decision (PRD §3.8).

    Mirrors create_book_title_payload but ties `isbn` to the suggestion's
    suggested_isbn so the implementation's same-ISBN check (PRD §3.8) passes.
    """
    payload: Dict[str, Any] = {
        "marc_control_number": _unique_marc(),
        "isbn": suggested_isbn,
        "title": "Acquired Title",
        "author": "Acquired Author",
        "publisher": "Acquired Publisher",
        "publication_year": 2020,
        "classification_scheme": "DEWEY",
        "classification_code": TEST_DEFAULTS["CLASSIFICATION_CODE"],
        "subject_category": "GENERAL",
        "acquisition_source": "ILL_PURCHASE",
    }
    payload.update(overrides)
    return payload


# ─────────────────────────────────────────────────────────────
# Test-driving (clock / sweep / events) (PRD §2.12, §3.9)
# ─────────────────────────────────────────────────────────────


def advance_clock_payload(iso_duration: str = "P1D") -> Dict[str, Any]:
    """Body for POST /library/_clock/advance (PRD §2.12)."""
    return {"iso_duration": iso_duration}


def emit_event_payload(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Body for POST /library/_events/emit (PRD §3.9)."""
    return {"event_type": event_type, "payload": payload}


def payment_confirmed_event_payload(
    fine_id: str, *, idempotency_key: str, amount_cents: Optional[int] = None
) -> Dict[str, Any]:
    """Payload for type=PAYMENT_CONFIRMED (PRD §3.6, §3.9)."""
    inner: Dict[str, Any] = {
        "fine_id": fine_id,
        "idempotency_key": idempotency_key,
    }
    if amount_cents is not None:
        inner["amount_cents"] = amount_cents
    return emit_event_payload("PAYMENT_CONFIRMED", inner)


def identity_verified_event_payload(reader_id: str) -> Dict[str, Any]:
    """Payload for type=IDENTITY_VERIFIED (PRD §3.2, §3.9)."""
    return emit_event_payload("IDENTITY_VERIFIED", {"reader_id": reader_id})


def ill_availability_event_payload(
    ill_request_id: str, *, available: bool, partner_max_days: Optional[int] = None
) -> Dict[str, Any]:
    """Payload for type=ILL_AVAILABILITY (PRD §3.7, §3.9)."""
    inner: Dict[str, Any] = {"ill_request_id": ill_request_id, "available": available}
    if partner_max_days is not None:
        inner["partner_max_days"] = partner_max_days
    return emit_event_payload("ILL_AVAILABILITY", inner)


def ill_delivered_event_payload(ill_request_id: str) -> Dict[str, Any]:
    """Payload for type=ILL_DELIVERED (PRD §3.7, §3.9)."""
    return emit_event_payload("ILL_DELIVERED", {"ill_request_id": ill_request_id})


def ill_return_initiated_event_payload(ill_request_id: str) -> Dict[str, Any]:
    """Payload for type=ILL_RETURN_INITIATED (PRD §3.7, §3.9)."""
    return emit_event_payload(
        "ILL_RETURN_INITIATED", {"ill_request_id": ill_request_id}
    )
