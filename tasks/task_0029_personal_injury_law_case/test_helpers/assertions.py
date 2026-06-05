"""Entity assertion helpers — one per primary entity, plus domain invariants.

All assertions verify only what PRD §2.4 / §3.x explicitly guarantees about each
entity's response shape; they tolerate additional fields the implementer may add.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


# ─── Common-fields helpers ─────────────────────────────────────────


def _assert_common_fields(data: dict, entity_name: str = "entity") -> None:
    """PRD §2.4: every primary entity carries id (UUID), created_at, updated_at,
    version (integer ≥ 1)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be int >= 1, got {data.get('version')!r}"
    )


def _assert_singleton_clock_fields(data: dict) -> None:
    """PRD §2.4: SystemClock is the singleton exception — id + created_at only."""
    assert isinstance(data.get("id"), str) and data["id"]
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "SystemClock.created_at must be ISO 8601"
    )


# ─── Client (PRD §3.1) ────────────────────────────────────────────


def assert_client(data: dict) -> None:
    """Validate Client response shape (PRD §3.1)."""
    _assert_common_fields(data, "Client")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["phone"], str) and data["phone"]
    assert isinstance(data["retainer_signed"], bool)
    rs_at = data.get("retainer_signed_at")
    assert rs_at is None or is_iso8601_timestamp(rs_at), (
        "Client.retainer_signed_at must be null or ISO 8601"
    )


# ─── Case (PRD §3.1) ──────────────────────────────────────────────


_CASE_STATUSES = {
    "INTAKE", "ACTIVE", "DEMAND_SENT", "IN_NEGOTIATION", "LITIGATION",
    "SETTLED", "CLOSED", "ABANDONED",
}
_JURISDICTIONS = {"CA", "NY", "TX", "FL", "IL"}


def assert_case(data: dict) -> None:
    """Validate Case response shape (PRD §3.1)."""
    _assert_common_fields(data, "Case")
    assert is_valid_uuid(data["client_id"]), "Case.client_id must be a UUID"
    assert isinstance(data["accident_date"], str) and data["accident_date"]
    assert data["jurisdiction"] in _JURISDICTIONS, (
        f"Case.jurisdiction must be one of {_JURISDICTIONS}, got {data['jurisdiction']!r}"
    )
    assert data["status"] in _CASE_STATUSES, (
        f"Case.status must be a known status, got {data['status']!r}"
    )
    assert isinstance(data["statute_of_limitations_date"], str)
    assert isinstance(data["sol_tolled_days"], int) and data["sol_tolled_days"] >= 0
    assert isinstance(data["filed_in_court"], bool)
    assert (
        isinstance(data["included_damages_total_cents"], int)
        and data["included_damages_total_cents"] >= 0
    )
    gs = data.get("gross_settlement_cents")
    assert gs is None or (isinstance(gs, int) and gs >= 0)


# ─── MedicalProvider (PRD §3.2) ───────────────────────────────────


def assert_provider(data: dict) -> None:
    _assert_common_fields(data, "MedicalProvider")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact"], str) and data["contact"]


# ─── MedicalRecordsRequest (PRD §3.2) ─────────────────────────────


_MRR_STATUSES = {"REQUESTED", "RECEIVED", "REVIEWED", "REJECTED"}


def assert_records_request(data: dict) -> None:
    _assert_common_fields(data, "MedicalRecordsRequest")
    assert is_valid_uuid(data["case_id"]), "MedicalRecordsRequest.case_id must be a UUID"
    assert is_valid_uuid(data["provider_id"]), "MedicalRecordsRequest.provider_id must be a UUID"
    assert data["status"] in _MRR_STATUSES
    rec_at = data.get("received_at")
    rev_at = data.get("reviewed_at")
    assert rec_at is None or is_iso8601_timestamp(rec_at)
    assert rev_at is None or is_iso8601_timestamp(rev_at)


# ─── DamagesItem (PRD §3.3) ───────────────────────────────────────


_DAMAGES_STATUSES = {"PROPOSED", "INCLUDED", "EXCLUDED"}
_DAMAGES_CATEGORIES = {
    "MEDICAL_BILLS", "LOST_WAGES", "PAIN_SUFFERING", "FUTURE_MEDICAL", "PROPERTY",
}


def assert_damages_item(data: dict) -> None:
    _assert_common_fields(data, "DamagesItem")
    assert is_valid_uuid(data["case_id"])
    assert data["category"] in _DAMAGES_CATEGORIES
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in _DAMAGES_STATUSES


# ─── MedicalLien (PRD §3.7) ───────────────────────────────────────


_LIEN_STATUSES = {"ASSERTED", "NEGOTIATING", "AGREED", "DISPUTED", "PAID"}


def assert_lien(data: dict) -> None:
    _assert_common_fields(data, "MedicalLien")
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["provider_id"])
    assert (
        isinstance(data["asserted_amount_cents"], int)
        and data["asserted_amount_cents"] >= 0
    )
    assert (
        isinstance(data["negotiated_amount_cents"], int)
        and data["negotiated_amount_cents"] >= 0
    )
    assert (
        data["negotiated_amount_cents"] <= data["asserted_amount_cents"]
    ), "MedicalLien.negotiated_amount_cents must never exceed asserted_amount_cents"
    assert data["status"] in _LIEN_STATUSES


# ─── DemandLetter (PRD §3.4) ──────────────────────────────────────


_DEMAND_STATUSES = {"DRAFT", "SENT", "ACKNOWLEDGED", "WITHDRAWN"}


def assert_demand_letter(data: dict) -> None:
    _assert_common_fields(data, "DemandLetter")
    assert is_valid_uuid(data["case_id"])
    assert isinstance(data["demand_amount_cents"], int)
    assert data["demand_amount_cents"] >= 0
    assert isinstance(data["pain_multiplier"], (int, float))
    assert 1.0 <= float(data["pain_multiplier"]) <= 5.0
    assert data["status"] in _DEMAND_STATUSES
    assert isinstance(data["drafted_by_user_id"], str) and data["drafted_by_user_id"]
    sent_at = data.get("sent_at")
    assert sent_at is None or is_iso8601_timestamp(sent_at)


# ─── SettlementOffer (PRD §3.5) ───────────────────────────────────


_OFFER_STATUSES = {"PENDING", "COUNTERED", "ACCEPTED", "REJECTED", "EXPIRED"}
_OFFER_PARTIES = {"CARRIER", "FIRM"}


def assert_offer(data: dict) -> None:
    _assert_common_fields(data, "SettlementOffer")
    assert is_valid_uuid(data["case_id"])
    assert (
        isinstance(data["offer_amount_cents"], int)
        and data["offer_amount_cents"] >= 0
    )
    assert data["by_party"] in _OFFER_PARTIES
    ct = data.get("counter_to_offer_id")
    assert ct is None or is_valid_uuid(ct)
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert data["status"] in _OFFER_STATUSES
    rr = data.get("responded_at")
    assert rr is None or is_iso8601_timestamp(rr)


# ─── CourtEvent (PRD §3.8) ────────────────────────────────────────


_EVENT_TYPES = {"FILING", "HEARING", "TRIAL", "MEDIATION"}
_EVENT_STATUSES = {"SCHEDULED", "OCCURRED", "CANCELLED"}


def assert_court_event(data: dict) -> None:
    _assert_common_fields(data, "CourtEvent")
    assert is_valid_uuid(data["case_id"])
    assert data["event_type"] in _EVENT_TYPES
    assert isinstance(data["scheduled_at"], str) and data["scheduled_at"]
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0
    assert data["status"] in _EVENT_STATUSES


# ─── Disbursement (PRD §3.7) ──────────────────────────────────────


_DISBURSEMENT_STATUSES = {"PENDING", "RELEASED"}


def assert_disbursement(data: dict) -> None:
    _assert_common_fields(data, "Disbursement")
    assert is_valid_uuid(data["case_id"])
    assert (
        isinstance(data["gross_settlement_cents"], int)
        and data["gross_settlement_cents"] >= 0
    )
    assert (
        isinstance(data["contingency_fee_cents"], int)
        and data["contingency_fee_cents"] >= 0
    )
    assert (
        isinstance(data["total_lien_payout_cents"], int)
        and data["total_lien_payout_cents"] >= 0
    )
    assert isinstance(data["net_to_client_cents"], int)
    assert data["status"] in _DISBURSEMENT_STATUSES


def assert_money_conservation(disbursement: dict, gross_settlement_cents: int) -> None:
    """PRD §3.7: gross = fee + total_lien_payout + net (integer cents, no drift)."""
    fee = disbursement["contingency_fee_cents"]
    payout = disbursement["total_lien_payout_cents"]
    net = disbursement["net_to_client_cents"]
    total = fee + payout + net
    assert total == gross_settlement_cents, (
        f"Money conservation violated: fee({fee}) + payout({payout}) + "
        f"net({net}) = {total}, expected gross={gross_settlement_cents}"
    )


# ─── SystemClock (PRD §2.4) ───────────────────────────────────────


def assert_system_clock(data: dict) -> None:
    _assert_singleton_clock_fields(data)
    assert is_iso8601_timestamp(data["current_utc"]), (
        "SystemClock.current_utc must be ISO 8601"
    )
