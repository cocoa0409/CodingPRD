"""Public JSON views for each entity.

Computed fields (SCAFFOLD source: computed) are derived here on every read so
the served representation always agrees with the underlying rows (PRD §2.5).
Internal bookkeeping keys (prefixed with '_') are never exposed.
"""
from db import db
from services import derive, calc


def _common(record):
    out = {
        "id": record["id"],
        "created_at": record["created_at"],
    }
    if "version" in record:
        out["updated_at"] = record["updated_at"]
        out["version"] = record["version"]
    return out


def cohort_view(c):
    out = _common(c)
    committed = derive.seats_committed(c["id"])
    out.update({
        "name": c["name"],
        "track": c["track"],
        "capacity": c["capacity"],
        "tuition_sticker_cents": c["tuition_sticker_cents"],
        "start_date": c["start_date"],
        "end_date": c["end_date"],
        "cirr_period_label": c["cirr_period_label"],
        "status": c["status"],
        "seats_committed": committed,
        "seats_available": c["capacity"] - committed,
    })
    return out


def applicant_view(a):
    out = _common(a)
    out.update({
        "cohort_id": a["cohort_id"],
        "full_name": a["full_name"],
        "email": a["email"],
        "reported_prior_income_cents": a["reported_prior_income_cents"],
        "status": a["status"],
        "admitted_at": a.get("admitted_at"),
    })
    return out


def enrollment_view(e):
    out = _common(e)
    attendance_pct, progress_pct = derive.enrollment_attendance(e["id"])
    isa_status = None
    if e["financing_choice"] == "ISA":
        contract = next(
            (c for c in db.isa_contracts.values() if c["enrollment_id"] == e["id"]),
            None,
        )
        if contract is not None:
            isa_status = contract["status"]
    out.update({
        "applicant_id": e["applicant_id"],
        "cohort_id": e["cohort_id"],
        "financing_choice": e["financing_choice"],
        "status": e["status"],
        "attendance_pct": attendance_pct,
        "progress_pct": progress_pct,
        "enrolled_at": e["enrolled_at"],
        "isa_status": isa_status,
    })
    return out


def isa_contract_view(c):
    derive.recompute_isa_ledger(c)
    out = _common(c)
    latest = derive.latest_income_report(c["id"])
    out.update({
        "enrollment_id": c["enrollment_id"],
        "income_share_pct": c["income_share_pct"],
        "cap_cents": c["cap_cents"],
        "term_months": c["term_months"],
        "income_threshold_cents": c["income_threshold_cents"],
        "status": c["status"],
        "payments_made_count": c["_payments_made_count"],
        "amount_paid_cents": c["_amount_paid_cents"],
        "remaining_cap_cents": c["_remaining_cap_cents"],
        "projected_payoff_cents": calc.projected_payoff(c, latest),
    })
    return out


def scholarship_view(s):
    out = _common(s)
    out.update({
        "enrollment_id": s["enrollment_id"],
        "kind": s["kind"],
        "cap_reduction_pct": s["cap_reduction_pct"],
        "status": s["status"],
    })
    return out


def deposit_view(d):
    out = _common(d)
    out.update({
        "enrollment_id": d["enrollment_id"],
        "amount_cents": d["amount_cents"],
        "status": d["status"],
        "refunded_amount_cents": d.get("refunded_amount_cents", 0),
    })
    return out


def income_report_view(r):
    out = _common(r)
    out.update({
        "isa_contract_id": r["isa_contract_id"],
        "period_start": r["period_start"],
        "period_end": r["period_end"],
        "gross_income_cents": r["gross_income_cents"],
        "employment_status": r["employment_status"],
        "obligation_cents": r["obligation_cents"],
        "payment_id": r.get("payment_id"),
    })
    return out


def payment_view(p):
    out = _common(p)
    if p["refund_status"] == "REFUNDED":
        rollup = "REVERSED"
    else:
        rollup = p["collection_status"]
    out.update({
        "isa_contract_id": p["isa_contract_id"],
        "income_report_id": p["income_report_id"],
        "amount_cents": p["amount_cents"],
        "collection_status": p["collection_status"],
        "refund_status": p["refund_status"],
        "status": rollup,
    })
    return out


def deferment_view(d):
    out = _common(d)
    out.update({
        "isa_contract_id": d["isa_contract_id"],
        "reason": d["reason"],
        "period_start": d["period_start"],
        "period_end": d["period_end"],
        "status": d["status"],
    })
    return out


def refund_view(r):
    out = _common(r)
    out.update({
        "enrollment_id": r["enrollment_id"],
        "reason": r["reason"],
        "requested_at": r["requested_at"],
        "gross_refund_cents": r.get("gross_refund_cents"),
        "net_refund_cents": r.get("net_refund_cents"),
        "status": r["status"],
    })
    return out


def placement_view(p):
    out = _common(p)
    out.update({
        "enrollment_id": p["enrollment_id"],
        "category": p["category"],
        "annual_salary_cents": p.get("annual_salary_cents"),
        "placement_days": p.get("placement_days"),
        "reported_at": p["reported_at"],
        "cirr_eligible": p["cirr_eligible"],
    })
    return out


def attendance_view(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "enrollment_id": a["enrollment_id"],
        "session_date": a["session_date"],
        "present": a["present"],
        "cumulative_progress_pct": a["cumulative_progress_pct"],
    }


def cirr_report_view(c):
    out = _common(c)
    if c["status"] == "PUBLISHED":
        # frozen snapshot taken at publish time
        out.update({
            "cohort_id": c["cohort_id"],
            "denominator_basis": c["denominator_basis"],
            "graduates_count": c["graduates_count"],
            "enrolled_count": c["enrolled_count"],
            "placed_count": c["placed_count"],
            "placement_rate": c["placement_rate"],
            "status": c["status"],
        })
        return out
    counts = compute_cirr_counts(c["cohort_id"], c["denominator_basis"])
    out.update({
        "cohort_id": c["cohort_id"],
        "denominator_basis": c["denominator_basis"],
        "graduates_count": counts["graduates_count"],
        "enrolled_count": counts["enrolled_count"],
        "placed_count": counts["placed_count"],
        "placement_rate": counts["placement_rate"],
        "status": c["status"],
    })
    return out


def compute_cirr_counts(cohort_id, denominator_basis):
    grad_enrollments = [
        e for e in db.enrollments.values()
        if e["cohort_id"] == cohort_id and e["status"] == "GRADUATED"
    ]
    grad_ids = {e["id"] for e in grad_enrollments}
    graduates_count = len(grad_enrollments)
    enrolled_count = sum(
        1 for e in db.enrollments.values()
        if e["cohort_id"] == cohort_id
        and e["status"] in ("ACTIVE", "GRADUATED", "DISMISSED", "WITHDRAWN")
    )
    placed_count = sum(
        1 for p in db.placement_outcomes.values()
        if p["enrollment_id"] in grad_ids and p["cirr_eligible"]
    )
    denom = graduates_count if denominator_basis == "GRADUATES_ONLY" else enrolled_count
    rate = calc.placement_rate(placed_count, denom)
    return {
        "graduates_count": graduates_count,
        "enrolled_count": enrolled_count,
        "placed_count": placed_count,
        "placement_rate": rate,
    }
