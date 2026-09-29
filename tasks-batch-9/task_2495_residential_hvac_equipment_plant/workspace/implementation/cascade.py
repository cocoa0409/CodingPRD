"""Transitive cascades and derived-field reconciliation (PRD 2.9, 3.1, 3.3, 3.5, 3.9).

Ordering rules honoured here:
  * rows swept INTO a cascade are processed in ascending created_at
  * allocation lines revoked to rebalance a pool are processed in DESCENDING created_at
  * every row a cascade touches is mutated in its own right (updated_at + version)
"""

import db
import derive

HOLDABLE_BUILD_STATES = (
    "DRAFT",
    "COIL_FAB",
    "BRAZED",
    "REWORK",
    "LEAK_PASSED",
    "CHARGED",
    "RUN_PASSED",
)

OPEN_BUILD_STATES = ("COIL_FAB", "BRAZED", "REWORK", "LEAK_PASSED", "CHARGED", "RUN_PASSED")


def asc(rows):
    return sorted(rows, key=lambda r: r["_seq"])


def desc(rows):
    return sorted(rows, key=lambda r: r["_seq"], reverse=True)


# --------------------------------------------------------- warehouse space
def release_reservation(reservation, reason):
    """ACTIVE -> RELEASED, then the holding warehouse recomputes occupancy."""
    if reservation["status"] != "ACTIVE":
        return
    reservation["status"] = "RELEASED"
    reservation["released_at"] = db.db.stamp()
    reservation["release_reason"] = reason
    db.db.touch(reservation)
    warehouse = db.db.get("warehouses", reservation["warehouse_id"])
    if warehouse is not None:
        db.db.touch(warehouse)


def release_build_reservations(build, reason):
    for reservation in asc(derive.build_reservations(build, ("ACTIVE",))):
        release_reservation(reservation, reason)


# ------------------------------------------------------------ supply pools
def refresh_supply_status(supply):
    """EXHAUSTED <-> ACTIVE moves driven by the recomputed available balance."""
    available = derive.available_units(supply)
    if supply["status"] == "ACTIVE" and available == 0:
        supply["status"] = "EXHAUSTED"
    elif supply["status"] == "EXHAUSTED" and available > 0 and supply["derate_pct"] == 0:
        supply["status"] = "ACTIVE"


def _revoke_line(line, reason, pools, orders):
    line["status"] = "REVOKED"
    line["closed_reason"] = reason
    db.db.touch(line)
    pools.add(line["component_supply_id"])
    orders.add(line["distributor_order_id"])


def _release_line(line, reason, pools, orders):
    line["status"] = "RELEASED"
    line["closed_reason"] = reason
    db.db.touch(line)
    pools.add(line["component_supply_id"])
    orders.add(line["distributor_order_id"])


def _kit_siblings(line):
    order = db.db.get("orders", line["distributor_order_id"])
    if order is None:
        return []
    return [
        sibling
        for sibling in derive.order_lines(order, ("RESERVED",))
        if sibling["component_type"] != line["component_type"]
    ]


def reconcile_order_allocation(order):
    allocated = derive.allocated_units(order)
    if allocated <= 0:
        order["allocation_status"] = "UNALLOCATED"
    elif allocated < order["requested_units"]:
        order["allocation_status"] = "PARTIALLY_ALLOCATED"
    else:
        order["allocation_status"] = "FULLY_ALLOCATED"
    db.db.touch(order)


def rebalance_supply(supply, reason, skip_supply_touch=False):
    """Revoke RESERVED lines newest-first until available_units >= 0."""
    pools = set()
    orders = set()
    guard = 0
    while derive.available_units(supply) < 0:
        guard += 1
        if guard > 10000:
            break
        candidates = desc(derive.supply_lines(supply, ("RESERVED",)))
        if not candidates:
            break
        line = candidates[0]
        _revoke_line(line, reason, pools, orders)
        for sibling in asc(_kit_siblings(line)):
            _revoke_line(sibling, reason, pools, orders)

    for pool_id in sorted(pools, key=lambda pid: db.db.get("supplies", pid)["_seq"]):
        pool = db.db.get("supplies", pool_id)
        if pool is None:
            continue
        if pool_id == supply["id"] and skip_supply_touch:
            continue
        refresh_supply_status(pool)
        db.db.touch(pool)

    for order_id in sorted(orders, key=lambda oid: db.db.get("orders", oid)["_seq"]):
        order = db.db.get("orders", order_id)
        if order is not None:
            reconcile_order_allocation(order)
    return len(orders)


def release_order_lines(order, reason):
    """Order cancellation / platform retirement: RESERVED lines -> RELEASED."""
    pools = set()
    orders = set()
    for line in asc(derive.order_lines(order, ("RESERVED",))):
        _release_line(line, reason, pools, orders)
    for pool_id in sorted(pools, key=lambda pid: db.db.get("supplies", pid)["_seq"]):
        pool = db.db.get("supplies", pool_id)
        if pool is None:
            continue
        refresh_supply_status(pool)
        db.db.touch(pool)


# ---------------------------------------------------------------- platform
def hold_build_regulatory(build):
    build["status"] = "HOLD_REGULATORY"
    build["hold_reason"] = "REFRIGERANT_SELL_THROUGH"
    db.db.touch(build)
    release_build_reservations(build, "BUILD_ON_REGULATORY_HOLD")


def platform_builds(platform, statuses=None):
    rows = [b for b in db.db.rows("builds") if b["platform_id"] == platform["id"]]
    if statuses is not None:
        rows = [b for b in rows if b["status"] in statuses]
    return rows


def platform_orders(platform, fulfillment=None):
    rows = [o for o in db.db.rows("orders") if o["platform_id"] == platform["id"]]
    if fulfillment is not None:
        rows = [o for o in rows if o["fulfillment_status"] == fulfillment]
    return rows


def platform_certs(platform, statuses=None):
    rows = [c for c in db.db.rows("certs") if c["platform_id"] == platform["id"]]
    if statuses is not None:
        rows = [c for c in rows if c["status"] in statuses]
    return rows


def restrict_platform(platform):
    """RELEASED -> RESTRICTED with the depth-4 sell-through cascade beneath it."""
    platform["status"] = "RESTRICTED"
    db.db.touch(platform)
    for build in asc(platform_builds(platform, HOLDABLE_BUILD_STATES)):
        hold_build_regulatory(build)


def retire_platform(platform):
    """The four-hop retirement cascade of PRD 3.3."""
    platform["status"] = "RETIRED"
    db.db.touch(platform)

    # hop 1 -- certifications withdrawn
    for cert in asc(platform_certs(platform, ("DRAFT", "SUBMITTED", "CERTIFIED"))):
        cert["status"] = "WITHDRAWN"
        cert["withdrawn_at"] = db.db.stamp()
        db.db.touch(cert)

    # hop 2 -- caused by those withdrawals: salability recomputed
    db.db.touch(platform)

    # hop 3 -- open lots cancelled, their pallet space released
    for build in asc(platform_builds(platform, ("DRAFT", "HOLD_REGULATORY"))):
        build["status"] = "CANCELLED"
        build["closed_reason"] = "PLATFORM_RETIRED"
        db.db.touch(build)
        release_build_reservations(build, "BUILD_CANCELLED")

    # hop 4 -- pending demand cancelled, allocation released
    for order in asc(platform_orders(platform, "PENDING")):
        order["fulfillment_status"] = "CANCELLED"
        order["cancelled_at"] = db.db.stamp()
        release_order_lines(order, "PLATFORM_RETIRED")
        order["allocation_status"] = "UNALLOCATED"
        db.db.touch(order)


# ----------------------------------------------------------------- program
def program_platforms(program, statuses=None):
    rows = [
        p for p in db.db.rows("platforms") if p["refrigerant_program_id"] == program["id"]
    ]
    if statuses is not None:
        rows = [p for p in rows if p["status"] in statuses]
    return rows


def enter_sell_through(program):
    program["status"] = "SELL_THROUGH"
    program["sell_through_entered_at"] = db.db.stamp()
    db.db.touch(program)
    for platform in asc(program_platforms(program, ("RELEASED",))):
        restrict_platform(platform)


def expire_program(program):
    program["status"] = "EXPIRED"
    program["expired_at"] = db.db.stamp()
    db.db.touch(program)
    for platform in asc(
        program_platforms(program, ("DRAFT", "ENG_REVIEW", "RELEASED", "RESTRICTED"))
    ):
        retire_platform(platform)
