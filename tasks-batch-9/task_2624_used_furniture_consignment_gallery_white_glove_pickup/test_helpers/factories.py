"""Request-payload factories.

Every factory returns only the fields a client is allowed to send. System and
computed columns are never seeded from a payload; the API derives them.
"""

import uuid
from typing import Any, Dict, List, Optional

from .constants import SCORES_GRADE_B


def unique_suffix() -> str:
    """Short random tail so unique-constrained fields never collide."""
    return uuid.uuid4().hex[:12]


def unique_email(prefix: str = "person") -> str:
    return f"{prefix}-{unique_suffix()}@example.test"


def unique_tag_code(prefix: str = "TAG") -> str:
    return f"{prefix}-{unique_suffix().upper()}"


# --- People -----------------------------------------------------------------

def consignor_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "display_name": f"Consignor {unique_suffix()}",
        "email": unique_email("consignor"),
        "address_line": "18 Harbour Lane",
        "floor_number": 1,
        "has_elevator": False,
    }
    payload.update(overrides)
    return payload


def buyer_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "display_name": f"Buyer {unique_suffix()}",
        "email": unique_email("buyer"),
        "address_line": "402 Kingfisher Street",
        "floor_number": 1,
        "has_elevator": False,
    }
    payload.update(overrides)
    return payload


# --- Pricing paperwork ------------------------------------------------------

def price_schedule_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": f"Schedule {unique_suffix()}",
        "unsold_trigger_day": 120,
        "election_window_days": 14,
    }
    payload.update(overrides)
    return payload


def price_schedule_step_payload(
    schedule_id: str,
    sequence: int,
    start_day_offset: int,
    markdown_pct: float,
    min_price_cents: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "schedule_id": schedule_id,
        "sequence": sequence,
        "start_day_offset": start_day_offset,
        "markdown_pct": markdown_pct,
        "min_price_cents": min_price_cents,
    }
    payload.update(overrides)
    return payload


def agreement_payload(
    consignor_id: str, price_schedule_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "consignor_id": consignor_id,
        "price_schedule_id": price_schedule_id,
        "term_days": 365,
    }
    payload.update(overrides)
    return payload


# --- Merchandise ------------------------------------------------------------

def item_payload(agreement_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "agreement_id": agreement_id,
        "title": f"Piece {unique_suffix()}",
        "category": "SOFA",
        "declared_value_cents": 189_950,
        "photo_count": 6,
        "volume_cuft": 40,
        "footprint_sqft": 20,
    }
    payload.update(overrides)
    return payload


def screen_payload(
    decision: str = "ACCEPT", scores: Optional[Dict[str, float]] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(dict(scores if scores is not None else SCORES_GRADE_B))
    payload.update(overrides)
    return payload


def receive_payload(
    scores: Optional[Dict[str, float]] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = dict(scores if scores is not None else SCORES_GRADE_B)
    payload.update(overrides)
    return payload


def place_payload(
    placement_zone_id: str, tag_code: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "placement_zone_id": placement_zone_id,
        "tag_code": tag_code if tag_code is not None else unique_tag_code(),
    }
    payload.update(overrides)
    return payload


def elect_disposition_payload(election: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"election": election}
    payload.update(overrides)
    return payload


def inventory_flag_payload(flag: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"flag": flag}
    payload.update(overrides)
    return payload


def write_off_payload(expected_item_version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_item_version": expected_item_version}
    payload.update(overrides)
    return payload


# --- Logistics resources ----------------------------------------------------

def truck_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": f"Truck {unique_suffix()}",
        "capacity_volume_cuft": 600,
    }
    payload.update(overrides)
    return payload


def crew_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": f"Crew {unique_suffix()}",
        "max_concurrent_jobs": 2,
    }
    payload.update(overrides)
    return payload


def floor_zone_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": f"Zone {unique_suffix()}",
        "zone_type": "SHOWROOM_FRONT",
        "capacity_sqft": 1_000,
    }
    payload.update(overrides)
    return payload


def pickup_job_payload(
    consignor_id: str,
    truck_id: str,
    window_start: str,
    window_end: str,
    crew_size: int = 2,
    item_ids: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "consignor_id": consignor_id,
        "truck_id": truck_id,
        "window_start": window_start,
        "window_end": window_end,
        "crew_size": crew_size,
    }
    if item_ids is not None:
        payload["item_ids"] = item_ids
    payload.update(overrides)
    return payload


def attach_item_payload(item_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"item_id": item_id}
    payload.update(overrides)
    return payload


def complete_pickup_payload(
    actual_stair_flights: int = 0,
    actual_elevator_used: bool = False,
    actual_crew_size: int = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "actual_stair_flights": actual_stair_flights,
        "actual_elevator_used": actual_elevator_used,
        "actual_crew_size": actual_crew_size,
    }
    payload.update(overrides)
    return payload


# --- Selling and delivering -------------------------------------------------

def sale_payload(
    item_id: str, buyer_id: str, sale_price_cents: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "item_id": item_id,
        "buyer_id": buyer_id,
        "sale_price_cents": sale_price_cents,
    }
    payload.update(overrides)
    return payload


def delivery_order_payload(
    sale_id: str, crew_id: str, window_start: str, window_end: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "sale_id": sale_id,
        "crew_id": crew_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def complete_delivery_payload(outcome: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    payload.update(overrides)
    return payload


# --- Claims, audits, payouts ------------------------------------------------

def damage_claim_payload(
    delivery_order_id: str, claim_amount_cents: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "delivery_order_id": delivery_order_id,
        "claim_amount_cents": claim_amount_cents,
        "description": "Corner crushed in transit; veneer lifted along the front rail.",
    }
    payload.update(overrides)
    return payload


def request_info_payload(note: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "info_request_note": note
        if note is not None
        else "Please send photographs of the damaged rail.",
    }
    payload.update(overrides)
    return payload


def resubmit_payload(
    description: Optional[str] = None,
    withdraw: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "description": description
        if description is not None
        else "Photographs attached, damage visible along the front rail.",
    }
    if withdraw is not None:
        payload["withdraw"] = withdraw
    payload.update(overrides)
    return payload


def adjudicate_payload(
    approve: bool, fault_party: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"approve": approve, "fault_party": fault_party}
    payload.update(overrides)
    return payload


def shrinkage_audit_payload(
    floor_zone_id: str, counted_item_ids: List[str], **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "floor_zone_id": floor_zone_id,
        "counted_item_ids": list(counted_item_ids),
    }
    payload.update(overrides)
    return payload


def payout_payload(expected_consignor_version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_consignor_version": expected_consignor_version
    }
    payload.update(overrides)
    return payload


def clock_payload(current_utc: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"current_utc": current_utc}
    payload.update(overrides)
    return payload
