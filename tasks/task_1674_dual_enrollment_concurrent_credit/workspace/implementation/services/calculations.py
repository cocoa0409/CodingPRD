"""The ten calculation rules from the scaffold `calculations` table.

1.  seat_availability          — REGISTERED-count seat ledger
2.  waitlist_promotion         — min waitlist_seq promotion on seat release
3.  effective_deadline         — min() across the two calendars, inclusive bounds
4.  refund_percentage          — 100 on drop; 50 in the cross-calendar mismatch window
5.  tuition_allocation         — state / district / family waterfall on Invoice create
6.  refund_settlement          — estimate (billed) and settled (paid) variants
7.  gpa_recompute              — college 4.0 scale (W excluded) vs HS 5.0 scale (W=0 in)
8.  prerequisite_satisfaction  — DAG edge rules + POSTED COLLEGE entry satisfaction
9.  placement_recency          — non-expired records, latest taken_at/created_at wins
10. transfer_credit_evaluation — articulated vs native readings for a COMPLETED enrollment
"""
from decimal import Decimal, ROUND_HALF_UP

from db import db
from errors import (
    raise_error,
    ERR_PLACEMENT_MISSING,
    ERR_PLACEMENT_SCORE_INSUFFICIENT,
    ERR_SELF_PREREQUISITE,
    ERR_DUPLICATE_PREREQUISITE,
    ERR_PREREQUISITE_CYCLE,
    ERR_ENROLLMENT_INVALID_STATE,
)
from services.core import new_record, touch
from util import CLOCK, dec_number, now_ts, rhu_cents

# ---------------------------------------------------------------------------
# Grade ordering: A > B > C > D > F (W is outside the letter ordering).
# ---------------------------------------------------------------------------
GRADE_ORDER = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}


def grade_meets(grade, min_grade):
    """grade at or above min_grade under A > B > C > D > F. Only A/B/C can
    satisfy any min_grade (min_grade is always one of A|B|C)."""
    if grade not in GRADE_ORDER or min_grade not in GRADE_ORDER:
        return False
    return GRADE_ORDER[grade] >= GRADE_ORDER[min_grade]


# ---------------------------------------------------------------------------
# 1. seat_availability — seats_taken = count of REGISTERED enrollments;
#    seats_available = capacity - seats_taken. Exact integer arithmetic.
# ---------------------------------------------------------------------------

def seats_taken(offering_id) -> int:
    return sum(
        1
        for e in db["enrollments"].values()
        if e["offering_id"] == offering_id and e["status"] == "REGISTERED"
    )


def seats_available(offering) -> int:
    return offering["capacity"] - seats_taken(offering["id"])


# ---------------------------------------------------------------------------
# 3. effective_deadline — the stricter (earlier) of the two calendars governs.
#    Boundaries are inclusive: now <= deadline passes.
# ---------------------------------------------------------------------------

def effective_add_deadline(offering):
    ct = db["terms"][offering["college_term_id"]]
    ht = db["terms"][offering["hs_term_id"]]
    return min(ct["_add_deadline"], ht["_add_deadline"])


def effective_drop_deadline(offering):
    ct = db["terms"][offering["college_term_id"]]
    ht = db["terms"][offering["hs_term_id"]]
    return min(ct["_drop_deadline"], ht["_drop_deadline"])


def effective_withdraw_deadline(offering):
    ct = db["terms"][offering["college_term_id"]]
    ht = db["terms"][offering["hs_term_id"]]
    return min(ct["_withdraw_deadline"], ht["_withdraw_deadline"])


# ---------------------------------------------------------------------------
# 4. refund_percentage — DROP: 100. WITHDRAW: 50 iff now <= the COLLEGE term's
#    drop_deadline (the college calendar alone governs the 50 pct mismatch
#    compensation), else 0.
# ---------------------------------------------------------------------------

DROP_REFUND_PCT = 100
MISMATCH_REFUND_PCT = 50
PLAIN_WITHDRAW_REFUND_PCT = 0


def withdraw_refund_pct(offering, now) -> int:
    ct = db["terms"][offering["college_term_id"]]
    if now <= ct["_drop_deadline"]:
        return MISMATCH_REFUND_PCT
    return PLAIN_WITHDRAW_REFUND_PCT


# ---------------------------------------------------------------------------
# 5. tuition_allocation — waterfall over three payer buckets; integer cents.
# ---------------------------------------------------------------------------

def find_funding_agreement(high_school_id, college_term_id):
    for a in db["funding_agreements"].values():
        if (
            a["high_school_id"] == high_school_id
            and a["college_term_id"] == college_term_id
        ):
            return a
    return None


def create_invoice(enrollment, offering):
    """Create the Invoice when an enrollment reaches REGISTERED (confirm,
    waitlist promotion, reinstate). Bucket order: state -> district -> family.
    Invariant: state + district + family == tuition_total_cents."""
    from errors import ERR_NO_FUNDING_AGREEMENT  # local to avoid cycles

    course = db["courses"][offering["course_id"]]
    agreement = find_funding_agreement(offering["high_school_id"], offering["college_term_id"])
    if agreement is None:
        raise_error(ERR_NO_FUNDING_AGREEMENT, "no funding agreement for school/term")

    hours = course["college_credit_hours"]
    tuition_total = hours * agreement["tuition_cents_per_credit"]

    # Bucket 1 — state: STATE_PROGRAM agreements on HS_CAMPUS delivery only.
    if agreement["funding_model"] == "STATE_PROGRAM" and offering["delivery_mode"] == "HS_CAMPUS":
        state_amount = min(tuition_total, agreement["state_rate_cents_per_credit"] * hours)
    else:
        state_amount = 0
    remainder_1 = tuition_total - state_amount

    # Bucket 2 — district: skipped entirely for FAMILY_RESPONSIBLE.
    if agreement["funding_model"] == "FAMILY_RESPONSIBLE":
        district_amount = 0
    else:
        district_amount = min(remainder_1, agreement["district_cap_cents"])

    # Bucket 3 — family remainder.
    family_amount = remainder_1 - district_amount

    return new_record(
        "invoices",
        {
            "enrollment_id": enrollment["id"],
            "funding_agreement_id": agreement["id"],
            "tuition_total_cents": tuition_total,
            "state_amount_cents": state_amount,
            "district_amount_cents": district_amount,
            "family_amount_cents": family_amount,
            "paid_state_cents": 0,
            "paid_district_cents": 0,
            "paid_family_cents": 0,
            "refund_pct": None,
            "refund_estimate_cents": None,
            "est_state_refund_cents": None,
            "est_district_refund_cents": None,
            "est_family_refund_cents": None,
            "refund_paid_cents": None,
            "status": "ISSUED",
            "refund_status": "NONE",
        },
    )


def paid_total_cents(invoice) -> int:
    return (
        invoice["paid_state_cents"]
        + invoice["paid_district_cents"]
        + invoice["paid_family_cents"]
    )


# ---------------------------------------------------------------------------
# 6. refund_settlement — pinned rounding order: per-payer round_half_up first,
#    family absorbs the remainder.
# ---------------------------------------------------------------------------

def apply_refund_estimate(invoice, pct: int):
    """Estimate variant (billed-based), fired at drop / withdraw / admin drop.
    Estimate fields are computed only when pct > 0. pct == 100 voids the
    invoice; pct == 50 leaves status unchanged. refund_status := DUE iff
    pct > 0 and the sum of payments is greater than zero, else NONE."""
    invoice["refund_pct"] = pct
    if pct > 0:
        est_total = rhu_cents(invoice["tuition_total_cents"], pct)
        est_state = rhu_cents(invoice["state_amount_cents"], pct)
        est_district = rhu_cents(invoice["district_amount_cents"], pct)
        # Family bucket pinned to absorb any rounding drift.
        invoice["refund_estimate_cents"] = est_total
        invoice["est_state_refund_cents"] = est_state
        invoice["est_district_refund_cents"] = est_district
        invoice["est_family_refund_cents"] = est_total - est_state - est_district
    if pct == DROP_REFUND_PCT:
        invoice["status"] = "VOIDED"
    invoice["refund_status"] = (
        "DUE" if (pct > 0 and paid_total_cents(invoice) > 0) else "NONE"
    )
    touch(invoice)


def settle_refund(invoice):
    """Settled variant (paid-based), fired at POST /invoices/{id}/refund.
    State and district refunded by per-payer rounding of PAID amounts; family
    receives the remainder of round_half_up(paid_total * pct / 100)."""
    pct = invoice["refund_pct"] or 0
    paid_state = invoice["paid_state_cents"]
    paid_district = invoice["paid_district_cents"]
    paid_total = paid_total_cents(invoice)
    r_state = rhu_cents(paid_state, pct)
    r_district = rhu_cents(paid_district, pct)
    r_total = rhu_cents(paid_total, pct)
    invoice["refund_paid_cents"] = r_state + r_district + (r_total - r_state - r_district)
    invoice["refund_status"] = "PROCESSED"
    touch(invoice)


def current_invoice(enrollment_id):
    """The enrollment's active invoice: the most recently created one. A
    reinstate creates a NEW invoice; the previous keeps its own state."""
    invoices = [i for i in db["invoices"].values() if i["enrollment_id"] == enrollment_id]
    if not invoices:
        return None
    invoices.sort(key=lambda i: i["_seq"])
    return invoices[-1]


# ---------------------------------------------------------------------------
# 2. waitlist_promotion — fires only when offering.status == OPEN; a seat
#    released while IN_SESSION or later stays free. Promotes the WAITLISTED
#    enrollment with the minimum waitlist_seq; creates its Invoice. Empty
#    candidate set is a no-op.
# ---------------------------------------------------------------------------

def next_waitlist_seq(offering_id) -> int:
    """Per-offering monotonic, never reused: max existing seq + 1 (starts at 1)."""
    seqs = [
        e["waitlist_seq"]
        for e in db["enrollments"].values()
        if e["offering_id"] == offering_id and e["waitlist_seq"] is not None
    ]
    return (max(seqs) if seqs else 0) + 1


def promote_waitlist(offering):
    if offering["status"] != "OPEN":
        return None
    if seats_available(offering) < 1:
        return None
    candidates = [
        e
        for e in db["enrollments"].values()
        if e["offering_id"] == offering["id"] and e["status"] == "WAITLISTED"
    ]
    if not candidates:
        return None
    promoted = min(candidates, key=lambda e: e["waitlist_seq"])
    promoted["status"] = "REGISTERED"
    touch(promoted)  # Enrollment.version += 1
    touch(offering)  # seat consumed: CourseOffering.version += 1 (again)
    create_invoice(promoted, offering)
    return promoted


# ---------------------------------------------------------------------------
# 7. gpa_recompute — two variants over POSTED TranscriptEntries only.
# ---------------------------------------------------------------------------

COLLEGE_SCALE = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}  # W excluded entirely
HS_SCALE = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 0, "W": 0}  # W included at 0 pts


def quality_points(institution, grade):
    scale = COLLEGE_SCALE if institution == "COLLEGE" else HS_SCALE
    return scale.get(grade, 0)


def entry_grade_points(institution, grade, credit_value):
    """grade_points stamped on the TranscriptEntry at creation."""
    qp = quality_points(institution, grade)
    points = dec_number(credit_value) * Decimal(qp)
    return float(points) if points != points.to_integral() else int(points)


def gpa_recompute(student_id, institution):
    """Recompute the student's GPA for one institution over POSTED entries.
    College: 4.0 scale, W excluded from numerator and denominator.
    High school: 5.0 weighted scale, W included with 0 points in the denominator.
    Empty eligible set -> 0.000. Three decimals, round_half_up."""
    student = db["students"].get(student_id)
    if student is None:
        return
    scale = COLLEGE_SCALE if institution == "COLLEGE" else HS_SCALE
    numerator = Decimal(0)
    denominator = Decimal(0)
    for entry in db["transcript_entries"].values():
        if entry["institution"] != institution or entry["status"] != "POSTED":
            continue
        enrollment = db["enrollments"].get(entry["enrollment_id"])
        if enrollment is None or enrollment["student_id"] != student_id:
            continue
        if entry["grade"] not in scale:
            continue
        credit = dec_number(entry["credit_value"])
        numerator += Decimal(scale[entry["grade"]]) * credit
        denominator += credit
    if denominator == 0:
        gpa = Decimal("0.000")
    else:
        gpa = (numerator / denominator).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    field = "college_gpa" if institution == "COLLEGE" else "hs_gpa"
    student[field] = float(gpa)
    # Posting/voiding refreshes the owning student's updated_at.
    student["updated_at"] = now_ts()


# ---------------------------------------------------------------------------
# 8. prerequisite_satisfaction — the Prerequisite table is a DAG over courses.
# ---------------------------------------------------------------------------

def check_new_prerequisite_edge(course_id, requires_course_id):
    """Edge creation rules in their fixed sub-order: self-edge, exact
    duplicate, then cycle (DFS reachability from requires_course_id back to
    course_id)."""
    if course_id == requires_course_id:
        raise_error(ERR_SELF_PREREQUISITE, "course_id must differ from requires_course_id")
    for p in db["prerequisites"].values():
        if p["course_id"] == course_id and p["requires_course_id"] == requires_course_id:
            raise_error(ERR_DUPLICATE_PREREQUISITE, "prerequisite edge already exists")
    # Cycle: would requires_course_id reach course_id through existing edges?
    adjacency = {}
    for p in db["prerequisites"].values():
        adjacency.setdefault(p["course_id"], []).append(p["requires_course_id"])
    stack = [requires_course_id]
    seen = set()
    while stack:
        node = stack.pop()
        if node == course_id:
            raise_error(ERR_PREREQUISITE_CYCLE, "edge would close a cycle")
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adjacency.get(node, []))


def prerequisites_satisfied(student_id, course_id) -> bool:
    """Every Prerequisite row of the course needs a POSTED COLLEGE
    TranscriptEntry for this student on an offering of requires_course_id,
    with grade at or above min_grade."""
    rows = [p for p in db["prerequisites"].values() if p["course_id"] == course_id]
    for row in rows:
        satisfied = False
        for entry in db["transcript_entries"].values():
            if entry["institution"] != "COLLEGE" or entry["status"] != "POSTED":
                continue
            enrollment = db["enrollments"].get(entry["enrollment_id"])
            if enrollment is None or enrollment["student_id"] != student_id:
                continue
            offering = db["offerings"].get(enrollment["offering_id"])
            if offering is None or offering["course_id"] != row["requires_course_id"]:
                continue
            if grade_meets(entry["grade"], row["min_grade"]):
                satisfied = True
                break
        if not satisfied:
            return False
    return True


# ---------------------------------------------------------------------------
# 9. placement_recency — records at/past expiry are invisible; the latest
#    non-expired record (taken_at DESC, created_at DESC) is the one evaluated.
# ---------------------------------------------------------------------------

def check_placement(student_id, course, now):
    if course["min_placement_score"] <= 0:
        return  # placement_exam_code ignored when no placement required
    records = [
        r
        for r in db["placement_records"].values()
        if r["student_id"] == student_id
        and r["exam_code"] == course["placement_exam_code"]
        and r["_expires_at"] > now
    ]
    if not records:
        raise_error(ERR_PLACEMENT_MISSING, "no current placement record for the exam")
    records.sort(key=lambda r: (r["_taken_at"], r["created_at"], r["_seq"]), reverse=True)
    latest = records[0]
    if latest["score"] < course["min_placement_score"]:
        raise_error(
            ERR_PLACEMENT_SCORE_INSUFFICIENT,
            "latest placement score is below the course minimum",
        )


# ---------------------------------------------------------------------------
# 10. transfer_credit_evaluation — articulated vs native readings of a
#     COMPLETED enrollment toward a target institution. Hours to 1 decimal.
# ---------------------------------------------------------------------------

def transfer_evaluation(enrollment, target_institution):
    if enrollment["status"] != "COMPLETED":
        raise_error(
            ERR_ENROLLMENT_INVALID_STATE,
            "transfer evaluation requires a COMPLETED enrollment",
        )
    now = CLOCK.now()
    offering = db["offerings"][enrollment["offering_id"]]
    course = db["courses"][offering["course_id"]]

    agreement = None
    for a in db["articulation_agreements"].values():
        if a["course_id"] != course["id"] or a["target_institution"] != target_institution:
            continue
        if a["_effective_from"] <= now <= a["_effective_to"]:  # CLOSED interval
            agreement = a
            break

    eligible = agreement is not None and grade_meets(
        enrollment["grade"], agreement["min_grade_for_transfer"]
    ) and enrollment["grade"] in ("A", "B", "C")

    q = Decimal("0.1")
    if eligible:
        articulated = dec_number(agreement["transfer_credit_hours"]).quantize(
            q, rounding=ROUND_HALF_UP
        )
        native = dec_number(course["college_credit_hours"]).quantize(
            q, rounding=ROUND_HALF_UP
        )
    else:
        articulated = Decimal("0.0")
        native = Decimal("0.0")
    loss = (native - articulated).quantize(q, rounding=ROUND_HALF_UP)

    return {
        "target_institution": target_institution,
        "eligible": eligible,
        "articulated_credit_hours": float(articulated),
        "native_credit_hours": float(native),
        "credit_loss_hours": float(loss),
    }
