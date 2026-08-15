"""Lot endpoints (PRD 3.5): listing and reservation under takedown agreements."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_AGREEMENT_PARCEL_MISMATCH,
    ERR_LOT_INVALID_STATE,
    ERR_PHASE_INVALID_STATE,
)
from middleware import authorized, check_builder_ownership
from response import success_object
from routes.helpers import get_one, list_response, public
from services.core import recompute_parcel, touch
from validate import check_body_fk_exists, get_body, req_str, require_path

bp = Blueprint("lots", __name__)


@bp.get("/lots")
def list_lots():
    return list_response("lots", {
        "phase_id": request.args.get("phase_id"),
        "sales_status": request.args.get("sales_status"),
        "lien_status": request.args.get("lien_status"),
        "reserved_agreement_id": request.args.get("reserved_agreement_id"),
    })


@bp.get("/lots/<rid>")
def get_lot(rid):
    return get_one("lots", rid)


@bp.post("/lots/<rid>/reserve")
def reserve_lot(rid):
    caller = authorized(["BuilderRep"])
    body = get_body()
    agreement = None
    if isinstance(body.get("agreement_id"), str):
        agreement = db["agreements"].get(body["agreement_id"])
    # Priority 2 (ownership): BuilderRep acts only under their own builder's agreements
    check_builder_ownership(caller, agreement)
    # Priority 3 (existence): path id first, then body FKs
    lot = require_path("lots", rid)
    check_body_fk_exists("agreements", body, "agreement_id")
    # Priority 4 (shape)
    agreement_id = req_str(body, "agreement_id")
    if agreement is None:
        agreement = db["agreements"][agreement_id]
    # Priority 6 (state): the addressed lot must be PLATTED
    if lot["sales_status"] != "PLATTED":
        raise_error(ERR_LOT_INVALID_STATE, "reserve requires lot sales_status PLATTED")
    # Priority 10 (referential), in declared order
    if agreement["status"] != "ACTIVE":
        raise_error(ERR_AGREEMENT_NOT_ACTIVE, "reserve requires an ACTIVE agreement")
    phase = db["phases"].get(lot["phase_id"])
    if phase is None or phase["status"] != "ACTIVE":
        raise_error(ERR_PHASE_INVALID_STATE, "reserve requires the lot's phase to be ACTIVE")
    if agreement["parcel_id"] != phase["parcel_id"]:
        raise_error(ERR_AGREEMENT_PARCEL_MISMATCH,
                    "agreement parcel does not match the lot's phase's parcel")
    lot["sales_status"] = "RESERVED"
    lot["reserved_agreement_id"] = agreement_id
    touch(lot)
    parcel = db["parcels"].get(phase["parcel_id"])
    if parcel is not None:
        recompute_parcel(parcel, bump="always")  # lots_available_count -1
    return success_object(public(lot))
