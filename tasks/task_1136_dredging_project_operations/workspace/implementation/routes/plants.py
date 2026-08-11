"""DredgePlant endpoints (PRD 3.3)."""
import uuid

from flask import Blueprint

from db import store
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE
from middleware import require_roles, ALL_ROLES
from response import ok
from routes.common import list_response
from services import serialize_plant
from util import as_enum, as_int, as_str, check, get_body, new_entity, req_present, touch

bp = Blueprint("plants", __name__)

_ALLOWED_TRANSITIONS = {
    ("REGISTERED", "OUT_OF_SERVICE"),
    ("OUT_OF_SERVICE", "REGISTERED"),
    ("REGISTERED", "RETIRED"),
    ("OUT_OF_SERVICE", "RETIRED"),
}


@bp.post("/plants")
@require_roles("ContractorOps")
def create_plant():
    body = get_body()
    contractor_ref = as_str(req_present(body, "contractor_ref"), "contractor_ref")
    plant_type = as_enum(
        req_present(body, "plant_type"),
        "plant_type",
        ["CUTTER_SUCTION", "HOPPER", "CLAMSHELL", "BACKHOE"],
    )
    rated = as_int(
        req_present(body, "rated_daily_production_cy"), "rated_daily_production_cy"
    )
    check(rated > 0, "rated_daily_production_cy must be > 0")
    rec = new_entity(
        {
            "id": str(uuid.uuid4()),
            "contractor_ref": contractor_ref,
            "plant_type": plant_type,
            "rated_daily_production_cy": rated,
            "status": "REGISTERED",
        }
    )
    store.plants[rec["id"]] = rec
    return ok(serialize_plant(rec), 201)


def _get_plant(pid):
    plant = store.plants.get(pid)
    if plant is None:
        raise ApiError(ERR_NOT_FOUND, "DredgePlant not found", 404)
    return plant


@bp.get("/plants/<pid>")
@require_roles(*ALL_ROLES)
def get_plant(pid):
    return ok(serialize_plant(_get_plant(pid)))


@bp.get("/plants")
@require_roles(*ALL_ROLES)
def list_plants():
    return list_response(store.plants, serialize_plant, ["status", "plant_type"])


@bp.patch("/plants/<pid>")
@require_roles("ContractorOps")
def patch_plant(pid):
    plant = _get_plant(pid)
    body = get_body()
    target = as_enum(
        req_present(body, "status"), "status", ["REGISTERED", "OUT_OF_SERVICE", "RETIRED"]
    )
    current = plant["status"]
    # State gate (class 6): only declared transitions; RETIRED is terminal.
    if (current, target) not in _ALLOWED_TRANSITIONS:
        raise ApiError(
            ERR_INVALID_STATE,
            "Plant cannot transition from %s to %s" % (current, target),
            409,
        )
    if target == "RETIRED":
        if any(
            e["plant_id"] == pid and e["status"] in ("ACTIVE", "SHUTDOWN")
            for e in store.events.values()
        ):
            raise ApiError(
                ERR_INVALID_STATE,
                "Plant has dredge events in ACTIVE or SHUTDOWN",
                409,
            )
    if target == "OUT_OF_SERVICE":
        # Cascade: every ACTIVE event of this plant -> SHUTDOWN (EQUIPMENT).
        for ev in store.events.values():
            if ev["plant_id"] == pid and ev["status"] == "ACTIVE":
                ev["status"] = "SHUTDOWN"
                ev["shutdown_reason"] = "EQUIPMENT"
                ev["last_shutdown_at"] = store.logical_now
                touch(ev)
    # OUT_OF_SERVICE -> REGISTERED pointedly does NOT resume anything.
    plant["status"] = target
    touch(plant)
    return ok(serialize_plant(plant))
