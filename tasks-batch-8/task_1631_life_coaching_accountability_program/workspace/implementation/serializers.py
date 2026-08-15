"""Entity serializers. Common fields (PRD §2.4): id, created_at, updated_at,
version — except the four append-style records (FitAssessment, Installment,
HabitCheckIn, CohortMembership) which carry only id and created_at.

Derived fields (PRD §2.10) are computed at read time from stored rows:
Enrollment.sessions_consumed / sessions_remaining / paid_cents / refunded_cents,
Goal.achieved_count, Client.engagement_score.
"""
import uuid

from db import store
from timeutil import fmt_dt, fmt_date
import calc


def new_id():
    return str(uuid.uuid4())


def base_row():
    """Common system fields for a versioned resource."""
    from timeutil import now_iso
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_created_sort": store.next_seq(),
    }


def append_row():
    """System fields for an append-style record (no updated_at / version)."""
    from timeutil import now_iso
    return {
        "id": new_id(),
        "created_at": now_iso(),
        "_created_sort": store.next_seq(),
    }


def touch(row):
    """Refresh updated_at and bump version on any mutation (PRD §2.4/§2.10),
    including mutations reached through a cascade."""
    from timeutil import now_iso
    row["updated_at"] = now_iso()
    row["version"] += 1


def _strip_internal(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


# ---------------------------------------------------------------- serializers

def coach(c):
    return {
        "id": c["id"],
        "display_name": c["display_name"],
        "email": c["email"],
        "credential_level": c["credential_level"],
        "credential_expires_on": fmt_date(c["credential_expires_on"]),
        "credential_status": c["credential_status"],
        "ethics_status": c["ethics_status"],
        "max_concurrent_clients": c["max_concurrent_clients"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def client(c, score_variant=None):
    variant = "provisional" if score_variant == "provisional" else "final"
    return {
        "id": c["id"],
        "full_name": c["full_name"],
        "email": c["email"],
        "timezone": c["timezone"],
        "client_status": c["client_status"],
        "engagement_score": calc.engagement_score(c["id"], variant),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def tier(t):
    return {
        "id": t["id"],
        "tier_code": t["tier_code"],
        "tier_type": t["tier_type"],
        "session_count": t["session_count"],
        "price_cents": t["price_cents"],
        "duration_days": t["duration_days"],
        "installment_count_allowed": t["installment_count_allowed"],
        "reschedule_cap": t["reschedule_cap"],
        "tier_status": t["tier_status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def discovery_call(d):
    return {
        "id": d["id"],
        "client_id": d["client_id"],
        "coach_id": d["coach_id"],
        "scheduled_start": fmt_dt(d["scheduled_start"]),
        "duration_minutes": d["duration_minutes"],
        "call_status": d["call_status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def fit_assessment(f):
    return {
        "id": f["id"],
        "discovery_call_id": f["discovery_call_id"],
        "scope_fit": f["scope_fit"],
        "commitment_score": f["commitment_score"],
        "outcome": f["outcome"],
        "assessor_coach_id": f["assessor_coach_id"],
        "created_at": f["created_at"],
    }


def enrollment(e):
    return {
        "id": e["id"],
        "client_id": e["client_id"],
        "coach_id": e["coach_id"],
        "program_tier_id": e["program_tier_id"],
        "discovery_call_id": e["discovery_call_id"],
        "lifecycle_status": e["lifecycle_status"],
        "payment_status": e["payment_status"],
        "activated_at": fmt_dt(e["activated_at"]) if e["activated_at"] else None,
        "sessions_total": e["sessions_total"],
        "sessions_total_price_basis": e["sessions_total_price_basis"],
        "sessions_consumed": calc.sessions_consumed(e["id"]),
        "sessions_remaining": calc.sessions_remaining(e),
        "late_reschedules_used": e["late_reschedules_used"],
        "pauses_used": e["pauses_used"],
        "paid_cents": calc.paid_cents(e["id"]),
        "refunded_cents": calc.refunded_cents(e["id"]),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def installment(i):
    return {
        "id": i["id"],
        "enrollment_id": i["enrollment_id"],
        "sequence_no": i["sequence_no"],
        "amount_cents": i["amount_cents"],
        "due_on": fmt_date(i["due_on"]) if i["due_on"] else None,
        "installment_status": i["installment_status"],
        "created_at": i["created_at"],
    }


def session(s):
    return {
        "id": s["id"],
        "enrollment_id": s["enrollment_id"],
        "coach_id": s["coach_id"],
        "scheduled_start": fmt_dt(s["scheduled_start"]),
        "duration_minutes": s["duration_minutes"],
        "buffer_minutes": s["buffer_minutes"],
        "session_status": s["session_status"],
        "successor_session_id": s["successor_session_id"],
        "is_late_reschedule": s["is_late_reschedule"],
        "cohort_id": s["cohort_id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def goal(g):
    achieved = sum(1 for h in store.check_ins.values()
                   if h["goal_id"] == g["id"] and h["completed"] is True)
    return {
        "id": g["id"],
        "enrollment_id": g["enrollment_id"],
        "title": g["title"],
        "target_count": g["target_count"],
        "goal_status": g["goal_status"],
        "achieved_count": achieved,
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def check_in(h):
    return {
        "id": h["id"],
        "goal_id": h["goal_id"],
        "check_in_date": fmt_date(h["check_in_date"]),
        "completed": h["completed"],
        "created_at": h["created_at"],
    }


def cohort(c):
    return {
        "id": c["id"],
        "coach_id": c["coach_id"],
        "title": c["title"],
        "capacity": c["capacity"],
        "window_start": fmt_date(c["window_start"]),
        "window_end": fmt_date(c["window_end"]),
        "cohort_status": c["cohort_status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def membership(m):
    return {
        "id": m["id"],
        "cohort_id": m["cohort_id"],
        "enrollment_id": m["enrollment_id"],
        "member_status": m["member_status"],
        "joined_at": m["joined_at"],
        "created_at": m["created_at"],
    }


def testimonial(t):
    return {
        "id": t["id"],
        "enrollment_id": t["enrollment_id"],
        "outcome_rating": t["outcome_rating"],
        "body_text": t["body_text"],
        "consent_status": t["consent_status"],
        "publish_status": t["publish_status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def refund_request(r):
    return {
        "id": r["id"],
        "enrollment_id": r["enrollment_id"],
        "requested_by_role": r["requested_by_role"],
        "basis": r["basis"],
        "amount_cents": r["amount_cents"],
        "refund_status": r["refund_status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
