"""Serializers — derived fields are reconciled at read time (immediate consistency)."""
import store
import services as svc
from util import iso, month_key


def base_view(rec):
    return {"id": rec["id"], "created_at": iso(rec["created_at"]),
            "updated_at": iso(rec["updated_at"]), "version": rec["version"]}


def team_view(t):
    v = base_view(t)
    v.update({
        "name": t["name"],
        "market": t["market"],
        "timezone": t["timezone"],
        "speed_to_lead_window_seconds": t["speed_to_lead_window_seconds"],
        "claim_window_seconds": t["claim_window_seconds"],
    })
    return v


def agent_view(a):
    v = base_view(a)
    v.update({
        "team_id": a["team_id"],
        "display_name": a["display_name"],
        "license_number": a["license_number"],
        "role_on_team": a["role_on_team"],
        "max_active_leads": a["max_active_leads"],
        "status": a["status"],
        "performance_tier": svc.agent_tier(a),
        "active_lead_count": svc.derived_active_lead_count(a["id"]),
        "trailing_90d_conversions": svc.agent_conversions(a),
        "trailing_90d_claimed": svc.agent_claimed(a),
        "trailing_90d_offered": svc.agent_offered(a),
        "avg_first_response_seconds": svc.agent_avg_response(a),
        "consecutive_missed_claims": a["consecutive_missed_claims"],
        "last_assigned_at": iso(a["last_assigned_at"]),
        "onboarded_at": iso(a["onboarded_at"]),
    })
    return v


def timeoff_view(t):
    v = base_view(t)
    v.update({
        "agent_id": t["agent_id"],
        "starts_at": iso(t["starts_at"]),
        "ends_at": iso(t["ends_at"]),
        "reason": t["reason"],
    })
    return v


def policy_view(p):
    v = base_view(p)
    v.update({
        "team_id": p["team_id"],
        "version_no": p["version_no"],
        "mode": p["mode"],
        "tier_weight_bps": p["tier_weight_bps"],
        "source_mode_overrides": p["source_mode_overrides"],
        "claim_window_seconds": p["claim_window_seconds"],
        "speed_to_lead_window_seconds": p["speed_to_lead_window_seconds"],
        "status": p["status"],
        "activated_at": iso(p["activated_at"]),
    })
    return v


def source_view(s):
    team = store.teams.get(s["team_id"])
    tzname = team["timezone"] if team else "UTC"
    now = store.now()
    mk = month_key(now, tzname)
    count = sum(1 for l in store.leads.values()
                if l["source_id"] == s["id"] and month_key(l["created_at"], tzname) == mk)
    v = base_view(s)
    v.update({
        "team_id": s["team_id"],
        "name": s["name"],
        "type": s["type"],
        "cost_per_lead_cents": s["cost_per_lead_cents"],
        "monthly_budget_cents": s["monthly_budget_cents"],
        "priority_weight": s["priority_weight"],
        "auto_route": s["auto_route"],
        "status": s["status"],
        "leads_this_month_count": count,
        "spent_this_month_cents": count * s["cost_per_lead_cents"],
    })
    return v


def lead_view(l):
    v = base_view(l)
    v.update({
        "team_id": l["team_id"],
        "source_id": l["source_id"],
        "assigned_agent_id": l["assigned_agent_id"],
        "referral_partner_id": l["referral_partner_id"],
        "contact_name": l["contact_name"],
        "contact_phone": l["contact_phone"],
        "contact_email": l["contact_email"],
        "expected_close_price_cents": l["expected_close_price_cents"],
        "status": l["status"],
        "temperature": l["temperature"],
        "engagement_score": svc.lead_score(l["id"]),
        "first_response_at": iso(l["first_response_at"]),
        "within_speed_sla": l["within_speed_sla"],
        "speed_deadline_at": iso(l["speed_deadline_at"]),
        "claim_deadline_at": iso(l["claim_deadline_at"]),
        "current_assignment_id": l["current_assignment_id"],
        "close_reason": l["close_reason"],
    })
    return v


def assignment_view(a):
    v = base_view(a)
    v.update({
        "lead_id": a["lead_id"],
        "agent_id": a["agent_id"],
        "policy_id": a["policy_id"],
        "supersedes_assignment_id": a["supersedes_assignment_id"],
        "rotation_seq": a["rotation_seq"],
        "policy_mode_snapshot": a["policy_mode_snapshot"],
        "offered_at": iso(a["offered_at"]),
        "claim_deadline_at": iso(a["claim_deadline_at"]),
        "responded_at": iso(a["responded_at"]),
        "status": a["status"],
        "outcome_reason": a["outcome_reason"],
    })
    return v


def event_view(e):
    return {
        "id": e["id"],
        "lead_id": e["lead_id"],
        "type": e["type"],
        "occurred_at": iso(e["occurred_at"]),
        "points": e["points"],
        "effective_points": svc.event_effective_points(e),
        "created_at": iso(e["created_at"]),
    }


def campaign_view(c):
    v = base_view(c)
    v.update({
        "team_id": c["team_id"],
        "name": c["name"],
        "temperature_target": c["temperature_target"],
        "steps": c["steps"],
        "status": c["status"],
    })
    return v


def enrollment_view(e):
    v = base_view(e)
    v.update({
        "campaign_id": e["campaign_id"],
        "lead_id": e["lead_id"],
        "status": e["status"],
        "entered_temperature": e["entered_temperature"],
        "current_step_index": e["current_step_index"],
        "next_send_at": iso(e["next_send_at"]),
        "exit_reason": e["exit_reason"],
    })
    return v


def partner_view(p):
    v = base_view(p)
    v.update({
        "team_id": p["team_id"],
        "name": p["name"],
        "fee_bps": p["fee_bps"],
        "status": p["status"],
    })
    return v


def agreement_view(a):
    v = base_view(a)
    v.update({
        "team_id": a["team_id"],
        "agent_a_id": a["agent_a_id"],
        "agent_b_id": a["agent_b_id"],
        "a_share_bps": a["a_share_bps"],
        "b_share_bps": a["b_share_bps"],
        "effective_from": iso(a["effective_from"]),
        "effective_until": iso(a["effective_until"]),
        "status": a["status"],
    })
    return v


def deal_view(d):
    v = base_view(d)
    v.update({
        "team_id": d["team_id"],
        "lead_id": d["lead_id"],
        "agent_id": d["agent_id"],
        "gross_commission_cents": d["gross_commission_cents"],
        "actual_gross_commission_cents": d["actual_gross_commission_cents"],
        "status": d["status"],
        "split_basis_type": d["split_basis_type"],
        "split_basis_cents": d["split_basis_cents"],
        "referral_partner_id": d["referral_partner_id"],
        "effective_fee_bps": d["effective_fee_bps"],
        "referral_fee_cents": d["referral_fee_cents"],
        "house_share_cents": d["house_share_cents"],
        "agent_pool_cents": d["agent_pool_cents"],
        "agent_shares": d["agent_shares"],
        "split_agreement_id": d["split_agreement_id"],
        "approved_at": iso(d["approved_at"]),
        "dispute_reason": d["dispute_reason"],
    })
    return v
