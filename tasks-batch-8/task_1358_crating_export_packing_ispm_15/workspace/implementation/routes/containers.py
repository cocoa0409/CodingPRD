"""Container load planning (PRD §3.8)."""
from flask import Blueprint

from db import STORE, new_id, now_iso, touch
from errors import (ApiError, ERR_DUPLICATE, ERR_CONTAINER_INVALID_STATE,
                    ERR_CRATE_INVALID_STATE, ERR_BATCH_NOT_ACTIVE,
                    ERR_CONTAINER_OVERWEIGHT, ERR_DG_SEGREGATION_VIOLATION,
                    not_found)
from middleware import (ALL_OPERATIONAL, require_roles, body, req_str, req_enum,
                        opt_num)
from response import success
from services import calc
from services.state import (get, ser_container, ser_crate, container_payload_used,
                            container_loaded_crates, item_dg_classes,
                            refresh_job_status)

bp = Blueprint("containers", __name__)

SIZES = {"20FT", "40FT", "40HC"}


def _get_container_or_404(cid):
    c = get("containers", cid)
    if not c:
        raise not_found("Container not found")
    return c


@bp.post("/crating/containers")
def create_container():
    require_roles(["LogisticsCoordinator"])
    d = body()
    container_no = req_str(d, "container_no")
    size = req_enum(d, "size", SIZES)
    dunnage = opt_num(d, "dunnage_weight_kg", gte=0)
    for c in STORE["containers"].values():
        if c["container_no"] == container_no:
            raise ApiError(ERR_DUPLICATE, "container_no already exists", 409)
    rec = {"id": new_id(), "container_no": container_no, "size": size,
           "max_payload_kg": calc.MAX_PAYLOAD_KG[size],
           "dunnage_weight_kg": dunnage if dunnage is not None else 0,
           "status": "PLANNING",
           "created_at": now_iso(), "updated_at": now_iso(), "version": 1}
    STORE["containers"][rec["id"]] = rec
    return success(ser_container(rec), status=201)


@bp.get("/crating/containers/<cid>")
def get_container(cid):
    require_roles(ALL_OPERATIONAL)
    return success(ser_container(_get_container_or_404(cid)))


@bp.post("/crating/containers/<cid>/lock")
def lock_container(cid):
    require_roles(["LogisticsCoordinator"])
    c = _get_container_or_404(cid)
    if c["status"] != "PLANNING":
        raise ApiError(ERR_CONTAINER_INVALID_STATE, "lock requires status PLANNING", 409)
    if not container_loaded_crates(cid):
        raise ApiError(ERR_CONTAINER_INVALID_STATE,
                       "lock requires at least one LOADED crate", 409)
    c["status"] = "LOCKED"
    touch(c)
    return success(ser_container(c))


@bp.post("/crating/containers/<cid>/unlock")
def unlock_container(cid):
    require_roles(["LogisticsCoordinator"])
    c = _get_container_or_404(cid)
    if c["status"] != "LOCKED":
        raise ApiError(ERR_CONTAINER_INVALID_STATE, "unlock requires status LOCKED", 409)
    if container_payload_used(cid) != 0:
        raise ApiError(ERR_CONTAINER_INVALID_STATE,
                       "unlock requires zero payload in use", 409)
    c["status"] = "PLANNING"
    touch(c)
    return success(ser_container(c))


@bp.post("/crating/containers/<cid>/gate-out")
def gate_out_container(cid):
    require_roles(["LogisticsCoordinator"])
    c = _get_container_or_404(cid)
    if c["status"] != "LOCKED":
        raise ApiError(ERR_CONTAINER_INVALID_STATE, "gate-out requires status LOCKED", 409)
    c["status"] = "GATED_OUT"
    touch(c)
    return success(ser_container(c))


@bp.post("/crating/containers/<cid>/load-crate")
def load_crate(cid):
    require_roles(["LogisticsCoordinator"])
    d = body()
    crate_id = req_str(d, "crate_id")
    cont = _get_container_or_404(cid)
    crate = get("crates", crate_id)
    if not crate:
        raise not_found("Crate not found")
    if crate["status"] != "SEALED":
        raise ApiError(ERR_CRATE_INVALID_STATE, "load-crate requires a SEALED crate", 409)
    if cont["status"] != "PLANNING":
        raise ApiError(ERR_CONTAINER_INVALID_STATE,
                       "load-crate requires the container to be PLANNING", 409)
    if crate["compliance_hold"]:
        raise ApiError(ERR_BATCH_NOT_ACTIVE, "Crate is under a compliance hold", 409)
    # DG segregation (tier 7, priority 21)
    new_classes = item_dg_classes(crate["item_id"])
    if new_classes:
        for other in container_loaded_crates(cid):
            other_classes = item_dg_classes(other["item_id"])
            if not other_classes:
                continue
            if "1" in new_classes or "1" in other_classes:
                raise ApiError(ERR_DG_SEGREGATION_VIOLATION,
                               "dg_class '1' may not share a container with any DG crate", 422)
            if ("3" in new_classes and "5.1" in other_classes) or \
               ("5.1" in new_classes and "3" in other_classes):
                raise ApiError(ERR_DG_SEGREGATION_VIOLATION,
                               "dg_class '3' and '5.1' may not co-load", 422)
    # payload guard (tier 11, inclusive limit)
    from decimal import Decimal
    projected = (Decimal(str(container_payload_used(cid)))
                 + Decimal(str(cont["dunnage_weight_kg"]))
                 + Decimal(str(crate["gross_weight_kg"])))
    if projected > Decimal(cont["max_payload_kg"]):
        raise ApiError(ERR_CONTAINER_OVERWEIGHT, "Container payload would be exceeded", 422)
    crate["container_id"] = cid
    crate["status"] = "LOADED"
    touch(crate)
    j = get("jobs", crate["packing_job_id"])
    if j:
        refresh_job_status(j)  # READY_TO_LOAD -> LOADED auto-check
    return success(ser_crate(crate))


@bp.post("/crating/containers/<cid>/unload-crate")
def unload_crate(cid):
    require_roles(["LogisticsCoordinator"])
    d = body()
    crate_id = req_str(d, "crate_id")
    cont = _get_container_or_404(cid)
    crate = get("crates", crate_id)
    if not crate:
        raise not_found("Crate not found")
    if crate["container_id"] != cid:
        raise not_found("Crate is not loaded in this container")
    if crate["status"] != "LOADED":
        raise ApiError(ERR_CRATE_INVALID_STATE, "unload-crate requires a LOADED crate", 409)
    if cont["status"] != "PLANNING":
        raise ApiError(ERR_CONTAINER_INVALID_STATE,
                       "unload-crate requires the container to be PLANNING", 409)
    crate["container_id"] = None
    crate["status"] = "SEALED"
    touch(crate)
    j = get("jobs", crate["packing_job_id"])
    if j:
        refresh_job_status(j)  # LOADED -> READY_TO_LOAD auto-revert
    return success(ser_crate(crate))
