"""Payload factories — one per writeable entity, input fields only.

All factories accept **overrides so tests can pin specific fields when their
assertions depend on a particular value.
"""
import uuid


# ─── Helpers ──────────────────────────────────────────────────


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def _email(local: str = "user") -> str:
    return f"{local}-{_suffix()}@example.com"


# ─── Client (PRD §3.1) ──────────────────────────────────────


def create_client_payload(**overrides) -> dict:
    """Payload for POST /clients/register.

    Required: full_name, email, phone (PRD §3.1).
    """
    defaults = {
        "full_name": "Test Claimant",
        "email": _email("client"),
        "phone": "555-0100",
    }
    defaults.update(overrides)
    return defaults


# ─── Case (PRD §3.1) ────────────────────────────────────────


def create_case_payload(client_id: str,
                        accident_date: str = "2024-06-15",
                        jurisdiction: str = "CA",
                        **overrides) -> dict:
    """Payload for POST /cases.

    Required: client_id, accident_date, jurisdiction. Optional: sol_tolled_days.
    """
    payload = {
        "client_id": client_id,
        "accident_date": accident_date,
        "jurisdiction": jurisdiction,
    }
    payload.update(overrides)
    return payload


# ─── MedicalProvider (PRD §3.2) ─────────────────────────────


def create_provider_payload(**overrides) -> dict:
    """Payload for POST /medical-providers.

    Required: name, contact (PRD §3.2).
    """
    defaults = {
        "name": f"Provider {_suffix()}",
        "contact": f"records-{_suffix()}@provider.example",
    }
    defaults.update(overrides)
    return defaults


# ─── MedicalRecordsRequest (PRD §3.2) ───────────────────────


def create_records_request_payload(case_id: str, provider_id: str,
                                    **overrides) -> dict:
    """Payload for POST /medical-records-requests.

    Required: case_id, provider_id (PRD §3.2).
    """
    payload = {"case_id": case_id, "provider_id": provider_id}
    payload.update(overrides)
    return payload


# ─── DamagesItem (PRD §3.3) ─────────────────────────────────


def create_damages_item_payload(case_id: str, category: str,
                                amount_cents: int,
                                **overrides) -> dict:
    """Payload for POST /damages-items.

    Required: case_id, category, amount_cents. Optional: documentation_note.
    """
    payload = {
        "case_id": case_id,
        "category": category,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


# ─── MedicalLien (PRD §3.7) ─────────────────────────────────


def create_lien_payload(case_id: str, provider_id: str,
                        asserted_amount_cents: int,
                        **overrides) -> dict:
    """Payload for POST /medical-liens.

    Required: case_id, provider_id, asserted_amount_cents (PRD §3.7).
    """
    payload = {
        "case_id": case_id,
        "provider_id": provider_id,
        "asserted_amount_cents": asserted_amount_cents,
    }
    payload.update(overrides)
    return payload


def agree_lien_payload(negotiated_amount_cents: int, **overrides) -> dict:
    """Payload for POST /medical-liens/{id}/agree (PRD §3.7)."""
    payload = {"negotiated_amount_cents": negotiated_amount_cents}
    payload.update(overrides)
    return payload


# ─── DemandLetter (PRD §3.4) ────────────────────────────────


def create_demand_letter_payload(case_id: str, pain_multiplier: float = 1.5,
                                  **overrides) -> dict:
    """Payload for POST /demand-letters.

    Required: case_id, pain_multiplier (PRD §3.4).
    """
    payload = {"case_id": case_id, "pain_multiplier": pain_multiplier}
    payload.update(overrides)
    return payload


# ─── SettlementOffer (PRD §3.5) ─────────────────────────────


def create_offer_payload(case_id: str, offer_amount_cents: int,
                         by_party: str,
                         counter_to_offer_id: str = None,
                         **overrides) -> dict:
    """Payload for POST /settlement-offers.

    Required: case_id, offer_amount_cents, by_party. Optional: counter_to_offer_id.
    """
    payload = {
        "case_id": case_id,
        "offer_amount_cents": offer_amount_cents,
        "by_party": by_party,
    }
    if counter_to_offer_id is not None:
        payload["counter_to_offer_id"] = counter_to_offer_id
    payload.update(overrides)
    return payload


def accept_offer_payload(expected_case_version: int, **overrides) -> dict:
    """Payload for POST /settlement-offers/{id}/accept (PRD §3.6)."""
    payload = {"expected_case_version": expected_case_version}
    payload.update(overrides)
    return payload


# ─── CourtEvent (PRD §3.8) ──────────────────────────────────


def create_court_event_payload(case_id: str, event_type: str,
                                scheduled_at: str,
                                duration_minutes: int = None,
                                **overrides) -> dict:
    """Payload for POST /court-events.

    Required: case_id, event_type, scheduled_at. Optional: duration_minutes
    (defaults to 60 per PRD §3.8).
    """
    payload = {
        "case_id": case_id,
        "event_type": event_type,
        "scheduled_at": scheduled_at,
    }
    if duration_minutes is not None:
        payload["duration_minutes"] = duration_minutes
    payload.update(overrides)
    return payload


# ─── Disbursement (PRD §3.7) ────────────────────────────────


def release_disbursement_payload(expected_case_version: int, **overrides) -> dict:
    """Payload for POST /disbursements/{id}/release (PRD §3.7)."""
    payload = {"expected_case_version": expected_case_version}
    payload.update(overrides)
    return payload


# ─── SystemClock (PRD §2.10) ────────────────────────────────


def set_clock_payload(to_iso8601: str) -> dict:
    """Payload for POST /_clock/set_current_utc (PRD §2.10)."""
    return {"to_iso8601": to_iso8601}
