"""Enforcement-action read + lift routes — PRD §3.8."""

from flask import Blueprint

import calc
import config
import domain
import serialize
import store
import validate as V
from auth import authenticate
from envelope import array_response, send, watch
from errors import ApiError

bp = Blueprint("enforcement", __name__)

READ_ROLES = ["HealthOfficer", "Inspector", "RecordsClerk", "EstablishmentOperator"]


@bp.get("/body-art/enforcement-actions/<enforcement_action_id>")
def read_enforcement_action(enforcement_action_id):
    authenticate(READ_ROLES)
    rec = V.get_enforcement_action(enforcement_action_id)
    return send(lambda: serialize.enforcement_action(rec), 200)


@bp.get("/body-art/enforcement-actions")
def list_enforcement_actions():
    authenticate(READ_ROLES)
    limit, offset = V.pagination()
    establishment_id = V.filter_string("establishment_id")
    artist_id = V.filter_string("artist_id")
    subject_type = V.filter_enum("subject_type", config.ENFORCEMENT_SUBJECT_TYPES)
    status = V.filter_enum("status", config.ENFORCEMENT_STATUSES)

    rows = store.sorted_rows(store.enforcement_actions)
    if establishment_id is not None:
        rows = [r for r in rows if r["establishment_id"] == establishment_id]
    if artist_id is not None:
        rows = [r for r in rows if r["artist_id"] == artist_id]
    if subject_type is not None:
        rows = [r for r in rows if r["subject_type"] == subject_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = V.paginate(rows, limit, offset)
    return array_response(
        [serialize.enforcement_action(r) for r in page], limit, offset, total
    )


@bp.post("/body-art/enforcement-actions/<enforcement_action_id>/lift")
def lift_enforcement_action(enforcement_action_id):
    caller = authenticate(["HealthOfficer"])
    rec = V.get_enforcement_action(enforcement_action_id)

    # PRD §3.8: segregation of duties, then state, then liftability.
    if caller.user_id == rec["issued_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_ENFORCEMENT_STATE_INVALID")
    if rec["action_type"] != "SUSPENSION":
        raise ApiError("ERR_ENFORCEMENT_NOT_LIFTABLE")

    lift_instant = store.now()
    suspension_days, base_cents, admin_fee, total = calc.reinstatement_penalty(
        rec["issued_at"], lift_instant
    )

    watch(rec)
    rec["status"] = "LIFTED"
    rec["lifted_by_user_id"] = caller.user_id
    rec["lifted_at"] = lift_instant
    rec["suspension_days"] = suspension_days
    rec["reinstatement_base_cents"] = base_cents
    rec["reinstatement_admin_fee_cents"] = admin_fee
    rec["reinstatement_total_cents"] = total

    if rec["subject_type"] == "ESTABLISHMENT":
        est = store.establishments.get(rec["establishment_id"])
        if est is not None:
            domain.reinstate_establishment(est, rec["id"])
    else:
        artist = store.artists.get(rec["artist_id"])
        if artist is not None:
            est = store.establishments.get(artist["establishment_id"])
            domain.reinstate_artist(artist, est)

    return send(lambda: serialize.enforcement_action(rec), 200)
