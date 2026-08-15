"""Derived fields and calculation rules (PRD 2.9, scaffold 1.3).

All derived figures are reconciled immediately: this module computes them from
the live store so every read reflects the post-mutation state. Stored mutation
state (statuses, frozen order lines, timestamps) changes eagerly in routes;
counts, balances, subsidies, rebates, seats, and DRAFT order totals derive here.

Calculations implemented:
- registration_net_fee (subsidy floored by min(), late flag strictly-greater)
- order_invoice (estimate: live while DRAFT / frozen at submit; final: reconcile)
- student_balance (provisional vs projected variants)
- school_rebate (round half-up PER LINE, then sum — pinned order)
- session_seating (REGISTERED headcount while SCHEDULED)
- equity_participation (rates + access gap, 1-decimal round half-up)
"""
from decimal import Decimal

from db import db
from util import CLOCK, round_half_up_int, round_half_up_1dp

ACTIVE_BALANCE_STATUSES = ("REGISTERED", "SAT", "NO_SHOW")


# ---------------------------------------------------------------------------
# Course / cycle aggregates
# ---------------------------------------------------------------------------

def authorized_teacher_count(course_id) -> int:
    return sum(
        1 for ta in db["teacher_authorizations"].values()
        if ta["course_id"] == course_id and ta["status"] == "AUTHORIZED"
    )


def course_status(course_id) -> str:
    return "ACTIVE" if authorized_teacher_count(course_id) >= 1 else "SUSPENDED"


def course_registered_count(course_id) -> int:
    """Non-CANCELLED registrations (order ordered_count input)."""
    return sum(
        1 for r in db["registrations"].values()
        if r["course_id"] == course_id and r["registration_status"] != "CANCELLED"
    )


def course_seated_count(course_id) -> int:
    """REGISTERED-only headcount (session seating input)."""
    return sum(
        1 for r in db["registrations"].values()
        if r["course_id"] == course_id and r["registration_status"] == "REGISTERED"
    )


def course_sat_count(course_id) -> int:
    return sum(
        1 for r in db["registrations"].values()
        if r["course_id"] == course_id and r["registration_status"] == "SAT"
    )


def cycle_registered_exam_count(cycle_id) -> int:
    return sum(
        1 for r in db["registrations"].values()
        if r["cycle_id"] == cycle_id and r["registration_status"] != "CANCELLED"
    )


# ---------------------------------------------------------------------------
# Fee reduction, net fee, balances, rebate
# ---------------------------------------------------------------------------

def application_for(student_id, cycle_id):
    """At most one row ever exists per (student, cycle)."""
    for a in db["fee_reduction_applications"].values():
        if a["student_id"] == student_id and a["cycle_id"] == cycle_id:
            return a
    return None


def reg_subsidy_cents(reg, projected=False) -> int:
    """min(fee_reduction_cents, fee + late) gated on the application status.

    Provisional variant: only APPROVED applications contribute.
    Projected variant: SUBMITTED applications are treated as if approved.
    """
    cycle = db["exam_cycles"].get(reg["cycle_id"])
    if cycle is None:
        return 0
    app = application_for(reg["student_id"], reg["cycle_id"])
    if app is None:
        return 0
    if projected:
        if app["status"] not in ("APPROVED", "SUBMITTED"):
            return 0
    else:
        if app["status"] != "APPROVED":
            return 0
    return min(cycle["fee_reduction_cents"],
               reg["fee_cents"] + reg["late_fee_applied_cents"])


def reg_net_cents(reg) -> int:
    return reg["fee_cents"] + reg["late_fee_applied_cents"] - reg_subsidy_cents(reg)


def student_balances(student_id):
    """(balance_cents provisional, projected_balance_cents) — CANCELLED excluded."""
    balance = 0
    projected = 0
    for r in db["registrations"].values():
        if r["student_id"] != student_id:
            continue
        if r["registration_status"] not in ACTIVE_BALANCE_STATUSES:
            continue
        balance += reg_net_cents(r)
        projected += (r["fee_cents"] + r["late_fee_applied_cents"]
                      - reg_subsidy_cents(r, projected=True))
    return balance, projected


def student_transcript_posted_count(student_id) -> int:
    return sum(
        1 for r in db["registrations"].values()
        if r["student_id"] == student_id and r["score_status"] == "POSTED"
    )


def cycle_rebate_cents(cycle) -> int:
    """PINNED ORDER: round each registration's rebate line first, then sum."""
    total = 0
    for r in db["registrations"].values():
        if r["cycle_id"] == cycle["id"] and r["registration_status"] != "CANCELLED":
            total += round_half_up_int(reg_net_cents(r) * cycle["rebate_rate_bp"], 10000)
    return total


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def scheduled_session_for_course(course_id):
    for s in db["exam_sessions"].values():
        if s["course_id"] == course_id and s["status"] == "SCHEDULED":
            return s
    return None


def session_seats_reserved(session) -> int:
    if session["status"] != "SCHEDULED":
        return 0
    return course_seated_count(session["course_id"])


# ---------------------------------------------------------------------------
# Exam order invoice (estimate live while DRAFT; frozen at submit; final at reconcile)
# ---------------------------------------------------------------------------

def adjustment_deltas(order):
    return {a["course_id"]: a["delta"] for a in order["adjustments"]}


def compute_order_lines(order, now):
    """Live per-course lines: ordered_count = non-CANCELLED count + adjustment delta."""
    cycle = db["exam_cycles"][order["cycle_id"]]
    deltas = adjustment_deltas(order)
    courses = sorted(
        (c for c in db["courses"].values() if c["cycle_id"] == cycle["id"]),
        key=lambda c: c["_seq"],
    )
    late = now > cycle["order_deadline_at"]
    lines = []
    for c in courses:
        ordered = course_registered_count(c["id"]) + deltas.get(c["id"], 0)
        late_total = ordered * cycle["late_fee_cents"] if late else 0
        lines.append({
            "course_id": c["id"],
            "ordered_count": ordered,
            "fee_cents": c["exam_fee_cents"],
            "late_fee_total_cents": late_total,
            "line_total_cents": ordered * c["exam_fee_cents"] + late_total,
        })
    return lines


def subsidy_component(cycle_id) -> int:
    """Sum of subsidy_cents over non-CANCELLED registrations at evaluation time."""
    return sum(
        reg_subsidy_cents(r) for r in db["registrations"].values()
        if r["cycle_id"] == cycle_id and r["registration_status"] != "CANCELLED"
    )


def compute_estimate(order, now):
    """Estimate variant: forward-looking; no unused penalty; late component from clock."""
    lines = compute_order_lines(order, now)
    gross_plus_late = sum(l["line_total_cents"] for l in lines)
    return gross_plus_late - subsidy_component(order["cycle_id"]), lines


def compute_final_total(order) -> int:
    """Final variant: frozen lines replayed against SAT outcomes + unused penalties."""
    cycle = db["exam_cycles"][order["cycle_id"]]
    lines = order["lines"] or []
    gross = sum(l["ordered_count"] * l["fee_cents"] for l in lines)
    late_comp = sum(l["late_fee_total_cents"] for l in lines) if order["submitted_late"] else 0
    unused = 0
    for l in lines:
        unused_count = max(0, l["ordered_count"] - course_sat_count(l["course_id"]))
        unused += unused_count * cycle["unused_exam_penalty_cents"]
    return gross + late_comp + unused - subsidy_component(order["cycle_id"])


def order_view_fields(order):
    """(lines, estimate_total_cents) honoring live-while-DRAFT / frozen-at-submit."""
    if order["status"] == "DRAFT":
        estimate, lines = compute_estimate(order, CLOCK.now())
        return lines, estimate
    return order["lines"] or [], order["estimate_total_cents"]


# ---------------------------------------------------------------------------
# Equity participation (GET /exam-cycles/{id}/equity-report)
# ---------------------------------------------------------------------------

SUBGROUPS = ("GEN", "FRL", "IEP", "ELL")


def equity_report(cycle, compare_cycle):
    subgroups = []
    rates = []
    for sg in SUBGROUPS:
        students = [s for s in db["students"].values() if s["subgroup_code"] == sg]
        if not students:
            continue
        participants = len({
            r["student_id"] for r in db["registrations"].values()
            if r["cycle_id"] == cycle["id"] and r["registration_status"] != "CANCELLED"
            and db["students"].get(r["student_id"]) is not None
            and db["students"][r["student_id"]]["subgroup_code"] == sg
        })
        rate = round_half_up_1dp(Decimal(100 * participants) / Decimal(len(students)))
        rates.append(rate)
        subgroups.append({
            "subgroup_code": sg,
            "students": len(students),
            "participants": participants,
            "participation_rate": float(rate),
        })
    total_exams = cycle_registered_exam_count(cycle["id"])
    growth = None
    if compare_cycle is not None:
        growth = total_exams - cycle_registered_exam_count(compare_cycle["id"])
    if rates:
        access_gap = float(round_half_up_1dp(max(rates) - min(rates)))
    else:
        access_gap = 0.0
    return {
        "subgroups": subgroups,
        "total_exams": total_exams,
        "growth_exams": growth,
        "access_gap_pct": access_gap,
    }
