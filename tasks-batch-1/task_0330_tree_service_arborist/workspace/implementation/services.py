"""Cross-cutting domain logic: hazard recompute, estimate recompute,
requires_permit derivation, and serialization shaping."""
import calculations
import db


# ---------------------------------------------------------------------------
# Tree / WorkOrder hazard + permit derivation
# ---------------------------------------------------------------------------
def compute_tree_hazard(tree):
    """Compute and store a single tree's hazard_score and hazard_tier."""
    score, tier = calculations.tree_hazard_score(
        tree["dbh_inches"], tree["lean_degrees"], tree["has_visible_decay"])
    tree["hazard_score"] = score
    tree["hazard_tier"] = tier
    return tree


def trees_of_wo(wid):
    return [t for t in db.trees.values() if t["work_order_id"] == wid]


def derive_requires_permit(wo):
    """requires_permit iff any child tree is protected/heritage AND the
    service area requires permit authority."""
    area = db.service_areas.get(wo["service_area_id"])
    authority = bool(area["requires_permit_authority"]) if area else False
    if not authority:
        return False
    for t in trees_of_wo(wo["id"]):
        if t["is_protected"] or t["is_heritage"]:
            return True
    return False


def recompute_work_order_hazard(wo):
    """Recompute every child tree's hazard, set hazard_level + requires_permit.
    (Used by assess.)"""
    tiers = []
    for t in trees_of_wo(wo["id"]):
        compute_tree_hazard(t)
        tiers.append(t["hazard_tier"])
    wo["hazard_level"] = calculations.hazard_level_from_tiers(tiers)
    wo["requires_permit"] = derive_requires_permit(wo)


# ---------------------------------------------------------------------------
# Estimate recompute
# ---------------------------------------------------------------------------
def line_items_of_estimate(eid):
    return [li for li in db.line_items.values() if li["estimate_id"] == eid]


def recompute_estimate(estimate):
    """Recompute subtotal, surcharges, and total for an estimate from its
    line items and the parent work order context. Stores results in place."""
    wo = db.work_orders.get(estimate["work_order_id"])
    area = db.service_areas.get(wo["service_area_id"]) if wo else None

    items = line_items_of_estimate(estimate["id"])
    subtotal = sum(li["extended_cost_cents"] for li in items)

    # Distinct near_utility_line trees referenced by REMOVAL or UTILITY_CLEARANCE lines.
    utility_tree_ids = set()
    for li in items:
        if li["service_type"] in ("REMOVAL", "UTILITY_CLEARANCE"):
            tid = li.get("tree_asset_id")
            if tid:
                tree = db.trees.get(tid)
                if tree and tree.get("near_utility_line"):
                    utility_tree_ids.add(tid)

    # Heritage: any REMOVAL line referencing a heritage tree.
    has_heritage_removal = False
    for li in items:
        if li["service_type"] == "REMOVAL":
            tid = li.get("tree_asset_id")
            if tid:
                tree = db.trees.get(tid)
                if tree and tree.get("is_heritage"):
                    has_heritage_removal = True
                    break

    heritage_pct = area["heritage_surcharge_pct"] if area else 0

    result = calculations.estimate_total(
        line_items_subtotal_cents=subtotal,
        hazard_level=wo["hazard_level"] if wo else "LOW",
        pricing_mode=estimate["pricing_mode"],
        is_emergency=bool(wo["is_emergency"]) if wo else False,
        heritage_surcharge_pct=heritage_pct,
        utility_tree_count=len(utility_tree_ids),
        has_heritage_removal=has_heritage_removal,
    )

    estimate["line_items_subtotal_cents"] = subtotal
    estimate["hazard_surcharge_cents"] = result["hazard_surcharge_cents"]
    estimate["utility_surcharge_cents"] = result["utility_surcharge_cents"]
    estimate["heritage_surcharge_cents"] = result["heritage_surcharge_cents"]
    estimate["total_cents"] = result["total_cents"]
    estimate["emergency_multiplier_applied"] = result["emergency_multiplier_applied"]
    db.touch(estimate)


# ---------------------------------------------------------------------------
# Booking overlap helpers
# ---------------------------------------------------------------------------
def active_bookings_for_resource(resource_kind, resource_id, exclude_id=None):
    """RESERVED/FINALIZED bookings of a given crew/equipment (occupy the calendar)."""
    out = []
    for b in db.bookings.values():
        if b["id"] == exclude_id:
            continue
        if b["status"] not in ("RESERVED", "FINALIZED"):
            continue
        if resource_kind == "CREW" and b["resource_kind"] == "CREW" and b["crew_id"] == resource_id:
            out.append(b)
        elif resource_kind == "EQUIPMENT" and b["resource_kind"] == "EQUIPMENT" and b["equipment_id"] == resource_id:
            out.append(b)
    return out
