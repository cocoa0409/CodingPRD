"""Core derived-state machinery: governing-rule selection, retention due
dates, disposition posture, stale-snapshot cascades, hold coverage
reconciliation, and destruction certificates.

Pinned derivations (PRD / scaffold):
- governing_rule_selection: OPEN conflict for (class, jurisdiction) -> no
  governing rule; else the unique ACTIVE rule whose half-open window covers
  the record's event_date.
- retention_due_date: anchor (EVENT_DATE raw, or first fiscal-year-end on or
  after event_date) + retention_months with last-day clamping.
- disposition_posture precedence: UNSCHEDULED > HELD > CONFLICT_BLOCKED >
  ELIGIBLE > RETAINED.
- stale_item_count: +1 when a contained record leaves ELIGIBLE, -1 when it
  re-enters ELIGIBLE, on SUBMITTED/APPROVED DispositionRequests only.
"""
from db import db, now, bump


# ---------------------------------------------------------------------------
# Conflicts and governing-rule selection
# ---------------------------------------------------------------------------
def open_conflict_for(record_class_id, jurisdiction_id):
    for c in db.retention_conflicts.values():
        if (c["status"] == "OPEN"
                and c["record_class_id"] == record_class_id
                and c["jurisdiction_id"] == jurisdiction_id):
            return c
    return None


def windows_overlap(a_from, a_to, b_from, b_to):
    """Half-open [from, to) overlap: a.from < b.to AND b.from < a.to.
    Mere adjacency (a.from == b.to) is NOT overlap. None means open-ended."""
    a_to_inf = a_to is None
    b_to_inf = b_to is None
    if not b_to_inf and not a_from < b_to:
        return False
    if not a_to_inf and not b_from < a_to:
        return False
    return True


def window_covers(rule, event_date):
    return (rule["effective_from"] <= event_date
            and (rule["effective_to"] is None or event_date < rule["effective_to"]))


def select_governing_rule(rec):
    """ACTIVE rule covering the record's event_date; None under an OPEN
    conflict or when no candidate covers (UNSCHEDULED)."""
    if open_conflict_for(rec["record_class_id"], rec["jurisdiction_id"]):
        return None
    cands = [r for r in db.retention_rules.values()
             if r["status"] == "ACTIVE"
             and r["record_class_id"] == rec["record_class_id"]
             and r["jurisdiction_id"] == rec["jurisdiction_id"]
             and window_covers(r, rec["event_date"])]
    if not cands:
        return None
    # Deterministic pick (the conflict machinery guarantees at most one).
    cands.sort(key=lambda r: (r["created_at"], r["rule_code"]))
    return cands[0]


def compute_due_date(rule, rec):
    program = db.programs.get(rule["program_id"])
    if rule["trigger_basis"] == "EVENT_DATE":
        anchor = rec["event_date"]
    else:  # FISCAL_YEAR_END: first program FYE on or after event_date
        y = rec["event_date"].year
        fye = clamp_fye(program, y)
        anchor = fye if rec["event_date"] <= fye else clamp_fye(program, y + 1)
    from utils import add_months
    return add_months(anchor, rule["retention_months"])


def clamp_fye(program, year):
    from utils import clamped_fye
    return clamped_fye(year, program["fiscal_year_end_month"],
                       program["fiscal_year_end_day"])


# ---------------------------------------------------------------------------
# Record stored computed fields and derived posture
# ---------------------------------------------------------------------------
def recompute_record_schedule(rec):
    """Recompute stored governing_rule_id / retention_due_date. Returns True
    when a stored field changed (a mutation worthy of a version bump)."""
    if open_conflict_for(rec["record_class_id"], rec["jurisdiction_id"]):
        new_gov, new_due = None, rec["retention_due_date"]
    else:
        rule = select_governing_rule(rec)
        if rule is None:
            new_gov, new_due = None, None
        else:
            new_gov, new_due = rule["id"], compute_due_date(rule, rec)
    changed = (new_gov != rec.get("governing_rule_id")
               or new_due != rec.get("retention_due_date"))
    rec["governing_rule_id"] = new_gov
    rec["retention_due_date"] = new_due
    return changed


def record_active_hold_count(rec):
    return sum(1 for it in db.hold_scope_items.values()
               if it["record_id"] == rec["id"] and it["status"] == "ACTIVE")


def derive_posture(rec):
    """Pinned precedence: UNSCHEDULED > HELD > CONFLICT_BLOCKED > ELIGIBLE >
    RETAINED."""
    conflict = open_conflict_for(rec["record_class_id"], rec["jurisdiction_id"]) is not None
    if not conflict and rec.get("governing_rule_id") is None:
        return "UNSCHEDULED"
    if record_active_hold_count(rec) > 0:
        return "HELD"
    if conflict:
        return "CONFLICT_BLOCKED"
    if now() >= rec["retention_due_date"]:
        return "ELIGIBLE"
    return "RETAINED"


# ---------------------------------------------------------------------------
# Stale-eligibility snapshots on in-flight disposition requests
# ---------------------------------------------------------------------------
def adjust_stale_for_record(rec, old_posture, new_posture):
    if old_posture == new_posture:
        return
    if old_posture == "ELIGIBLE" and new_posture != "ELIGIBLE":
        delta = 1
    elif old_posture != "ELIGIBLE" and new_posture == "ELIGIBLE":
        delta = -1
    else:
        return
    for req in db.disposition_requests.values():
        if req["status"] not in ("SUBMITTED", "APPROVED"):
            continue
        if any(it["record_id"] == rec["id"]
               for it in db.disposition_items.values()
               if it["request_id"] == req["id"]):
            req["stale_item_count"] = req.get("stale_item_count", 0) + delta
            bump(req)


def recompute_records_for_pair(record_class_id, jurisdiction_id):
    """Rule churn cascade: recompute every ACTIVE-status record of the pair;
    bump records whose stored schedule changed; adjust stale counters for
    posture flips into/out of ELIGIBLE."""
    recs = [r for r in db.records.values()
            if r["record_class_id"] == record_class_id
            and r["jurisdiction_id"] == jurisdiction_id
            and r["status"] == "ACTIVE"]
    recs.sort(key=lambda r: r["created_at"])
    for rec in recs:
        old_posture = derive_posture(rec)
        changed = recompute_record_schedule(rec)
        if changed:
            bump(rec)
        adjust_stale_for_record(rec, old_posture, derive_posture(rec))


def posture_flip_around(records, mutate):
    """Capture postures of the given records, apply `mutate()`, then adjust
    stale counters for any record that flipped into/out of ELIGIBLE. Records
    are bumped because their hold coverage changed."""
    before = {r["id"]: derive_posture(r) for r in records}
    mutate()
    for r in records:
        bump(r)
        adjust_stale_for_record(r, before[r["id"]], derive_posture(r))


# ---------------------------------------------------------------------------
# Hold aggregate helpers (derived on read)
# ---------------------------------------------------------------------------
def hold_assignments(hold_id):
    return [a for a in db.hold_custodians.values() if a["hold_id"] == hold_id]


def hold_items(hold_id):
    return [i for i in db.hold_scope_items.values() if i["hold_id"] == hold_id]


def hold_active_scope_count(hold_id):
    return sum(1 for i in db.hold_scope_items.values()
               if i["hold_id"] == hold_id and i["status"] == "ACTIVE")


def hold_all_acknowledged(hold_id):
    assigns = hold_assignments(hold_id)
    return len(assigns) > 0 and all(
        a["status"] in ("ACKNOWLEDGED", "RELEASED") for a in assigns)


def hold_late_ack_count(hold_id):
    return sum(1 for a in hold_assignments(hold_id) if a.get("was_late") is True)


def custodian_open_obligations(custodian_id):
    return sum(1 for a in db.hold_custodians.values()
               if a["custodian_id"] == custodian_id
               and a["status"] in ("PENDING", "ESCALATED"))


def add_reminder_log(hold, assignment, kind, reminder_seq):
    from db import new_id
    entry = {
        "id": new_id(),
        "created_at": now(),
        "program_id": hold["program_id"],
        "hold_id": hold["id"],
        "hold_custodian_id": assignment["id"],
        "custodian_id": assignment["custodian_id"],
        "kind": kind,
        "sent_at": now(),
        "reminder_seq": reminder_seq,
    }
    db.reminder_logs[entry["id"]] = entry
    return entry


# ---------------------------------------------------------------------------
# Freeze windows
# ---------------------------------------------------------------------------
def freeze_window_active(program_id):
    t = now()
    for w in db.freeze_windows.values():
        if (w["program_id"] == program_id and w["status"] == "ACTIVE"
                and w["start_at"] <= t <= w["end_at"]):
            return True
    return False


# ---------------------------------------------------------------------------
# Destruction
# ---------------------------------------------------------------------------
def next_cert_seq(program_id):
    seq = db.cert_seq.get(program_id, 0) + 1
    db.cert_seq[program_id] = seq
    return seq


def create_certificate(program_id, request_id, item_id, rec, method, witness):
    import hashlib
    from db import new_id
    from utils import fmt_ts
    rclass = db.record_classes.get(rec["record_class_id"])
    jur = db.jurisdictions.get(rec["jurisdiction_id"])
    destroyed = rec["destroyed_at"]
    digest = hashlib.sha256(
        ("%s|%s|%s" % (rec["id"], rec["title"], fmt_ts(destroyed))).encode("utf-8")
    ).hexdigest()
    cert = {
        "id": new_id(),
        "created_at": now(),
        "program_id": program_id,
        "request_id": request_id,
        "disposition_item_id": item_id,
        "record_id": rec["id"],
        "record_title": rec["title"],
        "record_class_code": rclass["code"] if rclass else None,
        "jurisdiction_code": jur["code"] if jur else None,
        "retention_due_date": rec.get("retention_due_date"),
        "destroyed_at": destroyed,
        "method": method,
        "content_hash": digest,
        "witness_user_id": witness,
        "certificate_seq": next_cert_seq(program_id),
    }
    db.destruction_certificates[cert["id"]] = cert
    return cert


def destroy_record(rec):
    rec["status"] = "DESTROYED"
    rec["destroyed_at"] = now()
    bump(rec)
