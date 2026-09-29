"""Payload builders with PRD-valid defaults.

Each builder returns a plain dict that satisfies every shape rule PRD 2.6 step 7
states for that operation, and accepts keyword overrides so a test can perturb
exactly one field. Passing ``None`` for an optional field transmits an explicit
null; omit the keyword entirely to leave the default in place.

Two format rules drive the id generators below: `market_code` "must match a
literal `DMA-` prefix followed by exactly three digits" and `serial_no` "must
match a literal `MT-` prefix followed by exactly six digits".
"""

import itertools
from typing import Any, Dict, List, Optional

_market_code_seq = itertools.count(101)
_serial_seq = itertools.count(100001)
_label_seq = itertools.count(1)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    base.update(overrides)
    return base


def next_market_code() -> str:
    """A fresh `DMA-` plus exactly three digits code, unique within a test."""
    return f"DMA-{next(_market_code_seq) % 1000:03d}"


def next_serial_no() -> str:
    """A fresh `MT-` plus exactly six digits serial, unique within a test."""
    return f"MT-{next(_serial_seq) % 1000000:06d}"


def next_rule_set_label(stem: str = "RULES") -> str:
    """A globally unique editing rule set label of 1 to 60 characters."""
    return f"{stem}-{next(_label_seq):04d}"


# ----------------------------------------------------------------------
# Markets and quota cells (PRD 3.1)
# ----------------------------------------------------------------------

def market_payload(
    name: str = "Ridgemont-Alder DMA",
    market_code: Optional[str] = None,
    dma_rank: int = 32,
    incentive_budget_cents: int = 5000000,
    **overrides,
) -> Dict[str, Any]:
    """A registrable market. `dma_rank` of at least 1; budget of at least 0."""
    return _merge(
        {
            "name": name,
            "market_code": market_code if market_code is not None else next_market_code(),
            "dma_rank": dma_rank,
            "incentive_budget_cents": incentive_budget_cents,
        },
        overrides,
    )


def quota_cell_payload(
    age_band: str = "P18_34",
    income_band: str = "MID",
    geo_zone: str = "URBAN",
    target_households: int = 10,
    base_incentive_cents: int = 2000,
    **overrides,
) -> Dict[str, Any]:
    """One demographic-by-geographic stratum; `target_households` at least 1."""
    return _merge(
        {
            "age_band": age_band,
            "income_band": income_band,
            "geo_zone": geo_zone,
            "target_households": target_households,
            "base_incentive_cents": base_incentive_cents,
        },
        overrides,
    )


def budget_adjustment_payload(
    delta_cents: int = 100000, memo: str = "Quarterly authorisation top-up", **overrides
) -> Dict[str, Any]:
    """A signed `delta_cents` together with a `memo` recording why."""
    return _merge({"delta_cents": delta_cents, "memo": memo}, overrides)


# ----------------------------------------------------------------------
# Universe estimates and editing rule sets (PRD 3.5)
# ----------------------------------------------------------------------

def cell_population(
    quota_cell_id: str, population_households: int = 100000, population_persons: int = 250000
) -> Dict[str, Any]:
    """One `cell_populations` entry; `population_households` at least 1."""
    return {
        "quota_cell_id": quota_cell_id,
        "population_households": population_households,
        "population_persons": population_persons,
    }


def universe_estimate_payload(
    market_id: str,
    expected_market_version: int,
    cell_populations: List[Dict[str, Any]],
    vintage_label: str = "2026Q3",
    effective_from: str = "2026-07-01T00:00:00Z",
    effective_to: str = "2026-10-01T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    """A drafted vintage. `vintage_label` is four digits, `Q`, then 1 through 4."""
    return _merge(
        {
            "market_id": market_id,
            "vintage_label": vintage_label,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "cell_populations": cell_populations,
            "expected_market_version": expected_market_version,
        },
        overrides,
    )


def edit_rule_set_payload(
    label: Optional[str] = None,
    missing_interval_ascription_minutes: int = 30,
    invalid_tuning_max_minutes: int = 600,
    outlier_household_minutes_cap: int = 100000,
    outlier_weight_ratio_cap: float = 3.0,
    fault_missing_minutes_threshold: int = 1440,
    **overrides,
) -> Dict[str, Any]:
    """A permissive reference rule set: nothing here invalidates ordinary data."""
    return _merge(
        {
            "label": label if label is not None else next_rule_set_label(),
            "missing_interval_ascription_minutes": missing_interval_ascription_minutes,
            "invalid_tuning_max_minutes": invalid_tuning_max_minutes,
            "outlier_household_minutes_cap": outlier_household_minutes_cap,
            "outlier_weight_ratio_cap": outlier_weight_ratio_cap,
            "fault_missing_minutes_threshold": fault_missing_minutes_threshold,
        },
        overrides,
    )


# ----------------------------------------------------------------------
# Households and meters (PRD 3.2, 3.3)
# ----------------------------------------------------------------------

def household_payload(
    market_id: str,
    quota_cell_id: str,
    recruitment_source: str = "ADDRESS_SAMPLE",
    persons_count: int = 3,
    **overrides,
) -> Dict[str, Any]:
    """A recruited home. `recruitment_source` is one of the three PRD 3.2 sources."""
    return _merge(
        {
            "market_id": market_id,
            "quota_cell_id": quota_cell_id,
            "recruitment_source": recruitment_source,
            "persons_count": persons_count,
        },
        overrides,
    )


def enumeration_payload(
    roster_persons_count: int = 3, tv_sets_count: int = 2, **overrides
) -> Dict[str, Any]:
    """A visit submission. Roster 1 to 12 inclusive; sets 0 to 8 inclusive."""
    return _merge(
        {"roster_persons_count": roster_persons_count, "tv_sets_count": tv_sets_count},
        overrides,
    )


def meter_payload(
    household_id: str,
    meter_type: str = "TV_TUNER",
    serial_no: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """A shipped device with a fresh `MT-` plus six digits serial."""
    return _merge(
        {
            "household_id": household_id,
            "meter_type": meter_type,
            "serial_no": serial_no if serial_no is not None else next_serial_no(),
        },
        overrides,
    )


def tuning_interval_payload(
    meter_id: str,
    household_id: str,
    start_iso: str,
    end_iso: str,
    tuning_minutes: int,
    source_methodology: str = "INHOME_TUNER",
    station_code: str = "KRDG-DT",
    **overrides,
) -> Dict[str, Any]:
    """One measured block. `tuning_minutes` must not exceed the block's wall length."""
    return _merge(
        {
            "meter_id": meter_id,
            "household_id": household_id,
            "source_methodology": source_methodology,
            "start_iso": start_iso,
            "end_iso": end_iso,
            "station_code": station_code,
            "tuning_minutes": tuning_minutes,
        },
        overrides,
    )


def processing_run_payload(
    market_id: str,
    universe_estimate_id: str,
    edit_rule_set_id: str,
    expected_market_version: int,
    window_start_iso: str = "2026-08-01T00:00:00Z",
    window_end_iso: str = "2026-08-02T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    """An opened run over a one-day window inside the reference vintage range."""
    return _merge(
        {
            "market_id": market_id,
            "universe_estimate_id": universe_estimate_id,
            "edit_rule_set_id": edit_rule_set_id,
            "window_start_iso": window_start_iso,
            "window_end_iso": window_end_iso,
            "expected_market_version": expected_market_version,
        },
        overrides,
    )


# ----------------------------------------------------------------------
# Clients and deliverables (PRD 3.8)
# ----------------------------------------------------------------------

def client_payload(
    contract_market_ids: List[str],
    name: str = "Alder Broadcasting Group",
    tier: str = "STANDARD",
    **overrides,
) -> Dict[str, Any]:
    """A subscriber. `contract_market_ids` holds 1 to 10 unique market ids."""
    return _merge(
        {"name": name, "tier": tier, "contract_market_ids": list(contract_market_ids)},
        overrides,
    )


def scheduled_deliverable_payload(
    processing_run_id: str, requested_cell_count: int = 4, **overrides
) -> Dict[str, Any]:
    """A dataset placement; `requested_cell_count` between 0 and 24."""
    return _merge(
        {
            "processing_run_id": processing_run_id,
            "requested_cell_count": requested_cell_count,
        },
        overrides,
    )


def custom_analysis_payload(
    client_id: str,
    processing_run_id: str,
    question: str = "Which suburban cells drove the week-over-week lift?",
    requested_cell_count: int = 3,
    **overrides,
) -> Dict[str, Any]:
    """A bespoke question; `question` 1 to 400 chars, cell count at least 1."""
    return _merge(
        {
            "client_id": client_id,
            "processing_run_id": processing_run_id,
            "question": question,
            "requested_cell_count": requested_cell_count,
        },
        overrides,
    )


# ----------------------------------------------------------------------
# Governance (PRD 3.9)
# ----------------------------------------------------------------------

def methodology_change_payload(
    target_edit_rule_set_id: str,
    proposed_edit_rule_set_id: str,
    affected_market_ids: List[str],
    title: str = "Tighten the invalid-tuning ceiling for 2027Q1",
    **overrides,
) -> Dict[str, Any]:
    """A drafted change; `title` 1 to 160 chars, 1 to 10 unique affected markets."""
    return _merge(
        {
            "title": title,
            "target_edit_rule_set_id": target_edit_rule_set_id,
            "proposed_edit_rule_set_id": proposed_edit_rule_set_id,
            "affected_market_ids": list(affected_market_ids),
        },
        overrides,
    )


def accreditation_audit_payload(
    market_id: str,
    scope_edit_rule_set_id: str,
    auditor_note: str = "Annual methodology review of the editing rule set in force.",
    **overrides,
) -> Dict[str, Any]:
    """An opened audit; `auditor_note` 1 to 400 characters recording the scope."""
    return _merge(
        {
            "market_id": market_id,
            "scope_edit_rule_set_id": scope_edit_rule_set_id,
            "auditor_note": auditor_note,
        },
        overrides,
    )


def finalize_audit_payload(
    outcome: str = "ACCREDITED",
    limitation_disclosures: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """A finalization. For `ACCREDITED` the disclosure array may be empty."""
    return _merge(
        {
            "outcome": outcome,
            "limitation_disclosures": (
                [] if limitation_disclosures is None else list(limitation_disclosures)
            ),
        },
        overrides,
    )
