"""Flight legs: creation, forecast, delay / restore, cancel, depart, arrive."""
from db import base_row, parse_iso, sorted_rows, store, touch
from middleware import (ALL_ROLES, ROLE_ACCEPTANCE_AGENT, ROLE_PROGRAM_ADMIN, register,
                        resolve_fk)
from response import created_response, object_response
from services import calc, domain, serialize
from routes.helpers import listing

ADMIN = [ROLE_PROGRAM_ADMIN]
ACCEPTANCE = [ROLE_ACCEPTANCE_AGENT]

LEG_SCHEMA = {
    "flight_number": {"type": "string", "required": True, "min_length": 1},
    "origin_station_id": {"type": "string", "required": True},
    "destination_station_id": {"type": "string", "required": True},
    "scheduled_departure_utc": {"type": "datetime", "required": True},
    "scheduled_arrival_utc": {"type": "datetime", "required": True},
    "forecast_high_c": {"type": "number", "required": True},
    "forecast_low_c": {"type": "number", "required": True},
    "cabin_animal_limit": {"type": "integer", "required": True, "gte": 0},
    "checked_animal_limit": {"type": "integer", "required": True, "gte": 0},
    "cargo_animal_limit": {"type": "integer", "required": True, "gte": 0},
}

FORECAST_SCHEMA = {
    "forecast_high_c": {"type": "number", "required": True},
    "forecast_low_c": {"type": "number", "required": True},
}

DELAY_SCHEMA = {
    "new_departure_utc": {"type": "datetime", "required": True},
    "new_arrival_utc": {"type": "datetime", "required": True},
}

RESTORE_SCHEMA = {
    "restored_departure_utc": {"type": "datetime", "required": True},
    "restored_arrival_utc": {"type": "datetime", "required": True},
}

REASON_SCHEMA = {"reason": {"type": "string", "nullable": True}}


def _reprice_downstream(leg, statuses, release_illegal):
    """connection_welfare_window over the slots that connect off this leg."""
    for segment in domain.downstream_segments(leg, statuses):
        minutes = domain.refresh_connection_window(segment)
        if not release_illegal or minutes is None:
            continue
        minimum = calc.CONNECTION_MINIMUM[segment["routing_type"]]
        if minutes < minimum or minutes > calc.CONNECTION_MAXIMUM_MINUTES:
            domain.release_segment(segment)


def init(app):
    @register(app, "/flight-legs", "POST", ADMIN, schema=LEG_SCHEMA)
    def create_leg(ctx):
        body = ctx.body
        origin = resolve_fk("station", body["origin_station_id"])
        destination = resolve_fk("station", body["destination_station_id"])
        departure = parse_iso(body["scheduled_departure_utc"])
        arrival = parse_iso(body["scheduled_arrival_utc"])
        domain.require(arrival > departure, "ERR_INVALID_TIME_RANGE",
                       "scheduled_arrival_utc must be strictly after "
                       "scheduled_departure_utc")
        row = base_row()
        row.update({
            "flight_number": body["flight_number"],
            "origin_station_id": origin["id"],
            "destination_station_id": destination["id"],
            "governing_embargo_rule_id": None,
            "scheduled_departure_utc": body["scheduled_departure_utc"],
            "scheduled_arrival_utc": body["scheduled_arrival_utc"],
            "block_minutes": domain.block_minutes(body["scheduled_departure_utc"],
                                                  body["scheduled_arrival_utc"]),
            "forecast_high_c": body["forecast_high_c"],
            "forecast_low_c": body["forecast_low_c"],
            "cabin_animal_limit": body["cabin_animal_limit"],
            "checked_animal_limit": body["checked_animal_limit"],
            "cargo_animal_limit": body["cargo_animal_limit"],
            "booked_cabin_count": 0,
            "booked_checked_count": 0,
            "booked_cargo_count": 0,
            "posture": "OPEN",
            "status": "SCHEDULED",
        })
        row["governing_embargo_rule_id"] = domain.select_governing_rule(row)
        row["posture"] = domain.derive_posture(row)
        store.legs[row["id"]] = row
        return created_response(serialize.dump("leg", row))

    @register(app, "/flight-legs/<rid>", "GET", ALL_ROLES, path_entity="leg")
    def get_leg(ctx):
        return object_response(serialize.dump("leg", ctx.row))

    @register(app, "/flight-legs", "GET", ALL_ROLES, paginated=True)
    def list_legs(ctx):
        return listing("leg", sorted_rows(store.legs), ctx,
                       [("origin_station_id", "origin_station_id", "str"),
                        ("destination_station_id", "destination_station_id", "str"),
                        ("governing_embargo_rule_id", "governing_embargo_rule_id", "str"),
                        ("status", "status", "str")])

    @register(app, "/flight-legs/<rid>/forecast", "PUT", ADMIN, schema=FORECAST_SCHEMA,
              path_entity="leg")
    def update_forecast(ctx):
        leg = ctx.row
        domain.require(leg["status"] in ("SCHEDULED", "DELAYED"),
                       "ERR_FLIGHT_LEG_INVALID_STATE",
                       "the forecast of a %s leg cannot be updated" % leg["status"])
        leg["forecast_high_c"] = ctx.body["forecast_high_c"]
        leg["forecast_low_c"] = ctx.body["forecast_low_c"]
        domain.embargo_determination(leg)
        domain.release_embargoed_slots(leg)
        domain.reconcile_leg(leg, force_touch=True)
        return object_response(serialize.dump("leg", leg))

    @register(app, "/flight-legs/<rid>/delay", "POST", ADMIN, schema=DELAY_SCHEMA,
              path_entity="leg")
    def delay_leg(ctx):
        leg = ctx.row
        domain.require(leg["status"] == "SCHEDULED", "ERR_FLIGHT_LEG_INVALID_STATE",
                       "only a SCHEDULED leg can be delayed")
        departure = parse_iso(ctx.body["new_departure_utc"])
        arrival = parse_iso(ctx.body["new_arrival_utc"])
        domain.require(arrival > departure, "ERR_INVALID_TIME_RANGE",
                       "new_arrival_utc must be strictly after new_departure_utc")
        domain.require(departure > parse_iso(leg["scheduled_departure_utc"]),
                       "ERR_SCHEDULE_NOT_MONOTONIC",
                       "new_departure_utc must be strictly after the current "
                       "scheduled_departure_utc")
        leg["scheduled_departure_utc"] = ctx.body["new_departure_utc"]
        leg["scheduled_arrival_utc"] = ctx.body["new_arrival_utc"]
        leg["block_minutes"] = domain.block_minutes(leg["scheduled_departure_utc"],
                                                    leg["scheduled_arrival_utc"])
        leg["status"] = "DELAYED"
        domain.embargo_determination(leg)
        _reprice_downstream(leg, ("RESERVED",), True)
        domain.reconcile_leg(leg, force_touch=True)
        return object_response(serialize.dump("leg", leg))

    @register(app, "/flight-legs/<rid>/restore-schedule", "POST", ADMIN,
              schema=RESTORE_SCHEMA, path_entity="leg")
    def restore_leg(ctx):
        leg = ctx.row
        domain.require(leg["status"] == "DELAYED", "ERR_FLIGHT_LEG_INVALID_STATE",
                       "only a DELAYED leg can be restored")
        departure = parse_iso(ctx.body["restored_departure_utc"])
        arrival = parse_iso(ctx.body["restored_arrival_utc"])
        domain.require(arrival > departure, "ERR_INVALID_TIME_RANGE",
                       "restored_arrival_utc must be strictly after "
                       "restored_departure_utc")
        domain.require(departure < parse_iso(leg["scheduled_departure_utc"]),
                       "ERR_SCHEDULE_NOT_MONOTONIC",
                       "restored_departure_utc must be strictly before the current "
                       "scheduled_departure_utc")
        leg["scheduled_departure_utc"] = ctx.body["restored_departure_utc"]
        leg["scheduled_arrival_utc"] = ctx.body["restored_arrival_utc"]
        leg["block_minutes"] = domain.block_minutes(leg["scheduled_departure_utc"],
                                                    leg["scheduled_arrival_utc"])
        leg["status"] = "SCHEDULED"
        domain.embargo_determination(leg)
        _reprice_downstream(leg, ("RESERVED", "ACCEPTED"), False)
        domain.reconcile_leg(leg, force_touch=True)
        return object_response(serialize.dump("leg", leg))

    @register(app, "/flight-legs/<rid>/cancel", "POST", ADMIN, schema=REASON_SCHEMA,
              path_entity="leg")
    def cancel_leg(ctx):
        leg = ctx.row
        domain.require(leg["status"] in ("SCHEDULED", "DELAYED"),
                       "ERR_FLIGHT_LEG_INVALID_STATE",
                       "a %s leg cannot be cancelled" % leg["status"])
        leg["status"] = "CANCELLED"
        for segment in domain.segments_of_leg(leg):
            if segment["status"] == "RESERVED":
                domain.release_segment(segment)
            elif segment["status"] == "ACCEPTED":
                animal = domain.animal_of_segment(segment)
                domain.offload_segment(segment, refund=True, mark_interrupted=False)
                if animal["status"] == "IN_TRANSIT":
                    animal["status"] = "TRAVEL_READY"
                    touch(animal)
                reservation = domain.reservation_of_animal(animal)
                domain._recompute_booking_status_after_release(reservation)
                domain.run_charge_assembly(reservation)
        domain.reconcile_leg(leg, force_touch=True)
        return object_response(serialize.dump("leg", leg))

    @register(app, "/flight-legs/<rid>/depart", "POST", ACCEPTANCE, schema={},
              path_entity="leg")
    def depart_leg(ctx):
        leg = ctx.row
        domain.require(leg["status"] in ("SCHEDULED", "DELAYED"),
                       "ERR_FLIGHT_LEG_INVALID_STATE",
                       "a %s leg cannot depart" % leg["status"])
        domain.require(leg["posture"] != "EMBARGOED", "ERR_LEG_EMBARGOED",
                       "the leg posture is EMBARGOED")
        segments = domain.segments_of_leg(leg)
        for segment in segments:
            if segment["status"] != "ACCEPTED":
                continue
            domain.require(segment["completed_welfare_check_count"]
                           >= segment["required_welfare_check_count"],
                           "ERR_WELFARE_CHECKS_INCOMPLETE",
                           "segment %s is missing welfare checks" % segment["id"])
        for segment in segments:
            domain.require(segment["status"] != "RESERVED",
                           "ERR_LEG_HAS_UNACCEPTED_SEGMENTS",
                           "segment %s is still RESERVED" % segment["id"])
        leg["status"] = "DEPARTED"
        for segment in segments:
            if segment["status"] != "ACCEPTED":
                continue
            animal = domain.animal_of_segment(segment)
            if animal["status"] == "TRAVEL_READY":
                animal["status"] = "IN_TRANSIT"
                touch(animal)
            reservation = domain.reservation_of_animal(animal)
            if reservation["booking_status"] in ("CONFIRMED", "HOLD_PARTIAL"):
                reservation["booking_status"] = "IN_TRANSIT"
                touch(reservation)
        domain.reconcile_leg(leg, force_touch=True)
        return object_response(serialize.dump("leg", leg))

    @register(app, "/flight-legs/<rid>/arrive", "POST", ACCEPTANCE, schema={},
              path_entity="leg")
    def arrive_leg(ctx):
        leg = ctx.row
        domain.require(leg["status"] == "DEPARTED", "ERR_FLIGHT_LEG_INVALID_STATE",
                       "only a DEPARTED leg can arrive")
        leg["status"] = "ARRIVED"
        reservations = []
        for segment in domain.segments_of_leg(leg):
            if segment["status"] != "ACCEPTED":
                continue
            animal = domain.animal_of_segment(segment)
            final = domain.final_segment(animal)
            segment["status"] = "COMPLETED"
            touch(segment)
            if final is not None and final["id"] == segment["id"] \
                    and animal["status"] == "IN_TRANSIT":
                animal["status"] = "DELIVERED"
                touch(animal)
            reservation = domain.reservation_of_animal(animal)
            if reservation["id"] not in [r["id"] for r in reservations]:
                reservations.append(reservation)
        for reservation in reservations:
            if reservation["booking_status"] != "IN_TRANSIT":
                continue
            animals = [a for a in domain.animals_of_reservation(reservation)
                       if a["status"] != "DENIED"]
            if animals and all(a["status"] == "DELIVERED" for a in animals):
                reservation["booking_status"] = "COMPLETED"
                touch(reservation)
                domain.run_charge_assembly(reservation)
        domain.reconcile_leg(leg, force_touch=True)
        return object_response(serialize.dump("leg", leg))
