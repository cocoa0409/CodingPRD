"""Business logic: calculations (PRD §3, SCAFFOLD §1.3), load-sheet
recompute, the overload auto-withdraw rule (§2.10), cascades, lazy
qualification expiry, and the late-cancel window.

Rounding discipline (PRD §2.6): credits are 2dp round-half-up; the assignment
credit formula rounds EACH component to 2dp first, then sums. Money is integer
cents, round-half-up to whole cents.
"""

from decimal import Decimal

import db
from util import dec, rhu2, rhu0, today, parse_date

TERMS_PER_YEAR = 2

# Assignment statuses counted as live teaching load.
LIVE_ASSIGNMENT_STATUSES = ("PROPOSED", "CONFIRMED")
TERMINAL_ASSIGNMENT_STATUSES = ("DECLINED", "WITHDRAWN", "RESCINDED", "CANCELLED")
# Overload request statuses the auto-withdraw rule may cancel.
NON_TERMINAL_OVERLOAD_STATUSES = ("SUBMITTED", "CHAIR_ENDORSED")


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def term_of_section(section):
    return db.get("workload_terms", section["term_id"])


def course_of_section(section):
    return db.get("courses", section["course_id"])


def sheet_key(term_id, faculty_id):
    return (term_id, faculty_id)


def find_sheet(term_id, faculty_id):
    for sheet in db.all_of("load_sheets"):
        if sheet["term_id"] == term_id and sheet["faculty_id"] == faculty_id:
            return sheet
    return None


def get_or_create_sheet(term_id, faculty_id):
    """One LoadSheet per (term, faculty); auto-created by the first assignment
    or release-time grant for the pair. Values are computed BEFORE persist so
    the row is born consistent at version 1."""
    sheet = find_sheet(term_id, faculty_id)
    if sheet is not None:
        return sheet
    faculty = db.get("faculty_members", faculty_id)
    base = dec(faculty["base_load_credits"]) if faculty else Decimal("0")
    base_2dp = float(base.quantize(Decimal("0.01")))
    return db.new_entity("load_sheets", {
        "term_id": term_id,
        "faculty_id": faculty_id,
        "teaching_credits": 0.0,
        "release_credits": 0.0,
        "effective_obligation_credits": base_2dp,
        "overload_credits": 0.0,
        "underload_credits": base_2dp,
    })


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def assignment_credits(section, course, term, enrolled_count):
    """assignment_credit_units (SCAFFOLD §1.3): per-component 2dp round-half-up
    THEN sum. Used for both the provisional snapshot (enrolled_count at
    creation) and the census-final recompute (enrolled_count at census)."""
    ctype = course["course_type"]
    if ctype == "LECTURE":
        type_mult = term["lecture_multiplier"]
    elif ctype == "LAB":
        type_mult = term["lab_multiplier"]
    else:  # SEMINAR
        type_mult = term["seminar_multiplier"]
    base_component = rhu2(dec(course["base_credits"]) * dec(type_mult))
    online_component = rhu2(term["online_premium_credits"]) if section["modality"] == "ONLINE" else 0.0
    large_component = (
        rhu2(term["large_class_bonus_credits"])
        if enrolled_count >= term["large_class_threshold"] else 0.0
    )
    total = dec(base_component) + dec(online_component) + dec(large_component)
    return float(total.quantize(Decimal("0.01")))


def buyout_value_cents(grant, faculty, term):
    """release_buyout_value: SALARY_PRORATE for RESEARCH_BUYOUT, FLAT_RATE for
    ADMINISTRATIVE/SABBATICAL. Integer cents, round-half-up."""
    credits = dec(grant["credits_released"])
    if grant["grant_type"] == "RESEARCH_BUYOUT":
        rate = dec(faculty["base_salary_cents"]) / (dec(faculty["base_load_credits"]) * TERMS_PER_YEAR)
        return rhu0(rate * credits)
    return rhu0(credits * dec(term["flat_release_rate_cents"]))


def overload_comp_cents(overload_credits, term):
    """overload_comp_cents: round_half_up(overload * rate), integer cents."""
    return rhu0(dec(overload_credits) * dec(term["overload_comp_rate_cents"]))


# ---------------------------------------------------------------------------
# Load sheet recompute + overload auto-withdraw (PRD §2.10)
# ---------------------------------------------------------------------------

def _credits_of(assignment):
    final = assignment.get("final_credit_units")
    return dec(final if final is not None else assignment["credit_units"])


def compute_sheet_values(term_id, faculty_id):
    """Pure computation of the five sheet figures for (term, faculty)."""
    faculty = db.get("faculty_members", faculty_id)
    base = dec(faculty["base_load_credits"]) if faculty else Decimal("0")
    teaching = Decimal("0")
    for a in db.all_of("assignments"):
        if (a["term_id"] == term_id and a["faculty_id"] == faculty_id
                and a["status"] in LIVE_ASSIGNMENT_STATUSES):
            teaching += _credits_of(a)
    release = Decimal("0")
    for g in db.all_of("release_time_grants"):
        if (g["term_id"] == term_id and g["faculty_id"] == faculty_id
                and g["status"] == "APPROVED"):
            release += dec(g["credits_released"])
    effective = base - release
    if effective < 0:
        effective = Decimal("0")
    overload = teaching - effective
    if overload < 0:
        overload = Decimal("0")
    underload = effective - teaching
    if underload < 0:
        underload = Decimal("0")
    q = Decimal("0.01")
    return {
        "teaching_credits": float(teaching.quantize(q)),
        "release_credits": float(release.quantize(q)),
        "effective_obligation_credits": float(effective.quantize(q)),
        "overload_credits": float(overload.quantize(q)),
        "underload_credits": float(underload.quantize(q)),
    }


def recompute_sheet(sheet):
    """Recompute one sheet; a value change is a mutation (version +1,
    updated_at refreshed). Afterwards the overload auto-withdraw rule fires:
    overload_credits == 0 withdraws every SUBMITTED/CHAIR_ENDORSED request of
    the pair."""
    values = compute_sheet_values(sheet["term_id"], sheet["faculty_id"])
    changed = any(sheet[k] != v for k, v in values.items())
    if changed:
        sheet.update(values)
        db.touch(sheet)
    if sheet["overload_credits"] == 0:
        auto_withdraw_overloads(sheet["term_id"], sheet["faculty_id"])


def recompute_pair(term_id, faculty_id):
    sheet = find_sheet(term_id, faculty_id)
    if sheet is not None:
        recompute_sheet(sheet)


def auto_withdraw_overloads(term_id, faculty_id):
    for req in db.all_of("overload_requests"):
        if (req["term_id"] == term_id and req["faculty_id"] == faculty_id
                and req["status"] in NON_TERMINAL_OVERLOAD_STATUSES):
            req["status"] = "WITHDRAWN"
            db.touch(req)


# ---------------------------------------------------------------------------
# Qualification lazy expiry (boundary: still ACTIVE on expires_on itself)
# ---------------------------------------------------------------------------

def effective_qual_status(qual):
    if qual["status"] == "ACTIVE" and today() > parse_date(qual["expires_on"], "expires_on"):
        return "EXPIRED"
    return qual["status"]


def qual_public(qual):
    out = db.public(qual)
    out["status"] = effective_qual_status(qual)
    return out


def has_active_qualification(faculty_id, course_id):
    for q in db.all_of("qualifications"):
        if (q["faculty_id"] == faculty_id and q["course_id"] == course_id
                and effective_qual_status(q) == "ACTIVE"):
            return True
    return False


# ---------------------------------------------------------------------------
# Late-cancel window (PRD §3.5): strictly fewer than reassignment_notice_days
# days before start_date — or past it — is late. Exactly N days out is NOT.
# ---------------------------------------------------------------------------

def is_late(term):
    start = parse_date(term["start_date"], "start_date")
    days_remaining = (start - today()).days
    return days_remaining < term["reassignment_notice_days"]


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def demote_section_if_unstaffed(section):
    """STAFFED -> SCHEDULED when no CONFIRMED assignment remains."""
    if section["status"] != "STAFFED":
        return
    for a in db.all_of("assignments"):
        if a["section_id"] == section["id"] and a["status"] == "CONFIRMED":
            return
    section["status"] = "SCHEDULED"
    db.touch(section)


def staff_section_on_confirm(section):
    """SCHEDULED -> STAFFED when an assignment on the section is CONFIRMED.

    The STAFFED rise is a read-only reflection of the child assignment's state:
    it does NOT advance the section's version (PRD §2.4's cascade examples
    enumerate the demotion direction; the promotion leaves version and
    updated_at untouched so a registrar sync sequenced around a confirm still
    matches expected_section_version)."""
    if section["status"] == "SCHEDULED":
        section["status"] = "STAFFED"


def faculty_leave_cascade(faculty):
    """ACTIVE/ON_LEAVE -> ON_LEAVE/SEPARATED cascade (PRD §3.2): every PROPOSED
    assignment -> WITHDRAWN (no stipend); every CONFIRMED -> RESCINDED with
    stipend 0 (a leave cascade is not a late chair rescind); affected sections
    demote; affected sheets recompute with the auto-withdraw rule."""
    affected_sections = set()
    affected_pairs = set()
    for a in db.all_of("assignments"):
        if a["faculty_id"] != faculty["id"]:
            continue
        if a["status"] == "PROPOSED":
            a["status"] = "WITHDRAWN"
            db.touch(a)
            affected_sections.add(a["section_id"])
            affected_pairs.add((a["term_id"], a["faculty_id"]))
        elif a["status"] == "CONFIRMED":
            a["status"] = "RESCINDED"
            db.touch(a)
            affected_sections.add(a["section_id"])
            affected_pairs.add((a["term_id"], a["faculty_id"]))
    for section_id in affected_sections:
        section = db.get("course_sections", section_id)
        if section is not None:
            demote_section_if_unstaffed(section)
    for term_id, faculty_id in affected_pairs:
        recompute_pair(term_id, faculty_id)


def recompute_faculty_sheets(faculty_id):
    """Used after a base_load_credits edit: every sheet of the faculty."""
    for sheet in db.all_of("load_sheets"):
        if sheet["faculty_id"] == faculty_id:
            recompute_sheet(sheet)


def cancel_section_cascade(section, term, late):
    """Section cancel cascade (PRD §3.6). Budget must be pre-validated by the
    caller; this function applies mutations only.

    - CONFIRMED assignments -> CANCELLED; when late each draws the stipend and
      the term ledger accrues it.
    - PROPOSED assignments -> WITHDRAWN (no stipend).
    - Affected sheets recompute; overload auto-withdraw applies.
    """
    confirmed = [a for a in db.all_of("assignments")
                 if a["section_id"] == section["id"] and a["status"] == "CONFIRMED"]
    proposed = [a for a in db.all_of("assignments")
                if a["section_id"] == section["id"] and a["status"] == "PROPOSED"]
    affected_pairs = set()
    spent_delta = 0
    for a in confirmed:
        a["status"] = "CANCELLED"
        if late:
            a["stipend_cents"] = term["late_cancel_stipend_cents"]
            spent_delta += a["stipend_cents"]
        db.touch(a)
        affected_pairs.add((a["term_id"], a["faculty_id"]))
    for a in proposed:
        a["status"] = "WITHDRAWN"
        db.touch(a)
        affected_pairs.add((a["term_id"], a["faculty_id"]))
    if spent_delta:
        term["comp_budget_spent_cents"] += spent_delta
        db.touch(term)
    section["status"] = "CANCELLED"
    db.touch(section)
    for term_id, faculty_id in affected_pairs:
        recompute_pair(term_id, faculty_id)
