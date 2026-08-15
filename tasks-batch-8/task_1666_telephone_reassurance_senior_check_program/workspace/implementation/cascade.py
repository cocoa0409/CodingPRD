"""State-machine side effects: escalations, holds, regeneration, closeout,
call-log cascades, waitlist offers."""
from datetime import timedelta

from db import store, now, new_entity, touch
import calc
import timeutil
from timeutil import parse_hm, fmt_hm

TERMINAL_ESCALATION = {"RESOLVED_OK", "RESOLVED_CONTACT_CONFIRMED",
                       "RESOLVED_WITH_REFERRAL", "CLOSED_SUPERSEDED",
                       "CLOSED_FALSE_ALARM"}


def insert_assignment(p, volunteer_id, date, ws_min, we_min, source,
                      escalation_id=None, rescheduled_from_id=None):
    a = new_entity()
    a.update({
        "participant_id": p["id"],
        "volunteer_id": volunteer_id,
        "scheduled_date": date,
        "window_start": fmt_hm(ws_min),
        "window_end": fmt_hm(we_min),
        "source": source,
        "escalation_id": escalation_id,
        "rescheduled_from_id": rescheduled_from_id,
        "status": "SCHEDULED",
        "cancel_reason": None,
    })
    store.assignments[a["id"]] = a
    calc.recompute_coverage(p)
    return a


def cancel_assignment(a, reason):
    if a["status"] != "SCHEDULED":
        return
    a["status"] = "CANCELLED"
    a["cancel_reason"] = reason
    touch(a)
    p = store.participants.get(a["participant_id"])
    if p:
        calc.recompute_coverage(p)


def future_dated(a):
    return a["status"] == "SCHEDULED" and a["scheduled_date"] >= timeutil.today()


# ---------------- escalation lifecycle ----------------

def open_escalation(p, trigger, opened_by, prog, note=None):
    old = None
    if p.get("open_escalation_id"):
        cand = store.escalations.get(p["open_escalation_id"])
        if cand and cand["stage"] in calc.OPEN_STAGES:
            old = cand
    if old:
        old["stage"] = "CLOSED_SUPERSEDED"
        touch(old)
    e = new_entity()
    stage = "STEP_3_WELFARE" if trigger == "CONCERN_IMMEDIATE" else "STEP_1_RETRY"
    e.update({
        "participant_id": p["id"],
        "trigger_type": trigger,
        "stage": stage,
        "opened_by_user_id": opened_by,
        "opened_at": now(),
        "stage_entered_at": now(),
        "retry_assignment_id": None,
        "supersedes_escalation_id": old["id"] if old else None,
        "contact_attempts": [],
        "resolution_note": None,
        "_resolved_at": None,
        "_open_note": note,
    })
    store.escalations[e["id"]] = e
    p["open_escalation_id"] = e["id"]
    touch(p)
    if trigger == "CONCERN_IMMEDIATE":
        create_welfare_check(e, p)
        welfare_hold_cascade(p)
    return e


def create_welfare_check(e, p):
    w = new_entity()
    w.update({
        "escalation_id": e["id"],
        "participant_id": p["id"],
        "status": "REQUESTED",
        "disposition": "NONE",
        "requested_at": now(),
        "dispatched_at": None,
        "completed_at": None,
        "responder_note": None,
    })
    store.welfare[w["id"]] = w
    return w


def welfare_hold_cascade(p):
    if p["status"] != "ENROLLED":
        return
    p["status"] = "WELFARE_HOLD"
    p["last_status_change_at"] = now()
    for a in list(store.assignments.values()):
        if a["participant_id"] == p["id"] and future_dated(a):
            cancel_assignment(a, "WELFARE_HOLD")
    calc.recompute_coverage(p)
    touch(p)


def regenerate_assignments(p, prog):
    """One REGULAR assignment per ACTIVE schedule whose next occurrence falls
    within the coming 7 days; selector-staffed; empty pool -> deficient."""
    td = timeutil.today()
    deficient = False
    schedules = [s for s in store.schedules.values()
                 if s["participant_id"] == p["id"] and s["status"] == "ACTIVE"]
    for s in sorted(schedules, key=lambda x: (x["created_at"], x["_seq"])):
        target_wd = s["weekday"]
        occ = None
        for offset in range(7):
            d = td + timedelta(days=offset)
            if timeutil.weekday_of(d) == target_wd:
                occ = d
                break
        if occ is None:
            continue
        ws = parse_hm(s["window_start"])
        we = min(ws + 30, 1439)
        v = calc.selector(p, occ, ws, we, prog)
        if v is None:
            deficient = True
            continue
        insert_assignment(p, v["id"], occ, ws, we, "REGULAR")
    if deficient:
        p["coverage_deficient"] = True


def release_hold(p, prog):
    """WELFARE_HOLD -> ENROLLED cascade."""
    if p["status"] != "WELFARE_HOLD":
        return
    p["status"] = "ENROLLED"
    p["consecutive_no_answer_count"] = 0
    p["last_status_change_at"] = now()
    regenerate_assignments(p, prog)
    calc.recompute_coverage(p)
    touch(p)


def finalize_resolution(e, new_stage, prog, note=None):
    e["stage"] = new_stage
    if note is not None:
        e["resolution_note"] = note
    e["_resolved_at"] = now()
    touch(e)
    p = store.participants.get(e["participant_id"])
    if not p:
        return
    p["consecutive_no_answer_count"] = 0
    if p.get("open_escalation_id") == e["id"]:
        p["open_escalation_id"] = None
    touch(p)
    if p["status"] == "WELFARE_HOLD":
        release_hold(p, prog)


def advance_eligible(e, prog):
    clock = now()
    if e["stage"] == "STEP_1_RETRY":
        if e.get("retry_assignment_id"):
            for lg in store.logs.values():
                if (lg["assignment_id"] == e["retry_assignment_id"]
                        and lg["outcome"] in calc.NOANS_FAMILY):
                    return True
        return clock >= e["stage_entered_at"] + timedelta(hours=prog["escalation_retry_hours"])
    if e["stage"] == "STEP_2_CONTACT":
        attempted = {att["contact_id"] for att in e["contact_attempts"]}
        actives = [c for c in store.contacts.values()
                   if c["participant_id"] == e["participant_id"] and c["status"] == "ACTIVE"]
        if all(c["id"] in attempted for c in actives):
            return True
        return clock >= e["stage_entered_at"] + timedelta(hours=prog["contact_phase_hours"])
    return False


def advance_escalation(e, prog):
    """One step: STEP_1 -> STEP_2, or STEP_2 -> STEP_3 (with welfare check +
    hold cascade). Caller must have verified eligibility."""
    if e["stage"] == "STEP_1_RETRY":
        e["stage"] = "STEP_2_CONTACT"
        e["stage_entered_at"] = now()
        touch(e)
    elif e["stage"] == "STEP_2_CONTACT":
        e["stage"] = "STEP_3_WELFARE"
        e["stage_entered_at"] = now()
        touch(e)
        p = store.participants.get(e["participant_id"])
        create_welfare_check(e, p)
        if p:
            welfare_hold_cascade(p)


# ---------------- call-log cascades ----------------

def process_log_side_effects(a, lg, prog):
    p = store.participants[a["participant_id"]]
    outcome = lg["outcome"]
    if outcome in calc.REACHED_FAMILY:
        a["status"] = "COMPLETED"
        p["consecutive_no_answer_count"] = 0
    else:
        a["status"] = "UNREACHED"
        p["consecutive_no_answer_count"] += 1
    touch(a)
    touch(p)

    # Retry success auto-resolves the open STEP_1 case.
    if outcome in calc.REACHED_FAMILY and p.get("open_escalation_id"):
        e = store.escalations.get(p["open_escalation_id"])
        if (e and e["stage"] == "STEP_1_RETRY"
                and e.get("retry_assignment_id") == a["id"]):
            finalize_resolution(e, "RESOLVED_OK", prog)

    # No-answer streak threshold (inclusive) auto-opens the protocol case.
    if (outcome in calc.NOANS_FAMILY
            and p["consecutive_no_answer_count"] >= prog["no_answer_threshold"]
            and p.get("open_escalation_id") is None):
        e = open_escalation(p, "NO_ANSWER_PROTOCOL", "system", prog)
        called = lg["called_at"]
        ws = called.hour * 60 + called.minute
        we = min(ws + 30, 1439)
        v = calc.selector(p, called.date(), ws, we, prog)
        if v is not None:
            retry = insert_assignment(p, v["id"], called.date(), ws, we,
                                      "ESCALATION_RETRY", escalation_id=e["id"])
            e["retry_assignment_id"] = retry["id"]
            touch(e)

    # Immediate-danger fast path opens CONCERN_IMMEDIATE at STEP_3_WELFARE.
    if outcome == "REACHED_CONCERN" and lg["concern_level"] == "IMMEDIATE_DANGER":
        open_escalation(p, "CONCERN_IMMEDIATE", "system", prog)

    calc.recompute_coverage(p)


# ---------------- waitlist offers ----------------

def exit_waitlist_participant(entry):
    p = store.participants.get(entry["participant_id"])
    if p and p["status"] == "WAITLISTED":
        p["status"] = "EXITED"
        p["last_status_change_at"] = now()
        touch(p)


def promotion_run(prog):
    clock = now()
    occupied = calc.occupied_slots()
    entries = [e for e in store.waitlist.values() if e["status"] == "WAITING"]
    TIER_PTS = {"CRITICAL": 100, "HIGH": 70, "MODERATE": 40, "LOW": 10}
    SRC_PTS = {"APS_REFERRAL": 50, "HOSPITAL_DISCHARGE": 40, "OTHER_PROVIDER": 30,
               "FAMILY": 20, "SELF": 10}
    scored = []
    for e in entries:
        p = store.participants[e["participant_id"]]
        days = int((clock - e["waitlist_entered_at"]).total_seconds() // 86400)
        days = min(max(days, 0), 30)
        raw = (TIER_PTS[p["acuity_tier"]] + SRC_PTS[p["referral_source"]]
               + 2 * days + (15 if p["lives_alone"] else 0))
        scored.append((e, p, raw))
    crit_wait = sum(1 for (_, p, _) in scored if p["acuity_tier"] == "CRITICAL")
    reserved = min(prog["max_reserve_slots"], crit_wait)
    gross_free = max(0, prog["total_capacity"] - occupied)
    noncrit_budget = max(0, gross_free - reserved)
    pressure = occupied * 100 >= 95 * prog["total_capacity"]
    ranked = []
    for e, p, raw in scored:
        final = raw + (30 if pressure and p["acuity_tier"] == "CRITICAL" else 0)
        ranked.append((e, p, final))
    ranked.sort(key=lambda t: (-t[2], t[0]["waitlist_entered_at"],
                               t[1]["created_at"], t[1]["_seq"]))
    gf_rem, nc_rem = gross_free, noncrit_budget
    offered = []
    for e, p, final in ranked:
        if p["acuity_tier"] == "CRITICAL":
            if gf_rem >= 1:
                gf_rem -= 1
                offered.append((e, final))
        else:
            if nc_rem >= 1:
                nc_rem -= 1
                offered.append((e, final))
    for e, final in offered:
        e["status"] = "OFFERED"
        e["offered_at"] = clock
        e["offer_expires_at"] = clock + timedelta(hours=prog["offer_ttl_hours"])
        e["priority_score_at_offer"] = final
        touch(e)
    prog["promotion_epoch"] += 1
    touch(prog)
    return {
        "epoch": prog["promotion_epoch"],
        "offers_created": len(offered),
        "offered_entry_ids": [e["id"] for e, _ in offered],
        "gross_free_after": gross_free - len(offered),
    }


# ---------------- daily closeout ----------------

def daily_closeout(prog):
    clock = now()
    td = clock.date()

    expired_assignment_ids = []
    for a in sorted(store.assignments.values(), key=lambda x: (x["created_at"], x["_seq"])):
        if a["status"] != "SCHEDULED" or a["scheduled_date"] >= td:
            continue
        if any(lg["assignment_id"] == a["id"] for lg in store.logs.values()):
            continue
        a["status"] = "EXPIRED"
        touch(a)
        expired_assignment_ids.append(a["id"])
        p = store.participants.get(a["participant_id"])
        if p:
            calc.recompute_coverage(p)

    expired_offer_entry_ids = []
    for e in sorted(store.waitlist.values(), key=lambda x: (x["created_at"], x["_seq"])):
        if e["status"] != "OFFERED" or e["offer_expires_at"] is None:
            continue
        if not (clock > e["offer_expires_at"]):
            continue
        expired_offer_entry_ids.append(e["id"])
        e["expires_count"] += 1
        e["offered_at"] = None
        e["offer_expires_at"] = None
        if e["expires_count"] >= 2:
            e["status"] = "REMOVED"
            e["removal_reason"] = "MAX_EXPIRES"
            touch(e)
            exit_waitlist_participant(e)
        else:
            e["status"] = "WAITING"
            touch(e)

    # Agreement expiry (clock strictly past valid_until) flips status first.
    for ag in store.agreements.values():
        if ag["status"] == "ACTIVE" and clock > ag["valid_until"]:
            ag["status"] = "EXPIRED"
            touch(ag)

    lapsed_volunteer_ids = []
    for v in sorted(store.volunteers.values(), key=lambda x: (x["created_at"], x["_seq"])):
        if v["status"] != "ACTIVE":
            continue
        if calc.training_current(v) and calc.agreement_current(v, prog):
            continue
        v["status"] = "LAPSED"
        touch(v)
        lapsed_volunteer_ids.append(v["id"])
        for a in list(store.assignments.values()):
            if a.get("volunteer_id") == v["id"] and future_dated(a):
                cancel_assignment(a, "VOLUNTEER_LAPSED")

    expired_survey_ids = []
    for s in sorted(store.surveys.values(), key=lambda x: (x["created_at"], x["_seq"])):
        if s["status"] != "ISSUED":
            continue
        if clock > s["issued_at"] + timedelta(days=prog["survey_valid_days"]):
            s["status"] = "EXPIRED"
            touch(s)
            expired_survey_ids.append(s["id"])

    advanced_escalation_ids = []
    for e in sorted(store.escalations.values(), key=lambda x: (x["created_at"], x["_seq"])):
        if e["stage"] not in ("STEP_1_RETRY", "STEP_2_CONTACT"):
            continue
        if advance_eligible(e, prog):
            advance_escalation(e, prog)
            advanced_escalation_ids.append(e["id"])

    for p in store.participants.values():
        if p["status"] in ("ENROLLED", "SUSPENDED", "WELFARE_HOLD"):
            calc.compute_rolling(p)

    touch(prog)
    return {
        "expired_assignment_ids": expired_assignment_ids,
        "expired_offer_entry_ids": expired_offer_entry_ids,
        "lapsed_volunteer_ids": lapsed_volunteer_ids,
        "expired_survey_ids": expired_survey_ids,
        "advanced_escalation_ids": advanced_escalation_ids,
    }
