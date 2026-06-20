"""Shared case-level compensating operations reused by direct endpoints and
cascades (PRD §3.4 block release, §3.10 cancel)."""
from db import db, touch
from services.calculations import estimated_case_cost, recompute_day


def case_implants(case_id):
    return [ci for ci in db.case_implants.values() if ci["surgical_case_id"] == case_id]


def release_reserved_implant(implant):
    """RESERVED -> RELEASED; decrement SupplyItem.reserved_qty by planned_qty."""
    implant["status"] = "RELEASED"
    supply = db.supply_items[implant["supply_item_id"]]
    supply["reserved_qty"] -= implant["planned_qty"]
    touch(supply)
    touch(implant)


def recompute_estimate_if_scheduled(case):
    if case["case_status"] == "SCHEDULED":
        procedure = db.procedures[case["procedure_id"]]
        case["estimated_cost_cents"] = estimated_case_cost(case, procedure)


def cancel_case_effects(case):
    """Compensating effects for cancelling a SCHEDULED case (PRD §3.10).

    Subtracts scheduled_minutes from block.committed_minutes, releases RESERVED
    implants, and recomputes the owning day. Sets case_status to CANCELLED.
    Caller is responsible for state precondition checks.
    """
    case["case_status"] = "CANCELLED"
    block = db.surgeon_blocks[case["surgeon_block_id"]]
    block["committed_minutes"] -= case["scheduled_minutes"]
    touch(block)
    for ci in case_implants(case["id"]):
        if ci["status"] == "RESERVED":
            release_reserved_implant(ci)
    touch(case)
    day = db.surgical_days[case["surgical_day_id"]]
    recompute_day(day)
    touch(day)
