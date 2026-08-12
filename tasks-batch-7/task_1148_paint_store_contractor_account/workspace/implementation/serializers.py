"""Entity serializers. Computed fields are derived at read time via services."""
import db
import services as svc
from util import fmt_dt


def _common(e):
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def _event_common(e):
    return {"id": e["id"], "created_at": fmt_dt(e["created_at"])}


def ser_account(a):
    out = {
        "company_name": a["company_name"],
        "status": a["status"],
        "tier": a["tier"],
        "credit_limit_cents": a["credit_limit_cents"],
        "outstanding_balance_cents": svc.outstanding_balance(a["id"]),
        "loyalty_points_balance": svc.loyalty_balance(a["id"]),
        "ytd_net_volume_cents": svc.ytd_net_volume(a["id"]),
        "lifetime_rebate_paid_cents": svc.lifetime_rebate_paid(a["id"]),
    }
    out.update(_common(a))
    return out


def ser_job(j):
    out = {
        "contractor_account_id": j["contractor_account_id"],
        "jurisdiction_id": j["jurisdiction_id"],
        "job_name": j["job_name"],
        "site_address": j["site_address"],
        "budget_cap_cents": j["budget_cap_cents"],
        "status": j["status"],
        "spent_cents": svc.job_spent(j["id"]),
    }
    out.update(_common(j))
    return out


def ser_jurisdiction(j):
    out = {"code": j["code"], "name": j["name"]}
    out.update(_common(j))
    return out


def ser_voc_rule(r):
    out = {
        "jurisdiction_id": r["jurisdiction_id"],
        "category": r["category"],
        "max_voc_gpl": r["max_voc_gpl"],
        "effective_from": fmt_dt(r["effective_from"]),
        "effective_to": fmt_dt(r["effective_to"]),
    }
    out.update(_common(r))
    return out


def ser_product(p):
    out = {
        "sku": p["sku"],
        "name": p["name"],
        "category": p["category"],
        "voc_gpl": p["voc_gpl"],
        "list_price_cents": p["list_price_cents"],
        "tintable": p["tintable"],
        "status": p["status"],
        "replacement_product_id": p["replacement_product_id"],
    }
    out.update(_common(p))
    return out


def ser_formula(f):
    out = {
        "product_id": f["product_id"],
        "color_code": f["color_code"],
        "name": f["name"],
        "shots": f["shots"],
        "revision": f["revision"],
        "source": f["source"],
        "status": f["status"],
        "supersedes_formula_id": f["supersedes_formula_id"],
    }
    out.update(_common(f))
    return out


def ser_match(m):
    out = {
        "contractor_account_id": m["contractor_account_id"],
        "product_id": m["product_id"],
        "sample_reference": m["sample_reference"],
        "status": m["status"],
        "iteration_count": m["iteration_count"],
        "formula_id": m["formula_id"],
    }
    out.update(_common(m))
    return out


def ser_bulletin(b):
    out = {
        "product_id": b["product_id"],
        "replacement_product_id": b["replacement_product_id"],
        "title": b["title"],
        "effective_date": fmt_dt(b["effective_date"]),
        "status": b["status"],
        "published_at": fmt_dt(b["published_at"]),
        "effected_at": fmt_dt(b["effected_at"]),
    }
    out.update(_common(b))
    return out


def ser_spec_sheet(s):
    ordered_pct, delivered_pct = svc.sheet_pull_through(s["id"])
    out = {
        "project_code": s["project_code"],
        "architect_name": s["architect_name"],
        "title": s["title"],
        "status": s["status"],
        "rejection_reason": s["rejection_reason"],
        "approved_at": fmt_dt(s["approved_at"]),
        "supersedes_spec_sheet_id": s["supersedes_spec_sheet_id"],
        "pull_through_ordered_pct": ordered_pct,
        "pull_through_delivered_pct": delivered_pct,
    }
    out.update(_common(s))
    return out


def ser_spec_line(l):
    out = {
        "spec_sheet_id": l["spec_sheet_id"],
        "product_id": l["product_id"],
        "specified_qty": l["specified_qty"],
        "obsoleted": l["obsoleted"],
        "ordered_qty": svc.spec_line_ordered_qty(l["id"]),
        "delivered_qty": svc.spec_line_delivered_qty(l["id"]),
    }
    out.update(_common(l))
    return out


def ser_order(o):
    out = {
        "contractor_account_id": o["contractor_account_id"],
        "job_account_id": o["job_account_id"],
        "payment_status": o["payment_status"],
        "fulfillment_status": o["fulfillment_status"],
        "tier_snapshot": o["tier_snapshot"],
        "subtotal_cents": o["subtotal_cents"],
        "discount_cents": o["discount_cents"],
        "tax_cents": o["tax_cents"],
        "total_cents": o["total_cents"],
        "refunded_cents": svc.order_refunded_cents(o["id"]),
        "paid_at": fmt_dt(o["paid_at"]),
    }
    out.update(_common(o))
    return out


def ser_order_line(l):
    out = {
        "order_id": l["order_id"],
        "product_id": l["product_id"],
        "formula_id": l["formula_id"],
        "spec_line_id": l["spec_line_id"],
        "quantity": l["quantity"],
        "returned_quantity": l["returned_quantity"],
        "unit_list_price_cents": l["unit_list_price_cents"],
        "unit_price_cents": l["unit_price_cents"],
        "line_total_cents": l["line_total_cents"],
        "is_custom_tint": l["is_custom_tint"],
    }
    out.update(_common(l))
    return out


def ser_return_record(rr):
    out = {
        "order_line_id": rr["order_line_id"],
        "quantity": rr["quantity"],
        "refund_merchandise_cents": rr["refund_merchandise_cents"],
        "tax_refund_cents": rr["tax_refund_cents"],
        "total_credit_cents": rr["total_credit_cents"],
    }
    out.update(_event_common(rr))
    return out


def ser_delivery(d):
    out = {
        "order_id": d["order_id"],
        "job_account_id": d["job_account_id"],
        "window_start": fmt_dt(d["window_start"]),
        "window_end": fmt_dt(d["window_end"]),
        "status": d["status"],
        "failure_reason": d["failure_reason"],
        "dispatched_at": fmt_dt(d["dispatched_at"]),
        "delivered_at": fmt_dt(d["delivered_at"]),
    }
    out.update(_common(d))
    return out


def ser_statement(s):
    out = {
        "contractor_account_id": s["contractor_account_id"],
        "period_start": fmt_dt(s["period_start"]),
        "period_end": fmt_dt(s["period_end"]),
        "status": s["status"],
        "provisional_amount_cents": s["provisional_amount_cents"],
        "final_amount_cents": s["final_amount_cents"],
        "adjustment_cents": s["adjustment_cents"],
        "payable_cents": s["payable_cents"],
        "period_net_cents": s["period_net_cents"],
        "paid_at": fmt_dt(s["paid_at"]),
    }
    out.update(_common(s))
    return out


def ser_loyalty_txn(t):
    out = {
        "contractor_account_id": t["contractor_account_id"],
        "order_id": t["order_id"],
        "type": t["type"],
        "points_delta": t["points_delta"],
        "note": t["note"],
    }
    out.update(_event_common(t))
    return out


def ser_mistint(m):
    out = {
        "product_id": m["product_id"],
        "formula_id": m["formula_id"],
        "quantity": m["quantity"],
        "cost_basis_cents": m["cost_basis_cents"],
        "list_price_cents": m["list_price_cents"],
        "current_price_cents": svc.mistint_price_now(m),
        "status": m["status"],
        "sold_price_cents": m["sold_price_cents"],
        "sold_to_contractor_account_id": m["sold_to_contractor_account_id"],
    }
    out.update(_common(m))
    return out


def sorted_rows(rows):
    """List responses are always sorted by created_at ascending (insertion-seq
    tiebreak for rows created at the same logical instant)."""
    return sorted(rows, key=lambda e: (e["created_at"], e["_seq"]))
