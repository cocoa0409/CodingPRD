"""Derived fields, recomputations and cascades (PRD §2.10, §3)."""
import calc
from db import base_record, db, sort_records, touch

# --------------------------------------------------------------------------
# Lookup helpers
# --------------------------------------------------------------------------
def specs_of_school(school_id):
    return [s for s in db.grade_kit_specs.values() if s["school_id"] == school_id]


def lines_of_spec(spec_id):
    return sort_records([l for l in db.kit_spec_lines.values()
                         if l["grade_kit_spec_id"] == spec_id])


def published_spec(school_id, grade_band):
    for spec in sort_records(list(db.grade_kit_specs.values())):
        if (spec["school_id"] == school_id and spec["grade_band"] == grade_band
                and spec["status"] == "PUBLISHED"):
            return spec
    return None


def spec_lines_for_event(event):
    spec = published_spec(event["school_id"], event["grade_band"])
    if spec is None:
        return None, []
    return spec, lines_of_spec(spec["id"])


def events_of_school(school_id):
    return sort_records([e for e in db.distribution_events.values()
                         if e["school_id"] == school_id])


def events_of_cycle(cycle_id):
    return sort_records([e for e in db.distribution_events.values()
                         if e["drive_cycle_id"] == cycle_id])


def registrations_of_event(event_id):
    return sort_records([r for r in db.student_registrations.values()
                         if r["distribution_event_id"] == event_id])


def registrations_of_school(school_id):
    event_ids = {e["id"] for e in db.distribution_events.values()
                 if e["school_id"] == school_id}
    return [r for r in db.student_registrations.values()
            if r["distribution_event_id"] in event_ids]


def sites_of_cycle(cycle_id):
    return sort_records([s for s in db.collection_sites.values()
                         if s["drive_cycle_id"] == cycle_id])


def batches_of_site(site_id):
    return sort_records([b for b in db.donation_batches.values()
                         if b["collection_site_id"] == site_id])


def batches_of_cycle(cycle_id):
    site_ids = {s["id"] for s in db.collection_sites.values()
                if s["drive_cycle_id"] == cycle_id}
    return sort_records([b for b in db.donation_batches.values()
                         if b["collection_site_id"] in site_ids])


def cycle_of_batch(batch):
    site = db.collection_sites.get(batch["collection_site_id"])
    if site is None:
        return None
    return db.drive_cycles.get(site["drive_cycle_id"])


def positions_of_cycle(cycle_id):
    return sort_records([p for p in db.inventory_positions.values()
                         if p["drive_cycle_id"] == cycle_id])


def orders_of_cycle(cycle_id):
    return sort_records([o for o in db.purchase_orders.values()
                         if o["drive_cycle_id"] == cycle_id])


def donations_of_cycle(cycle_id):
    return sort_records([d for d in db.cash_donations.values()
                         if d["drive_cycle_id"] == cycle_id])


def requests_of_cycle(cycle_id):
    return sort_records([t for t in db.teacher_requests.values()
                         if t["drive_cycle_id"] == cycle_id])


# --------------------------------------------------------------------------
# InventoryPosition
# --------------------------------------------------------------------------
def get_position(cycle_id, item_id, create=False):
    for pos in db.inventory_positions.values():
        if pos["drive_cycle_id"] == cycle_id and pos["supply_item_id"] == item_id:
            return pos
    if not create:
        return None
    rec = base_record()
    rec.update({
        "drive_cycle_id": cycle_id,
        "supply_item_id": item_id,
        "on_hand_qty": 0,
        "reserved_qty": 0,
        "distributed_qty": 0,
        "damaged_qty": 0,
        "accepted_donated_qty": 0,
        "purchased_received_qty": 0,
        "adjustment_qty": 0,
        "in_transit_qty": 0,
    })
    db.inventory_positions[rec["id"]] = rec
    return rec


def compute_in_transit(cycle_id, item_id):
    total = 0
    for order in db.purchase_orders.values():
        if (order["drive_cycle_id"] == cycle_id
                and order["supply_item_id"] == item_id
                and order["status"] in ("SUBMITTED", "APPROVED")):
            total += order["ordered_qty"]
    site_ids = {s["id"] for s in db.collection_sites.values()
                if s["drive_cycle_id"] == cycle_id}
    for batch in db.donation_batches.values():
        if (batch["collection_site_id"] in site_ids
                and batch["supply_item_id"] == item_id
                and batch["status"] in ("RECEIVED", "INSPECTED", "REMEDIATED")):
            total += batch["qty_declared"]
    return total


def refresh_in_transit(cycle_id, item_id, bump=True):
    pos = get_position(cycle_id, item_id, create=True)
    value = compute_in_transit(cycle_id, item_id)
    if pos["in_transit_qty"] != value:
        pos["in_transit_qty"] = value
        if bump:
            touch(pos)
        return True
    return False


# --------------------------------------------------------------------------
# DriveCycle aggregates
# --------------------------------------------------------------------------
def recompute_cycle_inventory(cycle):
    """total_items_on_hand — kept accurate; version bumps are decided by the
    caller because §3 names exactly which transitions bump the cycle."""
    total = sum(p["on_hand_qty"] for p in positions_of_cycle(cycle["id"]))
    changed = cycle["total_items_on_hand"] != total
    cycle["total_items_on_hand"] = total
    return changed


def recompute_cycle_cash(cycle):
    donations = donations_of_cycle(cycle["id"])
    received = sum(d["amount_cents"] for d in donations)
    allocated = sum(d["allocated_cents"] for d in donations)
    unrestricted = sum(d["amount_cents"] for d in donations
                       if d["restriction_type"] == "UNRESTRICTED")
    cycle["cash_received_cents"] = received
    cycle["cash_allocated_cents"] = allocated
    cycle["cash_available_cents"] = received - allocated
    cycle["unrestricted_gross_cents"] = unrestricted
    cycle["supplemental_cap_cents"] = calc.supplemental_cap(unrestricted)


def recompute_donation_status(donation):
    donation["available_cents"] = donation["amount_cents"] - donation["allocated_cents"]
    if donation["allocated_cents"] == 0:
        donation["status"] = "RECEIVED"
    elif donation["allocated_cents"] < donation["amount_cents"]:
        donation["status"] = "PARTIALLY_ALLOCATED"
    else:
        donation["status"] = "FULLY_ALLOCATED"


# --------------------------------------------------------------------------
# CollectionSite aggregate
# --------------------------------------------------------------------------
def recompute_site_accepted(site):
    total = sum(b["qty_accepted"] for b in batches_of_site(site["id"])
                if b["status"] == "ACCEPTED")
    changed = site["accepted_item_count"] != total
    site["accepted_item_count"] = total
    return changed


# --------------------------------------------------------------------------
# GradeKitSpec aggregates
# --------------------------------------------------------------------------
def recompute_spec(spec):
    lines = lines_of_spec(spec["id"])
    spec["line_count"] = len(lines)
    spec["kit_unit_cost_cents"] = calc.kit_unit_cost(lines, db.supply_items)


# --------------------------------------------------------------------------
# DistributionEvent derived fields
# --------------------------------------------------------------------------
def recompute_event_counters(event):
    regs = registrations_of_event(event["id"])
    event["confirmed_count"] = sum(1 for r in regs if r["eligibility_status"] == "CONFIRMED")
    event["waitlist_count"] = sum(1 for r in regs if r["eligibility_status"] == "WAITLISTED")
    event["served_student_count"] = sum(1 for r in regs if r["eligibility_status"] == "FULFILLED")


def provisional_fill(event):
    spec, lines = spec_lines_for_event(event)
    if spec is None:
        return 0.00
    cycle_id = event["drive_cycle_id"]

    def avail(line):
        pos = get_position(cycle_id, line["supply_item_id"])
        if pos is None:
            return 0
        return pos["on_hand_qty"] + pos["in_transit_qty"]

    headcount = sum(1 for r in registrations_of_event(event["id"])
                    if r["eligibility_status"] in
                    ("PENDING", "VERIFIED", "CONFIRMED", "WAITLISTED"))
    return calc.fill_projection(lines, avail, headcount)


def final_fill(event):
    spec, lines = spec_lines_for_event(event)
    if spec is None:
        return 0.00
    cycle_id = event["drive_cycle_id"]

    def avail(line):
        pos = get_position(cycle_id, line["supply_item_id"])
        if pos is None:
            return 0
        return pos["on_hand_qty"]

    headcount = sum(1 for r in registrations_of_event(event["id"])
                    if r["eligibility_status"] in ("VERIFIED", "CONFIRMED"))
    return calc.fill_projection(lines, avail, headcount)


def update_provisional_fill(event, bump=True):
    value = provisional_fill(event)
    if event["provisional_fill_pct"] != value:
        event["provisional_fill_pct"] = value
        if bump:
            touch(event)
        return True
    return False


# --------------------------------------------------------------------------
# School aggregates and the two impact indices
# --------------------------------------------------------------------------
def school_counts(school_id):
    regs = registrations_of_school(school_id)
    interim = sum(1 for r in regs if r["eligibility_status"] in ("CONFIRMED", "FULFILLED"))
    audited = sum(1 for r in regs if r["eligibility_status"] == "FULFILLED")
    no_show = sum(1 for r in regs if r["eligibility_status"] == "NO_SHOW")
    return interim, audited, no_show


def recompute_school(school, bump=True):
    """Recompute every school-level derived field, including both indices."""
    before = (school["target_student_count"], school["students_served_interim_count"],
              school["students_served_audited_count"], school["no_show_count"],
              school["kits_delivered_count"], school["impact_index_interim"],
              school["impact_index_audited"])

    school["target_student_count"] = sum(
        s["student_target_count"] for s in specs_of_school(school["id"])
        if s["status"] == "PUBLISHED")

    interim, audited, no_show = school_counts(school["id"])
    school["students_served_interim_count"] = interim
    school["students_served_audited_count"] = audited
    school["no_show_count"] = no_show
    school["kits_delivered_count"] = audited

    events = events_of_school(school["id"])
    interim_fills = [e["provisional_fill_pct"] for e in events
                     if e["status"] in ("PUBLISHED", "LOCKED", "CLOSED")]
    audited_fills = [e["final_fill_pct"] for e in events if e["status"] == "CLOSED"]

    school["impact_index_interim"] = calc.impact_index(
        interim, school["target_student_count"], interim_fills,
        school["title_i_pct"], 1.0)
    school["impact_index_audited"] = calc.impact_index(
        audited, school["target_student_count"], audited_fills,
        school["title_i_pct"],
        calc.audited_penalty_multiplier(no_show, audited))

    after = (school["target_student_count"], school["students_served_interim_count"],
             school["students_served_audited_count"], school["no_show_count"],
             school["kits_delivered_count"], school["impact_index_interim"],
             school["impact_index_audited"])
    if before != after:
        if bump:
            touch(school)
        return True
    return False


# --------------------------------------------------------------------------
# Reservation legs (unit conservation identity, PRD §2.9)
# --------------------------------------------------------------------------
def reserve_units(reg, event):
    """Forward leg: on_hand -> reserved."""
    spec, lines = spec_lines_for_event(event)
    cycle_id = event["drive_cycle_id"]
    reserved = []
    total = 0
    for line in lines:
        pos = get_position(cycle_id, line["supply_item_id"], create=True)
        pos["on_hand_qty"] -= line["qty_per_student"]
        pos["reserved_qty"] += line["qty_per_student"]
        touch(pos)
        reserved.append({"supply_item_id": line["supply_item_id"],
                         "qty": line["qty_per_student"]})
        total += line["qty_per_student"]
    reg["_reserved_lines"] = reserved
    reg["reserved_unit_count"] = total


def release_units(reg, event):
    """Compensating leg: reserved -> on_hand."""
    cycle_id = event["drive_cycle_id"]
    for entry in reg.get("_reserved_lines") or []:
        pos = get_position(cycle_id, entry["supply_item_id"], create=True)
        pos["reserved_qty"] -= entry["qty"]
        pos["on_hand_qty"] += entry["qty"]
        touch(pos)
    reg["_reserved_lines"] = []
    reg["reserved_unit_count"] = 0


def distribute_units(reg, event):
    """Fulfilment leg: reserved -> distributed."""
    cycle_id = event["drive_cycle_id"]
    for entry in reg.get("_reserved_lines") or []:
        pos = get_position(cycle_id, entry["supply_item_id"], create=True)
        pos["reserved_qty"] -= entry["qty"]
        pos["distributed_qty"] += entry["qty"]
        touch(pos)
    reg["_reserved_lines"] = []
    reg["reserved_unit_count"] = 0


def inventory_covers(event):
    """Every line of the event's published needs list has on_hand >= qty."""
    spec, lines = spec_lines_for_event(event)
    if spec is None:
        return False
    cycle_id = event["drive_cycle_id"]
    for line in lines:
        pos = get_position(cycle_id, line["supply_item_id"])
        on_hand = pos["on_hand_qty"] if pos else 0
        if on_hand < line["qty_per_student"]:
            return False
    return True


# --------------------------------------------------------------------------
# Waitlist promotion sweep (PRD §3.3 hop five)
# --------------------------------------------------------------------------
def waitlist_order(regs):
    return sorted(regs, key=lambda r: (r["verified_at"] or r["created_at"],
                                       r["created_at"], r["_seq"]))


def promotion_sweep(event):
    """Promote WAITLISTED -> CONFIRMED while capacity and coverage both hold."""
    promoted = []
    candidates = waitlist_order([r for r in registrations_of_event(event["id"])
                                 if r["eligibility_status"] == "WAITLISTED"])
    for reg in candidates:
        if event["confirmed_count"] >= event["seat_capacity"]:
            break
        if not inventory_covers(event):
            break
        reg["eligibility_status"] = "CONFIRMED"
        reserve_units(reg, event)
        touch(reg)
        recompute_event_counters(event)
        touch(event)
        promoted.append(reg)
    if promoted:
        school = db.schools.get(event["school_id"])
        if school is not None:
            recompute_school(school)
        cycle = db.drive_cycles.get(event["drive_cycle_id"])
        if cycle is not None:
            recompute_cycle_inventory(cycle)
    return promoted


def events_touching_item(cycle_id, item_id):
    """PUBLISHED events of the cycle whose published needs list has a line for
    this item (PRD §3.3 hop four)."""
    matches = []
    for event in events_of_cycle(cycle_id):
        if event["status"] != "PUBLISHED":
            continue
        spec, lines = spec_lines_for_event(event)
        if spec is None:
            continue
        if any(l["supply_item_id"] == item_id for l in lines):
            matches.append(event)
    return matches


def refresh_events_for_item(cycle_id, item_id, promote=False):
    matches = events_touching_item(cycle_id, item_id)
    for event in matches:
        update_provisional_fill(event)
    if promote:
        for event in matches:
            promotion_sweep(event)
        for event in matches:
            update_provisional_fill(event)
    return matches
