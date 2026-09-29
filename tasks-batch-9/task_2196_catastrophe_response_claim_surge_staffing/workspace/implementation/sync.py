"""Clock-driven re-evaluation (PRD 2.6) and the acknowledgement deadline (3.2).

Every request runs sync_all() after authorization, so no caller ever observes a
row that is stale with respect to the logical clock.
"""
import calc
import derive
import store
from store import add_days, add_hours, clock_now, sorted_rows, touch


# --------------------------------------------------------------------------
# Acknowledgement deadline
# --------------------------------------------------------------------------
def extension_days(event_id):
    if event_id is None:
        return 0
    now = clock_now()
    total = 0
    rows = [b for b in store.bulletins.values()
            if b["event_id"] == event_id
            and b["bulletin_type"] == "CLAIM_DEADLINE_EXTENSION"
            and b["status"] == "EFFECTIVE"
            and b["effective_from"] <= now < b["effective_to"]]
    for b in sorted_rows(rows):
        total += int(b["deadline_extension_days"])
    return total


def deadline_anchor(claim):
    if claim["reopen_count"] == 0 or claim.get("reopen_anchor_utc") is None:
        return claim["reported_at_utc"]
    return claim["reopen_anchor_utc"]


def recompute_deadline(claim):
    claim["deadline_utc"] = calc.claim_deadline(deadline_anchor(claim),
                                               extension_days(claim["event_id"]))
    return claim["deadline_utc"]


def recompute_event_deadlines(event_id):
    """Population is every claim on the event outside CLOSED / TRANSFERRED."""
    for c in store.claims.values():
        if c["event_id"] != event_id:
            continue
        if c["handling_status"] in ("CLOSED", "TRANSFERRED"):
            continue
        if c["deadline_utc"] is None and c["handling_status"] == "INTAKE":
            continue
        recompute_deadline(c)


# --------------------------------------------------------------------------
# Credential axis helpers
# --------------------------------------------------------------------------
def derived_credential(adjuster):
    now = clock_now()
    expiry = adjuster["license_expiry_utc"]
    if now >= expiry:
        return "EXPIRED"
    if now >= add_days(expiry, -calc.LICENSE_WARNING_DAYS):
        return "EXPIRING"
    return "VALID"


def waiver_in_force(adjuster):
    event_id = adjuster.get("waiver_event_id")
    if event_id is None:
        return False
    event = store.events.get(event_id)
    if event is None:
        return False
    now = clock_now()
    for b in store.bulletins.values():
        if b["event_id"] != event_id:
            continue
        if b["bulletin_type"] != "ADJUSTER_LICENSE_WAIVER":
            continue
        if b["status"] != "EFFECTIVE":
            continue
        if b["jurisdiction_state"] != event["jurisdiction_state"]:
            continue
        if b["effective_from"] <= now < b["effective_to"]:
            return True
    return False


def cancel_scheduled_assignments(adjuster_id, statuses=("SCHEDULED",)):
    """Credential-lapse and waiver-loss cascades of PRD 3.3."""
    for a in sorted_rows([x for x in store.assignments.values()
                          if x["adjuster_id"] == adjuster_id
                          and x["status"] in statuses]):
        a["status"] = "CANCELLED"
        touch(a)
        regress_claim(a["claim_id"])


def regress_claim(claim_id):
    """INSPECTION_PENDING -> TRIAGED once no live assignment remains."""
    claim = store.claims.get(claim_id)
    if claim is None or claim["handling_status"] != "INSPECTION_PENDING":
        return False
    live = [x for x in store.assignments.values()
            if x["claim_id"] == claim_id
            and x["status"] in ("SCHEDULED", "IN_PROGRESS")]
    if live:
        return False
    claim["handling_status"] = "TRIAGED"
    touch(claim)
    return True


# --------------------------------------------------------------------------
# The lazy re-evaluation itself
# --------------------------------------------------------------------------
def sync_all():
    affected_events = set()

    # 1. Bulletins whose binding window has ended expire.
    for b in sorted_rows(list(store.bulletins.values())):
        if b["status"] == "EFFECTIVE" and clock_now() >= b["effective_to"]:
            b["status"] = "EXPIRED"
            touch(b)
            affected_events.add(b["event_id"])

    # 2. Credential axis, then the deployment axis rest buffer.
    for adj in sorted_rows(list(store.adjusters.values())):
        current = adj["credential_status"]
        if current == "WAIVED":
            if not waiver_in_force(adj):
                adj["credential_status"] = "EXPIRED"
                adj["waiver_event_id"] = None
                touch(adj)
                cancel_scheduled_assignments(adj["id"])
        else:
            target = derived_credential(adj)
            if target != current:
                adj["credential_status"] = target
                touch(adj)
                if target == "EXPIRED":
                    cancel_scheduled_assignments(adj["id"])

        if adj["deployment_status"] == "RESTING" \
                and adj["last_demobilized_at_utc"] is not None \
                and clock_now() >= add_hours(adj["last_demobilized_at_utc"],
                                             calc.REST_BUFFER_HOURS):
            adj["deployment_status"] = "AVAILABLE"
            touch(adj)

    # 3. Deadlines for every event whose bulletin population moved.
    for event_id in affected_events:
        recompute_event_deadlines(event_id)


def event_posture(event):
    return derive.event_posture(event)
