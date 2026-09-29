"""Animal and sighting reads, subject to the producer privacy gate (PRD 2.7)."""
from flask import Blueprint

import shape
from authz import (HARVEST_OPERATOR, PRODUCER, PROGRAM_ADMIN, STATE_OFFICIAL,
                   TRACE_ANALYST, can_read_animal, require_can_read_animal,
                   require_roles)
from db import store
from respond import success
from routes._common import animal_or_404, get_or_404, page
from serialize import public

bp = Blueprint("animals", __name__)

READ_ROLES = (PRODUCER, PROGRAM_ADMIN, STATE_OFFICIAL, TRACE_ANALYST, HARVEST_OPERATOR)


@bp.get("/animals/<animal_id>")
def read_animal(animal_id):
    uid, role = require_roles(*READ_ROLES)
    animal = animal_or_404(animal_id)
    require_can_read_animal(uid, role, animal)
    return success(public(animal))


@bp.get("/animals")
def list_animals():
    uid, role = require_roles(*READ_ROLES)
    limit, offset = shape.pagination_params()
    rows = list(store.animals.values())
    for field in ("birth_premises_id", "current_premises_id", "species",
                  "lifecycle_status", "trace_status", "ain"):
        value = shape.q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    # List endpoints silently omit rows the caller may not read.
    rows = [r for r in rows if can_read_animal(uid, role, r)]
    return page(rows, limit, offset)


@bp.get("/sightings/<sighting_id>")
def read_sighting(sighting_id):
    uid, role = require_roles(*READ_ROLES)
    sighting = get_or_404(store.sightings, sighting_id, "ERR_SIGHTING_NOT_FOUND")
    animal = store.animals.get(sighting["animal_id"])
    if animal is not None:
        require_can_read_animal(uid, role, animal)
    return success(public(sighting))


@bp.get("/sightings")
def list_sightings():
    uid, role = require_roles(*READ_ROLES)
    limit, offset = shape.pagination_params()
    rows = list(store.sightings.values())
    for field in ("animal_id", "premises_id", "source_movement_id", "sighting_type"):
        value = shape.q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    include_reversed = shape.q_bool("include_reversed")
    if not include_reversed:
        rows = [r for r in rows if not r["reversed"]]
    readable = {}
    kept = []
    for row in rows:
        animal = store.animals.get(row["animal_id"])
        if animal is None:
            kept.append(row)
            continue
        allowed = readable.get(animal["id"])
        if allowed is None:
            allowed = can_read_animal(uid, role, animal)
            readable[animal["id"]] = allowed
        if allowed:
            kept.append(row)
    # PRD 2.3: the sighting history is ordered by sequence_no ascending.
    return page(kept, limit, offset,
                key=lambda s: (s["sequence_no"], s["created_at"], s["_seq"]))
