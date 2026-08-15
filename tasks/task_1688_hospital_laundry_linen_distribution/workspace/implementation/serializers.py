"""Entity serializers — exact field sets from the scaffold entity table."""
import services
from util import fmt_ts


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_ts(rec["created_at"]),
        "updated_at": fmt_ts(rec["updated_at"]),
        "version": rec["version"],
    }


def facility_out(f):
    out = {
        "name": f["name"],
        "rate_per_lb_cents": f["rate_per_lb_cents"],
        "isolation_surcharge_pct": f["isolation_surcharge_pct"],
        "monthly_cap_cents": f["monthly_cap_cents"],
        "surge_posture": f["surge_posture"],
        "credit_balance_cents": f["credit_balance_cents"],
    }
    out.update(_common(f))
    return out


def unit_out(u):
    out = {
        "facility_id": u["facility_id"],
        "name": u["name"],
        "unit_tier": u["unit_tier"],
        "quality_flag": services.unit_quality_flag(u),
    }
    out.update(_common(u))
    return out


def stock_out(s):
    out = {
        "facility_id": s["facility_id"],
        "sku": s["sku"],
        "display_name": s["display_name"],
        "category": s["category"],
        "piece_weight_lbs": s["piece_weight_lbs"],
        "unit_cost_cents": s["unit_cost_cents"],
        "max_wash_cycles": s["max_wash_cycles"],
        "reorder_point_pieces": s["reorder_point_pieces"],
        "opening_pieces": s["opening_pieces"],
        "opening_reserve_pieces": s["opening_reserve_pieces"],
        "in_circulation": s["in_circulation"],
        "in_wash": s["in_wash"],
        "reserve_pieces": s["reserve_pieces"],
        "retired_pieces": s["retired_pieces"],
        "lost_pieces": s["lost_pieces"],
        "wash_cycles_completed": s["wash_cycles_completed"],
        "posture": services.stock_posture(s),
        "shrinkage_status": s["shrinkage_status"],
    }
    out.update(_common(s))
    return out


def par_out(p):
    out = {
        "unit_id": p["unit_id"],
        "stock_id": p["stock_id"],
        "base_par_quantity": p["base_par_quantity"],
        "cart_cycle": p["cart_cycle"],
        "on_hand": p["on_hand"],
        "effective_par": p["effective_par"],
    }
    out.update(_common(p))
    return out


def _piece_lines(lines):
    return [{"stock_id": e["stock_id"], "pieces": e["pieces"]} for e in lines]


def run_out(r):
    out = {
        "unit_id": r["unit_id"],
        "manifest_id": r["manifest_id"],
        "scheduled_start": fmt_ts(r["scheduled_start"]),
        "scheduled_end": fmt_ts(r["scheduled_end"]),
        "status": r["status"],
        "soiled_lines": _piece_lines(r["soiled_lines"]),
        "restock_lines": _piece_lines(r["restock_lines"]),
        "shortage_flag": r["shortage_flag"],
        "storage_attested": r["storage_attested"],
        "completed_at": fmt_ts(r["completed_at"]),
        "late_delivery": r["late_delivery"],
    }
    out.update(_common(r))
    return out


def _manifest_lines(lines):
    return [
        {
            "stock_id": l["stock_id"],
            "weight_lbs": l["weight_lbs"],
            "isolation_flag": l["isolation_flag"],
            "expected_pieces": l["expected_pieces"],
        }
        for l in lines
    ]


def _returned_lines(lines):
    return [
        {
            "stock_id": l["stock_id"],
            "pieces": l["pieces"],
            "condemned_pieces": l["condemned_pieces"],
        }
        for l in lines
    ]


def manifest_out(m):
    out = {
        "facility_id": m["facility_id"],
        "invoice_id": m["invoice_id"],
        "lines": _manifest_lines(m["lines"]),
        "isolation_protocol_ack": m["isolation_protocol_ack"],
        "returned_lines": _returned_lines(m["returned_lines"]),
        "status": m["status"],
        "recorded_by_user_id": m["recorded_by_user_id"],
    }
    out.update(_common(m))
    return out


def invoice_out(i):
    out = {
        "facility_id": i["facility_id"],
        "period_start": fmt_ts(i["period_start"]),
        "period_end": fmt_ts(i["period_end"]),
        "period_adjusted_patient_days": i["period_adjusted_patient_days"],
        "status": i["status"],
        "provisional_total_cents": i["provisional_total_cents"],
        "final_total_cents": i["final_total_cents"],
        "credit_total_cents": i["credit_total_cents"],
        "billed_total_cents": i["billed_total_cents"],
        "cost_per_apd_cents": i["cost_per_apd_cents"],
        "created_by_user_id": i["created_by_user_id"],
        "finalized_by_user_id": i["finalized_by_user_id"],
    }
    out.update(_common(i))
    return out


def complaint_out(c):
    out = {
        "unit_id": c["unit_id"],
        "manifest_id": c["manifest_id"],
        "stock_id": c["stock_id"],
        "complaint_type": c["complaint_type"],
        "pieces_affected": c["pieces_affected"],
        "status": c["status"],
        "credit_cents": c["credit_cents"],
        "routed_invoice_id": c["routed_invoice_id"],
    }
    out.update(_common(c))
    return out


def surge_out(s):
    out = {
        "facility_id": s["facility_id"],
        "severity": s["severity"],
        "par_multiplier": s["par_multiplier"],
        "starts_at": fmt_ts(s["starts_at"]),
        "ends_at": fmt_ts(s["ends_at"]),
        "status": s["status"],
    }
    out.update(_common(s))
    return out
