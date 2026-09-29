"""Payload factories — one per write endpoint, input fields only.

Every factory accepts ``**overrides`` so a test can control exactly the input
it is exercising and inherit sensible values for everything else.
"""

from typing import Any, Dict

from .constants import (
    CONTRACT_EFFECTIVE_FROM,
    CONTRACT_EFFECTIVE_TO,
    ROUND_CLOSES_AT,
    TEST_DEFAULTS,
)


def _merge(defaults: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(defaults)
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not _OMIT}


class _Omit:
    """Sentinel meaning "leave this optional field out of the payload"."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<OMIT>"


_OMIT = _Omit()
OMIT = _OMIT


# ─── Carriers and qualification ───────────────────────────────────────────────

def carrier_payload(**overrides) -> Dict[str, Any]:
    """Registration payload for a carrier (PRD §3.1)."""
    return _merge(
        {
            "legal_name": TEST_DEFAULTS["CARRIER_A_LEGAL_NAME"],
            "scac_code": TEST_DEFAULTS["CARRIER_A_SCAC"],
            "diversity_classification": "NONE",
            "service_modes": ["DRY_VAN"],
            "fleet_power_units": TEST_DEFAULTS["CARRIER_A_FLEET_POWER_UNITS"],
            "auto_liability_limit_usd": TEST_DEFAULTS["CARRIER_A_AUTO_LIABILITY_USD"],
            "cargo_limit_usd": TEST_DEFAULTS["CARRIER_A_CARGO_USD"],
            "insurance_expiry_date": TEST_DEFAULTS["CARRIER_A_INSURANCE_EXPIRY"],
        },
        overrides,
    )


def qualification_review_payload(**overrides) -> Dict[str, Any]:
    """Payload opening a qualification review (PRD §3.1)."""
    return _merge(
        {
            "required_modes": ["DRY_VAN"],
            "min_auto_liability_usd": 1000000.00,
            "min_cargo_usd": 100000.00,
        },
        overrides,
    )


def insurance_verification_payload(**overrides) -> Dict[str, Any]:
    """Payload for the insurance arm of a review (PRD §3.1)."""
    return _merge(
        {
            "verified_auto_liability_usd": 1000000.00,
            "verified_cargo_usd": 250000.00,
            "verified_expiry_date": TEST_DEFAULTS["CARRIER_A_INSURANCE_EXPIRY"],
        },
        overrides,
    )


def decision_payload(**overrides) -> Dict[str, Any]:
    """Payload recording a qualification decision (PRD §3.1)."""
    return _merge({"outcome": "APPROVE", "decision_note": _OMIT}, overrides)


def carrier_status_change_payload(**overrides) -> Dict[str, Any]:
    """Payload for an administrative carrier status change (PRD §3.1)."""
    return _merge(
        {"to_status": "SUSPENDED", "reason": "Administrative action under test"},
        overrides,
    )


def scorecard_payload(**overrides) -> Dict[str, Any]:
    """Payload drafting a period scorecard (PRD §3.2)."""
    return _merge(
        {
            "period_start": "2026-05-01T00:00:00Z",
            "period_end": "2026-08-01T00:00:00Z",
            "on_time_pct": 96.00,
            "claims_ratio": 0.0150,
        },
        overrides,
    )


def scorecard_dispute_payload(**overrides) -> Dict[str, Any]:
    """Payload recording a carrier's dispute of a published scorecard (PRD §3.2)."""
    return _merge({"disputed_reason": "On-time data disputed by the carrier"}, overrides)


# ─── Bid events, lanes and invitations ────────────────────────────────────────

def bid_event_payload(**overrides) -> Dict[str, Any]:
    """Payload opening a bid event (PRD §3.3)."""
    return _merge(
        {
            "name": "Annual Truckload Procurement",
            "cost_basis": "FORECAST",
            "fuel_index_per_mile": TEST_DEFAULTS["EVENT_FUEL_INDEX_PER_MILE"],
            "accessorial_inflation_factor": TEST_DEFAULTS[
                "EVENT_ACCESSORIAL_INFLATION_FACTOR"
            ],
            "rate_floor_per_mile": TEST_DEFAULTS["EVENT_RATE_FLOOR_PER_MILE"],
            "rounds_allowed": 1,
            "cost_weight": TEST_DEFAULTS["EVENT_COST_WEIGHT"],
            "service_weight": TEST_DEFAULTS["EVENT_SERVICE_WEIGHT"],
            "capacity_weight": TEST_DEFAULTS["EVENT_CAPACITY_WEIGHT"],
            "diversity_weight": TEST_DEFAULTS["EVENT_DIVERSITY_WEIGHT"],
            "diversity_min_pct": 0.00,
            "max_award_share_pct": 100.00,
            "max_carriers_per_lane": 1,
            "contract_effective_from": CONTRACT_EFFECTIVE_FROM,
            "contract_effective_to": CONTRACT_EFFECTIVE_TO,
        },
        overrides,
    )


def lane_payload(**overrides) -> Dict[str, Any]:
    """Payload adding the 1147-mile dry-van lane to a draft event (PRD §3.3)."""
    return _merge(
        {
            "lane_code": TEST_DEFAULTS["LANE_A_CODE"],
            "origin_zip3": "300",
            "dest_zip3": "606",
            "equipment_type": "DRY_VAN",
            "mileage": TEST_DEFAULTS["LANE_A_MILEAGE"],
            "annual_volume_loads": TEST_DEFAULTS["LANE_A_ANNUAL_VOLUME_LOADS"],
            "service_days_required": TEST_DEFAULTS["LANE_A_SERVICE_DAYS_REQUIRED"],
            "accessorial_history_usd_per_load": TEST_DEFAULTS[
                "LANE_A_ACCESSORIAL_USD_PER_LOAD"
            ],
            "trailing_12m_actual_loads": TEST_DEFAULTS["LANE_A_TRAILING_12M_ACTUAL_LOADS"],
        },
        overrides,
    )


def reefer_lane_payload(**overrides) -> Dict[str, Any]:
    """Payload adding the 600-mile reefer lane with no incumbent (PRD §3.3)."""
    return _merge(
        {
            "lane_code": TEST_DEFAULTS["LANE_B_CODE"],
            "origin_zip3": "606",
            "dest_zip3": "802",
            "equipment_type": "REEFER",
            "mileage": TEST_DEFAULTS["LANE_B_MILEAGE"],
            "annual_volume_loads": TEST_DEFAULTS["LANE_B_ANNUAL_VOLUME_LOADS"],
            "service_days_required": TEST_DEFAULTS["LANE_B_SERVICE_DAYS_REQUIRED"],
            "accessorial_history_usd_per_load": TEST_DEFAULTS[
                "LANE_B_ACCESSORIAL_USD_PER_LOAD"
            ],
            "trailing_12m_actual_loads": TEST_DEFAULTS["LANE_B_TRAILING_12M_ACTUAL_LOADS"],
            "seasonality_peak_index": TEST_DEFAULTS["LANE_B_SEASONALITY_PEAK_INDEX"],
        },
        overrides,
    )


def invitation_payload(carrier_id: str, **overrides) -> Dict[str, Any]:
    """Payload inviting a carrier to an event (PRD §3.4)."""
    return _merge({"carrier_id": carrier_id, "nda_required": False}, overrides)


def invitation_response_payload(**overrides) -> Dict[str, Any]:
    """Payload accepting or declining an invitation (PRD §3.4)."""
    return _merge(
        {"accept": True, "nda_signed": _OMIT, "decline_reason": _OMIT}, overrides
    )


def invitation_revoke_payload(**overrides) -> Dict[str, Any]:
    """Payload revoking an invitation (PRD §3.4)."""
    return _merge({"revoked_reason": "Withdrawn from the event"}, overrides)


def bid_round_payload(**overrides) -> Dict[str, Any]:
    """Payload opening a negotiation round (PRD §3.4)."""
    return _merge(
        {
            "incumbent_visibility": "RANK_ONLY",
            "closes_at": ROUND_CLOSES_AT,
            "target_reduction_pct": _OMIT,
        },
        overrides,
    )


# ─── Bids, optimisation and award disposition ─────────────────────────────────

def lane_bid_payload(lane_id: str, carrier_id: str, **overrides) -> Dict[str, Any]:
    """Payload submitting one lane bid into an open round (PRD §3.4)."""
    return _merge(
        {
            "lane_id": lane_id,
            "carrier_id": carrier_id,
            "rate_per_mile": TEST_DEFAULTS["BID_A_RATE_PER_MILE"],
            "fuel_surcharge_included": True,
            "committed_volume_loads": TEST_DEFAULTS["BID_A_COMMITTED_VOLUME_LOADS"],
            "transit_days_offered": TEST_DEFAULTS["BID_A_TRANSIT_DAYS_OFFERED"],
        },
        overrides,
    )


def optimization_run_payload(
    bid_event_id: str, expected_bid_event_version: int, **overrides
) -> Dict[str, Any]:
    """Payload running an optimisation scenario (PRD §3.6)."""
    return _merge(
        {
            "bid_event_id": bid_event_id,
            "expected_bid_event_version": expected_bid_event_version,
            "scenario_label": "BASE",
            "max_carriers_per_lane": 1,
            "diversity_min_pct": 0.00,
            "min_capacity_coverage_pct": 0.00,
        },
        overrides,
    )


def allocation_rejection_payload(**overrides) -> Dict[str, Any]:
    """Payload rejecting a proposed or approved allocation (PRD §3.7)."""
    return _merge({"rejection_reason": "Capacity withdrawn by the carrier"}, overrides)


# ─── Contracts, rates and tendering ───────────────────────────────────────────

def rate_record_payload(
    lane_id: str, carrier_id: str, award_allocation_id: str, **overrides
) -> Dict[str, Any]:
    """Payload staging a rate record against a contract (PRD §3.8)."""
    return _merge(
        {
            "lane_id": lane_id,
            "carrier_id": carrier_id,
            "award_allocation_id": award_allocation_id,
            "routing_position": "PRIMARY",
            "rate_per_mile": TEST_DEFAULTS["RATE_A_PER_MILE"],
            "fuel_surcharge_included": True,
            "effective_from": CONTRACT_EFFECTIVE_FROM,
            "effective_to": CONTRACT_EFFECTIVE_TO,
            "committed_volume_loads": TEST_DEFAULTS["LANE_A_ANNUAL_VOLUME_LOADS"],
        },
        overrides,
    )


def tender_event_payload(load_reference: str, **overrides) -> Dict[str, Any]:
    """Payload appending one tender outcome to a live rate record (PRD §3.9)."""
    return _merge(
        {
            "outcome": "ACCEPTED",
            "load_reference": load_reference,
            "reject_reason": _OMIT,
        },
        overrides,
    )


# ─── Mini-bids ────────────────────────────────────────────────────────────────

def mini_bid_payload(
    bid_event_id: str, lane_id: str, rate_record_id: str, **overrides
) -> Dict[str, Any]:
    """Payload opening a mid-contract mini-bid window by hand (PRD §3.9)."""
    return _merge(
        {
            "bid_event_id": bid_event_id,
            "lane_id": lane_id,
            "rate_record_id": rate_record_id,
            "trigger_reason": "MARKET_INDEX",
            "window_open_at": "2026-09-02T00:00:00Z",
            "window_close_at": "2026-09-12T00:00:00Z",
        },
        overrides,
    )


def mini_bid_proposal_payload(carrier_id: str, **overrides) -> Dict[str, Any]:
    """Payload proposing a replacement per-mile rate (PRD §3.9)."""
    return _merge(
        {"carrier_id": carrier_id, "proposed_rate_per_mile": 2.1000}, overrides
    )


def mini_bid_apply_payload(expected_contract_version: int, **overrides) -> Dict[str, Any]:
    """Payload applying a proposed rate to the contract (PRD §3.9)."""
    return _merge(
        {
            "expected_contract_version": expected_contract_version,
            "effective_from": "2026-09-05T00:00:00Z",
            "effective_to": CONTRACT_EFFECTIVE_TO,
        },
        overrides,
    )


def mini_bid_denial_payload(**overrides) -> Dict[str, Any]:
    """Payload denying a requested or open mini-bid (PRD §3.9)."""
    return _merge({"denial_reason": "Market softened; no adjustment warranted"}, overrides)


def mini_bid_revert_payload(**overrides) -> Dict[str, Any]:
    """Payload reverting an applied mini-bid (PRD §3.9)."""
    return _merge({"revert_reason": "Adjustment applied against the wrong lane"}, overrides)
