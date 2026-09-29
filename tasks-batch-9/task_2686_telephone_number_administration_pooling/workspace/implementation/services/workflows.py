"""Shared cascades: reclamation orders, routing publication, the sweep."""

from db import base_record, by_created, db, days, light_record, now, touch
from services import constants as C
from services import calc, core


# --------------------------------------------------------------------------
# reclamation orders
# --------------------------------------------------------------------------

def create_reclamation_order(block, carrier_id, reason, issued_at):
    record = base_record(
        number_block_id=block["id"],
        carrier_id=carrier_id,
        reason=reason,
        status="ISSUED",
        issued_at=issued_at,
        response_due_at=issued_at + days(C.RECLAMATION_RESPONSE_DAYS),
        executed_at=None,
        appeal_note=None,
        strike_applied=False,
    )
    db.orders[record["id"]] = record
    return record


# --------------------------------------------------------------------------
# routing ledger
# --------------------------------------------------------------------------

def supersede_open_record(block, end_at):
    record = core.open_routing_record(block["id"])
    if record is not None:
        record["end_at"] = end_at
        record["record_status"] = "SUPERSEDED"
    return record


def publish_routing_record(block, lrn, switch_clli, effective_at, ocn):
    block["npac_db_version"] = block["npac_db_version"] + 1
    record = light_record(
        number_block_id=block["id"],
        lrn=lrn,
        ocn=ocn,
        switch_clli=switch_clli,
        effective_at=effective_at,
        end_at=None,
        record_status="PUBLISHED",
        npac_db_version=block["npac_db_version"],
    )
    db.routing_records[record["id"]] = record
    return record


def withdraw_routing(block):
    """Reclamation execution tears live routing down (PRD 3.7)."""
    if block["routing_status"] not in ("LERG_PUBLISHED", "PORT_LOCKED"):
        return False
    record = core.open_routing_record(block["id"])
    if record is not None:
        record["end_at"] = now()
        record["record_status"] = "WITHDRAWN"
    block["routing_status"] = "ROUTING_WITHDRAWN"
    block["current_lrn"] = None
    block["npac_db_version"] = block["npac_db_version"] + 1
    return True


# --------------------------------------------------------------------------
# holder release helpers
# --------------------------------------------------------------------------

def clear_holder_stamps(block):
    block["holder_carrier_id"] = None
    block["assigned_at"] = None
    block["activation_due_at"] = None
    block["activated_at"] = None


# --------------------------------------------------------------------------
# the reclamation sweep (PRD 3.7)
# --------------------------------------------------------------------------

def run_sweep(rate_center_id=None, reason_filter=None):
    swept_at = now()
    orders_issued = 0
    blocks_released = 0
    routing_activated = 0

    def in_scope(block):
        if rate_center_id is None:
            return True
        return block["rate_center_id"] == rate_center_id

    blocks = [b for b in by_created(db.blocks.values()) if in_scope(b)]

    # pass one - issue reclamation orders
    for block in blocks:
        reason = None
        if (
            block["allocation_status"] == "RESERVED"
            and block["activated_at"] is None
            and block["activation_due_at"] is not None
            and block["activation_due_at"] < swept_at
        ):
            reason = "ACTIVATION_DEADLINE_MISSED"
        elif block["allocation_status"] == "ASSIGNED":
            holder = block.get("holder_carrier_id")
            filing = (
                core.sweep_effective_filing(holder, block["rate_center_id"])
                if holder
                else None
            )
            if filing is None:
                reason = "UTILIZATION_SHORTFALL"
            else:
                strict = filing["strict_utilization_pct"]
                if strict is None or float(strict) < float(C.UTILIZATION_MIN_PCT_GROWTH):
                    reason = "UTILIZATION_SHORTFALL"
        if reason is None:
            continue
        if reason_filter is not None and reason != reason_filter:
            continue
        holder = block.get("holder_carrier_id")
        block["allocation_status"] = "RECLAMATION_PENDING"
        touch(block)
        create_reclamation_order(block, holder, reason, swept_at)
        orders_issued += 1

    # pass two - release aged inventory
    for block in blocks:
        if block["allocation_status"] != "AGING":
            continue
        if block["aging_release_at"] is None or block["aging_release_at"] > swept_at:
            continue
        block["allocation_status"] = "POOL_AVAILABLE"
        block["aging_release_at"] = None
        touch(block)
        blocks_released += 1
        rate_center = db.rate_centers.get(block["rate_center_id"])
        if rate_center is not None:
            touch(rate_center)
        npa = db.npas.get(block["npa_id"])
        if npa is not None:
            if not core.recompute_npa_posture(npa):
                touch(npa)

    # pass three - promote future-dated routing
    for block in blocks:
        if block["routing_status"] != "ROUTING_PENDING":
            continue
        record = core.open_routing_record(block["id"])
        if record is None or record["effective_at"] > swept_at:
            continue
        block["routing_status"] = "LERG_PUBLISHED"
        block["current_lrn"] = record["lrn"]
        touch(block)
        routing_activated += 1

    return {
        "orders_issued": orders_issued,
        "blocks_released": blocks_released,
        "routing_activated": routing_activated,
        "swept_at": swept_at,
    }


# --------------------------------------------------------------------------
# pooling completion (PRD 3.6)
# --------------------------------------------------------------------------

def complete_pooling_donations(rate_center):
    holders = []
    for block in core.blocks_of_rate_center(rate_center["id"]):
        holder = block.get("holder_carrier_id")
        if holder and block["allocation_status"] in ("RESERVED", "ASSIGNED"):
            if holder not in holders:
                holders.append(holder)
    carriers = [db.carriers[h] for h in holders if h in db.carriers]
    carriers.sort(key=lambda c: (c["created_at"], c["_seq"]))

    donated_total = 0
    shortfall_total = 0
    for carrier in carriers:
        blocks_held = len(
            [
                b
                for b in core.blocks_of_rate_center(rate_center["id"])
                if b.get("holder_carrier_id") == carrier["id"]
                and b["allocation_status"] in ("RESERVED", "ASSIGNED")
            ]
        )
        utilization = core.effective_utilization(carrier["id"], rate_center["id"])
        obligation = calc.donation_obligation(blocks_held, utilization)
        candidates = calc.donation_candidates(carrier["id"], rate_center["id"])
        donated = candidates[:obligation]
        for block in donated:
            block["allocation_status"] = "POOL_AVAILABLE"
            clear_holder_stamps(block)
            touch(block)
        if donated:
            touch(carrier)
        donated_total += len(donated)
        shortfall_total += obligation - len(donated)

    rate_center["last_donation_block_count"] = donated_total
    rate_center["donation_shortfall_count"] = shortfall_total
    if donated_total:
        npa = db.npas.get(rate_center["npa_id"])
        if npa is not None:
            if not core.recompute_npa_posture(npa):
                touch(npa)
    return donated_total, shortfall_total
