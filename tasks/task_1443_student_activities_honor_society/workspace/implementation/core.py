"""Shared helpers: nested fetchers, freeze guard, recomputation pipeline,
derived fields, athletics overlap, and common payload validation."""

from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
from db import (academic_year_of, iso, new_id, next_seq, now, now_iso, parse_dt,
                semester_of)
from errors import (ERR_ATHLETICS_CONFLICT, ERR_CHAPTER_FROZEN, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_NOT_AN_OFFICER, ApiError)

# ---------------------------------------------------------------------------
# record plumbing
# ---------------------------------------------------------------------------

def new_record(fields):
    rec = dict(fields)
    rec["id"] = new_id()
    ts = now_iso()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """Every mutation (direct write, cascade, or derived-field recomputation)
    refreshes updated_at and increments version (PRD section 2.5)."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = now_iso()


# ---------------------------------------------------------------------------
# request body helpers
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field: {f}")


def as_int(value, field):
    if isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be an integer")


def as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be a number")
    return value


def as_str(value, field):
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be a string")
    return value


# ---------------------------------------------------------------------------
# nested fetchers (left-to-right existence / nesting validation, PRD 2.6)
# ---------------------------------------------------------------------------

def _get(store, rid, what):
    rec = store.get(rid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"{what} not found: {rid}")
    return rec


def get_chapter(chapter_id):
    return _get(db.chapters, chapter_id, "Chapter")


def get_member(ch, member_id):
    m = _get(db.members, member_id, "Member")
    if m["chapter_id"] != ch["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, f"Member not found: {member_id}")
    return m


def get_cycle(ch, cycle_id):
    c = _get(db.cycles, cycle_id, "MembershipCycle")
    if c["chapter_id"] != ch["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, f"MembershipCycle not found: {cycle_id}")
    return c


def get_application(cycle, application_id):
    a = _get(db.applications, application_id, "CycleApplication")
    if a["cycle_id"] != cycle["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, f"CycleApplication not found: {application_id}")
    return a


def get_entry(member, entry_id):
    e = _get(db.service_entries, entry_id, "ServiceHourEntry")
    if e["member_id"] != member["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, f"ServiceHourEntry not found: {entry_id}")
    return e


def get_election(ch, election_id):
    e = _get(db.elections, election_id, "OfficerElection")
    if e["chapter_id"] != ch["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, f"OfficerElection not found: {election_id}")
    return e


def get_vote(election, vote_id):
    v = _get(db.votes, vote_id, "ElectionVote")
    if v["election_id"] != election["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, f"ElectionVote not found: {vote_id}")
    return v


def get_role(ch, role_id):
    r = _get(db.officer_roles, role_id, "OfficerRole")
    if r["chapter_id"] != ch["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, f"OfficerRole not found: {role_id}")
    return r


def get_minutes(ch, minutes_id):
    m = _get(db.meeting_minutes, minutes_id, "MeetingMinutes")
    if m["chapter_id"] != ch["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, f"MeetingMinutes not found: {minutes_id}")
    return m


def get_fundraiser(ch, fundraiser_id):
    f = _get(db.fundraisers, fundraiser_id, "FundraiserRequest")
    if f["chapter_id"] != ch["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, f"FundraiserRequest not found: {fundraiser_id}")
    return f


def get_ledger_entry(ch, entry_id):
    e = _get(db.ledger_entries, entry_id, "FundLedgerEntry")
    if e["chapter_id"] != ch["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, f"FundLedgerEntry not found: {entry_id}")
    return e


def get_dues_payment(member, payment_id):
    p = _get(db.dues_payments, payment_id, "DuesPayment")
    if p["member_id"] != member["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, f"DuesPayment not found: {payment_id}")
    return p


def get_probation_case(member, case_id):
    c = _get(db.probation_cases, case_id, "ProbationCase")
    if c["member_id"] != member["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, f"ProbationCase not found: {case_id}")
    return c


def get_block(ch, block_id):
    b = _get(db.athletics_blocks, block_id, "AthleticsCalendarBlock")
    if b["chapter_id"] != ch["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, f"AthleticsCalendarBlock not found: {block_id}")
    return b


# ---------------------------------------------------------------------------
# chapter freeze guard (PRD 2.7)
# ---------------------------------------------------------------------------

def check_frozen(ch):
    if ch["status"] in ("SUSPENDED", "DISSOLVED"):
        raise ApiError(ERR_CHAPTER_FROZEN, 409,
                       f"Chapter is {ch['status']}; child mutations are frozen")


# ---------------------------------------------------------------------------
# officers
# ---------------------------------------------------------------------------

def caller_active_role(chapter_id, user_id, office=None):
    """Return the caller's ACTIVE OfficerRole in this chapter, else 403."""
    for r in db.officer_roles.values():
        if (r["chapter_id"] == chapter_id and r["member_id"] == user_id
                and r["status"] == "ACTIVE"
                and (office is None or r["office"] == office)):
            return r
    if office:
        raise ApiError(ERR_NOT_AN_OFFICER, 403,
                       f"Caller does not hold an ACTIVE {office} OfficerRole")
    raise ApiError(ERR_NOT_AN_OFFICER, 403, "Caller does not hold an ACTIVE OfficerRole")


# ---------------------------------------------------------------------------
# athletics overlap (half-open intervals, PRD 3.8)
# ---------------------------------------------------------------------------

def member_has_conflict(member_id, when):
    """True if the member has an ACTIVE block covering instant `when`:
    block_start <= when < block_end (adjacency is not a conflict)."""
    for b in db.athletics_blocks.values():
        if b["member_id"] != member_id or b["status"] != "ACTIVE":
            continue
        start = parse_dt(b["block_start"], "block_start")
        end = parse_dt(b["block_end"], "block_end")
        if start <= when < end:
            return True
    return False


def check_member_conflict(member_id, when):
    if member_has_conflict(member_id, when):
        raise ApiError(ERR_ATHLETICS_CONFLICT, 409,
                       "Member has an ACTIVE athletics block overlapping the relevant date")


# ---------------------------------------------------------------------------
# derived fields / recomputation pipeline
# ---------------------------------------------------------------------------

def annual_cumulative_compliant(member, chapter):
    return member["verified_service_hours_current_year"] >= chapter["service_hours_annual_required"]


def per_semester_strict_compliant(member, chapter):
    return (member["verified_service_hours_current_semester"] >= chapter["service_hours_per_semester_required"]
            and member["verified_service_hours_current_year"] >= chapter["service_hours_annual_required"])


def compute_good_standing(member, chapter):
    """Derived flag (PRD 3.3). A freshly registered PROSPECTIVE member starts
    false; DISMISSED is false; any OPEN/APPEALED probation case is false.
    The service-hour obligation (annual-cumulative reading) binds members who
    must *remain* in good standing (ACTIVE / ON_PROBATION)."""
    if member["status"] in ("DISMISSED", "PROSPECTIVE"):
        return False
    for c in db.probation_cases.values():
        if c["member_id"] == member["id"] and c["status"] in ("OPEN", "APPEALED"):
            return False
    if member["status"] in ("ACTIVE", "ON_PROBATION"):
        return annual_cumulative_compliant(member, chapter)
    return True


def recompute_member(member, touch_it=True):
    chapter = db.chapters[member["chapter_id"]]
    # probation strikes: RESOLVED cases with confirmed violation
    member["probation_strikes"] = sum(
        1 for c in db.probation_cases.values()
        if c["member_id"] == member["id"] and c["status"] == "RESOLVED"
        and c["outcome"] == "STANDARDS_VIOLATION_CONFIRMED")
    # officer flag
    member["is_officer"] = any(
        r["member_id"] == member["id"] and r["status"] == "ACTIVE"
        for r in db.officer_roles.values())
    # verified service aggregates over current academic year / semester
    clock = now()
    ay = academic_year_of(clock)
    sem = semester_of(clock)
    yr = Decimal(0)
    sem_total = Decimal(0)
    for e in db.service_entries.values():
        if e["member_id"] != member["id"] or e["status"] != "VERIFIED":
            continue
        d = parse_dt(e["service_date"], "service_date")
        if academic_year_of(d) != ay:
            continue
        h = Decimal(str(e["hours"]))
        yr += h
        if semester_of(d) == sem:
            sem_total += h
    member["verified_service_hours_current_year"] = float(yr)
    member["verified_service_hours_current_semester"] = float(sem_total)
    member["good_standing"] = compute_good_standing(member, chapter)
    if touch_it:
        touch(member)


def recompute_chapter(chapter, touch_it=True):
    """Roll-up order pinned by the calculations table: member count first,
    then dues arrears, then fund balance, then the standing ladder."""
    chapter["active_member_count"] = sum(
        1 for m in db.members.values()
        if m["chapter_id"] == chapter["id"] and m["status"] == "ACTIVE")
    ay = academic_year_of(now())
    remitted = sum(
        p["amount_cents"] for p in db.dues_payments.values()
        if p["chapter_id"] == chapter["id"] and p["academic_year"] == ay
        and p["status"] == "REMITTED")
    expected = chapter["national_dues_cents_per_member"] * chapter["active_member_count"]
    chapter["dues_arrears_cents"] = max(expected - remitted, 0)
    chapter["fund_balance_cents"] = sum(
        e["amount_cents"] for e in db.ledger_entries.values()
        if e["chapter_id"] == chapter["id"] and e["status"] == "CLEARED")
    if chapter["dues_arrears_cents"] > 30 * chapter["national_dues_cents_per_member"]:
        standing = "REVOKED"
    elif chapter["dues_arrears_cents"] > 0:
        standing = "PROBATIONARY"
    else:
        active = chapter["active_member_count"]
        on_prob = sum(
            1 for m in db.members.values()
            if m["chapter_id"] == chapter["id"] and m["status"] == "ON_PROBATION")
        standing = "PROBATIONARY" if (active > 0 and on_prob * 2 > active) else "GOOD_STANDING"
    chapter["standing"] = standing
    if touch_it:
        touch(chapter)


def cycle_candidate_ids(cycle):
    return [a["member_id"] for a in db.applications.values()
            if a["cycle_id"] == cycle["id"]
            and db.members[a["member_id"]]["status"] == "CANDIDATE"]


def cycle_inducted_count(cycle):
    return sum(1 for m in db.members.values() if m.get("inducted_cycle_id") == cycle["id"])


def serialize_cycle(cycle):
    from response import serialize
    data = serialize(cycle)
    data["candidate_member_ids"] = sorted(
        cycle_candidate_ids(cycle),
        key=lambda mid: db.members[mid]["_seq"])
    data["inducted_count"] = cycle_inducted_count(cycle)
    return data


# ---------------------------------------------------------------------------
# eligibility score (calculations table, pinned order; half-up, 2 dp)
# ---------------------------------------------------------------------------

WEIGHT_GPA = Decimal("0.40")
WEIGHT_SERVICE = Decimal("0.30")
WEIGHT_LEADERSHIP = Decimal("0.15")
WEIGHT_PROBATION = Decimal("0.10")
WEIGHT_ATHLETICS = Decimal("0.05")
ELIGIBILITY_SCORE_THRESHOLD = Decimal("70.00")


def _clamp100(x):
    return min(max(x, Decimal(0)), Decimal(100))


def compute_eligibility_score(application):
    cycle = db.cycles[application["cycle_id"]]
    member = db.members[application["member_id"]]
    chapter = db.chapters[application["chapter_id"]]
    # sub-scores first, weighted sum last (pinned evaluation order)
    gpa_component = _clamp100(Decimal(100) * (Decimal(str(member["weighted_gpa"])) / Decimal("5.0"))) * WEIGHT_GPA
    denom = 2 * chapter["service_hours_annual_required"]
    if denom > 0:
        service_raw = _clamp100(Decimal(100) * (
            Decimal(str(member["verified_service_hours_current_year"])) / Decimal(denom)))
    else:
        service_raw = Decimal(100) if member["verified_service_hours_current_year"] > 0 else Decimal(0)
    service_component = service_raw * WEIGHT_SERVICE
    leadership_component = (Decimal(50) if member["is_officer"] else Decimal(0)) * WEIGHT_LEADERSHIP
    probation_penalty = (Decimal(-20) * member["probation_strikes"]) * WEIGHT_PROBATION
    conflict = member_has_conflict(member["id"], parse_dt(cycle["induction_date"], "induction_date"))
    athletics_penalty = (Decimal(-10) if conflict else Decimal(0)) * WEIGHT_ATHLETICS
    raw = gpa_component + service_component + leadership_component + probation_penalty + athletics_penalty
    score = _clamp100(raw).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(score)


# ---------------------------------------------------------------------------
# member dismissal cascade (shared by dismiss endpoint and probation strikes)
# ---------------------------------------------------------------------------

def cascade_member_dismissal(member):
    for r in db.officer_roles.values():
        if r["member_id"] == member["id"] and r["status"] == "ACTIVE":
            r["status"] = "REMOVED"
            r["ended_at"] = now_iso()
            touch(r)
    for e in db.service_entries.values():
        if e["member_id"] == member["id"] and e["status"] == "PENDING_VERIFICATION":
            e["status"] = "VOID"
            touch(e)
    for v in db.votes.values():
        if v["voter_member_id"] == member["id"] and v["status"] == "CAST":
            v["status"] = "VOIDED"
            touch(v)


def cascade_member_graduation(member):
    for r in db.officer_roles.values():
        if r["member_id"] == member["id"] and r["status"] == "ACTIVE":
            r["status"] = "RESIGNED"
            r["ended_at"] = now_iso()
            touch(r)


# ---------------------------------------------------------------------------
# ledger entry factory (system-created rows share the manual-entry shape)
# ---------------------------------------------------------------------------

def create_ledger_entry(chapter, entry_type, amount_cents, status, fundraiser_id=None,
                        description=""):
    rec = new_record({
        "chapter_id": chapter["id"],
        "fundraiser_id": fundraiser_id,
        "entry_type": entry_type,
        "amount_cents": int(amount_cents),
        "entry_date": now_iso(),
        "description": description,
        "status": status,
    })
    db.ledger_entries[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# fundraiser derived flag
# ---------------------------------------------------------------------------

def serialize_fundraiser(fr):
    from response import serialize
    data = serialize(fr)
    data["segregation_of_duties_enforced"] = (
        fr["advisor_approved_by_user_id"] != fr["director_approved_by_user_id"])
    return data
