"""Payload factories — one per creation endpoint, client-supplied fields only."""
from typing import List, Optional

from .constants import MID_AUGUST, MONTH_WINDOWS, TEST_DEFAULTS


def banner_payload(**overrides) -> dict:
    """A banner registered with only the two mandatory fields; every knob
    omitted here must come back at its declared default."""
    payload = {"banner_code": "MAIN", "name": "Main Grocery Banner"}
    payload.update(overrides)
    return payload


def site_payload(banner_id: str, **overrides) -> dict:
    payload = {
        "banner_id": banner_id,
        "site_number": "G-001",
        "site_type": "GROCERY",
    }
    payload.update(overrides)
    return payload


def grocery_site_payload(banner_id: str, site_number: str = "G-001", **overrides) -> dict:
    return site_payload(
        banner_id, site_number=site_number, site_type="GROCERY", **overrides
    )


def owned_fuel_center_payload(banner_id: str, site_number: str = "F-001", **overrides) -> dict:
    return site_payload(
        banner_id, site_number=site_number, site_type="OWNED_FUEL_CENTER", **overrides
    )


def partner_station_payload(
    banner_id: str,
    site_number: str = "P-001",
    partner_code: str = "PTR001",
    per_gallon_cap_cents: int = TEST_DEFAULTS["PARTNER_PER_GALLON_CAP_CENTS"],
    max_gallons_per_redemption: int = TEST_DEFAULTS["PARTNER_MAX_GALLONS_PER_REDEMPTION"],
    **overrides,
) -> dict:
    payload = {
        "banner_id": banner_id,
        "site_number": site_number,
        "site_type": "PARTNER_STATION",
        "partner_code": partner_code,
        "per_gallon_cap_cents": per_gallon_cap_cents,
        "max_gallons_per_redemption": max_gallons_per_redemption,
    }
    payload.update(overrides)
    return payload


def household_payload(banner_id: str, household_code: str = "HH-0001", **overrides) -> dict:
    payload = {"banner_id": banner_id, "household_code": household_code}
    payload.update(overrides)
    return payload


def member_payload(
    banner_id: str,
    alt_id: str = "5550000001",
    card_number: str = "4000000000000001",
    full_name: str = "Test Member",
    **overrides,
) -> dict:
    payload = {
        "banner_id": banner_id,
        "alt_id": alt_id,
        "card_number": card_number,
        "full_name": full_name,
    }
    payload.update(overrides)
    return payload


def household_link_payload(
    household_id: str, member_id: str, link_role: str = "PRIMARY", **overrides
) -> dict:
    payload = {
        "household_id": household_id,
        "member_id": member_id,
        "link_role": link_role,
    }
    payload.update(overrides)
    return payload


def promo_event_payload(
    banner_id: str,
    promo_code: str = "P_DOUBLE",
    multiplier: int = 2,
    applies_to_categories: Optional[List[str]] = None,
    starts_at: str = "2026-08-01T00:00:00Z",
    ends_at: str = "2026-09-01T00:00:00Z",
    stack_priority: int = 10,
    **overrides,
) -> dict:
    payload = {
        "banner_id": banner_id,
        "promo_code": promo_code,
        "multiplier": multiplier,
        "applies_to_categories": applies_to_categories or ["GROCERY"],
        "starts_at": starts_at,
        "ends_at": ends_at,
        "stack_priority": stack_priority,
    }
    payload.update(overrides)
    return payload


def point_cycle_payload(banner_id: str, cycle_month: str = "2026-08", **overrides) -> dict:
    opens_at, closes_at = MONTH_WINDOWS[cycle_month]
    payload = {
        "banner_id": banner_id,
        "cycle_month": cycle_month,
        "opens_at": opens_at,
        "closes_at": closes_at,
    }
    payload.update(overrides)
    return payload


def purchase_line(category: str = "GROCERY", amount_cents: int = 30000, quantity: int = 1) -> dict:
    return {"category": category, "amount_cents": amount_cents, "quantity": quantity}


def purchase_transaction_payload(
    member_id: str,
    site_id: str,
    transacted_at: str = MID_AUGUST,
    lines: Optional[List[dict]] = None,
    **overrides,
) -> dict:
    payload = {
        "member_id": member_id,
        "site_id": site_id,
        "transacted_at": transacted_at,
        "lines": lines if lines is not None else [purchase_line()],
    }
    payload.update(overrides)
    return payload


def point_transfer_payload(
    member_id: str, recipient_member_id: str, points: int = 100, **overrides
) -> dict:
    payload = {
        "member_id": member_id,
        "recipient_member_id": recipient_member_id,
        "points": points,
    }
    payload.update(overrides)
    return payload


def fuel_redemption_payload(
    member_id: str,
    site_id: str,
    alt_id_presented: str,
    points_committed: int,
    expected_member_version: int,
    **overrides,
) -> dict:
    payload = {
        "member_id": member_id,
        "site_id": site_id,
        "alt_id_presented": alt_id_presented,
        "points_committed": points_committed,
        "expected_member_version": expected_member_version,
    }
    payload.update(overrides)
    return payload


def settlement_batch_payload(
    site_id: str,
    period_start: str,
    period_end: str,
    expected_site_version: int,
    **overrides,
) -> dict:
    payload = {
        "site_id": site_id,
        "period_start": period_start,
        "period_end": period_end,
        "expected_site_version": expected_site_version,
    }
    payload.update(overrides)
    return payload


def point_dispute_payload(
    member_id: str,
    disputed_ledger_entry_id: str,
    claimed_points: int = 100,
    reason_code: str = "MISSING_ACCRUAL",
    **overrides,
) -> dict:
    payload = {
        "member_id": member_id,
        "disputed_ledger_entry_id": disputed_ledger_entry_id,
        "claimed_points": claimed_points,
        "reason_code": reason_code,
    }
    payload.update(overrides)
    return payload


def propose_adjustment_payload(
    proposed_points_delta: int = 100, authority_tier: str = "TIER1", **overrides
) -> dict:
    payload = {
        "proposed_points_delta": proposed_points_delta,
        "authority_tier": authority_tier,
    }
    payload.update(overrides)
    return payload


def fraud_signal_payload(
    household_id: str,
    signal_type: str = "RAPID_TRANSFER",
    severity_weight: int = 25,
    **overrides,
) -> dict:
    payload = {
        "household_id": household_id,
        "signal_type": signal_type,
        "severity_weight": severity_weight,
    }
    payload.update(overrides)
    return payload
