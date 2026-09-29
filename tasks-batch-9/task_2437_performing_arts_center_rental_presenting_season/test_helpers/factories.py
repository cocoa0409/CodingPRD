"""Payload factories — one per write endpoint, input fields only.

Every factory returns a plain dict of the fields the PRD declares as client
input, with sensible defaults that ``**overrides`` can replace. Passing
``field=None`` keeps the key with a null value; use ``pop`` on the returned
dict to omit a field entirely.
"""

from typing import Optional

from .constants import TEST_DEFAULTS


# ─── Season infrastructure ────────────────────────────

def create_performance_space_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["SPACE_NAME"],
        "seat_capacity": TEST_DEFAULTS["SEAT_CAPACITY"],
        "base_facility_fee_cents": TEST_DEFAULTS["BASE_FACILITY_FEE_CENTS"],
        "load_in_day_fee_cents": TEST_DEFAULTS["LOAD_IN_DAY_FEE_CENTS"],
        "changeover_buffer_minutes": TEST_DEFAULTS["CHANGEOVER_BUFFER_MINUTES"],
        "rigging_capacity_kg": TEST_DEFAULTS["RIGGING_CAPACITY_KG"],
        "house_power_amps": TEST_DEFAULTS["HOUSE_POWER_AMPS"],
        "dmx_universes": TEST_DEFAULTS["DMX_UNIVERSES"],
    }
    payload.update(overrides)
    return payload


def create_artist_payload(**overrides) -> dict:
    payload = {
        "legal_name": TEST_DEFAULTS["ARTIST_LEGAL_NAME"],
        "agency_name": TEST_DEFAULTS["AGENCY_NAME"],
        "guarantee_floor_cents": TEST_DEFAULTS["GUARANTEE_FLOOR_CENTS"],
        "historical_sell_through_pct": TEST_DEFAULTS["HISTORICAL_SELL_THROUGH_PCT"],
        "routing_window_start_utc": TEST_DEFAULTS["ROUTING_WINDOW_START_UTC"],
        "routing_window_end_utc": TEST_DEFAULTS["ROUTING_WINDOW_END_UTC"],
        "min_days_between_engagements": TEST_DEFAULTS["MIN_DAYS_BETWEEN_ENGAGEMENTS"],
    }
    payload.update(overrides)
    return payload


def create_rental_client_payload(**overrides) -> dict:
    payload = {
        "org_name": TEST_DEFAULTS["CLIENT_ORG_NAME"],
        "contact_email": TEST_DEFAULTS["CLIENT_CONTACT_EMAIL"],
        "credit_rating": "A",
        "is_nonprofit": False,
    }
    payload.update(overrides)
    return payload


def create_union_department_payload(**overrides) -> dict:
    payload = {
        "department": "STAGEHANDS",
        "roster_size": TEST_DEFAULTS["ROSTER_SIZE"],
        "straight_hourly_rate_cents": TEST_DEFAULTS["STRAIGHT_HOURLY_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_equipment_item_payload(**overrides) -> dict:
    payload = {
        "category": "POWER_DISTRO",
        "model_name": "400A Company Switch Distro",
        "on_hand_qty": 5,
        "daily_rate_cents": 25_000,
        "replacement_value_cents": 800_000,
    }
    payload.update(overrides)
    return payload


# ─── Booking ──────────────────────────────────────────

def create_presented_engagement_payload(space_id: str, artist_id: str,
                                        **overrides) -> dict:
    payload = {
        "engagement_type": "PRESENTED",
        "space_id": space_id,
        "artist_id": artist_id,
        "title": "Cadence Quartet in Recital",
        "load_in_start_utc": "2026-10-10T08:00:00Z",
        "performance_start_utc": "2026-10-11T19:00:00Z",
        "performance_end_utc": "2026-10-11T22:00:00Z",
        "load_out_end_utc": "2026-10-12T02:00:00Z",
        "performance_day_count": 1,
        "load_in_day_count": 1,
    }
    payload.update(overrides)
    return payload


def create_rental_engagement_payload(space_id: str, rental_client_id: str,
                                     **overrides) -> dict:
    payload = {
        "engagement_type": "RENTAL",
        "space_id": space_id,
        "rental_client_id": rental_client_id,
        "title": "Meridian Dance Spring Gala",
        "load_in_start_utc": "2026-10-01T08:00:00Z",
        "performance_start_utc": "2026-10-02T19:00:00Z",
        "performance_end_utc": "2026-10-02T22:00:00Z",
        "load_out_end_utc": "2026-10-03T02:00:00Z",
        "performance_day_count": 1,
        "load_in_day_count": 1,
    }
    payload.update(overrides)
    return payload


def assess_risk_payload(expected_engagement_version: int, **overrides) -> dict:
    payload = {"expected_engagement_version": expected_engagement_version}
    payload.update(overrides)
    return payload


def record_deposit_payload(amount_cents: int, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def cancel_engagement_payload(**overrides) -> dict:
    payload = {"reason": "Season restructuring"}
    payload.update(overrides)
    return payload


# ─── Fee negotiation ──────────────────────────────────

def open_fee_negotiation_payload(offered_fee_cents: int,
                                 offered_artist_share_pct: float,
                                 expected_engagement_version: int,
                                 **overrides) -> dict:
    payload = {
        "offered_fee_cents": offered_fee_cents,
        "offered_artist_share_pct": offered_artist_share_pct,
        "expected_engagement_version": expected_engagement_version,
    }
    payload.update(overrides)
    return payload


def counter_fee_negotiation_payload(counter_fee_cents: int,
                                    counter_artist_share_pct: float,
                                    **overrides) -> dict:
    payload = {
        "counter_fee_cents": counter_fee_cents,
        "counter_artist_share_pct": counter_artist_share_pct,
    }
    payload.update(overrides)
    return payload


def revise_fee_offer_payload(offered_fee_cents: int,
                             offered_artist_share_pct: float,
                             **overrides) -> dict:
    payload = {
        "offered_fee_cents": offered_fee_cents,
        "offered_artist_share_pct": offered_artist_share_pct,
    }
    payload.update(overrides)
    return payload


# ─── Technical rider and equipment ────────────────────

def submit_tech_rider_payload(**overrides) -> dict:
    payload = {
        "submitted_rigging_kg": 1_000,
        "requested_power_amps": 200,
        "requested_dmx_universes": 2,
        "requires_orchestra_pit": False,
    }
    payload.update(overrides)
    return payload


def create_equipment_line_payload(equipment_item_id: str, **overrides) -> dict:
    payload = {
        "equipment_item_id": equipment_item_id,
        "covers_gap": "POWER_SHORTFALL",
        "qty": 1,
        "rental_days": 1,
    }
    payload.update(overrides)
    return payload


# ─── Union labor ──────────────────────────────────────

def create_labor_call_payload(union_department_id: str, **overrides) -> dict:
    payload = {
        "union_department_id": union_department_id,
        "crew_size": 4,
        "call_start_utc": "2026-10-01T08:00:00Z",
        "call_end_utc": "2026-10-01T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def report_labor_hours_payload(actual_hours: float, meal_break_taken: bool,
                               **overrides) -> dict:
    payload = {"actual_hours": actual_hours, "meal_break_taken": meal_break_taken}
    payload.update(overrides)
    return payload


# ─── Ticketing ────────────────────────────────────────

def create_price_tier_payload(**overrides) -> dict:
    payload = {
        "tier_name": "ORCH",
        "seats_allocated": 100,
        "base_price_cents": 10_000,
        "price_ceiling_cents": 15_000,
        "dynamic_pricing_enabled": False,
        "subscription_eligible": False,
    }
    payload.update(overrides)
    return payload


def create_ticket_sale_payload(qty: int = 1, channel: str = "WEB", **overrides) -> dict:
    payload = {"qty": qty, "channel": channel}
    payload.update(overrides)
    return payload


def create_subscription_package_payload(included_engagement_ids: list,
                                        **overrides) -> dict:
    payload = {
        "name": "Season Choose-2",
        "package_price_cents": 100_000,
        "included_engagement_ids": list(included_engagement_ids),
        "subscription_tier_name": "ORCH",
        "seats_per_order": 2,
    }
    payload.update(overrides)
    return payload


def sell_subscription_orders_payload(order_qty: int = 1, **overrides) -> dict:
    payload = {"order_qty": order_qty}
    payload.update(overrides)
    return payload


# ─── Settlement ───────────────────────────────────────

def reconcile_expenses_payload(actual_marketing_cents: int = 0, **overrides) -> dict:
    payload = {"actual_marketing_cents": actual_marketing_cents}
    payload.update(overrides)
    return payload


# ─── Education programs ───────────────────────────────

def create_education_program_payload(**overrides) -> dict:
    payload = {
        "program_type": "STUDENT_MATINEE",
        "participant_capacity": 100,
        "subsidy_requested_cents": 300_000,
    }
    payload.update(overrides)
    return payload


# ─── Capital reserve ledger ───────────────────────────

def create_reserve_ledger_entry_payload(entry_type: str, amount_cents: int,
                                        memo: str = "Season reserve movement",
                                        engagement_id: Optional[str] = None,
                                        **overrides) -> dict:
    payload = {
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "memo": memo,
    }
    if engagement_id is not None:
        payload["engagement_id"] = engagement_id
    payload.update(overrides)
    return payload


__all__ = [
    "create_performance_space_payload",
    "create_artist_payload",
    "create_rental_client_payload",
    "create_union_department_payload",
    "create_equipment_item_payload",
    "create_presented_engagement_payload",
    "create_rental_engagement_payload",
    "assess_risk_payload",
    "record_deposit_payload",
    "cancel_engagement_payload",
    "open_fee_negotiation_payload",
    "counter_fee_negotiation_payload",
    "revise_fee_offer_payload",
    "submit_tech_rider_payload",
    "create_equipment_line_payload",
    "create_labor_call_payload",
    "report_labor_hours_payload",
    "create_price_tier_payload",
    "create_ticket_sale_payload",
    "create_subscription_package_payload",
    "sell_subscription_orders_payload",
    "reconcile_expenses_payload",
    "create_education_program_payload",
    "create_reserve_ledger_entry_payload",
]
