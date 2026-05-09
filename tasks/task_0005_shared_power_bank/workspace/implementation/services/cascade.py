"""Anomaly cascade chain (PRD §2.8) and ticket-driven side effects."""
from db import db, make_common_fields, bump
from clock import clock
from services.priority import compute_priority_score


def create_repair_ticket(*, target_type: str, target_id: str, source: str, issue_code: str) -> dict:
    """Create a RepairTicket and run the §2.8 cascade if applicable."""
    cf = make_common_fields()
    ticket = {
        **cf,
        "target_type": target_type,
        "target_id": target_id,
        "source": source,
        "issue_code": issue_code,
        "status": "OPEN",
        "assigned_operator_id": None,
    }
    db.repair_tickets[ticket["id"]] = ticket

    # Cascade hop 2: device AVAILABLE -> FAULTY (if target is a device currently AVAILABLE).
    if target_type == "DEVICE":
        device = db.devices.get(target_id)
        if device is not None and device["status"] == "AVAILABLE":
            device["status"] = "FAULTY"
            bump(device)
            # Cascade hop 3: slot OCCUPIED -> FAULTY (if device housed in a slot)
            housing_slot = None
            cab_id = device.get("current_cabinet_id")
            slot_idx = device.get("current_slot_index")
            if cab_id is not None and slot_idx is not None:
                for s in db.slots.values():
                    if s["cabinet_id"] == cab_id and s["slot_index"] == slot_idx:
                        housing_slot = s
                        break
                if housing_slot is not None and housing_slot["slot_status"] == "OCCUPIED":
                    housing_slot["slot_status"] = "FAULTY"
                    bump(housing_slot)
                    # Cascade hop 4: OperatorTask REPAIR_DISPATCH auto-created.
                    _create_repair_dispatch_task(housing_slot["cabinet_id"], ticket["id"])
    return ticket


def _create_repair_dispatch_task(cabinet_id: str, repair_ticket_id: str) -> dict:
    cf = make_common_fields()
    task = {
        **cf,
        "cabinet_id": cabinet_id,
        "task_type": "REPAIR_DISPATCH",
        "priority_score": compute_priority_score(cabinet_id),
        "status": "PENDING",
        "assigned_operator_id": None,
        "linked_repair_ticket_id": repair_ticket_id,
    }
    db.operator_tasks[task["id"]] = task
    return task
