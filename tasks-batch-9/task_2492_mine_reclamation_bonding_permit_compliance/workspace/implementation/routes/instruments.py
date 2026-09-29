"""Bond instruments: proposal, credited value and substitution (PRD 3.3)."""

from flask import Blueprint

import calculations as calc
import constants as C
import engine
import serialization as ser
from db import D, ZERO, base_row, db, now
from engine import bump
from errors import ApiError
from response import created_response, object_response
from routes._shared import (
    collection_filtered,
    require_permit_operator,
    require_permit_status,
    require_state,
)
from validation import (
    authorize,
    enum_field,
    get_body,
    lookup,
    number_field,
    resolve,
    str_field,
)

bp = Blueprint("instruments", __name__)

LIST_FILTERS = [
    ("permit_id", "permit_id", None),
    ("replaces_instrument_id", "replaces_instrument_id", None),
    ("status", "status", C.INSTRUMENT_STATUSES),
    ("instrument_type", "instrument_type", C.INSTRUMENT_TYPES),
]

SURETY_GROUP = ("surety_company_name", "surety_naic_rating")
COLLATERAL_GROUP = ("collateral_type", "collateral_market_value")


def _check_shape(instrument_type, surety_name, surety_rating, coll_type, coll_value):
    """Band 13 — the type-conditional detail groups (ERR_COLLATERAL_DETAILS_REQUIRED)."""
    has_surety = surety_name is not None or surety_rating is not None
    has_collateral = coll_type is not None or coll_value is not None

    if instrument_type == "SURETY":
        ok = surety_name is not None and surety_rating is not None and not has_collateral
    elif instrument_type == "COLLATERAL":
        ok = coll_type is not None and coll_value is not None and not has_surety
    else:
        ok = not has_surety and not has_collateral

    if not ok:
        raise ApiError(
            "ERR_COLLATERAL_DETAILS_REQUIRED",
            "The supplied detail fields do not match the declared instrument_type.",
        )


@bp.post("/mining/bond-instruments")
def create_instrument():
    user_id, role = authorize([C.ROLE_OPERATOR])
    body = get_body()
    permit_id = str_field(body, "permit_id")
    instrument_type = enum_field(body, "instrument_type", C.INSTRUMENT_TYPES)
    face_amount = number_field(body, "face_amount", gt=0)
    surety_company_name = str_field(body, "surety_company_name", required=False)
    surety_naic_rating = enum_field(body, "surety_naic_rating", C.SURETY_RATINGS, required=False)
    collateral_type = enum_field(body, "collateral_type", C.COLLATERAL_TYPES, required=False)
    collateral_market_value = number_field(body, "collateral_market_value", required=False, ge=0)
    replaces_instrument_id = str_field(body, "replaces_instrument_id", required=False)

    # Band 5 — permit first, then the substitution target.
    permit = resolve(db.permits, permit_id, "ERR_PERMIT_NOT_FOUND")
    resolve(db.instruments, replaces_instrument_id, "ERR_INSTRUMENT_NOT_FOUND")

    # Band 6, then band 10.
    require_permit_operator(role, user_id, permit)
    require_permit_status(permit, C.PERMIT_STATUSES_INSTRUMENT)

    # Band 13.
    _check_shape(
        instrument_type,
        surety_company_name,
        surety_naic_rating,
        collateral_type,
        collateral_market_value,
    )

    row = base_row()
    row.update(
        {
            "permit_id": permit_id,
            "instrument_type": instrument_type,
            "face_amount": face_amount,
            "surety_company_name": surety_company_name,
            "surety_naic_rating": surety_naic_rating,
            "collateral_type": collateral_type,
            "collateral_market_value": collateral_market_value,
            "replaces_instrument_id": replaces_instrument_id,
            "credited_amount": ZERO,
            "status": "PROPOSED",
            "accepted_by_user_id": None,
            "accepted_at": None,
        }
    )
    db.instruments[row["id"]] = row
    return created_response(ser.instrument_out(row))


@bp.get("/mining/bond-instruments/<instrument_id>")
def get_instrument(instrument_id):
    authorize(C.ROLES_OP_STAFF)
    row = lookup(db.instruments, instrument_id, "ERR_INSTRUMENT_NOT_FOUND")
    return object_response(ser.instrument_out(row))


@bp.get("/mining/bond-instruments")
def list_instruments():
    authorize(C.ROLES_OP_STAFF)
    return collection_filtered(db.instruments.values(), LIST_FILTERS, ser.instrument_out)


@bp.post("/mining/bond-instruments/<instrument_id>/accept")
def accept_instrument(instrument_id):
    user_id, role = authorize([C.ROLE_BOND_SPECIALIST])
    get_body()

    instrument = lookup(db.instruments, instrument_id, "ERR_INSTRUMENT_NOT_FOUND")
    permit = db.permits[instrument["permit_id"]]
    operator = db.operators.get(permit["operator_id"])

    # Band 9, then band 10.
    require_state(instrument, "status", ["PROPOSED"], "ERR_INSTRUMENT_STATE_INVALID")
    require_permit_status(permit, C.PERMIT_STATUSES_INSTRUMENT)

    # Band 13 — a `B` rating is writable but not acceptable.
    if instrument["instrument_type"] == "SURETY":
        if instrument["surety_naic_rating"] not in C.ELIGIBLE_SURETY_RATINGS:
            raise ApiError(
                "ERR_SURETY_RATING_INELIGIBLE",
                "The surety's NAIC rating is not acceptable as financial security.",
            )

    # Band 14 — the substitution target.
    target = None
    if instrument["replaces_instrument_id"] is not None:
        target = db.instruments.get(instrument["replaces_instrument_id"])
        valid = (
            target is not None
            and target["permit_id"] == permit["id"]
            and target["status"] in ("ACCEPTED", "SUBSTITUTION_REQUIRED")
        )
        if valid:
            for other in db.instruments.values():
                if (
                    other["id"] != instrument["id"]
                    and other["replaces_instrument_id"] == target["id"]
                    and other["status"] == "ACCEPTED"
                ):
                    valid = False
                    break
        if not valid:
            raise ApiError(
                "ERR_SUBSTITUTION_TARGET_INVALID",
                "The instrument named by replaces_instrument_id cannot be substituted for.",
            )

    # Band 14 — self-bonding standing.
    if instrument["instrument_type"] == "SELF_BOND":
        if operator is None or operator["self_bond_status"] != "QUALIFIED":
            raise ApiError(
                "ERR_SELF_BOND_NOT_QUALIFIED",
                "The operator is not qualified to post a self-bond.",
            )
        # Band 15 — statewide self-bonding capacity.
        if D(instrument["face_amount"]) > calc.self_bond_headroom(operator):
            raise ApiError(
                "ERR_SELF_BOND_CAPACITY_EXCEEDED",
                "The self-bond exceeds the operator's remaining self-bonding headroom.",
            )

    instrument["credited_amount"] = calc.instrument_credited_amount(instrument, operator)
    instrument["status"] = "ACCEPTED"
    instrument["accepted_by_user_id"] = user_id
    instrument["accepted_at"] = now()
    bump(instrument)

    if target is not None:
        target["status"] = "REPLACED"
        bump(target)

    engine.refresh_bond_ledger(permit)
    engine.recompute_posture(permit)
    bump(permit)

    return object_response(ser.instrument_out(instrument))
