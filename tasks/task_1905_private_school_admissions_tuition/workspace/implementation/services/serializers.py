"""Entity -> JSON serializers. System/computed fields resolved at render time."""

import db

HOLDING_STATES = ("OFFERED", "CONTRACT_ISSUED", "ENROLLED")
APP_TERMINAL = ("DENIED", "DECLINED", "WITHDRAWN", "EXPIRED", "MELTED")


def _base(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def cycle_view(c):
    v = _base(c)
    v.update({
        "academic_year": c["academic_year"],
        "early_deadline_at": c["early_deadline_at"],
        "regular_deadline_at": c["regular_deadline_at"],
        "reenroll_response_deadline_at": c["reenroll_response_deadline_at"],
        "melt_deadline_at": c["melt_deadline_at"],
        "aid_budget_total_cents": c["aid_budget_total_cents"],
        "aid_committed_cents": cycle_committed(c["id"]),
        "pacing_cap_cents": pacing_cap(c),
        "status": c["status"],
    })
    return v


def section_view(s):
    held, aid_held = seat_counts(s["id"])
    v = _base(s)
    v.update({
        "cycle_id": s["cycle_id"],
        "grade_level": s["grade_level"],
        "capacity": s["capacity"],
        "tuition_cents": s["tuition_cents"],
        "max_aid_seat_pct": s["max_aid_seat_pct"],
        "seats_held": held,
        "aid_seats_held": aid_held,
        "seats_available": s["capacity"] - held,
    })
    return v


def applicant_view(a):
    v = _base(a)
    v.update({
        "family_id": a["family_id"],
        "first_name": a["first_name"],
        "last_name": a["last_name"],
        "date_of_birth": a["date_of_birth"],
        "legacy_parent": a["legacy_parent"],
    })
    return v


def student_view(s):
    v = _base(s)
    v.update({
        "family_id": s["family_id"],
        "first_name": s["first_name"],
        "last_name": s["last_name"],
        "current_grade_section_id": s["current_grade_section_id"],
        "status": s["status"],
        "source": s["source"],
        "re_enrolled_for_cycle_id": s["re_enrolled_for_cycle_id"],
    })
    return v


def application_view(a):
    v = _base(a)
    v.update({
        "applicant_id": a["applicant_id"],
        "cycle_id": a["cycle_id"],
        "grade_section_id": a["grade_section_id"],
        "round": a["round"],
        "status": a["status"],
        "submitted_at": a["submitted_at"],
        "composite_score": a["composite_score"],
        "preference_points": a["preference_points"],
        "sibling_verified": a["sibling_verified"],
        "offer_expires_at": a["offer_expires_at"] if a["status"] == "OFFERED" else None,
        "promoted_from_waitlist": a["promoted_from_waitlist"],
        "estimated_deposit_cents": (
            a["estimated_deposit_cents"]
            if a["status"] in ("OFFERED", "CONTRACT_ISSUED", "ENROLLED") else None
        ),
    })
    return v


def evaluation_view(e):
    v = _base(e)
    v.update({
        "application_id": e["application_id"],
        "kind": e["kind"],
        "scheduled_start": e["scheduled_start"],
        "scheduled_end": e["scheduled_end"],
        "interviewer_id": e["interviewer_id"],
        "test_session_id": e["test_session_id"],
        "score": e["score"],
        "status": e["status"],
    })
    return v


def test_session_view(t):
    v = _base(t)
    v.update({
        "cycle_id": t["cycle_id"],
        "session_start": t["session_start"],
        "session_end": t["session_end"],
        "room_capacity": t["room_capacity"],
        "booked_count": session_booked_count(t["id"]),
    })
    return v


def aid_view(a):
    v = _base(a)
    v.update({
        "application_id": a["application_id"],
        "reported_annual_income_cents": a["reported_annual_income_cents"],
        "household_size": a["household_size"],
        "verified_annual_income_cents": a["verified_annual_income_cents"],
        "verified_by_user_id": a["verified_by_user_id"],
        "verification_status": a["verification_status"],
        "provisional_award_cents": a["provisional_award_cents"],
        "final_award_cents": a["final_award_cents"],
        "award_status": a["award_status"],
        "appeal_reason": a["appeal_reason"],
    })
    return v


def contract_view(c):
    v = _base(c)
    v.update({
        "application_id": c["application_id"],
        "tuition_cents": c["tuition_cents"],
        "award_cents": c["award_cents"],
        "net_tuition_cents": c["net_tuition_cents"],
        "deposit_amount_cents": c["deposit_amount_cents"],
        "paid_cents": c["paid_cents"],
        "response_due_at": c["response_due_at"],
        "created_student_id": c["created_student_id"],
        "status": c["status"],
    })
    return v


def reenrollment_view(r):
    v = _base(r)
    v.update({
        "student_id": r["student_id"],
        "cycle_id": r["cycle_id"],
        "prior_tuition_cents": r["prior_tuition_cents"],
        "new_tuition_cents": r["new_tuition_cents"],
        "sibling_discount_cents": r["sibling_discount_cents"],
        "discounted_tuition_cents": r["discounted_tuition_cents"],
        "response_deadline_at": r["response_deadline_at"],
        "status": r["status"],
    })
    return v


# ---------------------------------------------------------------------------
# Derived counters (recomputed on read — the store is the ledger's source)
# ---------------------------------------------------------------------------

def cycle_committed(cycle_id: str) -> int:
    """Sum of final_award_cents over this cycle's ACCEPTED aid applications."""
    total = 0
    for a in db.aid_applications.values():
        if a["award_status"] != "ACCEPTED" or a["final_award_cents"] is None:
            continue
        app = db.applications.get(a["application_id"])
        if app and app["cycle_id"] == cycle_id:
            total += a["final_award_cents"]
    return total


def pacing_cap(cycle) -> int:
    from decimal import Decimal, ROUND_HALF_UP
    budget = cycle["aid_budget_total_cents"]
    status = cycle["status"]
    if status in ("DRAFT", "OPEN"):
        return int((Decimal("0.40") * Decimal(budget)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if status == "EARLY_CLOSED":
        return int((Decimal("0.75") * Decimal(budget)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return budget  # CLOSED / ARCHIVED


def seat_counts(section_id: str):
    held = 0
    aid_held = 0
    for app in db.applications.values():
        if app["grade_section_id"] != section_id or app["status"] not in HOLDING_STATES:
            continue
        held += 1
        if is_aid_seeking(app["id"]):
            aid_held += 1
    return held, aid_held


def is_aid_seeking(application_id: str) -> bool:
    aid = find_aid_for_application(application_id)
    return aid is not None and aid["award_status"] != "RELEASED"


def session_booked_count(session_id: str) -> int:
    n = 0
    for e in db.evaluations.values():
        if e["kind"] == "TEST" and e["test_session_id"] == session_id and e["status"] != "CANCELLED":
            n += 1
    return n


def find_aid_for_application(application_id: str):
    for a in db.aid_applications.values():
        if a["application_id"] == application_id:
            return a
    return None


def find_live_contract_for_application(application_id: str):
    for c in db.contracts.values():
        if c["application_id"] == application_id and c["status"] not in ("CANCELLED", "LAPSED"):
            return c
    return None
