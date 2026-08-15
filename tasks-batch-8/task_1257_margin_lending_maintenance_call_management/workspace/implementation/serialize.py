"""Entity serializers — exactly the fields declared in the scaffold entity
table. Primary resources carry id/created_at/updated_at/version (PRD 2.7);
ledger records (TradeFill, DayTradeEvent, PriceMark, InterestLedgerEntry)
carry only id/created_at — updated_at/version are absent."""
from timeutil import fmt_dt


def _common(e):
    return {
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def _ledger(e):
    return {"created_at": fmt_dt(e["created_at"])}


def ser_customer(c):
    out = {"id": c["id"], "legal_name": c["legal_name"], "email": c["email"]}
    out.update(_common(c))
    return out


def ser_application(a):
    out = {
        "id": a["id"],
        "customer_id": a["customer_id"],
        "annual_income_cents": a["annual_income_cents"],
        "liquid_net_worth_cents": a["liquid_net_worth_cents"],
        "investment_experience_years": a["investment_experience_years"],
        "application_status": a["application_status"],
        "reviewed_by_user_id": a["reviewed_by_user_id"],
        "decided_by_user_id": a["decided_by_user_id"],
        "rejection_reason": a["rejection_reason"],
        "account_id": a["account_id"],
    }
    out.update(_common(a))
    return out


def ser_account(a):
    out = {
        "id": a["id"],
        "customer_id": a["customer_id"],
        "application_id": a["application_id"],
        "account_status": a["account_status"],
        "cash_balance_cents": a["cash_balance_cents"],
        "equity_realtime_cents": a["equity_realtime_cents"],
        "equity_official_cents": a["equity_official_cents"],
        "reg_req_official_cents": a["reg_req_official_cents"],
        "house_req_official_cents": a["house_req_official_cents"],
        "reg_req_realtime_cents": a["reg_req_realtime_cents"],
        "house_req_realtime_cents": a["house_req_realtime_cents"],
        "buying_power_cents": a["buying_power_cents"],
        "pdt_flag": a["pdt_flag"],
        "pdt_flagged_at": fmt_dt(a["pdt_flagged_at"]),
    }
    out.update(_common(a))
    return out


def ser_security(s):
    out = {
        "id": s["id"],
        "symbol": s["symbol"],
        "marginable": s["marginable"],
        "house_maint_long_bps": s["house_maint_long_bps"],
        "house_maint_short_bps": s["house_maint_short_bps"],
        "liquidity_tier": s["liquidity_tier"],
        "concentration_threshold_bps": s["concentration_threshold_bps"],
    }
    out.update(_common(s))
    return out


def ser_position(p):
    out = {
        "id": p["id"],
        "account_id": p["account_id"],
        "security_id": p["security_id"],
        "quantity": p["quantity"],
        "avg_cost_cents": p["avg_cost_cents"],
        "mv_realtime_cents": p["mv_realtime_cents"],
        "mv_official_cents": p["mv_official_cents"],
        "reserved_qty": p["reserved_qty"],
        "opened_at": fmt_dt(p["opened_at"]),
        "today_bought_qty": p["today_bought_qty"],
        "today_sold_qty": p["today_sold_qty"],
        "last_trade_date": p["last_trade_date"].isoformat() if p["last_trade_date"] else None,
    }
    out.update(_common(p))
    return out


def ser_fill(f):
    out = {
        "id": f["id"],
        "account_id": f["account_id"],
        "security_id": f["security_id"],
        "side": f["side"],
        "quantity": f["quantity"],
        "price_cents": f["price_cents"],
        "fill_date": f["fill_date"].isoformat(),
        "is_day_trade": f["is_day_trade"],
    }
    out.update(_ledger(f))
    return out


def ser_day_trade_event(e):
    out = {
        "id": e["id"],
        "account_id": e["account_id"],
        "security_id": e["security_id"],
        "event_date": e["event_date"].isoformat(),
    }
    out.update(_ledger(e))
    return out


def ser_mark(m):
    out = {
        "id": m["id"],
        "security_id": m["security_id"],
        "mark_type": m["mark_type"],
        "price_cents": m["price_cents"],
        "marked_at": fmt_dt(m["marked_at"]),
    }
    out.update(_ledger(m))
    return out


def ser_call(c):
    out = {
        "id": c["id"],
        "account_id": c["account_id"],
        "call_type": c["call_type"],
        "call_status": c["call_status"],
        "call_amount_cents": c["call_amount_cents"],
        "issued_at": fmt_dt(c["issued_at"]),
        "due_at": fmt_dt(c["due_at"]),
        "resolved_at": fmt_dt(c["resolved_at"]),
        "cure_method": c["cure_method"],
    }
    out.update(_common(c))
    return out


def ser_liquidation_order(o):
    out = {
        "id": o["id"],
        "account_id": o["account_id"],
        "call_id": o["call_id"],
        "position_id": o["position_id"],
        "quantity": o["quantity"],
        "filled_quantity": o["filled_quantity"],
        "proceeds_cents": o["proceeds_cents"],
        "order_status": o["order_status"],
        "created_by_user_id": o["created_by_user_id"],
        "last_filled_by_user_id": o["last_filled_by_user_id"],
    }
    out.update(_common(o))
    return out


def ser_cash_movement(m):
    out = {
        "id": m["id"],
        "account_id": m["account_id"],
        "movement_type": m["movement_type"],
        "amount_cents": m["amount_cents"],
        "resulting_cash_balance_cents": m["resulting_cash_balance_cents"],
    }
    out.update(_common(m))
    return out


def ser_interest_entry(e):
    out = {
        "id": e["id"],
        "account_id": e["account_id"],
        "entry_type": e["entry_type"],
        "accrual_date": e["accrual_date"].isoformat(),
        "debit_balance_snapshot_cents": e["debit_balance_snapshot_cents"],
        "rate_bps_applied": e["rate_bps_applied"],
        "amount_cents": e["amount_cents"],
        "posted": e["posted"],
    }
    out.update(_ledger(e))
    return out


def ser_rate_tier(t):
    out = {
        "id": t["id"],
        "tier_level": t["tier_level"],
        "min_balance_cents": t["min_balance_cents"],
        "annual_rate_bps": t["annual_rate_bps"],
        "effective_from": t["effective_from"].isoformat(),
        "effective_to": t["effective_to"].isoformat() if t["effective_to"] else None,
    }
    out.update(_common(t))
    return out


def ser_dispute(d):
    out = {
        "id": d["id"],
        "account_id": d["account_id"],
        "call_id": d["call_id"],
        "reason": d["reason"],
        "dispute_status": d["dispute_status"],
        "reviewed_by_user_id": d["reviewed_by_user_id"],
        "decided_by_user_id": d["decided_by_user_id"],
        "decision": d["decision"],
    }
    out.update(_common(d))
    return out
