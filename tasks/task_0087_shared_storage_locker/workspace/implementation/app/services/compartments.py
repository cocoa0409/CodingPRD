"""Compartment business logic."""
from __future__ import annotations

from typing import Any, Optional

from .. import constants
from ..auth import current_actor
from ..audit import emit_audit_event
from ..clock import now_dt
from ..errors import ApiError
from ..store import bump_version, common_fields_create, get_store
from .cabinets import get_cabinet_or_404
from .capacity import recompute_cabinet_capacity
from .serializers import serialize_compartment
from .validation import require_field, require_in, require_int


def get_compartment_or_404(compartment_id: str) -> dict[str, Any]:
    store = get_store()
    c = store.compartments.get(compartment_id)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", f"Compartment {compartment_id} not found.")
    return c


def get_nested_compartment(cabinet_id: str, compartment_id: str) -> dict[str, Any]:
    """Validate cabinet exists, then compartment exists, then compartment belongs to cabinet.
    Left-to-right validation per PRD §2.7."""
    get_cabinet_or_404(cabinet_id)
    c = get_compartment_or_404(compartment_id)
    if c["cabinet_id"] != cabinet_id:
        raise ApiError("ERR_NOT_FOUND", "Compartment does not belong to cabinet.")
    return c


def create_compartment(cabinet_id: str, body: dict[str, Any]) -> dict[str, Any]:
    cabinet = get_cabinet_or_404(cabinet_id)
    slot_number = require_int(require_field(body, "slot_number"), "slot_number", min_value=1)
    size_class = require_in(require_field(body, "size_class"), "size_class", constants.SIZE_CLASSES)

    store = get_store()
    key = (cabinet_id, slot_number)
    if key in store.slot_uniq:
        raise ApiError("ERR_DUPLICATE_SLOT", f"Slot {slot_number} already exists in cabinet.")

    comp = common_fields_create()
    comp.update(
        {
            "cabinet_id": cabinet_id,
            "slot_number": slot_number,
            "size_class": size_class,
            "operational_status": "OK",
            "occupancy_status": "IDLE",
            "fault_category": None,
            "active_rental_id": None,
            "holding_item_description": None,
            "holding_claim_deadline": None,
        }
    )
    store.compartments[comp["id"]] = comp
    store.slot_uniq[key] = comp["id"]

    # Recompute cabinet capacity (and bump cabinet version)
    recompute_cabinet_capacity(cabinet, bump=True)
    return serialize_compartment(comp)


def get_compartment(cabinet_id: str, compartment_id: str) -> dict[str, Any]:
    c = get_nested_compartment(cabinet_id, compartment_id)
    return serialize_compartment(c)


def list_compartments(
    cabinet_id: str,
    size_class: Optional[str],
    operational_status: Optional[str],
    occupancy_status: Optional[str],
) -> list[dict[str, Any]]:
    get_cabinet_or_404(cabinet_id)
    store = get_store()
    items = [c for c in store.compartments.values() if c["cabinet_id"] == cabinet_id]
    if size_class:
        items = [c for c in items if c["size_class"] == size_class]
    if operational_status:
        items = [c for c in items if c["operational_status"] == operational_status]
    if occupancy_status:
        items = [c for c in items if c["occupancy_status"] == occupancy_status]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    return [serialize_compartment(c) for c in items]


def claim_holding(compartment_id: str) -> dict[str, Any]:
    """Renter retrieves item from a HOLDING compartment (PRD §3.5)."""
    store = get_store()
    comp = get_compartment_or_404(compartment_id)

    if comp["occupancy_status"] != "HOLDING":
        raise ApiError("ERR_INVALID_STATE", "Compartment is not in HOLDING.")

    # Find the most-recent FORCE_CLEARED rental that landed on this compartment
    candidates = [
        r for r in store.rentals.values()
        if r["compartment_id"] == compartment_id and r["status"] == "FORCE_CLEARED"
    ]
    if not candidates:
        raise ApiError("ERR_NOT_FOUND", "No force-cleared rental on this compartment.")
    candidates.sort(key=lambda r: r.get("ended_at") or r["updated_at"], reverse=True)
    most_recent = candidates[0]

    actor_id, actor_role = current_actor()
    if most_recent["renter_id"] != actor_id:
        raise ApiError("ERR_FORBIDDEN", "Renter does not own the held item.")

    # Check claim window
    from ..clock import parse_iso
    deadline = comp.get("holding_claim_deadline")
    if deadline is None:
        raise ApiError("ERR_CLAIM_WINDOW_EXPIRED", "No claim window set.")
    try:
        deadline_dt = parse_iso(deadline)
    except ValueError:
        raise ApiError("ERR_BAD_REQUEST", "Invalid holding_claim_deadline.")
    if now_dt() > deadline_dt:
        raise ApiError("ERR_CLAIM_WINDOW_EXPIRED", "Holding claim window has expired.")

    comp["occupancy_status"] = "IDLE"
    comp["holding_item_description"] = None
    comp["holding_claim_deadline"] = None
    bump_version(comp)

    # Recompute cabinet capacity
    cabinet = store.cabinets[comp["cabinet_id"]]
    recompute_cabinet_capacity(cabinet, bump=True)

    emit_audit_event(
        event_kind="COMPARTMENT_OPENED",
        subject_type="Compartment",
        subject_id=comp["id"],
        actor_role=actor_role,
        actor_id=actor_id,
        unlock_channel="OPERATOR_OVERRIDE",
        detail={"reason": "holding_claim"},
    )

    return serialize_compartment(comp)
