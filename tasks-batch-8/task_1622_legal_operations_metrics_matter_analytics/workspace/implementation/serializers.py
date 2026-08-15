"""Resource serializers — exact public field sets per SCAFFOLD entity table.
Internal bookkeeping fields (``_seq``, ``_creator_id``, ``_activated_at``,
``_panel``) never leak into responses.
"""
from services.aggregates import active_fiscal_period_id, compute_dashboard_panel


def _common(e):
    return {"id": e["id"], "created_at": e["created_at"], "updated_at": e["updated_at"], "version": e["version"]}


def department_view(d):
    v = _common(d)
    v.update({
        "name": d["name"],
        "budget_warning_pct": d["budget_warning_pct"],
        "budget_critical_pct": d["budget_critical_pct"],
        "deflection_target_pct": d["deflection_target_pct"],
        "active_fiscal_period_id": active_fiscal_period_id(),
    })
    return v


def period_view(p):
    v = _common(p)
    v.update({
        "label": p["label"],
        "start_date": p["start_date"],
        "end_date": p["end_date"],
        "status": p["status"],
        "reopen_count": p["reopen_count"],
        "total_actual_spend_cents": p["total_actual_spend_cents"],
        "total_accrual_cents": p["total_accrual_cents"],
    })
    return v


def practice_area_view(a):
    v = _common(a)
    v.update({"code": a["code"], "display_name": a["display_name"], "status": a["status"]})
    return v


def matter_type_view(t):
    v = _common(t)
    v.update({
        "practice_area_id": t["practice_area_id"],
        "code": t["code"],
        "display_name": t["display_name"],
        "default_budget_cents": t["default_budget_cents"],
    })
    return v


def firm_view(f):
    v = _common(f)
    v.update({
        "name": f["name"],
        "tier": f["tier"],
        "blended_hourly_rate_cents": f["blended_hourly_rate_cents"],
        "status": f["status"],
    })
    return v


def counsel_view(c):
    v = _common(c)
    v.update({
        "full_name": c["full_name"],
        "email": c["email"],
        "annual_capacity_hours": c["annual_capacity_hours"],
        "loaded_hourly_cost_cents": c["loaded_hourly_cost_cents"],
        "status": c["status"],
    })
    return v


def matter_view(m):
    v = _common(m)
    v.update({
        "matter_number": m["matter_number"],
        "title": m["title"],
        "practice_area_id": m["practice_area_id"],
        "matter_type_id": m["matter_type_id"],
        "fiscal_period_id": m["fiscal_period_id"],
        "primary_firm_id": m["primary_firm_id"],
        "lead_counsel_id": m["lead_counsel_id"],
        "status": m["status"],
        "budget_cents": m["budget_cents"],
        "actual_spend_cents": m["actual_spend_cents"],
        "accrual_outstanding_cents": m["accrual_outstanding_cents"],
        "cycle_days": m["cycle_days"],
    })
    return v


def assignment_view(a):
    v = _common(a)
    v.update({
        "matter_id": a["matter_id"],
        "counsel_id": a["counsel_id"],
        "allocated_hours": a["allocated_hours"],
        "status": a["status"],
    })
    return v


def budget_view(b):
    v = _common(b)
    v.update({
        "fiscal_period_id": b["fiscal_period_id"],
        "practice_area_id": b["practice_area_id"],
        "matter_type_id": b["matter_type_id"],
        "allocated_cents": b["allocated_cents"],
        "consumed_cents": b["consumed_cents"],
        "posture": b["posture"],
    })
    return v


def accrual_view(a):
    v = _common(a)
    v.update({
        "matter_id": a["matter_id"],
        "fiscal_period_id": a["fiscal_period_id"],
        "firm_id": a["firm_id"],
        "amount_cents": a["amount_cents"],
        "status": a["status"],
    })
    return v


def invoice_view(i):
    v = _common(i)
    v.update({
        "matter_id": i["matter_id"],
        "firm_id": i["firm_id"],
        "fiscal_period_id": i["fiscal_period_id"],
        "invoice_number": i["invoice_number"],
        "amount_cents": i["amount_cents"],
        "payment_status": i["payment_status"],
        "accrual_match_status": i["accrual_match_status"],
        "matched_accrual_id": i["matched_accrual_id"],
    })
    return v


def spend_line_view(l):
    # Spend lines: id + created_at only, no updated_at / version (PRD section 2.4).
    return {
        "id": l["id"],
        "created_at": l["created_at"],
        "matter_id": l["matter_id"],
        "fiscal_period_id": l["fiscal_period_id"],
        "firm_id": l["firm_id"],
        "invoice_id": l["invoice_id"],
        "posting_date": l["posting_date"],
        "amount_cents": l["amount_cents"],
        "source_status": l["source_status"],
        "reversal_of_id": l["reversal_of_id"],
    }


def dashboard_view(d):
    # DRAFT dashboards are provisional: recompute live on every read.
    panel = compute_dashboard_panel(d["fiscal_period_id"]) if d["status"] == "DRAFT" else d["_panel"]
    v = _common(d)
    v.update({
        "fiscal_period_id": d["fiscal_period_id"],
        "snapshot_label": d["snapshot_label"],
        "status": d["status"],
    })
    v.update(panel)
    return v
