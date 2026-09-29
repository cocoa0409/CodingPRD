"""Animal records: creation, amendment, screening, promotion and denial."""
from db import base_row, sorted_rows, store, touch
from errors import ApiError
from middleware import (ALL_ROLES, ROLE_ACCEPTANCE_AGENT, ROLE_RESERVATIONS_AGENT,
                        register, resolve_fk)
from response import created_response, object_response
from services import calc, domain, serialize
from routes.helpers import ANIMAL_KINDS, listing

AGENT = [ROLE_RESERVATIONS_AGENT]
ACCEPTANCE = [ROLE_ACCEPTANCE_AGENT]
BOTH_AGENTS = [ROLE_RESERVATIONS_AGENT, ROLE_ACCEPTANCE_AGENT]

ANIMAL_SCHEMA = {
    "reservation_id": {"type": "string", "required": True},
    "species_profile_id": {"type": "string", "required": True},
    "container_model_id": {"type": "string", "required": True},
    "animal_name": {"type": "string", "required": True, "min_length": 1},
    "breed_name": {"type": "string", "required": True, "min_length": 1},
    "animal_kind": {"type": "enum", "values": ANIMAL_KINDS},
    "declared_weight_kg": {"type": "number", "required": True, "gt": 0},
    "height_at_shoulder_cm": {"type": "number", "required": True, "gt": 0},
    "length_nose_to_tail_cm": {"type": "number", "required": True, "gt": 0},
    "age_weeks": {"type": "integer", "required": True, "gte": 0},
    "behavior_attestation_on_file": {"type": "boolean"},
}

AMEND_SCHEMA = {
    "container_model_id": {"type": "string"},
    "declared_weight_kg": {"type": "number", "gt": 0},
    "measured_weight_kg": {"type": "number", "nullable": True, "gt": 0},
    "behavior_attestation_on_file": {"type": "boolean"},
}

REASON_SCHEMA = {"reason": {"type": "string", "nullable": True}}


def init(app):
    @register(app, "/animal-records", "POST", AGENT, schema=ANIMAL_SCHEMA)
    def create_animal(ctx):
        body = ctx.body
        reservation = resolve_fk("reservation", body["reservation_id"])
        species = resolve_fk("species", body["species_profile_id"])
        container = resolve_fk("container", body["container_model_id"])
        domain.require(species["status"] == "ACTIVE", "ERR_SPECIES_RETIRED",
                       "the species profile is RETIRED")
        row = base_row()
        row.update({
            "reservation_id": reservation["id"],
            "species_profile_id": species["id"],
            "container_model_id": container["id"],
            "animal_name": body["animal_name"],
            "breed_name": body["breed_name"],
            "animal_kind": body.get("animal_kind", "PET"),
            "declared_weight_kg": body["declared_weight_kg"],
            "measured_weight_kg": None,
            "height_at_shoulder_cm": body["height_at_shoulder_cm"],
            "length_nose_to_tail_cm": body["length_nose_to_tail_cm"],
            "age_weeks": body["age_weeks"],
            "chargeable_weight_kg": 0,
            "container_compliance_state": "UNEVALUATED",
            "deficiency_codes": [],
            "behavior_attestation_on_file": body.get("behavior_attestation_on_file",
                                                     False),
            "status": "DRAFT",
        })
        store.animals[row["id"]] = row
        domain.recompute_animal_count(reservation)
        touch(reservation)
        return created_response(serialize.dump("animal", row))

    @register(app, "/animal-records/<rid>", "GET", ALL_ROLES, path_entity="animal")
    def get_animal(ctx):
        return object_response(serialize.dump("animal", ctx.row))

    @register(app, "/animal-records", "GET", ALL_ROLES, paginated=True)
    def list_animals(ctx):
        return listing("animal", sorted_rows(store.animals), ctx,
                       [("reservation_id", "reservation_id", "str"),
                        ("species_profile_id", "species_profile_id", "str"),
                        ("container_model_id", "container_model_id", "str"),
                        ("status", "status", "str")])

    @register(app, "/animal-records/<rid>", "PUT", BOTH_AGENTS, schema=AMEND_SCHEMA,
              path_entity="animal")
    def amend_animal(ctx):
        animal = ctx.row
        reset = False
        if ctx.has("container_model_id"):
            container = resolve_fk("container", ctx.body["container_model_id"])
            if container["id"] != animal["container_model_id"]:
                reset = True
            animal["container_model_id"] = container["id"]
        if ctx.has("declared_weight_kg"):
            if ctx.body["declared_weight_kg"] != animal["declared_weight_kg"]:
                reset = True
            animal["declared_weight_kg"] = ctx.body["declared_weight_kg"]
        if ctx.has("measured_weight_kg"):
            animal["measured_weight_kg"] = ctx.body["measured_weight_kg"]
        if ctx.has("behavior_attestation_on_file"):
            animal["behavior_attestation_on_file"] = \
                ctx.body["behavior_attestation_on_file"]
        if reset:
            animal["container_compliance_state"] = "UNEVALUATED"
            animal["deficiency_codes"] = []
        touch(animal)
        return object_response(serialize.dump("animal", animal))

    @register(app, "/animal-records/<rid>/screen", "POST", ACCEPTANCE, schema={},
              path_entity="animal")
    def screen_animal(ctx):
        animal = ctx.row
        domain.require(animal["status"] in ("DRAFT", "TRAVEL_READY"),
                       "ERR_ANIMAL_INVALID_STATE",
                       "a %s animal cannot be screened" % animal["status"])
        species = store.species[animal["species_profile_id"]]
        container = store.containers[animal["container_model_id"]]
        reservation = domain.reservation_of_animal(animal)
        domain.require(species["status"] == "ACTIVE", "ERR_SPECIES_RETIRED",
                       "the species profile is RETIRED")
        domain.require(species["acceptance_class"] != "EMBARGOED_SPECIES",
                       "ERR_SPECIES_NOT_ACCEPTED",
                       "the species acceptance class is EMBARGOED_SPECIES")
        restrictions = domain.active_breed_restrictions(animal)
        for restriction in restrictions:
            if restriction["restriction_type"] == "BANNED":
                raise ApiError("ERR_BREED_BANNED", "the breed is banned from carriage")
        domain.require(animal["age_weeks"] >= species["min_age_weeks"],
                       "ERR_ANIMAL_UNDERAGE",
                       "the animal is younger than the species minimum")
        cargo_only = species["acceptance_class"] == "CARGO_ONLY" or any(
            r["restriction_type"] == "CARGO_ONLY" for r in restrictions)
        if cargo_only:
            domain.require(reservation["routing_type"] == "CARGO",
                           "ERR_ROUTING_NOT_PERMITTED_FOR_BREED",
                           "the species or breed is restricted to CARGO routing")
        gross = calc.gross_weight_kg(animal["declared_weight_kg"], container)
        for restriction in restrictions:
            if restriction["restriction_type"] != "WEIGHT_CAPPED":
                continue
            if restriction["max_weight_kg"] is None:
                continue
            domain.require(gross <= calc.dec(restriction["max_weight_kg"]),
                           "ERR_BREED_WEIGHT_CAP_EXCEEDED",
                           "the gross weight exceeds the breed weight cap")
        domain.evaluate_container(animal)
        domain.apply_provisional_fees(animal)
        animal["status"] = "SCREENED"
        touch(animal)
        domain.run_charge_assembly(reservation)
        return object_response(serialize.dump("animal", animal))

    @register(app, "/animal-records/<rid>/mark-travel-ready", "POST", ACCEPTANCE,
              schema={}, path_entity="animal")
    def mark_travel_ready(ctx):
        animal = ctx.row
        domain.require(animal["status"] == "SCREENED", "ERR_ANIMAL_INVALID_STATE",
                       "a %s animal cannot be marked travel-ready" % animal["status"])
        domain.require(animal["container_compliance_state"] == "COMPLIANT",
                       "ERR_CONTAINER_NON_COMPLIANT",
                       "the container compliance state is %s"
                       % animal["container_compliance_state"])
        if animal["animal_kind"] == "SERVICE_ANIMAL":
            domain.require(animal["behavior_attestation_on_file"] is True,
                           "ERR_BEHAVIOR_ATTESTATION_MISSING",
                           "the behavior attestation is not on file")
        else:
            error_id, _ = domain.check_documents([animal])
            if error_id is not None:
                raise ApiError(error_id, "the destination document set is incomplete")
        slots = [s for s in domain.segments_of_animal(animal)
                 if s["status"] == "RESERVED" and s["sequence_index"] == 1]
        domain.require(bool(slots), "ERR_ANIMAL_INVALID_STATE",
                       "the animal holds no reserved slot at sequence_index 1")
        animal["status"] = "TRAVEL_READY"
        touch(animal)
        domain.recompute_animal_count(domain.reservation_of_animal(animal))
        return object_response(serialize.dump("animal", animal))

    @register(app, "/animal-records/<rid>/deny", "POST", ACCEPTANCE,
              schema=REASON_SCHEMA, path_entity="animal")
    def deny_animal(ctx):
        animal = ctx.row
        domain.require(animal["status"] in ("DRAFT", "SCREENED"),
                       "ERR_ANIMAL_INVALID_STATE",
                       "a %s animal cannot be denied" % animal["status"])
        animal["status"] = "DENIED"
        touch(animal)
        for segment in domain.segments_of_animal(animal):
            if segment["status"] == "RESERVED":
                domain.release_segment(segment, refund=False, recompute_booking=False)
        reservation = domain.reservation_of_animal(animal)
        before = reservation["animal_count"]
        domain.recompute_animal_count(reservation)
        if reservation["animal_count"] != before:
            touch(reservation)
        domain.run_charge_assembly(reservation)
        return object_response(serialize.dump("animal", animal))
