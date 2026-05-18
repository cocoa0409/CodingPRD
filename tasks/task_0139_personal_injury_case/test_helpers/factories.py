"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for
the request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared
input fields are produced; computed/system fields are intentionally
omitted so the implementation cannot accidentally accept them.

PRD §2.5: timestamps are ISO 8601 UTC with three fractional digits.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .constants import (
    DEFAULT_POST_SUIT_RATE_BPS,
    DEFAULT_PRE_SUIT_RATE_BPS,
    DEFAULT_TRIAL_RATE_BPS,
    MULTIPLIER_DEFAULT,
    TEST_DEFAULTS,
)


# ---------------------------------------------------------------------------
# Time helpers — PRD §2.5
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def iso_now() -> str:
    return iso_utc(utcnow())


def iso_instant_utc(
    year: int, month: int, day: int,
    hour: int = 12, minute: int = 0, second: int = 0,
    millis: int = 0,
) -> str:
    """Build a deterministic ISO 8601 UTC instant."""
    micros = millis * 1000
    return iso_utc(datetime(year, month, day, hour, minute, second,
                            micros, tzinfo=timezone.utc))


def iso_date(d: date) -> str:
    """PRD §3.2: 'stored as a YYYY-MM-DD date string'."""
    return d.isoformat()


def date_offset(d: date, *, days: int = 0) -> date:
    return d + timedelta(days=days)


def parse_iso(iso_ts: str) -> datetime:
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def parse_iso_date(iso_d: str) -> date:
    return date.fromisoformat(iso_d)


# ---------------------------------------------------------------------------
# Random helpers
# ---------------------------------------------------------------------------
def random_suffix(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits,
                                  k=length))


def random_email() -> str:
    return f"client_{random_suffix(6)}@example.com"


def random_courtroom() -> str:
    return f"Room-{random_suffix(4)}"


# ---------------------------------------------------------------------------
# Client payload — PRD §3.1
# ---------------------------------------------------------------------------
def create_client_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.1: 'The intake step captures full_name, date_of_birth,
    contact_email, and state_of_residence.'
    """
    defaults: Dict[str, Any] = {
        "full_name": TEST_DEFAULTS["client_full_name"],
        "date_of_birth": TEST_DEFAULTS["client_dob_adult"],
        "contact_email": random_email(),
        "state_of_residence": TEST_DEFAULTS["client_state"],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Case payload — PRD §3.1
# ---------------------------------------------------------------------------
def create_case_payload(client_id: str, **overrides) -> Dict[str, Any]:
    """PRD §3.1: 'Opening a case captures the client_id ..., the
    incident_date ..., the incident_type ..., the jurisdiction_state
    ..., and optionally assigned_attorney_id and
    assigned_paralegal_id.'
    """
    defaults: Dict[str, Any] = {
        "client_id": client_id,
        "incident_date": TEST_DEFAULTS["case_incident_date"],
        "incident_type": TEST_DEFAULTS["case_incident_type"],
        "jurisdiction_state": TEST_DEFAULTS["case_jurisdiction"],
    }
    defaults.update(overrides)
    return defaults


def case_costs_payload(case_costs_cents: int,
                       version: Optional[int] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"case_costs_cents": case_costs_cents}
    if version is not None:
        body["version"] = version
    return body


def toll_payload(additional_days: int, reason: str = "incapacity",
                 ) -> Dict[str, Any]:
    """PRD §3.2: 'a ManagingPartner operation that supplies
    additional_days and a free-text reason'."""
    return {"additional_days": additional_days, "reason": reason}


def dismiss_payload(reason: str = "client withdrew") -> Dict[str, Any]:
    """PRD §3.3: 'The dismissal endpoint takes a free-text reason in
    its body.'"""
    return {"reason": reason}


def approve_disbursement_payload(strategy: str) -> Dict[str, Any]:
    """PRD §3.10: 'The approval call carries strategy in its body,
    naming one of CHRONOLOGICAL_PRIORITY or FORWARD_LOOKING_PRORATA.'
    """
    return {"strategy": strategy}


# ---------------------------------------------------------------------------
# Contingency Fee payload — PRD §3.1
# ---------------------------------------------------------------------------
def create_contingency_fee_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.1: 'three rate fields pre_suit_rate_bps, post_suit_rate_bps,
    and trial_rate_bps (each defaulting respectively to 3333, 4000, and
    4500, each greater than 0 and at most 5000)'.
    """
    defaults: Dict[str, Any] = {
        "pre_suit_rate_bps": DEFAULT_PRE_SUIT_RATE_BPS,
        "post_suit_rate_bps": DEFAULT_POST_SUIT_RATE_BPS,
        "trial_rate_bps": DEFAULT_TRIAL_RATE_BPS,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Medical Record Request payloads — PRD §3.3
# ---------------------------------------------------------------------------
def create_medical_record_request_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.3: 'Each request captures provider_name (non-empty free
    text), date_of_service_start, and date_of_service_end'.
    """
    defaults: Dict[str, Any] = {
        "provider_name": TEST_DEFAULTS["provider_name"],
        "date_of_service_start": TEST_DEFAULTS["service_start"],
        "date_of_service_end": TEST_DEFAULTS["service_end"],
    }
    defaults.update(overrides)
    return defaults


def patch_medical_record_request_payload(
    status: str, billed_amount_cents: Optional[int] = None,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.3: 'patching its status to RECEIVED together with a
    billed_amount_cents value'."""
    body: Dict[str, Any] = {"status": status}
    if billed_amount_cents is not None:
        body["billed_amount_cents"] = billed_amount_cents
    if version is not None:
        body["version"] = version
    return body


# ---------------------------------------------------------------------------
# Damages payloads — PRD §3.4
# ---------------------------------------------------------------------------
def create_damages_multiplier_payload(
    lost_wages_cents: int = 0,
    property_damage_cents: int = 0,
    multiplier_value: float = MULTIPLIER_DEFAULT,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.4: 'When the method is MULTIPLIER, the payload must
    supply multiplier_value (a decimal in the closed range 1.0 to 5.0,
    defaulting to 1.5 and stored to one decimal place)'.
    """
    defaults: Dict[str, Any] = {
        "lost_wages_cents": lost_wages_cents,
        "property_damage_cents": property_damage_cents,
        "pain_suffering_method": "MULTIPLIER",
        "multiplier_value": multiplier_value,
    }
    defaults.update(overrides)
    return defaults


def create_damages_per_diem_payload(
    per_diem_rate_cents: int,
    per_diem_days: int,
    lost_wages_cents: int = 0,
    property_damage_cents: int = 0,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.4: 'when the method is PER_DIEM, the payload must supply
    per_diem_rate_cents strictly greater than zero and per_diem_days
    strictly greater than zero'.
    """
    defaults: Dict[str, Any] = {
        "lost_wages_cents": lost_wages_cents,
        "property_damage_cents": property_damage_cents,
        "pain_suffering_method": "PER_DIEM",
        "per_diem_rate_cents": per_diem_rate_cents,
        "per_diem_days": per_diem_days,
    }
    defaults.update(overrides)
    return defaults


def patch_damages_payload(version: Optional[int] = None, **fields,
                          ) -> Dict[str, Any]:
    body: Dict[str, Any] = dict(fields)
    if version is not None:
        body["version"] = version
    return body


# ---------------------------------------------------------------------------
# Lien payloads — PRD §3.8
# ---------------------------------------------------------------------------
def create_lien_payload(lien_type: str, face_amount_cents: int,
                        lienholder_name: Optional[str] = None,
                        ) -> Dict[str, Any]:
    """PRD §3.8: 'A lien is recorded with lienholder_name, lien_type
    ..., and face_amount_cents (strictly greater than zero).'
    """
    return {
        "lienholder_name": lienholder_name or f"Lienholder {random_suffix(4)}",
        "lien_type": lien_type,
        "face_amount_cents": face_amount_cents,
    }


def patch_lien_payload(
    negotiated_amount_cents: Optional[int] = None,
    status: Optional[str] = None,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {}
    if negotiated_amount_cents is not None:
        body["negotiated_amount_cents"] = negotiated_amount_cents
    if status is not None:
        body["status"] = status
    if version is not None:
        body["version"] = version
    return body


# ---------------------------------------------------------------------------
# Demand Letter payloads — PRD §3.5
# ---------------------------------------------------------------------------
def create_demand_letter_payload(demanded_amount_cents: int,
                                 ) -> Dict[str, Any]:
    """PRD §3.5: 'Drafting captures demanded_amount_cents'."""
    return {"demanded_amount_cents": demanded_amount_cents}


def send_demand_letter_payload(
    expected_damages_version: Optional[int] = None,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.5: 'The caller may optionally supply
    expected_damages_version in the request body to assert which
    version of the damages row they intend to snapshot'.
    """
    body: Dict[str, Any] = {}
    if expected_damages_version is not None:
        body["expected_damages_version"] = expected_damages_version
    if version is not None:
        body["version"] = version
    return body


# ---------------------------------------------------------------------------
# Settlement Offer payloads — PRD §3.6
# ---------------------------------------------------------------------------
def create_settlement_offer_payload(
    offer_party: str, amount_cents: int, expires_at: str,
    predecessor_offer_id: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.6: 'Each offer carries offer_party (DEFENDANT or
    PLAINTIFF), amount_cents (strictly greater than zero), expires_at
    (a wall-clock instant), and optionally predecessor_offer_id.'
    """
    body: Dict[str, Any] = {
        "offer_party": offer_party,
        "amount_cents": amount_cents,
        "expires_at": expires_at,
    }
    if predecessor_offer_id is not None:
        body["predecessor_offer_id"] = predecessor_offer_id
    return body


def patch_settlement_offer_payload(
    status: str, version: Optional[int] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"status": status}
    if version is not None:
        body["version"] = version
    return body


# ---------------------------------------------------------------------------
# Court Event payloads — PRD §3.7
# ---------------------------------------------------------------------------
def create_court_event_payload(
    event_type: str, scheduled_at: str, duration_minutes: int,
    courtroom: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.7: 'Each event carries event_type ..., scheduled_at ...,
    duration_minutes ..., and optionally courtroom.'
    """
    body: Dict[str, Any] = {
        "event_type": event_type,
        "scheduled_at": scheduled_at,
        "duration_minutes": duration_minutes,
    }
    if courtroom is not None:
        body["courtroom"] = courtroom
    return body


def patch_court_event_payload(
    status: Optional[str] = None,
    scheduled_at: Optional[str] = None,
    award_amount_cents: Optional[int] = None,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {}
    if status is not None:
        body["status"] = status
    if scheduled_at is not None:
        body["scheduled_at"] = scheduled_at
    if award_amount_cents is not None:
        body["award_amount_cents"] = award_amount_cents
    if version is not None:
        body["version"] = version
    return body


# ---------------------------------------------------------------------------
# Clock / sweep payloads — PRD §3.6
# ---------------------------------------------------------------------------
def clock_advance_payload(seconds: int) -> Dict[str, Any]:
    """PRD §3.6: 'a clock-advance capability that moves the logical
    clock forward by a supplied number of seconds'."""
    return {"seconds": seconds}


__all__ = [
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_instant_utc",
    "iso_date",
    "date_offset",
    "parse_iso",
    "parse_iso_date",
    "random_suffix",
    "random_email",
    "random_courtroom",
    "create_client_payload",
    "create_case_payload",
    "case_costs_payload",
    "toll_payload",
    "dismiss_payload",
    "approve_disbursement_payload",
    "create_contingency_fee_payload",
    "create_medical_record_request_payload",
    "patch_medical_record_request_payload",
    "create_damages_multiplier_payload",
    "create_damages_per_diem_payload",
    "patch_damages_payload",
    "create_lien_payload",
    "patch_lien_payload",
    "create_demand_letter_payload",
    "send_demand_letter_payload",
    "create_settlement_offer_payload",
    "patch_settlement_offer_payload",
    "create_court_event_payload",
    "patch_court_event_payload",
    "clock_advance_payload",
]
