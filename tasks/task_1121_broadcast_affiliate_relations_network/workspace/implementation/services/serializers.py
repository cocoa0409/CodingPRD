"""Entity serialization helpers."""


def network_view(n):
    return {
        "id": n["id"],
        "call_sign": n["call_sign"],
        "primary_feed_tz": n["primary_feed_tz"],
        "reverse_comp_standard_pct": n["reverse_comp_standard_pct"],
        "retrans_share_standard_pct": n["retrans_share_standard_pct"],
        "current_period_index": n["current_period_index"],
        "posture": n["posture"],
        "current_utc": n["current_utc"],
        "created_at": n["created_at"],
        "updated_at": n["updated_at"],
        "version": n["version"],
    }


def station_group_view(sg):
    return {
        "id": sg["id"],
        "group_name": sg["group_name"],
        "leverage_tier": sg["leverage_tier"],
        "aggregate_retrans_cents": sg["aggregate_retrans_cents"],
        "created_at": sg["created_at"],
        "updated_at": sg["updated_at"],
        "version": sg["version"],
    }


def station_view(s):
    return {
        "id": s["id"],
        "station_group_id": s["station_group_id"],
        "call_sign": s["call_sign"],
        "dma_code": s["dma_code"],
        "network_id": s["network_id"],
        "posture": s["posture"],
        "monthly_outage_minutes_current_period": s["monthly_outage_minutes_current_period"],
        "clearance_rate_current_period": s["clearance_rate_current_period"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def territory_view(t):
    return {
        "id": t["id"],
        "network_id": t["network_id"],
        "dma_code": t["dma_code"],
        "exclusivity_holder_station_id": t["exclusivity_holder_station_id"],
        "protection_window_start_utc": t["protection_window_start_utc"],
        "protection_window_end_utc": t["protection_window_end_utc"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def agreement_view(a):
    return {
        "id": a["id"],
        "station_id": a["station_id"],
        "network_id": a["network_id"],
        "term_start_utc": a["term_start_utc"],
        "term_end_utc": a["term_end_utc"],
        "reverse_comp_pct": a["reverse_comp_pct"],
        "retrans_share_pct": a["retrans_share_pct"],
        "clearance_obligation_hours": a["clearance_obligation_hours"],
        "status": a["status"],
        "renewal_round_count": a["renewal_round_count"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def program_view(p):
    return {
        "id": p["id"],
        "network_id": p["network_id"],
        "title": p["title"],
        "scheduled_start_utc": p["scheduled_start_utc"],
        "scheduled_end_utc": p["scheduled_end_utc"],
        "avail_minutes_total": p["avail_minutes_total"],
        "avail_minutes_local_allocatable": p["avail_minutes_local_allocatable"],
        "is_syndicated": p["is_syndicated"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def clearance_report_view(c):
    return {
        "id": c["id"],
        "station_id": c["station_id"],
        "period_index": c["period_index"],
        "cleared_hours": c["cleared_hours"],
        "preempted_hours": c["preempted_hours"],
        "status": c["status"],
        "clearance_rate": c["clearance_rate"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def preemption_view(p):
    return {
        "id": p["id"],
        "station_id": p["station_id"],
        "program_id": p["program_id"],
        "agreement_id": p["agreement_id"],
        "requested_start_utc": p["requested_start_utc"],
        "requested_end_utc": p["requested_end_utc"],
        "reason": p["reason"],
        "status": p["status"],
        "counter_start_utc": p["counter_start_utc"],
        "counter_end_utc": p["counter_end_utc"],
        "counter_round_count": p["counter_round_count"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def avail_allocation_view(a):
    return {
        "id": a["id"],
        "station_id": a["station_id"],
        "program_id": a["program_id"],
        "period_index": a["period_index"],
        "local_minutes_claimed": a["local_minutes_claimed"],
        "status": a["status"],
        "claimed_revenue_cents": a["claimed_revenue_cents"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def settlement_view(s):
    return {
        "id": s["id"],
        "station_id": s["station_id"],
        "agreement_id": s["agreement_id"],
        "period_index": s["period_index"],
        "gross_retrans_cents": s["gross_retrans_cents"],
        "net_retrans_cents": s["net_retrans_cents"],
        "network_share_cents": s["network_share_cents"],
        "variant_used": s["variant_used"],
        "status": s["status"],
        "outage_credit_cents": s["outage_credit_cents"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def outage_event_view(o):
    return {
        "id": o["id"],
        "station_id": o["station_id"],
        "period_index": o["period_index"],
        "started_at_utc": o["started_at_utc"],
        "ended_at_utc": o["ended_at_utc"],
        "duration_minutes": o["duration_minutes"],
        "cause": o["cause"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def outage_credit_view(c):
    return {
        "id": c["id"],
        "station_id": c["station_id"],
        "outage_event_id": c["outage_event_id"],
        "settlement_id": c["settlement_id"],
        "credit_cents": c["credit_cents"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def renewal_offer_view(o):
    return {
        "id": o["id"],
        "agreement_id": o["agreement_id"],
        "proposed_by_role": o["proposed_by_role"],
        "proposed_reverse_comp_pct": o["proposed_reverse_comp_pct"],
        "proposed_retrans_share_pct": o["proposed_retrans_share_pct"],
        "proposed_term_months": o["proposed_term_months"],
        "round_index": o["round_index"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def compliance_report_view(c):
    return {
        "id": c["id"],
        "station_id": c["station_id"],
        "period_index": c["period_index"],
        "report_kind": c["report_kind"],
        "status": c["status"],
        "finding_count": c["finding_count"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def exclusivity_claim_view(c):
    return {
        "id": c["id"],
        "territory_id": c["territory_id"],
        "program_id": c["program_id"],
        "claimant_station_id": c["claimant_station_id"],
        "respondent_station_id": c["respondent_station_id"],
        "alleged_window_start_utc": c["alleged_window_start_utc"],
        "alleged_window_end_utc": c["alleged_window_end_utc"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }
