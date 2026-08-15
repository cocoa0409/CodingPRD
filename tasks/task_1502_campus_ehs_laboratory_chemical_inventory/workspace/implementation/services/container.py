"""Container intake and waste tagging (PRD §3.2, §3.3)."""
import db
from errors import (ApiError, ERR_LAB_STATE, ERR_CONTAINER_STATE, ERR_LAB_FROZEN,
                    ERR_CONTROLLED_MATERIAL_UNREGISTERED, ERR_REQUIRED_TRAINING_INCOMPLETE,
                    ERR_DUPLICATE_BARCODE, ERR_AREA_CAPACITY_EXCEEDED,
                    ERR_CROSS_LAB_REFERENCE)
from services.common import touch, refresh_posture, area_container_count


def validate_container_body(body):
    """Priority 2 well-formedness for POST /ehs/containers (run before FK
    existence checks at priority 5)."""
    from services.common import (require_fields, require_string, require_enum,
                                 optional_enum, require_positive_number,
                                 HAZARD_CLASSES)
    require_fields(body, ["lab_id", "barcode", "chemical_name", "hazard_class", "quantity_value"])
    require_string(body, "barcode")
    require_string(body, "chemical_name")
    require_enum(body, "hazard_class", HAZARD_CLASSES)
    require_positive_number(body, "quantity_value")
    optional_enum(body, "quantity_unit", ("GAL", "L", "KG", "LB"), default="GAL")


def create_container(lab, body):
    from services.common import (require_string, require_enum, optional_enum,
                                 require_positive_number, HAZARD_CLASSES)
    barcode = require_string(body, "barcode")
    chemical_name = require_string(body, "chemical_name")
    hazard_class = require_enum(body, "hazard_class", HAZARD_CLASSES)
    quantity_value = require_positive_number(body, "quantity_value")
    quantity_unit = optional_enum(body, "quantity_unit", ("GAL", "L", "KG", "LB"), default="GAL")

    # Priority 6: state precondition — container create requires lab ACTIVE.
    if lab["status"] != "ACTIVE":
        raise ApiError(ERR_LAB_STATE, "Lab must be ACTIVE to register a container", 409)
    # Priority 7: frozen gate.
    if lab["posture"] == "FROZEN":
        raise ApiError(ERR_LAB_FROZEN, "Lab posture FROZEN blocks container registration", 409)
    # Priority 8: controlled-material registration screen.
    if hazard_class in ("CONTROLLED_SUBSTANCE", "SELECT_AGENT"):
        has_active = any(
            r["lab_id"] == lab["id"] and r["material_type"] == hazard_class
            and r["status"] == "ACTIVE"
            for r in db.registrations.values())
        if not has_active:
            raise ApiError(ERR_CONTROLLED_MATERIAL_UNREGISTERED,
                           "No ACTIVE registration for this material type", 422)
    # Priority 11: barcode uniqueness within the lab.
    if any(c["lab_id"] == lab["id"] and c["barcode"] == barcode
           for c in db.containers.values()):
        raise ApiError(ERR_DUPLICATE_BARCODE,
                       "Barcode already exists within this lab", 409)

    container = {
        "id": db.new_id(),
        "lab_id": lab["id"],
        "barcode": barcode,
        "chemical_name": chemical_name,
        "hazard_class": hazard_class,
        "quantity_value": quantity_value,
        "quantity_unit": quantity_unit,
        "state": "IN_USE",
        "accumulation_area_id": None,
        "tagged_at": None,
        "pickup_request_id": None,
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.containers[container["id"]] = container
    refresh_posture(lab)
    return container


def tag_waste(container, lab, area, user_id):
    """IN_USE -> WASTE_TAGGED into an accumulation area (battery of guards in
    the scaffold's priority order)."""
    # Priority 6: state preconditions (container, then lab).
    if container["state"] != "IN_USE":
        raise ApiError(ERR_CONTAINER_STATE, "Container must be IN_USE to tag as waste", 409)
    if lab["status"] not in ("ACTIVE", "CLOSING"):
        raise ApiError(ERR_LAB_STATE, "Lab must be ACTIVE or CLOSING to tag waste", 409)
    # Priority 7: frozen gate.
    if lab["posture"] == "FROZEN":
        raise ApiError(ERR_LAB_FROZEN, "Lab posture FROZEN blocks waste tagging", 409)
    # Priority 9: required training — acting worker must hold COMPLETED
    # training for this hazard class in this lab.
    trained = any(
        t["lab_id"] == lab["id"] and t["worker_id"] == user_id
        and t["hazard_class"] == container["hazard_class"] and t["status"] == "COMPLETED"
        for t in db.training_assignments.values())
    if not trained:
        raise ApiError(ERR_REQUIRED_TRAINING_INCOMPLETE,
                       "Acting worker lacks COMPLETED training for this hazard class", 422)
    # Priority 19: cross-lab reference.
    if area["lab_id"] != container["lab_id"]:
        raise ApiError(ERR_CROSS_LAB_REFERENCE,
                       "Accumulation area belongs to a different lab", 422)
    # Priority 14: area capacity.
    if area_container_count(area["id"]) >= area["capacity_containers"]:
        raise ApiError(ERR_AREA_CAPACITY_EXCEEDED,
                       "Accumulation area is at capacity", 409)

    container["state"] = "WASTE_TAGGED"
    container["accumulation_area_id"] = area["id"]
    container["tagged_at"] = db.now()
    touch(container)
    refresh_posture(lab)
    return container


def untag_waste(container, lab):
    """WASTE_TAGGED -> IN_USE (compensating action)."""
    if container["state"] != "WASTE_TAGGED":
        raise ApiError(ERR_CONTAINER_STATE, "Container must be WASTE_TAGGED to untag", 409)
    linked = container["pickup_request_id"]
    if linked is not None:
        req = db.waste_pickup_requests.get(linked)
        if req is not None and req["status"] not in ("REJECTED", "CANCELLED"):
            raise ApiError(ERR_CONTAINER_STATE,
                           "Container is linked to a non-terminal pickup request", 409)
    container["state"] = "IN_USE"
    container["accumulation_area_id"] = None
    container["tagged_at"] = None
    container["pickup_request_id"] = None
    touch(container)
    refresh_posture(lab)
    return container
