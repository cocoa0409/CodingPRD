"""Peer group endpoints (PRD §3.1)."""

from flask import Blueprint

import calc
import config as C
import envelope
import models
import services
import validators
from auth import authenticate
from errors import ApiError
from routes.common import listing, need
from store import db, ordered

bp = Blueprint("peer_groups", __name__)

READ_ROLES = (C.ROLE_ANALYST, C.ROLE_SUPERVISOR, C.ROLE_INVESTIGATOR)


@bp.post("/peer-groups")
def create_peer_group():
    authenticate(C.ROLE_SUPERVISOR)
    payload = validators.body()
    code = validators.req_string(payload, "code", max_len=32)
    store_type = validators.req_enum(payload, "store_type", C.STORE_TYPES)
    min_cents = validators.req_int(payload, "min_monthly_redemption_cents", minimum=0)
    if "max_monthly_redemption_cents" not in payload:
        raise validators.invalid("Field 'max_monthly_redemption_cents' is required.")
    max_cents = payload["max_monthly_redemption_cents"]
    if max_cents is not None:
        max_cents = validators.req_int(
            payload, "max_monthly_redemption_cents", minimum=min_cents
        )
    mar_method = validators.req_enum(payload, "mar_method", C.MAR_METHODS)
    allowance = calc.dec(
        validators.req_number(payload, "competitive_allowance_pct", minimum=0, maximum=0.25)
    )
    min_subs = validators.opt_int(
        payload, "min_submissions_for_ceiling", default=3, minimum=1
    )
    multiplier = calc.dec(
        validators.req_number(payload, "min_stock_multiplier", minimum=0.5, maximum=3.0)
    )

    for existing in db.peer_groups.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_PEER_GROUP_CODE")

    record = models.peer_group(
        code=code,
        store_type=store_type,
        min_monthly_redemption_cents=min_cents,
        max_monthly_redemption_cents=max_cents,
        mar_method=mar_method,
        competitive_allowance_pct=allowance,
        min_submissions_for_ceiling=min_subs,
        min_stock_multiplier=multiplier,
    )
    db.peer_groups[record["id"]] = record
    return envelope.success(record, 201)


@bp.get("/peer-groups/<entity_id>")
def read_peer_group(entity_id):
    authenticate(*READ_ROLES)
    return envelope.success(need(db.peer_groups, entity_id, "ERR_PEER_GROUP_NOT_FOUND"))


@bp.get("/peer-groups")
def list_peer_groups():
    authenticate(*READ_ROLES)
    return listing(
        ordered(db.peer_groups),
        {"store_type": "store_type", "status": "status"},
    )


@bp.post("/peer-groups/<entity_id>/retire")
def retire_peer_group(entity_id):
    authenticate(C.ROLE_SUPERVISOR)
    peer_group = need(db.peer_groups, entity_id, "ERR_PEER_GROUP_NOT_FOUND")
    if peer_group["status"] == "ACTIVE":
        services.retire_peer_group(peer_group)
    return envelope.success(peer_group)
