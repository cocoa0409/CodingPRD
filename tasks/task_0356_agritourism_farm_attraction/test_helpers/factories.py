"""Payload factories — one per writable entity, input fields only.

Each factory returns the minimal valid create payload and merges **overrides so
tests can pin the exact field a claim targets.
"""
from .constants import RATE_CARD, WINDOW_START, WINDOW_END


# --- Farm -------------------------------------------------------------------

def create_farm_payload(**overrides) -> dict:
    defaults = {"name": "Test Farm"}
    defaults.update(overrides)
    return defaults


# --- WeatherEvent -----------------------------------------------------------

def create_weather_event_payload(kind, **overrides) -> dict:
    defaults = {"kind": kind}
    defaults.update(overrides)
    return defaults


# --- PricingPolicy ----------------------------------------------------------

def create_pricing_policy_payload(**overrides) -> dict:
    defaults = dict(RATE_CARD)
    defaults.update(overrides)
    return defaults


# --- AdmissionWindow --------------------------------------------------------

def create_admission_window_payload(starts_at=WINDOW_START, ends_at=WINDOW_END,
                                    capacity=10, **overrides) -> dict:
    defaults = {"starts_at": starts_at, "ends_at": ends_at, "capacity": capacity}
    defaults.update(overrides)
    return defaults


# --- Visitor ----------------------------------------------------------------

def create_visitor_payload(email="visitor@example.com", full_name="Test Visitor",
                           **overrides) -> dict:
    defaults = {"email": email, "full_name": full_name}
    defaults.update(overrides)
    return defaults


# --- SeasonPass -------------------------------------------------------------

def create_season_pass_payload(visitor_id, valid_from="2026-10-01T00:00:00Z",
                               valid_until="2026-11-01T00:00:00Z", **overrides) -> dict:
    defaults = {"visitor_id": visitor_id, "valid_from": valid_from, "valid_until": valid_until}
    defaults.update(overrides)
    return defaults


# --- Reservation ------------------------------------------------------------

def create_reservation_payload(window_id, visitor_id, expected_window_version,
                               adult_count=1, child_count=0, **overrides) -> dict:
    defaults = {
        "window_id": window_id,
        "visitor_id": visitor_id,
        "adult_count": adult_count,
        "child_count": child_count,
        "expected_window_version": expected_window_version,
    }
    defaults.update(overrides)
    return defaults


# --- ActivityPass -----------------------------------------------------------

def create_activity_pass_payload(activity, quantity=1, **overrides) -> dict:
    defaults = {"activity": activity, "quantity": quantity}
    defaults.update(overrides)
    return defaults


# --- Waiver -----------------------------------------------------------------

def create_waiver_payload(participant_name, **overrides) -> dict:
    defaults = {"participant_name": participant_name}
    defaults.update(overrides)
    return defaults


# --- PumpkinPurchase --------------------------------------------------------

def create_pumpkin_purchase_payload(estimated_weight_lb, **overrides) -> dict:
    defaults = {"estimated_weight_lb": estimated_weight_lb}
    defaults.update(overrides)
    return defaults


def weigh_out_payload(scale_weight_lb, **overrides) -> dict:
    defaults = {"scale_weight_lb": scale_weight_lb}
    defaults.update(overrides)
    return defaults


# --- ConcessionOrder --------------------------------------------------------

def create_concession_order_payload(food_cents=0, vehicle_count=0, **overrides) -> dict:
    defaults = {"food_cents": food_cents, "vehicle_count": vehicle_count}
    defaults.update(overrides)
    return defaults


# --- GroupBooking -----------------------------------------------------------

def create_group_booking_payload(window_id, group_leader_id, kind,
                                 adult_count=0, child_count=0, **overrides) -> dict:
    defaults = {
        "window_id": window_id,
        "group_leader_id": group_leader_id,
        "kind": kind,
        "adult_count": adult_count,
        "child_count": child_count,
    }
    defaults.update(overrides)
    return defaults
