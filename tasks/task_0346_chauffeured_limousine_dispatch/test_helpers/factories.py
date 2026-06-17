"""Payload factories — one per entity, input fields only.

Each factory returns a dict carrying only the server-accepted input fields for
the corresponding create endpoint. Optional fields are omitted unless overridden,
so factories can exercise both the default-applied path and explicit values.
"""


def create_corporate_account_payload(**overrides) -> dict:
    defaults = {
        "company_name": "Acme",
        "billing_email": "ap@acme.com",
    }
    defaults.update(overrides)
    return defaults


def create_affiliate_payload(**overrides) -> dict:
    defaults = {
        "name": "Bay Black Car",
        "market_code": "SFO",
        "payout_share_pct": 70,
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_class_payload(**overrides) -> dict:
    defaults = {
        "code": "SEDAN",
        "base_fare_cents": 5000,
        "per_mile_cents": 250,
        "hourly_rate_cents": 12000,
        "wait_per_minute_cents": 200,
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(vehicle_class_id: str, **overrides) -> dict:
    defaults = {
        "vehicle_class_id": vehicle_class_id,
        "plate": "BLK-1",
    }
    defaults.update(overrides)
    return defaults


def create_chauffeur_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dana",
        "home_market_code": "SFO",
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(corporate_account_id: str, vehicle_class_id: str, **overrides) -> dict:
    defaults = {
        "corporate_account_id": corporate_account_id,
        "trip_type": "POINT_TO_POINT",
        "vehicle_class_id": vehicle_class_id,
        "pickup_at": "2026-07-01T12:00:00Z",
        "planned_drop_at": "2026-07-01T13:00:00Z",
        "estimated_miles": 10,
    }
    defaults.update(overrides)
    return defaults


def create_flight_tracking_payload(reservation_id: str, **overrides) -> dict:
    defaults = {
        "reservation_id": reservation_id,
        "flight_number": "UA1234",
        "scheduled_arrival_at": "2026-07-06T15:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(reservation_id: str, chauffeur_id: str, vehicle_id: str,
                              expected_reservation_version: int, **overrides) -> dict:
    defaults = {
        "reservation_id": reservation_id,
        "chauffeur_id": chauffeur_id,
        "vehicle_id": vehicle_id,
        "expected_reservation_version": expected_reservation_version,
    }
    defaults.update(overrides)
    return defaults


def create_farm_out_order_payload(reservation_id: str, affiliate_id: str,
                                  expected_reservation_version: int, **overrides) -> dict:
    defaults = {
        "reservation_id": reservation_id,
        "affiliate_id": affiliate_id,
        "expected_reservation_version": expected_reservation_version,
    }
    defaults.update(overrides)
    return defaults


def wait_event_payload(kind: str, occurred_at: str, **overrides) -> dict:
    defaults = {"kind": kind, "occurred_at": occurred_at}
    defaults.update(overrides)
    return defaults


def trip_event_payload(action: str, **overrides) -> dict:
    defaults = {"action": action}
    defaults.update(overrides)
    return defaults


def billing_event_payload(action: str, **overrides) -> dict:
    defaults = {"action": action}
    defaults.update(overrides)
    return defaults


def decision_event_payload(action: str, **overrides) -> dict:
    defaults = {"action": action}
    defaults.update(overrides)
    return defaults


def duty_event_payload(action: str, **overrides) -> dict:
    defaults = {"action": action}
    defaults.update(overrides)
    return defaults


def flight_update_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults
