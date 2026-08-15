"""Entity serializers: convert internal records to API response format."""
from util import fmt_value


def _base(rec, include_version=True):
    """Common fields for all entities."""
    out = {
        "id": rec["id"],
        "created_at": fmt_value(rec["created_at"]),
        "updated_at": fmt_value(rec["updated_at"]),
    }
    if include_version:
        out["version"] = rec["version"]
    return out


def owner_out(rec):
    out = _base(rec)
    out.update({
        "owner_name": rec["owner_name"],
        "billing_email": rec["billing_email"],
        "status": rec["status"],
        "outstanding_balance_cents": rec["outstanding_balance_cents"],
    })
    return out


def pen_out(rec):
    out = _base(rec)
    out.update({
        "pen_code": rec["pen_code"],
        "capacity_head": rec["capacity_head"],
        "status": rec["status"],
        "current_occupancy_head": rec["current_occupancy_head"],
    })
    return out


def lot_out(rec):
    out = _base(rec)
    out.update({
        "owner_id": rec["owner_id"],
        "lot_number": rec["lot_number"],
        "sex_class": rec["sex_class"],
        "head_count_in": rec["head_count_in"],
        "in_weight_total_lbs": rec["in_weight_total_lbs"],
        "purchase_cost_cents": rec["purchase_cost_cents"],
        "arrival_date": fmt_value(rec["arrival_date"]),
        "commingle_allowed": rec["commingle_allowed"],
        "status": rec["status"],
        "head_count_current": rec["head_count_current"],
        "head_shipped": rec["head_shipped"],
        "total_deaths": rec["total_deaths"],
        "out_weight_total_lbs": rec["out_weight_total_lbs"],
        "total_feed_cost_cents": rec["total_feed_cost_cents"],
        "total_health_cost_cents": rec["total_health_cost_cents"],
        "total_death_loss_cents": rec["total_death_loss_cents"],
        "total_hedge_pnl_cents": rec["total_hedge_pnl_cents"],
        "insurance_credit_pending_cents": rec["insurance_credit_pending_cents"],
        "withdrawal_clear_date": fmt_value(rec["withdrawal_clear_date"]),
        "provisional_cog_cents_per_cwt": rec["provisional_cog_cents_per_cwt"],
    })
    return out


def ration_out(rec):
    out = _base(rec)
    out.update({
        "ration_name": rec["ration_name"],
        "step_level": rec["step_level"],
        "cost_per_ton_cents": rec["cost_per_ton_cents"],
    })
    return out


def pen_assignment_out(rec):
    out = _base(rec)
    out.update({
        "pen_id": rec["pen_id"],
        "lot_id": rec["lot_id"],
        "head_count": rec["head_count"],
        "start_date": fmt_value(rec["start_date"]),
        "end_date": fmt_value(rec["end_date"]),
        "status": rec["status"],
    })
    return out


def ration_assignment_out(rec):
    out = _base(rec)
    out.update({
        "lot_id": rec["lot_id"],
        "ration_id": rec["ration_id"],
        "start_date": fmt_value(rec["start_date"]),
        "end_date": fmt_value(rec["end_date"]),
        "status": rec["status"],
    })
    return out


def feed_call_out(rec):
    """FeedCall is immutable: no updated_at, no version."""
    return {
        "id": rec["id"],
        "created_at": fmt_value(rec["created_at"]),
        "pen_id": rec["pen_id"],
        "call_date": fmt_value(rec["call_date"]),
        "bunk_score": rec.get("bunk_score"),
        "base_qty_lbs_per_head": rec.get("base_qty_lbs_per_head"),
        "ration_id": rec["ration_id"],
        "qty_lbs_per_head": rec["qty_lbs_per_head"],
        "total_qty_lbs": rec["total_qty_lbs"],
        "total_cost_cents": rec["total_cost_cents"],
    }


def health_event_out(rec):
    out = _base(rec)
    out.update({
        "lot_id": rec["lot_id"],
        "treatment_date": fmt_value(rec["treatment_date"]),
        "drug_product": rec["drug_product"],
        "withdrawal_days": rec["withdrawal_days"],
        "head_treated": rec["head_treated"],
        "treatment_cost_cents": rec["treatment_cost_cents"],
        "withdrawal_end_date": fmt_value(rec["withdrawal_end_date"]),
        "status": rec["status"],
    })
    return out


def death_loss_out(rec):
    out = _base(rec)
    out.update({
        "lot_id": rec["lot_id"],
        "loss_date": fmt_value(rec["loss_date"]),
        "head_count": rec["head_count"],
        "cause": rec["cause"],
        "insured": rec["insured"],
        "loss_value_cents": rec["loss_value_cents"],
        "allocations": rec["allocations"],
        "status": rec["status"],
    })
    return out


def insurance_claim_out(rec):
    out = _base(rec)
    out.update({
        "death_loss_id": rec["death_loss_id"],
        "claimed_amount_cents": rec["claimed_amount_cents"],
        "approved_amount_cents": rec["approved_amount_cents"],
        "status": rec["status"],
        "appeal_count": rec["appeal_count"],
        "decided_by_user_id": rec["decided_by_user_id"],
    })
    return out


def hedge_position_out(rec):
    out = _base(rec)
    out.update({
        "lot_id": rec["lot_id"],
        "contract_month": rec["contract_month"],
        "side": rec["side"],
        "quantity_contracts": rec["quantity_contracts"],
        "entry_price_cents_per_cwt": rec["entry_price_cents_per_cwt"],
        "exit_price_cents_per_cwt": rec["exit_price_cents_per_cwt"],
        "realized_pnl_cents": rec["realized_pnl_cents"],
        "status": rec["status"],
    })
    return out


def close_out_out(rec):
    out = _base(rec)
    out.update({
        "lot_id": rec["lot_id"],
        "pricing_basis": rec["pricing_basis"],
        "grid_base_price_cents_per_cwt": rec["grid_base_price_cents_per_cwt"],
        "carcass_records": rec["carcass_records"],
        "total_grid_value_cents": rec["total_grid_value_cents"],
        "total_cost_cents": rec["total_cost_cents"],
        "final_cog_cents_per_cwt": rec["final_cog_cents_per_cwt"],
        "hedge_pnl_cents": rec["hedge_pnl_cents"],
        "net_result_cents": rec["net_result_cents"],
        "status": rec["status"],
    })
    return out


def invoice_out(rec):
    out = _base(rec)
    out.update({
        "lot_id": rec["lot_id"],
        "owner_id": rec["owner_id"],
        "feed_cents": rec["feed_cents"],
        "yardage_cents": rec["yardage_cents"],
        "yardage_head_days": rec["yardage_head_days"],
        "health_cents": rec["health_cents"],
        "death_loss_cents": rec["death_loss_cents"],
        "insurance_credit_cents": rec["insurance_credit_cents"],
        "total_cents": rec["total_cents"],
        "amount_paid_cents": rec["amount_paid_cents"],
        "status": rec["status"],
        "void_reason": rec["void_reason"],
    })
    return out
