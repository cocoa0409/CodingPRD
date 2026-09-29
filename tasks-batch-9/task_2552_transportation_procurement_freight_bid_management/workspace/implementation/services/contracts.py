"""The contract's committed value, its rate basis and the carrier commitment rollups —
PRD §3.8 and the status sets of §2.12."""
from decimal import Decimal

import store
from numeric import D, q2
from services import bidding

BASIS_RATE_STATUSES = ("STAGED", "LOADED", "LIVE", "AT_RISK")

VOLUME_DISCOUNT_TIERS = (
    (Decimal("1500000"), Decimal("0.025")),
    (Decimal("500000"), Decimal("0.015")),
    (Decimal("0"), Decimal("0.000")),
)
ACCESSORIAL_ALLOWANCE_TIERS = (
    (Decimal("1200000"), Decimal("0.020")),
    (Decimal("400000"), Decimal("0.010")),
    (Decimal("0"), Decimal("0.000")),
)


def record_committed_value(record, event):
    """Derive the record's own committed value exactly as bid evaluation derives a
    rate: the effective per-mile rate, the lane linehaul, then the volume."""
    lane = store.lanes.get(record["lane_id"])
    mileage = D(lane["mileage"]) if lane else Decimal("0")
    rate = bidding.effective_rate(record["rate_per_mile"],
                                  record["fuel_surcharge_included"], event)
    linehaul = q2(mileage * rate)
    return q2(linehaul * D(record["committed_volume_loads"]))


def contract_records(contract_id):
    return store.sorted_rows([r for r in store.rate_records.values()
                              if r["contract_id"] == contract_id])


def recompute_rate_record_count(contract):
    contract["rate_record_count"] = sum(
        1 for r in contract_records(contract["id"])
        if r["status"] in BASIS_RATE_STATUSES)


def _tier(value, tiers):
    for floor, pct in tiers:
        if value >= floor:
            return pct
    return Decimal("0.000")


def recompute_committed_value(contract, event):
    """The basis excludes SUPERSEDED and ROLLED_BACK records, which is exactly how a
    mini-bid apply removes the old rate's value and a revert removes the replacement's.
    The volume discount reads the base; the accessorial allowance reads the
    post-discount subtotal."""
    base = Decimal("0")
    for record in contract_records(contract["id"]):
        if record["status"] in BASIS_RATE_STATUSES:
            base += D(record["committed_value_usd"] or 0)
    base = q2(base)
    contract["base_committed_value_usd"] = base

    discount_pct = _tier(base, VOLUME_DISCOUNT_TIERS)
    contract["volume_discount_pct"] = discount_pct
    discount = q2(base * discount_pct)
    contract["volume_discount_usd"] = discount
    subtotal = q2(base - discount)

    allowance_pct = _tier(subtotal, ACCESSORIAL_ALLOWANCE_TIERS)
    contract["accessorial_allowance_pct"] = allowance_pct
    allowance = q2(subtotal * allowance_pct)
    contract["accessorial_allowance_usd"] = allowance

    contract["total_committed_value_usd"] = q2(subtotal + allowance)
    return contract["total_committed_value_usd"]


def recompute_carrier_commitments(carrier):
    """active_primary_lane_count and committed_volume_loads, each over its own
    allocation status set (PRD §2.12)."""
    primary = 0
    volume = 0
    for allocation in store.allocations.values():
        if allocation["carrier_id"] != carrier["id"]:
            continue
        if (allocation["routing_position"] == "PRIMARY"
                and allocation["status"] in ("EXECUTED", "ACTIVE")):
            primary += 1
        if allocation["status"] in ("EXECUTED", "ACTIVE", "SUSPENDED_ROUTING"):
            volume += allocation["allocated_volume_loads"]
    carrier["active_primary_lane_count"] = primary
    carrier["committed_volume_loads"] = volume


def interval_overlaps(record, effective_from, effective_to, exclude_ids=()):
    """Half-open intervals: two records where one's effective_to is exactly the other's
    effective_from are adjacent and do not overlap."""
    start = store.parse_dt(effective_from)
    end = store.parse_dt(effective_to)
    for other in store.rate_records.values():
        if other["id"] == record["id"] or other["id"] in exclude_ids:
            continue
        if (other["lane_id"] != record["lane_id"]
                or other["carrier_id"] != record["carrier_id"]
                or other["routing_position"] != record["routing_position"]):
            continue
        if other["status"] not in ("LOADED", "LIVE", "AT_RISK"):
            continue
        other_start = store.parse_dt(other["effective_from"])
        other_end = store.parse_dt(other["effective_to"])
        if start < other_end and other_start < end:
            return True
    return False
