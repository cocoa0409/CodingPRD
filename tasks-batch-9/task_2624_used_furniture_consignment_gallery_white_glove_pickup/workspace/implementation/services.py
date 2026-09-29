"""Derived figures, the ledger, zone occupancy and the shared cascades."""

import calc
import store
from store import db

ON_FLOOR_STATES = ("ON_FLOOR", "MARKED_DOWN")
HELD_INVENTORY = ("IN_CUSTODY", "SHRINKAGE_MISSING")


# ---------------------------------------------------------------------------
# lookups / derived figures
# ---------------------------------------------------------------------------
def agreement_of(item):
    return db.agreements.get(item.get("agreement_id"))


def schedule_of_item(item):
    agreement = agreement_of(item)
    if agreement is None:
        return None
    return db.price_schedules.get(agreement.get("price_schedule_id"))


def steps_of_schedule(schedule_id):
    steps = [s for s in db.price_schedule_steps.values() if s["schedule_id"] == schedule_id]
    steps.sort(key=lambda s: s["sequence"])
    return steps


def steps_of_item(item):
    schedule = schedule_of_item(item)
    if schedule is None:
        return []
    return steps_of_schedule(schedule["id"])


def step_count(schedule_id):
    return len([s for s in db.price_schedule_steps.values() if s["schedule_id"] == schedule_id])


def items_of_agreement(agreement_id):
    return [i for i in db.items.values() if i.get("agreement_id") == agreement_id]


def components_of(item_id):
    rows = [i for i in db.items.values() if i.get("parent_lot_item_id") == item_id]
    return store.by_created_at(rows)


def lot_component_count(item):
    return len(components_of(item["id"]))


def lot_ready(item):
    components = components_of(item["id"])
    if not components:
        return True
    return all(c["inventory_state"] == "IN_CUSTODY" for c in components)


def days_on_floor(item):
    if item.get("listed_at") is None:
        return 0
    return store.whole_days_between(item["listed_at"], store.now())


def unsold_trigger_day_effective(item):
    schedule = schedule_of_item(item)
    if schedule is None:
        return 0
    return int(schedule["unsold_trigger_day"]) + calc.ELECTION_EXTENSION_DAYS * int(
        item.get("election_round") or 0
    )


def items_of_job(job_id):
    return store.by_created_at([i for i in db.items.values() if i.get("pickup_job_id") == job_id])


def job_item_count(job_id):
    return len(items_of_job(job_id))


def job_total_volume(job_id):
    return sum(int(i["volume_cuft"]) for i in items_of_job(job_id))


def items_in_zone(zone_id):
    rows = [
        i
        for i in db.items.values()
        if i.get("placement_zone_id") == zone_id and i["inventory_state"] in HELD_INVENTORY
    ]
    return store.by_created_at(rows)


def zone_occupied_sqft(zone_id):
    return sum(int(i["footprint_sqft"]) for i in items_in_zone(zone_id))


def zone_utilization(zone):
    return calc.utilization_state(zone_occupied_sqft(zone["id"]), int(zone["capacity_sqft"]))


def zone_remaining_sqft(zone):
    return int(zone["capacity_sqft"]) - zone_occupied_sqft(zone["id"])


# ---------------------------------------------------------------------------
# ledger
# ---------------------------------------------------------------------------
def ledger_of_consignor(consignor_id):
    rows = [e for e in db.ledger_entries.values() if e["consignor_id"] == consignor_id]
    rows.sort(key=lambda e: (e["effective_at"], e["_seq"]))
    return rows


def ledger_of_item(item_id):
    rows = [e for e in db.ledger_entries.values() if e.get("item_id") == item_id]
    rows.sort(key=lambda e: (e["effective_at"], e["_seq"]))
    return rows


def unclaimed_balance_cents(consignor_id):
    return sum(int(e["amount_cents"]) for e in ledger_of_consignor(consignor_id))


def lifetime_credits_cents(consignor_id):
    return sum(int(e["amount_cents"]) for e in ledger_of_consignor(consignor_id) if int(e["amount_cents"]) > 0)


def mint_entry(
    consignor,
    entry_type,
    amount_cents,
    memo,
    item_id=None,
    withholding_cents=None,
    processing_fee_cents=None,
    net_payout_cents=None,
    bump_version=True,
):
    """Append one PayoutLedgerEntry and run the consignor-level cascade."""
    entry = store.new_row(
        db.ledger_entries,
        {
            "consignor_id": consignor["id"],
            "item_id": item_id,
            "entry_type": entry_type,
            "amount_cents": int(amount_cents),
            "withholding_cents": withholding_cents,
            "processing_fee_cents": processing_fee_cents,
            "net_payout_cents": net_payout_cents,
            "balance_after_cents": 0,
            "memo": memo,
            "effective_at": store.now(),
        },
        versioned=False,
    )
    balance = unclaimed_balance_cents(consignor["id"])
    entry["balance_after_cents"] = balance

    # PRD 2.11: the suspension posture follows the recomputed balance.
    if balance < calc.SUSPEND_BELOW_CENTS:
        consignor["status"] = "SUSPENDED"
    elif balance >= 0 and consignor["status"] == "SUSPENDED":
        consignor["status"] = "ACTIVE"

    # An ESCHEATMENT_DEBIT deliberately does not refresh the dormancy origin.
    if entry_type != "ESCHEATMENT_DEBIT":
        consignor["last_activity_at"] = store.now()
        if consignor["escheat_state"] == "DORMANT":
            consignor["escheat_state"] = "NONE"

    if bump_version:
        store.touch(consignor)
    return entry


def consignor_of_item(item):
    return db.consignors.get(item.get("consignor_id"))


# ---------------------------------------------------------------------------
# pricing cascades
# ---------------------------------------------------------------------------
def discount_elected(item):
    return item.get("disposition_election") == "DISCOUNT"


def recompute_current_price(item):
    """calculations.markdown_price against the item's own tenure. Returns True on change."""
    if item.get("list_price_cents") is None:
        return False
    steps = steps_of_item(item)
    step = calc.governing_step(steps, days_on_floor(item))
    if step is None:
        return False
    sequence, current = calc.markdown_price(
        item["list_price_cents"], step, discount_elected(item)
    )
    changed = False
    if item.get("markdown_sequence") != sequence:
        item["markdown_sequence"] = sequence
        changed = True
    if item.get("current_price_cents") != current:
        item["current_price_cents"] = current
        changed = True
    return changed


def clearance_relocation(item):
    """calculations.clearance_relocation_selector. Returns True on any change."""
    current = item.get("current_price_cents")
    zone_id = item.get("placement_zone_id")
    if current is None or zone_id is None:
        return False
    zone = db.zones.get(zone_id)
    if zone is None or zone["zone_type"] == "CLEARANCE":
        return False
    if current >= calc.CLEARANCE_THRESHOLD_CENTS:
        return False

    footprint = int(item["footprint_sqft"])
    eligible = [
        z
        for z in db.zones.values()
        if z["zone_type"] == "CLEARANCE"
        and z["status"] == "OPEN"
        and zone_remaining_sqft(z) >= footprint
    ]
    if not eligible:
        changed = item.get("clearance_relocation_pending") is not True
        item["clearance_relocation_pending"] = True
        return changed
    eligible.sort(key=lambda z: (-zone_remaining_sqft(z), z["created_at"], z["_seq"]))
    winner = eligible[0]
    item["placement_zone_id"] = winner["id"]
    item["clearance_relocation_pending"] = False
    return True


def price_lot_parent(parent):
    """Bundle price plus the grade roll-up. Returns True on change."""
    components = components_of(parent["id"])
    live = [c for c in components if c["lifecycle_state"] != "SCREEN_REJECTED"]
    bundle = calc.lot_bundle_list_price([c.get("list_price_cents") or 0 for c in live])
    grade = calc.worst_grade([c.get("condition_grade") for c in live])
    changed = False
    if parent.get("list_price_cents") != bundle:
        parent["list_price_cents"] = bundle
        changed = True
    if grade is not None and parent.get("condition_grade") != grade:
        parent["condition_grade"] = grade
        changed = True
    return changed


def cascade_lot_parent(component):
    """PRD 3.5 links 2-5: reprice the parent, re-step it, relocate it if cheap."""
    parent_id = component.get("parent_lot_item_id")
    if not parent_id:
        return
    parent = db.items.get(parent_id)
    if parent is None:
        return
    changed = price_lot_parent(parent)
    if parent["lifecycle_state"] in ON_FLOOR_STATES:
        if recompute_current_price(parent):
            changed = True
        if clearance_relocation(parent):
            changed = True
    if changed:
        store.touch(parent)


def release_placement(item):
    item["placement_zone_id"] = None
