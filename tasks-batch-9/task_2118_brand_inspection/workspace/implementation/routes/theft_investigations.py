"""Theft caseload: referral, closing and the single permitted reopen."""

from flask import Blueprint, request

from db import by_created_at, db, touch
from errors import ApiError
from middleware import caller_id, endpoint
from response import object_response, paginate
from routes import lookup
from services import aggregates, cascades, constants as C
from validation import INVESTIGATION_OUTCOMES, body, req_enum, req_str

bp = Blueprint("theft_investigations", __name__)

READ_ROLES = ("TheftInvestigator", "BoardAdmin", "FieldInspector")


@bp.get("/theft-investigations/<investigation_id>")
@endpoint(*READ_ROLES)
def read_investigation(investigation_id):
    return object_response(lookup.investigation(investigation_id))


@bp.get("/theft-investigations")
@endpoint(*READ_ROLES)
def list_investigations():
    rows = lookup.filtered(
        db.investigations,
        {
            "animal_lot_id": request.args.get("animal_lot_id"),
            "brand_registration_id": request.args.get("brand_registration_id"),
            "status": request.args.get("status"),
        },
    )
    return paginate(by_created_at(rows))


def _parent_order(investigation):
    lot = db.lots.get(investigation["animal_lot_id"])
    if lot is None:
        return None
    return db.orders.get(lot["inspection_order_id"])


@bp.post("/theft-investigations/<investigation_id>/refer")
@endpoint("TheftInvestigator")
def refer_investigation(investigation_id):
    payload = body()
    referral_agency = req_str(payload, "referral_agency")

    investigation = lookup.investigation(investigation_id)
    if investigation["status"] != "OPENED":
        raise ApiError("ERR_INVESTIGATION_INVALID_STATE", "The case is not open for referral.")

    investigation["status"] = "REFERRED"
    investigation["referral_agency"] = referral_agency
    touch(investigation)
    return object_response(investigation)


@bp.post("/theft-investigations/<investigation_id>/close")
@endpoint("TheftInvestigator")
def close_investigation(investigation_id):
    payload = body()
    outcome = req_enum(payload, "outcome", INVESTIGATION_OUTCOMES)

    investigation = lookup.investigation(investigation_id)
    if investigation["status"] not in C.OPEN_INVESTIGATION_STATUSES:
        raise ApiError("ERR_INVESTIGATION_INVALID_STATE", "The case is already closed.")

    investigation["status"] = "CLOSED"
    investigation["outcome"] = outcome
    investigation["closed_by_user_id"] = caller_id()
    touch(investigation)

    registration = db.registrations.get(investigation["brand_registration_id"])
    if registration is not None:
        changed = aggregates.recompute_encumbrance(registration)
        if outcome == "UNFOUNDED":
            if registration["encumbrance_count"] == 0 and registration["status"] == "ENCUMBERED":
                registration["status"] = "ACTIVE"
                touch(registration)
                cascades.release_held_filings(registration)
            elif changed:
                touch(registration)
        else:
            if registration["status"] == "ENCUMBERED":
                cascades.revoke_registration_and_cascade(registration, unschedule=False)
            elif changed:
                touch(registration)

    order = _parent_order(investigation)
    if order is not None:
        cascades.recompute_order_hold(order)

    return object_response(investigation)


@bp.post("/theft-investigations/<investigation_id>/reopen")
@endpoint("TheftInvestigator")
def reopen_investigation(investigation_id):
    investigation = lookup.investigation(investigation_id)
    if investigation["status"] != "CLOSED":
        raise ApiError("ERR_INVESTIGATION_INVALID_STATE", "Only a closed case may be reopened.")
    if investigation["reopen_count"] >= C.MAX_REOPENS:
        raise ApiError("ERR_INVESTIGATION_INVALID_STATE", "The case has already been reopened once.")

    registration = db.registrations.get(investigation["brand_registration_id"])
    if registration is None or registration["status"] not in ("ACTIVE", "GRACE", "ENCUMBERED"):
        raise ApiError("ERR_REGISTRATION_INVALID_STATE", "The record can no longer be encumbered.")

    investigation["status"] = "OPENED"
    investigation["reopen_count"] += 1
    investigation["outcome"] = "PENDING"
    touch(investigation)

    aggregates.recompute_encumbrance(registration)
    if registration["status"] in C.REGISTRATION_GROUP_STATUSES:
        registration["status"] = "ENCUMBERED"
    touch(registration)

    order = _parent_order(investigation)
    if order is not None:
        cascades.set_order_hold(order, True)

    return object_response(investigation)
