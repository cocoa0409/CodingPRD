"""Payload factories — one per entity, input fields only (PRD §3 / §4)."""
from .constants import DEFAULTS


def create_network_payload(**overrides) -> dict:
    defaults = {
        "call_sign": DEFAULTS["NETWORK_CALL_SIGN"],
        "primary_feed_tz": DEFAULTS["NETWORK_TZ"],
        "reverse_comp_standard_pct": DEFAULTS["REVERSE_COMP_PCT"],
        "retrans_share_standard_pct": DEFAULTS["RETRANS_SHARE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_station_group_payload(**overrides) -> dict:
    defaults = {
        "group_name": DEFAULTS["GROUP_NAME"],
        "leverage_tier": DEFAULTS["LEVERAGE_TIER"],
    }
    defaults.update(overrides)
    return defaults


def create_station_payload(**overrides) -> dict:
    defaults = {
        "call_sign": DEFAULTS["STATION_CALL_SIGN"],
        "dma_code": DEFAULTS["DMA_CODE"],
    }
    # station_group_id is required; allow override
    if "station_group_id" in overrides:
        defaults["station_group_id"] = overrides.pop("station_group_id")
    defaults.update(overrides)
    return defaults


def create_territory_payload(**overrides) -> dict:
    defaults = {
        "dma_code": DEFAULTS["DMA_CODE"],
        "protection_window_start_utc": "2026-05-01T00:00:00Z",
        "protection_window_end_utc": "2026-06-30T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["PROG_TITLE"],
        "scheduled_start_utc": DEFAULTS["PROG_START"],
        "scheduled_end_utc": DEFAULTS["PROG_END"],
        "avail_minutes_total": DEFAULTS["PROG_AVAIL_TOTAL"],
        "avail_minutes_local_allocatable": DEFAULTS["PROG_AVAIL_LOCAL"],
        "is_syndicated": False,
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "term_start_utc": DEFAULTS["TERM_START"],
        "term_end_utc": DEFAULTS["TERM_END"],
        "reverse_comp_pct": DEFAULTS["REVERSE_COMP_PCT"],
        "retrans_share_pct": DEFAULTS["RETRANS_SHARE_PCT"],
        "clearance_obligation_hours": DEFAULTS["CLEARANCE_OBLIGATION_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_renewal_offer_payload(**overrides) -> dict:
    defaults = {
        "proposed_by_role": "NETWORK_AFFILIATE_RELATIONS",
        "proposed_reverse_comp_pct": 0.45,
        "proposed_retrans_share_pct": 0.55,
        "proposed_term_months": 24,
    }
    defaults.update(overrides)
    return defaults


def create_clearance_report_payload(**overrides) -> dict:
    defaults = {
        "period_index": 0,
        "cleared_hours": 90.0,
        "preempted_hours": 10.0,
    }
    defaults.update(overrides)
    return defaults


def create_preemption_payload(**overrides) -> dict:
    defaults = {
        "requested_start_utc": "2026-06-01T20:00:00Z",
        "requested_end_utc": "2026-06-01T21:00:00Z",
        "reason": "BREAKING_NEWS",
    }
    if "program_id" in overrides:
        defaults["program_id"] = overrides.pop("program_id")
    if "agreement_id" in overrides:
        defaults["agreement_id"] = overrides.pop("agreement_id")
    defaults.update(overrides)
    return defaults


def create_avail_allocation_payload(**overrides) -> dict:
    defaults = {
        "period_index": 0,
        "local_minutes_claimed": 5,
        "claimed_revenue_cents": 100,
    }
    if "program_id" in overrides:
        defaults["program_id"] = overrides.pop("program_id")
    defaults.update(overrides)
    return defaults


def create_retrans_settlement_payload(**overrides) -> dict:
    defaults = {
        "period_index": 0,
        "gross_retrans_cents": 1_000_000,
    }
    if "agreement_id" in overrides:
        defaults["agreement_id"] = overrides.pop("agreement_id")
    defaults.update(overrides)
    return defaults


def create_outage_event_payload(**overrides) -> dict:
    defaults = {
        "period_index": 0,
        "started_at_utc": "2026-05-05T01:00:00Z",
        "ended_at_utc": "2026-05-05T02:00:00Z",
        "cause": "POWER_LOSS",
    }
    defaults.update(overrides)
    return defaults


def create_compliance_report_payload(**overrides) -> dict:
    defaults = {
        "period_index": 0,
        "report_kind": "FCC_302",
    }
    defaults.update(overrides)
    return defaults


def create_exclusivity_claim_payload(**overrides) -> dict:
    defaults = {
        "alleged_window_start_utc": "2026-06-01T19:00:00Z",
        "alleged_window_end_utc": "2026-06-01T21:00:00Z",
    }
    # Required FK references; allow override
    for key in ("program_id", "claimant_station_id", "respondent_station_id"):
        if key in overrides:
            defaults[key] = overrides.pop(key)
    defaults.update(overrides)
    return defaults
