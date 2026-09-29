"""Spare-part sourcing, the allowance waterfall and the obsolescence cascade."""
import db
from services import calc, credit, domain

SOURCE_BUCKET = {
    "NEW": "on_hand_qty",
    "REFURBISHED": "refurb_on_hand_qty",
    "LOANER_SWAP": "refurb_on_hand_qty",
}


def source_bucket(source):
    """Both refurbished and loaner sourcing draw on the refurbished bucket."""
    return SOURCE_BUCKET[source]


def is_covered(parts_inclusion, part_category):
    """FULL covers everything; WEAR_ONLY covers exactly the WEAR category."""
    if parts_inclusion == "FULL":
        return True
    if parts_inclusion == "WEAR_ONLY" and part_category == "WEAR":
        return True
    return False


def allocate(call, contract, part, qty, source):
    """Price the order per unit, run the waterfall and move the stock."""
    # The per-unit figure is rounded to whole cents BEFORE the multiplication.
    unit_cents = calc.rhu_int(
        calc.dec(part["unit_price_cents"]) * calc.SOURCE_PRICE_FACTOR[source]
    )
    list_total_cents = unit_cents * qty
    covered_cents = list_total_cents if is_covered(
        contract["parts_inclusion"], part["category"]
    ) else 0
    remaining = contract["parts_allowance_remaining_cents"]
    allowance_draw_cents = covered_cents if covered_cents < remaining else remaining
    if allowance_draw_cents < 0:
        allowance_draw_cents = 0
    club_billable_cents = list_total_cents - allowance_draw_cents

    row = db.base_row()
    row.update({
        "service_call_id": call["id"],
        "part_id": part["id"],
        "qty": qty,
        "source": source,
        "list_total_cents": list_total_cents,
        "covered_cents": covered_cents,
        "allowance_draw_cents": allowance_draw_cents,
        "club_billable_cents": club_billable_cents,
        "status": "ALLOCATED",
        "installed_at": None,
        "cancellation_reason": None,
    })
    db.part_orders[row["id"]] = row

    db.apply_changes(contract, {
        "parts_allowance_remaining_cents": remaining - allowance_draw_cents
    })
    bucket = source_bucket(source)
    db.apply_changes(part, {
        bucket: part[bucket] - qty,
        "allocated_qty": part["allocated_qty"] + qty,
    })
    return row


def install(order):
    """The unit is physically consumed: allocated falls, no bucket restore."""
    installed_at = db.now()
    db.apply_changes(order, {
        "status": "INSTALLED",
        "installed_at": db.iso(installed_at),
    })
    part = db.parts.get(order["part_id"])
    if part is not None:
        db.apply_changes(part, {
            "allocated_qty": part["allocated_qty"] - order["qty"]
        })
    if order["source"] == "LOANER_SWAP":
        call = db.calls.get(order["service_call_id"])
        if call is not None:
            equipment_row = db.equipment.get(call["equipment_id"])
            if equipment_row is not None:
                db.apply_changes(equipment_row, {"loaner_active": True})
            event = credit.event_for_call(call["id"], statuses=("OPEN",))
            if event is not None:
                # Both credit variants are capped at the instant the loaner went in.
                db.apply_changes(event, {"mitigated_at": db.iso(installed_at)})
    return order


def cancel(order, reason):
    """A true compensation: the money returns before the record of it is erased."""
    call = db.calls.get(order["service_call_id"])
    contract = db.contracts.get(call["contract_id"]) if call else None
    if contract is not None:
        db.apply_changes(contract, {
            "parts_allowance_remaining_cents":
                contract["parts_allowance_remaining_cents"] + order["allowance_draw_cents"]
        })
    db.apply_changes(order, {
        "status": "CANCELLED",
        "cancellation_reason": reason,
        "allowance_draw_cents": 0,
        "club_billable_cents": 0,
    })
    part = db.parts.get(order["part_id"])
    if part is not None:
        # The very bucket that was debited is the one restored.
        bucket = source_bucket(order["source"])
        db.apply_changes(part, {
            bucket: part[bucket] + order["qty"],
            "allocated_qty": part["allocated_qty"] - order["qty"],
        })
    return order


def obsolescence_cascade(part, lifecycle_status):
    """Only a critical spare reaches outside its own row."""
    if not part["is_critical_spare"]:
        return
    support_status = ("UNSUPPORTED" if lifecycle_status == "OBSOLETE"
                     else "END_OF_SUPPORT_ANNOUNCED")
    notified_at = db.now_iso()
    club_ids = []
    for unit in db.ordered(db.equipment, lambda e: e["model_id"] == part["model_id"]):
        # Hop one stamps the notification; hops three and four re-derive the
        # condition triple, which is where the relaxed 60.00 threshold bites.
        domain.refresh_equipment_condition(unit, {
            "support_status": support_status,
            "eos_notified_at": notified_at,
        })
        if unit["club_id"] not in club_ids:
            club_ids.append(unit["club_id"])
    # Hop three: obsolete_unit_count, replacement_candidate_count, then the risk.
    for club_id in club_ids:
        domain.recompute_contract_fleet(club_id)
