"""Checklist generation and the compound turnover status (PRD 3.5, 3.6)."""

from db import base_fields, db, ordered, touch

# task_code, sequence_no, category, requires_photo, applicable size tiers
ALL_TIERS = ("STUDIO", "ONE_BR", "TWO_BR", "THREE_BR_PLUS")
CHECKLIST_TEMPLATE = (
    ("STRIP_LINENS", 10, "CLEANING", False, ALL_TIERS),
    ("BATHROOM_DEEP_CLEAN", 20, "CLEANING", True, ALL_TIERS),
    ("BED_STAGING", 30, "STAGING", True, ALL_TIERS),
    ("SUPPLY_RESTOCK", 40, "RESTOCK", True, ALL_TIERS),
    ("PATIO_STAGING", 50, "STAGING", True, ("THREE_BR_PLUS",)),
)

UNDERWAY_STATUSES = ("IN_PROGRESS", "AWAITING_VERIFICATION", "REWORK_REQUIRED")
NON_TERMINAL_TURNOVER_STATUSES = (
    "PENDING_ASSIGNMENT", "SCHEDULED", "IN_PROGRESS", "AWAITING_VERIFICATION",
    "REWORK_REQUIRED", "ON_HOLD",
)


def generate_checklist(turnover, prop):
    """Rows projected from the fixed template in ascending template order."""
    created = []
    for task_code, sequence_no, category, requires_photo, tiers in CHECKLIST_TEMPLATE:
        if prop["size_tier"] not in tiers:
            continue
        task = base_fields()
        task.update({
            "turnover_id": turnover["id"],
            "task_code": task_code,
            "category": category,
            "sequence_no": sequence_no,
            "requires_photo": requires_photo,
            "photo_uri": None,
            "note": None,
            "status": "PENDING",
            "submitted_at": None,
            "reviewed_by_user_id": None,
            "reject_count": 0,
            "reject_reason": None,
            "restock_line_count": 0,
            "restock_charge_cents": 0,
            "_restock_entries": [],
        })
        db.checklist_tasks[task["id"]] = task
        created.append(task)
    turnover["checklist_task_count"] = len(created)
    return created


def turnover_tasks(turnover_id):
    return sorted(
        [t for t in db.checklist_tasks.values() if t["turnover_id"] == turnover_id],
        key=lambda t: (t["sequence_no"], t["_seq"]),
    )


def derive_status(turnover):
    """Ordered child rule, first match winning (PRD 3.6)."""
    tasks = turnover_tasks(turnover["id"])
    if any(t["status"] == "REJECTED" for t in tasks):
        return "REWORK_REQUIRED"
    if any(t["status"] == "PENDING" for t in tasks):
        return "IN_PROGRESS"
    return "AWAITING_VERIFICATION"


def rederive_turnover(turnover, force_bump=False):
    """Re-derive the parent status from its children.  Only a turnover that is
    currently underway is re-derived; ON_HOLD, COMPLETED and VOID never are.
    A re-derivation that actually changes the status bumps the version."""
    changed = False
    if turnover["status"] in UNDERWAY_STATUSES:
        new_status = derive_status(turnover)
        if new_status != turnover["status"]:
            turnover["status"] = new_status
            changed = True
    if changed or force_bump:
        touch(turnover, bump=True)
    return changed


def all_tasks_closed(turnover):
    return all(t["status"] in ("VERIFIED", "WAIVED")
               for t in turnover_tasks(turnover["id"]))


def verified_restock_chargeback(turnover):
    total = 0
    for task in ordered(db.checklist_tasks.values()):
        if task["turnover_id"] != turnover["id"]:
            continue
        if task["category"] == "RESTOCK" and task["status"] == "VERIFIED":
            total += task["restock_charge_cents"]
    return total
