"""FEFO bin allocation and lot pick selection. PRD §3.4 + §3.5."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..errors import ApiError
from ..store import get_store


INFINITY = 10**18


def zone_earliest_neighbour_expiry(zone_id: str) -> int:
    """Smallest expiry_minutes of any lot stored in any bin of `zone_id`.

    Returns INFINITY when the zone is empty.
    """
    store = get_store()
    earliest = INFINITY
    for lot in store.lots.values():
        bin_id = lot.get("bin_id")
        if not bin_id:
            continue
        b = store.bins.get(bin_id)
        if not b or b.get("zone_id") != zone_id:
            continue
        exp = lot.get("expiry_minutes")
        if exp is not None and exp < earliest:
            earliest = exp
    return earliest


def allocate_bin_fefo(
    warehouse_id: str,
    product: dict[str, Any],
    quantity_units: int,
) -> dict[str, Any]:
    """Choose a destination bin for a regular acceptance (non-quarantine).

    Filters per PRD §3.4 and orders by (zone_earliest_neighbour_expiry, zone.code, bin.code).
    Raises ERR_SEGREGATION_VIOLATION / ERR_BIN_CAPACITY_EXCEEDED / ERR_ZONE_CAPACITY_EXCEEDED /
    ERR_NO_ELIGIBLE_BIN per the validation table.
    """
    store = get_store()
    required_zone_type = product["required_zone_type"]
    required_tag = product.get("special_storage_tag", "NONE")
    unit_weight = Decimal(str(product["unit_weight_kg"]))
    total_weight = Decimal(quantity_units) * unit_weight

    # Step through filters, recording each failure category once so we can
    # surface the *priority* failure when the candidate set is empty.

    any_zone_type_match = False
    any_tag_match = False
    any_capacity_match = False
    any_zone_budget_match = False

    candidates: list[dict[str, Any]] = []

    for b in store.bins.values():
        if b.get("warehouse_id") != warehouse_id:
            continue
        if b.get("status") != "AVAILABLE":
            continue
        zone = store.zones.get(b["zone_id"])
        if not zone:
            continue
        if zone.get("zone_type") != required_zone_type:
            continue
        any_zone_type_match = True
        if zone.get("current_posture") != "OPEN":
            continue
        if b.get("special_storage_tag", "NONE") != required_tag:
            continue
        any_tag_match = True
        if int(b.get("volume_units", 0)) < int(quantity_units):
            continue
        if Decimal(str(b.get("weight_limit_kg", 0))) < total_weight:
            continue
        any_capacity_match = True
        if int(zone.get("utilization_units", 0)) + int(quantity_units) > int(zone.get("capacity_units", 0)):
            continue
        any_zone_budget_match = True
        candidates.append(b)

    if not candidates:
        # Priority order on what to surface: segregation > bin capacity > zone capacity > none.
        # (PRD §2.12: segregation @15, capacity @19, zone capacity @28.)
        if any_zone_type_match and not any_tag_match:
            raise ApiError(
                "ERR_SEGREGATION_VIOLATION",
                f"No available bin in {required_zone_type} zone with special_storage_tag={required_tag!r}",
            )
        if any_tag_match and not any_capacity_match:
            raise ApiError(
                "ERR_BIN_CAPACITY_EXCEEDED",
                "Receipt quantity/weight exceeds candidate bin capacity",
            )
        if any_capacity_match and not any_zone_budget_match:
            raise ApiError(
                "ERR_ZONE_CAPACITY_EXCEEDED",
                "Zone utilization would exceed capacity_units",
            )
        raise ApiError("ERR_NO_ELIGIBLE_BIN", "No bin satisfies FEFO allocation criteria")

    candidates.sort(
        key=lambda b: (
            zone_earliest_neighbour_expiry(b["zone_id"]),
            store.zones[b["zone_id"]]["code"],
            b["code"],
        )
    )
    return candidates[0]


def allocate_quarantine_bin(warehouse_id: str) -> dict[str, Any] | None:
    """Choose any AVAILABLE bin in a QUARANTINE-zone of this warehouse.

    The PRD does not require strict FEFO on quarantine bins; we apply
    deterministic ordering by (zone.code, bin.code) for stable behaviour.
    Returns None if no quarantine bin is available (callers decide whether
    to error or fall through to a synthetic bin).
    """
    store = get_store()
    candidates: list[dict[str, Any]] = []
    for b in store.bins.values():
        if b.get("warehouse_id") != warehouse_id:
            continue
        if b.get("status") != "AVAILABLE":
            continue
        zone = store.zones.get(b["zone_id"])
        if not zone or zone.get("zone_type") != "QUARANTINE":
            continue
        candidates.append(b)
    if not candidates:
        return None
    candidates.sort(key=lambda b: (store.zones[b["zone_id"]]["code"], b["code"]))
    return candidates[0]


def pick_fefo_lot(
    warehouse_id: str,
    product_id: str,
    quantity_units: int,
    clock_minutes: int,
) -> dict[str, Any]:
    """FEFO pick: smallest expiry_minutes among eligible lots.

    PRD §3.5: "walks every lot in the warehouse whose `product_id`
    matches the shipment's, whose `quality_status` is `RELEASED`,
    whose `expiry_minutes` is strictly greater than the warehouse's
    `clock_minutes`, and whose `quantity_on_hand` is at least the
    shipment's `quantity_units`."

    The quantity-on-hand check is one of the candidate-set FILTERS,
    not a post-selection assertion — a lot with insufficient stock is
    excluded from the candidate set and the FEFO walk continues to
    the next earliest-expiry lot.

    Raises ERR_NO_FEFO_LOT when the resulting candidate set is empty.
    ERR_INSUFFICIENT_STOCK is reserved for the race-condition case
    (PRD §2.11) where a candidate had stock at filter time but lost
    the atomic decrement race; that case is detected at the commit
    site, not here.
    """
    store = get_store()
    # Eligible lots: same product, RELEASED, not expired, sufficient on-hand.
    same_product = [
        L
        for L in store.lots.values()
        if L.get("warehouse_id") == warehouse_id
        and L.get("product_id") == product_id
        and L.get("quality_status") == "RELEASED"
        and int(L.get("expiry_minutes", 0)) > int(clock_minutes)
        and int(L.get("quantity_on_hand", 0)) >= int(quantity_units)
    ]
    if not same_product:
        raise ApiError("ERR_NO_FEFO_LOT", "No eligible lot for this product")

    # FEFO order: expiry asc, then created_at asc, then id asc.
    same_product.sort(key=lambda L: (int(L["expiry_minutes"]), L["created_at"], L["id"]))
    return same_product[0]
