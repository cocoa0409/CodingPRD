"""Domain services: org-tree helpers, cycle auto-close on clock advance,
invite reminder sweeps, scoring (snapshot generation), plan auto-completion,
and derived-counter reconciliation.
"""

from datetime import timedelta

from db import db, touch, stamp_new, stamp_new_immutable, now_iso, parse_ts
from errors import err, ERR_INVALID_STATE
from services import calculations as calc


# ---------------------------------------------------------------------------
# Org unit tree helpers
# ---------------------------------------------------------------------------

def unit_subtree_ids(unit_id):
    """unit_id plus all descendant unit ids."""
    result = {unit_id}
    changed = True
    while changed:
        changed = False
        for unit in db.org_units.values():
            pid = unit.get("parent_unit_id")
            if pid in result and unit["id"] not in result:
                result.add(unit["id"])
                changed = True
    return result


def manager_subtree_ids(user_id):
    """All units whose manager_user_id == user_id, plus their descendants."""
    owned = [u["id"] for u in db.org_units.values() if u["manager_user_id"] == user_id]
    result = set()
    for uid in owned:
        result |= unit_subtree_ids(uid)
    return result


def would_create_unit_cycle(unit_id, new_parent_id):
    """True when setting unit.parent_unit_id = new_parent_id closes a cycle.

    A cycle exists iff unit_id is an ancestor of (or equal to) new_parent_id.
    """
    if new_parent_id is None:
        return False
    if new_parent_id == unit_id:
        return True
    seen = set()
    cur = new_parent_id
    while cur is not None and cur not in seen:
        seen.add(cur)
        if cur == unit_id:
            return True
        parent = db.org_units.get(cur)
        cur = parent.get("parent_unit_id") if parent else None
    return False


# ---------------------------------------------------------------------------
# Derived counters on SurveyCycle
# ---------------------------------------------------------------------------

def recompute_cycle_counters(cycle):
    """Recompute invited/submitted/partial counts and response_rate. Bumps the
    cycle's version only when a derived value actually changes (§2.4)."""
    invited, submitted, partial, rate = calc.compute_response_rate(cycle["id"])
    changed = (
        cycle.get("invited_count") != invited
        or cycle.get("submitted_count") != submitted
        or cycle.get("partial_count") != partial
        or cycle.get("response_rate") != rate
    )
    cycle["invited_count"] = invited
    cycle["submitted_count"] = submitted
    cycle["partial_count"] = partial
    cycle["response_rate"] = rate
    if changed:
        touch(cycle)


# ---------------------------------------------------------------------------
# Cycle auto-close on clock advance
# ---------------------------------------------------------------------------

def fire_auto_transitions():
    """After a clock set: auto-close any OPEN cycle whose closes_at has been
    reached (logical clock >= closes_at)."""
    for cycle in list(db.survey_cycles.values()):
        if cycle["status"] == "OPEN" and db.clock >= cycle["_closes_at"]:
            close_cycle(cycle)


def close_cycle(cycle):
    """OPEN -> CLOSED. Expire INVITED/REMINDED invites; PARTIAL stays PARTIAL."""
    cycle["status"] = "CLOSED"
    for iv in db.survey_invites.values():
        if iv["cycle_id"] == cycle["id"] and iv["status"] in ("INVITED", "REMINDED"):
            iv["status"] = "EXPIRED"
            touch(iv)
    touch(cycle)
    recompute_cycle_counters(cycle)


# ---------------------------------------------------------------------------
# Scoring: snapshot generation
# ---------------------------------------------------------------------------

def generate_snapshots(cycle):
    """CLOSED -> SCORING side effect: for every OrgUnit with >= 1 invite in the
    cycle, generate DIRECT and SUBTREE snapshots, run scoring/suppression/
    percentile, then compute the provisional attrition risk."""
    invited_unit_ids = {
        iv["unit_id_at_invite"]
        for iv in db.survey_invites.values()
        if iv["cycle_id"] == cycle["id"]
    }
    for unit_id in sorted(
            invited_unit_ids,
            key=lambda uid: db.org_units[uid]["_created_seq"] if uid in db.org_units else 0):
        for scope in ("DIRECT", "SUBTREE"):
            snap = stamp_new({
                "cycle_id": cycle["id"],
                "unit_id": unit_id,
                "scope": scope,
                "submitted_n": 0,
                "dimension_scores": {},
                "overall_score": None,
                "benchmark_percentile": None,
                "numeric_suppressed": False,
                "verbatim_suppressed": False,
                "generation": 1,
            })
            computed = calc.compute_snapshot_fields(snap)
            snap.update(computed)
            db.report_snapshots[snap["id"]] = snap

    # Provisional attrition risk (snapshots exist, so low_engagement decidable).
    risk = calc.compute_attrition_risk(cycle, provisional=True)
    if cycle.get("attrition_risk") != risk:
        cycle["attrition_risk"] = risk


def recompute_snapshot(snap):
    computed = calc.compute_snapshot_fields(snap)
    snap.update(computed)
    snap["generation"] = snap.get("generation", 1) + 1
    touch(snap)


# ---------------------------------------------------------------------------
# Reminder sweep
# ---------------------------------------------------------------------------

def run_reminder_sweep(cycle):
    """Bulk reminder sweep over non-submitted invites of an OPEN cycle.

    Returns (reminded_count, reminded_invite_ids). Cap-blocked or
    cadence-blocked invites are skipped silently.
    """
    now = db.clock
    reminded = []
    invites = [iv for iv in db.survey_invites.values()
               if iv["cycle_id"] == cycle["id"]
               and iv["status"] in ("INVITED", "REMINDED")]
    invites.sort(key=lambda iv: iv["_created_seq"])
    for iv in invites:
        if iv["reminder_count"] >= 3:
            continue
        if iv["status"] == "INVITED" and iv["last_reminded_at"] is None:
            if now < cycle["_opens_at"] + timedelta(hours=24):
                continue
        else:
            if iv["last_reminded_at"] is None:
                continue
            last = parse_ts(iv["last_reminded_at"])
            if now - last < timedelta(hours=48):
                continue
        # Send the reminder.
        seq_no = iv["reminder_count"] + 1
        event = stamp_new_immutable({
            "invite_id": iv["id"],
            "sent_at": now_iso(),
            "sequence_no": seq_no,
        })
        db.reminder_events[event["id"]] = event
        iv["reminder_count"] += 1
        iv["last_reminded_at"] = now_iso()
        iv["status"] = "REMINDED"
        touch(iv)
        reminded.append(iv["id"])
    return len(reminded), reminded


# ---------------------------------------------------------------------------
# Action plan helpers
# ---------------------------------------------------------------------------

def recompute_plan_progress(plan):
    plan["progress_pct"] = calc.compute_progress_pct(plan["id"])


def maybe_auto_complete_plan(plan):
    """When the last OPEN item resolves and at least one DONE exists, the plan
    auto-transitions IN_PROGRESS -> COMPLETED with progress_pct = 100."""
    if plan["status"] != "IN_PROGRESS":
        return
    items = [ai for ai in db.action_items.values() if ai["plan_id"] == plan["id"]]
    if not items:
        return
    open_count = sum(1 for ai in items if ai["status"] == "OPEN")
    done_count = sum(1 for ai in items if ai["status"] == "DONE")
    if open_count == 0 and done_count >= 1:
        plan["status"] = "COMPLETED"
        plan["progress_pct"] = 100
        touch(plan)
