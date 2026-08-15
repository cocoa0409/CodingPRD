"""TakedownAgreement endpoints (PRD 3.4, 3.7): pricing terms, default/cure cycle."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_AGREEMENT_INVALID_STATE,
    ERR_AGREEMENT_NOT_BEHIND_SCHEDULE,
    ERR_PARCEL_NOT_ACQUIRED,
    ERR_STALE_AGREEMENT_VERSION,
)
from middleware import authorized, check_builder_ownership
from response import success_object
from routes.helpers import get_one, list_response, public
from services import calculations as calc
from services.cascades import lot_release_cascade
from services.core import new_record, touch
from util import CLOCK, parse_dt
from validate import (
    check_body_fk_exists,
    get_body,
    opt_int,
    req_datetime,
    req_int,
    req_str,
    require_path,
)

bp = Blueprint("agreements", __name__)


@bp.post("/takedown-agreements")
def create_agreement():
    authorized(["DeveloperOperator"])
    body = get_body()
    # Priority 3: body FK existence in declared order (parcel_id, builder_id)
    check_body_fk_exists("parcels", body, "parcel_id")
    check_body_fk_exists("builders", body, "builder_id")
    # Priority 4: shape
    rec = new_record("agreements", {
        "parcel_id": req_str(body, "parcel_id"),
        "builder_id": req_str(body, "builder_id"),
        "effective_date": req_datetime(body, "effective_date"),
        "base_lot_price_cents": req_int(body, "base_lot_price_cents", minimum=1),
        "escalator_rate_bp_per_quarter": req_int(body, "escalator_rate_bp_per_quarter", non_negative=True),
        "price_cap_bp": req_int(body, "price_cap_bp", minimum=10000),
        "min_lots_per_quarter": req_int(body, "min_lots_per_quarter", minimum=1),
        "scheduled_lot_count": req_int(body, "scheduled_lot_count", minimum=1),
        "closed_lot_count": 0,
        "default_reason": None,
        "status": "DRAFT",
    })
    return success_object(public(rec), status=201)


@bp.get("/takedown-agreements")
def list_agreements():
    return list_response("agreements", {
        "parcel_id": request.args.get("parcel_id"),
        "builder_id": request.args.get("builder_id"),
        "status": request.args.get("status"),
    })


@bp.get("/takedown-agreements/<rid>")
def get_agreement(rid):
    return get_one("agreements", rid)


@bp.post("/takedown-agreements/<rid>/activate")
def activate_agreement(rid):
    authorized(["DeveloperOperator"])
    agreement = require_path("agreements", rid)
    if agreement["status"] != "DRAFT":
        raise_error(ERR_AGREEMENT_INVALID_STATE, "activate requires DRAFT")
    # Priority 10 (referential)
    parcel = db["parcels"].get(agreement["parcel_id"])
    if parcel is None or parcel["status"] != "ACQUIRED":
        raise_error(ERR_PARCEL_NOT_ACQUIRED, "agreement activation requires parcel ACQUIRED")
    agreement["status"] = "ACTIVE"
    touch(agreement)
    return success_object(public(agreement))


@bp.post("/takedown-agreements/<rid>/amend")
def amend_agreement(rid):
    caller = authorized(["DeveloperOperator", "BuilderRep"])
    agreement = db["agreements"].get(rid)
    # Priority 2 (ownership) — evaluated when the target resolves
    check_builder_ownership(caller, agreement)
    # Priority 3 (existence)
    if agreement is None:
        require_path("agreements", rid)
    body = get_body()
    # Priority 4 (shape): expected version is non-optional (PRD 2.7)
    expected = req_int(body, "expected_agreement_version")
    base = opt_int(body, "base_lot_price_cents", None, minimum=1)
    escalator = opt_int(body, "escalator_rate_bp_per_quarter", None, non_negative=True)
    cap = opt_int(body, "price_cap_bp", None, minimum=10000)
    min_lots = opt_int(body, "min_lots_per_quarter", None, minimum=1)
    # Priority 5 (OCC) — before the state check (PRD 2.8)
    if expected != agreement["version"]:
        raise_error(ERR_STALE_AGREEMENT_VERSION,
                    "expected_agreement_version does not match TakedownAgreement.version")
    # Priority 6 (state)
    if agreement["status"] != "ACTIVE":
        raise_error(ERR_AGREEMENT_INVALID_STATE, "amend requires ACTIVE")
    if base is not None:
        agreement["base_lot_price_cents"] = base
    if escalator is not None:
        agreement["escalator_rate_bp_per_quarter"] = escalator
    if cap is not None:
        agreement["price_cap_bp"] = cap
    if min_lots is not None:
        agreement["min_lots_per_quarter"] = min_lots
    touch(agreement)
    return success_object(public(agreement))


@bp.post("/takedown-agreements/<rid>/declare-default")
def declare_default(rid):
    authorized(["DeveloperOperator"])
    agreement = require_path("agreements", rid)
    body = get_body()
    reason = req_str(body, "reason")
    if agreement["status"] != "ACTIVE":
        raise_error(ERR_AGREEMENT_INVALID_STATE, "declare-default requires ACTIVE")
    # Priority 10 (referential): behind-schedule check on completed quarters
    q = calc.quarters_elapsed(parse_dt(agreement["effective_date"]), CLOCK.now())
    if not (agreement["closed_lot_count"] < q * agreement["min_lots_per_quarter"]):
        raise_error(ERR_AGREEMENT_NOT_BEHIND_SCHEDULE,
                    "closed_lot_count meets the elapsed-quarter schedule")
    lot_release_cascade(agreement)
    agreement["default_reason"] = reason
    agreement["status"] = "DEFAULTED"
    touch(agreement)
    return success_object(public(agreement))


@bp.post("/takedown-agreements/<rid>/cure")
def cure_agreement(rid):
    authorized(["DeveloperOperator"])
    agreement = require_path("agreements", rid)
    body = get_body()
    req_str(body, "cure_note")  # carried for the record
    if agreement["status"] != "DEFAULTED":
        raise_error(ERR_AGREEMENT_INVALID_STATE, "cure requires DEFAULTED")
    # Released lots are NOT re-reserved; the builder must reserve anew
    agreement["default_reason"] = None
    agreement["status"] = "ACTIVE"
    touch(agreement)
    return success_object(public(agreement))


@bp.post("/takedown-agreements/<rid>/terminate")
def terminate_agreement(rid):
    authorized(["DeveloperOperator"])
    agreement = require_path("agreements", rid)
    if agreement["status"] not in ("ACTIVE", "DEFAULTED"):
        raise_error(ERR_AGREEMENT_INVALID_STATE, "terminate requires ACTIVE or DEFAULTED")
    lot_release_cascade(agreement)
    agreement["status"] = "TERMINATED"
    touch(agreement)
    return success_object(public(agreement))
