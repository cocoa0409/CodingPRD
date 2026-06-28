"""Shared business-logic helpers: lookups, cascades, derived-field recompute.

These functions enforce the state machines and side effects from scaffold §1.2
and PRD §3. Every derived recompute touches the owning resource (refresh
updated_at, bump version) per PRD §2.4 / §2.5.
"""
import db
import calculations as calc
from clock import clock, parse_iso
from errors import err


# --------------------------------------------------------------------------
# Lookups (existence, ERR_NOT_FOUND)
# --------------------------------------------------------------------------
def must_get(table, rec_id):
    rec = db.get(table, rec_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "%s %s not found." % (table, rec_id))
    return rec


def species_by_id(species_id):
    return must_get("species_profiles", species_id)


# --------------------------------------------------------------------------
# Children helpers
# --------------------------------------------------------------------------
def entry_points_of_inspection(inspection_id):
    return [
        ep for ep in db.values("entry_points")
        if ep["inspection_id"] == inspection_id
    ]


def line_items_of_quote(quote_id):
    return [
        li for li in db.values("quote_line_items")
        if li["quote_id"] == quote_id
    ]


def trap_placements_of_wo(work_order_id):
    return [
        tp for tp in db.values("trap_placements")
        if tp["work_order_id"] == work_order_id
    ]


def exclusion_repairs_of_wo(work_order_id):
    return [
        er for er in db.values("exclusion_repairs")
        if er["work_order_id"] == work_order_id
    ]


def permits_of_wo(work_order_id):
    return [
        p for p in db.values("permits")
        if p["work_order_id"] == work_order_id
    ]


# --------------------------------------------------------------------------
# Inspection derived field
# --------------------------------------------------------------------------
def refresh_detected_individual_count(inspection):
    total = sum(
        ep["estimated_individuals"]
        for ep in entry_points_of_inspection(inspection["id"])
    )
    inspection["detected_individual_count"] = total
    db.touch(inspection)


# --------------------------------------------------------------------------
# Technician kit (PRD §2.8)
# --------------------------------------------------------------------------
def kit_deploy(technician):
    """Draw a trap from the kit (on SET)."""
    technician["traps_deployed"] += 1
    technician["traps_available"] = (
        technician["kit_trap_capacity"] - technician["traps_deployed"]
    )
    db.touch(technician)


def kit_restore(technician):
    """Return a trap to the kit (leaving SET via capture/pull/cancel)."""
    technician["traps_deployed"] -= 1
    technician["traps_available"] = (
        technician["kit_trap_capacity"] - technician["traps_deployed"]
    )
    db.touch(technician)


# --------------------------------------------------------------------------
# Property posture
# --------------------------------------------------------------------------
def set_posture(prop, posture):
    """Reconcile a property's derived posture. PRD §2.4/§2.5: a derived recompute
    refreshes updated_at and bumps version, like a client-driven edit."""
    prop["posture"] = posture
    db.touch(prop)


# --------------------------------------------------------------------------
# Risk scores (calc infestation_risk_score)
# --------------------------------------------------------------------------
def compute_initial_risk(inspection_id):
    eps = entry_points_of_inspection(inspection_id)
    return calc.infestation_risk_score(eps, species_by_id)


def compute_residual_risk(inspection_id):
    eps = [
        ep for ep in entry_points_of_inspection(inspection_id)
        if ep["seal_status"] == "OPEN"
    ]
    return calc.infestation_risk_score(eps, species_by_id)


# --------------------------------------------------------------------------
# WorkOrder helpers
# --------------------------------------------------------------------------
def inspection_of_work_order(wo):
    quote = db.get("quotes", wo["quote_id"])
    return db.get("inspections", quote["inspection_id"]) if quote else None


def find_trap_line_item(quote_id, species_id):
    """First not-yet-performed TRAP line for this species on the quote."""
    candidates = [
        li for li in line_items_of_quote(quote_id)
        if li["line_type"] == "TRAP" and li["species_id"] == species_id
    ]
    for li in candidates:
        if not li["performed"]:
            return li
    return candidates[0] if candidates else None


def remaining_set_traps(work_order_id):
    return [
        tp for tp in trap_placements_of_wo(work_order_id)
        if tp["status"] == "SET"
    ]


def ever_set_any_trap(work_order_id):
    return any(
        tp["status"] in ("SET", "SPENT", "EMPTY")
        for tp in trap_placements_of_wo(work_order_id)
    )


def perform_trap_line_for_species(quote_id, species_id):
    li = find_trap_line_item(quote_id, species_id)
    if li and not li["performed"]:
        li["performed"] = True
        db.touch(li)


def trapped_species_ids(work_order_id):
    """Distinct species among non-cancelled trap placements on the work order."""
    ids = []
    for tp in trap_placements_of_wo(work_order_id):
        if tp["status"] in ("SET", "SPENT", "EMPTY") and tp["species_id"] not in ids:
            ids.append(tp["species_id"])
    return ids


def maybe_clear_removal(wo):
    """If no SET trap remains, advance removal_status to CLEARED and flip TRAP lines.

    PRD §3.6: when no trap remains SET, removal_status -> CLEARED and the matching
    TRAP line item's performed flag is set true. Mutates wo in place WITHOUT a
    version bump — the calling field-work handler owns the work order's single
    version bump per §2.6.
    """
    if remaining_set_traps(wo["id"]):
        return
    wo["removal_status"] = "CLEARED"
    for sid in trapped_species_ids(wo["id"]):
        perform_trap_line_for_species(wo["quote_id"], sid)


def maybe_seal_exclusion(wo):
    """exclusion_status SEALING -> SEALED when all targeted OPEN entry points sealed.

    'all of the open entry points targeted by repairs are sealed' — i.e. every
    entry point that has a repair targeting it is now SEALED.
    """
    repairs = exclusion_repairs_of_wo(wo["id"])
    if not repairs:
        return
    targeted_ep_ids = {er["entry_point_id"] for er in repairs}
    all_sealed = True
    for ep_id in targeted_ep_ids:
        ep = db.get("entry_points", ep_id)
        if ep is None or ep["seal_status"] != "SEALED":
            all_sealed = False
            break
    if all_sealed and wo["exclusion_status"] == "SEALING":
        # Mutate in place WITHOUT a version bump — the calling complete handler
        # owns the work order's single version bump per §2.6.
        wo["exclusion_status"] = "SEALED"


def maybe_auto_close(wo):
    """Auto-close OPEN->CLOSED when both dimensions terminal (PRD §3.6)."""
    if wo["lifecycle"] != "OPEN":
        return
    if wo["removal_status"] == "CLEARED" and wo["exclusion_status"] == "SEALED":
        close_work_order(wo)


def close_work_order(wo):
    """WorkOrder OPEN->CLOSED system transition (scaffold §1.2, PRD §3.6)."""
    quote = db.get("quotes", wo["quote_id"])
    line_items = line_items_of_quote(quote["id"])
    emergency = quote["emergency_flag"]

    final_total = calc.quote_final_total(line_items, emergency)
    quote["final_total_cents"] = final_total
    db.touch(quote)

    wo["lifecycle"] = "CLOSED"
    wo["net_charged_cents"] = final_total
    inspection = db.get("inspections", quote["inspection_id"])
    wo["residual_risk_score"] = compute_residual_risk(inspection["id"])
    db.touch(wo)
    # Pin the close timestamp for warranty-deadline arithmetic (PRD §3.9). Stored
    # privately so it does not appear in the serialized work order.
    wo["_closed_at"] = wo["updated_at"]

    prop = db.get("properties", wo["property_id"])
    if prop:
        set_posture(prop, "OPEN")


def cancel_set_traps_and_restore(wo):
    """Move every SET trap to CANCELLED and restore each to its technician's kit."""
    for tp in trap_placements_of_wo(wo["id"]):
        if tp["status"] == "SET":
            tp["status"] = "CANCELLED"
            db.touch(tp)
            tech = db.get("technicians", tp["technician_id"])
            if tech:
                kit_restore(tech)


# --------------------------------------------------------------------------
# Window / overlap helpers
# --------------------------------------------------------------------------
def trap_windows_overlap(a_start, a_end, b_start, b_end, buffer_minutes):
    """Closed intervals inflated by buffer on each side overlap?"""
    from datetime import timedelta
    buf = timedelta(minutes=buffer_minutes)
    a_lo, a_hi = a_start - buf, a_end + buf
    b_lo, b_hi = b_start - buf, b_end + buf
    # Closed-interval overlap.
    return a_lo <= b_hi and b_lo <= a_hi


def visit_windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open intervals [start, end) overlap?"""
    return a_start < b_end and b_start < a_end
