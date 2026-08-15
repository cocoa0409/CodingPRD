"""Payload factories — one per entity, input fields only (PRD Section 4)."""
from .constants import DEFAULT_MEAL_RATES, DEFAULT_SITE


def create_site_payload(**overrides) -> dict:
    defaults = {
        "name": "Club S",
        "youth_capacity": DEFAULT_SITE["youth_capacity"],
        "standard_ratio": DEFAULT_SITE["standard_ratio"],
        "elevated_ratio": DEFAULT_SITE["elevated_ratio"],
        "base_weekly_fee_cents": DEFAULT_SITE["base_weekly_fee_cents"],
        "registration_fee_cents": DEFAULT_SITE["registration_fee_cents"],
        "max_arrears_cents": DEFAULT_SITE["max_arrears_cents"],
        "meal_rates_cents": {
            meal: dict(tiers) for meal, tiers in DEFAULT_MEAL_RATES.items()
        },
    }
    defaults.update(overrides)
    return defaults


def create_staff_payload(site_id: str, full_name: str = "Staff One",
                         position: str = "DIRECTOR", **overrides) -> dict:
    defaults = {"site_id": site_id, "full_name": full_name, "position": position}
    defaults.update(overrides)
    return defaults


def create_credential_payload(kind: str, expires_at: str) -> dict:
    return {"kind": kind, "expires_at": expires_at}


def create_member_payload(site_id: str, legal_name: str = "Kid A", **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "legal_name": legal_name,
        "date_of_birth": "2012-01-01",
        "grade": 7,
        "household_size": 1,
        "household_income_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_decide_payload(decision: str = "APPROVE") -> dict:
    return {"decision": decision}


def create_fee_payment_payload(amount_cents: int, expected_member_version: int) -> dict:
    return {"amount_cents": amount_cents, "expected_member_version": expected_member_version}


def create_guardian_payload(member_id: str, full_name: str = "Jane Doe",
                            relation: str = "mother", **overrides) -> dict:
    defaults = {"member_id": member_id, "full_name": full_name, "relation": relation}
    defaults.update(overrides)
    return defaults


def create_fund_payload(site_id: str, name: str = "Fund S",
                        budget_cents: int = 10_000, **overrides) -> dict:
    defaults = {"site_id": site_id, "name": name, "budget_cents": budget_cents}
    defaults.update(overrides)
    return defaults


def create_award_payload(fund_id: str, member_id: str, discount_pct: float = 0.50,
                         weekly_cap_cents: int = 500, annual_cap_cents: int = 1000,
                         **overrides) -> dict:
    defaults = {
        "fund_id": fund_id,
        "member_id": member_id,
        "discount_pct": discount_pct,
        "weekly_cap_cents": weekly_cap_cents,
        "annual_cap_cents": annual_cap_cents,
    }
    defaults.update(overrides)
    return defaults


def create_club_day_payload(site_id: str, date: str) -> dict:
    return {"site_id": site_id, "date": date}


def create_meal_counts_payload(meal_type: str = "BREAKFAST", free_count: int = 0,
                               reduced_count: int = 0, paid_count: int = 0) -> dict:
    return {
        "meal_type": meal_type,
        "free_count": free_count,
        "reduced_count": reduced_count,
        "paid_count": paid_count,
    }


def create_attendance_payload(club_day_id: str, member_id: str) -> dict:
    return {"club_day_id": club_day_id, "member_id": member_id}


def create_sign_out_payload(sign_out_type: str, pickup_name=None) -> dict:
    payload = {"sign_out_type": sign_out_type}
    if pickup_name is not None:
        payload["pickup_name"] = pickup_name
    return payload


def create_area_payload(site_id: str, name: str = "Gym", capacity: int = 30,
                        **overrides) -> dict:
    defaults = {"site_id": site_id, "name": name, "capacity": capacity}
    defaults.update(overrides)
    return defaults


def create_rotation_payload(club_day_id: str, area_id: str, block: str, kind: str,
                            member_id=None, staff_id=None) -> dict:
    payload = {"club_day_id": club_day_id, "area_id": area_id, "block": block, "kind": kind}
    if member_id is not None:
        payload["member_id"] = member_id
    if staff_id is not None:
        payload["staff_id"] = staff_id
    return payload


def create_route_payload(site_id: str, route_name: str = "Route 1",
                         school_name: str = "Lincoln", seat_capacity: int = 5,
                         **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "route_name": route_name,
        "school_name": school_name,
        "seat_capacity": seat_capacity,
    }
    defaults.update(overrides)
    return defaults


def create_ride_payload(route_id: str, member_id: str, effective_start_date: str,
                        effective_end_date=None) -> dict:
    payload = {
        "route_id": route_id,
        "member_id": member_id,
        "effective_start_date": effective_start_date,
    }
    if effective_end_date is not None:
        payload["effective_end_date"] = effective_end_date
    return payload


def create_end_ride_payload(end_date: str) -> dict:
    return {"end_date": end_date}


def create_claim_payload(site_id: str, claim_month: str) -> dict:
    return {"site_id": site_id, "claim_month": claim_month}


def create_incident_payload(member_id: str, incident_date: str, category: str,
                            description=None) -> dict:
    payload = {"member_id": member_id, "incident_date": incident_date, "category": category}
    if description is not None:
        payload["description"] = description
    return payload


def create_adjudicate_payload(outcome: str = "SUSTAINED", suspension_days=None,
                              suspension_start_date=None) -> dict:
    payload = {"outcome": outcome}
    if suspension_days is not None:
        payload["suspension_days"] = suspension_days
    if suspension_start_date is not None:
        payload["suspension_start_date"] = suspension_start_date
    return payload


def create_resolve_appeal_payload(decision: str) -> dict:
    return {"decision": decision}


def create_report_payload(site_id: str, report_month: str, funder_type: str) -> dict:
    return {"site_id": site_id, "report_month": report_month, "funder_type": funder_type}
