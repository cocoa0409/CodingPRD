"""Serialize entities to output dicts. Recompute computed fields where needed."""
from db import db
from calculations import annualize_charge_cost


def ser_member(m):
    return {
        "id": m["id"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
        "email": m["email"],
        "full_name": m["full_name"],
        "success_fee_pct": m["success_fee_pct"],
        "savings_account_id": m["savings_account_id"],
        "status": m["status"],
        "lifetime_gross_savings_cents": m["lifetime_gross_savings_cents"],
        "lifetime_member_savings_cents": m["lifetime_member_savings_cents"],
    }


def ser_savings_account(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "member_id": s["member_id"],
        "nickname": s["nickname"],
        "balance_cents": s["balance_cents"],
        "status": s["status"],
    }


def _detected_charge_count(linked_account_id):
    return sum(
        1 for c in db.recurring_charges.values()
        if c["linked_account_id"] == linked_account_id and c["status"] != "DISMISSED"
    )


def ser_linked_account(la):
    return {
        "id": la["id"],
        "created_at": la["created_at"],
        "updated_at": la["updated_at"],
        "version": la["version"],
        "member_id": la["member_id"],
        "institution_name": la["institution_name"],
        "account_type": la["account_type"],
        "status": la["status"],
        "detected_charge_count": la["detected_charge_count"],
    }


def ser_recurring_charge(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "linked_account_id": c["linked_account_id"],
        "merchant_name": c["merchant_name"],
        "amount_cents": c["amount_cents"],
        "cadence": c["cadence"],
        "category": c["category"],
        "first_seen_utc": c["first_seen_utc"],
        "annualized_cost_cents": c["annualized_cost_cents"],
        "status": c["status"],
    }


def _parse_iso(s):
    # Compare ISO8601 strings lexicographically after normalizing Z; the test
    # harness uses comparable UTC formats. Use datetime for safety.
    from datetime import datetime
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def compute_reminder_due(sub):
    if not sub.get("is_free_trial"):
        return False
    if sub["status"] == "CANCELLED":
        return False
    trial_end = sub.get("trial_end_utc")
    if not trial_end:
        return False
    lead = sub.get("trial_reminder_lead_days", 3)
    end_dt = _parse_iso(trial_end)
    clock_dt = _parse_iso(db.clock_current_utc)
    if end_dt is None or clock_dt is None:
        return False
    from datetime import timedelta
    threshold = end_dt - timedelta(days=lead)
    return clock_dt >= threshold


def ser_subscription(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "member_id": s["member_id"],
        "recurring_charge_id": s["recurring_charge_id"],
        "plan_name": s["plan_name"],
        "monthly_cost_cents": s["monthly_cost_cents"],
        "is_free_trial": s["is_free_trial"],
        "trial_end_utc": s["trial_end_utc"],
        "trial_reminder_lead_days": s["trial_reminder_lead_days"],
        "reminder_due": compute_reminder_due(s),
        "status": s["status"],
        "cancelled_utc": s["cancelled_utc"],
    }


def ser_negotiation_case(n):
    return {
        "id": n["id"],
        "created_at": n["created_at"],
        "updated_at": n["updated_at"],
        "version": n["version"],
        "member_id": n["member_id"],
        "recurring_charge_id": n["recurring_charge_id"],
        "assigned_agent_id": n["assigned_agent_id"],
        "baseline_annual_cost_cents": n["baseline_annual_cost_cents"],
        "current_offer_annual_cost_cents": n["current_offer_annual_cost_cents"],
        "agreed_annual_cost_cents": n["agreed_annual_cost_cents"],
        "round_count": n["round_count"],
        "gross_annual_savings_cents": n["gross_annual_savings_cents"],
        "success_fee_cents": n["success_fee_cents"],
        "member_net_savings_cents": n["member_net_savings_cents"],
        "status": n["status"],
    }


def _open_case_count(agent_id):
    return sum(
        1 for n in db.negotiation_cases.values()
        if n["assigned_agent_id"] == agent_id
        and n["status"] in ("OPEN", "PROPOSED", "COUNTERED")
    )


def ser_concierge_agent(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "display_name": a["display_name"],
        "max_open_cases": a["max_open_cases"],
        "open_case_count": a["open_case_count"],
    }


def ser_refund_claim(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "member_id": r["member_id"],
        "recurring_charge_id": r["recurring_charge_id"],
        "claim_type": r["claim_type"],
        "observed_old_amount_cents": r["observed_old_amount_cents"],
        "observed_new_amount_cents": r["observed_new_amount_cents"],
        "claimed_refund_cents": r["claimed_refund_cents"],
        "approved_refund_cents": r["approved_refund_cents"],
        "success_fee_cents": r["success_fee_cents"],
        "member_net_savings_cents": r["member_net_savings_cents"],
        "dispute_round": r["dispute_round"],
        "status": r["status"],
    }


def ser_ledger_entry(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "member_id": e["member_id"],
        "source_type": e["source_type"],
        "negotiation_case_id": e["negotiation_case_id"],
        "refund_claim_id": e["refund_claim_id"],
        "gross_savings_cents": e["gross_savings_cents"],
        "success_fee_cents": e["success_fee_cents"],
        "member_net_cents": e["member_net_cents"],
        "transfer_status": e["transfer_status"],
        "transferred_utc": e["transferred_utc"],
    }


def ser_clock():
    return {"current_utc": db.clock_current_utc}
