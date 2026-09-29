"""Segment assignments (routing slots) and their welfare check event log."""
from db import base_row, parse_iso, sorted_rows, store, touch
from errors import ApiError
from middleware import (ALL_ROLES, ROLE_ACCEPTANCE_AGENT, ROLE_RESERVATIONS_AGENT,
                        register, resolve_fk)
from response import created_response, object_response
from services import calc, domain, serialize
from routes.helpers import CHECK_OUTCOMES, CHECK_TYPES, ROUTING_TYPES, listing

AGENT = [ROLE_RESERVATIONS_AGENT]
ACCEPTANCE = [ROLE_ACCEPTANCE_AGENT]

SEGMENT_SCHEMA = {
    "animal_record_id": {"type": "string", "required": True},
    "flight_leg_id": {"type": "string", "required": True},
    "routing_type": {"type": "enum", "required": True, "values": ROUTING_TYPES},
    "sequence_index": {"type": "integer", "required": True, "gte": 1},
    "expected_flight_leg_version": {"type": "integer", "required": True, "gte": 1},
}

WELFARE_SCHEMA = {
    "segment_assignment_id": {"type": "string", "required": True},
    "check_type": {"type": "enum", "required": True, "values": CHECK_TYPES},
    "outcome": {"type": "enum", "values": CHECK_OUTCOMES},
    "notes": {"type": "string", "nullable": True},
}

REASON_SCHEMA = {"reason": {"type": "string", "nullable": True}}


def _embargo_blocks(leg, routing_type):
    if leg["posture"] != "EMBARGOED" or leg["governing_embargo_rule_id"] is None:
        return False
    rule = store.embargo_rules.get(leg["governing_embargo_rule_id"])
    if rule is None:
        return False
    return routing_type in rule["applies_to_routings"]


def init(app):
    @register(app, "/segment-assignments", "POST", AGENT, schema=SEGMENT_SCHEMA)
    def create_segment(ctx):
        body = ctx.body
        animal = resolve_fk("animal", body["animal_record_id"])
        leg = resolve_fk("leg", body["flight_leg_id"])
        routing = body["routing_type"]
        sequence = body["sequence_index"]
        domain.require(body["expected_flight_leg_version"] == leg["version"],
                       "ERR_STALE_FLIGHT_LEG_VERSION",
                       "the flight leg version has advanced")
        domain.require(leg["status"] in ("SCHEDULED", "DELAYED"),
                       "ERR_FLIGHT_LEG_INVALID_STATE",
                       "a %s leg cannot take a new routing slot" % leg["status"])
        domain.require(animal["status"] in ("DRAFT", "SCREENED", "TRAVEL_READY"),
                       "ERR_ANIMAL_INVALID_STATE",
                       "a %s animal cannot take a routing slot" % animal["status"])
        domain.require(not _embargo_blocks(leg, routing), "ERR_LEG_EMBARGOED",
                       "the leg embargoes %s carriage" % routing)
        origin = store.stations[leg["origin_station_id"]]
        destination = store.stations[leg["destination_station_id"]]
        domain.require(origin["status"] == "ACCEPTING" and
                       destination["status"] == "ACCEPTING",
                       "ERR_STATION_SUSPENDED",
                       "a station on this leg is SUSPENDED")
        reservation = domain.reservation_of_animal(animal)
        domain.require(routing == reservation["routing_type"], "ERR_ROUTING_MISMATCH",
                       "the reservation routing_type is %s" % reservation["routing_type"])
        live = [s for s in domain.segments_of_animal(animal) if s["status"] != "RELEASED"]
        taken = [s["sequence_index"] for s in live]
        if not live:
            domain.require(sequence == 1, "ERR_SEGMENT_SEQUENCE_INVALID",
                           "the first routing slot must carry sequence_index 1")
        else:
            domain.require(sequence not in taken, "ERR_SEGMENT_SEQUENCE_INVALID",
                           "sequence_index %s is already taken" % sequence)
            domain.require(sequence == max(taken) + 1, "ERR_SEGMENT_SEQUENCE_INVALID",
                           "sequence_index must be exactly one greater than %s"
                           % max(taken))
        start = parse_iso(leg["scheduled_departure_utc"])
        end = parse_iso(leg["scheduled_arrival_utc"])
        for other in live:
            other_leg = domain.leg_of_segment(other)
            other_start = parse_iso(other_leg["scheduled_departure_utc"])
            other_end = parse_iso(other_leg["scheduled_arrival_utc"])
            if other_start <= end and start <= other_end:
                raise ApiError("ERR_ANIMAL_ITINERARY_OVERLAP",
                               "the requested leg overlaps an existing routing slot")
        minutes, required_checks = domain.connection_window(animal, sequence, routing, leg)
        if sequence > 1 and minutes is not None:
            domain.require(minutes >= calc.CONNECTION_MINIMUM[routing],
                           "ERR_CONNECTION_BELOW_MINIMUM",
                           "the connection is shorter than the %s minimum" % routing)
            domain.require(minutes <= calc.CONNECTION_MAXIMUM_MINUTES,
                           "ERR_CONNECTION_EXCEEDS_MAXIMUM",
                           "the connection exceeds %d minutes"
                           % calc.CONNECTION_MAXIMUM_MINUTES)
        booked = leg[domain.BOOKED_FIELD[routing]]
        limit = leg[domain.LIMIT_FIELD[routing]]
        domain.require(booked + 1 <= limit, "ERR_ROUTING_LIMIT_REACHED",
                       "the %s limit on this leg is reached" % routing)
        row = base_row()
        row.update({
            "animal_record_id": animal["id"],
            "flight_leg_id": leg["id"],
            "routing_type": routing,
            "sequence_index": sequence,
            "connection_minutes": minutes,
            "required_welfare_check_count": required_checks,
            "completed_welfare_check_count": 0,
            "segment_fee_amount": domain.provisional_fee_for_segment(animal, routing, leg),
            "fee_variant": "PROVISIONAL_AT_RESERVATION",
            "status": "RESERVED",
        })
        store.segments[row["id"]] = row
        domain.reconcile_leg(leg, force_touch=True)
        domain.run_charge_assembly(reservation)
        return created_response(serialize.dump("segment", row))

    @register(app, "/segment-assignments/<rid>", "GET", ALL_ROLES, path_entity="segment")
    def get_segment(ctx):
        return object_response(serialize.dump("segment", ctx.row))

    @register(app, "/segment-assignments", "GET", ALL_ROLES, paginated=True)
    def list_segments(ctx):
        return listing("segment", sorted_rows(store.segments), ctx,
                       [("animal_record_id", "animal_record_id", "str"),
                        ("flight_leg_id", "flight_leg_id", "str"),
                        ("status", "status", "str")])

    @register(app, "/segment-assignments/<rid>/accept", "POST", ACCEPTANCE, schema={},
              path_entity="segment")
    def accept_segment(ctx):
        segment = ctx.row
        animal = domain.animal_of_segment(segment)
        reservation = domain.reservation_of_animal(animal)
        leg = domain.leg_of_segment(segment)
        domain.require(ctx.user_id != reservation["booked_by_agent_id"],
                       "ERR_SEGREGATION_OF_DUTIES",
                       "the booking agent may not accept the animal at the counter")
        domain.require(reservation["booking_status"] in ("CONFIRMED", "HOLD_PARTIAL"),
                       "ERR_RESERVATION_INVALID_STATE",
                       "a %s reservation cannot be accepted"
                       % reservation["booking_status"])
        domain.require(animal["status"] == "TRAVEL_READY", "ERR_ANIMAL_INVALID_STATE",
                       "a %s animal cannot be accepted" % animal["status"])
        domain.require(segment["status"] == "RESERVED", "ERR_SEGMENT_INVALID_STATE",
                       "a %s routing slot cannot be accepted" % segment["status"])
        container = store.containers[animal["container_model_id"]]
        species = store.species[animal["species_profile_id"]]
        if animal["measured_weight_kg"] is not None:
            gross = calc.gross_weight_kg(animal["measured_weight_kg"], container)
            for restriction in domain.active_breed_restrictions(animal):
                if restriction["restriction_type"] != "WEIGHT_CAPPED":
                    continue
                if restriction["max_weight_kg"] is None:
                    continue
                domain.require(gross <= calc.dec(restriction["max_weight_kg"]),
                               "ERR_BREED_WEIGHT_CAP_EXCEEDED",
                               "the gross weight exceeds the breed weight cap")
            if reservation["routing_type"] == "CABIN":
                domain.require(gross <= calc.dec(species["max_cabin_weight_kg"]),
                               "ERR_CABIN_WEIGHT_EXCEEDED",
                               "the gross weight exceeds the cabin ceiling")
        domain.require(animal["container_compliance_state"] == "COMPLIANT",
                       "ERR_CONTAINER_NON_COMPLIANT",
                       "the container compliance state is %s"
                       % animal["container_compliance_state"])
        domain.require(not _embargo_blocks(leg, segment["routing_type"]),
                       "ERR_LEG_EMBARGOED",
                       "the leg embargoes %s carriage" % segment["routing_type"])
        domain.require(animal["measured_weight_kg"] is not None,
                       "ERR_MEASURED_WEIGHT_REQUIRED",
                       "measured_weight_kg is not recorded on the animal")
        domain.require(reservation["compliance_status"] == "VERIFIED",
                       "ERR_COMPLIANCE_NOT_VERIFIED",
                       "the compliance dimension is %s"
                       % reservation["compliance_status"])
        domain.require(leg["status"] in ("SCHEDULED", "DELAYED"),
                       "ERR_FLIGHT_LEG_INVALID_STATE",
                       "a %s leg cannot accept an animal" % leg["status"])
        segment["status"] = "ACCEPTED"
        domain.apply_final_fee(animal, segment)
        touch(segment)
        domain.run_charge_assembly(reservation)
        return object_response(serialize.dump("segment", segment))

    @register(app, "/segment-assignments/<rid>/release", "POST", AGENT,
              schema=REASON_SCHEMA, path_entity="segment")
    def release_slot(ctx):
        segment = ctx.row
        domain.require(segment["status"] == "RESERVED", "ERR_SEGMENT_INVALID_STATE",
                       "a %s routing slot cannot be released" % segment["status"])
        domain.release_segment(segment)
        return object_response(serialize.dump("segment", segment))

    @register(app, "/segment-assignments/<rid>/offload", "POST", ACCEPTANCE,
              schema=REASON_SCHEMA, path_entity="segment")
    def offload_slot(ctx):
        segment = ctx.row
        domain.require(segment["status"] == "ACCEPTED", "ERR_SEGMENT_INVALID_STATE",
                       "a %s routing slot cannot be offloaded" % segment["status"])
        domain.offload_segment(segment)
        return object_response(serialize.dump("segment", segment))

    @register(app, "/welfare-checks", "POST", ACCEPTANCE, schema=WELFARE_SCHEMA)
    def create_welfare_check(ctx):
        body = ctx.body
        segment = resolve_fk("segment", body["segment_assignment_id"])
        domain.require(segment["status"] in ("RESERVED", "ACCEPTED"),
                       "ERR_SEGMENT_INVALID_STATE",
                       "a %s routing slot cannot take a welfare check"
                       % segment["status"])
        row = base_row(versioned=False)
        row.update({
            "segment_assignment_id": segment["id"],
            "check_type": body["check_type"],
            "recorded_at_utc": domain.clock_iso(),
            "performed_by_user_id": ctx.user_id,
            "outcome": body.get("outcome", "NORMAL"),
            "notes": body.get("notes"),
        })
        store.welfare_checks[row["id"]] = row
        domain.recompute_completed_welfare_checks(segment)
        touch(segment)
        return created_response(serialize.dump("welfare_check", row))

    @register(app, "/segment-assignments/<rid>/welfare-checks", "GET", ALL_ROLES,
              paginated=True, path_entity="segment")
    def list_welfare_checks(ctx):
        rows = domain.welfare_checks_of_segment(ctx.row)
        return listing("welfare_check", rows, ctx,
                       [("check_type", "check_type", "str")])
