"""Entity serializers — computed fields derived fresh on every read."""
import store as db
import logical_clock as clock
from logic import (base_fields, mv, unrealized, cash_balance, total_value,
                   restriction_status)


def client_out(c):
    aum = sum(total_value(pf["id"]) for pf in db.portfolios.values()
              if pf["client_id"] == c["id"]
              and pf["lifecycle_status"] in ("OPEN", "ACTIVE", "FROZEN"))
    out = base_fields(c)
    out.update({
        "full_name": c["full_name"],
        "risk_tolerance_score": c["risk_tolerance_score"],
        "status": c["status"],
        "total_aum_cents": aum,
    })
    return out


def benchmark_out(b):
    out = base_fields(b)
    out.update({"name": b["name"], "description": b["description"],
                "status": b["status"]})
    return out


def ips_out(i):
    overdue = (i["status"] == "ACTIVE" and i["next_review_due_dt"] is not None
               and clock.now() > i["next_review_due_dt"])  # strict >
    out = base_fields(i)
    out.update({
        "client_id": i["client_id"],
        "benchmark_id": i["benchmark_id"],
        "objective_text": i["objective_text"],
        "risk_tolerance_score": i["risk_tolerance_score"],
        "review_cadence_months": i["review_cadence_months"],
        "status": i["status"],
        "activated_at": clock.fmt_or_none(i["activated_at_dt"]),
        "next_review_due": clock.fmt_or_none(i["next_review_due_dt"]),
        "review_overdue": overdue,
        "supersedes_ips_id": i["supersedes_ips_id"],
    })
    return out


def target_out(t):
    out = base_fields(t)
    out.update({
        "ips_id": t["ips_id"],
        "asset_class": t["asset_class"],
        "target_pct": float(t["target_pct"]),
        "band_pct": float(t["band_pct"]),
    })
    return out


def portfolio_out(pf):
    out = base_fields(pf)
    out.update({
        "client_id": pf["client_id"],
        "name": pf["name"],
        "tax_status": pf["tax_status"],
        "lifecycle_status": pf["lifecycle_status"],
        "drift_status": pf["drift_status"],
        "cash_balance_cents": cash_balance(pf["id"]),
        "total_value_cents": total_value(pf["id"]),
        "lifetime_realized_gains_cents": pf["lifetime_realized_gains_cents"],
    })
    return out


def security_out(s):
    out = base_fields(s)
    out.update({
        "ticker": s["ticker"],
        "asset_class": s["asset_class"],
        "price_cents": s["price_cents"],
        "trading_status": s["trading_status"],
    })
    return out


def position_out(p):
    out = base_fields(p)
    out.update({
        "portfolio_id": p["portfolio_id"],
        "security_id": p["security_id"],
        "quantity": p["quantity"],
        "cost_basis_cents": p["cost_basis_cents"],
        "market_value_cents": mv(p),
        "unrealized_gain_cents": unrealized(p),
    })
    return out


def event_out(e):
    return {
        "id": e["id"],
        "portfolio_id": e["portfolio_id"],
        "occurred_at": clock.fmt(e["occurred_dt"]),
        "kind": e["kind"],
        "amount_cents": e["amount_cents"],
        "balance_after_cents": e["balance_after_cents"],
        "valuation_before_cents": e["valuation_before_cents"],
        "source_type": e["source_type"],
        "source_id": e["source_id"],
        "created_at": clock.fmt(e["created_dt"]),
    }


def restricted_out(e):
    out = base_fields(e)
    out.update({
        "security_id": e["security_id"],
        "restriction_level": e["restriction_level"],
        "effective_from": clock.fmt(e["from_dt"]),
        "effective_to": clock.fmt(e["to_dt"]),
        "reason": e["reason"],
        "status": restriction_status(e),
    })
    return out


def proposal_out(p):
    out = base_fields(p)
    out.update({
        "portfolio_id": p["portfolio_id"],
        "trigger_type": p["trigger_type"],
        "status": p["status"],
        "ips_id": p["ips_id"],
        "pinned_ips_version": p["pinned_ips_version"],
        "generated_at": clock.fmt_or_none(p["generated_at_dt"]),
        "expires_at": clock.fmt_or_none(p["expires_at_dt"]),
        "total_buys_cents": p["total_buys_cents"],
        "total_sells_cents": p["total_sells_cents"],
        "est_tax_reserve_cents": p["est_tax_reserve_cents"],
        "cash_delta_cents": p["cash_delta_cents"],
        "decided_by_user_id": p["decided_by_user_id"],
    })
    return out


def trade_out(t):
    out = base_fields(t)
    out.update({
        "proposal_id": t["proposal_id"],
        "security_id": t["security_id"],
        "side": t["side"],
        "quantity": t["quantity"],
        "pinned_price_cents": t["pinned_price_cents"],
        "est_proceeds_cents": t["est_proceeds_cents"],
        "est_tax_impact_cents": t["est_tax_impact_cents"],
        "status": t["status"],
        "executed_at": clock.fmt_or_none(t["executed_at_dt"]),
        "executed_price_cents": t["executed_price_cents"],
        "voided_at": clock.fmt_or_none(t["voided_at_dt"]),
    })
    return out


def withdrawal_out(w):
    out = base_fields(w)
    out.update({
        "portfolio_id": w["portfolio_id"],
        "amount_cents": w["amount_cents"],
        "funding_mode": w["funding_mode"],
        "status": w["status"],
        "modeled_at": clock.fmt_or_none(w["modeled_at_dt"]),
        "modeled_plan": w["modeled_plan"],
        "modeled_proceeds_cents": w["modeled_proceeds_cents"],
        "modeled_tax_cost_cents": w["modeled_tax_cost_cents"],
        "modeled_cash_used_cents": w["modeled_cash_used_cents"],
        "post_withdrawal_drift_status": w["post_withdrawal_drift_status"],
    })
    return out


def report_out(r):
    out = base_fields(r)
    out.update({
        "portfolio_id": r["portfolio_id"],
        "benchmark_id": r["benchmark_id"],
        "period_start": r["period_start_d"].isoformat(),
        "period_end": r["period_end_d"].isoformat(),
        "calculation_method": r["calculation_method"],
        "beginning_value_cents": r["beginning_value_cents"],
        "ending_value_cents": r["ending_value_cents"],
        "benchmark_return_bps": r["benchmark_return_bps"],
        "portfolio_return_bps": r["portfolio_return_bps"],
        "excess_return_bps": r["excess_return_bps"],
        "status": r["status"],
    })
    return out


def amendment_out(a):
    out = base_fields(a)
    out.update({
        "ips_id": a["ips_id"],
        "proposed_objective_text": a["proposed_objective_text"],
        "proposed_review_cadence_months": a["proposed_review_cadence_months"],
        "proposed_risk_tolerance_score": a["proposed_risk_tolerance_score"],
        "proposed_benchmark_id": a["proposed_benchmark_id"],
        "proposed_by_user_id": a["proposed_by_user_id"],
        "status": a["status"],
        "approve_votes": a["approve_votes"],
        "reject_votes": a["reject_votes"],
        "voter_user_ids": a["voter_user_ids"],
        "ratified_minute_id": a["ratified_minute_id"],
        "finalized_by_user_id": a["finalized_by_user_id"],
        "finalized_at": clock.fmt_or_none(a["finalized_at_dt"]),
    })
    return out


def minute_out(m):
    out = base_fields(m)
    out.update({
        "meeting_date": m["meeting_date_d"].isoformat(),
        "amendment_refs": m["amendment_refs"],
        "decisions_text": m["decisions_text"],
        "recorded_by_user_id": m["recorded_by_user_id"],
        "status": m["status"],
        "ratified_by_user_id": m["ratified_by_user_id"],
        "ratified_at": clock.fmt_or_none(m["ratified_at_dt"]),
    })
    return out
