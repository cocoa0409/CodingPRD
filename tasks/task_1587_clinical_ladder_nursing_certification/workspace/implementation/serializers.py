"""Entity serialization. Computed fields (tenure_years) resolved on read."""

from response import iso_render
from services.calculations import tenure_years as calc_tenure_years


def nurse_view(n):
    return {
        "id": n["id"],
        "employee_code": n["employee_code"],
        "full_name": n["full_name"],
        "hire_date": iso_render(n["hire_date"]),
        "home_unit": n["home_unit"],
        "current_level": n["current_level"],
        "differential_status": n["differential_status"],
        "differential_activated_at": iso_render(n["differential_activated_at"]),
        "tenure_years": calc_tenure_years(n),
        "retention_risk_score": n["retention_risk_score"],
        "created_at": iso_render(n["created_at"]),
        "updated_at": iso_render(n["updated_at"]),
        "version": n["version"],
    }


def criterion_view(c):
    return {
        "id": c["id"],
        "target_level": c["target_level"],
        "min_portfolio_score": c["min_portfolio_score"],
        "min_participation_points": c["min_participation_points"],
        "required_certification_track": c["required_certification_track"],
        "differential_monthly_cents": c["differential_monthly_cents"],
        "effective_from": iso_render(c["effective_from"]),
        "effective_until": iso_render(c["effective_until"]),
        "created_at": iso_render(c["created_at"]),
        "updated_at": iso_render(c["updated_at"]),
        "version": c["version"],
    }


def participation_event_view(e):
    return {
        "id": e["id"],
        "nurse_id": e["nurse_id"],
        "event_kind": e["event_kind"],
        "points": e["points"],
        "occurred_on": iso_render(e["occurred_on"]),
        "status": e["status"],
        "created_at": iso_render(e["created_at"]),
        "updated_at": iso_render(e["updated_at"]),
        "version": e["version"],
    }


def certification_view(c):
    return {
        "id": c["id"],
        "nurse_id": c["nurse_id"],
        "track": c["track"],
        "certifying_body": c["certifying_body"],
        "exam_fee_cents": c["exam_fee_cents"],
        "obtained_on": iso_render(c["obtained_on"]),
        "expires_on": iso_render(c["expires_on"]),
        "status": c["status"],
        "renewal_of_id": c["renewal_of_id"],
        "created_at": iso_render(c["created_at"]),
        "updated_at": iso_render(c["updated_at"]),
        "version": c["version"],
    }


def claim_view(c):
    return {
        "id": c["id"],
        "certification_id": c["certification_id"],
        "claimed_amount_cents": c["claimed_amount_cents"],
        "approved_amount_cents": c["approved_amount_cents"],
        "status": c["status"],
        "denial_reason": c["denial_reason"],
        "fiscal_year": c["fiscal_year"],
        "created_at": iso_render(c["created_at"]),
        "updated_at": iso_render(c["updated_at"]),
        "version": c["version"],
    }


def bonus_view(b):
    return {
        "id": b["id"],
        "certification_id": b["certification_id"],
        "bonus_amount_cents": b["bonus_amount_cents"],
        "status": b["status"],
        "clawback_reason": b["clawback_reason"],
        "created_at": iso_render(b["created_at"]),
        "updated_at": iso_render(b["updated_at"]),
        "version": b["version"],
    }


def application_view(a):
    return {
        "id": a["id"],
        "nurse_id": a["nurse_id"],
        "target_level": a["target_level"],
        "portfolio_narrative": a["portfolio_narrative"],
        "criterion_id": a["criterion_id"],
        "status": a["status"],
        "submitted_at": iso_render(a["submitted_at"]),
        "review_cycle": a["review_cycle"],
        "aggregate_score": a["aggregate_score"],
        "participation_snapshot_points": a["participation_snapshot_points"],
        "created_at": iso_render(a["created_at"]),
        "updated_at": iso_render(a["updated_at"]),
        "version": a["version"],
    }


def assignment_view(a):
    return {
        "id": a["id"],
        "application_id": a["application_id"],
        "reviewer_nurse_id": a["reviewer_nurse_id"],
        "dimension_scores": a["dimension_scores"],
        "submitted_at": iso_render(a["submitted_at"]),
        "status": a["status"],
        "created_at": iso_render(a["created_at"]),
        "updated_at": iso_render(a["updated_at"]),
        "version": a["version"],
    }


def decision_view(d):
    # Append-only audit row: id + created_at only from the common set
    return {
        "id": d["id"],
        "application_id": d["application_id"],
        "decided_by_admin_id": d["decided_by_admin_id"],
        "outcome": d["outcome"],
        "criterion_version_snapshot": d["criterion_version_snapshot"],
        "decided_at": iso_render(d["decided_at"]),
        "created_at": iso_render(d["created_at"]),
    }


def review_view(r):
    return {
        "id": r["id"],
        "nurse_id": r["nurse_id"],
        "review_year": r["review_year"],
        "maintenance_score": r["maintenance_score"],
        "outcome": r["outcome"],
        "resolution_reason": r["resolution_reason"],
        "created_at": iso_render(r["created_at"]),
        "updated_at": iso_render(r["updated_at"]),
        "version": r["version"],
    }


def budget_line_view(b):
    return {
        "id": b["id"],
        "unit": b["unit"],
        "fiscal_year": b["fiscal_year"],
        "allocated_cents": b["allocated_cents"],
        "committed_cents": b["committed_cents"],
        "forecast_cents": b["forecast_cents"],
        "forecast_variant": b["forecast_variant"],
        "created_at": iso_render(b["created_at"]),
        "updated_at": iso_render(b["updated_at"]),
        "version": b["version"],
    }


def snapshot_view(s):
    # Immutable capture: id + created_at only from the common set
    return {
        "id": s["id"],
        "captured_at": iso_render(s["captured_at"]),
        "unit": s["unit"],
        "headcount_by_level": s["headcount_by_level"],
        "avg_retention_risk_score": s["avg_retention_risk_score"],
        "demotion_rate": s["demotion_rate"],
        "created_at": iso_render(s["created_at"]),
    }
