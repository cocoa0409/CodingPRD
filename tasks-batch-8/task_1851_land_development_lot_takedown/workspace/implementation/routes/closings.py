"""LotClosing endpoints (PRD 3.5): open, finalize (lien release cascade), cancel."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_CLOSING_INVALID_STATE,
    ERR_LOT_NOT_RESERVED_BY_AGREEMENT,
    ERR_NO_ACTIVE_LOAN,
)
from middleware import authorized, check_builder_ownership
from response import success_object
from routes.helpers import get_one, list_response, public
from services import calculations as calc
from services.cascades import finalize_cascade
from services.core import active_loan_for, new_record, touch
from util import CLOCK
from validate import check_body_fk_exists, get_body, req_str, require_path

bp = Blueprint("closings", __name__)


@bp.post("/lot-closings")
def create_closing():
    caller = authorized(["BuilderRep"])
    body = get_body()
    agreement = None
    if isinstance(body.get("agreement_id"), str):
        agreement = db["agreements"].get(body["agreement_id"])
    # Priority 2 (ownership): the BuilderRep must own the body agreement
    check_builder_ownership(caller, agreement)
    # Priority 3 (existence): body FKs in declared order — lot_id, agreement_id
    check_body_fk_exists("lots", body, "lot_id")
    check_body_fk_exists("agreements", body, "agreement_id")
    # Priority 4 (shape)
    lot_id = req_str(body, "lot_id")
    agreement_id = req_str(body, "agreement_id")
    lot = db["lots"][lot_id]
    agreement = db["agreements"][agreement_id]
    # Priority 10 (referential), PRD 3.5 order: lot reserved by this agreement,
    # agreement ACTIVE, then the parcel's ACTIVE loan must be selectable
    if lot["sales_status"] != "RESERVED" or lot["reserved_agreement_id"] != agreement_id:
        raise_error(ERR_LOT_NOT_RESERVED_BY_AGREEMENT,
                    "lot is not RESERVED under this agreement")
    if agreement["status"] != "ACTIVE":
        raise_error(ERR_AGREEMENT_NOT_ACTIVE, "closing requires an ACTIVE agreement")
    phase = db["phases"][lot["phase_id"]]
    parcel_id = phase["parcel_id"]
    loan = active_loan_for(parcel_id)
    if loan is None:
        raise_error(ERR_NO_ACTIVE_LOAN, "no ACTIVE development loan for the parcel")
    # Pricing engine freezes its result onto the closing at creation time
    contract_price = calc.lot_current_price(agreement, CLOCK.now())
    release_price = calc.lien_release_price(contract_price, loan["release_price_floor_bp"])
    rec = new_record("closings", {
        "lot_id": lot_id,
        "agreement_id": agreement_id,
        "loan_id": loan["id"],
        "contract_price_cents": contract_price,
        "release_price_cents": release_price,
        "payment_applied_cents": 0,
        "finalized_at": None,
        "status": "PENDING",
    })
    # Creation advances the lot on both dimensions at once (one mutation event)
    lot["sales_status"] = "UNDER_CONTRACT"
    lot["lien_status"] = "RELEASE_PENDING"
    touch(lot)
    return success_object(public(rec), status=201)


@bp.get("/lot-closings")
def list_closings():
    return list_response("closings", {
        "lot_id": request.args.get("lot_id"),
        "agreement_id": request.args.get("agreement_id"),
        "loan_id": request.args.get("loan_id"),
        "status": request.args.get("status"),
    })


@bp.get("/lot-closings/<rid>")
def get_closing(rid):
    return get_one("closings", rid)


@bp.post("/lot-closings/<rid>/finalize")
def finalize_closing(rid):
    authorized(["LenderOfficer"])
    closing = require_path("closings", rid)
    if closing["status"] != "PENDING":
        raise_error(ERR_CLOSING_INVALID_STATE, "finalize requires PENDING")
    finalize_cascade(closing)
    return success_object(public(closing))


@bp.post("/lot-closings/<rid>/cancel")
def cancel_closing(rid):
    caller = authorized(["BuilderRep", "DeveloperOperator"])
    closing = db["closings"].get(rid)
    # Priority 2 (ownership) for the entity-backed BuilderRep
    if caller.role == "BuilderRep" and closing is not None:
        check_builder_ownership(caller, db["agreements"].get(closing["agreement_id"]))
    if closing is None:
        require_path("closings", rid)
    if closing["status"] != "PENDING":
        raise_error(ERR_CLOSING_INVALID_STATE, "cancel requires PENDING")
    closing["status"] = "CANCELLED"
    touch(closing)
    # The reservation stands: sales returns to RESERVED, lien re-encumbered
    lot = db["lots"][closing["lot_id"]]
    lot["sales_status"] = "RESERVED"
    lot["lien_status"] = "ENCUMBERED"
    touch(lot)
    return success_object(public(closing))
