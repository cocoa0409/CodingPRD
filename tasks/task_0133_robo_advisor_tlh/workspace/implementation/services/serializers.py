"""Public response shapes for each entity — strips internal-only fields."""
from __future__ import annotations


def _audit_keys(entity, common=True):
    out = {"id": entity["id"], "created_at": entity["created_at"]}
    if common:
        out["updated_at"] = entity["updated_at"]
        out["version"] = entity["version"]
    return out


def serialize_client(c):
    return {
        **_audit_keys(c),
        "full_name": c["full_name"],
        "birth_date": c["birth_date"],
        "age": c.get("age"),
        "kyc_status": c["kyc_status"],
        "risk_band": c.get("risk_band"),
        "time_horizon_years": c.get("time_horizon_years"),
    }


def serialize_risk_questionnaire(q):
    return {
        **_audit_keys(q, common=False),
        "client_id": q["client_id"],
        "submitted_at": q["submitted_at"],
        "q1_loss_tolerance": q["q1_loss_tolerance"],
        "q2_volatility_comfort": q["q2_volatility_comfort"],
        "q3_growth_vs_stability": q["q3_growth_vs_stability"],
        "q4_liquidity_need": q["q4_liquidity_need"],
        "q5_experience": q["q5_experience"],
        "scoring_method": q["scoring_method"],
        "raw_score": q["raw_score"],
        "assigned_band": q["assigned_band"],
    }


def serialize_model_portfolio(m):
    return {
        **_audit_keys(m, common=False),
        "risk_band": m["risk_band"],
        "horizon_band": m["horizon_band"],
        "target_allocation": m["target_allocation"],
        "is_active": m["is_active"],
    }


def serialize_account(a):
    return {
        **_audit_keys(a),
        "client_id": a["client_id"],
        "model_portfolio_id": a.get("model_portfolio_id"),
        "cash_balance_cents": a["cash_balance_cents"],
        "compliance_status": a["compliance_status"],
        "investment_status": a["investment_status"],
        "max_drift_pct": a["max_drift_pct"],
    }


def serialize_security(s):
    return {
        **_audit_keys(s, common=False),
        "ticker": s["ticker"],
        "asset_class": s["asset_class"],
        "substantially_identical_group_id": s["substantially_identical_group_id"],
        "is_investable": s["is_investable"],
        "last_price_cents": s["last_price_cents"],
    }


def serialize_correlation_link(c):
    return {
        **_audit_keys(c, common=False),
        "security_a_id": c["security_a_id"],
        "security_b_id": c["security_b_id"],
        "correlation": c["correlation"],
    }


def serialize_position(p):
    return {
        **_audit_keys(p),
        "account_id": p["account_id"],
        "security_id": p["security_id"],
        "shares": p["shares"],
        "total_cost_basis_cents": p["total_cost_basis_cents"],
        "market_value_cents": p["market_value_cents"],
    }


def serialize_lot(l):
    return {
        **_audit_keys(l),
        "position_id": l["position_id"],
        "buy_trade_id": l["buy_trade_id"],
        "acquired_at": l["acquired_at"],
        "shares_opened": l["shares_opened"],
        "shares_remaining": l["shares_remaining"],
        "unit_cost_cents": l["unit_cost_cents"],
        "adjusted_unit_cost_cents": l["adjusted_unit_cost_cents"],
        "status": l["status"],
    }


def serialize_trade(t):
    return {
        **_audit_keys(t),
        "account_id": t["account_id"],
        "security_id": t["security_id"],
        "side": t["side"],
        "requested_shares": t["requested_shares"],
        "cost_basis_method": t.get("cost_basis_method"),
        "specific_lot_id": t.get("specific_lot_id"),
        "rebalance_run_id": t.get("rebalance_run_id"),
        "status": t["status"],
        "executed_at": t.get("executed_at"),
        "execution_price_cents": t.get("execution_price_cents"),
        "gross_proceeds_cents": t.get("gross_proceeds_cents"),
        "realized_gain_loss_cents": t.get("realized_gain_loss_cents"),
        "disallowed_loss_cents": t.get("disallowed_loss_cents", 0),
    }


def serialize_wash_sale_event(w):
    return {
        **_audit_keys(w, common=False),
        "sell_trade_id": w["sell_trade_id"],
        "replacement_trade_id": w["replacement_trade_id"],
        "group_id": w["group_id"],
        "matched_shares": w["matched_shares"],
        "disallowed_loss_cents": w["disallowed_loss_cents"],
        "replacement_lot_id": w["replacement_lot_id"],
        "recorded_at": w["recorded_at"],
    }


def serialize_harvest_opportunity(h):
    return {
        **_audit_keys(h),
        "account_id": h["account_id"],
        "position_id": h["position_id"],
        "unrealized_loss_cents": h["unrealized_loss_cents"],
        "replacement_security_id": h.get("replacement_security_id"),
        "status": h["status"],
        "detected_at": h["detected_at"],
    }


def serialize_rebalance_run(r):
    return {
        **_audit_keys(r),
        "account_id": r["account_id"],
        "quarter_key": r["quarter_key"],
        "max_drift_pct_at_start": r.get("max_drift_pct_at_start"),
        "status": r["status"],
        "started_at": r.get("started_at"),
        "completed_at": r.get("completed_at"),
    }


def serialize_dividend_event(d):
    return {
        **_audit_keys(d, common=False),
        "account_id": d["account_id"],
        "security_id": d["security_id"],
        "amount_cents": d["amount_cents"],
        "received_at": d["received_at"],
        "reinvest_trade_id": d.get("reinvest_trade_id"),
    }


def serialize_form_1099b(f):
    return {
        **_audit_keys(f),
        "client_id": f["client_id"],
        "tax_year": f["tax_year"],
        "short_term_proceeds_cents": f["short_term_proceeds_cents"],
        "short_term_cost_basis_cents": f["short_term_cost_basis_cents"],
        "short_term_realized_gain_loss_cents": f["short_term_realized_gain_loss_cents"],
        "long_term_proceeds_cents": f["long_term_proceeds_cents"],
        "long_term_cost_basis_cents": f["long_term_cost_basis_cents"],
        "long_term_realized_gain_loss_cents": f["long_term_realized_gain_loss_cents"],
        "total_disallowed_wash_sale_cents": f["total_disallowed_wash_sale_cents"],
        "status": f["status"],
        "issued_at": f.get("issued_at"),
    }
