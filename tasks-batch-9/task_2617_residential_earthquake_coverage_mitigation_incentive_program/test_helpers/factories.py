"""Request-payload builders.

Each builder returns a payload carrying only the fields its endpoint accepts,
filled with values that satisfy every documented validation, so a test can
override just the one field it is exercising.
"""
import itertools
from typing import Any, Dict, List, Optional

from .constants import CLOCK_EPOCH

_counter = itertools.count(1)


def _next() -> int:
    """A per-process counter for values the API requires to be distinct."""
    return next(_counter)


# ─── Clock ────────────────────────────────────────────────────────────────────
def set_clock_payload(current_utc: str = CLOCK_EPOCH) -> Dict[str, Any]:
    """Payload pinning the logical clock."""
    return {"current_utc": current_utc}


# ─── Participating insurers ───────────────────────────────────────────────────
def create_insurer_payload(**overrides: Any) -> Dict[str, Any]:
    """A participating insurer with a mid-sized market share."""
    n = _next()
    payload: Dict[str, Any] = {
        "name": f"Pacific Mutual {n}",
        "naic_code": f"{10000 + n}",
        "market_share_pct": 25.0,
    }
    payload.update(overrides)
    return payload


def compliance_action_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    """Payload driving an insurer compliance transition."""
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


def take_up_evaluation_payload(
    window_start: str,
    window_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Payload bounding a take-up rate evaluation window."""
    payload: Dict[str, Any] = {
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


# ─── Policyholders ────────────────────────────────────────────────────────────
def create_policyholder_payload(**overrides: Any) -> Dict[str, Any]:
    """A policyholder in a coastal county."""
    n = _next()
    payload: Dict[str, Any] = {
        "full_name": f"Dana Ortiz {n}",
        "email": f"dana.ortiz.{n}@example.com",
        "county_code": "06081",
        "outreach_campaign_code": "OUTREACH-2026",
    }
    payload.update(overrides)
    return payload


# ─── Dwellings ────────────────────────────────────────────────────────────────
def create_dwelling_payload(policyholder_id: str, **overrides: Any) -> Dict[str, Any]:
    """A tier-two, stiff-soil, slab wood-frame dwelling built after the code year."""
    n = _next()
    payload: Dict[str, Any] = {
        "policyholder_id": policyholder_id,
        "street_address": f"{100 + n} Alameda Street",
        "county_hazard_tier": "TIER_2",
        "soil_class": "STIFF",
        "structure_type": "WOOD_FRAME_SLAB",
        "year_built": 1995,
        "dwelling_limit_cents": 20000000,
    }
    payload.update(overrides)
    return payload


def declare_retrofit_payload(declared_scope: str) -> Dict[str, Any]:
    """Payload declaring an as-yet unverified retrofit scope."""
    return {"declared_scope": declared_scope}


# ─── Mandatory offers ─────────────────────────────────────────────────────────
def create_mandatory_offer_payload(
    insurer_id: str,
    policyholder_id: str,
    dwelling_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """A mandatory earthquake coverage offer."""
    payload: Dict[str, Any] = {
        "insurer_id": insurer_id,
        "policyholder_id": policyholder_id,
        "dwelling_id": dwelling_id,
        "campaign_code": "OUTREACH-2026",
    }
    payload.update(overrides)
    return payload


def respond_to_offer_payload(response: str, **overrides: Any) -> Dict[str, Any]:
    """Payload carrying an acceptance or a decline."""
    payload: Dict[str, Any] = {"response": response}
    payload.update(overrides)
    return payload


# ─── Policies ─────────────────────────────────────────────────────────────────
def create_policy_payload(
    dwelling_id: str,
    insurer_id: str,
    accepted_offer_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """A quote at the neutral ten per cent deductible."""
    payload: Dict[str, Any] = {
        "dwelling_id": dwelling_id,
        "insurer_id": insurer_id,
        "accepted_offer_id": accepted_offer_id,
        "deductible_pct": 10,
        "contents_sublimit_cents": 3000000,
        "loss_of_use_sublimit_cents": 1500000,
    }
    payload.update(overrides)
    return payload


def lifecycle_action_payload(action: str) -> Dict[str, Any]:
    """Payload driving a policy lifecycle transition."""
    return {"action": action}


# ─── Grant cycles ─────────────────────────────────────────────────────────────
def create_grant_cycle_payload(**overrides: Any) -> Dict[str, Any]:
    """A funding cycle open across the whole of the test calendar."""
    payload: Dict[str, Any] = {
        "program_track": "BRACE_AND_BOLT",
        "label": f"Cycle {_next()}",
        "opens_at": "2026-07-01T00:00:00Z",
        "closes_at": "2026-12-31T00:00:00Z",
        "total_pool_cents": 100000000,
    }
    payload.update(overrides)
    return payload


# ─── Retrofit grants ──────────────────────────────────────────────────────────
def create_retrofit_grant_payload(
    dwelling_id: str,
    grant_cycle_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """A cripple-wall bracing application from the lowest income tier."""
    payload: Dict[str, Any] = {
        "dwelling_id": dwelling_id,
        "grant_cycle_id": grant_cycle_id,
        "income_tier": "TIER_LOW",
        "project_cost_estimate_cents": 900000,
        "requested_scope": "CRIPPLE_WALL_BRACING",
    }
    payload.update(overrides)
    return payload


def review_grant_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    """Payload carrying a review decision."""
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def reserve_funds_payload(expected_grant_cycle_version: int) -> Dict[str, Any]:
    """Payload carrying the cycle version the caller believes is current."""
    return {"expected_grant_cycle_version": expected_grant_cycle_version}


# ─── Contractors ──────────────────────────────────────────────────────────────
def create_contractor_payload(
    certified_scopes: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A contractor certified for cripple-wall bracing well into the future."""
    n = _next()
    payload: Dict[str, Any] = {
        "business_name": f"Bayline Seismic {n}",
        "license_no": f"CSLB-{700000 + n}",
        "certified_scopes": (
            list(certified_scopes)
            if certified_scopes is not None
            else ["CRIPPLE_WALL_BRACING"]
        ),
        "certification_expires_at": "2027-12-31T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def certification_payload(certification_status: str, **overrides: Any) -> Dict[str, Any]:
    """Payload changing a contractor's certification standing."""
    payload: Dict[str, Any] = {"certification_status": certification_status}
    payload.update(overrides)
    return payload


# ─── Retrofit projects ────────────────────────────────────────────────────────
def create_retrofit_project_payload(
    grant_id: str,
    contractor_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """A project pairing a funded grant with a certified contractor."""
    payload: Dict[str, Any] = {"grant_id": grant_id, "contractor_id": contractor_id}
    payload.update(overrides)
    return payload


# ─── Inspections ──────────────────────────────────────────────────────────────
def create_inspection_payload(
    project_id: str,
    window_start: str = "2026-08-04T09:00:00Z",
    window_end: str = "2026-08-04T10:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """A one-hour inspection window comfortably inside the permitted duration."""
    payload: Dict[str, Any] = {
        "project_id": project_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def record_result_payload(result: str, **overrides: Any) -> Dict[str, Any]:
    """Payload carrying an inspection outcome."""
    payload: Dict[str, Any] = {"result": result}
    payload.update(overrides)
    return payload


# ─── Catastrophe events ───────────────────────────────────────────────────────
def create_catastrophe_event_payload(**overrides: Any) -> Dict[str, Any]:
    """A declarable magnitude 6.4 event with a one-million-dollar retention."""
    payload: Dict[str, Any] = {
        "event_code": f"EQ-2026-{_next():03d}",
        "magnitude": 6.4,
        "epicenter_county_code": "06081",
        "occurred_at": "2026-09-05T00:00:00Z",
        "retention_cents": 100000000,
    }
    payload.update(overrides)
    return payload


# ─── Reinsurance layers ───────────────────────────────────────────────────────
def create_reinsurance_layer_payload(**overrides: Any) -> Dict[str, Any]:
    """A first layer attaching at the usual retention."""
    payload: Dict[str, Any] = {
        "treaty_year": 2026,
        "layer_index": 1,
        "attachment_point_cents": 100000000,
        "limit_cents": 400000000,
        "ceded_pct": 1.0,
    }
    payload.update(overrides)
    return payload


def layer_status_payload(status: str) -> Dict[str, Any]:
    """Payload changing a reinsurance layer's status."""
    return {"status": status}


# ─── Claims ───────────────────────────────────────────────────────────────────
def create_claim_payload(
    policy_id: str,
    event_id: str,
    expected_event_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """A first notice of loss with structural damage only."""
    payload: Dict[str, Any] = {
        "policy_id": policy_id,
        "event_id": event_id,
        "structural_damage_cents": 5000000,
        "cosmetic_damage_cents": 0,
        "contents_damage_cents": 0,
        "loss_of_use_cents": 0,
        "expected_event_version": expected_event_version,
    }
    payload.update(overrides)
    return payload


def record_payment_payload(amount_cents: int) -> Dict[str, Any]:
    """Payload recording a payment against a settled claim."""
    return {"amount_cents": amount_cents}


def deny_claim_payload(denial_reason: str = "Loss outside policy period") -> Dict[str, Any]:
    """Payload denying a claim."""
    return {"denial_reason": denial_reason}


def reason_payload(reason: str = "Requested by the program administrator") -> Dict[str, Any]:
    """A bare reason payload, accepted by the several endpoints that take one."""
    return {"reason": reason}
