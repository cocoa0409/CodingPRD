"""Shared service logic: posture gate, cascading effects, escalation events,
the daily scan, and schedule-impact cascade."""
from datetime import timedelta

import calc
from db import store
from store_ops import touch, new_id


# ---------------------------------------------------------------------------
# Posture gates (PRD 2.5)
# ---------------------------------------------------------------------------

def require_active(project):
    """Child mutations require posture == ACTIVE."""
    if project["posture"] != "ACTIVE":
        from errors import project_not_active
        raise project_not_active()


def require_setup_or_active(project):
    """Spec-section create/activate carve-out: SETUP or ACTIVE."""
    if project["posture"] not in ("SETUP", "ACTIVE"):
        from errors import project_not_active
        raise project_not_active()


def require_active_or_closeout(project):
    """Owner-report create/publish carve-out: ACTIVE or CLOSEOUT."""
    if project["posture"] not in ("ACTIVE", "CLOSEOUT"):
        from errors import project_not_active
        raise project_not_active()


# ---------------------------------------------------------------------------
# Escalation events (PRD 3.8)
# ---------------------------------------------------------------------------

def append_escalation_event(project_id, event_type, source_type, source_id, detail):
    ev = {
        "id": new_id(),
        "_seq": next(store.seq),
        "created_at": store.clock,
        "project_id": project_id,
        "event_type": event_type,
        "source_type": source_type,
        "source_id": source_id,
        "detail": detail,
        "event_date": calc.clock_date(),
    }
    store.escalation_events[ev["id"]] = ev
    return ev


# ---------------------------------------------------------------------------
# Expediting re-evaluation (PRD 3.4)
# ---------------------------------------------------------------------------

def reevaluate_expediting(submittal, lli):
    """Recompute submittal.expediting_status after a relevant change.

    - Delivery moves the dimension to CLEAR (handled at advance call site).
    - From EXPEDITING: rises to ESCALATED when level >= 2, subsides below 2.
    - From MONITORING: rises straight to ESCALATED when level >= 2 (scan).
    """
    if lli is None:
        return
    if lli["status"] == "DELIVERED":
        if submittal["expediting_status"] in ("MONITORING", "EXPEDITING", "ESCALATED"):
            submittal["expediting_status"] = "CLEAR"
        return
    if lli["status"] == "CANCELLED":
        return
    level = lli["escalation_level"]
    exp = submittal["expediting_status"]
    if level >= 2 and exp in ("MONITORING", "EXPEDITING"):
        submittal["expediting_status"] = "ESCALATED"
    elif level < 2 and exp == "ESCALATED":
        submittal["expediting_status"] = "EXPEDITING"


# ---------------------------------------------------------------------------
# LLI recompute + escalation events
# ---------------------------------------------------------------------------

def recompute_lli_with_events(lli, submittal):
    """Recompute the LLI and append tier-change events; re-evaluate expediting."""
    old_level, new_level = calc.recompute_lli(lli, submittal)
    if new_level > old_level:
        append_escalation_event(
            lli["project_id"], "LLI_ESCALATION_RAISED", "LONG_LEAD_ITEM", lli["id"],
            "escalation_level %d -> %d" % (old_level, new_level),
        )
    elif new_level < old_level:
        append_escalation_event(
            lli["project_id"], "LLI_ESCALATION_CLEARED", "LONG_LEAD_ITEM", lli["id"],
            "escalation_level %d -> %d" % (old_level, new_level),
        )
    reevaluate_expediting(submittal, lli)


# ---------------------------------------------------------------------------
# Affected-subcontractor selector (PRD 3.3 / 3.5)
# ---------------------------------------------------------------------------

def affected_subcontractor_ids(project_id, section, submittal_id):
    """Distinct set: section's responsible sub UNION subs of non-CANCELLED
    InstallationActivities referencing the submittal. Ordered by created_at ASC."""
    seen = set()
    ordered = []
    responsible = section.get("responsible_subcontractor_id") if section else None
    if responsible:
        sub = store.subcontractors.get(responsible)
        if sub is not None:
            seen.add(responsible)
            ordered.append(sub)
    if submittal_id:
        acts = [
            a for a in store.installation_activities.values()
            if a["project_id"] == project_id
            and a["submittal_id"] == submittal_id
            and a["status"] != "CANCELLED"
        ]
        subs = []
        for a in acts:
            s = store.subcontractors.get(a["subcontractor_id"])
            if s is not None and s["id"] not in seen:
                seen.add(s["id"])
                subs.append(s)
        subs.sort(key=lambda s: s["_seq"])
        ordered.extend(subs)
    # final ordering: created_at ASC across the whole union
    ordered.sort(key=lambda s: s["_seq"])
    return ordered


def create_distribution_records(project_id, source_type, source_id, subs):
    out = []
    for sub in subs:
        rec = {
            "id": new_id(),
            "_seq": next(store.seq),
            **{"created_at": store.clock, "updated_at": store.clock, "version": 1},
            "project_id": project_id,
            "subcontractor_id": sub["id"],
            "source_type": source_type,
            "source_id": source_id,
            "status": "QUEUED",
            "sent_date": None,
            "ack_due_date": None,
            "acknowledged_date": None,
            "is_overdue": False,
        }
        store.distribution_records[rec["id"]] = rec
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# Daily scan (PRD 3.8)
# ---------------------------------------------------------------------------

def run_daily_scan(project):
    """Runs the four families of scan effects. Assumes posture already checked."""
    pid = project["id"]
    today = calc.clock_date()

    # 1. Overdue RFIs — at most once per RFI per current answer cycle.
    for rfi in store.rfis.values():
        if rfi["project_id"] != pid:
            continue
        if rfi["status"] not in ("OPEN", "ROUTED"):
            continue
        due = rfi.get("due_date")
        if due is None:
            continue
        if today > due and not rfi["is_overdue"]:
            rfi["is_overdue"] = True
            touch(rfi)
            append_escalation_event(
                pid, "RFI_OVERDUE", "RFI", rfi["id"],
                "RFI %s overdue (due %s)" % (rfi["rfi_number"], due.isoformat()),
            )

    # 2. Long-lead recomputation.
    for lli in store.long_lead_items.values():
        if lli["project_id"] != pid:
            continue
        if lli["status"] in ("DELIVERED", "CANCELLED"):
            continue
        submittal = store.submittals.get(lli["submittal_id"])
        old_level, new_level = calc.recompute_lli(lli, submittal)
        if new_level > old_level:
            append_escalation_event(
                pid, "LLI_ESCALATION_RAISED", "LONG_LEAD_ITEM", lli["id"],
                "escalation_level %d -> %d" % (old_level, new_level),
            )
        elif new_level < old_level:
            append_escalation_event(
                pid, "LLI_ESCALATION_CLEARED", "LONG_LEAD_ITEM", lli["id"],
                "escalation_level %d -> %d" % (old_level, new_level),
            )
        if submittal is not None:
            reevaluate_expediting(submittal, lli)
        touch(lli)

    # 3. Auto-advance expediting MONITORING -> EXPEDITING.
    for sub in store.submittals.values():
        if sub["project_id"] != pid:
            continue
        if sub["expediting_status"] != "MONITORING":
            continue
        rod = sub.get("required_on_site_date")
        if rod is None:
            continue
        days_until = (rod - today).days
        if days_until <= project["expedite_window_days"]:
            sub["expediting_status"] = "EXPEDITING"
            # A level>=2 LLI would already have been raised to ESCALATED in step 2
            # for existing items; if the LLI is at level >= 2 stay ESCALATED.
            lli = find_lli_for_submittal(sub["id"])
            if lli is not None and lli["escalation_level"] >= 2:
                sub["expediting_status"] = "ESCALATED"
            touch(sub)

    # 4. Acknowledgement policing.
    for rec in store.distribution_records.values():
        if rec["project_id"] != pid:
            continue
        if rec["status"] != "SENT":
            continue
        if rec["is_overdue"]:
            continue
        ack_due = rec.get("ack_due_date")
        if ack_due is None:
            continue
        if today > ack_due:
            rec["is_overdue"] = True
            touch(rec)
            append_escalation_event(
                pid, "DIST_ACK_OVERDUE", "DISTRIBUTION_RECORD", rec["id"],
                "ack overdue (due %s)" % ack_due.isoformat(),
            )
            sub = store.subcontractors.get(rec["subcontractor_id"])
            if sub is not None:
                sub["late_ack_count"] += 1
                old_standing = sub["standing"]
                new_standing = old_standing
                if sub["late_ack_count"] >= 6:
                    new_standing = "SUSPENDED"
                elif sub["late_ack_count"] >= 3:
                    new_standing = "WATCH"
                if new_standing != old_standing:
                    sub["standing"] = new_standing
                    ev_type = (
                        "SUBCONTRACTOR_SUSPENDED" if new_standing == "SUSPENDED"
                        else "SUBCONTRACTOR_WATCH"
                    )
                    append_escalation_event(
                        pid, ev_type, "SUBCONTRACTOR", sub["id"],
                        "standing %s -> %s (late_ack_count=%d)" % (
                            old_standing, new_standing, sub["late_ack_count"]),
                    )
                touch(sub)


def find_lli_for_submittal(submittal_id):
    for lli in store.long_lead_items.values():
        if lli["submittal_id"] == submittal_id:
            return lli
    return None


# ---------------------------------------------------------------------------
# Schedule-impact cascade on assessment accept (PRD 3.6)
# ---------------------------------------------------------------------------

def apply_schedule_cascade(project, rfi):
    """Every PLANNED activity on the RFI's submittal shifts +d calendar days;
    the submittal's required_on_site_date shifts; the LLI recomputes."""
    d = rfi.get("estimated_schedule_days") or 0
    if d <= 0:
        return
    submittal_id = rfi.get("submittal_id")
    if not submittal_id:
        return
    delta = timedelta(days=d)
    # Shift PLANNED activities
    for act in store.installation_activities.values():
        if act["project_id"] != project["id"]:
            continue
        if act["submittal_id"] != submittal_id:
            continue
        if act["status"] != "PLANNED":
            continue
        act["start_date"] = act["start_date"] + delta
        act["end_date"] = act["end_date"] + delta
        act["shift_applied_days"] += d
        touch(act)
    # Shift submittal dates
    submittal = store.submittals.get(submittal_id)
    if submittal is None:
        return
    if submittal.get("required_on_site_date") is not None:
        submittal["required_on_site_date"] = submittal["required_on_site_date"] + delta
    section = store.spec_sections.get(submittal["spec_section_id"])
    if section is not None:
        calc.recompute_submittal_dates(submittal, section, project)
    touch(submittal)
    # LLI recompute
    lli = find_lli_for_submittal(submittal_id)
    if lli is not None and lli["status"] not in ("DELIVERED", "CANCELLED"):
        lli["required_on_site_date"] = submittal.get("required_on_site_date")
        recompute_lli_with_events(lli, submittal)
        touch(lli)
    elif lli is not None:
        # keep mirror in sync even for terminal items
        lli["required_on_site_date"] = submittal.get("required_on_site_date")
