"""Item capture endpoints (PRD §3.1)."""
from flask import Blueprint

from db import STORE, new_id, now_iso, touch
from errors import ApiError, ERR_JOB_INVALID_STATE, ERR_ITEM_NOT_CAPTURABLE, not_found
from middleware import (ALL_OPERATIONAL, require_roles, body, req_str, req_num,
                        req_enum, req_int, opt_str, opt_num, opt_enum, opt_bool,
                        opt_int, paginate, enum_filter, str_filter)
from response import success
from services import calc
from services.state import get, ser_item, item_designs

bp = Blueprint("items", __name__)

FRAGILE = {"STANDARD", "DELICATE", "HIGHLY_FRAGILE"}
BATTERY = {"NONE", "LITHIUM_ION", "LITHIUM_METAL", "WET_CELL"}
ITEM_STATUSES = {"CAPTURED", "DESIGN_APPROVED", "PACKED", "SEALED"}


def _get_item_or_404(iid):
    it = get("items", iid)
    if not it:
        raise not_found("Item not found")
    return it


def _validate_item_fields(d, partial=False):
    """Returns dict of validated fields. Client-sent computed fields are ignored."""
    out = {}
    getters = [
        ("description", lambda k: req_str(d, k) if not partial else opt_str(d, k)),
        ("length_cm", lambda k: req_num(d, k, gt=0) if not partial else opt_num(d, k, gt=0)),
        ("width_cm", lambda k: req_num(d, k, gt=0) if not partial else opt_num(d, k, gt=0)),
        ("height_cm", lambda k: req_num(d, k, gt=0) if not partial else opt_num(d, k, gt=0)),
        ("weight_kg", lambda k: req_num(d, k, gt=0) if not partial else opt_num(d, k, gt=0)),
        ("fragile_class", lambda k: req_enum(d, k, FRAGILE) if not partial else opt_enum(d, k, FRAGILE)),
        ("declared_value_cents", lambda k: req_int(d, k, minimum=0) if not partial else opt_int(d, k, minimum=0)),
        ("hazmat", lambda k: opt_bool(d, k)),
        ("battery_in_equipment", lambda k: opt_enum(d, k, BATTERY)),
    ]
    for key, getter in getters:
        v = getter(key)
        if partial and v is None:
            continue
        out[key] = v
    return out


@bp.post("/crating/packing-jobs/<jid>/items")
def create_item(jid):
    require_roles(["SalesRep"])
    d = body()
    fields = _validate_item_fields(d, partial=False)
    j = get("jobs", jid)
    if not j:
        raise not_found("PackingJob not found")
    if j["status"] != "QUOTED":
        raise ApiError(ERR_JOB_INVALID_STATE,
                       "Items may only be captured while the job is QUOTED", 409)
    metrics = calc.item_metrics(fields["length_cm"], fields["width_cm"],
                                fields["height_cm"], fields["weight_kg"])
    rec = {
        "id": new_id(), "packing_job_id": jid,
        "description": fields["description"],
        "length_cm": fields["length_cm"], "width_cm": fields["width_cm"],
        "height_cm": fields["height_cm"], "weight_kg": fields["weight_kg"],
        "fragile_class": fields["fragile_class"],
        "hazmat": fields.get("hazmat") if fields.get("hazmat") is not None else False,
        "battery_in_equipment": fields.get("battery_in_equipment") or "NONE",
        "declared_value_cents": fields["declared_value_cents"],
        "volume_m3": metrics["volume_m3"],
        "dimensional_weight_kg": metrics["dimensional_weight_kg"],
        "chargeable_weight_kg": metrics["chargeable_weight_kg"],
        "status": "CAPTURED",
        "created_at": now_iso(), "updated_at": now_iso(), "version": 1,
    }
    STORE["items"][rec["id"]] = rec
    touch(j)  # capturing an item bumps the parent job's version
    return success(ser_item(rec), status=201)


@bp.get("/crating/items/<iid>")
def get_item(iid):
    require_roles(ALL_OPERATIONAL)
    return success(ser_item(_get_item_or_404(iid)))


@bp.get("/crating/items")
def list_items():
    require_roles(ALL_OPERATIONAL)
    job_id = str_filter("packing_job_id")
    status = enum_filter("status", ITEM_STATUSES)
    recs = [it for it in STORE["items"].values()
            if (job_id is None or it["packing_job_id"] == job_id)
            and (status is None or it["status"] == status)]
    recs.sort(key=lambda it: it["created_at"])
    page, meta = paginate(recs)
    return success([ser_item(it) for it in page], pagination=meta)


@bp.patch("/crating/items/<iid>")
def patch_item(iid):
    require_roles(["SalesRep"])
    d = body()
    fields = _validate_item_fields(d, partial=True)
    it = _get_item_or_404(iid)
    j = get("jobs", it["packing_job_id"])
    if j["status"] != "QUOTED":
        raise ApiError(ERR_JOB_INVALID_STATE,
                       "Items may only be corrected while the job is QUOTED", 409)
    if any(ds["status"] != "SUPERSEDED" for ds in item_designs(iid)):
        raise ApiError(ERR_ITEM_NOT_CAPTURABLE,
                       "A non-SUPERSEDED design exists for this item", 409)
    for k, v in fields.items():
        it[k] = v
    metrics = calc.item_metrics(it["length_cm"], it["width_cm"],
                                it["height_cm"], it["weight_kg"])
    it.update(metrics)
    touch(it)
    touch(j)
    return success(ser_item(it))
