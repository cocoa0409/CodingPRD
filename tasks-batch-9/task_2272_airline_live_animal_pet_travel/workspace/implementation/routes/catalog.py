"""Program configuration: species profiles, breed restrictions, destination
requirements, container models, stations and temperature embargo rules."""
from db import base_row, sorted_rows, store, touch
from errors import ApiError
from middleware import (ALL_ROLES, ROLE_PROGRAM_ADMIN, register, resolve_fk)
from response import created_response, object_response
from services import domain, serialize
from routes.helpers import (ACCEPTANCE_CLASSES, BREED_STATUSES, CONFIG_STATUSES,
                            COUNTRY_PATTERN, DIRECTIONS, DOCUMENT_TYPES, IATA_PATTERN,
                            MONTH_DAY_PATTERN, RESTRICTION_TYPES, ROUTING_TYPES,
                            SPECIES_CODE_PATTERN, SPECIES_STATUSES, STATION_STATUSES,
                            listing)

ADMIN = [ROLE_PROGRAM_ADMIN]

SPECIES_SCHEMA = {
    "species_code": {"type": "string", "required": True, "pattern": SPECIES_CODE_PATTERN},
    "common_name": {"type": "string", "required": True, "min_length": 1},
    "acceptance_class": {"type": "enum", "required": True, "values": ACCEPTANCE_CLASSES},
    "max_cabin_weight_kg": {"type": "number", "required": True, "gte": 0, "lte": 50},
    "min_age_weeks": {"type": "integer", "required": True, "gte": 0},
    "requires_veterinary_review": {"type": "boolean"},
    "status": {"type": "enum", "values": SPECIES_STATUSES},
}

BREED_SCHEMA = {
    "species_profile_id": {"type": "string", "required": True},
    "breed_name": {"type": "string", "required": True, "min_length": 1, "max_length": 60},
    "restriction_type": {"type": "enum", "required": True, "values": RESTRICTION_TYPES},
    "max_weight_kg": {"type": "number", "nullable": True, "gt": 0},
}

DEST_REQ_SCHEMA = {
    "species_profile_id": {"type": "string", "required": True},
    "destination_country_code": {"type": "string", "required": True,
                                 "pattern": COUNTRY_PATTERN},
    "document_type": {"type": "enum", "required": True, "values": DOCUMENT_TYPES},
    "max_age_days_at_arrival": {"type": "integer", "required": True, "gte": 1},
    "mandatory": {"type": "boolean"},
}

CONTAINER_SCHEMA = {
    "model_code": {"type": "string", "required": True, "min_length": 2, "max_length": 24},
    "interior_length_cm": {"type": "number", "required": True, "gt": 0},
    "interior_width_cm": {"type": "number", "required": True, "gt": 0},
    "interior_height_cm": {"type": "number", "required": True, "gt": 0},
    "tare_weight_kg": {"type": "number", "required": True, "gte": 0},
    "ventilation_area_pct": {"type": "number", "required": True, "gte": 0, "lte": 100},
    "ventilated_side_count": {"type": "integer", "required": True, "gte": 0, "lte": 4},
    "wheels_removable": {"type": "boolean", "required": True},
    "cabin_eligible": {"type": "boolean", "required": True},
}

STATION_SCHEMA = {
    "iata_code": {"type": "string", "required": True, "pattern": IATA_PATTERN},
    "country_code": {"type": "string", "required": True, "pattern": COUNTRY_PATTERN},
    "kennel_bay_count": {"type": "integer", "required": True, "gte": 0},
    "status": {"type": "enum", "values": STATION_STATUSES},
}

EMBARGO_SCHEMA = {
    "station_id": {"type": "string", "required": True},
    "direction": {"type": "enum", "required": True, "values": DIRECTIONS},
    "season_start_month_day": {"type": "string", "required": True,
                               "pattern": MONTH_DAY_PATTERN},
    "season_end_month_day": {"type": "string", "required": True,
                             "pattern": MONTH_DAY_PATTERN},
    "forecast_high_limit_c": {"type": "number", "required": True},
    "forecast_low_limit_c": {"type": "number", "required": True},
    "applies_to_routings": {"type": "array", "required": True, "min_items": 1,
                            "items": {"type": "enum", "values": ROUTING_TYPES}},
}


def init(app):
    # ---------------- species profiles ----------------
    @register(app, "/species-profiles", "POST", ADMIN, schema=SPECIES_SCHEMA)
    def create_species(ctx):
        body = ctx.body
        for row in store.species.values():
            if row["species_code"] == body["species_code"]:
                raise ApiError("ERR_DUPLICATE_SPECIES_CODE",
                               "species_code already registered")
        row = base_row()
        row.update({
            "species_code": body["species_code"],
            "common_name": body["common_name"],
            "acceptance_class": body["acceptance_class"],
            "max_cabin_weight_kg": body["max_cabin_weight_kg"],
            "min_age_weeks": body["min_age_weeks"],
            "requires_veterinary_review": body.get("requires_veterinary_review", False),
            "breed_restriction_count": 0,
            "status": body.get("status", "ACTIVE"),
        })
        store.species[row["id"]] = row
        return created_response(serialize.dump("species", row))

    @register(app, "/species-profiles/<rid>", "GET", ALL_ROLES, path_entity="species")
    def get_species(ctx):
        return object_response(serialize.dump("species", ctx.row))

    @register(app, "/species-profiles", "GET", ALL_ROLES, paginated=True)
    def list_species(ctx):
        return listing("species", sorted_rows(store.species), ctx,
                       [("status", "status", "str")])

    @register(app, "/species-profiles/<rid>/status", "PUT", ADMIN,
              schema={"status": {"type": "enum", "required": True,
                                 "values": SPECIES_STATUSES}},
              path_entity="species")
    def set_species_status(ctx):
        ctx.row["status"] = ctx.body["status"]
        touch(ctx.row)
        return object_response(serialize.dump("species", ctx.row))

    # ---------------- breed restrictions ----------------
    @register(app, "/breed-restrictions", "POST", ADMIN, schema=BREED_SCHEMA)
    def create_breed(ctx):
        body = ctx.body
        species = resolve_fk("species", body["species_profile_id"])
        lowered = body["breed_name"].lower()
        for row in store.breeds.values():
            if row["species_profile_id"] == species["id"] and row["status"] == "ACTIVE" \
                    and row["breed_name"].lower() == lowered:
                raise ApiError("ERR_DUPLICATE_BREED_RESTRICTION",
                               "an active restriction already covers this breed")
        supplied = body.get("max_weight_kg") is not None
        if supplied != (body["restriction_type"] == "WEIGHT_CAPPED"):
            raise ApiError("ERR_DUPLICATE_BREED_RESTRICTION",
                           "max_weight_kg is supplied exactly when restriction_type is "
                           "WEIGHT_CAPPED")
        row = base_row()
        row.update({
            "species_profile_id": species["id"],
            "breed_name": body["breed_name"],
            "restriction_type": body["restriction_type"],
            "max_weight_kg": body.get("max_weight_kg"),
            "status": "ACTIVE",
        })
        store.breeds[row["id"]] = row
        domain.recompute_breed_restriction_count(species)
        touch(species)
        return created_response(serialize.dump("breed", row))

    @register(app, "/species-profiles/<rid>/breed-restrictions", "GET", ALL_ROLES,
              paginated=True, path_entity="species")
    def list_species_breeds(ctx):
        rows = [r for r in sorted_rows(store.breeds)
                if r["species_profile_id"] == ctx.row["id"]]
        return listing("breed", rows, ctx, [("status", "status", "str")])

    @register(app, "/breed-restrictions/<rid>", "GET", ALL_ROLES, path_entity="breed")
    def get_breed(ctx):
        return object_response(serialize.dump("breed", ctx.row))

    @register(app, "/breed-restrictions/<rid>/status", "PUT", ADMIN,
              schema={"status": {"type": "enum", "required": True,
                                 "values": BREED_STATUSES}},
              path_entity="breed")
    def set_breed_status(ctx):
        ctx.row["status"] = ctx.body["status"]
        touch(ctx.row)
        species = store.species.get(ctx.row["species_profile_id"])
        if species is not None:
            domain.recompute_breed_restriction_count(species)
            touch(species)
        return object_response(serialize.dump("breed", ctx.row))

    # ---------------- destination requirements ----------------
    @register(app, "/destination-requirements", "POST", ADMIN, schema=DEST_REQ_SCHEMA)
    def create_dest_req(ctx):
        body = ctx.body
        species = resolve_fk("species", body["species_profile_id"])
        row = base_row()
        row.update({
            "species_profile_id": species["id"],
            "destination_country_code": body["destination_country_code"],
            "document_type": body["document_type"],
            "max_age_days_at_arrival": body["max_age_days_at_arrival"],
            "mandatory": body.get("mandatory", True),
            "status": "ACTIVE",
        })
        store.dest_reqs[row["id"]] = row
        return created_response(serialize.dump("dest_req", row))

    @register(app, "/species-profiles/<rid>/destination-requirements", "GET", ALL_ROLES,
              paginated=True, path_entity="species")
    def list_species_dest_reqs(ctx):
        rows = [r for r in sorted_rows(store.dest_reqs)
                if r["species_profile_id"] == ctx.row["id"]]
        return listing("dest_req", rows, ctx,
                       [("destination_country_code", "destination_country_code", "str"),
                        ("status", "status", "str")])

    @register(app, "/destination-requirements/<rid>", "GET", ALL_ROLES,
              path_entity="dest_req")
    def get_dest_req(ctx):
        return object_response(serialize.dump("dest_req", ctx.row))

    # ---------------- container models ----------------
    @register(app, "/container-models", "POST", ADMIN, schema=CONTAINER_SCHEMA)
    def create_container(ctx):
        body = ctx.body
        for row in store.containers.values():
            if row["model_code"] == body["model_code"]:
                raise ApiError("ERR_DUPLICATE_CONTAINER_MODEL",
                               "model_code already registered")
        row = base_row()
        for field in ("model_code", "interior_length_cm", "interior_width_cm",
                      "interior_height_cm", "tare_weight_kg", "ventilation_area_pct",
                      "ventilated_side_count", "wheels_removable", "cabin_eligible"):
            row[field] = body[field]
        store.containers[row["id"]] = row
        return created_response(serialize.dump("container", row))

    @register(app, "/container-models/<rid>", "GET", ALL_ROLES, path_entity="container")
    def get_container(ctx):
        return object_response(serialize.dump("container", ctx.row))

    @register(app, "/container-models", "GET", ALL_ROLES, paginated=True)
    def list_containers(ctx):
        return listing("container", sorted_rows(store.containers), ctx,
                       [("cabin_eligible", "cabin_eligible", "bool")])

    # ---------------- stations ----------------
    @register(app, "/stations", "POST", ADMIN, schema=STATION_SCHEMA)
    def create_station(ctx):
        body = ctx.body
        for row in store.stations.values():
            if row["iata_code"] == body["iata_code"]:
                raise ApiError("ERR_DUPLICATE_STATION_CODE", "iata_code already registered")
        row = base_row()
        row.update({
            "iata_code": body["iata_code"],
            "country_code": body["country_code"],
            "kennel_bay_count": body["kennel_bay_count"],
            "reserved_bay_count": 0,
            "status": body.get("status", "ACCEPTING"),
        })
        store.stations[row["id"]] = row
        return created_response(serialize.dump("station", row))

    @register(app, "/stations/<rid>", "GET", ALL_ROLES, path_entity="station")
    def get_station(ctx):
        return object_response(serialize.dump("station", ctx.row))

    @register(app, "/stations", "GET", ALL_ROLES, paginated=True)
    def list_stations(ctx):
        return listing("station", sorted_rows(store.stations), ctx,
                       [("status", "status", "str")])

    @register(app, "/stations/<rid>/status", "PUT", ADMIN,
              schema={"status": {"type": "enum", "required": True,
                                 "values": STATION_STATUSES}},
              path_entity="station")
    def set_station_status(ctx):
        ctx.row["status"] = ctx.body["status"]
        touch(ctx.row)
        return object_response(serialize.dump("station", ctx.row))

    # ---------------- temperature embargo rules ----------------
    @register(app, "/temperature-embargo-rules", "POST", ADMIN, schema=EMBARGO_SCHEMA)
    def create_embargo_rule(ctx):
        body = ctx.body
        station = resolve_fk("station", body["station_id"])
        row = base_row()
        row.update({
            "station_id": station["id"],
            "direction": body["direction"],
            "season_start_month_day": body["season_start_month_day"],
            "season_end_month_day": body["season_end_month_day"],
            "forecast_high_limit_c": body["forecast_high_limit_c"],
            "forecast_low_limit_c": body["forecast_low_limit_c"],
            "applies_to_routings": list(body["applies_to_routings"]),
            "status": "ACTIVE",
        })
        store.embargo_rules[row["id"]] = row
        touch(station)
        return created_response(serialize.dump("embargo_rule", row))

    @register(app, "/stations/<rid>/temperature-embargo-rules", "GET", ALL_ROLES,
              paginated=True, path_entity="station")
    def list_station_embargo_rules(ctx):
        rows = [r for r in sorted_rows(store.embargo_rules)
                if r["station_id"] == ctx.row["id"]]
        return listing("embargo_rule", rows, ctx,
                       [("direction", "direction", "str"), ("status", "status", "str")])

    @register(app, "/temperature-embargo-rules/<rid>", "GET", ALL_ROLES,
              path_entity="embargo_rule")
    def get_embargo_rule(ctx):
        return object_response(serialize.dump("embargo_rule", ctx.row))

    @register(app, "/temperature-embargo-rules/<rid>/status", "PUT", ADMIN,
              schema={"status": {"type": "enum", "required": True,
                                 "values": CONFIG_STATUSES}},
              path_entity="embargo_rule")
    def set_embargo_rule_status(ctx):
        ctx.row["status"] = ctx.body["status"]
        touch(ctx.row)
        station = store.stations.get(ctx.row["station_id"])
        if station is not None:
            touch(station)
        return object_response(serialize.dump("embargo_rule", ctx.row))
