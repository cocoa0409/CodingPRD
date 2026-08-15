"""Crate endpoints (PRD §3.4)."""
from flask import Blueprint

from db import STORE, new_id, now_iso, logical_now, touch
from errors import (ApiError, ERR_DUPLICATE, ERR_NO_APPROVED_DESIGN,
                    ERR_JOB_INVALID_STATE, ERR_CRATE_INVALID_STATE,
                    ERR_BATCH_NOT_ACTIVE, ERR_INDICATOR_MISMATCH,
                    ERR_BARRIER_MISMATCH, ERR_HAZMAT_DECLARATION_REQUIRED,
                    ERR_STAMPS_EXHAUSTED, not_found, bad_request)
from middleware import (ALL_OPERATIONAL, require_roles, body, req_str,
                        paginate, enum_filter, str_filter)
from response import success
from services import calc
from services.state import (get, ser_crate, live_crate_for_item, refresh_batch,
                            batch_stamps_available, refresh_job_status,
                            has_approved_declaration)

bp = Blueprint("crates", __name__)

CRATE_STATUSES = {"PLANNED", "BUILT", "PACKED", "SEALED", "REOPENED",
                  "LOADED", "SHIPPED", "DELIVERED", "VOIDED"}
BARRIERS = {"NONE", "VCI", "VACUUM_SEALED"}


def get_crate_or_404(cid):
    c = get("crates", cid)
    if not c:
        raise not_found("Crate not found")
    return c


def _crate_batch(crate):
    d = get("designs", crate["design_id"])
    return get("batches", d["wood_batch_id"]) if d and d["wood_batch_id"] else None


def _batch_active_guard(crate):
    """ERR_BATCH_NOT_ACTIVE if the pinned batch is not ACTIVE/unexpired or the
    crate carries a compliance hold."""
    batch = _crate_batch(crate)
    if batch is None:
        raise ApiError(ERR_BATCH_NOT_ACTIVE, "Pinned design has no wood batch", 409)
    refresh_batch(batch)  # lazy expiry evaluation
    if batch["status"] != "ACTIVE" or batch["expires_at"] < logical_now():
        raise ApiError(ERR_BATCH_NOT_ACTIVE, "WoodBatch is not ACTIVE or has expired", 409)
    if crate["compliance_hold"]:
        raise ApiError(ERR_BATCH_NOT_ACTIVE, "Crate is under a compliance hold", 409)
    return batch


@bp.post("/crating/items/<item_id>/crates")
def create_crate(item_id):
    require_roles(["ShopForeman"])
    d = body()
    design_id = req_str(d, "design_id")
    it = get("items", item_id)
    if not it:
        raise not_found("Item not found")
    design = get("designs", design_id)
    if not design:
        raise not_found("CrateDesign not found")
    # uniqueness (PRD §2.9): at most one non-VOIDED crate per item (ladder tier 9)
    if live_crate_for_item(item_id) is not None:
        raise ApiError(ERR_DUPLICATE, "Item already has a non-VOIDED crate", 409)
    # design must belong to this item and be APPROVED (tier 10)
    if design["item_id"] != item_id or design["status"] != "APPROVED":
        raise ApiError(ERR_NO_APPROVED_DESIGN,
                       "design_id must reference an APPROVED design of this item", 409)
    metrics = calc.crate_metrics(it, design)
    rec = {
        "id": new_id(), "item_id": item_id, "packing_job_id": it["packing_job_id"],
        "design_id": design_id, "container_id": None,
        "stamp_serial": None, "stamp_status": None, "compliance_hold": False,
        "status": "PLANNED",
        "created_at": now_iso(), "updated_at": now_iso(), "version": 1,
    }
    rec.update(metrics)
    STORE["crates"][rec["id"]] = rec
    design["status"] = "LOCKED"  # version-pinning
    touch(design)
    return success(ser_crate(rec), status=201)


@bp.get("/crating/crates/<cid>")
def get_crate(cid):
    require_roles(ALL_OPERATIONAL)
    return success(ser_crate(get_crate_or_404(cid)))


@bp.get("/crating/crates")
def list_crates():
    require_roles(ALL_OPERATIONAL)
    item_id = str_filter("item_id")
    job_id = str_filter("packing_job_id")
    container_id = str_filter("container_id")
    design_id = str_filter("design_id")
    status = enum_filter("status", CRATE_STATUSES)
    recs = [c for c in STORE["crates"].values()
            if (item_id is None or c["item_id"] == item_id)
            and (job_id is None or c["packing_job_id"] == job_id)
            and (container_id is None or c["container_id"] == container_id)
            and (design_id is None or c["design_id"] == design_id)
            and (status is None or c["status"] == status)]
    recs.sort(key=lambda c: c["created_at"])
    page, meta = paginate(recs)
    return success([ser_crate(c) for c in page], pagination=meta)


@bp.post("/crating/crates/<cid>/build")
def build_crate(cid):
    require_roles(["ShopForeman"])
    c = get_crate_or_404(cid)
    j = get("jobs", c["packing_job_id"])
    if j["status"] != "PACKING":
        raise ApiError(ERR_JOB_INVALID_STATE, "build requires the job to be PACKING", 409)
    if c["status"] != "PLANNED":
        raise ApiError(ERR_CRATE_INVALID_STATE, "build requires status PLANNED", 409)
    batch = _batch_active_guard(c)
    design = get("designs", c["design_id"])
    batch["reserved_board_feet"] -= design["board_feet_required"]
    batch["consumed_board_feet"] += design["board_feet_required"]
    touch(batch)
    refresh_batch(batch)
    c["status"] = "BUILT"
    touch(c)
    return success(ser_crate(c))


@bp.post("/crating/crates/<cid>/pack")
def pack_crate(cid):
    require_roles(["ShopForeman"])
    d = body()
    indicator_g = d.get("indicator_g")
    if isinstance(indicator_g, bool) or not isinstance(indicator_g, int):
        raise bad_request("Field 'indicator_g' is required and must be an integer")
    barrier = d.get("moisture_barrier")
    if not isinstance(barrier, str) or barrier not in BARRIERS:
        raise bad_request("Field 'moisture_barrier' is required and must be one of NONE|VCI|VACUUM_SEALED")
    c = get_crate_or_404(cid)
    if c["status"] not in ("BUILT", "REOPENED"):
        raise ApiError(ERR_CRATE_INVALID_STATE,
                       "pack requires status BUILT or REOPENED", 409)
    design = get("designs", c["design_id"])
    # indicator compared before barrier (PRD §2.8 tier 7)
    if indicator_g != design["shock_indicator_g"]:
        raise ApiError(ERR_INDICATOR_MISMATCH, "indicator_g does not match the design", 422)
    if barrier != design["moisture_barrier_required"]:
        raise ApiError(ERR_BARRIER_MISMATCH, "moisture_barrier does not match the design", 422)
    was_built = c["status"] == "BUILT"
    c["status"] = "PACKED"
    touch(c)
    if was_built:
        it = get("items", c["item_id"])
        if it:
            it["status"] = "PACKED"
            touch(it)
    return success(ser_crate(c))


@bp.post("/crating/crates/<cid>/seal")
def seal_crate(cid):
    require_roles(["ComplianceOfficer"])
    c = get_crate_or_404(cid)
    j = get("jobs", c["packing_job_id"])
    if j["status"] not in ("PACKING", "READY_TO_LOAD"):
        raise ApiError(ERR_JOB_INVALID_STATE,
                       "seal requires the job to be PACKING or READY_TO_LOAD", 409)
    if c["status"] != "PACKED":
        raise ApiError(ERR_CRATE_INVALID_STATE, "seal requires status PACKED", 409)
    it = get("items", c["item_id"])
    # business-safety tier: declaration presence first, then batch activity
    if (it["hazmat"] or it["battery_in_equipment"] != "NONE") \
            and not has_approved_declaration(it["id"]):
        raise ApiError(ERR_HAZMAT_DECLARATION_REQUIRED,
                       "Hazmat/battery item requires an APPROVED declaration", 422)
    batch = _batch_active_guard(c)
    if batch_stamps_available(batch) <= 0:
        raise ApiError(ERR_STAMPS_EXHAUSTED, "No ISPM-15 stamp serials available", 422)
    seq = batch["stamps_applied"] + batch["stamps_voided"] + 1
    c["stamp_serial"] = "ISPM15-%s-%04d" % (batch["ht_certificate_no"], seq)
    c["stamp_status"] = "ACTIVE"
    batch["stamps_applied"] += 1
    touch(batch)
    c["status"] = "SEALED"
    touch(c)
    it["status"] = "SEALED"
    touch(it)
    refresh_job_status(j)  # PACKING -> READY_TO_LOAD auto-check
    return success(ser_crate(c))


@bp.post("/crating/crates/<cid>/reopen")
def reopen_crate(cid):
    require_roles(["ShopForeman"])
    c = get_crate_or_404(cid)
    if c["status"] != "SEALED":
        raise ApiError(ERR_CRATE_INVALID_STATE, "reopen requires status SEALED", 409)
    batch = _crate_batch(c)
    c["stamp_status"] = "VOIDED"  # serial retained for audit
    if batch:
        batch["stamps_applied"] -= 1
        batch["stamps_voided"] += 1
        batch["consumed_board_feet"] -= 2
        batch["scrapped_board_feet"] += 2
        touch(batch)
        refresh_batch(batch)
    c["status"] = "REOPENED"
    touch(c)
    it = get("items", c["item_id"])
    if it and it["status"] == "SEALED":
        it["status"] = "PACKED"
        touch(it)
    j = get("jobs", c["packing_job_id"])
    refresh_job_status(j)  # READY_TO_LOAD -> PACKING auto-revert
    return success(ser_crate(c))
