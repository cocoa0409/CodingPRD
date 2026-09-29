"""Request-payload builders with valid defaults.

Each builder returns a payload that the PRD accepts as-is, so a test only names
the one or two fields the behaviour under test actually turns on. Keyword
overrides are merged last, and passing ``None`` for a field removes it from the
payload so the omitted-field pathways stay reachable.
"""

from typing import Any, Dict, List, Optional

from .constants import CLOCK_STARTUP_UTC
from .types import (
    ComplaintCategory,
    ExceptionReasonCode,
    RebateModel,
    RoomType,
)

Payload = Dict[str, Any]


def _merge(base: Payload, overrides: Payload) -> Payload:
    """Apply overrides, dropping any key whose override value is ``None``."""
    merged = dict(base)
    for key, value in overrides.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------


def clock_payload(to_iso8601: str = CLOCK_STARTUP_UTC, **overrides: Any) -> Payload:
    """PRD §2.5: the body carries ``to_iso8601``."""
    return _merge({"to_iso8601": to_iso8601}, overrides)


# ---------------------------------------------------------------------------
# Tournament
# ---------------------------------------------------------------------------


def tournament_payload(**overrides: Any) -> Payload:
    """A four-day event window (2026-09-10 → 2026-09-13, three nights)."""
    return _merge(
        {
            "name": "Fall Classic 2026",
            "rights_holder_org": "USYS",
            "destination_org": "Metro CVB",
            "start_date": "2026-09-10",
            "end_date": "2026-09-13",
            "booking_deadline": "2026-09-01T00:00:00Z",
            "stay_to_play_required": True,
            "share_pct_organizer": 0.5,
            "share_pct_rights_holder": 0.3,
            "share_pct_destination": 0.2,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Hotel and Team
# ---------------------------------------------------------------------------


def hotel_payload(**overrides: Any) -> Payload:
    return _merge(
        {
            "name": "Host Inn Metro",
            "city": "Metro",
            "total_rooms": 100,
            "distance_miles_from_venue": 3.0,
        },
        overrides,
    )


def team_payload(**overrides: Any) -> Payload:
    """A visiting team: 120 miles out, well beyond the local radius."""
    return _merge(
        {
            "name": "Riverside FC 16U",
            "home_city": "Farville",
            "home_state": "ST",
            "org_contact_email": "riverside@example.com",
            "distance_miles_from_venue": 120.0,
        },
        overrides,
    )


def local_team_payload(**overrides: Any) -> Payload:
    """A team inside the local radius of PRD §3.3."""
    return _merge(
        {
            "name": "Metro United 16U",
            "home_city": "Metro",
            "home_state": "ST",
            "org_contact_email": "metro@example.com",
            "distance_miles_from_venue": 10.0,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# HotelContract and RoomBlock
# ---------------------------------------------------------------------------


def hotel_contract_payload(
    tournament_id: str, hotel_id: str, **overrides: Any
) -> Payload:
    """A flat per-room-night rebate contract."""
    return _merge(
        {
            "tournament_id": tournament_id,
            "hotel_id": hotel_id,
            "negotiated_nightly_rate_cents": 14900,
            "rebate_model": RebateModel.PER_ROOM_NIGHT_FLAT.value,
            "rebate_flat_cents_per_room_night": 900,
            "attrition_threshold_pct": 0.1,
            "attrition_penalty_rate_cents_per_room_night": 900,
            "cutoff_date": "2026-08-20",
        },
        overrides,
    )


def percent_contract_payload(
    tournament_id: str, hotel_id: str, **overrides: Any
) -> Payload:
    """A percent-of-room-revenue rebate contract."""
    return _merge(
        hotel_contract_payload(
            tournament_id,
            hotel_id,
            rebate_model=RebateModel.PERCENT_OF_ROOM_REVENUE.value,
            rebate_percent=0.08,
            rebate_flat_cents_per_room_night=None,
        ),
        overrides,
    )


def tiered_contract_payload(
    tournament_id: str, hotel_id: str, **overrides: Any
) -> Payload:
    """A tiered per-room-night rebate contract (PRD §3.7 tier table)."""
    return _merge(
        hotel_contract_payload(
            tournament_id,
            hotel_id,
            rebate_model=RebateModel.TIERED_PER_ROOM_NIGHT.value,
            rebate_flat_cents_per_room_night=None,
        ),
        overrides,
    )


def negotiation_payload(action: str, **overrides: Any) -> Payload:
    return _merge({"action": action}, overrides)


def room_block_payload(contract_id: str, **overrides: Any) -> Payload:
    """A 20-room block spanning the whole event window."""
    return _merge(
        {
            "contract_id": contract_id,
            "room_type": RoomType.DOUBLE_QUEEN.value,
            "block_size_rooms": 20,
            "arrival_date": "2026-09-10",
            "departure_date": "2026-09-13",
            "release_deadline": "2026-08-25",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# TeamRegistration
# ---------------------------------------------------------------------------


def team_registration_payload(
    tournament_id: str, team_id: str, **overrides: Any
) -> Payload:
    """A 13-player, 3-staff roster."""
    return _merge(
        {
            "tournament_id": tournament_id,
            "team_id": team_id,
            "roster_player_count": 13,
            "roster_staff_count": 3,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------


def booking_payload(
    registration_id: str,
    room_block_id: str,
    expected_registration_version: int,
    **overrides: Any,
) -> Payload:
    """A four-room, three-night booking inside the default block window."""
    return _merge(
        {
            "registration_id": registration_id,
            "room_block_id": room_block_id,
            "rooms_requested": 4,
            "check_in_date": "2026-09-10",
            "check_out_date": "2026-09-13",
            "expected_registration_version": expected_registration_version,
        },
        overrides,
    )


def rooming_list_entry(
    room_index: int, occupant_count: int = 4, minor_occupant_count: int = 0, **overrides: Any
) -> Payload:
    return _merge(
        {
            "room_index": room_index,
            "occupant_count": occupant_count,
            "minor_occupant_count": minor_occupant_count,
        },
        overrides,
    )


def rooming_list_payload(
    entries: Optional[List[Payload]] = None, rooms: int = 4, **overrides: Any
) -> Payload:
    """Either an explicit entry list, or ``rooms`` full rooms of four adults."""
    if entries is None:
        entries = [rooming_list_entry(index + 1) for index in range(rooms)]
    return _merge({"entries": entries}, overrides)


def cancel_payload(
    cancellation_reason: str = "team withdrew from the event", **overrides: Any
) -> Payload:
    return _merge({"cancellation_reason": cancellation_reason}, overrides)


def actualization_payload(reported_room_nights: int, **overrides: Any) -> Payload:
    return _merge(
        {
            "reported_room_nights": reported_room_nights,
            "report_note": "folio at checkout",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# ExceptionRequest
# ---------------------------------------------------------------------------


def exception_request_payload(registration_id: str, **overrides: Any) -> Payload:
    return _merge(
        {
            "registration_id": registration_id,
            "reason_code": ExceptionReasonCode.FAMILY_MEDICAL.value,
            "requested_rooms_exempt": 1,
            "justification": "one player travels with a medical caregiver",
        },
        overrides,
    )


def local_exception_request_payload(registration_id: str, **overrides: Any) -> Payload:
    """A ``LOCAL_TEAM`` filing, which PRD §3.6 treats specially."""
    return _merge(
        exception_request_payload(
            registration_id,
            reason_code=ExceptionReasonCode.LOCAL_TEAM.value,
            requested_rooms_exempt=4,
            justification="the team sleeps at home, ten miles from the venue",
        ),
        overrides,
    )


def review_payload(action: str, **overrides: Any) -> Payload:
    return _merge({"action": action}, overrides)


def team_action_payload(action: str, **overrides: Any) -> Payload:
    return _merge({"action": action}, overrides)


# ---------------------------------------------------------------------------
# Complaint
# ---------------------------------------------------------------------------


def complaint_payload(tournament_id: str, **overrides: Any) -> Payload:
    return _merge(
        {
            "tournament_id": tournament_id,
            "category": ComplaintCategory.PRICING_FAIRNESS.value,
            "narrative": "the cancellation penalty tier was misapplied",
        },
        overrides,
    )


def triage_payload(route: str, **overrides: Any) -> Payload:
    return _merge({"route": route}, overrides)


def adjudicate_payload(outcome: str, remedy_type: str, **overrides: Any) -> Payload:
    return _merge({"outcome": outcome, "remedy_type": remedy_type}, overrides)


# ---------------------------------------------------------------------------
# RebateInvoice and RevenueDistribution
# ---------------------------------------------------------------------------


def rebate_invoice_payload(contract_id: str, **overrides: Any) -> Payload:
    return _merge({"contract_id": contract_id, "period_label": "2026-09"}, overrides)


def lifecycle_payload(action: str, **overrides: Any) -> Payload:
    return _merge({"action": action}, overrides)


def remit_payload(amount_cents: int, **overrides: Any) -> Payload:
    return _merge({"amount_cents": amount_cents}, overrides)


def revenue_distribution_payload(
    tournament_id: str, source_invoice_id: str, expected_invoice_version: int, **overrides: Any
) -> Payload:
    return _merge(
        {
            "tournament_id": tournament_id,
            "source_invoice_id": source_invoice_id,
            "expected_invoice_version": expected_invoice_version,
        },
        overrides,
    )


def advance_payload(action: str, **overrides: Any) -> Payload:
    return _merge({"action": action}, overrides)
