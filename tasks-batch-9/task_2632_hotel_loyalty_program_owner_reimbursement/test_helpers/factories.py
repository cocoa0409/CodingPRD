"""Payload factories - one per creatable resource, input fields only."""

import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def unique_suffix() -> int:
    """Monotonic counter so repeated creates inside one test stay distinct."""
    return next(_counter)


def unique_email(prefix: str = "member") -> str:
    return f"{prefix}{unique_suffix()}@example.com"


def create_hotel_payload(**overrides) -> dict:
    payload = {
        "name": "Harborline Central",
        "brand_code": "HRB",
        "market_tier": "URBAN",
        "program_fee_pct": TEST_DEFAULTS["PROGRAM_FEE_PCT"],
        "rooms_count": TEST_DEFAULTS["ROOMS_COUNT"],
        "trailing_12m_occupancy_pct": TEST_DEFAULTS["OCCUPANCY_PCT"],
        "trailing_12m_adr_cents": TEST_DEFAULTS["ADR_CENTS"],
    }
    payload.update(overrides)
    return payload


def performance_refresh_payload(**overrides) -> dict:
    payload = {
        "trailing_12m_occupancy_pct": 0.96,
        "trailing_12m_adr_cents": 30_000,
    }
    payload.update(overrides)
    return payload


def terminate_hotel_payload(**overrides) -> dict:
    payload = {"termination_reason": "Franchise agreement not renewed"}
    payload.update(overrides)
    return payload


def create_rate_plan_payload(**overrides) -> dict:
    payload = {"rate_code": "BAR", "rate_category": "TRANSIENT"}
    payload.update(overrides)
    return payload


def create_redemption_pricing_payload(**overrides) -> dict:
    payload = {
        "season": "STANDARD",
        "window_start_date": "2026-01-01",
        "window_end_date": "2026-12-31",
        "points_per_night": TEST_DEFAULTS["POINTS_PER_NIGHT"],
        "cash_copay_cents": 0,
        "min_tier_required": "BASE",
        "award_allotment_per_night": TEST_DEFAULTS["AWARD_ALLOTMENT_PER_NIGHT"],
    }
    payload.update(overrides)
    return payload


def create_blackout_window_payload(**overrides) -> dict:
    payload = {
        "start_date": "2026-11-01",
        "end_date": "2026-11-05",
        "scope": "ALL_REDEMPTIONS",
    }
    payload.update(overrides)
    return payload


def revoke_blackout_window_payload(**overrides) -> dict:
    payload = {"revoke_reason": "Demand forecast revised downward"}
    payload.update(overrides)
    return payload


def create_member_payload(**overrides) -> dict:
    payload = {
        "email": unique_email(),
        "full_name": "Dana Vance",
        "enrollment_date": "2026-01-05",
    }
    payload.update(overrides)
    return payload


def point_adjustment_payload(member_id: str, points: int, expected_member_version: int, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "points": points,
        "adjustment_reason": "Goodwill for a long check-in queue.",
        "expected_member_version": expected_member_version,
    }
    payload.update(overrides)
    return payload


def create_stay_payload(member_id: str, hotel_id: str, rate_plan_id: str, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "hotel_id": hotel_id,
        "rate_plan_id": rate_plan_id,
        "checkin_date": "2026-07-01",
        "checkout_date": "2026-07-03",
        "room_revenue_cents": 12_345,
    }
    payload.update(overrides)
    return payload


def dispute_stay_payload(**overrides) -> dict:
    payload = {"dispute_reason": "Guest challenged the room rate."}
    payload.update(overrides)
    return payload


def void_stay_payload(**overrides) -> dict:
    payload = {"void_reason": "Duplicate folio."}
    payload.update(overrides)
    return payload


def deny_benefit_payload(**overrides) -> dict:
    payload = {"denial_reason": "No suite inventory on the arrival date"}
    payload.update(overrides)
    return payload


def create_redemption_payload(member_id: str, hotel_id: str, expected_hotel_version: int, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "hotel_id": hotel_id,
        "checkin_date": "2026-09-10",
        "checkout_date": "2026-09-12",
        "expected_hotel_version": expected_hotel_version,
    }
    payload.update(overrides)
    return payload


def cancel_redemption_payload(**overrides) -> dict:
    payload = {"cancel_reason": "Trip cancelled by the guest"}
    payload.update(overrides)
    return payload


def create_reimbursement_batch_payload(hotel_id: str, period_month: str = "2026-09", **overrides) -> dict:
    payload = {"hotel_id": hotel_id, "period_month": period_month}
    payload.update(overrides)
    return payload


def reject_batch_payload(**overrides) -> dict:
    payload = {"rejection_reason": "Occupancy attestation missing for the period"}
    payload.update(overrides)
    return payload


def create_partner_payload(**overrides) -> dict:
    payload = {
        "name": "Meridian SkyAlliance",
        "partner_type": "AIRLINE",
        "points_cost_per_1000_cents": 5_000,
        "monthly_cap_points": 500_000,
    }
    payload.update(overrides)
    return payload


def create_point_purchase_payload(member_id: str, points_quantity: int = 20_000, channel: str = "DIRECT_PURCHASE", **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "channel": channel,
        "points_quantity": points_quantity,
    }
    payload.update(overrides)
    return payload


def refund_point_purchase_payload(**overrides) -> dict:
    payload = {"refund_reason": "Partner reported an unauthorized bulk order"}
    payload.update(overrides)
    return payload


def breakage_rate_payload(breakage_rate_pct: float = 0.35, **overrides) -> dict:
    payload = {"breakage_rate_pct": breakage_rate_pct}
    payload.update(overrides)
    return payload


def create_complaint_payload(member_id: str, subject_type: str = "POINT_SHORTFALL", **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "subject_type": subject_type,
        "description": "My March stay never credited.",
    }
    payload.update(overrides)
    return payload


def resolve_complaint_payload(resolution: str = "Reviewed and closed.", **overrides) -> dict:
    payload = {"resolution": resolution}
    payload.update(overrides)
    return payload


def provide_complaint_info_payload(**overrides) -> dict:
    payload = {"description": "Here is the folio number."}
    payload.update(overrides)
    return payload


def adjudicate_complaint_payload(adjudication_outcome: str = "DELIVERY_ORDERED", **overrides) -> dict:
    payload = {"adjudication_outcome": adjudication_outcome}
    payload.update(overrides)
    return payload
