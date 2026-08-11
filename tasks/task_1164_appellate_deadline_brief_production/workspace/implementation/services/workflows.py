"""Cross-entity cascades: posture transitions, auto-creations, deadline
recomputation. Implements PRD §3 workflows and SCAFFOLD §1.2 state machines.
"""
from db import STORE, now_iso, new_id, parse_iso, fmt_iso
from errors import ApiError
from services.core import (
    new_entity, touch, add_calendar_days, roll_forward,
    record_for_case, schedule_for_case, toa_for_brief,
    transcripts_for_record, briefs_for_schedule, deadlines_for_case,
    recompute_record_completeness, recompute_toa_counts,
    compute_schedule_dates, granted_motions_for_schedule,
    schedule_due_for_brief_type, court_for_case,
    BRIEF_TYPE_TO_DEADLINE_KIND, DEFAULT_OPENING_DAYS, DEFAULT_RESPONSE_DAYS,
)


# ---------------------------------------------------------------------------
# Notice-of-appeal deadline (SCAFFOLD calc: notice_of_appeal_deadline)
# ---------------------------------------------------------------------------

def compute_notice_provisional(judgment_iso, court):
    prov = add_calendar_days(judgment_iso, court["appeal_deadline_days"])
    if court.get("weekend_holiday_rollforward"):
        prov = roll_forward(prov)
    return prov


def create_deadline(case_id, kind, basis_event_id, provisional_due_at):
    d = new_entity({
        "case_id": case_id,
        "kind": kind,
        "basis_event_id": basis_event_id,
        "provisional_due_at": provisional_due_at,
        "final_due_at": provisional_due_at,
        "tolled": False,
        "met": False,
        "met_at": None,
    })
    STORE.deadlines[d["id"]] = d
    return d


# ---------------------------------------------------------------------------
# Case posture helpers
# ---------------------------------------------------------------------------

def set_case_posture(case, posture):
    if case.get("posture") != posture:
        case["posture"] = posture
        touch(case)


def maybe_close_case(case):
    """DECIDED -> CLOSED when mandate reached and no DRAFT/FILED petitions (PRD §3.8)."""
    if case.get("posture") != "DECIDED":
        return
    decisions = [d for d in STORE.decisions.values() if d["case_id"] == case["id"]]
    if not decisions:
        return
    decision = sorted(decisions, key=lambda d: (d.get("_seq", 0)))[-1]
    mandate_at = decision.get("mandate_at")
    if not mandate_at:
        return
    pending = [p for p in STORE.petitions.values()
               if p["case_id"] == case["id"] and p["status"] in ("DRAFT", "FILED")]
    if pending:
        return
    if parse_iso(now_iso()) >= parse_iso(mandate_at):
        set_case_posture(case, "CLOSED")


# ---------------------------------------------------------------------------
# Case creation (PRD §3.2)
# ---------------------------------------------------------------------------

def open_case(body):
    from services.core import fk_court, fk_attorney, req_enum, req_str
    court = fk_court(body.get("court_id"))
    docket = req_str(body, "docket_number")
    caption = req_str(body, "caption")
    lead = fk_attorney(body.get("lead_attorney_id"), "lead_attorney_id")
    side = req_enum(body, "appellant_side", ("APPELLANT", "APPELLEE", "CROSS_APPELLANT"))
    from services.core import req_iso
    judgment_iso = req_iso(body, "judgment_entered_at")

    # Uniqueness: docket_number unique within court (PRD §3.2)
    for c in STORE.cases.values():
        if c["court_id"] == court["id"] and c["docket_number"] == docket:
            raise ApiError("ERR_DUPLICATE",
                           "docket_number already exists within this court", 409)

    case = new_entity({
        "court_id": court["id"],
        "docket_number": docket,
        "caption": caption,
        "lead_attorney_id": lead["id"],
        "appellant_side": side,
        "posture": "OPEN",
        "notice_filed_at": None,
        "judgment_entered_at": judgment_iso,
    })
    STORE.cases[case["id"]] = case

    # Auto-create JUDGMENT_ENTERED event
    ev = new_entity({
        "case_id": case["id"],
        "event_type": "JUDGMENT_ENTERED",
        "occurred_at": judgment_iso,
        "notes": "",
    })
    STORE.events[ev["id"]] = ev

    # Auto-create NOTICE_OF_APPEAL deadline
    prov = compute_notice_provisional(judgment_iso, court)
    create_deadline(case["id"], "NOTICE_OF_APPEAL", ev["id"], prov)
    return case


# ---------------------------------------------------------------------------
# Appeal event logging (PRD §3.2)
# ---------------------------------------------------------------------------

EVENT_TYPES = (
    "JUDGMENT_ENTERED", "NOTICE_FILED", "POST_JUDGMENT_MOTION_FILED",
    "POST_JUDGMENT_MOTION_DECIDED", "RECORD_COMPLETE", "BRIEF_FILED",
    "DECISION_ISSUED",
)


def log_event(case, body):
    from services.core import req_enum, req_iso, opt_str
    etype = req_enum(body, "event_type", EVENT_TYPES)
    occurred = req_iso(body, "occurred_at")
    notes = opt_str(body, "notes", "") or ""

    ev = new_entity({
        "case_id": case["id"],
        "event_type": etype,
        "occurred_at": occurred,
        "notes": notes,
    })
    STORE.events[ev["id"]] = ev

    noa_deadlines = [d for d in STORE.deadlines.values()
                     if d["case_id"] == case["id"] and d["kind"] == "NOTICE_OF_APPEAL"
                     and not d["met"]]

    if etype == "POST_JUDGMENT_MOTION_FILED":
        for d in noa_deadlines:
            if not d["tolled"]:
                d["tolled"] = True
                touch(d)
    elif etype == "POST_JUDGMENT_MOTION_DECIDED":
        # Find most recent POST_JUDGMENT_MOTION_FILED before this decided event
        filed_events = [e for e in STORE.events.values()
                        if e["case_id"] == case["id"]
                        and e["event_type"] == "POST_JUDGMENT_MOTION_FILED"
                        and parse_iso(e["occurred_at"]) < parse_iso(occurred)]
        if filed_events:
            latest = max(filed_events, key=lambda e: parse_iso(e["occurred_at"]))
            delta = parse_iso(occurred) - parse_iso(latest["occurred_at"])
            for d in noa_deadlines:
                new_final = fmt_iso(parse_iso(d["provisional_due_at"]) + delta)
                changed = (d["final_due_at"] != new_final) or d["tolled"]
                d["final_due_at"] = new_final
                d["tolled"] = False
                if changed:
                    touch(d)
    return ev


# ---------------------------------------------------------------------------
# Record / transcript cascades (PRD §3.3)
# ---------------------------------------------------------------------------

def maybe_complete_record(record):
    """ASSEMBLING -> COMPLETE when no ORDERED/IN_PREPARATION remain and at
    least one DELIVERED/FILED exists (SCAFFOLD Record machine)."""
    if record["status"] != "ASSEMBLING":
        return
    orders = transcripts_for_record(record["id"])
    active = [o for o in orders if o["status"] in ("ORDERED", "IN_PREPARATION")]
    delivered = [o for o in orders if o["status"] in ("DELIVERED", "FILED")]
    if active or not delivered:
        return
    record["status"] = "COMPLETE"
    record["completeness_pct"] = 100
    record["completed_at"] = now_iso()
    touch(record)

    case = STORE.cases.get(record["case_id"])
    if not case:
        return
    schedule = schedule_for_case(case["id"])
    # Schedule activates on record completion (PRD §3.4)
    if schedule and schedule["status"] == "PENDING":
        activate_schedule(schedule, record, case)
    # Posture: RECORD_PENDING -> BRIEFING when briefing schedule exists
    if case.get("posture") == "RECORD_PENDING" and schedule:
        set_case_posture(case, "BRIEFING")
        create_briefing_deadlines(case, schedule)


def activate_schedule(schedule, record, case):
    """PENDING -> ACTIVE; compute the three dates forward-anchored on record
    completion instant (PRD §3.4)."""
    court = court_for_case(case)
    anchor = record.get("completed_at") or now_iso()
    opening, response, reply = compute_schedule_dates(
        anchor, court, granted_motions_for_schedule(schedule["id"]))
    schedule["opening_due_at"] = opening
    schedule["response_due_at"] = response
    schedule["reply_due_at"] = reply
    schedule["status"] = "ACTIVE"
    touch(schedule)
    # Re-derive due_at for briefs under this schedule
    for b in briefs_for_schedule(schedule["id"]):
        b["due_at"] = schedule_due_for_brief_type(schedule, b["brief_type"])
        touch(b)


def create_briefing_deadlines(case, schedule):
    existing = {d["kind"] for d in deadlines_for_case(case["id"])}
    specs = (
        ("OPENING_BRIEF", schedule.get("opening_due_at")),
        ("RESPONSE_BRIEF", schedule.get("response_due_at")),
        ("REPLY_BRIEF", schedule.get("reply_due_at")),
    )
    for kind, due in specs:
        if kind in existing or not due:
            continue
        create_deadline(case["id"], kind, None, due)


# ---------------------------------------------------------------------------
# Briefing schedule completion check (PRD §3.4)
# ---------------------------------------------------------------------------

def maybe_complete_schedule(schedule):
    if schedule["status"] != "ACTIVE":
        return
    briefs = briefs_for_schedule(schedule["id"])
    opening_ok = any(b["brief_type"] == "OPENING" and b["status"] == "ACCEPTED" for b in briefs)
    response_ok = any(b["brief_type"] == "RESPONSE" and b["status"] == "ACCEPTED" for b in briefs)
    reply_ok = any(b["brief_type"] == "REPLY" and b["status"] == "ACCEPTED" for b in briefs)
    reply_due = schedule.get("reply_due_at")
    reply_window_expired = bool(reply_due) and parse_iso(now_iso()) > parse_iso(reply_due)
    if opening_ok and response_ok and (reply_ok or reply_window_expired):
        schedule["status"] = "COMPLETE"
        touch(schedule)
        case = STORE.cases.get(schedule["case_id"])
        if case and case.get("posture") == "BRIEFING":
            set_case_posture(case, "ARGUMENT_PENDING")
            # Auto-create oral argument in REQUESTED
            oa = new_entity({
                "case_id": case["id"],
                "scheduled_start": None,
                "duration_minutes": None,
                "panel_judges": [],
                "moot_completed": False,
                "status": "REQUESTED",
            })
            STORE.oral_arguments[oa["id"]] = oa


def reconcile_case(case):
    """Evaluate the clock-driven rules that time alone can trigger (PRD §2.5:
    advancing the clock "changes only what 'now' means for every rule evaluated
    afterwards"; §3.8: posture is "always readable as the case's computed
    posture"). Runs the ACTIVE -> COMPLETE schedule completion (§3.4, which
    drives posture BRIEFING -> ARGUMENT_PENDING and auto-creates the oral
    argument) and the DECIDED -> CLOSED mandate closure (§3.8)."""
    if case is None:
        return
    for s in list(STORE.briefing_schedules.values()):
        if s["case_id"] == case["id"] and s["status"] == "ACTIVE":
            maybe_complete_schedule(s)
    maybe_close_case(case)


# ---------------------------------------------------------------------------
# Filing creation + acceptance cascades (PRD §3.6)
# ---------------------------------------------------------------------------

FILING_TYPES = (
    "NOTICE_OF_APPEAL", "RECORD", "BRIEF", "EXTENSION_MOTION",
    "REHEARING_PETITION", "CERT_PETITION",
)
FILING_METHODS = ("EFILE", "PAPER", "HAND")


def create_filing(case, filing_type, method, served_emails, brief_id=None):
    from db import new_confirmation_number
    f = new_entity({
        "case_id": case["id"],
        "brief_id": brief_id,
        "filing_type": filing_type,
        "method": method,
        "served_party_emails": list(served_emails or []),
        "filed_at": now_iso(),
        "confirmation_number": new_confirmation_number() if method == "EFILE" else None,
        "status": "SUBMITTED",
    })
    STORE.filings[f["id"]] = f
    return f


def accept_filing(filing):
    """Filing SUBMITTED -> ACCEPTED with per-type cascades (PRD §3.6)."""
    filing["status"] = "ACCEPTED"
    touch(filing)
    case = STORE.cases.get(filing["case_id"])
    ftype = filing["filing_type"]

    if ftype == "BRIEF" and filing.get("brief_id"):
        brief = STORE.briefs.get(filing["brief_id"])
        if brief and brief["status"] == "EFILED":
            brief["status"] = "ACCEPTED"
            touch(brief)
            # Mark corresponding deadline met
            kind = BRIEF_TYPE_TO_DEADLINE_KIND.get(brief["brief_type"])
            if kind:
                for d in deadlines_for_case(case["id"]):
                    if d["kind"] == kind and not d["met"]:
                        d["met"] = True
                        d["met_at"] = now_iso()
                        touch(d)
                        break
            # Response brief accepted -> reply window opens (already reflected in
            # schedule.reply_due_at; nothing to shift — anchoring already done).
            # Check schedule completion
            schedule = STORE.briefing_schedules.get(brief["schedule_id"])
            if schedule:
                maybe_complete_schedule(schedule)

    elif ftype == "NOTICE_OF_APPEAL":
        if case and case.get("posture") == "OPEN":
            case["notice_filed_at"] = filing["filed_at"]
            set_case_posture(case, "RECORD_PENDING")
            # Auto-create Record (1:1) — ERR_DUPLICATE if one exists
            if record_for_case(case["id"]) is not None:
                raise ApiError("ERR_DUPLICATE", "Case already has a record", 409)
            rec = new_entity({
                "case_id": case["id"],
                "designation_due_at": None,
                "designated_at": None,
                "status": "PENDING_DESIGNATION",
                "completeness_pct": 0,
            })
            STORE.records[rec["id"]] = rec
            # Auto-create BriefingSchedule (1:1)
            if schedule_for_case(case["id"]) is not None:
                raise ApiError("ERR_DUPLICATE", "Case already has a briefing schedule", 409)
            sched = new_entity({
                "case_id": case["id"],
                "opening_due_at": None,
                "response_due_at": None,
                "reply_due_at": None,
                "extensions_granted_count": 0,
                "status": "PENDING",
            })
            STORE.briefing_schedules[sched["id"]] = sched
            # Record-phase deadlines
            existing = {d["kind"] for d in deadlines_for_case(case["id"])}
            if "RECORD_DESIGNATION" not in existing:
                create_deadline(case["id"], "RECORD_DESIGNATION", None, filing["filed_at"])
            if "TRANSCRIPT_ORDER" not in existing:
                create_deadline(case["id"], "TRANSCRIPT_ORDER", None, filing["filed_at"])

    elif ftype == "RECORD":
        rec = record_for_case(filing["case_id"])
        if rec and rec["status"] == "COMPLETE":
            rec["status"] = "FILED"
            touch(rec)

    elif ftype in ("REHEARING_PETITION", "CERT_PETITION"):
        # Petition transitions DRAFT->FILED via petitions/{id}/file which creates
        # this filing. On acceptance the petition stays FILED (already filed).
        pass


def reject_filing(filing):
    """Filing SUBMITTED -> REJECTED; brief filings compensate EFILED -> DRAFT."""
    filing["status"] = "REJECTED"
    touch(filing)
    if filing["filing_type"] == "BRIEF" and filing.get("brief_id"):
        brief = STORE.briefs.get(filing["brief_id"])
        if brief and brief["status"] == "EFILED":
            brief["status"] = "DRAFT"
            touch(brief)


# ---------------------------------------------------------------------------
# Decision entry (PRD §3.8)
# ---------------------------------------------------------------------------

def enter_decision(case, body):
    from services.core import req_enum, req_iso
    outcome = req_enum(body, "outcome",
                       ("AFFIRMED", "REVERSED", "REMANDED", "DISMISSED", "MIXED"))
    issued = req_iso(body, "issued_at")
    court = court_for_case(case)

    # rehearing_deadline per jurisdiction
    window = 14 if court["jurisdiction_type"] == "FEDERAL" else 30
    rehearing_deadline = add_calendar_days(issued, window)
    # mandate issues after rehearing window closes (no separate court field;
    # anchor at rehearing deadline per PRD §3.8 "once the rehearing window has closed")
    mandate_at = rehearing_deadline

    dec = new_entity({
        "case_id": case["id"],
        "outcome": outcome,
        "issued_at": issued,
        "mandate_at": mandate_at,
        "rehearing_deadline_at": rehearing_deadline,
    })
    STORE.decisions[dec["id"]] = dec

    if case.get("posture") == "ARGUMENT_PENDING":
        set_case_posture(case, "DECIDED")

    # Auto-create REHEARING_PETITION and CERT_PETITION deadlines
    existing = {d["kind"] for d in deadlines_for_case(case["id"])}
    if "REHEARING_PETITION" not in existing:
        create_deadline(case["id"], "REHEARING_PETITION", None, rehearing_deadline)
    if "CERT_PETITION" not in existing:
        cert_deadline = add_calendar_days(issued, 90)
        create_deadline(case["id"], "CERT_PETITION", None, cert_deadline)
    return dec


# ---------------------------------------------------------------------------
# Petition cascades (PRD §3.8)
# ---------------------------------------------------------------------------

def petition_due_at(petition_type, decision, court):
    issued = decision["issued_at"]
    if petition_type in ("REHEARING", "REHEARING_EN_BANC"):
        window = 14 if court["jurisdiction_type"] == "FEDERAL" else 30
        return add_calendar_days(issued, window)
    # CERTIORARI
    return add_calendar_days(issued, 90)


def grant_petition(petition):
    petition["status"] = "GRANTED"
    touch(petition)
    case = STORE.cases.get(petition["case_id"])
    if not case:
        return
    if petition["petition_type"] in ("REHEARING", "REHEARING_EN_BANC"):
        if case.get("posture") == "DECIDED":
            set_case_posture(case, "BRIEFING")
            sched = new_entity({
                "case_id": case["id"],
                "opening_due_at": None,
                "response_due_at": None,
                "reply_due_at": None,
                "extensions_granted_count": 0,
                "status": "PENDING",
            })
            STORE.briefing_schedules[sched["id"]] = sched
    elif petition["petition_type"] == "CERTIORARI":
        set_case_posture(case, "CLOSED")


def deny_petition(petition):
    petition["status"] = "DENIED"
    touch(petition)
    case = STORE.cases.get(petition["case_id"])
    if not case:
        return
    decisions = decisions_for_case_sorted(case["id"])
    if decisions:
        dec = decisions[-1]
        # mandate_at = now() + court.mandate_delay_days (default: use rehearing
        # window — no explicit court field; default 0 days means mandate now)
        court = court_for_case(case)
        delay = court.get("mandate_delay_days", 0) or 0
        dec["mandate_at"] = add_calendar_days(now_iso(), delay)
        touch(dec)
    pending = [p for p in STORE.petitions.values()
               if p["case_id"] == case["id"] and p["status"] in ("DRAFT", "FILED")]
    if not pending and case.get("posture") == "DECIDED":
        set_case_posture(case, "CLOSED")


def decisions_for_case_sorted(case_id):
    return sorted(
        [d for d in STORE.decisions.values() if d["case_id"] == case_id],
        key=lambda d: d.get("_seq", 0),
    )
