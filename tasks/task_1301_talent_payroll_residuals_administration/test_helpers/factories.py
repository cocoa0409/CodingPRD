"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
import itertools

from .constants import (
    ENGAGEMENT_END_DATE,
    ENGAGEMENT_START_DATE,
    MEAL_PENALTY_CENTS,
    PHW_HEALTH_PCT,
    PHW_PENSION_PCT,
    PHW_WELFARE_PCT,
    REST_PENALTY_CENTS,
    T1_DAY_RATE_CENTS,
    T1_OT_MULTIPLIER,
    T1_OT_THRESHOLD_MINUTES,
    T2_DAY_RATE_CENTS,
    TURNAROUND_MIN_HOURS,
)

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_union_agreement_payload(**overrides) -> dict:
    defaults = {
        "union_code": "SAG_AFTRA",
        "name": f"SAG Basic 2026 #{_n()}",
        "effective_from": "2026-01-01",
        "effective_to": "2027-01-01",
        "rate_tiers": [
            {"tier_code": "T1", "category": "PRINCIPAL",
             "day_rate_cents": T1_DAY_RATE_CENTS,
             "ot_daily_threshold_minutes": T1_OT_THRESHOLD_MINUTES,
             "ot_multiplier": T1_OT_MULTIPLIER},
            {"tier_code": "T2", "category": "BACKGROUND",
             "day_rate_cents": T2_DAY_RATE_CENTS,
             "ot_daily_threshold_minutes": T1_OT_THRESHOLD_MINUTES,
             "ot_multiplier": T1_OT_MULTIPLIER},
        ],
        "meal_penalty_cents": MEAL_PENALTY_CENTS,
        "rest_penalty_cents": REST_PENALTY_CENTS,
        "turnaround_min_hours": TURNAROUND_MIN_HOURS,
        "phw_pension_pct": PHW_PENSION_PCT,
        "phw_health_pct": PHW_HEALTH_PCT,
        "phw_welfare_pct": PHW_WELFARE_PCT,
        "residual_base_pct_by_market": {
            "NETWORK_REBROADCAST": 0.025,
            "SYNDICATION": 0.045,
            "STREAMING": 0.012,
        },
    }
    defaults.update(overrides)
    return defaults


def create_production_payload(union_agreement_id, **overrides) -> dict:
    defaults = {
        "title": f"Picture {_n()}",
        "production_company": "Studio X",
        "union_agreement_id": union_agreement_id,
        "production_type": "FILM",
        "jurisdictions": [
            {"jurisdiction_code": "CA", "tax_pct": 0.10,
             "valid_from": "2026-01-01", "valid_to": "2027-01-01"},
            {"jurisdiction_code": "NM", "tax_pct": 0.05,
             "valid_from": "2026-01-01", "valid_to": "2027-01-01"},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_performer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": f"Pat Star {_n()}",
        "primary_union_code": "SAG_AFTRA",
        "tax_residency_state": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_engagement_payload(production_id, union_agreement_id, performer_id,
                              **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "union_agreement_id": union_agreement_id,
        "performer_id": performer_id,
        "tier_code": "T1",
        "payee_type": "DIRECT",
        "weekly_guarantee_cents": 500000,
        "guaranteed_days": 20,
        "start_date": ENGAGEMENT_START_DATE,
        "end_date": ENGAGEMENT_END_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_timecard_payload(engagement_id, **overrides) -> dict:
    """Default is the TC-A card: call 08:00, meal 14:30-15:00, wrap 19:00."""
    defaults = {
        "engagement_id": engagement_id,
        "work_date": "2026-08-10",
        "jurisdiction_code": "CA",
        "call_time": "2026-08-10T08:00:00Z",
        "first_meal_out": "2026-08-10T14:30:00Z",
        "first_meal_in": "2026-08-10T15:00:00Z",
        "wrap_time": "2026-08-10T19:00:00Z",
        "scheduled_hours": 10,
    }
    defaults.update(overrides)
    return defaults


def revise_timecard_payload(**overrides) -> dict:
    defaults = {
        "call_time": "2026-08-10T08:00:00Z",
        "first_meal_out": "2026-08-10T14:30:00Z",
        "first_meal_in": "2026-08-10T15:00:00Z",
        "wrap_time": "2026-08-10T19:00:00Z",
        "scheduled_hours": 10,
    }
    defaults.update(overrides)
    return defaults


def create_residual_obligation_payload(engagement_id, **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "reuse_market": "SYNDICATION",
        "window_start": "2027-01-05",
        "window_end": "2027-06-30",
        "reported_gross_receipts_cents": 20000000,
    }
    defaults.update(overrides)
    return defaults


def create_pay_batch_payload(**overrides) -> dict:
    defaults = {
        "period_label": f"2026-W33 #{_n()}",
        "cutoff_date": "2026-08-31",
    }
    defaults.update(overrides)
    return defaults


def create_garnishment_order_payload(performer_id, **overrides) -> dict:
    """Exactly one of pct_of_disposable / fixed_amount_cents per PRD §3.10:
    default is pct_of_disposable; a fixed-amount override drops it."""
    defaults = {
        "performer_id": performer_id,
        "creditor_name": "County CSA",
        "order_type": "CHILD_SUPPORT",
        "priority_rank": 1,
        "pct_of_disposable": 0.20,
    }
    if "fixed_amount_cents" in overrides and "pct_of_disposable" not in overrides:
        defaults.pop("pct_of_disposable")
    defaults.update(overrides)
    return defaults


def create_remittance_report_payload(pay_batch_id, union_agreement_id, **overrides) -> dict:
    defaults = {
        "pay_batch_id": pay_batch_id,
        "union_agreement_id": union_agreement_id,
    }
    defaults.update(overrides)
    return defaults


def create_grievance_case_payload(engagement_id, **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "category": "UNDERPAYMENT",
        "claimed_amount_cents": 10000,
        "description": "OT underpaid for 2026-08-10",
    }
    defaults.update(overrides)
    return defaults
