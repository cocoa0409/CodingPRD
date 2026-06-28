"""Business logic: state machines, calculations, cascades, reconciliation.

Every rule traces to a PRD §3 sentence. PRD wins over SCAFFOLD on any conflict.
"""
from decimal import Decimal

from db import db, touch
from clock import clock
from util import (
    round_half_up_2dp, round_half_up_int, floor_int, parse_iso8601,
)

# Finance constants (calc finance_schedule)
DOWN_TIER_CENTS = 600000
MONTHLY_RATE = Decimal("0.01")

# Skills weighting (calc skills_weighted_score)
W_PRE_TRIP = Decimal("0.30")
W_BASIC_CONTROL = Decimal("0.30")
W_ROAD = Decimal("0.40")


# ---------------------------------------------------------------------------
# Hour reconciliation (PRD §2.6, §3.4 — denormalized totals recomputed)
# ---------------------------------------------------------------------------
def _sessions_for_enrollment(enrollment_id):
    return [s for s in db.clock_sessions.values()
            if s["enrollment_id"] == enrollment_id]


def recompute_logged_hours(enr):
    """logged_<phase>_hours = sum(duration_minutes/60) over COMPLETED sessions."""
    sessions = _sessions_for_enrollment(enr["id"])
    totals = {"CLASSROOM": Decimal(0), "RANGE": Decimal(0), "ROAD": Decimal(0)}
    for s in sessions:
        if s["status"] == "COMPLETED":
            totals[s["phase"]] += Decimal(s["duration_minutes"]) / Decimal(60)
    enr["logged_classroom_hours"] = round_half_up_2dp(totals["CLASSROOM"])
    enr["logged_range_hours"] = round_half_up_2dp(totals["RANGE"])
    enr["logged_road_hours"] = round_half_up_2dp(totals["ROAD"])


def recompute_projected_road_hours(enr):
    """projected_road_hours = sum over ROAD sessions in {BOOKED, COMPLETED}."""
    sessions = _sessions_for_enrollment(enr["id"])
    total = Decimal(0)
    for s in sessions:
        if s["phase"] == "ROAD" and s["status"] in ("BOOKED", "COMPLETED"):
            total += Decimal(s["duration_minutes"]) / Decimal(60)
    enr["projected_road_hours"] = round_half_up_2dp(total)


def recompute_truck_reserved(truck):
    total = sum(s["duration_minutes"] for s in db.clock_sessions.values()
                if s.get("truck_id") == truck["id"] and s["status"] == "BOOKED")
    truck["reserved_minutes"] = int(total)


def recompute_instructor_reserved(instr):
    total = sum(s["duration_minutes"] for s in db.clock_sessions.values()
                if s.get("instructor_id") == instr["id"] and s["status"] == "BOOKED")
    instr["reserved_minutes"] = int(total)


# ---------------------------------------------------------------------------
# Enrollment gate re-evaluation (PRD §3.4)
# ---------------------------------------------------------------------------
def evaluate_test_ready_gate(enr):
    """Upward to TEST_READY and downward back to TRAINING based on logged hours."""
    program = db.programs.get(enr["program_id"])
    if program is None:
        return
    meets = (
        enr["logged_classroom_hours"] >= program["classroom_required_hours"]
        and enr["logged_range_hours"] >= program["range_required_hours"]
        and enr["logged_road_hours"] >= program["road_required_hours"]
    )
    if enr["status"] == "TRAINING" and meets:
        enr["status"] = "TEST_READY"
        touch(enr)
    elif enr["status"] == "TEST_READY" and not meets:
        enr["status"] = "TRAINING"
        touch(enr)


def evaluate_prereq_gate(enr):
    """PREREQ_PENDING -> TRAINING when both flags true (PRD §3.2)."""
    if enr["status"] == "PREREQ_PENDING" and \
            enr["dot_medical_verified"] and enr["permit_verified"]:
        enr["status"] = "TRAINING"
        touch(enr)


def revert_training_to_prereq_pending(enr):
    """TRAINING -> PREREQ_PENDING when a verification flag goes false (PRD §3.2).

    Cancels all BOOKED clock sessions and releases reserved minutes.
    """
    if enr["status"] != "TRAINING":
        return
    if enr["dot_medical_verified"] and enr["permit_verified"]:
        return
    enr["status"] = "PREREQ_PENDING"
    touch(enr)
    cancel_booked_sessions(enr)


# ---------------------------------------------------------------------------
# Session cancellation cascade (PRD §3.2 revert, §3.9 withdraw)
# ---------------------------------------------------------------------------
def cancel_booked_sessions(enr):
    """Auto-CANCEL all BOOKED sessions; release reserved minutes."""
    affected_trucks = set()
    affected_instructors = set()
    for s in db.clock_sessions.values():
        if s["enrollment_id"] == enr["id"] and s["status"] == "BOOKED":
            s["status"] = "CANCELLED"
            touch(s)
            if s.get("truck_id"):
                affected_trucks.add(s["truck_id"])
            if s.get("instructor_id"):
                affected_instructors.add(s["instructor_id"])
    for tid in affected_trucks:
        t = db.trucks.get(tid)
        if t:
            recompute_truck_reserved(t)
            touch(t)
    for iid in affected_instructors:
        i = db.instructors.get(iid)
        if i:
            recompute_instructor_reserved(i)
            touch(i)
    recompute_projected_road_hours(enr)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def compute_weighted_score(pre_trip, basic_control, road):
    raw = (W_PRE_TRIP * Decimal(str(pre_trip))
           + W_BASIC_CONTROL * Decimal(str(basic_control))
           + W_ROAD * Decimal(str(road)))
    return round_half_up_2dp(raw)


def compute_finance_schedule(tuition_cents, term_months):
    """calc finance_schedule — order-sensitive (PRD §3.7)."""
    tuition = Decimal(tuition_cents)
    pct = Decimal("0.20") if tuition_cents >= DOWN_TIER_CENTS else Decimal("0.10")
    down_payment_cents = round_half_up_int(tuition * pct)
    financed_cents = tuition_cents - down_payment_cents
    total_interest_cents = round_half_up_int(
        Decimal(financed_cents) * MONTHLY_RATE * Decimal(term_months))
    total_repay = financed_cents + total_interest_cents
    installment_cents = floor_int(Decimal(total_repay) / Decimal(term_months))
    final_installment_cents = total_repay - installment_cents * (term_months - 1)
    return {
        "down_payment_cents": down_payment_cents,
        "financed_cents": financed_cents,
        "total_interest_cents": total_interest_cents,
        "installment_cents": installment_cents,
        "final_installment_cents": final_installment_cents,
    }


def compute_clawback(carrier, months_served):
    """calc reimbursement_clawback — linear decay (PRD §3.6)."""
    remaining = carrier["commitment_months"] - months_served
    if remaining <= 0:
        return 0
    raw = Decimal(carrier["reimbursement_cents"]) * Decimal(remaining) \
        / Decimal(carrier["commitment_months"])
    return round_half_up_int(raw)


# ---------------------------------------------------------------------------
# Sponsorship forfeit (PRD §3.6, §3.9)
# ---------------------------------------------------------------------------
def forfeit_offer(offer):
    """ACCEPTED -> FORFEITED: compute clawback, clear enrollment carrier."""
    carrier = db.carriers.get(offer["carrier_id"])
    offer["clawback_cents"] = compute_clawback(carrier, offer["months_served"]) \
        if carrier else 0
    offer["status"] = "FORFEITED"
    touch(offer)
    enr = db.enrollments.get(offer["enrollment_id"])
    if enr and enr.get("sponsoring_carrier_id") == offer["carrier_id"]:
        enr["sponsoring_carrier_id"] = None
        touch(enr)


def fulfill_if_committed(offer):
    """ACCEPTED -> FULFILLED when months_served >= commitment_months."""
    carrier = db.carriers.get(offer["carrier_id"])
    if carrier and offer["status"] == "ACCEPTED" \
            and offer["months_served"] >= carrier["commitment_months"]:
        offer["clawback_cents"] = 0
        offer["status"] = "FULFILLED"
        touch(offer)


# ---------------------------------------------------------------------------
# Document auto-expiry (PRD §3.8 clock advance)
# ---------------------------------------------------------------------------
def expire_documents_past(now):
    """APPROVED PrereqDocuments with expires_on <= now -> EXPIRED."""
    for doc in db.prereq_documents.values():
        if doc["status"] == "APPROVED":
            exp = parse_iso8601(doc["expires_on"])
            if now >= exp:
                apply_document_expiry(doc)


def apply_document_expiry(doc):
    """Move doc to EXPIRED, clear flag, possibly revert enrollment."""
    doc["status"] = "EXPIRED"
    touch(doc)
    enr = db.enrollments.get(doc["enrollment_id"])
    if not enr:
        return
    if doc["kind"] == "DOT_MEDICAL":
        enr["dot_medical_verified"] = False
    elif doc["kind"] == "CLP_PERMIT":
        enr["permit_verified"] = False
    touch(enr)
    revert_training_to_prereq_pending(enr)
