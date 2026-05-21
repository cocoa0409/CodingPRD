"""Payload factories — one per entity, input fields only.

PRD §2.4: server-managed fields are not part of the client request body.
The factories below emit ONLY the source: input fields the PRD declares
on each entity. Helpers append timestamp strings in ISO 8601 UTC with
three fractional digits per PRD §2.4 / §2.7.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Random helpers
# ---------------------------------------------------------------------------
def random_suffix(n: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def random_digits(n: int) -> str:
    return "".join(random.choices(string.digits, k=n))


def random_employee_no() -> str:
    """PRD §3.1: pattern ^E\\d{6}$ (letter E followed by exactly six digits)."""
    return f"E{random_digits(6)}"


def random_pairing_code() -> str:
    """PRD §3.1: human-readable pairing identifier, unique."""
    return f"P-{random.randint(2026, 2030)}-{random.randint(1, 365):03d}-{random_suffix(4)}"


def random_iata() -> str:
    """3-letter IATA code; PRD §3.1."""
    return "".join(random.choices(string.ascii_uppercase, k=3))


def random_flight_number() -> str:
    """PRD §3.1: flight identifier (e.g., AA1234)."""
    return f"AA{random.randint(100, 9999)}"


def random_bid_window_id() -> str:
    return f"BW-{random_suffix(8)}"


def random_union_local_id() -> str:
    return f"L-{random.randint(100, 999)}"


# ---------------------------------------------------------------------------
# Timestamp helpers — PRD §2.7 demands ISO 8601 UTC with 3 fractional digits.
# ---------------------------------------------------------------------------
def iso_from_dt(dt: datetime) -> str:
    """Render dt as ISO 8601 UTC with three fractional digits and a Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = dt.microsecond // 1000
    return f"{base}.{millis:03d}Z"


def iso_now_utc() -> str:
    return iso_from_dt(datetime.now(timezone.utc))


def parse_iso(iso: str) -> datetime:
    s = iso.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def add_minutes_iso(iso: str, minutes: int) -> str:
    return iso_from_dt(parse_iso(iso) + timedelta(minutes=minutes))


def add_hours_iso(iso: str, hours: int) -> str:
    return iso_from_dt(parse_iso(iso) + timedelta(hours=hours))


def add_days_iso(iso: str, days: int) -> str:
    return iso_from_dt(parse_iso(iso) + timedelta(days=days))


# ---------------------------------------------------------------------------
# CrewMember — PRD §3.1
# ---------------------------------------------------------------------------
_seniority_seq: Dict[str, int] = {}


def next_seniority(rank: str) -> int:
    """Hand out a unique, strictly-positive seniority number per rank.
    PRD §3.1: "a strictly positive union_seniority_number (lower numbers
    indicate greater seniority and the number must be unique within rank)".
    Tests can still override via the factory's `union_seniority_number`
    parameter.
    """
    _seniority_seq[rank] = _seniority_seq.get(rank, 0) + 1
    return _seniority_seq[rank]


def create_crew_member_payload(rank: str = "CAPTAIN",
                                base_airport: Optional[str] = None,
                                union_seniority_number: Optional[int] = None,
                                union_local_id: Optional[str] = None,
                                **overrides) -> Dict[str, Any]:
    """PRD §3.1: creation takes employee_no, rank, base_airport,
    union_seniority_number, union_local_id."""
    payload = {
        "employee_no": random_employee_no(),
        "rank": rank,
        "base_airport": base_airport or TEST_DEFAULTS["BASE_AIRPORT_DEFAULT"],
        "union_seniority_number": (
            union_seniority_number
            if union_seniority_number is not None
            else next_seniority(rank)
        ),
        "union_local_id": union_local_id or "L-100",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Pairing / DutyPeriod / FlightLeg — PRD §3.1
# ---------------------------------------------------------------------------
def create_pairing_payload(pairing_code: Optional[str] = None,
                            base_airport: Optional[str] = None,
                            required_rank_composition: Optional[Dict] = None,
                            **overrides) -> Dict[str, Any]:
    """PRD §3.1: creation takes pairing_code, base_airport,
    required_rank_composition."""
    payload = {
        "pairing_code": pairing_code or random_pairing_code(),
        "base_airport": base_airport or TEST_DEFAULTS["BASE_AIRPORT_DEFAULT"],
        "required_rank_composition": (
            required_rank_composition
            if required_rank_composition is not None
            else {"CAPTAIN": 1}
        ),
    }
    payload.update(overrides)
    return payload


def create_duty_period_payload(sequence_no: int,
                                 report_at: str,
                                 release_at: str,
                                 **overrides) -> Dict[str, Any]:
    """PRD §3.1: creation takes sequence_no, report_at, release_at."""
    payload = {
        "sequence_no": int(sequence_no),
        "report_at": report_at,
        "release_at": release_at,
    }
    payload.update(overrides)
    return payload


def create_flight_leg_payload(leg_sequence_no: int,
                                flight_number: Optional[str],
                                dep_airport: str,
                                arr_airport: str,
                                dep_at: str,
                                arr_at: str,
                                leg_type: Optional[str] = None,
                                **overrides) -> Dict[str, Any]:
    """PRD §3.1: creation takes leg_sequence_no, flight_number,
    dep_airport, arr_airport, dep_at, arr_at, and optional leg_type
    (default REVENUE)."""
    payload: Dict[str, Any] = {
        "leg_sequence_no": int(leg_sequence_no),
        "flight_number": flight_number or random_flight_number(),
        "dep_airport": dep_airport,
        "arr_airport": arr_airport,
        "dep_at": dep_at,
        "arr_at": arr_at,
    }
    if leg_type is not None:
        payload["leg_type"] = leg_type
    payload.update(overrides)
    return payload


def open_bidding_payload(bid_window_id: Optional[str] = None,
                          **overrides) -> Dict[str, Any]:
    """PRD §3.2: open-bidding takes bid_window_id."""
    payload = {
        "bid_window_id": (
            bid_window_id or TEST_DEFAULTS["DEFAULT_BID_WINDOW_ID"]
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Bid — PRD §3.2
# ---------------------------------------------------------------------------
def create_bid_payload(pairing_id: str,
                        bid_window_id: str,
                        preference_rank: int = 1,
                        **overrides) -> Dict[str, Any]:
    """PRD §3.2: bid takes pairing_id, preference_rank, bid_window_id."""
    payload = {
        "pairing_id": pairing_id,
        "preference_rank": int(preference_rank),
        "bid_window_id": bid_window_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ReservePool — PRD §3.4
# ---------------------------------------------------------------------------
def create_reserve_pool_payload(crew_member_id: str,
                                  reserve_date: str,
                                  standby_start_at: str,
                                  standby_end_at: str,
                                  **overrides) -> Dict[str, Any]:
    """PRD §3.4: reserve-pool takes crew_member_id, reserve_date,
    standby_start_at, standby_end_at."""
    payload = {
        "crew_member_id": crew_member_id,
        "reserve_date": reserve_date,
        "standby_start_at": standby_start_at,
        "standby_end_at": standby_end_at,
    }
    payload.update(overrides)
    return payload


def call_out_reserve_payload(pairing_id: str,
                                assigned_rank_slot: str,
                                sick_call_id: Optional[str] = None,
                                **overrides) -> Dict[str, Any]:
    """PRD §3.4: call-out takes pairing_id, assigned_rank_slot, and
    optional sick_call_id."""
    payload: Dict[str, Any] = {
        "pairing_id": pairing_id,
        "assigned_rank_slot": assigned_rank_slot,
    }
    if sick_call_id is not None:
        payload["sick_call_id"] = sick_call_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# SickCall — PRD §3.4
# ---------------------------------------------------------------------------
def create_sick_call_payload(crew_member_id: str,
                                effective_from: str,
                                expected_return_at: str,
                                assignment_id: Optional[str] = None,
                                **overrides) -> Dict[str, Any]:
    """PRD §3.4: sick-call takes crew_member_id, optional assignment_id,
    effective_from, expected_return_at."""
    payload: Dict[str, Any] = {
        "crew_member_id": crew_member_id,
        "effective_from": effective_from,
        "expected_return_at": expected_return_at,
    }
    if assignment_id is not None:
        payload["assignment_id"] = assignment_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Assignment (admin override) — PRD §3.5
# ---------------------------------------------------------------------------
def create_assignment_payload(pairing_id: str,
                                crew_member_id: str,
                                assigned_rank_slot: str,
                                **overrides) -> Dict[str, Any]:
    """PRD §3.5: admin-override assignment takes pairing_id,
    crew_member_id, assigned_rank_slot."""
    payload = {
        "pairing_id": pairing_id,
        "crew_member_id": crew_member_id,
        "assigned_rank_slot": assigned_rank_slot,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TradeRequest — PRD §3.8
# ---------------------------------------------------------------------------
def create_trade_request_payload(initiator_assignment_id: str,
                                    counterparty_assignment_id: str,
                                    counterparty_id: str,
                                    **overrides) -> Dict[str, Any]:
    """PRD §3.8: trade request takes initiator_assignment_id,
    counterparty_assignment_id, counterparty_id."""
    payload = {
        "initiator_assignment_id": initiator_assignment_id,
        "counterparty_assignment_id": counterparty_assignment_id,
        "counterparty_id": counterparty_id,
    }
    payload.update(overrides)
    return payload


def counter_trade_payload(new_initiator_assignment_id: str,
                            new_counterparty_assignment_id: str,
                            **overrides) -> Dict[str, Any]:
    """PRD §3.8: counter takes new_initiator_assignment_id and
    new_counterparty_assignment_id."""
    payload = {
        "new_initiator_assignment_id": new_initiator_assignment_id,
        "new_counterparty_assignment_id": new_counterparty_assignment_id,
    }
    payload.update(overrides)
    return payload


def clock_advance_payload(target_at: str, **overrides) -> Dict[str, Any]:
    """PRD §3.7: clock advance takes target_at."""
    payload = {"target_at": target_at}
    payload.update(overrides)
    return payload


def version_body(version: int) -> Dict[str, Any]:
    """PRD §2.5: optimistic-concurrency PATCH body fragment."""
    return {"version": int(version)}


__all__ = [
    "add_days_iso",
    "add_hours_iso",
    "add_minutes_iso",
    "call_out_reserve_payload",
    "clock_advance_payload",
    "counter_trade_payload",
    "create_assignment_payload",
    "create_bid_payload",
    "create_crew_member_payload",
    "create_duty_period_payload",
    "create_flight_leg_payload",
    "create_pairing_payload",
    "create_reserve_pool_payload",
    "create_sick_call_payload",
    "create_trade_request_payload",
    "iso_from_dt",
    "iso_now_utc",
    "next_seniority",
    "open_bidding_payload",
    "parse_iso",
    "random_bid_window_id",
    "random_employee_no",
    "random_flight_number",
    "random_iata",
    "random_pairing_code",
    "random_suffix",
    "random_union_local_id",
    "version_body",
]
