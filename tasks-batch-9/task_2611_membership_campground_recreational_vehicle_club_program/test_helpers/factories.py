"""Payload factories: valid-by-default request bodies with keyword overrides."""

import itertools
from typing import Any, Dict

_counter = itertools.count(1)


def unique_suffix() -> int:
    """Monotonic counter for fields the contract requires to be unique."""
    return next(_counter)


# ---------------------------------------------------------------------------
# Tiers
# ---------------------------------------------------------------------------


def make_membership_tier_payload(**overrides: Any) -> Dict[str, Any]:
    """A mid-market tier: uppercase code, rank 1, modest entitlements."""
    n = unique_suffix()
    payload: Dict[str, Any] = {
        "code": f"TIER{n:04d}",
        "name": f"Test Tier {n}",
        "tier_rank": 1,
        "upfront_cost_cents": 795000,
        "annual_dues_cents": 42000,
        "entitlement_nights_class_a": 0,
        "entitlement_nights_class_b": 10,
        "entitlement_nights_class_c": 18,
        "annual_total_night_cap": 24,
        "advance_window_days": 60,
        "max_consecutive_stay_nights": 14,
        "min_out_nights_between_stays": 3,
        "affiliate_access_enabled": False,
        "resale_allowed": False,
        "transfer_fee_cents": 60000,
    }
    payload.update(overrides)
    return payload


def make_classic_tier_payload(**overrides: Any) -> Dict[str, Any]:
    """CLASSIC: rank 1, 42,000 cents dues, no affiliate access, no resale."""
    payload = make_membership_tier_payload(
        code=f"CLASSIC{unique_suffix():03d}",
        name="Classic Membership",
    )
    payload.update(overrides)
    return payload


def make_president_tier_payload(**overrides: Any) -> Dict[str, Any]:
    """PRESIDENT: rank 3, 58,000 cents dues, affiliate access and resale on."""
    payload = make_membership_tier_payload(
        code=f"PRESIDENT{unique_suffix():03d}",
        name="President Membership",
        tier_rank=3,
        upfront_cost_cents=1850000,
        annual_dues_cents=58000,
        entitlement_nights_class_a=14,
        entitlement_nights_class_b=21,
        entitlement_nights_class_c=28,
        annual_total_night_cap=45,
        advance_window_days=120,
        max_consecutive_stay_nights=21,
        min_out_nights_between_stays=1,
        affiliate_access_enabled=True,
        resale_allowed=True,
        transfer_fee_cents=95000,
    )
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Members and memberships
# ---------------------------------------------------------------------------


def make_member_payload(**overrides: Any) -> Dict[str, Any]:
    """A natural person; email must be unique across all member records."""
    n = unique_suffix()
    payload: Dict[str, Any] = {
        "full_name": f"Test Member {n}",
        "email": f"member{n:05d}@example.test",
        "home_region": "Pacific Northwest",
    }
    payload.update(overrides)
    return payload


def make_membership_payload(member_id: str, tier_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "member_id": member_id,
        "tier_id": tier_id,
        "upfront_paid_cents": 795000,
    }
    payload.update(overrides)
    return payload


def make_suspension_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"suspension_reason": "ADMIN_ACTION"}
    payload.update(overrides)
    return payload


def make_reinstatement_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reinstatement_fee_paid_cents": 15000}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Dues
# ---------------------------------------------------------------------------


def make_payment_payload(amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def make_payment_reversal_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": "Chargeback filed by the card issuer"}
    payload.update(overrides)
    return payload


def make_annual_dues_run_payload(cycle_year: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"cycle_year": cycle_year}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Parks and partner agreements
# ---------------------------------------------------------------------------


def make_park_payload(**overrides: Any) -> Dict[str, Any]:
    """A club-owned park whose season spans nearly the whole year."""
    n = unique_suffix()
    payload: Dict[str, Any] = {
        "name": f"Test Park {n}",
        "park_class": "CLASS_C",
        "total_sites": 20,
        "member_allocation_pct": 60,
        "season_open_date": "2026-01-05",
        "season_close_date": "2026-12-20",
    }
    payload.update(overrides)
    return payload


def make_affiliate_agreement_payload(**overrides: Any) -> Dict[str, Any]:
    """A partner agreement; partner_name must be unique across all agreements."""
    n = unique_suffix()
    payload: Dict[str, Any] = {
        "partner_name": f"Partner Network {n}",
        "effective_from": "2026-01-01",
        "effective_to": "2026-12-31",
        "annual_member_night_quota": 40,
        "reciprocity_ratio": 1.5,
        "min_tier_rank": 2,
        "advance_window_cap_days": 45,
        "per_stay_night_cap": 7,
        "settlement_rate_cents_per_night": 1500,
    }
    payload.update(overrides)
    return payload


def make_agreement_status_change_payload(new_status: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"new_status": new_status}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------


def make_reservation_payload(
    park_id: str,
    membership_id: str,
    arrival_date: str,
    scheduled_departure_date: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "park_id": park_id,
        "membership_id": membership_id,
        "arrival_date": arrival_date,
        "scheduled_departure_date": scheduled_departure_date,
    }
    payload.update(overrides)
    return payload


def make_transient_reservation_payload(
    park_id: str,
    arrival_date: str,
    scheduled_departure_date: str,
    guest_name: str = "Walk-in Guest",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "park_id": park_id,
        "guest_name": guest_name,
        "arrival_date": arrival_date,
        "scheduled_departure_date": scheduled_departure_date,
    }
    payload.update(overrides)
    return payload


def make_check_out_payload(actual_departure_date: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"actual_departure_date": actual_departure_date}
    payload.update(overrides)
    return payload


def make_extension_payload(new_departure_date: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"new_departure_date": new_departure_date}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------


def make_maintenance_window_payload(
    park_id: str, start_date: str, end_date: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "park_id": park_id,
        "start_date": start_date,
        "end_date": end_date,
        "work_type": "ROUTINE",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Surveys, inspections and capital work
# ---------------------------------------------------------------------------


def make_satisfaction_survey_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "overall_rating": 5,
        "cleanliness_rating": 5,
        "staff_rating": 5,
        "value_rating": 5,
    }
    payload.update(overrides)
    return payload


def make_amenity_inspection_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "restroom_score": 4,
        "hookup_score": 4,
        "utility_score": 4,
        "road_score": 4,
    }
    payload.update(overrides)
    return payload


def make_capital_project_payload(park_id: str, **overrides: Any) -> Dict[str, Any]:
    n = unique_suffix()
    payload: Dict[str, Any] = {
        "park_id": park_id,
        "title": f"Capital Project {n}",
        "category": "UTILITY",
        "requested_cost_cents": 4500000,
        "fiscal_year": 2026,
    }
    payload.update(overrides)
    return payload


def make_capital_decision_payload(
    decision: str, expected_park_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": decision,
        "expected_park_version": expected_park_version,
    }
    payload.update(overrides)
    return payload


def make_reinvestment_run_payload(
    fiscal_year: int, budget_cents: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"fiscal_year": fiscal_year, "budget_cents": budget_cents}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Occupancy exceptions and transfers
# ---------------------------------------------------------------------------


def make_exception_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def make_transfer_request_payload(
    membership_id: str,
    to_member_id: str,
    transfer_type: str,
    expected_membership_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "membership_id": membership_id,
        "to_member_id": to_member_id,
        "transfer_type": transfer_type,
        "expected_membership_version": expected_membership_version,
    }
    payload.update(overrides)
    return payload


def make_transfer_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload
