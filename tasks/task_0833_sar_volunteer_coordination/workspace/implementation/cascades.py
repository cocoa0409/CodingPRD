"""Cascading state side-effects shared across task/incident transitions."""
import store


def dec_resource(resource_id):
    """Decrement a resource's active_assignment_count (conserved quantity)."""
    r = store.resources.get(resource_id)
    if r is None:
        return
    if r["active_assignment_count"] > 0:
        r["active_assignment_count"] -= 1
    store.mutate(r)


def member_has_other_deployed(member_id, exclude_callout_id):
    return any(
        c["member_id"] == member_id
        and c["status"] == "DEPLOYED"
        and c["id"] != exclude_callout_id
        for c in store.callouts.values()
    )


def restore_member_if_free(member_id, exclude_callout_id):
    """Set member back to ACTIVE when they hold no other DEPLOYED callout."""
    if not member_has_other_deployed(member_id, exclude_callout_id):
        m = store.members.get(member_id)
        if m is not None and m["status"] != "ACTIVE":
            m["status"] = "ACTIVE"
            store.mutate(m)


def callouts_of_task(task_id):
    return [c for c in store.callouts.values() if c["task_id"] == task_id]


def assignments_of_task(task_id):
    return [a for a in store.resource_assignments.values() if a["task_id"] == task_id]


def task_cancel_cascade(task):
    """Demobilize field on task cancel; cancel resource assignments."""
    for c in callouts_of_task(task["id"]):
        st = c["status"]
        if st == "REQUESTED":
            c["status"] = "NO_RESPONSE"
            store.mutate(c)
        elif st in ("ACKNOWLEDGED", "STANDBY"):
            c["status"] = "DEMOBILIZED"
            store.mutate(c)
        elif st == "DEPLOYED":
            c["status"] = "DEMOBILIZED"
            store.mutate(c)
            restore_member_if_free(c["member_id"], c["id"])
    for a in assignments_of_task(task["id"]):
        if a["status"] in ("RESERVED", "ACTIVE"):
            a["status"] = "CANCELLED"
            store.mutate(a)
            dec_resource(a["resource_id"])


def task_suspend_cascade(task):
    """Release ACTIVE resource assignments on task suspend."""
    for a in assignments_of_task(task["id"]):
        if a["status"] == "ACTIVE":
            a["status"] = "RELEASED"
            store.mutate(a)
            dec_resource(a["resource_id"])


def task_debrief_cascade(task):
    """Demobilize DEPLOYED callouts on task debrief; restore members."""
    for c in callouts_of_task(task["id"]):
        if c["status"] == "DEPLOYED":
            c["status"] = "DEMOBILIZED"
            store.mutate(c)
            restore_member_if_free(c["member_id"], c["id"])


def incident_cancel_cascade(incident):
    """Cancel every non-terminal task, each firing its own task cascade."""
    active = {"DRAFT", "ASSIGNED", "IN_PROGRESS", "SUSPENDED"}
    affected = [
        t for t in store.tasks.values()
        if t["incident_id"] == incident["id"] and t["status"] in active
    ]
    for t in affected:
        t["status"] = "CANCELLED"
        store.mutate(t)
        task_cancel_cascade(t)
