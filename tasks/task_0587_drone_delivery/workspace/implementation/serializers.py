"""Resource -> JSON payload projection (PRD 2.5, 2.8)."""
from decimal import Decimal

import calc
from services import flight_service
from timeutil import iso


def num(value, places=None):
    if value is None:
        return None
    dec = Decimal(str(value))
    if places is not None:
        dec = calc.rhu(dec, places)
    return float(dec)


def _audit(rec, versioned=True):
    out = {"id": rec["id"], "created_at": iso(rec["created_at"])}
    if versioned:
        out["updated_at"] = iso(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def service_area(rec):
    out = _audit(rec)
    out.update(
        name=rec["name"],
        center_lat=num(rec["center_lat"]),
        center_lon=num(rec["center_lon"]),
        max_range_km=num(rec["max_range_km"]),
        max_payload_g=rec["max_payload_g"],
        status=rec["status"],
    )
    return out


def nest(rec):
    out = _audit(rec)
    out.update(
        service_area_id=rec["service_area_id"],
        name=rec["name"],
        lat=num(rec["lat"]),
        lon=num(rec["lon"]),
        pad_count=rec["pad_count"],
        status=rec["status"],
        reserved_pads=flight_service.reserved_pads(rec["id"]),
    )
    return out


def drone(rec):
    out = _audit(rec)
    out.update(
        home_nest_id=rec["home_nest_id"],
        tail_number=rec["tail_number"],
        airframe_class=rec["airframe_class"],
        max_payload_g=rec["max_payload_g"],
        cruise_speed_kmh=num(rec["cruise_speed_kmh"]),
        hours_since_service=num(rec["hours_since_service"], 2),
        flight_hours=num(rec["flight_hours"], 2),
        status=rec["status"],
        installed_battery_id=rec["installed_battery_id"],
        advisory_risk_score=num(calc.advisory_risk_score(rec), 1),
        blocking_risk_score=num(calc.blocking_risk_score(rec), 1),
    )
    return out


def battery(rec):
    out = _audit(rec)
    out.update(
        nest_id=rec["nest_id"],
        serial=rec["serial"],
        charge_pct=num(rec["charge_pct"], 1),
        cycle_count=rec["cycle_count"],
        state=rec["state"],
        health_pct=num(calc.health_pct(rec["cycle_count"]), 1),
    )
    return out


def customer(rec):
    out = _audit(rec)
    out.update(
        name=rec["name"],
        email=rec["email"],
        dropoff_lat=num(rec["dropoff_lat"]),
        dropoff_lon=num(rec["dropoff_lon"]),
        held_total=num(flight_service.held_total(rec["id"]), 2),
        billed_total=num(flight_service.billed_total(rec["id"]), 2),
    )
    return out


def order(rec):
    out = _audit(rec)
    out.update(
        customer_id=rec["customer_id"],
        service_area_id=rec["service_area_id"],
        payload_weight_g=rec["payload_weight_g"],
        priority=rec["priority"],
        dropoff_lat=num(rec["dropoff_lat"]),
        dropoff_lon=num(rec["dropoff_lon"]),
        distance_km=num(rec["distance_km"], 3),
        delivery_fee=num(rec["delivery_fee"], 2),
        airspace_surcharge=num(rec["airspace_surcharge"], 2),
        order_total=num(rec["order_total"], 2),
        status=rec["status"],
    )
    return out


def flight(rec):
    out = _audit(rec)
    out.update(
        order_id=rec["order_id"],
        drone_id=rec["drone_id"],
        launch_nest_id=rec["launch_nest_id"],
        recovery_nest_id=rec["recovery_nest_id"],
        battery_id=rec["battery_id"],
        ops_state=rec["ops_state"],
        clearance_state=rec["clearance_state"],
        planned_route_km=num(rec["planned_route_km"], 3),
        required_energy_pct=num(rec["required_energy_pct"], 1),
        actual_energy_pct=num(rec["actual_energy_pct"], 1),
        actual_route_km=num(rec["actual_route_km"], 3),
        wind_kph_at_dispatch=num(rec["wind_kph_at_dispatch"]),
        eta_recovery_at=iso(rec["eta_recovery_at"]),
        pad_hold_start=iso(rec["pad_hold_start"]),
        pad_hold_end=iso(rec["pad_hold_end"]),
        filed_by_user_id=rec["filed_by_user_id"],
        released_by_user_id=rec["released_by_user_id"],
        abort_reason=rec["abort_reason"],
    )
    return out


def authorization(rec):
    out = _audit(rec)
    out.update(
        flight_id=rec["flight_id"],
        grid_cells=list(rec["grid_cells"]),
        requested_alt_ft=rec["requested_alt_ft"],
        window_start=iso(rec["window_start"]),
        window_end=iso(rec["window_end"]),
        status=rec["status"],
        auth_code=rec["auth_code"],
    )
    return out


def geofence_zone(rec):
    out = _audit(rec)
    out.update(
        service_area_id=rec["service_area_id"],
        kind=rec["kind"],
        center_lat=num(rec["center_lat"]),
        center_lon=num(rec["center_lon"]),
        radius_km=num(rec["radius_km"]),
        effective_from=iso(rec["effective_from"]),
        effective_to=iso(rec["effective_to"]),
        status=rec["status"],
    )
    return out


def weather_observation(rec):
    out = _audit(rec, versioned=False)
    out.update(
        service_area_id=rec["service_area_id"],
        observed_at=iso(rec["observed_at"]),
        wind_kph=num(rec["wind_kph"]),
        gust_kph=num(rec["gust_kph"]),
        visibility_km=num(rec["visibility_km"]),
        precip=rec["precip"],
        flyable=rec["flyable"],
    )
    return out


def delivery_drop(rec):
    out = _audit(rec, versioned=False)
    out.update(
        flight_id=rec["flight_id"],
        drop_lat=num(rec["drop_lat"]),
        drop_lon=num(rec["drop_lon"]),
        hover_alt_ft=rec["hover_alt_ft"],
        photo_ref=rec["photo_ref"],
        confirmed_by_user_id=rec["confirmed_by_user_id"],
    )
    return out


def incident(rec):
    out = _audit(rec)
    out.update(
        drone_id=rec["drone_id"],
        flight_id=rec["flight_id"],
        severity=rec["severity"],
        category=rec["category"],
        narrative=rec["narrative"],
        status=rec["status"],
    )
    return out


def maintenance_log(rec):
    out = _audit(rec)
    out.update(
        drone_id=rec["drone_id"],
        incident_id=rec["incident_id"],
        work_type=rec["work_type"],
        scheduled_start=iso(rec["scheduled_start"]),
        scheduled_end=iso(rec["scheduled_end"]),
        status=rec["status"],
        completed_at=iso(rec["completed_at"]),
        notes=rec["notes"],
    )
    return out


BY_ENTITY = {
    "ServiceArea": service_area,
    "Nest": nest,
    "Drone": drone,
    "Battery": battery,
    "Customer": customer,
    "Order": order,
    "Flight": flight,
    "AirspaceAuthorization": authorization,
    "GeofenceZone": geofence_zone,
    "WeatherObservation": weather_observation,
    "DeliveryDrop": delivery_drop,
    "Incident": incident,
    "MaintenanceLog": maintenance_log,
}
