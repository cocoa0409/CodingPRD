"""Business logic: calculations, cascades, sweeps."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from core import now, touch

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_FEE_CENTS = {
    "EXEMPT": 50000,
    "EXPEDITED": 150000,
    "FULL_BOARD": 250000,
}
RELIANCE_SITE_FEE_CENTS = 74999
INDUSTRY_MULTIPLIER = Decimal("1.5")

BASE_SCORE = 100
CONFIRMED_DEDUCTION = 20
OPEN_CASE_DEDUCTION = 5
LATE_UNFILED_DEDUCTION = 8
DEBARMENT_THRESHOLD = 60
SUBMISSION_GATE = 60

ASSIGNMENT_RESPONSE_WINDOW_DAYS = 7
MAX_ACTIVE_ASSIGNMENTS = 5
MEETING_START_GRACE_MINUTES = 30
AGENDA_CAPACITY = 8

STANDARD_INTERVAL_DAYS = 365
HIGH_RISK_INTERVAL_DAYS = 180
CR_SUBMISSION_WINDOW_DAYS = 60

AE_WINDOW_DAYS = {
    "SERIOUS_ADVERSE_EVENT": 5,
    "UNANTICIPATED_PROBLEM": 5,
    "PROTOCOL_DEVIATION_WITH_HARM": 15,
}

PROTOCOL_TERMINAL = {"DISAPPROVED", "WITHDRAWN", "CLOSED"}
OPEN_CASE_STATUSES = {"OPENED", "INVESTIGATION", "FINDING_CONFIRMED"}


def round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fee_multiplier(protocol):
    return INDUSTRY_MULTIPLIER if protocol.get("is_industry_sponsored") else Decimal("1.0")


def fee_line(base_cents, multiplier):
    return round_half_up_cents(Decimal(base_cents) * multiplier)


def provisional_fee(protocol):
    return fee_line(BASE_FEE_CENTS[protocol["claimed_review_level"]],
                    fee_multiplier(protocol))


def settled_base_fee(protocol):
    return fee_line(BASE_FEE_CENTS[protocol["determined_review_level"]],
                    fee_multiplier(protocol))


def reliance_site_fee(protocol):
    return fee_line(RELIANCE_SITE_FEE_CENTS, fee_multiplier(protocol))


# ---------------------------------------------------------------------------
# Compliance scores
# ---------------------------------------------------------------------------

def investigator_protocol_ids(investigator_id):
    return [p["id"] for p in db.protocols.values()
            if p.get("pi_id") == investigator_id]


def recompute_investigator_scores(investigator_id):
    inv = db.investigators.get(investigator_id)
    if inv is None:
        return
    pids = set(investigator_protocol_ids(investigator_id))
    cases = [c for c in db.non_compliance_cases.values()
             if c.get("protocol_id") in pids]
    confirmed = sum(1 for c in cases
                    if c.get("finding_confirmed") is True
                    and c.get("status") in ("FINDING_CONFIRMED", "CLOSED"))
    open_cases = sum(1 for c in cases
                     if c.get("status") in ("OPENED", "INVESTIGATION"))
    late_unfiled = sum(1 for a in db.adverse_events.values()
                       if a.get("protocol_id") in pids
                       and a.get("is_late") is True
                       and a.get("status") == "FILED")
    final = BASE_SCORE - CONFIRMED_DEDUCTION * confirmed
    provisional = (final
                   - OPEN_CASE_DEDUCTION * open_cases
                   - LATE_UNFILED_DEDUCTION * late_unfiled)
    inv["final_compliance_score"] = final
    inv["provisional_compliance_score"] = provisional
    if final < DEBARMENT_THRESHOLD:
        inv["status"] = "DEBARRED"
    touch(inv)


# ---------------------------------------------------------------------------
# Member active assignment count
# ---------------------------------------------------------------------------

def recompute_member_assignment_count(member_id):
    m = db.irb_members.get(member_id)
    if m is None:
        return
    m["active_assignment_count"] = sum(
        1 for a in db.review_assignments.values()
        if a.get("reviewer_id") == member_id
        and a.get("status") in ("OFFERED", "ACCEPTED"))
    touch(m)


# ---------------------------------------------------------------------------
# Meeting item_count
# ---------------------------------------------------------------------------

def recompute_meeting_item_count(meeting_id):
    m = db.board_meetings.get(meeting_id)
    if m is None:
        return
    m["item_count"] = sum(
        1 for it in db.agenda_items.values()
        if it.get("meeting_id") == meeting_id and it.get("status") == "LISTED")
    touch(m)


# ---------------------------------------------------------------------------
# Suspension cascade (shared by issue-finding CONFIRMED and AE disposition)
# ---------------------------------------------------------------------------

def suspend_protocol(protocol):
    """Protocol must be in APPROVED or EXEMPT_ACTIVE."""
    protocol["pre_suspension_state"] = protocol["status"]
    protocol["status"] = "SUSPENDED"
    touch(protocol)
    # Link 2a: reliance agreements EXECUTED -> SUSPENDED
    for ra in db.reliance_agreements.values():
        if ra.get("protocol_id") == protocol["id"] and ra.get("status") == "EXECUTED":
            ra["status"] = "SUSPENDED"
            touch(ra)
    # Link 2b: LISTED agenda items on SCHEDULED meetings -> REMOVED
    affected_meetings = set()
    for it in db.agenda_items.values():
        if it.get("protocol_id") != protocol["id"] or it.get("status") != "LISTED":
            continue
        meeting = db.board_meetings.get(it.get("meeting_id"))
        if meeting is not None and meeting.get("status") == "SCHEDULED":
            it["status"] = "REMOVED"
            touch(it)
            affected_meetings.add(meeting["id"])
    # Link 3: meetings whose item_count falls to 0 -> CANCELLED
    for mid in affected_meetings:
        recompute_meeting_item_count(mid)
        meeting = db.board_meetings[mid]
        if meeting.get("status") == "SCHEDULED" and meeting.get("item_count") == 0:
            meeting["status"] = "CANCELLED"
            touch(meeting)


def reinstate_protocol(protocol):
    target = protocol.get("pre_suspension_state")
    protocol["status"] = target
    protocol["pre_suspension_state"] = None
    touch(protocol)
    for ra in db.reliance_agreements.values():
        if ra.get("protocol_id") == protocol["id"] and ra.get("status") == "SUSPENDED":
            ra["status"] = "EXECUTED"
            touch(ra)


def open_case(protocol, source, reason=None):
    case_fields = {
        "protocol_id": protocol["id"],
        "source": source,
        "reason": reason,
        "opened_at": None,  # filled below via fmt in new_record? opened_at uses logical now
        "finding_confirmed": None,
        "status": "OPENED",
    }
    from core import new_record, fmt_iso
    case_fields["opened_at"] = fmt_iso(now())
    case = new_record(case_fields)
    db.non_compliance_cases[case["id"]] = case
    return case


def create_continuing_review(protocol, cycle_index, due_at):
    from core import new_record, fmt_iso
    window = due_at - timedelta(days=CR_SUBMISSION_WINDOW_DAYS)
    cr = new_record({
        "protocol_id": protocol["id"],
        "cycle_index": cycle_index,
        "due_at": fmt_iso(due_at),
        "window_opens_at": fmt_iso(window),
        "submitted_at": None,
        "status": "PENDING_SUBMISSION",
    })
    db.continuing_reviews[cr["id"]] = cr
    return cr


def approve_protocol(protocol, instant):
    """Shared approval side effects (expedited + board)."""
    interval = HIGH_RISK_INTERVAL_DAYS \
        if protocol.get("risk_level") == "GREATER_THAN_MINIMAL" \
        else STANDARD_INTERVAL_DAYS
    protocol["continuing_review_interval_days"] = interval
    expires = instant + timedelta(days=interval)
    from core import fmt_iso
    protocol["approval_expires_at"] = fmt_iso(expires)
    protocol["status"] = "APPROVED"
    touch(protocol)
    create_continuing_review(protocol, 1, expires)


def has_conflict(reviewer_id, protocol_id):
    return any(
        d for d in db.conflict_declarations.values()
        if d.get("protocol_id") == protocol_id
        and d.get("reviewer_id") == reviewer_id
        and d.get("status") == "CONFLICTED")


def open_cases_for_protocol(protocol_id):
    return [c for c in db.non_compliance_cases.values()
            if c.get("protocol_id") == protocol_id
            and c.get("status") in OPEN_CASE_STATUSES]


def approved_consent_exists(protocol_id):
    return any(d for d in db.consent_documents.values()
               if d.get("protocol_id") == protocol_id
               and d.get("status") == "APPROVED")


def submitted_recommendations(protocol_id):
    return [a for a in db.review_assignments.values()
            if a.get("protocol_id") == protocol_id
            and a.get("status") == "SUBMITTED"
            and a.get("recommendation_voided") is not True]


# ---------------------------------------------------------------------------
# Clock sweep
# ---------------------------------------------------------------------------

def run_sweep():
    """Returns (lapsed_continuing_reviews, failed_quorum_meetings, expired_assignments)."""
    from core import parse_iso
    current = now()
    lapsed = 0
    failed = 0
    expired = 0

    # 1. Lapse due continuing reviews
    for cr in list(db.continuing_reviews.values()):
        if cr.get("status") not in ("PENDING_SUBMISSION", "SUBMITTED"):
            continue
        due_at = parse_iso(cr["due_at"], "due_at")
        if due_at < current:
            cr["status"] = "LAPSED"
            touch(cr)
            lapsed += 1
            protocol = db.protocols.get(cr.get("protocol_id"))
            if protocol is not None:
                # link 1: protocol APPROVED -> EXPIRED
                if protocol.get("status") == "APPROVED":
                    protocol["status"] = "EXPIRED"
                    touch(protocol)
                # link 2: open LAPSED_CR case
                open_case(protocol, "LAPSED_CR")
                # link 3: investigator provisional score recompute
                recompute_investigator_scores(protocol.get("pi_id"))

    # 2. Fail meetings past grace
    for m in list(db.board_meetings.values()):
        if m.get("status") != "SCHEDULED":
            continue
        start = parse_iso(m["scheduled_at"], "scheduled_at")
        if start + timedelta(minutes=MEETING_START_GRACE_MINUTES) < current:
            m["status"] = "FAILED_QUORUM"
            touch(m)
            failed += 1

    # 3. Expire stale OFFERED assignments
    for a in list(db.review_assignments.values()):
        if a.get("status") != "OFFERED":
            continue
        deadline = parse_iso(a["response_deadline_at"], "response_deadline_at")
        if deadline < current:
            a["status"] = "EXPIRED"
            touch(a)
            expired += 1
            recompute_member_assignment_count(a.get("reviewer_id"))

    return lapsed, failed, expired
