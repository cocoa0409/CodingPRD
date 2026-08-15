"""CrateDesign endpoints (PRD §3.2)."""
from flask import Blueprint

from db import STORE, new_id, now_iso, logical_now, touch
from errors import (ApiError, ERR_STALE_VERSION, ERR_ITEM_HAS_CRATE,
                    ERR_DESIGN_INVALID_STATE, ERR_BATCH_NOT_ACTIVE,
                    ERR_INSUFFICIENT_WOOD, not_found, bad_request)
from middleware import (ALL_OPERATIONAL, require_roles, body, req_int, req_str,
                        paginate, enum_filter, str_filter)
from response import success
from services import calc
from services.state import (get, ser_design, item_designs, live_crate_for_item,
                            batch_available, refresh_batch)

bp = Blueprint("designs", __name__)

DESIGN_STATUSES = {"DRAFT", "IN_REVIEW", "APPROVED", "REJECTED", "LOCKED", "SUPERSEDED"}


def _get_design_or_404(did):
    d = get("designs", did)
    if not d:
        raise not_found("CrateDesign not found")
    return d


@bp.post("/crating/items/<item_id>/designs")
def create_design(item_id):
    require_roles(["CratingDesigner"])
    d = body()
    expected = req_int(d, "expected_item_version")
    it = get("items", item_id)
    if not it:
        raise not_found("Item not found")
    # OCC on the parent Item (PRD §2.7)
    if expected != it["version"]:
        raise ApiError(ERR_STALE_VERSION, "Stale Item version", 412)
    if live_crate_for_item(item_id) is not None:
        raise ApiError(ERR_ITEM_HAS_CRATE,
                       "Item already has a non-VOIDED crate", 409)
    priors = item_designs(item_id)
    # supersede-by-create: existing DRAFT / IN_REVIEW / REJECTED designs
    for old in priors:
        if old["status"] in ("DRAFT", "IN_REVIEW", "REJECTED"):
            old["status"] = "SUPERSEDED"
            touch(old)
    rec = {
        "id": new_id(), "item_id": item_id, "revision": len(priors) + 1,
        "wood_batch_id": None, "reject_reason": None, "status": "DRAFT",
        "created_at": now_iso(), "updated_at": now_iso(), "version": 1,
    }
    rec.update(calc.design_geometry(it))
    STORE["designs"][rec["id"]] = rec
    touch(it)  # design creation bumps the item's version
    return success(ser_design(rec), status=201)


@bp.get("/crating/designs/<did>")
def get_design(did):
    require_roles(ALL_OPERATIONAL)
    return success(ser_design(_get_design_or_404(did)))


@bp.get("/crating/designs")
def list_designs():
    require_roles(ALL_OPERATIONAL)
    item_id = str_filter("item_id")
    wood_batch_id = str_filter("wood_batch_id")
    status = enum_filter("status", DESIGN_STATUSES)
    recs = [d for d in STORE["designs"].values()
            if (item_id is None or d["item_id"] == item_id)
            and (wood_batch_id is None or d["wood_batch_id"] == wood_batch_id)
            and (status is None or d["status"] == status)]
    recs.sort(key=lambda d: d["created_at"])
    page, meta = paginate(recs)
    return success([ser_design(d) for d in page], pagination=meta)


@bp.post("/crating/designs/<did>/submit")
def submit_design(did):
    require_roles(["CratingDesigner"])
    d = _get_design_or_404(did)
    if d["status"] != "DRAFT":
        raise ApiError(ERR_DESIGN_INVALID_STATE, "submit requires status DRAFT", 409)
    d["status"] = "IN_REVIEW"
    touch(d)
    return success(ser_design(d))


@bp.post("/crating/designs/<did>/approve")
def approve_design(did):
    require_roles(["ComplianceOfficer"])
    b = body()
    wood_batch_id = req_str(b, "wood_batch_id")
    d = _get_design_or_404(did)
    batch = get("batches", wood_batch_id)
    if not batch:
        raise not_found("WoodBatch not found")
    if d["status"] != "IN_REVIEW":
        raise ApiError(ERR_DESIGN_INVALID_STATE, "approve requires status IN_REVIEW", 409)
    refresh_batch(batch)  # lazy expiry evaluation
    if batch["status"] != "ACTIVE" or batch["expires_at"] < logical_now():
        raise ApiError(ERR_BATCH_NOT_ACTIVE, "WoodBatch is not ACTIVE or has expired", 409)
    if batch_available(batch) < d["board_feet_required"]:
        raise ApiError(ERR_INSUFFICIENT_WOOD, "Insufficient available board feet", 422)
    d["wood_batch_id"] = wood_batch_id
    d["status"] = "APPROVED"
    touch(d)
    batch["reserved_board_feet"] += d["board_feet_required"]
    touch(batch)
    refresh_batch(batch)
    it = get("items", d["item_id"])
    if it and it["status"] == "CAPTURED":
        it["status"] = "DESIGN_APPROVED"
        touch(it)
    return success(ser_design(d))


@bp.post("/crating/designs/<did>/reject")
def reject_design(did):
    require_roles(["ComplianceOfficer"])
    b = body()
    reason = b.get("reason")
    if not isinstance(reason, str):
        raise bad_request("Field 'reason' is required and must be a string")
    d = _get_design_or_404(did)
    if d["status"] != "IN_REVIEW":
        raise ApiError(ERR_DESIGN_INVALID_STATE, "reject requires status IN_REVIEW", 409)
    d["status"] = "REJECTED"
    d["reject_reason"] = reason
    touch(d)
    return success(ser_design(d))


@bp.post("/crating/designs/<did>/revise")
def revise_design(did):
    require_roles(["CratingDesigner"])
    d = _get_design_or_404(did)
    if d["status"] != "REJECTED":
        raise ApiError(ERR_DESIGN_INVALID_STATE, "revise requires status REJECTED", 409)
    d["status"] = "DRAFT"
    d["revision"] += 1
    it = get("items", d["item_id"])
    if it:
        d.update(calc.design_geometry(it))  # recompute from current item dims
    touch(d)
    return success(ser_design(d))
