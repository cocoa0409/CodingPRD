"""Device replacement, harvest retirement and application voiding (PRD 3.4 / 3.8)."""
from flask import Blueprint

import derive
import shape
from authz import (HARVEST_OPERATOR, PRODUCER, PROGRAM_ADMIN, STATE_OFFICIAL,
                   SUPPLIER_REP, animal_producer_ids, require_owner, require_roles)
from db import base_record, store, touch
from errors import conflict, invalid_state, unprocessable
from respond import success
from routes._common import lot_or_404, page, premises_or_404, tag_or_404
from routes.lots import ain_in_lot
from serialize import public

bp = Blueprint("tags", __name__)


@bp.get("/tags/<tag_id>")
def read_tag(tag_id):
    require_roles(PRODUCER, PROGRAM_ADMIN, STATE_OFFICIAL, HARVEST_OPERATOR, SUPPLIER_REP)
    return success(public(tag_or_404(tag_id)))


@bp.get("/tags")
def list_tags():
    require_roles(PRODUCER, PROGRAM_ADMIN, STATE_OFFICIAL, HARVEST_OPERATOR, SUPPLIER_REP)
    limit, offset = shape.pagination_params()
    rows = list(store.tags.values())
    for field in ("tag_lot_id", "animal_id", "replaces_tag_id", "device_status", "ain"):
        value = shape.q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return page(rows, limit, offset)


@bp.post("/tags/<tag_id>/replace")
def replace_tag(tag_id):
    uid, role = require_roles(PRODUCER)
    body = shape.body()
    replacement_ain = shape.s_str(body, "replacement_ain", pattern=shape.AIN_RE)
    tag_lot_id = shape.s_str(body, "tag_lot_id")
    old_tag = tag_or_404(tag_id)
    new_lot = lot_or_404(tag_lot_id)
    animal = store.animals.get(old_tag["animal_id"])
    # Band 6 - the tagged animal must belong to the acting producer.
    require_owner(animal is not None and uid in animal_producer_ids(animal))
    # Band 10 - own-state gates.
    if old_tag["device_status"] != "APPLIED":
        raise invalid_state("Only an APPLIED device may be replaced")
    if animal["lifecycle_status"] != "ACTIVE":
        raise invalid_state("The tagged animal is not ACTIVE")
    if new_lot["status"] in ("RECALLED", "VOIDED"):
        raise conflict("ERR_LOT_NOT_ISSUABLE",
                       "The tag lot is RECALLED or VOIDED and cannot supply a replacement")
    # Band 11 - the replacement lot's supplier must be APPROVED.
    supplier = store.suppliers.get(new_lot["supplier_id"])
    if supplier is None or supplier["status"] != "APPROVED":
        raise conflict("ERR_SUPPLIER_NOT_APPROVED", "The device supplier is not APPROVED")
    # Band 14 - the replacement AIN must sit inside the addressed lot.
    if not ain_in_lot(replacement_ain, new_lot, supplier):
        raise unprocessable("ERR_AIN_OUT_OF_LOT_RANGE",
                            "The replacement AIN prefix or serial does not belong to this lot")
    # Band 15 - AIN uniqueness.
    if any(t["ain"] == replacement_ain for t in store.tags.values()):
        raise conflict("ERR_DUPLICATE_AIN", "Another tag already carries this ain")
    # Band 16 - exhaustion.
    if new_lot["unapplied_count"] == 0:
        raise conflict("ERR_LOT_EXHAUSTED", "The lot has no unapplied serial left")

    old_tag["device_status"] = "REPLACED"
    touch(old_tag)
    new_tag = base_record()
    new_tag.update({
        "tag_lot_id": new_lot["id"],
        "ain": replacement_ain,
        "animal_id": animal["id"],
        "replaces_tag_id": old_tag["id"],
        "device_status": "APPLIED",
        "applied_at": store.now(),
        "retired_at": None,
        "tag_returned": None,
        "carcass_ref": None,
    })
    store.tags[new_tag["id"]] = new_tag

    old_lot = store.tag_lots.get(old_tag["tag_lot_id"])
    if old_lot is not None:
        derive.recompute_lot(old_lot)
    if new_lot is not old_lot:
        derive.recompute_lot(new_lot)
    # No sighting is appended: a replacement is a device event, not an observation.
    animal["ain"] = replacement_ain
    touch(animal)
    return success(public(new_tag), status=201)


@bp.post("/tags/<tag_id>/retire")
def retire_tag(tag_id):
    uid, role = require_roles(HARVEST_OPERATOR)
    body = shape.body()
    harvest_premises_id = shape.s_str(body, "harvest_premises_id")
    harvested_at = shape.s_instant(body, "harvested_at")
    carcass_ref = shape.s_str(body, "carcass_ref")
    tag_returned = shape.s_bool(body, "tag_returned")
    tag = tag_or_404(tag_id)
    premises = premises_or_404(harvest_premises_id)
    # Band 6 - the facility is its own principal.
    require_owner(uid == premises["id"])
    # Band 10 - own-state gate.
    if tag["device_status"] != "APPLIED":
        raise invalid_state("Only an APPLIED device may be retired")
    # Band 11 - cross-entity state gates.
    if premises["registration_status"] != "ACTIVE":
        raise conflict("ERR_PREMISES_NOT_ACTIVE", "The premises registration is not ACTIVE")
    if premises["health_status"] == "QUARANTINED":
        raise conflict("ERR_PREMISES_UNDER_HOLD", "The premises is under quarantine")
    # Band 13 - cross-field temporal checks.
    now = store.now()
    if harvested_at > now:
        raise unprocessable("ERR_FUTURE_TIMESTAMP", "harvested_at is later than the logical clock")
    animal = store.animals.get(tag["animal_id"])
    latest = derive.latest_observed_at(tag["animal_id"]) if animal else None
    if latest is not None and harvested_at < latest:
        raise unprocessable("ERR_BACKDATED_EVENT",
                            "harvested_at precedes the animal's latest observation")
    # Band 14 - referential coherence.
    if (animal is None or animal["lifecycle_status"] != "ACTIVE"
            or animal["current_premises_id"] != premises["id"]):
        raise unprocessable("ERR_ANIMAL_NOT_AT_PREMISES",
                            "The animal does not currently stand at the harvest premises")
    if premises["operation_type"] != "HARVEST_FACILITY":
        raise unprocessable("ERR_NOT_HARVEST_FACILITY",
                            "The premises is not a harvest facility")

    # CASCADE-B hop 1: the device retires.
    tag.update({
        "retired_at": now,
        "tag_returned": tag_returned,
        "carcass_ref": carcass_ref,
        "device_status": "RETIRED",
    })
    touch(tag)
    # hop 2: the lot counters shift.
    lot = store.tag_lots.get(tag["tag_lot_id"])
    if lot is not None:
        derive.recompute_lot(lot)
        # hop 3 + hop 4: the supplier's retirement statistics and discipline.
        supplier = store.suppliers.get(lot["supplier_id"])
        if supplier is not None:
            derive.recompute_supplier(supplier, apply_status_transitions=True)
    # The harvest observation re-projects the animal.
    previous_premises = animal["current_premises_id"]
    derive.append_sighting(animal, premises["id"], "HARVEST", harvested_at)
    derive.reproject_animal(animal)
    derive.recompute_premises_animal_count([previous_premises, premises["id"]])
    return success(public(tag))


@bp.post("/tags/<tag_id>/void-application")
def void_application(tag_id):
    require_roles(PROGRAM_ADMIN)
    tag = tag_or_404(tag_id)
    animal = store.animals.get(tag["animal_id"])
    # Band 10 - own-state gates.
    if tag["device_status"] != "APPLIED":
        raise invalid_state("Only an APPLIED device application may be voided")
    if animal is None or animal["lifecycle_status"] != "ACTIVE":
        raise invalid_state("The tagged animal is not ACTIVE")

    tag["device_status"] = "VOIDED"
    touch(tag)
    lot = store.tag_lots.get(tag["tag_lot_id"])
    if lot is not None:
        derive.recompute_lot(lot)
    previous_premises = animal["current_premises_id"]
    for sighting in derive.animal_rows(animal["id"]):
        sighting["reversed"] = True
    derive.reproject_animal(animal)
    derive.recompute_premises_animal_count([previous_premises])
    return success(public(tag))
