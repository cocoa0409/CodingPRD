"""Rights-request deadline resolution and routing selection."""
import db
from services.core import created_asc
from services.risk import DEFAULT_DEADLINE_DAYS, DEFAULT_EXTENSION_DAYS
from utils import add_days


def resolve_governing_rule(consumer):
    """The StateLawRule with state_code == consumer.state_code, but only when
    the latest ApplicabilityEvaluation for it (created_at DESC) has
    applies == true. Returns None when no rule governs."""
    rule = None
    for r in db.state_law_rules.values():
        if r["state_code"] == consumer["state_code"]:
            rule = r
            break
    if rule is None:
        return None
    evaluations = [e for e in db.evaluations.values()
                   if e["state_law_rule_id"] == rule["id"]]
    if not evaluations:
        return None
    latest = max(evaluations, key=lambda e: (e["created_at"], e["_seq"]))
    if not latest["applies"]:
        return None
    return rule


def deadline_params(rule):
    if rule is None:
        return DEFAULT_DEADLINE_DAYS, DEFAULT_EXTENSION_DAYS
    return rule["request_deadline_days"], rule["extension_days"]


def provisional_due(created_at, rule):
    base_days, _ = deadline_params(rule)
    return add_days(created_at, base_days)


def final_due(created_at, request_type, rule):
    base_days, extension_days = deadline_params(rule)
    days = base_days
    if request_type in ("DELETION", "PORTABILITY"):
        days += extension_days
    return add_days(created_at, days)


def select_routing_systems(requested_categories):
    """ACTIVE DataSystems whose stores_categories intersect the requested
    categories, ranked created_at ASC with system_key ASC tie-break."""
    wanted = set(requested_categories)
    pool = [s for s in db.data_systems.values()
            if s["status"] == "ACTIVE" and wanted & set(s["stores_categories"])]
    pool.sort(key=lambda s: (s["created_at"], s["system_key"]))
    return pool


def is_overdue(request_row):
    """clock > effective due date (final when VERIFIED else provisional) and
    fulfillment_status not in {COMPLETED, DENIED}."""
    if request_row["fulfillment_status"] in ("COMPLETED", "DENIED"):
        return False
    if request_row["verification_status"] == "VERIFIED" and request_row["final_due_at"] is not None:
        due = request_row["final_due_at"]
    else:
        due = request_row["provisional_due_at"]
    import clock as _clock
    return _clock.now() > due


def bubble_task_started(task):
    parent = db.rights_requests.get(task["request_id"])
    if parent is not None and parent["fulfillment_status"] == "ROUTED":
        parent["fulfillment_status"] = "IN_PROGRESS"
        from services.core import touch
        touch(parent)


def bubble_task_terminal(task):
    siblings = [t for t in db.tasks.values() if t["request_id"] == task["request_id"]]
    if not all(t["status"] in ("COMPLETED", "CANCELLED") for t in siblings):
        return
    parent = db.rights_requests.get(task["request_id"])
    if parent is not None and parent["fulfillment_status"] == "IN_PROGRESS":
        parent["fulfillment_status"] = "READY_TO_RESPOND"
        from services.core import touch
        touch(parent)


def cancel_open_tasks(request_id):
    from services.core import touch
    targets = [t for t in db.tasks.values()
               if t["request_id"] == request_id
               and t["status"] in ("PENDING", "IN_PROGRESS")]
    for t in created_asc(targets):
        t["status"] = "CANCELLED"
        touch(t)
