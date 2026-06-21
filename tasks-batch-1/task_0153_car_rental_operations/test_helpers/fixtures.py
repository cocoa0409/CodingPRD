"""Composite setup helpers for the Car Rental Operations API.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the server database starts empty before every test. Fixtures
use get_success_data() (lenient) so setup failures surface as clear "Setup failed"
errors rather than confusing assertion mismatches.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_fleet_manager_headers,
    make_rental_agent_headers,
    make_member_headers,
)
from . import factories as f

FM = make_fleet_manager_headers()
RA = make_rental_agent_headers()

# Standard ECON rate card used by most threshold scenarios.
ECON_CARD = dict(
    code="ECON", tier_rank=1, daily_rate_cents=5000, weekly_rate_cents=28000,
    included_miles_per_day=200, overage_per_mile_cents=25,
    ldw_per_day_cents=1500, pai_per_day_cents=800,
)


# ---------------------------------------------------------------------------
# Tier 1 / 2: base catalogue primitives
# ---------------------------------------------------------------------------
def create_location(api=api_client, headers=None, **overrides) -> dict:
    headers = headers or FM
    return get_success_data(api.create_location(f.create_location_payload(**overrides), headers))


def create_vehicle_class(api=api_client, headers=None, **overrides) -> dict:
    headers = headers or FM
    return get_success_data(api.create_vehicle_class(f.create_vehicle_class_payload(**overrides), headers))


def create_econ_class(api=api_client, headers=None, **overrides) -> dict:
    payload = dict(ECON_CARD)
    payload.update(overrides)
    headers = headers or FM
    return get_success_data(api.create_vehicle_class(payload, headers))


def create_vehicle(location_id, class_id, api=api_client, headers=None, **overrides) -> dict:
    headers = headers or FM
    return get_success_data(
        api.create_vehicle(f.create_vehicle_payload(location_id, class_id, **overrides), headers)
    )


def create_member(api=api_client, headers=None, **overrides) -> dict:
    headers = headers or RA
    return get_success_data(api.create_member(f.create_member_payload(**overrides), headers))


def set_member_loyalty(member_id, api=api_client, headers=None, **fields) -> dict:
    headers = headers or FM
    return get_success_data(api.set_member_loyalty(member_id, fields, headers))


def set_clock(to_iso8601, api=api_client, headers=None) -> None:
    headers = headers or RA
    get_success_data(api.set_clock({"to_iso8601": to_iso8601}, headers))


def create_reservation(member_id, pickup_location_id, dropoff_location_id, class_id,
                       pickup_at, dropoff_at, api=api_client, headers=None, **overrides) -> dict:
    headers = headers or RA
    payload = f.create_reservation_payload(
        member_id, pickup_location_id, dropoff_location_id, class_id,
        pickup_at, dropoff_at, **overrides,
    )
    return get_success_data(api.create_reservation(payload, headers))


def confirm_reservation(reservation_id, api=api_client, headers=None) -> dict:
    headers = headers or RA
    return get_success_data(api.confirm_reservation(reservation_id, headers))


def hold_vehicle(vehicle_id, reservation_id, expected_version, api=api_client, headers=None) -> dict:
    headers = headers or RA
    return get_success_data(api.hold_vehicle(
        vehicle_id,
        {"reservation_id": reservation_id, "expected_vehicle_version": expected_version},
        headers,
    ))


# ---------------------------------------------------------------------------
# Tier 2: a one-location, one-ECON-class fleet
# ---------------------------------------------------------------------------
def setup_fleet(api=api_client, num_vehicles=1, location_overrides=None,
                class_overrides=None) -> dict:
    """Active branch + ECON class + `num_vehicles` AVAILABLE vehicles.

    Returns dict with keys: location, vehicle_class, vehicles (list).
    """
    loc = create_location(api=api, **(location_overrides or {}))
    cls = create_econ_class(api=api, **(class_overrides or {}))
    vehicles = [create_vehicle(loc["id"], cls["id"], api=api) for _ in range(num_vehicles)]
    return {"location": loc, "vehicle_class": cls, "vehicles": vehicles}


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_confirmed_reservation(api=api_client, member_overrides=None,
                                reservation_overrides=None, class_overrides=None,
                                location_overrides=None, num_vehicles=1,
                                pickup_at="2026-07-01T10:00:00Z",
                                dropoff_at="2026-07-04T10:00:00Z") -> dict:
    """Active fleet + member + CONFIRMED reservation (vehicle NOT yet held).

    Returns dict: location, vehicle_class, vehicles, member, reservation (confirmed).
    """
    fleet = setup_fleet(api=api, num_vehicles=num_vehicles,
                        location_overrides=location_overrides, class_overrides=class_overrides)
    member = create_member(api=api, **(member_overrides or {}))
    res = create_reservation(
        member["id"], fleet["location"]["id"], fleet["location"]["id"],
        fleet["vehicle_class"]["id"], pickup_at, dropoff_at,
        api=api, **(reservation_overrides or {}),
    )
    confirmed = confirm_reservation(res["id"], api=api)
    return {**fleet, "member": member, "reservation": confirmed}


def setup_open_agreement(api=api_client, member_overrides=None,
                         reservation_overrides=None, class_overrides=None,
                         odometer_out=1000, fuel_out_eighths=8,
                         pickup_at="2026-07-01T10:00:00Z",
                         dropoff_at="2026-07-04T10:00:00Z") -> dict:
    """Active fleet + member + reservation -> confirm -> hold -> pickup (OPEN agreement).

    Returns dict: location, vehicle_class, vehicles, member, reservation, vehicle,
    agreement (OPEN).
    """
    ctx = setup_confirmed_reservation(
        api=api, member_overrides=member_overrides,
        reservation_overrides=reservation_overrides, class_overrides=class_overrides,
        pickup_at=pickup_at, dropoff_at=dropoff_at,
    )
    vehicle = ctx["vehicles"][0]
    hold_vehicle(vehicle["id"], ctx["reservation"]["id"], vehicle["version"], api=api)
    agreement = get_success_data(api.create_rental_agreement(
        f.create_rental_agreement_payload(
            ctx["reservation"]["id"], vehicle["id"],
            odometer_out=odometer_out, fuel_out_eighths=fuel_out_eighths,
        ),
        RA,
    ))
    return {**ctx, "vehicle": vehicle, "agreement": agreement}


def setup_closed_agreement(api=api_client, odometer_in=1100, fuel_in_eighths=8,
                           member_overrides=None, reservation_overrides=None,
                           class_overrides=None, odometer_out=1000,
                           fuel_out_eighths=8) -> dict:
    """Drive an OPEN agreement through to CLOSED.

    Returns the setup_open_agreement dict plus agreement_closed.
    """
    ctx = setup_open_agreement(
        api=api, member_overrides=member_overrides,
        reservation_overrides=reservation_overrides, class_overrides=class_overrides,
        odometer_out=odometer_out, fuel_out_eighths=fuel_out_eighths,
    )
    closed = get_success_data(api.close_rental_agreement(
        ctx["agreement"]["id"],
        {"odometer_in": odometer_in, "fuel_in_eighths": fuel_in_eighths},
        RA,
    ))
    return {**ctx, "agreement_closed": closed}


def file_incident(agreement_id, severity, assessed_damage_cents, api=api_client, headers=None) -> dict:
    headers = headers or RA
    return get_success_data(api.create_incident_report(
        f.create_incident_report_payload(agreement_id, severity, assessed_damage_cents),
        headers,
    ))


def get_vehicle(vehicle_id, api=api_client, headers=None) -> dict:
    headers = headers or RA
    return get_success_data(api.get_vehicle(vehicle_id, headers))


def get_vehicle_class(class_id, api=api_client, headers=None) -> dict:
    headers = headers or RA
    return get_success_data(api.get_vehicle_class(class_id, headers))


def get_reservation(reservation_id, api=api_client, headers=None) -> dict:
    headers = headers or RA
    return get_success_data(api.get_reservation(reservation_id, headers))


def get_agreement(agreement_id, api=api_client, headers=None) -> dict:
    headers = headers or RA
    return get_success_data(api.get_rental_agreement(agreement_id, headers))


def get_member(member_id, api=api_client, headers=None) -> dict:
    headers = headers or RA
    return get_success_data(api.get_member(member_id, headers))


def get_ledger_entries(agreement_id, api=api_client, headers=None, params=None) -> list:
    headers = headers or RA
    data, _meta = _list(api.list_agreement_ledger_entries(agreement_id, headers, params=params))
    return data


def get_member_accruals(member_id, api=api_client, headers=None, params=None) -> list:
    headers = headers or RA
    data, _meta = _list(api.list_member_loyalty_accruals(member_id, headers, params=params))
    return data


def _list(response):
    """Lenient paginated read for fixtures: returns (data_list, meta)."""
    body = get_success_data(response)
    # get_success_data returns the data payload (a list for array responses).
    meta = response.json().get("meta", {})
    return body, meta
