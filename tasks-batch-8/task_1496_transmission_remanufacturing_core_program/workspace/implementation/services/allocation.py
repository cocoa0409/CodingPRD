"""Parts reservation allocation (waterfall) and the PART_HOLD promotion scan.

Scaffold §1.3 parts_reservation_allocation + PRD §2.9 / §3.2.
"""

from db import db

ADAPTED_SURCHARGE_MINUTES = 30


def _allocatable_candidates(order, part_family, needed):
    cands = []
    for p in db.hard_parts.values():
        if p["part_family"] != part_family:
            continue
        # Must carry an interchange mapping to this order's model.
        mapped = any(
            m["hard_part_id"] == p["id"]
            and m["transmission_model_id"] == order["transmission_model_id"]
            for m in db.interchange_mappings.values()
        )
        if not mapped:
            continue
        if (p["qty_on_hand"] - p["qty_reserved"]) < needed:
            continue
        tier = next(
            m["tier"]
            for m in db.interchange_mappings.values()
            if m["hard_part_id"] == p["id"]
            and m["transmission_model_id"] == order["transmission_model_id"]
        )
        cands.append((p, tier))
    # Rank: DIRECT before ADAPTED; within tier unit_cost_cents ASC;
    # tie-break created_at ASC (never id).
    cands.sort(
        key=lambda pt: (
            0 if pt[1] == "DIRECT" else 1,
            pt[0]["unit_cost_cents"],
            pt[0]["created_at"],
        )
    )
    return cands


def try_allocate(order):
    """Run the full allocation for an order. Returns (picks, shortage_families).

    picks: list of {hard_part_id, part_family, qty, tier}
    Pure function — does not mutate anything.
    """
    required = sorted(
        order["pinned_spec"]["required_parts"], key=lambda line: line["part_family"]
    )
    picks = []
    shortages = []
    # Track hypothetical reservations so multiple lines in the same family
    # account for each other within this allocation run.
    hypo_reserved = {}

    def availability(p):
        return p["qty_on_hand"] - p["qty_reserved"] - hypo_reserved.get(p["id"], 0)

    for line in required:
        needed = line["qty"]
        fam = line["part_family"]
        cands = []
        for p in db.hard_parts.values():
            if p["part_family"] != fam:
                continue
            tier = None
            for m in db.interchange_mappings.values():
                if (
                    m["hard_part_id"] == p["id"]
                    and m["transmission_model_id"] == order["transmission_model_id"]
                ):
                    tier = m["tier"]
                    break
            if tier is None:
                continue
            if availability(p) < needed:
                continue
            cands.append((p, tier))
        cands.sort(
            key=lambda pt: (
                0 if pt[1] == "DIRECT" else 1,
                pt[0]["unit_cost_cents"],
                pt[0]["created_at"],
            )
        )
        if not cands:
            shortages.append(fam)
        else:
            p, tier = cands[0]
            hypo_reserved[p["id"]] = hypo_reserved.get(p["id"], 0) + needed
            picks.append(
                {
                    "hard_part_id": p["id"],
                    "part_family": fam,
                    "qty": needed,
                    "tier": tier,
                }
            )
    if shortages:
        return None, shortages
    return picks, []


def apply_picks(order, picks):
    """Commit reservation picks: bump qty_reserved and surcharge minutes."""
    now = db.now()
    for pick in picks:
        part = db.hard_parts[pick["hard_part_id"]]
        part["qty_reserved"] += pick["qty"]
        part["updated_at"] = now
        part["version"] += 1
        if pick["tier"] == "ADAPTED":
            order["surcharge_labor_minutes"] += ADAPTED_SURCHARGE_MINUTES
    order["reserved_parts"] = list(picks)
    order["shortage_parts"] = []


def release_reservations(order):
    """Release every reserved line back to its part (qty_reserved -= qty)."""
    if not order["reserved_parts"]:
        return
    now = db.now()
    for line in order["reserved_parts"]:
        part = db.hard_parts.get(line["hard_part_id"])
        if part is not None:
            part["qty_reserved"] -= line["qty"]
            part["updated_at"] = now
            part["version"] += 1
    order["reserved_parts"] = []


def promotion_scan():
    """After any availability-increasing event: iterate PART_HOLD orders in
    created_at ASC order; promote every order that fully resolves,
    re-checking availability after each promotion."""
    waiting = [o for o in db.reman_orders.values() if o["status"] == "PART_HOLD"]
    waiting.sort(key=lambda o: o["created_at"])
    now = db.now()
    for order in waiting:
        picks, shortages = try_allocate(order)
        if picks is not None:
            apply_picks(order, picks)
            order["status"] = "ASSEMBLY"
            order["updated_at"] = now
            order["version"] += 1
