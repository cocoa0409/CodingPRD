"""CreditFreeze routes."""
from __future__ import annotations

import secrets
import string

from flask import Blueprint

from ..auth import enforce_consumer_ownership, require_auth
from ..calculations import recompute_posture_for_consumer_bureau
from ..clock import clock
from ..errors import ApiError
from ..responses import json_object
from ..store import stamp_create, stamp_update, store
from ..utils import check_occ, parse_json_body, require_field


bp_credit_freezes = Blueprint("credit_freezes", __name__)

VALID_BUREAUS = {"EQUIFAX", "EXPERIAN", "TRANSUNION"}


def _mint_pin() -> str:
    """Issue an 8-character numeric PIN."""
    return "".join(secrets.choice(string.digits) for _ in range(8))


@bp_credit_freezes.route("/consumers/<consumer_id>/credit_freezes", methods=["POST"])
@require_auth(["Consumer"])
def place_freeze(consumer_id: str):
    enforce_consumer_ownership(consumer_id)
    consumer = store.consumers.get(consumer_id)
    if consumer is None:
        raise ApiError("ERR_NOT_FOUND", "Consumer not found.", 404)
    body = parse_json_body()
    bureau = require_field(body, "bureau", types=[str])
    if bureau not in VALID_BUREAUS:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            f"bureau must be one of {sorted(VALID_BUREAUS)}.",
            400,
        )
    with store.lock:
        # Priority 18: unique-active per (consumer, bureau).
        for existing in store.credit_freezes.values():
            if (
                existing["consumer_id"] == consumer_id
                and existing["bureau"] == bureau
                and existing["status"] == "ACTIVE"
            ):
                raise ApiError(
                    "ERR_FREEZE_ALREADY_ACTIVE",
                    "An ACTIVE CreditFreeze already exists for this (consumer, bureau).",
                    409,
                )
        # Mint a PIN on the first freeze across any bureau, persistent forever after.
        if consumer.get("freeze_pin") is None:
            consumer["freeze_pin"] = _mint_pin()
            stamp_update(consumer)
        freeze = stamp_create(
            {
                "consumer_id": consumer_id,
                "bureau": bureau,
                "placed_day": clock.day,
                "lifted_day": None,
                "status": "ACTIVE",
            }
        )
        store.credit_freezes[freeze["id"]] = freeze
        recompute_posture_for_consumer_bureau(consumer_id, bureau)
    return json_object(freeze, 201)


@bp_credit_freezes.route(
    "/consumers/<consumer_id>/credit_freezes/<freeze_id>", methods=["GET"]
)
@require_auth(["Consumer", "PlatformAdmin"])
def get_freeze(consumer_id: str, freeze_id: str):
    enforce_consumer_ownership(consumer_id)
    consumer = store.consumers.get(consumer_id)
    if consumer is None:
        raise ApiError("ERR_NOT_FOUND", "Consumer not found.", 404)
    freeze = store.credit_freezes.get(freeze_id)
    if freeze is None or freeze["consumer_id"] != consumer_id:
        raise ApiError("ERR_NOT_FOUND", "CreditFreeze not found.", 404)
    return json_object(freeze, 200)


@bp_credit_freezes.route(
    "/consumers/<consumer_id>/credit_freezes/<freeze_id>/lift", methods=["POST"]
)
@require_auth(["Consumer"])
def lift_freeze(consumer_id: str, freeze_id: str):
    enforce_consumer_ownership(consumer_id)
    consumer = store.consumers.get(consumer_id)
    if consumer is None:
        raise ApiError("ERR_NOT_FOUND", "Consumer not found.", 404)
    freeze = store.credit_freezes.get(freeze_id)
    if freeze is None or freeze["consumer_id"] != consumer_id:
        raise ApiError("ERR_NOT_FOUND", "CreditFreeze not found.", 404)
    body = parse_json_body()
    with store.lock:
        check_occ(freeze, body)
        if freeze["status"] != "ACTIVE":
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "Only ACTIVE freezes may be lifted.",
                409,
            )
        # Priority 15: PIN check.
        pin = body.get("pin")
        if not isinstance(pin, str) or consumer.get("freeze_pin") is None or pin != consumer["freeze_pin"]:
            raise ApiError(
                "ERR_INVALID_FREEZE_PIN",
                "Supplied PIN is invalid.",
                403,
            )
        freeze["status"] = "LIFTED"
        freeze["lifted_day"] = clock.day
        stamp_update(freeze)
        recompute_posture_for_consumer_bureau(consumer_id, freeze["bureau"])
    return json_object(freeze, 200)
