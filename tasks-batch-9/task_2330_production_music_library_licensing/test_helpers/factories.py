"""Payload builders with valid defaults for every write endpoint.

Each builder produces a payload that passes the schema pass of the validation
ladder, so a test only has to name the one field it wants to be wrong. Every
default is a value the PRD allows for that field.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    DEFAULT_QUOTE_VALID_DAYS,
    DEFAULT_TAX_WITHHOLDING_PCT,
)

JsonDict = Dict[str, Any]

_counter = {"n": 0}


def next_suffix() -> int:
    """Monotonic per-process counter for unique codes and references."""
    _counter["n"] += 1
    return _counter["n"]


def _merge(base: JsonDict, overrides: JsonDict) -> JsonDict:
    payload = dict(base)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Composers and agreements
# ---------------------------------------------------------------------------


def composer_payload(**overrides: Any) -> JsonDict:
    return _merge(
        {
            "display_name": f"Composer {next_suffix()}",
            "pro_affiliation": "ASCAP",
            "payee_country": "US",
            "tax_withholding_pct": DEFAULT_TAX_WITHHOLDING_PCT,
        },
        overrides,
    )


def royalty_split_agreement_payload(composer_id: str, **overrides: Any) -> JsonDict:
    """A ROYALTY_SPLIT agreement: buyout must be exactly 0."""
    return _merge(
        {
            "composer_id": composer_id,
            "agreement_type": "ROYALTY_SPLIT",
            "writer_share_pct": 50.00,
            "publisher_share_pct": 50.00,
            "sync_fee_share_pct": 40.00,
            "buyout_fee_cents": 0,
            "exclusivity": "NON_EXCLUSIVE",
            "holdback_days": 0,
            "advance_cents": 0,
            "blanket_opt_in": True,
        },
        overrides,
    )


def work_for_hire_agreement_payload(composer_id: str, **overrides: Any) -> JsonDict:
    """A WORK_FOR_HIRE agreement: sync share exactly 0, buyout strictly above 0."""
    return _merge(
        {
            "composer_id": composer_id,
            "agreement_type": "WORK_FOR_HIRE",
            "writer_share_pct": 50.00,
            "publisher_share_pct": 50.00,
            "sync_fee_share_pct": 0.00,
            "buyout_fee_cents": 250000,
            "exclusivity": "NON_EXCLUSIVE",
            "holdback_days": 0,
            "advance_cents": 0,
            "blanket_opt_in": True,
        },
        overrides,
    )


def amendment_payload(**overrides: Any) -> JsonDict:
    return _merge(
        {
            "proposed_writer_share_pct": 60.00,
            "proposed_publisher_share_pct": 40.00,
            "proposed_sync_fee_share_pct": 45.00,
            "proposed_holdback_days": 30,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Compositions and search
# ---------------------------------------------------------------------------


def composition_payload(composer_id: str, agreement_id: str, **overrides: Any) -> JsonDict:
    return _merge(
        {
            "composer_id": composer_id,
            "agreement_id": agreement_id,
            "title": f"Work {next_suffix()}",
            "duration_sec": 180,
            "tempo_bpm": 120,
            "genre": "CINEMATIC",
            "mood_tags": ["EPIC"],
            "instrumentation": ["STRINGS"],
        },
        overrides,
    )


def search_profile_payload(**overrides: Any) -> JsonDict:
    return _merge(
        {
            "weight_mood": 40,
            "weight_genre": 20,
            "weight_instrumentation": 20,
            "weight_tempo": 20,
            "tempo_tolerance_bpm": 20,
            "restricted_availability_factor": 0.60,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Rate card and licensees
# ---------------------------------------------------------------------------


def license_tier_payload(**overrides: Any) -> JsonDict:
    return _merge(
        {
            "code": f"TIER-{next_suffix():04d}",
            "media_type": "BROADCAST_TV",
            "allowed_scales": ["LOCAL", "NATIONAL", "WORLDWIDE"],
            "base_rate_cents": 300000,
            "min_term_months": 1,
            "max_term_months": 120,
            "per_use_eligible": True,
            "blanket_eligible": False,
        },
        overrides,
    )


def blanket_tier_payload(**overrides: Any) -> JsonDict:
    """A tier a blanket licence may cite: per-use ineligible, blanket eligible."""
    return license_tier_payload(
        per_use_eligible=False, blanket_eligible=True, allowed_scales=["NATIONAL"], **overrides
    )


def licensee_payload(**overrides: Any) -> JsonDict:
    return _merge(
        {
            "legal_name": f"Licensee {next_suffix()}",
            "licensee_type": "PRODUCTION_COMPANY",
            "credit_limit_cents": 10000000,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Sync requests, quotes and licences
# ---------------------------------------------------------------------------


def sync_request_payload(
    composition_id: str, licensee_id: str, tier_id: str, **overrides: Any
) -> JsonDict:
    return _merge(
        {
            "composition_id": composition_id,
            "licensee_id": licensee_id,
            "tier_id": tier_id,
            "media_type": "BROADCAST_TV",
            "distribution_scale": "NATIONAL",
            "requested_term_start": "2026-09-01T00:00:00Z",
            "requested_term_months": 12,
            "exclusive_requested": False,
            "custom_edit_requested": False,
            "stems_requested": False,
            "alternate_lengths_sec": [],
            "rush_requested": False,
        },
        overrides,
    )


def quote_payload(quote_valid_days: int = DEFAULT_QUOTE_VALID_DAYS, **overrides: Any) -> JsonDict:
    return _merge({"quote_valid_days": quote_valid_days}, overrides)


def revision_payload(revision_note: str = "please revise", **overrides: Any) -> JsonDict:
    return _merge({"revision_note": revision_note}, overrides)


def per_use_license_payload(
    sync_request_id: str, expected_composition_version: int, **overrides: Any
) -> JsonDict:
    return _merge(
        {
            "license_mode": "PER_USE",
            "sync_request_id": sync_request_id,
            "expected_composition_version": expected_composition_version,
        },
        overrides,
    )


def blanket_license_payload(
    composition_id: str,
    blanket_agreement_id: str,
    tier_id: str,
    expected_composition_version: int,
    **overrides: Any,
) -> JsonDict:
    return _merge(
        {
            "license_mode": "BLANKET",
            "expected_composition_version": expected_composition_version,
            "composition_id": composition_id,
            "blanket_agreement_id": blanket_agreement_id,
            "tier_id": tier_id,
            "media_type": "BROADCAST_TV",
            "distribution_scale": "NATIONAL",
            "term_start": "2026-08-01T00:00:00Z",
            "term_months": 12,
        },
        overrides,
    )


def deliver_payload(delivered_asset_count: int = 1, **overrides: Any) -> JsonDict:
    return _merge({"delivered_asset_count": delivered_asset_count}, overrides)


# ---------------------------------------------------------------------------
# Blanket coverage, usage reports and cue sheets
# ---------------------------------------------------------------------------


def blanket_agreement_payload(licensee_id: str, **overrides: Any) -> JsonDict:
    return _merge(
        {
            "licensee_id": licensee_id,
            "coverage_start": "2026-08-01T00:00:00Z",
            "coverage_end": "2027-08-01T00:00:00Z",
            "annual_fee_cents": 4800000,
            "reporting_cadence": "MONTHLY",
            "usage_cap_minutes": 3,
            "pool_share_pct": 25.00,
        },
        overrides,
    )


def usage_report_payload(blanket_agreement_id: str, **overrides: Any) -> JsonDict:
    return _merge(
        {
            "blanket_agreement_id": blanket_agreement_id,
            "period_start": "2026-08-01T00:00:00Z",
            "period_end": "2026-08-31T00:00:00Z",
        },
        overrides,
    )


def cue(composition_id: str, usage_type: str = "THEME", duration_sec: int = 45) -> JsonDict:
    return {
        "composition_id": composition_id,
        "usage_type": usage_type,
        "duration_sec": duration_sec,
    }


def cue_sheet_payload(
    cues: List[JsonDict],
    license_id: Optional[str] = None,
    usage_report_id: Optional[str] = None,
    **overrides: Any,
) -> JsonDict:
    payload: JsonDict = {
        "production_title": f"Production {next_suffix()}",
        "broadcast_date": "2026-08-01T00:00:00Z",
        "market_tier": "NETWORK",
        "cues": cues,
    }
    if license_id is not None:
        payload["license_id"] = license_id
    if usage_report_id is not None:
        payload["usage_report_id"] = usage_report_id
    return _merge(payload, overrides)


def three_cue_network_sheet(composition_id: str, **overrides: Any) -> JsonDict:
    """THEME / FEATURE / BACKGROUND at 45 seconds each on a NETWORK sheet."""
    return cue_sheet_payload(
        [
            cue(composition_id, "THEME", 45),
            cue(composition_id, "FEATURE", 45),
            cue(composition_id, "BACKGROUND", 45),
        ],
        **overrides,
    )


# ---------------------------------------------------------------------------
# Fingerprint matches and claims
# ---------------------------------------------------------------------------


def fingerprint_match_payload(composition_id: str, **overrides: Any) -> JsonDict:
    return _merge(
        {
            "composition_id": composition_id,
            "source_platform": "UGC_VIDEO",
            "source_reference": f"ugc:detection-{next_suffix()}",
            "matched_seconds": 225,
            "confidence_pct": 99.0,
        },
        overrides,
    )


def settle_claim_payload(settlement_basis: str = "STATUTORY", **overrides: Any) -> JsonDict:
    return _merge(
        {"settlement_basis": settlement_basis, "payment_received": True}, overrides
    )


# ---------------------------------------------------------------------------
# Ledger and statements
# ---------------------------------------------------------------------------


def ledger_entry_payload(composer_id: str, amount_cents: int, **overrides: Any) -> JsonDict:
    return _merge(
        {
            "composer_id": composer_id,
            "source_type": "ADJUSTMENT",
            "amount_cents": amount_cents,
            "memo": f"manual adjustment {next_suffix()}",
        },
        overrides,
    )


def statement_payload(
    composer_id: str, expected_composer_version: int, **overrides: Any
) -> JsonDict:
    return _merge(
        {
            "composer_id": composer_id,
            "period_start": "2026-08-01T00:00:00Z",
            "period_end": "2026-08-31T00:00:00Z",
            "basis": "ACCRUAL",
            "expected_composer_version": expected_composer_version,
        },
        overrides,
    )


def preview_params(
    period_start: str = "2026-08-01T00:00:00Z",
    period_end: str = "2026-08-31T00:00:00Z",
    basis: Optional[str] = None,
) -> JsonDict:
    params: JsonDict = {"period_start": period_start, "period_end": period_end}
    if basis is not None:
        params["basis"] = basis
    return params
