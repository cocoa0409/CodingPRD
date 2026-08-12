"""Animals, their placement restrictions, identification, the eligibility view,
and litters."""

from flask import Blueprint, request

import auth
import clock
import derive
import envelope
import gates
from errors import ApiError
from routing import listing, must, must_fk, query_filters
from store import DB, touch
from validation import Field, parse_body

bp = Blueprint("animals", __name__)

READ_ANIMAL_ROLES = ["PlatformAdmin", "IntakeOfficer", "FosterCoordinator", "AdoptionCounselor",
                     "TransportDispatcher", "Veterinarian", "FinanceOfficer", "Driver",
                     "FosterParent", "Adopter", "PartnerRescue"]


@bp.post("/rescue/animals")
def create_animal():
    auth.authenticate(["PlatformAdmin", "IntakeOfficer"])
    body = parse_body(request, [
        Field("name", "string", required=True),
        Field("species", "string", required=True, enum="species"),
        Field("size_class", "string", required=True, enum="size_class"),
        Field("weight_lb", "number", required=True, fmt="gt0"),
        Field("date_of_birth", "datetime", required=True),
        Field("current_organization_id", "string", required=True),
        Field("temperament", "string", default="UNKNOWN", enum="temperament"),
        Field("microchip_id", "string", default=None),
        Field("litter_id", "string", default=None),
        Field("restriction_no_children_under_years", "integer", default=0, fmt="gte0"),
        Field("restriction_no_cats", "boolean", default=False),
        Field("restriction_no_dogs", "boolean", default=False),
        Field("restriction_requires_fenced_yard", "boolean", default=False),
        Field("restriction_housing_types_excluded", "array", default=None,
              elem_enum="housing_type"),
    ])
    # Rung 11: body foreign keys, in the order the endpoint lists them.
    must("Organization", body["current_organization_id"])
    must_fk("Litter", body["litter_id"])
    gates.check_gate1(body["current_organization_id"])

    animal = DB.insert("Animal", {
        "name": body["name"],
        "species": body["species"],
        "size_class": body["size_class"],
        "weight_lb": body["weight_lb"],
        "date_of_birth": body["date_of_birth"],      # (b) echoed byte-verbatim
        "temperament": body["temperament"],
        "microchip_id": body["microchip_id"],
        "identifiable": body["microchip_id"] is not None,
        "litter_id": body["litter_id"],
        "current_organization_id": body["current_organization_id"],
        "current_foster_home_id": None,
        "current_intake_record_id": None,
        "lifecycle_status": "PRE_INTAKE",
        "alteration_status": "NOT_ALTERED",
        "rabies_vaccinated_at": None,
        "restriction_no_children_under_years": body["restriction_no_children_under_years"],
        "restriction_no_cats": body["restriction_no_cats"],
        "restriction_no_dogs": body["restriction_no_dogs"],
        "restriction_requires_fenced_yard": body["restriction_requires_fenced_yard"],
        "restriction_housing_types_excluded": body["restriction_housing_types_excluded"] or [],
        "current_hub_code": None,
    })
    # Litter.member_count is "count of Animal rows whose litter_id is this
    # litter", so registering a littermate raises it by derivation.
    return envelope.created(derive.animal(animal))


@bp.get("/rescue/animals/<animal_id>")
def read_animal(animal_id):
    auth.authenticate(READ_ANIMAL_ROLES)
    return envelope.ok(derive.animal(must("Animal", animal_id)))


@bp.get("/rescue/animals")
def list_animals():
    auth.authenticate(["PlatformAdmin", "IntakeOfficer", "FosterCoordinator",
                       "AdoptionCounselor", "TransportDispatcher", "Veterinarian"])
    filters = query_filters(["species", "lifecycle_status", "litter_id",
                             "current_organization_id", "current_foster_home_id",
                             "current_intake_record_id"])
    return listing("Animal", DB.all("Animal"), filters)


@bp.patch("/rescue/animals/<animal_id>/restrictions")
def update_restrictions(animal_id):
    auth.authenticate(["PlatformAdmin", "IntakeOfficer", "AdoptionCounselor"])
    body = parse_body(request, [
        Field("restriction_no_children_under_years", "integer", fmt="gte0"),
        Field("restriction_no_cats", "boolean"),
        Field("restriction_no_dogs", "boolean"),
        Field("restriction_requires_fenced_yard", "boolean"),
        Field("restriction_housing_types_excluded", "array", elem_enum="housing_type"),
    ])
    animal = must("Animal", animal_id)
    gates.run_gates(gates.gate1_org_id(animal=animal), animal=animal, gate2=True)

    for field in ("restriction_no_children_under_years", "restriction_no_cats",
                  "restriction_no_dogs", "restriction_requires_fenced_yard",
                  "restriction_housing_types_excluded"):
        if field in body["_supplied"]:
            animal[field] = body[field]
    touch(animal)
    return envelope.ok(derive.animal(animal))


@bp.post("/rescue/animals/<animal_id>/identification")
def record_identification(animal_id):
    auth.authenticate(["PlatformAdmin", "IntakeOfficer"])
    body = parse_body(request, [
        Field("microchip_id", "string", required=True),
        Field("extend_stray_hold", "boolean", required=True),
    ])
    animal = must("Animal", animal_id)
    gates.run_gates(gates.gate1_org_id(animal=animal), animal=animal, gate2=True)

    # Rung 18 deliberately EXCLUDES this endpoint (PRD 2.5): its hold-axis
    # precondition is evaluated at rung 21 instead, so that
    # ERR_HOLD_ALREADY_EXPIRED can actually be observed.
    if body["extend_stray_hold"]:
        episode = derive.current_episode(animal) or derive.open_episode(animal)
        if episode is None:
            # PRD 2.11: ERR_INTAKE_RECORD_NOT_FOUND "is also the code used when
            # an operation requires the animal's currently open custody episode
            # and no such episode exists".
            raise ApiError("ERR_INTAKE_RECORD_NOT_FOUND",
                           "The animal has no currently open custody episode.")
        # Rung 21: the monotone latch.
        if episode["hold_status"] == "HOLD_EXPIRED":
            raise ApiError("ERR_HOLD_ALREADY_EXPIRED",
                           "The stray hold has already expired; the hold clock is not moved.")

    animal["microchip_id"] = body["microchip_id"]
    animal["identifiable"] = True
    touch(animal)

    if body["extend_stray_hold"]:
        episode = derive.current_episode(animal) or derive.open_episode(animal)
        # PRD 3.2: the extension "is only meaningful on a STRAY episode whose
        # identifiable_at_intake is still false".
        if episode["intake_type"] == "STRAY" and not episode["identifiable_at_intake"]:
            import calc
            episode["identifiable_at_intake"] = True
            episode["hold_days"] = calc.STRAY_HOLD_STRAY_IDENTIFIABLE_DAYS
            # (c) derived instant, rendered in the style of intake_datetime
            episode["hold_expires_at"] = clock.derive(
                clock.plus_days(clock.parse(episode["intake_datetime"]), episode["hold_days"]),
                episode["intake_datetime"])
            touch(episode)
    return envelope.ok(derive.animal(animal))


@bp.get("/rescue/animals/<animal_id>/eligibility")
def animal_eligibility(animal_id):
    auth.authenticate(["PlatformAdmin", "IntakeOfficer", "FosterCoordinator",
                       "AdoptionCounselor", "TransportDispatcher"])
    animal = must("Animal", animal_id)
    episode = derive.current_episode(animal)
    out = {
        "animal_id": animal["id"],
        "lifecycle_status": animal["lifecycle_status"],
        "stray_hold_status": episode["hold_status"] if episode else None,
        "stray_hold_expires_at": episode["hold_expires_at"] if episode else None,
    }
    out.update(gates.blocked_by(animal))
    return envelope.ok(out)


# =====================================================================
#  Litters
# =====================================================================

@bp.post("/rescue/litters")
def create_litter():
    auth.authenticate(["PlatformAdmin", "IntakeOfficer"])
    body = parse_body(request, [
        Field("label", "string", required=True),
        Field("dam_animal_id", "string", default=None),
    ])
    must_fk("Animal", body["dam_animal_id"])
    # Gate 1: a Litter carries no organization-bearing field, so it is ungated.
    litter = DB.insert("Litter", {
        "label": body["label"],
        "dam_animal_id": body["dam_animal_id"],
        "transport_basis": "GROUPED",
        "split_approved_at": None,
    })
    return envelope.created(derive.litter(litter))


@bp.get("/rescue/litters/<litter_id>")
def read_litter(litter_id):
    auth.authenticate(["PlatformAdmin", "IntakeOfficer", "TransportDispatcher", "FosterCoordinator"])
    return envelope.ok(derive.litter(must("Litter", litter_id)))


@bp.get("/rescue/litters")
def list_litters():
    auth.authenticate(["PlatformAdmin", "IntakeOfficer", "TransportDispatcher", "FosterCoordinator"])
    return listing("Litter", DB.all("Litter"), query_filters(["dam_animal_id", "transport_basis"]))


@bp.post("/rescue/litters/<litter_id>/split-approval")
def split_approval(litter_id):
    auth.authenticate(["PlatformAdmin", "TransportDispatcher"])
    body = parse_body(request, [Field("approved_reason", "string", required=True)])
    litter = must("Litter", litter_id)
    if litter["transport_basis"] != "GROUPED":
        raise ApiError("ERR_INVALID_STATE", "The litter is already SPLIT_APPROVED.")
    litter["transport_basis"] = "SPLIT_APPROVED"
    litter["split_approved_at"] = clock.stamp()      # (c) clock-derived
    touch(litter)
    return envelope.ok(derive.litter(litter))
