"""Shared workflow helpers: event appends, transitions, lookup utilities."""

from datetime import timedelta

import calc
import db
import errors


# ---------------------------------------------------------------------------
# Lookups (path-id existence -> ERR_NOT_FOUND)
# ---------------------------------------------------------------------------

def get_or_404(store, entity_id, label="resource"):
    row = store.get(entity_id)
    if row is None:
        raise errors.not_found(f"{label} not found: {entity_id}")
    return row


def get_case_or_404(case_id):
    return get_or_404(db.cases, case_id, "case")


# ---------------------------------------------------------------------------
# Event appends
# ---------------------------------------------------------------------------

def append_event(case, event_type, actor_role, actor_id, body=None,
                 bump_case_version=False):
    """Append a CaseEvent. When the append is standalone (not part of a
    transition that already bumps the case version), bump the case version."""
    event = db.make_append_only()
    event.update({
        "case_id": case["id"],
        "event_type": event_type,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "body": body,
        "occurred_at": db.clock_now(),
    })
    db.events[event["id"]] = event
    if bump_case_version:
        db.touch(case)
    return event


# ---------------------------------------------------------------------------
# Case terminal / state guards
# ---------------------------------------------------------------------------

CASE_TERMINAL = ("CLOSED", "WITHDRAWN")
REVIEW_TERMINAL = ("DETERMINED", "SUPERSEDED")
NOTIFICATION_TERMINAL = ("DELIVERED", "FAILED")
EFFECTUATION_TERMINAL = ("EFFECTUATED", "WAIVED")
REOPENING_TERMINAL = ("GRANTED", "DENIED")
REFERRAL_TERMINAL = ("EFFECTUATED",)


def guard_case_mutable(case):
    if case["status"] in CASE_TERMINAL:
        raise errors.already_terminal(
            f"case is in terminal state {case['status']}")


def guard_status(case, allowed):
    """Terminal -> ERR_ALREADY_TERMINAL; otherwise undeclared -> ERR_INVALID_STATE."""
    guard_case_mutable(case)
    if case["status"] not in allowed:
        raise errors.invalid_state(
            f"case status {case['status']} does not allow this action")


def guard_entity_status(entity, allowed, terminal_states, label):
    if entity["status"] in terminal_states:
        raise errors.already_terminal(
            f"{label} is in terminal state {entity['status']}")
    if entity["status"] not in allowed:
        raise errors.invalid_state(
            f"{label} status {entity['status']} does not allow this action")


# ---------------------------------------------------------------------------
# Shared case side effects
# ---------------------------------------------------------------------------

def recompute_resolution_due(case):
    member = db.members[case["member_id"]]
    policy = calc.active_policy_or_error(
        member["program"], case["case_kind"], case["priority_track"])
    case["resolution_due_at"] = calc.compute_resolution_due(case, policy)
    return policy


def maybe_close_reopened_source(spawned_case):
    """REOPENED -> CLOSED auto-transition: fires when the spawned replacement
    case reaches CLOSED (scaffold section 1.2)."""
    source_id = spawned_case.get("reopened_from_case_id")
    if not source_id:
        return
    source = db.cases.get(source_id)
    if source is None or source["status"] != "REOPENED":
        return
    source["status"] = "CLOSED"
    source["closed_at"] = db.clock_now()
    db.touch(source)


def close_case(case, actor_role, actor_id):
    """Shared closure side effects for NOTIFIED->CLOSED and IRE_REFERRED->CLOSED."""
    case["status"] = "CLOSED"
    case["closed_at"] = db.clock_now()
    append_event(case, "NOTE", actor_role, actor_id, body="CLOSED")
    db.touch(case)
    maybe_close_reopened_source(case)


def live_review_for_case(case_id):
    """At most one live review (REQUESTED/ASSIGNED/DETERMINATION_DRAFT)."""
    for r in db.reviews.values():
        if (r["case_id"] == case_id
                and r["status"] in ("REQUESTED", "ASSIGNED", "DETERMINATION_DRAFT")):
            return r
    return None


def determined_review_exists(case_id):
    return any(r["case_id"] == case_id and r["status"] == "DETERMINED"
               for r in db.reviews.values())


def effectuations_for_case(case_id):
    rows = [e for e in db.effectuations.values() if e["case_id"] == case_id]
    rows.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return rows


def referrals_for_case(case_id):
    rows = [r for r in db.referrals.values() if r["case_id"] == case_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def create_effectuation(case, payment_amount_cents, referral_id=None):
    eff = db.make_common()
    eff.update({
        "case_id": case["id"],
        "referral_id": referral_id,
        "status": "PENDING",
        "payment_amount_cents": payment_amount_cents,
        "timeliness_percent": None,
        "completed_at": None,
    })
    db.effectuations[eff["id"]] = eff
    return eff


def sweep_effectuations_overdue():
    """Clock-set side effect: IN_PROGRESS effectuations whose parent case
    effectuation_due_at is now in the past transition to OVERDUE."""
    now = db.clock_now()
    for eff in db.effectuations.values():
        if eff["status"] != "IN_PROGRESS":
            continue
        case = db.cases.get(eff["case_id"])
        if case is None:
            continue
        due = case.get("effectuation_due_at")
        if due is not None and due < now:
            eff["status"] = "OVERDUE"
            db.touch(eff)
