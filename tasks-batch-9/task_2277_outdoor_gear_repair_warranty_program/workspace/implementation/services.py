"""Derived-field recomputation, cascades and serialisation.

Every function here mutates rows in place through ``set_fields``/``touch`` so
that each hop of a cascade is a real mutation: ``updated_at`` refreshed and
``version`` incremented exactly once per affected row per request.
"""

from datetime import timedelta
from decimal import Decimal

import calc
from core import db, dt_of, fail, iso, new_row, now, ordered, set_fields

# --------------------------------------------------------------------------- #
# Lookups
# --------------------------------------------------------------------------- #

def model_of_item(item):
    return db.gear_models.get(item["gear_model_id"])


def item_of_claim(claim):
    return db.gear_items.get(claim["gear_item_id"])


def center_of(row):
    return db.service_centers.get(row.get("service_center_id"))


def claim_of_order(order):
    return db.warranty_claims.get(order["warranty_claim_id"])


def owner_of_item(item):
    return db.customers.get(item["owner_customer_id"])


def live_assessment(claim):
    """Newest non-superseded assessment on the claim."""
    rows = [
        a for a in ordered(db.claim_assessments)
        if a["warranty_claim_id"] == claim["id"] and not a["is_superseded"]
    ]
    return rows[-1] if rows else None


def cert_level(technician, work_type):
    for entry in technician.get("certifications") or []:
        if entry.get("work_type") == work_type:
            return entry.get("level")
    return None


def order_reservations(order_id):
    return [r for r in ordered(db.parts_reservations) if r["repair_order_id"] == order_id]


def order_blocks(order_id):
    return [b for b in ordered(db.work_blocks) if b["repair_order_id"] == order_id]


def claim_liability_entries(claim_id):
    return [e for e in ordered(db.liability_entries) if e["warranty_claim_id"] == claim_id]


# --------------------------------------------------------------------------- #
# Gear unit derived fields (PRD Sec. 2.8)
# --------------------------------------------------------------------------- #

def item_derived(item):
    model = model_of_item(item)
    purchase_dt = dt_of(item["purchase_date"])
    months = calc.age_months(purchase_dt, now())
    years = calc.completed_years(months)
    depreciated = calc.replacement_value_depreciated(
        item["purchase_price_cents"], model["msrp_cents"], years
    )
    base_msrp = model["msrp_cents"]
    if model.get("discontinued_at") and model.get("successor_model_id"):
        successor = db.gear_models.get(model["successor_model_id"])
        if successor is not None:
            base_msrp = successor["msrp_cents"]
    return {
        "age_months": months,
        "warranty_state": calc.warranty_state(model, purchase_dt, now()),
        "replacement_value_depreciated_cents": depreciated,
        "replacement_value_successor_cents": calc.replacement_value_successor(base_msrp),
    }


def refresh_item(item):
    """Recompute the clock-dependent surface without counting as a mutation."""
    item.update(item_derived(item))
    return item


def rewrite_item_derived(item):
    """Recompute as part of a mutation (audit fields move when values change)."""
    return set_fields(item, **item_derived(item))


def item_warranty_state(item):
    return item_derived(item)["warranty_state"]


# --------------------------------------------------------------------------- #
# Catalogue model derived fields (PRD Sec. 2.10 / 3.5)
# --------------------------------------------------------------------------- #

def recompute_model_support(model):
    if model is None:
        return
    own = [l for l in db.part_lots.values() if l["gear_model_id"] == model["id"]]
    if any(l["status"] in ("AVAILABLE", "LOW") for l in own):
        status = "SUPPORTED"
    else:
        status = "NO_SUPPORT"
        successor_id = model.get("successor_model_id")
        if successor_id:
            for lot in db.part_lots.values():
                if (
                    lot["gear_model_id"] == successor_id
                    and lot["substitution_allowed"]
                    and lot["substitute_for_part_code"] is not None
                    and lot["status"] in ("AVAILABLE", "LOW")
                ):
                    status = "SUBSTITUTION_ONLY"
                    break
    set_fields(model, parts_support_status=status)


def recompute_support_for_lot(lot):
    """The lot's own model plus every model that names this model as successor."""
    recompute_model_support(db.gear_models.get(lot["gear_model_id"]))
    for model in ordered(db.gear_models):
        if model.get("successor_model_id") == lot["gear_model_id"]:
            recompute_model_support(model)


def recompute_lot(lot):
    available = lot["on_hand_units"] - lot["reserved_units"]
    set_fields(
        lot,
        available_units=available,
        status=calc.lot_status(available, lot["low_watermark_units"]),
    )
    recompute_support_for_lot(lot)


def bump_model_counter(model, field, amount=1):
    updated = {field: model[field] + amount}
    defect = updated.get("defect_claim_count", model["defect_claim_count"])
    irreparable = updated.get("irreparable_count", model["irreparable_count"])
    updated["repairability_flag"] = calc.repairability_flag(defect, irreparable)
    set_fields(model, **updated)


# --------------------------------------------------------------------------- #
# Service centre derived fields (PRD Sec. 2.9 / 3.6)
# --------------------------------------------------------------------------- #

def open_liability_of(center):
    total = 0
    for entry in db.liability_entries.values():
        if entry["status"] != "OPEN":
            continue
        claim = db.warranty_claims.get(entry["warranty_claim_id"])
        if claim is not None and claim["service_center_id"] == center["id"]:
            total += entry["reserved_amount_cents"]
    return total


def liability_fields(center):
    open_cents = open_liability_of(center)
    cap = center["liability_cap_cents"]
    return {
        "open_liability_cents": open_cents,
        "liability_utilization_pct": calc.utilization_pct(open_cents, cap),
        "liability_posture": calc.posture(open_cents, cap),
    }


def recompute_center_liability(center):
    if center is not None:
        set_fields(center, **liability_fields(center))


def queue_depth_of(center, exclude_order_id=None):
    count = 0
    for order in db.repair_orders.values():
        if order["service_center_id"] != center["id"]:
            continue
        if exclude_order_id is not None and order["id"] == exclude_order_id:
            continue
        if order["work_status"] in calc.QUEUE_STATES:
            count += 1
    return count


def window_multiplier(center):
    """Largest multiplier among ACTIVE windows covering the clock, else 1.00."""
    clock = now()
    best = Decimal("1.00")
    for window in db.surge_windows.values():
        if window["service_center_id"] != center["id"] or window["status"] != "ACTIVE":
            continue
        start = dt_of(window["start_date"])
        end = dt_of(window["end_date"])
        if start is None or end is None:
            continue
        if start <= clock <= end:
            value = Decimal(str(window["multiplier"]))
            if value > best:
                best = value
    return best


def surge_multiplier_for(center, queue_depth):
    tier = calc.tier_multiplier(queue_depth)
    window = window_multiplier(center)
    return tier if tier > window else window


def queue_fields(center):
    depth = queue_depth_of(center)
    return {
        "active_queue_depth": depth,
        "current_surge_multiplier": float(surge_multiplier_for(center, depth)),
    }


def recompute_center_queue(center):
    if center is not None:
        set_fields(center, **queue_fields(center))


# --------------------------------------------------------------------------- #
# Inventory / bench give-back chains (PRD Sec. 3.8)
# --------------------------------------------------------------------------- #

def release_reservation(reservation, reason=None):
    lot = db.part_lots.get(reservation["part_lot_id"])
    set_fields(
        reservation,
        status="RELEASED",
        settled_at=iso(now()),
    )
    if lot is not None:
        set_fields(lot, reserved_units=lot["reserved_units"] - reservation["units"])
        recompute_lot(lot)


def consume_reservation(reservation):
    lot = db.part_lots.get(reservation["part_lot_id"])
    set_fields(reservation, status="CONSUMED", settled_at=iso(now()))
    if lot is not None:
        set_fields(
            lot,
            on_hand_units=lot["on_hand_units"] - reservation["units"],
            reserved_units=lot["reserved_units"] - reservation["units"],
        )
        recompute_lot(lot)


def release_order_reservations(order):
    for reservation in order_reservations(order["id"]):
        if reservation["status"] == "RESERVED":
            release_reservation(reservation)


def cancel_block(block):
    technician = db.technicians.get(block["technician_id"])
    set_fields(block, status="CANCELLED")
    if technician is not None:
        set_fields(
            technician,
            scheduled_minutes_open=technician["scheduled_minutes_open"] - block["duration_minutes"],
        )


def cancel_order_blocks(order):
    for block in order_blocks(order["id"]):
        if block["status"] == "SCHEDULED":
            cancel_block(block)


# --------------------------------------------------------------------------- #
# Liability entries
# --------------------------------------------------------------------------- #

def open_liability_entry(claim, basis, variant, amount):
    row = new_row()
    row.update({
        "warranty_claim_id": claim["id"],
        "basis": basis,
        "valuation_variant": variant,
        "reserved_amount_cents": amount,
        "status": "OPEN",
        "release_reason": None,
        "released_at": None,
    })
    db.liability_entries[row["id"]] = row
    return row


def release_claim_liability(claim, reason, basis=None):
    released = False
    for entry in claim_liability_entries(claim["id"]):
        if entry["status"] != "OPEN":
            continue
        if basis is not None and entry["basis"] != basis:
            continue
        set_fields(
            entry,
            status="RELEASED",
            release_reason=reason,
            released_at=iso(now()),
        )
        released = True
    return released


# --------------------------------------------------------------------------- #
# Condemnation cascade (PRD Sec. 3.9)
# --------------------------------------------------------------------------- #

def condemn_order(order):
    claim = claim_of_order(order)
    item = db.gear_items.get(order["gear_item_id"])
    center = center_of(order)

    set_fields(order, work_status="IRREPARABLE")

    # parts give-back, then bench give-back
    release_order_reservations(order)
    cancel_order_blocks(order)

    # liability revaluation on a warranty order
    if order["order_kind"] == "WARRANTY_REPAIR" and claim is not None:
        release_claim_liability(claim, "REVALUED_TO_REPLACEMENT", basis="REPAIR")
        refresh_item(item)
        open_liability_entry(
            claim, "REPLACEMENT", "SUCCESSOR_MSRP",
            item["replacement_value_successor_cents"],
        )
        recompute_center_liability(center)

    if item is not None:
        set_fields(item, disposition_status="IRREPARABLE_HOLD")
        model = model_of_item(item)
        if model is not None:
            bump_model_counter(model, "irreparable_count")

    # The order has left QUEUED/IN_WORK/BENCH_DONE, so the centre's queue
    # surface no longer counts it (PRD Sec. 3.6 definition of active_queue_depth).
    recompute_center_queue(center)


def decline_cascade(estimate, order):
    claim = claim_of_order(order)
    item = db.gear_items.get(order["gear_item_id"])

    updates = {"billing_status": "ESTIMATE_DECLINED"}
    if order["work_status"] in ("QUEUED", "IN_WORK"):
        updates["work_status"] = "CLOSED_UNREPAIRED"
    set_fields(order, **updates)

    release_order_reservations(order)
    cancel_order_blocks(order)

    if item is not None and item["disposition_status"] == "IN_REPAIR":
        set_fields(item, disposition_status="RETURNED")
    if claim is not None and claim["status"] == "PAID_REPAIR_OFFERED":
        set_fields(claim, status="CLOSED_DECLINED")

    # The order has left QUEUED/IN_WORK/BENCH_DONE, so the centre's queue
    # surface no longer counts it (PRD Sec. 3.6 definition of active_queue_depth).
    recompute_center_queue(center_of(order))


# --------------------------------------------------------------------------- #
# Technician routing selector (PRD Sec. 3.8)
# --------------------------------------------------------------------------- #

def blocks_overlap(existing, start_dt, end_dt):
    other_start = dt_of(existing["start_at"])
    other_end = dt_of(existing["end_at"])
    return other_start < end_dt and start_dt < other_end


def technician_conflict(technician_id, start_dt, end_dt):
    for block in db.work_blocks.values():
        if block["technician_id"] != technician_id or block["status"] != "SCHEDULED":
            continue
        if blocks_overlap(block, start_dt, end_dt):
            return True
    return False


def route_technician(center_id, work_type, start_dt, end_dt):
    minimum = calc.WORK_TYPE_MIN_LEVEL[work_type]
    pool = []
    for technician in ordered(db.technicians):
        if technician["service_center_id"] != center_id:
            continue
        if technician["status"] != "ACTIVE":
            continue
        level = cert_level(technician, work_type)
        if level is None or level < minimum:
            continue
        if technician_conflict(technician["id"], start_dt, end_dt):
            continue
        pool.append((technician, level))
    if not pool:
        return None
    pool.sort(key=lambda pair: (
        -pair[1],
        pair[0]["scheduled_minutes_open"],
        pair[0]["created_at"],
        pair[0]["_seq"],
    ))
    return pool[0][0]


def scheduled_blocks_on_date(center_id, day):
    count = 0
    for block in db.work_blocks.values():
        if block["status"] != "SCHEDULED":
            continue
        order = db.repair_orders.get(block["repair_order_id"])
        if order is None or order["service_center_id"] != center_id:
            continue
        start = dt_of(block["start_at"])
        if start is not None and start.date() == day:
            count += 1
    return count


# --------------------------------------------------------------------------- #
# Pricing helpers
# --------------------------------------------------------------------------- #

def final_lines(order):
    labor_groups = {}
    for block in order_blocks(order["id"]):
        if block["status"] != "COMPLETED":
            continue
        minutes = block.get("actual_minutes") or 0
        labor_groups[block["work_type"]] = labor_groups.get(block["work_type"], 0) + minutes
    labor_lines = [
        {"work_type": work_type, "minutes": labor_groups[work_type]}
        for work_type in sorted(labor_groups)
    ]
    parts_lines = []
    for reservation in order_reservations(order["id"]):
        if reservation["status"] != "CONSUMED":
            continue
        lot = db.part_lots.get(reservation["part_lot_id"])
        if lot is None:
            continue
        parts_lines.append({
            "part_code": lot["part_code"],
            "units": reservation["units"],
            "unit_price_cents": lot["unit_price_cents"],
        })
    return labor_lines, parts_lines


def loyalty_tier_for_order(order):
    item = db.gear_items.get(order["gear_item_id"])
    owner = owner_of_item(item) if item is not None else None
    return owner["loyalty_tier"] if owner is not None else "STANDARD"


def new_estimate(order, variant, status, labor_lines, parts_lines):
    components = calc.price(
        labor_lines, parts_lines, loyalty_tier_for_order(order), variant,
        order["expedite_requested"],
    )
    row = new_row()
    row.update({
        "repair_order_id": order["id"],
        "variant": variant,
        "status": status,
        "labor_lines": labor_lines,
        "parts_lines": parts_lines,
        "valid_until": iso(now() + timedelta(days=calc.ESTIMATE_VALIDITY_DAYS)),
        "decided_at": None,
    })
    row.update(components)
    db.repair_estimates[row["id"]] = row
    return row


# --------------------------------------------------------------------------- #
# Claim helpers
# --------------------------------------------------------------------------- #

def proof_verified(item):
    return bool(
        item["proof_of_purchase_type"] != "NONE" and item["proof_of_purchase_ref"] is not None
    )


def order_of_claim(claim, non_terminal_only=False):
    rows = [o for o in ordered(db.repair_orders) if o["warranty_claim_id"] == claim["id"]]
    if non_terminal_only:
        rows = [o for o in rows if o["work_status"] not in calc.ORDER_WORK_TERMINAL]
    return rows[-1] if rows else None


def driving_claim_for_item(item):
    """The claim that condemned the unit (newest still-open warranty claim)."""
    rows = [
        c for c in ordered(db.warranty_claims)
        if c["gear_item_id"] == item["id"]
        and c["status"] in ("WARRANTY_APPROVED", "REPLACEMENT_AUTHORIZED")
    ]
    return rows[-1] if rows else None


# --------------------------------------------------------------------------- #
# Ownership (check 5)
# --------------------------------------------------------------------------- #

def item_behind_claim(claim):
    return db.gear_items.get(claim["gear_item_id"])


def item_behind_order(order):
    return db.gear_items.get(order["gear_item_id"])


def item_behind_estimate(estimate):
    order = db.repair_orders.get(estimate["repair_order_id"])
    return db.gear_items.get(order["gear_item_id"]) if order is not None else None


def guard_owner(ctx, item):
    if not ctx.is_customer:
        return
    if item is None or item["owner_customer_id"] != ctx.user_id:
        fail("ERR_NOT_RESOURCE_OWNER")


# --------------------------------------------------------------------------- #
# Serialisation
# --------------------------------------------------------------------------- #

def public(row):
    return {key: value for key, value in row.items() if not key.startswith("_")}


def ser_item(item):
    refresh_item(item)
    return public(item)


def ser_items(items):
    return [ser_item(i) for i in items]


def ser(row):
    return public(row)


def ser_all(rows):
    return [public(r) for r in rows]


# --------------------------------------------------------------------------- #
# Path / body reference resolution (checks 6-8)
# --------------------------------------------------------------------------- #

def need(collection, key, error_id):
    row = collection.get(key) if isinstance(key, str) else None
    if row is None:
        fail(error_id)
    return row


def fk(body, key, collection, error_id):
    """Check 7/8 -- a supplied body reference must resolve."""
    if key not in body or body[key] is None:
        return None
    return need(collection, body[key], error_id)


def claim_assessments_of(claim_id):
    return [a for a in ordered(db.claim_assessments) if a["warranty_claim_id"] == claim_id]


def order_estimates(order_id):
    return [e for e in ordered(db.repair_estimates) if e["repair_order_id"] == order_id]
