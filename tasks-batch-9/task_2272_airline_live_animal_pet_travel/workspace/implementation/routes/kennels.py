"""Kennel allocations and the irregular-operations care sweep."""
from db import base_row, parse_iso, sorted_rows, store, touch
from middleware import ALL_ROLES, ROLE_ACCEPTANCE_AGENT, register, resolve_fk
from response import created_response, object_response
from services import calc, domain, serialize
from routes.helpers import listing

ACCEPTANCE = [ROLE_ACCEPTANCE_AGENT]

ALLOCATION_SCHEMA = {
    "station_id": {"type": "string", "required": True},
    "animal_record_id": {"type": "string", "required": True},
    "bay_count": {"type": "integer", "required": True, "gte": 1},
    "occupancy_start_utc": {"type": "datetime", "required": True},
    "occupancy_end_utc": {"type": "datetime", "required": True},
    "feeding_interval_minutes": {"type": "integer", "required": True, "gte": 60,
                                 "lte": 720},
    "expected_station_version": {"type": "integer", "required": True, "gte": 1},
}

IROPS_SCHEMA = {"flight_leg_id": {"type": "string", "required": True}}

REASON_SCHEMA = {"reason": {"type": "string", "nullable": True}}


def init(app):
    @register(app, "/kennel-allocations", "POST", ACCEPTANCE, schema=ALLOCATION_SCHEMA)
    def create_allocation(ctx):
        body = ctx.body
        station = resolve_fk("station", body["station_id"])
        animal = resolve_fk("animal", body["animal_record_id"])
        domain.require(body["expected_station_version"] == station["version"],
                       "ERR_STALE_STATION_VERSION", "the station version has advanced")
        domain.require(animal["status"] in ("SCREENED", "TRAVEL_READY", "IN_TRANSIT"),
                       "ERR_ANIMAL_INVALID_STATE",
                       "a %s animal cannot hold kennel bays" % animal["status"])
        domain.require(station["status"] == "ACCEPTING", "ERR_STATION_SUSPENDED",
                       "the station is SUSPENDED")
        start = parse_iso(body["occupancy_start_utc"])
        end = parse_iso(body["occupancy_end_utc"])
        domain.require(end > start, "ERR_INVALID_TIME_RANGE",
                       "occupancy_end_utc must be strictly after occupancy_start_utc")
        projected = domain.projected_peak(station, body["bay_count"], start, end)
        domain.require(projected <= station["kennel_bay_count"],
                       "ERR_KENNEL_CAPACITY_EXCEEDED",
                       "the projected peak occupancy of %d bays exceeds the pool of %d"
                       % (projected, station["kennel_bay_count"]))
        row = base_row()
        row.update({
            "station_id": station["id"],
            "animal_record_id": animal["id"],
            "bay_count": body["bay_count"],
            "occupancy_start_utc": body["occupancy_start_utc"],
            "occupancy_end_utc": body["occupancy_end_utc"],
            "feeding_interval_minutes": body["feeding_interval_minutes"],
            "status": "RESERVED",
        })
        store.allocations[row["id"]] = row
        domain.recompute_reserved_bay_count(station)
        touch(station)
        return created_response(serialize.dump("allocation", row))

    @register(app, "/kennel-allocations/<rid>", "GET", ALL_ROLES, path_entity="allocation")
    def get_allocation(ctx):
        return object_response(serialize.dump("allocation", ctx.row))

    @register(app, "/kennel-allocations", "GET", ALL_ROLES, paginated=True)
    def list_allocations(ctx):
        return listing("allocation", sorted_rows(store.allocations), ctx,
                       [("station_id", "station_id", "str"),
                        ("animal_record_id", "animal_record_id", "str"),
                        ("status", "status", "str")])

    @register(app, "/kennel-allocations/<rid>/occupy", "POST", ACCEPTANCE, schema={},
              path_entity="allocation")
    def occupy_allocation(ctx):
        allocation = ctx.row
        domain.require(allocation["status"] == "RESERVED", "ERR_ALLOCATION_INVALID_STATE",
                       "a %s allocation cannot be occupied" % allocation["status"])
        domain.require(store.clock >= parse_iso(allocation["occupancy_start_utc"]),
                       "ERR_ALLOCATION_INVALID_STATE",
                       "the occupancy window has not opened yet")
        animal = store.animals[allocation["animal_record_id"]]
        domain.require(animal["status"] in ("TRAVEL_READY", "IN_TRANSIT"),
                       "ERR_ANIMAL_INVALID_STATE",
                       "a %s animal cannot occupy holding bays" % animal["status"])
        allocation["status"] = "OCCUPIED"
        touch(allocation)
        return object_response(serialize.dump("allocation", allocation))

    @register(app, "/kennel-allocations/<rid>/release", "POST", ACCEPTANCE,
              schema=REASON_SCHEMA, path_entity="allocation")
    def release_allocation(ctx):
        allocation = ctx.row
        domain.require(allocation["status"] in ("RESERVED", "OCCUPIED"),
                       "ERR_ALLOCATION_INVALID_STATE",
                       "a %s allocation cannot be released" % allocation["status"])
        domain.release_allocation(allocation)
        return object_response(serialize.dump("allocation", allocation))

    @register(app, "/irops-care-sweeps", "POST", ACCEPTANCE, schema=IROPS_SCHEMA)
    def irops_sweep(ctx):
        leg = resolve_fk("leg", ctx.body["flight_leg_id"])
        affected = []
        for segment in domain.segments_of_leg(leg):
            if segment["status"] not in ("RESERVED", "ACCEPTED"):
                continue
            animal = domain.animal_of_segment(segment)
            reservation = domain.reservation_of_animal(animal)
            entry = None
            for row in affected:
                if row[0]["id"] == reservation["id"]:
                    entry = row
                    break
            if entry is None:
                entry = (reservation, [])
                affected.append(entry)
            if animal["id"] not in entry[1]:
                entry[1].append(animal["id"])
        for reservation, animal_ids in affected:
            domain.require(reservation["booking_status"]
                           in ("PENDING", "CONFIRMED", "HOLD_PARTIAL", "IN_TRANSIT"),
                           "ERR_RESERVATION_INVALID_STATE",
                           "a %s reservation cannot take a care sweep"
                           % reservation["booking_status"])
        domain.require(leg["status"] in ("SCHEDULED", "DELAYED", "DEPARTED"),
                       "ERR_FLIGHT_LEG_INVALID_STATE",
                       "a %s leg cannot take a care sweep" % leg["status"])
        total_animals = 0
        for reservation, animal_ids in affected:
            total_animals += len(animal_ids)
            reservation["irops_fee_total"] += \
                calc.IROPS_CARE_FEE_PER_ANIMAL * len(animal_ids)
            touch(reservation)
            domain.run_charge_assembly(reservation)
        return object_response({
            "flight_leg_id": leg["id"],
            "affected_animal_count": total_animals,
            "irops_fee_per_animal": calc.IROPS_CARE_FEE_PER_ANIMAL,
            "total_fee_charged": calc.IROPS_CARE_FEE_PER_ANIMAL * total_animals,
        })
