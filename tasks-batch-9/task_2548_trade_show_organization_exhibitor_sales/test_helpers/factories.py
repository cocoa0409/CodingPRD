"""
Request-payload factories.  Every factory returns ONLY input fields: "`id` is a
server-generated UUID ... Clients never supply any of them."

Each factory takes keyword overrides so a test can vary exactly one input.
"""

from typing import Any, Dict, List, Optional

from .constants import DEFAULT_CLOCK
from .types import (
    LocationClass,
    PremiumZone,
    RegistrationCategory,
    ServiceType,
    SpendBand,
    PurchasingAuthority,
    ViolationType,
)


# ── §3.1 VenueContract ──────────────────────────────────────────────────────
def venue_contract_payload(**overrides: Any) -> Dict[str, Any]:
    """The canonical Metro Convention Centre HALL_A rate card and term."""
    payload: Dict[str, Any] = {
        "venue_code": "MCC",
        "hall_code": "HALL_A",
        "hall_gross_sqft": 250000,
        "min_aisle_ratio_pct": 30,
        "max_booth_height_ft": 20,
        "contract_year_start": 2027,
        "contract_year_count": 3,
        "committed_net_sqft_per_year": 1200,
        "attrition_allowance_pct": 15,
        "advance_order_discount_pct": 20,
        "labor_rate_cents_per_hour": 9500,
        "electrical_rate_cents_per_amp": 4200,
        "material_handling_rate_cents_per_cwt": 8800,
    }
    payload.update(overrides)
    return payload


def terminate_payload(expected_venue_contract_version: int,
                      terminated_effective_date: str,
                      **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_venue_contract_version": expected_venue_contract_version,
        "terminated_effective_date": terminated_effective_date,
    }
    payload.update(overrides)
    return payload


# ── §3.1 Show ───────────────────────────────────────────────────────────────
def show_payload(venue_contract_id: str, **overrides: Any) -> Dict[str, Any]:
    """The canonical 2027 edition: move-in 2027-03-01, event 03-05..03-07."""
    payload: Dict[str, Any] = {
        "venue_contract_id": venue_contract_id,
        "name": "National Buyers Expo",
        "edition_year": 2027,
        "move_in_start": "2027-03-01",
        "event_start": "2027-03-05",
        "event_end": "2027-03-07",
        "move_out_end": "2027-03-09",
        "gross_sqft": 100000,
        "aisle_ratio_pct": 40,
        "base_rate_cents_per_sqft": 3275,
        "selection_desk_capacity": 2,
    }
    payload.update(overrides)
    return payload


def show_2028_payload(venue_contract_id: str, **overrides: Any) -> Dict[str, Any]:
    """The sibling 2028 edition used as a rebooking target."""
    payload = show_payload(
        venue_contract_id,
        edition_year=2028,
        move_in_start="2028-03-01",
        event_start="2028-03-05",
        event_end="2028-03-07",
        move_out_end="2028-03-09",
        base_rate_cents_per_sqft=3400,
    )
    payload.update(overrides)
    return payload


def transition_payload(target_status: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"target_status": target_status}
    payload.update(overrides)
    return payload


# ── §3.2 Booth ──────────────────────────────────────────────────────────────
def booth_payload(booth_number: str = "A100", width_ft: int = 20,
                  depth_ft: int = 20,
                  location_class: str = LocationClass.CORNER,
                  max_height_ft: int = 16,
                  premium_zone: Optional[str] = PremiumZone.MAIN_AISLE,
                  **overrides: Any) -> Dict[str, Any]:
    """A 20x20 CORNER / MAIN_AISLE booth: 400 sqft at the canonical base rate."""
    payload: Dict[str, Any] = {
        "booth_number": booth_number,
        "width_ft": width_ft,
        "depth_ft": depth_ft,
        "location_class": location_class,
        "max_height_ft": max_height_ft,
    }
    if premium_zone is not None:
        payload["premium_zone"] = premium_zone
    payload.update(overrides)
    return payload


def inline_booth_payload(booth_number: str, width_ft: int, depth_ft: int,
                         max_height_ft: int = 12,
                         **overrides: Any) -> Dict[str, Any]:
    """An INLINE booth with no premium zone: both multipliers are 1.00."""
    payload = booth_payload(
        booth_number=booth_number,
        width_ft=width_ft,
        depth_ft=depth_ft,
        location_class=LocationClass.INLINE,
        max_height_ft=max_height_ft,
        premium_zone=PremiumZone.NONE,
    )
    payload.update(overrides)
    return payload


def combine_payload(expected_show_version: int,
                    booth_ids: List[str]) -> Dict[str, Any]:
    return {"expected_show_version": expected_show_version,
            "booth_ids": booth_ids}


# ── §3.3 Exhibitor ──────────────────────────────────────────────────────────
def exhibitor_payload(legal_name: str = "Atlas Kitchenware LLC",
                      contact_email: str = "sales@atlaskitchenware.example",
                      **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": legal_name,
        "contact_email": contact_email,
    }
    payload.update(overrides)
    return payload


def point_adjustment_payload(points_delta: int,
                             reason: str = "Negotiated loyalty grant") -> Dict[str, Any]:
    return {"points_delta": points_delta, "reason": reason}


# ── §3.4 SelectionAppointment ───────────────────────────────────────────────
def appointment_payload(exhibitor_id: str, round_index: int = 1,
                        window_start: str = "2027-01-10T09:00:00Z",
                        window_end: str = "2027-01-10T11:00:00Z",
                        **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "exhibitor_id": exhibitor_id,
        "round_index": round_index,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def exercise_payload(expected_show_version: int, requested_sqft: int,
                     **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_show_version": expected_show_version,
        "requested_sqft": requested_sqft,
    }
    payload.update(overrides)
    return payload


# ── §3.5 SpaceContract ──────────────────────────────────────────────────────
def space_contract_payload(show_id: str, exhibitor_id: str,
                           expected_show_version: int, requested_sqft: int,
                           **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "show_id": show_id,
        "exhibitor_id": exhibitor_id,
        "expected_show_version": expected_show_version,
        "requested_sqft": requested_sqft,
    }
    payload.update(overrides)
    return payload


def counter_payload(requested_discount_pct: int) -> Dict[str, Any]:
    return {"action": "COUNTER", "requested_discount_pct": requested_discount_pct}


def reoffer_payload(approved_discount_pct: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "action": "REOFFER",
        "approved_discount_pct": approved_discount_pct,
    }
    payload.update(overrides)
    return payload


def sign_payload(expected_show_version: int,
                 deposit_paid_cents: int) -> Dict[str, Any]:
    return {"expected_show_version": expected_show_version,
            "deposit_paid_cents": deposit_paid_cents}


def deposit_payload(amount_cents: int) -> Dict[str, Any]:
    return {"amount_cents": amount_cents}


def cancel_payload(
    cancellation_reason: str = "Exhibitor withdrew from the edition",
) -> Dict[str, Any]:
    return {"cancellation_reason": cancellation_reason}


def rebook_payload(target_show_id: str, expected_target_show_version: int,
                   requested_sqft: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "target_show_id": target_show_id,
        "expected_target_show_version": expected_target_show_version,
        "requested_sqft": requested_sqft,
    }
    payload.update(overrides)
    return payload


# ── §3.9 ServiceOrder / RuleViolation / LeadScan ────────────────────────────
def service_order_payload(service_type: str = ServiceType.LABOR,
                          quantity: int = 8,
                          ordered_at: str = "2027-02-08T00:00:00Z",
                          **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "service_type": service_type,
        "quantity": quantity,
        "ordered_at": ordered_at,
    }
    payload.update(overrides)
    return payload


def rule_violation_payload(violation_type: str = ViolationType.NOISE,
                           notes: str = "Amplified demo audible two aisles away",
                           **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "violation_type": violation_type,
        "notes": notes,
    }
    payload.update(overrides)
    return payload


def adjudicate_payload(disposition: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"disposition": disposition}
    payload.update(overrides)
    return payload


def lead_scan_payload(registration_id: str,
                      scanned_at: str = "2027-03-05T10:00:00Z") -> Dict[str, Any]:
    return {"registration_id": registration_id, "scanned_at": scanned_at}


# ── §3.7 Sponsorship ────────────────────────────────────────────────────────
def sponsorship_package_payload(package_code: str = "PKG_KEYNOTE",
                                list_price_cents: int = 1000000,
                                price_floor_cents: int = 700000,
                                inventory_total: int = 2,
                                obligation_codes: Optional[List[str]] = None,
                                priority_point_value: int = 12,
                                **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "package_code": package_code,
        "list_price_cents": list_price_cents,
        "price_floor_cents": price_floor_cents,
        "inventory_total": inventory_total,
        "obligation_codes": (
            list(obligation_codes) if obligation_codes is not None
            else ["STAGE_BRANDING", "PROGRAM_AD"]
        ),
        "priority_point_value": priority_point_value,
    }
    payload.update(overrides)
    return payload


def sponsorship_deal_payload(exhibitor_id: str,
                             negotiated_price_cents: int) -> Dict[str, Any]:
    return {"exhibitor_id": exhibitor_id,
            "negotiated_price_cents": negotiated_price_cents}


def resolve_obligation_payload(disposition: str,
                               **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"disposition": disposition}
    payload.update(overrides)
    return payload


# ── §3.8 Registration ───────────────────────────────────────────────────────
def registration_payload(category: str = RegistrationCategory.BUYER,
                         company_name: str = "Northwind Retail Group",
                         job_title: str = "Director of Merchandising",
                         purchasing_authority: str = PurchasingAuthority.DECISION_MAKER,
                         annual_spend_band: str = SpendBand.OVER_1M,
                         email: str = "buyer@northwind.example",
                         **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "category": category,
        "company_name": company_name,
        "job_title": job_title,
        "purchasing_authority": purchasing_authority,
        "annual_spend_band": annual_spend_band,
        "email": email,
    }
    payload.update(overrides)
    return payload


def screen_payload(decision: str, reason: str) -> Dict[str, Any]:
    return {"decision": decision, "reason": reason}


# ── §2.4 logical clock ──────────────────────────────────────────────────────
def clock_payload(current_utc: str = DEFAULT_CLOCK) -> Dict[str, Any]:
    return {"current_utc": current_utc}
