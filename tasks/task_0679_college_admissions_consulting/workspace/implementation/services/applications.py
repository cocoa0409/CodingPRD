"""Application-level helpers: open_task_count recompute, appeal task append."""
from db import store
from common import make_entity


def compute_open_task_count(application):
    """Count this application's tasks in OPEN or BLOCKED (per scaffold field def)."""
    count = 0
    for task in store.application_tasks.values():
        if task.get("application_id") != application["id"]:
            continue
        if task.get("status") in ("OPEN", "BLOCKED"):
            count += 1
    return count


def recompute_open_task_count(application):
    application["open_task_count"] = compute_open_task_count(application)


def append_appeal_task(application):
    """Append a system FORM task 'Appeal letter', blocks_submission=false, OPEN."""
    t = make_entity()
    t.update({
        "application_id": application["id"],
        "title": "Appeal letter",
        "task_type": "FORM",
        "due_utc": application["deadline_utc"],
        "estimated_cost_cents": 0,
        "blocks_submission": False,
        "status": "OPEN",
    })
    store.application_tasks[t["id"]] = t
    return t
