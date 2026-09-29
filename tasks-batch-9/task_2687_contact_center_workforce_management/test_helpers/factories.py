"""Payload factories.

Every factory returns a plain dict of a valid create/transition payload and
accepts ``**overrides`` so a caller can bend exactly the field under test.
Money is always an integer (cents, or millicents for partner rates); hour and
ratio quantities are always JSON numbers, never strings.
"""

import itertools

from .constants import (
    BILLING_COMMITMENT_FLOOR,
    CHANNEL_CHAT,
    CHANNEL_VOICE,
    CONFIDENCE_HIGH,
    DECISION_APPROVE,
    PUBLICATION_PUBLISHED,
    REASON_SYSTEM_OUTAGE,
    REQUIREMENT_BASIS_MAX_OF_BOTH,
    RESPONSE_ACCEPT,
)

_counter = itertools.count(1)


def unique_suffix():
    """Monotonic suffix for the fields the PRD requires to be unique."""
    return f"{next(_counter):04d}"


# ─── Logical clock ────────────────────────────────────

def clock_payload(to_iso8601, **overrides):
    """Body for setting the logical clock."""
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


# ─── Labour agreements ────────────────────────────────

def labor_agreement_payload(**overrides):
    """A permissive agreement: nothing in the canonical scenario trips it."""
    payload = {
        "code": f"LA-CORE-{unique_suffix()}",
        "min_rest_hours": 11,
        "max_weekly_hours": 45.0,
        "max_consecutive_days": 6,
        "vto_min_notice_hours": 12,
        "preference_honor_floor_pct": 0.5000,
        "ot_premium_multiplier": 1.00,
    }
    payload.update(overrides)
    return payload


# ─── Planning cycles ──────────────────────────────────

def planning_cycle_payload(**overrides):
    """A Monday-to-Sunday cycle over the standard 2026-09-07 horizon."""
    payload = {
        "name": f"W37-2026-{unique_suffix()}",
        "horizon_start_date": "2026-09-07",
        "horizon_end_date": "2026-09-13",
        "interval_minutes": 30,
        "requirement_basis": REQUIREMENT_BASIS_MAX_OF_BOTH,
        "ot_budget_cents": 1000000,
        "intraday_alert_short_threshold": 99,
    }
    payload.update(overrides)
    return payload


def posture_payload(target_posture, **overrides):
    """Body for driving the cycle posture state machine."""
    payload = {"target_posture": target_posture}
    payload.update(overrides)
    return payload


def reforecast_payload(expected_cycle_version, effective_from_interval_start, **overrides):
    """Body for a reforecast run, carrying the cycle-version echo."""
    payload = {
        "expected_cycle_version": expected_cycle_version,
        "effective_from_interval_start": effective_from_interval_start,
    }
    payload.update(overrides)
    return payload


# ─── Forecast groups ──────────────────────────────────

def forecast_group_payload(planning_cycle_id, **overrides):
    """VOICE / VOICE_EN over an 08:00-to-10:00 window at half-hour intervals.

    Four intervals shaped 0.4 / 0.3 / 0.2 / 0.1 of a 1200-contact day.
    """
    payload = {
        "planning_cycle_id": planning_cycle_id,
        "channel": CHANNEL_VOICE,
        "skill_code": "VOICE_EN",
        "base_daily_volume": 1200,
        "base_aht_seconds": 300,
        "operating_start_minute": 480,
        "operating_end_minute": 600,
        "intraday_curve": [0.4, 0.3, 0.2, 0.1],
        "dow_multipliers": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        "service_level_target_pct": 0.8000,
        "service_level_seconds": 20,
        "occupancy_target_pct": 0.8500,
        "shrinkage_pct": 0.3000,
    }
    payload.update(overrides)
    return payload


def partner_forecast_group_payload(planning_cycle_id, **overrides):
    """CHAT / CHAT_EN shaped to two 82-contact intervals for partner work."""
    payload = {
        "planning_cycle_id": planning_cycle_id,
        "channel": CHANNEL_CHAT,
        "skill_code": "CHAT_EN",
        "base_daily_volume": 164,
        "base_aht_seconds": 120,
        "operating_start_minute": 480,
        "operating_end_minute": 540,
        "intraday_curve": [0.5, 0.5],
        "dow_multipliers": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        "service_level_target_pct": 0.8000,
        "service_level_seconds": 20,
        "occupancy_target_pct": 0.8500,
        "shrinkage_pct": 0.3000,
    }
    payload.update(overrides)
    return payload


def coverage_forecast_group_payload(planning_cycle_id, **overrides):
    """CHAT / CHAT_EN shaped to four small intervals each needing one agent."""
    payload = {
        "planning_cycle_id": planning_cycle_id,
        "channel": CHANNEL_CHAT,
        "skill_code": "CHAT_EN",
        "base_daily_volume": 40,
        "base_aht_seconds": 60,
        "operating_start_minute": 480,
        "operating_end_minute": 600,
        "intraday_curve": [0.4, 0.3, 0.2, 0.1],
        "dow_multipliers": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        "service_level_target_pct": 0.8000,
        "service_level_seconds": 20,
        "occupancy_target_pct": 0.8500,
        "shrinkage_pct": 0.3000,
    }
    payload.update(overrides)
    return payload


def interval_grid_payload(service_date="2026-09-07", **overrides):
    """Body for generating one service date's interval grid."""
    payload = {"service_date": service_date}
    payload.update(overrides)
    return payload


def actuals_payload(actual_volume, actual_aht_seconds, **overrides):
    """Body for posting observed volume and handle time against one interval."""
    payload = {
        "actual_volume": actual_volume,
        "actual_aht_seconds": actual_aht_seconds,
    }
    payload.update(overrides)
    return payload


# ─── Marketing events ─────────────────────────────────

def marketing_event_payload(planning_cycle_id, forecast_group_id=None, **overrides):
    """A HIGH-confidence driver over the 08:00-to-10:00 Monday window."""
    payload = {
        "planning_cycle_id": planning_cycle_id,
        "name": f"Campaign-{unique_suffix()}",
        "uplift_pct": 1.2000,
        "confidence_tier": CONFIDENCE_HIGH,
        "window_start": "2026-09-07T08:00:00Z",
        "window_end": "2026-09-07T10:00:00Z",
    }
    if forecast_group_id is not None:
        payload["forecast_group_id"] = forecast_group_id
    payload.update(overrides)
    return payload


def marketing_event_status_payload(target_status, **overrides):
    """Body for driving the marketing-event lifecycle."""
    payload = {"target_status": target_status}
    payload.update(overrides)
    return payload


# ─── Agents ───────────────────────────────────────────

def agent_payload(labor_agreement_id, **overrides):
    """A VOICE_EN agent at 24.00 currency units per hour."""
    payload = {
        "labor_agreement_id": labor_agreement_id,
        "employee_code": f"E-{unique_suffix()}",
        "full_name": "Agent One",
        "skills": ["VOICE_EN"],
        "seniority_rank": 1,
        "weekly_contracted_hours": 37.5,
        "hourly_rate_cents": 2400,
    }
    payload.update(overrides)
    return payload


def agent_patch_payload(**overrides):
    """Body for the agent partial update; every field is optional."""
    payload = {}
    payload.update(overrides)
    return payload


# ─── Shift templates ──────────────────────────────────

def shift_template_payload(planning_cycle_id, **overrides):
    """Monday 08:00 for eight elapsed hours less a thirty-minute break."""
    payload = {
        "planning_cycle_id": planning_cycle_id,
        "code": f"T-MON-AM-{unique_suffix()}",
        "skill_code": "VOICE_EN",
        "start_time_local": "08:00",
        "duration_minutes": 480,
        "unpaid_break_minutes": 30,
        "days_of_week": [0],
        "slots_total": 1,
    }
    payload.update(overrides)
    return payload


# ─── Bid rounds and bids ──────────────────────────────

def bid_round_payload(planning_cycle_id, **overrides):
    """Body for opening a bidding round."""
    payload = {
        "planning_cycle_id": planning_cycle_id,
        "code": f"R-{unique_suffix()}",
        "max_reopen_count": 2,
    }
    payload.update(overrides)
    return payload


def bid_round_status_payload(target_status, **overrides):
    """Body for driving the bid-round lifecycle."""
    payload = {"target_status": target_status}
    payload.update(overrides)
    return payload


def shift_bid_payload(bid_round_id, agent_id, preference_template_ids, **overrides):
    """Body for a bid: an ordered, most-preferred-first template list."""
    payload = {
        "bid_round_id": bid_round_id,
        "agent_id": agent_id,
        "preference_template_ids": list(preference_template_ids),
    }
    payload.update(overrides)
    return payload


# ─── Schedule shifts ──────────────────────────────────

def schedule_shift_payload(
    planning_cycle_id, agent_id, shift_template_id, service_date="2026-09-07", **overrides
):
    """Body for creating a draft shift directly."""
    payload = {
        "planning_cycle_id": planning_cycle_id,
        "agent_id": agent_id,
        "shift_template_id": shift_template_id,
        "service_date": service_date,
    }
    payload.update(overrides)
    return payload


def publication_payload(target_publication_status=PUBLICATION_PUBLISHED, **overrides):
    """Body for moving a shift along its publication axis."""
    payload = {"target_publication_status": target_publication_status}
    payload.update(overrides)
    return payload


def adherence_observation_payload(out_of_adherence_seconds, **overrides):
    """Body for an adherence observation; the value replaces wholesale."""
    payload = {"out_of_adherence_seconds": out_of_adherence_seconds}
    payload.update(overrides)
    return payload


# ─── Adherence exceptions ─────────────────────────────

def adherence_exception_payload(schedule_shift_id, agent_id, duration_seconds, **overrides):
    """Body for an agent's own exception request."""
    payload = {
        "schedule_shift_id": schedule_shift_id,
        "agent_id": agent_id,
        "reason_code": REASON_SYSTEM_OUTAGE,
        "duration_seconds": duration_seconds,
        "narrative": "Telephony platform outage during the affected window.",
    }
    payload.update(overrides)
    return payload


def exception_decision_payload(decision=DECISION_APPROVE, **overrides):
    """Body for the coach's branching decision."""
    payload = {"decision": decision, "coach_note": "Reviewed the outage log."}
    payload.update(overrides)
    return payload


def exception_resubmit_payload(duration_seconds, **overrides):
    """Body for a resubmission out of the information-requested branch."""
    payload = {
        "narrative": "Revised account with the incident ticket attached.",
        "duration_seconds": duration_seconds,
    }
    payload.update(overrides)
    return payload


# ─── Intraday actions ─────────────────────────────────

def ot_offer_payload(
    planning_cycle_id,
    agent_id,
    schedule_shift_id,
    target_forecast_group_id,
    hours=4.0,
    expires_at="2026-09-30T00:00:00Z",
    **overrides,
):
    """Body for an overtime offer to one agent."""
    payload = {
        "planning_cycle_id": planning_cycle_id,
        "kind": "OT_OFFER",
        "expires_at": expires_at,
        "agent_id": agent_id,
        "schedule_shift_id": schedule_shift_id,
        "target_forecast_group_id": target_forecast_group_id,
        "hours": hours,
    }
    payload.update(overrides)
    return payload


def vto_offer_payload(
    planning_cycle_id,
    agent_id,
    schedule_shift_id,
    hours=1.0,
    expires_at="2026-09-30T00:00:00Z",
    **overrides,
):
    """Body for a voluntary-time-off offer to one agent."""
    payload = {
        "planning_cycle_id": planning_cycle_id,
        "kind": "VTO_OFFER",
        "expires_at": expires_at,
        "agent_id": agent_id,
        "schedule_shift_id": schedule_shift_id,
        "hours": hours,
    }
    payload.update(overrides)
    return payload


def routing_adjustment_payload(
    planning_cycle_id,
    source_forecast_group_id,
    target_forecast_group_id,
    interval_start,
    agents_shifted=1,
    expires_at="2026-09-30T00:00:00Z",
    **overrides,
):
    """Body for a routing adjustment, which auto-accepts at creation."""
    payload = {
        "planning_cycle_id": planning_cycle_id,
        "kind": "ROUTING_ADJUSTMENT",
        "expires_at": expires_at,
        "source_forecast_group_id": source_forecast_group_id,
        "target_forecast_group_id": target_forecast_group_id,
        "agents_shifted": agents_shifted,
        "interval_start": interval_start,
    }
    payload.update(overrides)
    return payload


def action_response_payload(response=RESPONSE_ACCEPT, **overrides):
    """Body for the offered agent's answer."""
    payload = {"response": response}
    payload.update(overrides)
    return payload


# ─── Outsourced partners ──────────────────────────────

def outsource_partner_payload(**overrides):
    """A CHAT_EN partner at 12,500 millicents per handled contact."""
    payload = {
        "legal_name": f"Partner {unique_suffix()}",
        "skill_codes": ["CHAT_EN"],
        "rate_per_contact_millicents": 12500,
        "interval_max_volume": 50,
        "commitment_floor_volume": 10,
        "performance_threshold_pct": 0.8500,
        "billing_basis": BILLING_COMMITMENT_FLOOR,
    }
    payload.update(overrides)
    return payload


def performance_report_payload(
    sl_attainment_pct, period_end_date="2026-08-31", **overrides
):
    """Body for a partner service-level attainment report."""
    payload = {
        "period_end_date": period_end_date,
        "sl_attainment_pct": sl_attainment_pct,
    }
    payload.update(overrides)
    return payload


# ─── Partner allocations ──────────────────────────────

def partner_allocation_payload(
    outsource_partner_id, interval_plan_id, allocated_volume, **overrides
):
    """Body for proposing one allocation against one interval."""
    payload = {
        "outsource_partner_id": outsource_partner_id,
        "interval_plan_id": interval_plan_id,
        "allocated_volume": allocated_volume,
    }
    payload.update(overrides)
    return payload


def generate_allocations_payload(interval_plan_id, **overrides):
    """Body for the cheapest-first allocation waterfall."""
    payload = {"interval_plan_id": interval_plan_id}
    payload.update(overrides)
    return payload


def commit_allocation_payload(expected_partner_version, **overrides):
    """Body for committing an allocation, carrying the partner-version echo."""
    payload = {"expected_partner_version": expected_partner_version}
    payload.update(overrides)
    return payload


def settle_allocation_payload(delivered_volume, **overrides):
    """Body for settling a committed allocation."""
    payload = {"delivered_volume": delivered_volume}
    payload.update(overrides)
    return payload


# ─── Hiring classes ───────────────────────────────────

def hiring_class_payload(planning_cycle_id, labor_agreement_id, **overrides):
    """A twenty-four-seat cohort at 0.1250 expected attrition."""
    payload = {
        "planning_cycle_id": planning_cycle_id,
        "labor_agreement_id": labor_agreement_id,
        "cohort_name": f"CLASS-A-{unique_suffix()}",
        "skill_code": "VOICE_EN",
        "start_date": "2026-08-24",
        "seats": 24,
        "training_weeks": 2,
        "nesting_weeks": 2,
        "expected_attrition_pct": 0.1250,
        "graduate_hourly_rate_cents": 2200,
        "graduate_weekly_hours": 37.5,
    }
    payload.update(overrides)
    return payload


def hiring_class_status_payload(target_status, **overrides):
    """Body for driving the hiring-class lifecycle short of graduation."""
    payload = {"target_status": target_status}
    payload.update(overrides)
    return payload
