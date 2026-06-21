"""Calculation rules (scaffold §1.3, PRD §3.4/§3.6).

All money is integer cents. round_half_up applied where a fraction scales a cent
amount; rounding-order pinned per formula.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db
from services.common import sort_by_created, touch

# Constants (scaffold §1.3 constants)
TIER_TABLE = {"NONE": Decimal("0.0"), "PARTIAL": Decimal("0.5"), "FULL": Decimal("1.0")}
CAMP_MATERIALS_SURCHARGE_CENTS = 1500
SIBLING_PCT = Decimal("0.10")
RAIN_OVERFLOW_TOLERANCE = 1


def _round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------
def parse_iso_date(s: str) -> date:
    """Parse an ISO date (or datetime) string into a date."""
    if not isinstance(s, str):
        raise ValueError("not a date string")
    txt = s.strip()
    # Accept full datetimes too; take the date component.
    if "T" in txt:
        txt = txt.split("T", 1)[0]
    # Tolerate trailing Z / offsets that may slip through on date-only strings.
    return date.fromisoformat(txt[:10])


# ---------------------------------------------------------------------------
# compute_child_age (scaffold §1.3) — whole years floored to the most recent
# birthday on the session's reference date.
# ---------------------------------------------------------------------------
def compute_child_age(child: dict, session: dict) -> int:
    ref = parse_iso_date(session["age_as_of_date"])
    dob = parse_iso_date(child["birth_date"])
    age = ref.year - dob.year
    if (ref.month, ref.day) < (dob.month, dob.day):
        age -= 1
    return age


def age_eligible(child: dict, session: dict) -> bool:
    age = compute_child_age(child, session)
    return session["age_group_min"] <= age <= session["age_group_max"]


# ---------------------------------------------------------------------------
# compute_scholarship_discount (scaffold §1.3) — tier table lookup, fraction [0,1]
# ---------------------------------------------------------------------------
def tier_discount_pct(tier: str) -> float:
    return float(TIER_TABLE[tier])


def child_active_discount_pct(child_id: str) -> Decimal:
    """The child's currently-APPROVED scholarship discount fraction, else 0."""
    for award in db.scholarship_awards.values():
        if award["child_id"] == child_id and award["status"] == "APPROVED":
            return TIER_TABLE[award["tier"]]
    return Decimal("0.0")


# ---------------------------------------------------------------------------
# compute_line_tuition (scaffold §1.3, PRD §3.6)
#   after_scholarship = round_half_up(base * (1 - sch))   # scale-then-round
#   if CAMP: line = after_scholarship + 1500              # then add surcharge
#   result = max(0, line)
# `discount_pct` lets callers pin the fraction (e.g. 0 for the revoke compensation).
# ---------------------------------------------------------------------------
def compute_line_tuition(enrollment: dict, *, discount_pct: Decimal | None = None) -> int:
    offering = db.weekly_offerings[enrollment["weekly_offering_id"]]
    session = db.sessions[offering["session_id"]]
    program = db.programs[session["program_id"]]
    base = session["base_weekly_tuition_cents"]

    if discount_pct is None:
        sch = child_active_discount_pct(enrollment["child_id"])
    else:
        sch = discount_pct

    after_scholarship = _round_half_up(Decimal(base) * (Decimal(1) - sch))
    if program["program_type"] == "CAMP":
        line = after_scholarship + CAMP_MATERIALS_SURCHARGE_CENTS
    else:
        line = after_scholarship
    return max(0, line)


# ---------------------------------------------------------------------------
# reconcile_offering_counts (scaffold §1.3)
# ---------------------------------------------------------------------------
def _offering_enrollments(offering_id: str) -> list:
    return [e for e in db.enrollments.values() if e["weekly_offering_id"] == offering_id]


def reconcile_offering_counts(offering: dict) -> None:
    members = _offering_enrollments(offering["id"])
    confirmed = [e for e in members if e["status"] == "CONFIRMED"]
    waitlisted = [e for e in members if e["status"] == "WAITLISTED"]
    session = db.sessions[offering["session_id"]]

    offering["enrolled_count"] = len(confirmed)
    offering["waitlist_count"] = len(waitlisted)
    offering["capacity_state"] = (
        "FULL" if len(confirmed) >= session["weekly_capacity"] else "AVAILABLE"
    )
    # 1-based waitlist ranks by created_at ASC.
    for i, e in enumerate(sort_by_created(waitlisted), start=1):
        e["waitlist_rank"] = i
    touch(offering)


# ---------------------------------------------------------------------------
# Invoice line set + totals (scaffold §1.3 compute_sibling_discount / compute_invoice_totals)
# ---------------------------------------------------------------------------
def confirmed_lines(invoice_id: str) -> list:
    return [
        e
        for e in db.enrollments.values()
        if e.get("invoice_id") == invoice_id and e["status"] == "CONFIRMED"
    ]


def compute_sibling_discount(invoice: dict) -> int:
    """Household sibling discount over CONFIRMED lines of a DRAFT invoice (PRD §3.6).

    DRAFT  -> uses provisional_tuition_cents
    FINALIZED/PAID -> uses final_tuition_cents (frozen)
    """
    lines = confirmed_lines(invoice["id"])
    amount_field = (
        "provisional_tuition_cents" if invoice["status"] == "DRAFT" else "final_tuition_cents"
    )

    # Group by child; per child the single highest line on this invoice.
    by_child: dict = {}
    for e in lines:
        cid = e["child_id"]
        amt = e[amount_field]
        if cid not in by_child or amt > by_child[cid]:
            by_child[cid] = amt

    if len(by_child) < 2:
        return 0

    # Anchor = child whose single highest line is the largest of all children's;
    # tie-break: lowest Child.created_at (earliest child), then insertion seq.
    def _child_seq(cid: str) -> int:
        c = db.children.get(cid)
        return c.get("_seq", 0) if c else 0

    def _child_created(cid: str) -> str:
        c = db.children.get(cid)
        return c["created_at"] if c else ""

    # Largest best amount wins; on ties the EARLIEST child (smallest created_at,
    # then smallest seq) is the anchor. Sort so the anchor sorts first.
    anchor_cid = sorted(
        by_child.keys(),
        key=lambda cid: (-by_child[cid], _child_created(cid), _child_seq(cid)),
    )[0]
    eligible = {cid: best for cid, best in by_child.items() if cid != anchor_cid}
    total = sum(eligible.values())
    return _round_half_up(SIBLING_PCT * Decimal(total))


def compute_invoice_totals(invoice: dict) -> None:
    """Re-derive subtotal/sibling_discount/total_due in the pinned order (PRD §3.6).

    Order: (1) per-line tuitions are already current on the enrollments, then
    (2) sibling_discount, then (3) totals. This function performs (2) and (3).
    Any change is a mutation of the invoice -> touch().
    """
    lines = confirmed_lines(invoice["id"])
    amount_field = (
        "provisional_tuition_cents" if invoice["status"] == "DRAFT" else "final_tuition_cents"
    )
    subtotal = sum(e[amount_field] for e in lines)
    sibling = compute_sibling_discount(invoice)
    total_due = max(0, subtotal - sibling)

    changed = (
        invoice.get("subtotal_cents") != subtotal
        or invoice.get("sibling_discount_cents") != sibling
        or invoice.get("total_due_cents") != total_due
    )
    invoice["subtotal_cents"] = subtotal
    invoice["sibling_discount_cents"] = sibling
    invoice["total_due_cents"] = total_due
    if changed:
        touch(invoice)


# ---------------------------------------------------------------------------
# Week-overlap helper (PRD §3.4, validation §1.4 priority 12)
# ---------------------------------------------------------------------------
def weeks_overlap(week_start_a: str, week_start_b: str) -> bool:
    """Half-open [week_start, week_start+7d) intervals overlap?

    Adjacency (next Monday, no overlap) is allowed.
    """
    a = parse_iso_date(week_start_a)
    b = parse_iso_date(week_start_b)
    a_end = a + timedelta(days=7)
    b_end = b + timedelta(days=7)
    return a < b_end and b < a_end
